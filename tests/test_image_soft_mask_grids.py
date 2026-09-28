"""Small, source-grid oracles; these tests do not launch a CAD host."""
from __future__ import annotations

import json
from types import SimpleNamespace

import ezdxf
import numpy as np
import pytest

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from librecad_pdf_importer.core import image_soft_mask
from librecad_pdf_importer.core.document import ExtractionOptions, _extract_images
from librecad_pdf_importer.core.image_soft_mask import align_image_soft_mask
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import, write_import_report


def make_pdf(image_size=(2, 1), mask_size=(3, 1), *, decode=None, colorspace="DeviceRGB"):
    doc = fitz.open()
    page = doc.new_page(width=80, height=80)
    channels = {"DeviceGray": 1, "DeviceRGB": 3, "DeviceCMYK": 4}[colorspace]
    image_samples = bytes((i * 37 + 17) % 256 for i in range(np.prod(image_size) * channels))
    mask_samples = bytes((0, 128, 255)[i % 3] for i in range(np.prod(mask_size)))

    def add_image(size, space, data):
        xref = doc.get_new_xref()
        doc.update_object(xref, f"<< /Type /XObject /Subtype /Image /Width {size[0]} "
                          f"/Height {size[1]} /ColorSpace /{space} /BitsPerComponent 8 >>")
        doc.update_stream(xref, data)
        return xref

    image_xref = add_image(image_size, colorspace, image_samples)
    mask_xref = add_image(mask_size, "DeviceGray", mask_samples)
    doc.xref_set_key(image_xref, "SMask", f"{mask_xref} 0 R")
    if decode:
        doc.xref_set_key(mask_xref, "Decode", decode)
    resources = doc.get_new_xref()
    doc.update_object(resources, f"<< /XObject << /Im {image_xref} 0 R >> >>")
    doc.xref_set_key(page.xref, "Resources", f"{resources} 0 R")
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, b"q 24 6 -9 30 20 12 cm /Im Do Q")
    page.set_contents(content)
    return doc, image_xref, mask_xref


def array(pix):
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


@pytest.mark.parametrize("image_size,mask_size,space", [
    ((2, 1), (3, 1), "DeviceRGB"),
    ((3, 2), (2, 3), "DeviceRGB"),
    ((15, 15), (41, 41), "DeviceGray"),
    ((2, 1), (3, 1), "DeviceCMYK"),
])
def test_alignment_preserves_every_color_and_alpha_cell(image_size, mask_size, space):
    with make_pdf(image_size, mask_size, colorspace=space)[0] as doc:
        image_xref, mask_xref = doc[0].get_images(full=True)[0][:2]
        original, original_mask = fitz.Pixmap(doc, image_xref), fitz.Pixmap(doc, mask_xref)
        color, mask = align_image_soft_mask(doc, image_xref, mask_xref, original, original_mask)
        assert color.width == mask.width == np.lcm(image_size[0], mask_size[0])
        assert color.height == mask.height == np.lcm(image_size[1], mask_size[1])
        # Independent oracle: normalized output cell centers map to their
        # original cells. This catches a resize-to-max implementation.
        for aligned, source in ((color, original), (mask, original_mask)):
            y = np.arange(aligned.height) * source.height // aligned.height
            x = np.arange(aligned.width) * source.width // aligned.width
            np.testing.assert_array_equal(array(aligned), array(source)[y[:, None], x])
        assert color.colorspace.n == original.colorspace.n
        composed = fitz.Pixmap(color, mask)
        assert composed.alpha
        np.testing.assert_array_equal(array(composed)[:, :, -1], array(mask)[:, :, 0])


def test_inverted_decode_partial_alpha_png_and_affine_placement(tmp_path):
    doc, image_xref, mask_xref = make_pdf(decode="[1 0]")
    with doc:
        page = doc[0]
        original_rect, original_ctm = page.get_image_rects(image_xref, transform=True)[0]
        placements = _extract_images(doc, page, 1, ExtractionOptions(), tmp_path)
        assert len(placements) == 1
        placement = placements[0]
        assert placement.pixel_size == (6, 1)
        assert placement.affine_pdf == pytest.approx(tuple(original_ctm))
        assert placement.source_bbox_pdf == pytest.approx(tuple(original_rect))
        assert placement.alpha_present
        png = fitz.Pixmap(placement.path)
        # Decode was applied by MuPDF, once, before exact cell replication.
        assert array(png)[0, :, -1].tolist() == [255, 255, 127, 127, 0, 0]
        original = fitz.Pixmap(doc, image_xref)
        # PNG decode returns premultiplied RGB: check partial alpha against
        # the original color, allowing one byte for PNG un/premultiply roundoff.
        source = array(original)[0]
        for x, alpha in enumerate((255, 255, 127, 127, 0, 0)):
            expected = source[x // 3].astype(float) * alpha / 255
            assert np.max(np.abs(array(png)[0, x, :3].astype(float) - expected)) <= 1.1


@pytest.mark.parametrize("target,key,value,reason", [
    ("image", "Interpolate", "true", "interpolated unequal"),
    ("mask", "Interpolate", "true", "interpolated unequal"),
    ("mask", "Interpolate", "/Invalid", "PDF boolean"),
])
def test_unsupported_semantics_fail_without_saving_opaque_image(tmp_path, target, key, value, reason):
    doc, image_xref, mask_xref = make_pdf()
    with doc:
        doc.xref_set_key(image_xref if target == "image" else mask_xref, key, value)
        with pytest.raises(RuntimeError, match=reason):
            _extract_images(doc, doc[0], 1, ExtractionOptions(), tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("value", ["true", "false"])
def test_indirect_interpolate_is_resolved(value):
    doc, image_xref, mask_xref = make_pdf()
    with doc:
        indirect = doc.get_new_xref()
        doc.update_object(indirect, value)
        doc.xref_set_key(mask_xref, "Interpolate", f"{indirect} 0 R")
        color, mask = fitz.Pixmap(doc, image_xref), fitz.Pixmap(doc, mask_xref)
        if value == "true":
            with pytest.raises(ValueError, match="interpolated unequal"):
                align_image_soft_mask(doc, image_xref, mask_xref, color, mask)
        else:
            assert align_image_soft_mask(doc, image_xref, mask_xref, color, mask)[0].width == 6


def test_unequal_matte_grids_are_rejected_before_replication():
    doc, image_xref, mask_xref = make_pdf()
    with doc:
        color, mask = fitz.Pixmap(doc, image_xref), fitz.Pixmap(doc, mask_xref)
        doc.xref_set_key(mask_xref, "Matte", "[1 1 1]")
        with pytest.raises(ValueError, match="Matte requires matching"):
            align_image_soft_mask(doc, image_xref, mask_xref, color, mask)


@pytest.mark.parametrize("cycle", [True, False])
def test_indirect_metadata_cycles_and_depth_fail_closed(cycle):
    class IndirectValues:
        def xref_get_key(self, xref, key):
            return "xref", "1 0 R"

        def xref_object(self, xref, *, compressed):
            assert compressed
            return f"{1 if cycle else xref + 1} 0 R"

    with pytest.raises(ValueError, match="cyclic or excessive indirect Interpolate"):
        image_soft_mask._pdf_value(IndirectValues(), 1, "Interpolate")


def test_equal_size_keeps_existing_pixmaps_without_metadata_access():
    color = fitz.Pixmap(fitz.csRGB, 2, 1, b"\xff\x00\x00" * 2, False)
    mask = fitz.Pixmap(fitz.csGRAY, 2, 1, b"\x00\xff", False)
    assert align_image_soft_mask(None, 0, 0, color, mask) == (color, mask)


def test_row_padding_does_not_become_image_samples():
    pix = SimpleNamespace(width=2, height=2, n=1, stride=3, colorspace=fitz.csGRAY,
                          samples_mv=memoryview(bytes((10, 20, 99, 30, 40, 88))))
    expanded = image_soft_mask._repeat_cells(pix, 4, 2)
    assert expanded.samples == bytes((10, 10, 20, 20, 30, 30, 40, 40))


def test_unequal_grid_image_survives_serialized_dxf_and_report(tmp_path):
    source, output = tmp_path / "source.pdf", tmp_path / "output.dxf"
    report_path = tmp_path / "output_import_report.json"
    with make_pdf()[0] as doc:
        doc.save(source)
    run = run_import(str(source), mode="vector",
                     overrides={"pages": "1", "import_text": False, "raster_dpi": 72})
    try:
        image = run.extraction.pages[0].images[0]
        assert image.pixel_size == (6, 1) and image.alpha_present
        assert image.source_instance_count == 1
        export = export_to_dxf(run.extraction, str(output),
                              DxfExportOptions(include_text=False, provenance_opts=run.config))
        assert export.image_count == 1
        reopened = ezdxf.readfile(output)
        assert len(list(reopened.modelspace().query("IMAGE"))) == 1
        write_import_report(run, str(report_path))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["extra"]["result_status"] == "success"
        assert report["result"]["images"] == 1
        assert report["result"]["warnings"] == 0
        assert report["extra"]["image_delivery"]["source_instances"] == 1
        assert report["extra"]["image_delivery"]["placements"] == 1
        assert report["fallback"]["used"] is False
    finally:
        run.close()


@pytest.mark.parametrize("sizes,budget", [(((101, 1), (103, 1)), None),
                                          (((3, 2), (2, 3)), 1)])
def test_budget_fails_before_expansion(monkeypatch, sizes, budget):
    doc, image_xref, mask_xref = make_pdf(*sizes)
    with doc:
        if budget is not None:
            monkeypatch.setattr(image_soft_mask, "SOFT_MASK_MAX_WORK_BYTES", budget)
        def forbidden(*args):
            pytest.fail("grid expansion must not start beyond the bound")
        monkeypatch.setattr(image_soft_mask, "_repeat_cells", forbidden)
        with pytest.raises(ValueError, match="bounded extraction budget"):
            align_image_soft_mask(doc, image_xref, mask_xref,
                                  fitz.Pixmap(doc, image_xref), fitz.Pixmap(doc, mask_xref))

"""Raster pixels follow the source renderer's device lattice, not glyph fitting."""
from dataclasses import replace
from pathlib import Path

import ezdxf
import pymupdf as fitz
import pytest

from librecad_pdf_importer.importer import run_import
from librecad_pdf_importer.exporters import dxf_exporter as exporter
from librecad_pdf_importer.raster_geometry import raster_pixel_geometry


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("flip_y", [False, True])
@pytest.mark.parametrize("unit,scale", [(1.0, 1.0), (2.0, 1.75)])
def test_actual_source_pixel_corners_survive_reopen(tmp_path, rotation, flip_y, unit, scale):
    source = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        for _ in range(2):
            p = pdf.new_page(width=220, height=120)
            p.insert_text((31.13, 53.77), "13/16 x 1", fontsize=12.21)
            p.set_cropbox(fitz.Rect(20, 10, 200, 110))
            p.set_rotation(rotation)
            pdf.xref_set_key(p.xref, "UserUnit", str(unit))
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={
        "pages": "1-2", "user_scale": scale, "flip_y": flip_y, "text_mode": "raster"})
    # A source-text fitting correction is deliberately unrelated to page pixels.
    # Prior code moved and scaled the raster because it depended on this bbox.
    for page in run.extraction.pages:
        page.page_data.text_items = [replace(t, bbox=(1, 2, 3, 4))
                                     for t in page.page_data.text_items]
    target = tmp_path / "output.dxf"
    result = exporter.export_to_dxf(run.extraction, str(target), exporter.DxfExportOptions(
        include_images=False, text_mode="raster", page_arrangement="touch"))
    native = ezdxf.readfile(target)
    assert len(result.text_deliveries) == 2
    with fitz.open(source) as pdf:
        for index, delivery in enumerate(result.text_deliveries):
            evidence = delivery["attempts"][-1]["evidence"]
            p = pdf[index]
            dpi = evidence["raster_dpi"]
            pix = p.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72),
                               clip=fitz.Rect(evidence["source_clip_pdf"]),
                               colorspace=fitz.csRGB, alpha=False)
            assert Path(evidence["asset_path"]).read_bytes() == pix.tobytes("png")
            model_unit = 25.4/72*scale
            # Page stacking is a separate, explicit exporter operation.
            dy = -index * run.extraction.pages[0].page_data.height
            expected = []
            for x, y in ((pix.x, pix.y+pix.height), (pix.x+pix.width, pix.y+pix.height),
                         (pix.x+pix.width, pix.y), (pix.x, pix.y)):
                display_x, display_y = x*72/dpi, y*72/dpi
                expected.append((display_x*model_unit,
                                 ((p.rect.height-display_y) if flip_y else display_y)*model_unit+dy))
            image = native.entitydb[delivery["entity_handles"][0]]
            corners = []
            for i, j in ((0, 0), (pix.width, 0), (pix.width, pix.height), (0, pix.height)):
                point = image.dxf.insert + image.dxf.u_pixel*i + image.dxf.v_pixel*j
                corners.append(tuple(point)[:2])
            for actual, wanted in zip(corners, expected, strict=True):
                assert actual == pytest.approx(wanted, abs=1e-10)
            assert evidence["pixel_origin"] == [pix.x, pix.y]
            assert evidence["source_pixel_lattice_verified"] is True


def test_serialized_axis_reversal_is_rejected_even_when_lengths_match(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        p = pdf.new_page(width=220, height=120)
        p.insert_text((30, 50), "SOURCE")
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "raster"})
    original = exporter._reopen_candidate_for_verification

    def corrupted(*args, **kwargs):
        doc, auditor = original(*args, **kwargs)
        for image in doc.modelspace().query("IMAGE"):
            image.dxf.v_pixel = -image.dxf.v_pixel
        return doc, auditor

    monkeypatch.setattr(exporter, "_reopen_candidate_for_verification", corrupted)
    target = tmp_path / "output.dxf"
    result = exporter.export_to_dxf(run.extraction, str(target), exporter.DxfExportOptions(
        include_images=False, text_mode="raster"))
    # The reversed IMAGE is still rejected post-write; since the 2026-09-19 owner
    # decision that costs the item (one forced re-export, visible degraded TEXT),
    # not the sheet. The rejected raster never reaches the accepted DXF.
    delivery = result.text_deliveries[0]
    assert delivery["verified"] is False and delivery["degraded"] is True
    assert delivery["degrade_reason"].endswith("raster placement changed")
    assert delivery["attempts"][0]["strategy"] == "serialized_delivery_verification"
    assert delivery["final_representation"] == "text"
    native = ezdxf.readfile(target)
    assert [entity.dxftype() for entity in native.modelspace()] == ["TEXT"]
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.parametrize("origin,size,dpi,matrix", [
    ((0.5, 1), (2, 3), 300, (1, 0, 0, -1, 0, 100)),
    ((0, 1), (0, 3), 300, (1, 0, 0, -1, 0, 100)),
    ((0, 1), (2, 3), 0, (1, 0, 0, -1, 0, 100)),
    ((0, 1), (2, 3), 300, (1, 0, 0, 0, 0, 100)),
])
def test_invalid_pixel_or_page_frame_fails(origin, size, dpi, matrix):
    with pytest.raises(ValueError):
        raster_pixel_geometry(origin, size, dpi, matrix)

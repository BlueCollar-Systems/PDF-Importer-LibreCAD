"""Local source pixels retain gray Multiply detail and editable native ink."""
import hashlib

import ezdxf
import pymupdf as fitz
import pytest

from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.exporters import dxf_exporter as exporter


def prepare(tmp_path, *, text=False, flip_y=True):
    source = tmp_path/'multiply.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        page.draw_line((20, 0), (90, 70), color=(.2, .2, .2), width=1)
        if text:
            page.insert_text((56, 44), 'X', fontsize=8)
        resources = int(doc.xref_get_key(page.xref, 'Resources')[1].split()[0])
        doc.xref_set_key(resources, 'ExtGState', '<< /Mul << /Type /ExtGState /BM /Multiply /CA 1 /ca 1 >> >>')
        raw = page.read_contents()+b'\nq /Mul gs 1 .5 .25 RG 12 w 1 J 60 60 m 60.01 60 l S Q\n'
        xref = doc.get_new_xref()
        doc.update_object(xref, '<<>>')
        doc.update_stream(xref, raw)
        page.set_contents(xref)
        doc.save(source)
    return extract_document(str(source), options=ExtractionOptions(import_mode='vector', flip_y=flip_y))


@pytest.mark.parametrize('flip_y', [True, False])
def test_exact_final_source_pixels_and_page_lattice_survive_dxf(tmp_path, flip_y):
    extraction = prepare(tmp_path, flip_y=flip_y)
    try:
        assert len(extraction.pages[0].nontext_composites) == 1
        result = exporter.export_to_dxf(extraction, str(tmp_path/'out.dxf'), exporter.DxfExportOptions(
            include_images=False, include_text=False))
        assert len(result.nontext_composites) == 1
        record = result.nontext_composites[0]
        doc = ezdxf.readfile(result.output_path)
        hatch = doc.entitydb[record['canonical_hatch_handle']]
        assert hatch.dxftype() == 'HATCH'
        assert len(doc.modelspace().query('LINE')) == 2
        image = doc.entitydb[record['image_handle']]
        assert image == list(doc.modelspace())[-1]
        assert image.dxf.layer == 'P001_SOURCE_BLEND_DISPLAY'
        geom = record['pixel_geometry']
        assert tuple(image.dxf.insert)[:2] == pytest.approx(geom['image_insert'])
        assert tuple(image.dxf.u_pixel)[:2] == pytest.approx(geom['image_u_pixel'])
        assert tuple(image.dxf.v_pixel)[:2] == pytest.approx(geom['image_v_pixel'])
        pixel = fitz.Pixmap(record['asset_path'])
        recipe = record['recipe']
        with fitz.open(extraction.pdf_path) as pdf:
            source = pdf[0].get_pixmap(matrix=fitz.Matrix(600/72, 600/72),
                                      clip=fitz.Rect(recipe['coverage_bounds_pdf']), alpha=False)
            assert pixel.samples == source.samples
            assert [source.x, source.y, source.x+source.width, source.y+source.height] == recipe['device_bounds']
        assert hashlib.sha256(pixel.samples).hexdigest() == record['pixel_evidence']['rgb_sha256']
    finally:
        extraction.cleanup_temporary_assets()


def test_composite_never_borrows_text_even_when_text_export_disabled(tmp_path):
    extraction = prepare(tmp_path, text=True)
    assert not extraction.pages[0].nontext_composites
    result = exporter.export_to_dxf(extraction, str(tmp_path/'out.dxf'), exporter.DxfExportOptions(
        include_text=False, include_images=False))
    assert not result.nontext_composites
    assert not result.source_capsules  # No falsely opaque Multiply HATCH.
    extraction.cleanup_temporary_assets()


@pytest.mark.parametrize('change', ['axis', 'identity', 'fade', 'layer', 'transparent', 'z', 'axis_z'])
def test_changed_serialized_display_prevents_output_publication(tmp_path, monkeypatch, change):
    extraction = prepare(tmp_path)
    original = exporter._reopen_candidate_for_verification
    def corrupt(*args, **kwargs):
        doc, auditor = original(*args, **kwargs)
        image, = doc.modelspace().query('IMAGE')
        if change == 'axis':
            image.dxf.u_pixel = -image.dxf.u_pixel
        elif change == 'identity':
            image.set_xdata('BCS_NONTEXT_COMPOSITE', [(1000, '{}')])
        elif change == 'fade':
            image.dxf.fade = 95
        elif change == 'transparent':
            image.dxf.transparency = 33554559
        elif change == 'z':
            image.dxf.insert = (*tuple(image.dxf.insert)[:2], 50)
        elif change == 'axis_z':
            image.dxf.u_pixel = (*tuple(image.dxf.u_pixel)[:2], 1)
        else:
            doc.layers.get(image.dxf.layer).freeze()
        return doc, auditor
    monkeypatch.setattr(exporter, '_reopen_candidate_for_verification', corrupt)
    output = tmp_path/'out.dxf'
    with pytest.raises(RuntimeError):
        exporter.export_to_dxf(extraction, str(output), exporter.DxfExportOptions(include_text=False))
    assert not output.exists()
    extraction.cleanup_temporary_assets()


def test_changed_page_affine_cannot_move_display_away_from_canonical_ink(tmp_path):
    extraction = prepare(tmp_path)
    page = extraction.pages[0]
    mapping = list(page.display_to_model)
    mapping[4] += 10
    page.display_to_model = tuple(mapping)
    output = tmp_path/'out.dxf'
    with pytest.raises(RuntimeError, match='page mapping changed'):
        exporter.export_to_dxf(extraction, str(output), exporter.DxfExportOptions(include_text=False))
    assert not output.exists()
    extraction.cleanup_temporary_assets()

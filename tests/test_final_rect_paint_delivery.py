"""Delivery contract for paints whose source eligibility is tested separately."""
from pathlib import Path

import ezdxf
import pymupdf as fitz
import pytest

from librecad_pdf_importer.importer import run_import, write_import_report
from librecad_pdf_importer.exporters import dxf_exporter as exporter
from librecad_pdf_importer.exporters.final_rect_paint import render_uniform_source_paint


def prepared(tmp_path):
    source = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=120)
        page.draw_rect((15, 20, 80, 60), color=None, fill=(0, 0, 0))
        page.insert_text((25, 50), "SOURCE", fontsize=12)
        page.draw_rect((20, 30, 110, 55), color=(.01569, 1, 1), fill=(.01569, 1, 1),
                       width=2.16, fill_opacity=.300003)
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "raster"})
    page = run.extraction.pages[0]
    primitive = page.page_data.primitives[-1]
    xs, ys = zip(*primitive.points, strict=True)
    # Only the exporter seam is under test here. Source-state qualification has
    # its own parser/renderer tests; this is an explicit injected proof fixture.
    page.final_rect_paints = [{
        "primitive_id": primitive.id, "seqno": primitive.source_draw_order,
        "source_bbox_pdf": [20, 30, 110, 55],
        "model_bounds": [min(xs), min(ys), max(xs), max(ys)],
        "fill_rgb": list(primitive.source_fill_color), "fill_opacity": primitive.fill_opacity,
        "stroke_rgb": list(primitive.source_stroke_color), "stroke_width_pdf": 2.16,
        "stroke_width_model": primitive.line_width, "proof": {"test_seam": True},
    }]
    return run


@pytest.mark.parametrize("include_text", [False, True])
def test_paint_asset_and_source_stroke_survive_serialization(tmp_path, include_text):
    run = prepared(tmp_path)
    result = exporter.export_to_dxf(run.extraction, str(tmp_path/'out.dxf'), exporter.DxfExportOptions(
        include_text=include_text, include_images=False, text_mode="raster", provenance_opts=run.config))
    doc = ezdxf.readfile(result.output_path)
    assert len(result.final_rect_paints) == 1
    paint = result.final_rect_paints[0]
    image = doc.entitydb[paint['image_handle']]
    pix = fitz.Pixmap(paint['asset_path'])
    assert pix.alpha == 1
    assert bytes(pix.samples) == bytes(pix.samples[:4])*256
    entities = list(doc.modelspace())
    index = entities.index(image)
    assert entities[index+1].dxftype() == 'LWPOLYLINE'
    assert entities[index+1].closed
    # The original black vector fill remains below the translucent paint.
    assert entities[0].dxftype() == 'HATCH'
    if include_text:
        assert len(result.text_deliveries) == 1
        delivery = result.text_deliveries[0]
        assert delivery['final_representation'] == 'raster'
        assert entities[-1].dxf.handle == delivery['entity_handles'][0]
        evidence = delivery['attempts'][-1]['evidence']
        assert evidence['source_pixel_lattice_verified'] is True
        assert evidence['host_safe_opaque_image_verified'] is True
        assert not fitz.Pixmap(evidence['asset_path']).alpha
    write_import_report(run, str(tmp_path/'report.json'))
    assert run.config._final_rect_paint_deliveries == result.final_rect_paints
    assert Path(paint['asset_path']).is_relative_to(tmp_path)


@pytest.mark.parametrize("change", ['stroke', 'identity', 'image_axis', 'display', 'layer'])
def test_changed_serialized_paint_is_not_published(tmp_path, monkeypatch, change):
    run = prepared(tmp_path)
    original = exporter._reopen_candidate_for_verification

    def corrupted(*args, **kwargs):
        doc, auditor = original(*args, **kwargs)
        image = next(iter(doc.modelspace().query('IMAGE')))
        if change == 'identity':
            image.set_xdata('BCS_FINAL_RECT_PAINT', [(1000, '{}')])
        elif change == 'image_axis':
            image.dxf.u_pixel = -image.dxf.u_pixel
        elif change == 'display':
            image.dxf.fade = 90
        elif change == 'layer':
            doc.layers.get(image.dxf.layer).freeze()
        else:
            next(iter(doc.modelspace().query('LWPOLYLINE'))).dxf.lineweight = 5
        return doc, auditor

    monkeypatch.setattr(exporter, '_reopen_candidate_for_verification', corrupted)
    target = tmp_path/'out.dxf'
    with pytest.raises(RuntimeError, match='changed|hidden'):
        exporter.export_to_dxf(run.extraction, str(target), exporter.DxfExportOptions(
            include_text=False, include_images=False))
    assert not target.exists()


def test_source_renderer_alpha_quantization_matches_source_over():
    png, proof = render_uniform_source_paint((.01569, 1, 1), .300003)
    pix = fitz.Pixmap(png)
    assert proof['premultiplied_rgba8'] == [1, 75, 75, 75]
    assert list(pix.samples[:4]) == proof['premultiplied_rgba8']
    # This is the same source renderer result used by the independent native
    # alpha control; it deliberately differs from hand-rounded (4,255,255,77).

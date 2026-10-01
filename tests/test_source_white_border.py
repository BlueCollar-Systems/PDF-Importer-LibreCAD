"""A source white-filled annotation must not acquire a black printed border."""
import ezdxf
import pymupdf as fitz
import pytest

from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import


@pytest.mark.parametrize("stroke", [(1, 1, 1), (0, 0, 0), None])
def test_saved_source_white_rectangle_preserves_its_actual_border(tmp_path, stroke):
    source = tmp_path / "annotation-background.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(30, 30, 120, 80), color=stroke, fill=(1, 1, 1), width=1)
        doc.save(source)
    run = run_import(str(source), mode="vector", overrides={"import_text": False})
    primitive = run.extraction.pages[0].page_data.primitives[0]
    assert primitive.fill_color == (1, 1, 1)
    assert primitive.stroke_color == stroke
    output = tmp_path / "result.dxf"
    export_to_dxf(run.extraction, str(output), DxfExportOptions(include_text=False, include_images=False))
    reopened = ezdxf.readfile(output)
    outlines = list(reopened.modelspace().query("LWPOLYLINE"))
    fills = list(reopened.modelspace().query("HATCH"))
    assert len(fills) == 1 and fills[0].dxf.true_color == 0xFEFEFE
    if stroke is None:
        assert not outlines
    else:
        assert len(outlines) == 1 and outlines[0].closed
        assert outlines[0].dxf.lineweight == 35
        assert outlines[0].dxf.true_color == (0xFEFEFE if stroke == (1, 1, 1) else 0)
        if stroke == (1, 1, 1):
            assert outlines[0].dxf.color not in (0, 7, 256)
        points = list(outlines[0].get_points())
        assert min(p[0] for p in points) == pytest.approx(30 * 25.4 / 72)
        assert max(p[0] for p in points) == pytest.approx(120 * 25.4 / 72)

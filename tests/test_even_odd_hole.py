"""An even-odd fill with a hole stays one fill with an empty counter."""
from __future__ import annotations

import pymupdf
import ezdxf

from pdfcadcore.primitive_extractor import extract_page
from librecad_pdf_importer.exporters.dxf_exporter import export_to_dxf, DxfExportOptions
from librecad_pdf_importer.importer import run_import


def test_even_odd_rectangles_share_one_fill_and_keep_the_hole(tmp_path):
    pdf_path = tmp_path / "hole.pdf"
    document = pymupdf.open()
    page = document.new_page(width=400, height=400)
    shape = page.new_shape()
    shape.draw_rect((50, 50, 300, 300))
    shape.draw_rect((120, 120, 220, 220))
    shape.finish(color=(0, 0, 0), fill=(0.2, 0.2, 0.8), even_odd=True, closePath=True, width=1)
    shape.commit()
    document.save(pdf_path)
    document.close()

    with pymupdf.open(pdf_path) as source:
        extracted = extract_page(source[0], 1)
    filled = [item for item in extracted.primitives if item.fill_color is not None]
    assert len(filled) == 2
    assert all(item.fill_even_odd for item in filled)
    assert filled[0].source_draw_order == filled[1].source_draw_order
    outer = max(filled, key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])).bbox
    inner = min(filled, key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])).bbox

    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1", "import_text": False})
    output = tmp_path / "hole.dxf"
    export_to_dxf(run.extraction, str(output), DxfExportOptions(include_text=False))
    drawing = ezdxf.readfile(output)
    solids = [entity for entity in drawing.modelspace() if entity.dxftype() == "SOLID"]
    hatches = [entity for entity in drawing.modelspace() if entity.dxftype() == "HATCH"]
    assert solids
    assert not hatches

    def centroid(entity):
        points = [entity.dxf.vtx0, entity.dxf.vtx1, entity.dxf.vtx2]
        return (
            sum(point.x for point in points) / 3,
            sum(point.y for point in points) / 3,
        )

    for entity in solids:
        x, y = centroid(entity)
        assert outer[0] - 0.2 <= x <= outer[2] + 0.2
        assert outer[1] - 0.2 <= y <= outer[3] + 0.2
        assert not (inner[0] + 0.2 < x < inner[2] - 0.2 and inner[1] + 0.2 < y < inner[3] - 0.2)

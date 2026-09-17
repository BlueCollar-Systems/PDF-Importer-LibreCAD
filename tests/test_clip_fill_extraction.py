"""Synthetic vector masks: no private drawing required."""
import sys
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "PDFVectorImporter", ROOT / "pdf_vector_importer", ROOT):
    if (candidate / "pdfcadcore").is_dir():
        sys.path.insert(0, str(candidate))
        break
from pdfcadcore import primitive_extractor as pe
from pdfcadcore.fitz_loader import import_fitz


def clip_rows():
    fitz = import_fitz()
    # An open outer contour, a small real vertex, and an independent counter.
    points = [(0, 0), (10, 0), (10, 10), (0, 10), (0, .001)]
    items = [("l", fitz.Point(*a), fitz.Point(*b)) for a, b in zip(points[:-1], points[1:], strict=True)]
    items.append(("re", fitz.Rect(3, 3, 7, 7), 1))
    return [
        {"type": "clip", "level": 0, "scissor": fitz.Rect(0, 0, 10, 10),
         "items": items, "even_odd": True},
        {"type": "f", "level": 1, "seqno": 7, "rect": fitz.Rect(-1, -1, 11, 11),
         "items": [("re", fitz.Rect(-1, -1, 11, 11), 1)], "fill": (0, 0, 0),
         "fill_opacity": 1.0},
    ]


@pytest.mark.parametrize("cached", [False, True])
def test_clip_contours_keep_group_vertices_holes_and_implicit_closure(monkeypatch, cached):
    fitz = import_fitz()
    calls = []
    rows = clip_rows()
    def drawings(*, extended=False):
        calls.append(extended)
        assert extended
        return rows
    page = SimpleNamespace(rect=fitz.Rect(0, 0, 100, 100), get_drawings=drawings)
    monkeypatch.setattr(pe, "_extract_text", lambda *args, **kwargs: [])
    result = pe.extract_page(page, 2, scale=2, detect_arcs=True, drawings=rows if cached else None)
    assert calls == ([] if cached else [True])
    assert len(result.primitives) == 2
    assert all(p.clip_fill_group_id == "clip-fill:7" and p.clip_fill_even_odd for p in result.primitives)
    assert all(p.closed and p.type == "closed_loop" for p in result.primitives)
    outer, counter = result.primitives
    assert len(outer.points) == 5  # tiny real edge was not removed or circle-fit
    assert outer.points[4][1] == pytest.approx((100 - .001) * pe.MM_PER_PT * 2)
    assert counter.bbox == pytest.approx((3 * pe.MM_PER_PT * 2, 93 * pe.MM_PER_PT * 2,
                                          7 * pe.MM_PER_PT * 2, 97 * pe.MM_PER_PT * 2))
    assert result._source_drawings[0]["bcs_compound_clip_fill"]


def test_plain_fill_keeps_existing_primitive_behavior(monkeypatch):
    fitz = import_fitz()
    row = clip_rows()[1]
    row["level"] = 0
    page = SimpleNamespace(rect=fitz.Rect(0, 0, 100, 100))
    monkeypatch.setattr(pe, "_extract_text", lambda *args, **kwargs: [])
    result = pe.extract_page(page, 1, detect_arcs=False, drawings=[row])
    assert len(result.primitives) == 1
    assert result.primitives[0].clip_fill_group_id is None


def test_circle_fitting_keeps_exact_polygons_around_clip_artwork(monkeypatch):
    fitz = import_fitz()
    def polygon(cx, seq):
        pts = [fitz.Point(cx+2*math.cos(i*math.tau/16), 5+2*math.sin(i*math.tau/16)) for i in range(16)]
        return dict(type="s", level=0, seqno=seq, closePath=True, color=(0,0,0),
                    rect=fitz.Rect(cx-2,3,cx+2,7), items=[("l", p, pts[(i+1)%16]) for i,p in enumerate(pts)])
    rows = clip_rows() + [polygon(5, 8), polygon(50, 9)]
    page = SimpleNamespace(rect=fitz.Rect(0, 0, 100, 100))
    monkeypatch.setattr(pe, "_extract_text", lambda *args, **kwargs: [])
    result = pe.extract_page(page, 1, detect_arcs=True, drawings=rows)
    strokes = sorted((p for p in result.primitives if p.stroke_color), key=lambda p:p.bbox[0])
    assert strokes[0].type == "closed_loop" and len(strokes[0].points) == 17
    assert strokes[1].type == "circle"  # unrelated ordinary circles are unchanged

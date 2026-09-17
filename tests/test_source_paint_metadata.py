"""Native hosts must retain PDF opacity and paint order without legacy drift."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
import pytest

from pdfcadcore.primitive_extractor import extract_page, _source_draw_order
from pdfcadcore.primitives import Primitive


def test_raw_source_paint_survives_beside_legacy_composite():
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=150)
        page.draw_rect(pymupdf.Rect(10, 10, 90, 60), fill=(0, 0, 0), color=None)
        page.draw_rect(pymupdf.Rect(20, 20, 100, 70), fill=(0, 1, 1), color=(1, 0, 0),
                       fill_opacity=.3, stroke_opacity=.5)
        raw = page.get_drawings()
        data = extract_page(page, 1, detect_arcs=False)
    by_order = {p.source_draw_order: p for p in data.primitives}
    assert set(by_order) == {r["seqno"] for r in raw}
    for row in raw:
        p = by_order[row["seqno"]]
        assert p.source_fill_color == row["fill"]
        assert p.source_stroke_color == row["color"]
        assert p.fill_opacity == (1.0 if row.get("fill_opacity") is None else row["fill_opacity"])
        assert p.stroke_opacity == (1.0 if row.get("stroke_opacity") is None else row["stroke_opacity"])
    transparent = [p for p in data.primitives if p.source_fill_color == (0, 1, 1)][0]
    assert transparent.fill_opacity == pytest.approx(.3, abs=1e-6)
    assert transparent.fill_color == pytest.approx((.7, 1, 1), abs=1e-6)
    assert transparent.stroke_color == pytest.approx((1, .5, .5), abs=1e-6)


def test_older_primitive_constructors_remain_opaque_without_source_sequence():
    p = Primitive(id=1, type="line", points=[(0, 0), (10, 0)], stroke_color=(0, 0, 0))
    assert p.source_draw_order is None
    assert p.source_stroke_color is None
    assert p.source_fill_color is None
    assert p.stroke_opacity == p.fill_opacity == 1


@pytest.mark.parametrize("raw", [None, True, False, -1, 1.5, "1.5", float("nan"), float("inf"), "unknown"])
def test_invalid_sequence_cannot_invent_paint_order(raw):
    assert _source_draw_order(raw) is None


@pytest.mark.parametrize("raw", [0, 12, 12.0, "12"])
def test_exact_integer_sequence_is_preserved(raw):
    assert _source_draw_order(raw) == int(raw)

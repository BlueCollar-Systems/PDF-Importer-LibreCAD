"""Rectangular PDF clips must trim the strokes drawn inside them."""
from __future__ import annotations

import pymupdf

from pdfcadcore.primitive_extractor import extract_page


def _clipped_pdf():
    document = pymupdf.open()
    page = document.new_page(width=400, height=300)
    page.clean_contents()
    xref = page.get_contents()[0]
    clip = b"""q
80 80 160 100 re W n
1 0 0 RG 2 w
20 130 m 380 130 l S
Q
"""
    document.update_stream(xref, document.xref_stream(xref) + clip)
    return document


def test_clipped_rectangle_fill_stays_a_fill_and_the_page_still_imports():
    document = pymupdf.open()
    page = document.new_page(width=100, height=100)
    page.clean_contents()
    xref = page.get_contents()[0]
    document.update_stream(xref, document.xref_stream(xref) + b"""
q
20 20 60 60 re W n
0 0 1 rg
10 10 80 80 re f
1 0 0 RG 1 w
10 50 m 90 50 l S
Q
""")
    from pdfcadcore.drawing_clips import get_clip_aware_drawings

    rows = get_clip_aware_drawings(page)
    fills = [row for row in rows if row.get("type") == "f"]
    assert fills
    assert all(row.get("bcs_stroke_clipped_to") != "rectangle" for row in fills)
    for row in rows:
        for item in row.get("items") or []:
            if item and item[0] == "l" and len(item) >= 3:
                assert not isinstance(item[1], tuple)
    extracted = extract_page(page, 1)
    document.close()
    assert any(item.fill_color == (0.0, 0.0, 1.0) for item in extracted.primitives)
    red = [item for item in extracted.primitives if item.stroke_color == (1.0, 0.0, 0.0)]
    assert len(red) == 1
    xs = [point[0] for point in red[0].points]
    assert min(xs) == pytest_approx(20 * 25.4 / 72)
    assert max(xs) == pytest_approx(80 * 25.4 / 72)


def test_numeric_pair_line_does_not_abort_the_page():
    document = pymupdf.open()
    page = document.new_page(width=100, height=100)
    extracted = extract_page(page, 1, drawings=[{
        "type": "s",
        "color": (0, 0, 0),
        "width": 1,
        "closePath": False,
        "items": [("l", (10.0, 20.0), (80.0, 40.0))],
    }])
    document.close()
    assert len(extracted.primitives) == 1
    assert extracted.primitives[0].type == "line"


def test_horizontal_stroke_is_cut_to_the_rectangular_clip():
    document = _clipped_pdf()
    page = extract_page(document[0], 1)
    document.close()
    red = [item for item in page.primitives if item.stroke_color == (1.0, 0.0, 0.0)]
    assert len(red) == 1
    xs = [point[0] for point in red[0].points]
    # PDF x 80 and 240, in millimetres. The unclipped line ran from x 20 to 380.
    assert min(xs) == pytest_approx(80 * 25.4 / 72)
    assert max(xs) == pytest_approx(240 * 25.4 / 72)


def pytest_approx(value):
    import pytest
    return pytest.approx(value, abs=0.05)

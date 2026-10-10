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

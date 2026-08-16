"""Constant alpha (PDF /CA, /ca) is composited into the delivered colour.

Visual-oracle finding (single-page garden map, 2026-08-16): the page paints 355 black
separator bars at fill alpha 0.4, ~350 text spans at alpha 0.4-0.75 and 28 white
overlays at alpha 0.15. Every host received the raw colour and drew them opaque, so
mid-grey separators came out black and faint labels came out solid grey — visible
next to the PDF viewer on any host. CAD hosts have no page compositor (LibreCAD has
no transparency at all), so pdfcadcore now composites constant alpha against the
white page once, at extraction, for strokes, fills and text. Opaque content is
bit-identical to before.
"""
from __future__ import annotations

import pymupdf
import pytest

from pdfcadcore import primitive_extractor as PE


def _extract(doc):
    return PE.extract_page(doc.load_page(0), 1)


@pytest.fixture
def alpha_pdf():
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    # black fill at 40 % over the page -> #999999; opaque red fill unchanged
    page.draw_rect(pymupdf.Rect(10, 10, 60, 30), color=None, fill=(0, 0, 0), fill_opacity=0.4)
    page.draw_rect(pymupdf.Rect(10, 40, 60, 60), color=None, fill=(1, 0, 0))
    # blue stroke at 25 %
    page.draw_line(pymupdf.Point(10, 80), pymupdf.Point(150, 80), color=(0, 0, 1),
                   width=2, stroke_opacity=0.25)
    # grey text at 50 % and opaque text of the same colour
    page.insert_text(pymupdf.Point(20, 120), "FAINT", fontsize=12, color=(0.5, 0.5, 0.5),
                     fill_opacity=0.5)
    page.insert_text(pymupdf.Point(20, 150), "SOLID", fontsize=12, color=(0.5, 0.5, 0.5))
    yield doc
    doc.close()


def _close(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_fill_alpha_is_composited_against_the_white_page(alpha_pdf):
    data = _extract(alpha_pdf)
    fills = [p for p in data.primitives if p.fill_color is not None]
    greys = [p for p in fills if _close(p.fill_color, (0.6, 0.6, 0.6))]
    reds = [p for p in fills if _close(p.fill_color, (1.0, 0.0, 0.0))]
    assert greys, [p.fill_color for p in fills]
    assert reds, [p.fill_color for p in fills]
    assert not any(_close(p.fill_color, (0.0, 0.0, 0.0)) for p in fills)


def test_stroke_alpha_is_composited_against_the_white_page(alpha_pdf):
    data = _extract(alpha_pdf)
    strokes = [p for p in data.primitives if p.stroke_color is not None and p.fill_color is None]
    assert any(_close(p.stroke_color, (0.75, 0.75, 1.0)) for p in strokes), \
        [p.stroke_color for p in strokes]


def test_text_alpha_is_composited_against_the_white_page(alpha_pdf):
    data = _extract(alpha_pdf)
    by_text = {t.text.strip(): t for t in data.text_items}
    # span colour and alpha are 8-bit in PyMuPDF (128/255), hence the tolerance
    assert _close(by_text["FAINT"].color, (0.75, 0.75, 0.75), tol=0.01), by_text["FAINT"].color
    assert _close(by_text["SOLID"].color, (0.5, 0.5, 0.5), tol=0.01), by_text["SOLID"].color


@pytest.mark.parametrize(
    "color, alpha, expected",
    [
        ((0.0, 0.0, 0.0), 0.4, (0.6, 0.6, 0.6)),
        ((1.0, 0.0, 0.0), 1.0, (1.0, 0.0, 0.0)),
        ((0.2, 0.4, 0.6), 0.0, (1.0, 1.0, 1.0)),
        ((0.2, 0.4, 0.6), None, (0.2, 0.4, 0.6)),
        ((0.2, 0.4, 0.6), 1.7, (0.2, 0.4, 0.6)),
        ((0.2, 0.4, 0.6), -0.5, (1.0, 1.0, 1.0)),
        ((0.2, 0.4, 0.6), "nan", (0.2, 0.4, 0.6)),
        (None, 0.4, None),
    ],
)
def test_composite_alpha_helper(color, alpha, expected):
    out = PE._composite_alpha(color, alpha)
    if expected is None:
        assert out is None
    else:
        assert _close(out, expected), out


def test_span_alpha_accepts_pymupdf_0_255_ints():
    # PyMuPDF text spans carry alpha as an int 0-255; drawings carry 0.0-1.0 floats.
    assert _close(PE._composite_alpha((0.0, 0.0, 0.0), PE._span_alpha({"alpha": 102})),
                  (0.6, 0.6, 0.6))
    assert PE._span_alpha({}) is None
    assert PE._span_alpha({"alpha": 255}) == 1.0

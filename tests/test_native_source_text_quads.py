"""Source text matrices must never acquire shear from font-metric recovery."""
import math

import pymupdf
import pytest

from pdfcadcore.primitive_extractor import (
    _extract_text,
    _raw_text_with_source_quads,
)


@pytest.mark.parametrize("matrix", [
    pymupdf.Matrix(1.3, 1),
    pymupdf.Matrix(1, .2, .3, 1, 0, 0),
    pymupdf.Matrix(1.3, 1).prerotate(27),
    pymupdf.Matrix(1, 1).prerotate(90),
])
def test_original_pdf_matrix_controls_character_axes(matrix):
    with pymupdf.open() as doc:
        page = doc.new_page(width=500, height=400)
        # Two overlapping, identically spelled runs exercise occurrence binding.
        for _ in range(2):
            page.insert_text((100, 150), "Affine F A", fontsize=12,
                             morph=(pymupdf.Point(100, 150), matrix))
        raw = _raw_text_with_source_quads(page)
        chars = [c for b in raw["blocks"] if b["type"] == 0
                 for line in b["lines"] for span in line["spans"]
                 for c in span["chars"]]
        assert "".join(c["c"] for c in chars) == "Affine F A" * 2
        assert all("quad" in c for c in chars)
        for char in chars:
            ul, ur, lr, ll = char["quad"]
            # PDF user Y increases upwards; PyMuPDF page Y increases downwards.
            top = (ur[0] - ul[0], ur[1] - ul[1])
            side = (ll[0] - ul[0], ll[1] - ul[1])
            assert abs(top[0] * (-matrix.b) - top[1] * matrix.a) < .0002
            assert abs(side[0] * matrix.d + side[1] * matrix.c) < .0002
            assert math.hypot(*top) > 0
            assert math.hypot(*side) > 0
            assert (lr[0] - ur[0], lr[1] - ur[1]) == pytest.approx(side, abs=.0001)
        items = _extract_text(page, 400, 1, True, 1)
        layouts = [c for item in items for c in item.source_char_layout]
        assert [c.text for c in layouts] == [c["c"] for c in chars]
        assert [c.source_origin_pdf for c in layouts] == [c["origin"] for c in chars]
        assert [c.source_quad_pdf for c in layouts] == [c["quad"] for c in chars]


def test_nonuniform_horizontal_letters_do_not_use_recovered_shear():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((100, 150), "F", fontsize=12,
                         morph=(pymupdf.Point(100, 150), pymupdf.Matrix(1.3, 1)))
        line = _raw_text_with_source_quads(page)["blocks"][0]["lines"][0]
        span = line["spans"][0]
        char = span["chars"][0]
        recovered = pymupdf.recover_char_quad(line["dir"], span, char)
        assert abs(recovered.ul.y - recovered.ur.y) > 1
        assert char["quad"][0][1] == char["quad"][1][1]
        assert span["quad"] == char["quad"]


def test_page_adapter_without_native_textpage_keeps_explicit_quads():
    expected = {"blocks": []}

    class Adapter:
        def get_text(self, kind):
            assert kind == "rawdict"
            return expected

    assert _raw_text_with_source_quads(Adapter()) is expected

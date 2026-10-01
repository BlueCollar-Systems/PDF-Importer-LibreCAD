"""Exact visible ink survives while out-of-page line extensions disappear."""
import copy
import hashlib

import pytest

from pdfcadcore.page_paint_bounds import clip_axis_page_lines


def line(start=(-20., 50.), end=(120., 50.), **changes):
    row = {"type": "s", "seqno": 0, "items": [("l", start, end)],
           "rect": (min(start[0], end[0]), min(start[1], end[1]),
                    max(start[0], end[0]), max(start[1], end[1])),
           "lineCap": (0, 0, 0), "dashes": "[] 0", "closePath": False, "width": 2.}
    row.update(changes)
    return row


def clip(row, log=None):
    return clip_axis_page_lines([row], (0, 0, 100, 100),
                                [("stroke-path", (-30, -30, 130, 130))] if log is None else log)[0]


@pytest.mark.parametrize("start,end,expected", [
    ((-20., 50.), (120., 50.), ((0., 50.), (100., 50.))),
    ((120., 50.), (-20., 50.), ((100., 50.), (0., 50.))),
    ((50., -20.), (50., 120.), ((50., 0.), (50., 100.))),
    ((50., 120.), (50., -20.), ((50., 100.), (50., 0.))),
    ((30., 50.), (120., 50.), ((30., 50.), (100., 50.))),
])
def test_editable_line_direction_and_visible_segment_are_preserved(start, end, expected):
    row = line(start, end)
    before = copy.deepcopy(row)
    result = clip(row)
    assert result["items"] == [("l", *expected)]
    assert row == before
    assert result["page_line_clip_proof"]["source_points"] == (start, end)
    assert result["seqno"] == row["seqno"]


@pytest.mark.parametrize("changes", [
    {"lineCap": (1, 1, 1)}, {"lineCap": None}, {"lineCap": (False, False, False)},
    {"dashes": "[2 2] 0"}, {"dashes": ""}, {"closePath": True},
    {"width": float("nan")}, {"width": 0}, {"seqno": True},
    {"items": [("l", (-20, 30), (120, 70))]},
    {"items": [("l", (-20, .5), (120, .5))]},
    {"items": [("l", (-20, 50), (120, 50)), ("l", (120, 50), (100, 60))]},
])
def test_unknown_caps_dashes_diagonal_or_transverse_clipping_keep_source(changes):
    row = line(**changes)
    assert clip(row) is row


@pytest.mark.parametrize("log", [[], [("fill-path", (-30, -30, 130, 130))],
                                  [("stroke-path", (0, 0, 100, 100))]])
def test_missing_or_unbound_renderer_paint_keeps_source(log):
    row = line()
    assert clip(row, log) is row


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_real_pdf_visible_pixels_are_identical_and_native_points_stay_in_page(rotation):
    import pymupdf as fitz
    from pdfcadcore.drawing_clips import get_clip_aware_drawings

    original = fitz.open()
    page = original.new_page(width=100, height=100)
    page.draw_line((-20, 50), (120, 50), width=2, lineCap=0)
    page.draw_line((50, -20), (50, 120), width=2, lineCap=0)
    page.set_rotation(rotation)
    source_bytes = original.tobytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    with fitz.open(stream=source_bytes, filetype="pdf") as source:
        rows = get_clip_aware_drawings(source[0])
        assert len(rows) == 2
        for row in rows:
            assert row["page_line_clip_proof"]["kind"] == "axis_butt_line_visible_page_intersection"
            assert all(0 <= coordinate <= 100 for item in row["items"] for p in item[1:] for coordinate in p)
        rebuilt = fitz.open()
        output = rebuilt.new_page(width=100, height=100)
        for row in rows:
            output.draw_line(*row["items"][0][1:], width=row["width"], lineCap=0)
        output.set_rotation(rotation)
        assert source[0].get_pixmap(alpha=False).samples == output.get_pixmap(alpha=False).samples
    assert hashlib.sha256(source_bytes).hexdigest() == digest

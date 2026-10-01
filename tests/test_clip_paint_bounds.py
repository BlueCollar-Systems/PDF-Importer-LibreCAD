"""Only renderer-proven paint outside an active PDF clip can disappear."""
from types import SimpleNamespace

import pytest

from pdfcadcore.page_paint_bounds import page_visible_drawings


def clipped_rows(*, bounds=(0, 0, 10, 10), kind="s"):
    return [{"type": "clip", "level": 0, "scissor": bounds},
            {"type": kind, "level": 1, "seqno": 0, "rect": (2, 11, 8, 11)}]


def resolve(rows, log):
    page = SimpleNamespace(rect=(0, 0, 100, 100), get_bboxlog=lambda: log)
    return page_visible_drawings(page, rows)


@pytest.mark.parametrize("kind,log", [
    ("s", [("stroke-path", (1, 10.5, 9, 11.5))]),
    ("f", [("fill-path", (2, 11, 8, 12))]),
    ("fs", [("fill-path", (2, 11, 8, 12)), ("stroke-path", (1, 10.5, 9, 12.5))]),
])
def test_complete_paint_outside_active_clip_is_invisible(kind, log):
    rows = clipped_rows(kind=kind)
    assert resolve(rows, log) == rows[:1]


@pytest.mark.parametrize("log", [[], [("fill-path", (1, 10.5, 9, 11.5))],
    [("stroke-path", (1, 10, 9, 11.5))],
    [("stroke-path", (1, 9, 9, 12))],
    [("stroke-path", (1, float("nan"), 9, 12))]])
def test_missing_wrong_or_touching_paint_proof_retains_source(log):
    rows = clipped_rows()
    assert resolve(rows, log) == rows


@pytest.mark.parametrize("bounds", [None, (0, 0, float("inf"), 10), (10, 10, 0, 0)])
def test_invalid_scissor_never_authorizes_dropping(bounds):
    rows = clipped_rows(bounds=bounds)
    assert resolve(rows, [("stroke-path", (1, 10.5, 9, 11.5))]) == rows


def test_nested_clip_and_group_scope_expire_at_the_correct_level():
    rows = [{"type": "clip", "level": 0, "scissor": (0, 0, 90, 90)},
            {"type": "group", "level": 1},
            {"type": "clip", "level": 2, "scissor": (0, 0, 10, 10)},
            {"type": "s", "level": 3, "seqno": 0, "rect": (2, 11, 8, 11)},
            {"type": "s", "level": 1, "seqno": 1, "rect": (2, 11, 8, 11)},
            {"type": "s", "level": 0, "seqno": 2, "rect": (2, 91, 8, 91)}]
    log = [("stroke-path", (1, 10.5, 9, 11.5)),
           ("stroke-path", (1, 10.5, 9, 11.5)),
           ("stroke-path", (1, 90.5, 9, 91.5))]
    assert resolve(rows, log) == rows[:3] + rows[4:]


def test_partial_clipping_does_not_rewrite_or_drop_the_line():
    rows = clipped_rows()
    rows[1]["rect"] = (-5, 5, 5, 5)
    assert resolve(rows, [("stroke-path", (-6, 4, 6, 6))]) == rows


def test_fill_outside_but_stroke_touching_clip_keeps_both():
    rows = clipped_rows(kind="fs")
    assert resolve(rows, [("fill-path", (2, 11, 8, 12)),
                          ("stroke-path", (1, 10, 9, 12.5))]) == rows


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_real_pdf_clip_removes_only_invisible_stroke_and_preserves_source(rotation):
    import hashlib
    import pymupdf as fitz
    from pdfcadcore.drawing_clips import get_clip_aware_drawings

    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    stream = doc.get_new_xref()
    doc.update_object(stream, "<<>>")
    doc.update_stream(stream, b"q 20 20 60 60 re W n 0 0 0 RG 1 w "
                      b"10 83 m 90 83 l S 10 50 m 90 50 l S Q "
                      b"10 90 m 90 90 l S")
    page.set_contents(stream)
    page.set_rotation(rotation)
    original = doc.tobytes()
    digest = hashlib.sha256(original).hexdigest()
    with fitz.open(stream=original, filetype="pdf") as source:
        page = source[0]
        raw = page.get_drawings(extended=True)
        retained = get_clip_aware_drawings(page)
        assert [row["seqno"] for row in retained] == [1, 2]
        partial = next(row for row in raw if row.get("seqno") == 1)
        assert retained[0]["items"] == partial["items"]
    assert hashlib.sha256(original).hexdigest() == digest

from copy import deepcopy

import pytest

from pdfcadcore.drawing_clips import (
    UnsupportedClipFillError,
    get_clip_aware_drawings,
    resolve_covered_clip_fills,
)


def clip(level=0, items=None, bounds=(0, 0, 20, 10)):
    return {"type": "clip", "level": level, "scissor": bounds,
            "even_odd": True, "items": items or [
                ("l", (0, 0), (20, 0)), ("l", (20, 0), (20, 10)),
                ("l", (20, 10), (0, 10)), ("l", (0, 10), (0, 0)),
                ("re", (5, 2, 15, 8), 1)]}


def fill(level=1, bounds=(0, 0, 20, 10), **changes):
    row = {"type": "f", "level": level, "rect": bounds,
           "items": [("re", bounds, 1)], "seqno": 41,
           "fill": (0, 0, 0), "fill_opacity": 1.0, "even_odd": False}
    row.update(changes)
    return row


def test_covered_compound_mask_keeps_contours_counters_and_paint_identity():
    rows = [clip(), fill()]
    before = deepcopy(rows)
    result = resolve_covered_clip_fills(rows)
    assert rows == before
    assert len(result) == 1
    assert result[0]["items"] == rows[0]["items"]
    assert result[0]["items"] is not rows[0]["items"]
    assert result[0]["even_odd"] is True
    assert result[0]["closePath"] is True
    assert result[0]["fill"] == (0, 0, 0)
    assert result[0]["seqno"] == 41
    assert result[0]["bcs_compound_clip_fill"] is True
    assert result[0]["bcs_clip_fill_group_id"] == "clip-fill:41"


def test_clip_scope_ends_at_equal_level_and_group_rows_are_not_paint():
    sibling = fill(level=0, seqno=42)
    result = resolve_covered_clip_fills([clip(), fill(), sibling, {"type": "group", "level": 0}])
    assert len(result) == 2
    assert result[1] is sibling
    assert "bcs_compound_clip_fill" not in sibling


def test_normal_paint_rows_and_paths_are_not_rewritten():
    stroke = {"type": "s", "level": 1, "items": [("l", (0, 0), (20, 10))]}
    ordinary = fill(level=0)
    assert resolve_covered_clip_fills([clip(), stroke, ordinary]) == [stroke, ordinary]


def test_rectangular_clip_containing_paint_preserves_original_rectangle():
    mask = clip(items=[("re", (-1, -1, 21, 11), 1)], bounds=(-1, -1, 21, 11))
    paint = fill()
    assert resolve_covered_clip_fills([mask, paint])[0] is paint


@pytest.mark.parametrize("rows,reason", [
    ([clip(), fill(bounds=(0, 0, 10, 10))], "partially"),
    ([clip(), clip(level=1), fill(level=2)], "nested"),
    ([clip(), fill(fill_opacity=0.5)], "opaque"),
])
def test_unsupported_rectangle_intersections_fail_explicitly(rows, reason):
    with pytest.raises(UnsupportedClipFillError, match=reason):
        resolve_covered_clip_fills(rows)


def test_float32_transform_roundoff_does_not_turn_full_cover_into_intersection():
    result = resolve_covered_clip_fills([clip(), fill(bounds=(0, 0, 19.9995, 10))])
    assert result[0]["bcs_compound_clip_fill"] is True


def test_fetch_requests_extended_drawings_once():
    class Page:
        calls = 0
        def get_drawings(self, *, extended):
            assert extended is True
            self.calls += 1
            return [clip(), fill()]
    page = Page()
    assert get_clip_aware_drawings(page)[0]["bcs_compound_clip_fill"]
    assert page.calls == 1


def test_adapter_compatibility_does_not_swallow_parser_type_errors():
    class OldPage:
        def get_drawings(self):
            return [fill(level=0)]
    assert get_clip_aware_drawings(OldPage())[0]["seqno"] == 41
    class BrokenPage:
        def get_drawings(self, *, extended):
            raise TypeError("invalid drawing content")
    with pytest.raises(TypeError, match="invalid drawing content"):
        get_clip_aware_drawings(BrokenPage())


def test_mask_outline_strokes_preserve_source_edges_without_changing_items():
    near = dict(type="s", level=0, rect=(4, 2, 16, 9), items=[("l", (4, 2), (16, 9))])
    far = dict(type="s", level=0, rect=(40, 2, 60, 9), items=[("l", (40, 2), (60, 9))])
    result = resolve_covered_clip_fills([clip(), fill(), near, far])
    assert result[1]["bcs_preserve_source_edges"] is True
    assert result[1]["items"] is near["items"]
    assert "bcs_preserve_source_edges" not in near
    assert result[2] is far


def test_outline_grid_handles_negative_and_far_source_coordinates():
    mask = clip(bounds=(-1000, -300, -980, -290))
    paint = fill(bounds=(-1000, -300, -980, -290))
    near = dict(type="s", level=0, rect=(-990, -299, -989, -291), items=[])
    far = dict(type="s", level=0, rect=(1e9, 1e9, 1e9+100, 1e9+100), items=[])
    result = resolve_covered_clip_fills([mask, paint, near, far])
    assert result[1]["bcs_preserve_source_edges"]
    assert result[2] is far

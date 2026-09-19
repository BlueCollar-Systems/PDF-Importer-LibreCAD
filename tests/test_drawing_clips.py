from copy import deepcopy

import pytest

from pdfcadcore.drawing_clips import (
    UnsupportedClipFillError,
    clip_fill_issues,
    get_clip_aware_drawings,
    resolve_covered_clip_fills,
    summarize_clip_fill_issues,
)


def clip(level=0, items=None, bounds=(0, 0, 20, 10)):
    return {"type": "clip", "level": level, "scissor": bounds,
            "even_odd": True, "items": items or [
                ("l", (0, 0), (20, 0)), ("l", (20, 0), (20, 10)),
                ("l", (20, 10), (0, 10)), ("l", (0, 10), (0, 0)),
                ("re", (5, 2, 15, 8), 1)]}


def rect_clip(bounds, level=0):
    return {"type": "clip", "level": level, "scissor": bounds,
            "even_odd": False, "items": [("re", bounds, 1)]}


def fill(level=1, bounds=(0, 0, 20, 10), **changes):
    row = {"type": "f", "level": level, "rect": bounds,
           "items": [("re", bounds, 1)], "seqno": 41,
           "fill": (0, 0, 0), "fill_opacity": 1.0, "even_odd": False}
    row.update(changes)
    return row


def contours_of(row):
    """Closed point loops of a resolved compound fill, as sets for comparison."""
    loops, current = [], []
    for kind, start, end in row["items"]:
        assert kind == "l"
        if current and current[-1] != tuple(start):
            loops.append(current)
            current = []
        if not current:
            current.append(tuple(start))
        current.append(tuple(end))
    if current:
        loops.append(current)
    return [frozenset(loop) for loop in loops]


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
    # The plain case is not an issue: nothing about it needs telling.
    assert clip_fill_issues(result) == []
    assert "bcs_clip_fill_resolution" not in result[0]


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
    result = resolve_covered_clip_fills([mask, paint])
    assert result[0] is paint
    assert clip_fill_issues(result) == []


# --- one unprovable fill is a fact about that fill, never the end of the page ---

def test_the_resolver_never_raises_for_the_three_shapes_that_used_to_abort_a_document():
    # These are the exact inputs the first resolver refused with
    # "only partially covers", "needs a nested vector intersection" and
    # "is not an opaque fill". 197 corpus drawings died on them.
    for rows in (
        [clip(), fill(bounds=(0, 0, 10, 10))],
        [clip(), clip(level=1), fill(level=2)],
        [clip(), fill(fill_opacity=0.5)],
    ):
        resolve_covered_clip_fills(rows)


def test_a_fill_that_partly_covers_a_line_path_is_cut_exactly_counters_included():
    rows = [clip(), fill(bounds=(0, 0, 10, 10))]
    before = deepcopy(rows)
    result = resolve_covered_clip_fills(rows)
    assert rows == before
    assert len(result) == 1
    row = result[0]
    assert row["bcs_compound_clip_fill"] is True
    assert row["bcs_clip_fill_resolution"] == "polygon-rect"
    assert row["even_odd"] is True and row["fill"] == (0, 0, 0)
    assert tuple(row["rect"]) == (0, 0, 10, 10)
    # The cut runs through the clip's counter, so the counter opens onto the
    # outline: one loop, not a hole sharing an edge with the ring around it
    # (face makers reject that).
    assert contours_of(row) == [
        frozenset({(0, 0), (10, 0), (10, 2), (5, 2), (5, 8), (10, 8), (10, 10), (0, 10)}),
    ]
    (issue,) = clip_fill_issues(result)
    assert (issue["reason"], issue["action"], issue["exact"], issue["severity"], issue["dropped"]) == (
        "partial-cover", "polygon-rect", True, "info", False)
    assert issue["seqno"] == 41


def diamond(cx, cy, r, clockwise=False):
    corners = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    if clockwise:
        corners.reverse()
    return [("l", corners[i], corners[(i + 1) % 4]) for i in range(4)]


def test_a_cut_line_path_keeps_the_counters_the_cut_does_not_reach():
    outline = [("l", (0, 0), (20, 0)), ("l", (20, 0), (20, 10)), ("l", (20, 10), (0, 10)), ("l", (0, 10), (0, 0))]
    result = resolve_covered_clip_fills([clip(items=outline + diamond(5, 5, 2) + diamond(15, 5, 2)),
                                         fill(bounds=(0, 0, 10, 10))])
    assert result[0]["even_odd"] is True and result[0]["bcs_clip_fill_resolution"] == "polygon-rect"
    assert contours_of(result[0]) == [
        frozenset({(0, 0), (10, 0), (10, 10), (0, 10)}),
        frozenset({(5, 3), (7, 5), (5, 7), (3, 5)}),   # the far diamond is outside the fill and gone
    ]


def test_the_fill_is_never_returned_as_its_unclipped_rectangle():
    # Emitting the flood rectangle is the bug that turns a sheet solid black.
    for rows in (
        [clip(), fill(bounds=(-500, -500, 10, 500))],
        [clip(), clip(level=1), fill(level=2, bounds=(-500, -500, 500, 500))],
        [{"type": "clip", "level": 0, "scissor": (0, 0, 20, 10), "items": []}, fill(bounds=(-500, -500, 500, 500))],
    ):
        for row in resolve_covered_clip_fills(rows):
            box = tuple(row["rect"])
            assert box[0] >= 0 and box[1] >= 0 and box[2] <= 20 and box[3] <= 10


def test_two_path_clips_at_once_drop_that_one_fill_and_say_so():
    neighbour = {"type": "s", "level": 0, "rect": (40, 0, 60, 5), "items": [("l", (40, 0), (60, 5))]}
    wedge = [("l", (0, 0), (20, 0)), ("l", (20, 0), (20, 10)), ("l", (20, 10), (0, 0))]
    result = resolve_covered_clip_fills([clip(), clip(level=1, items=wedge), fill(level=2), neighbour])
    assert result == [neighbour]  # everything else on the page still arrives
    (issue,) = clip_fill_issues(result)
    assert (issue["reason"], issue["action"], issue["severity"], issue["dropped"]) == (
        "nested", "dropped-unsupported", "warning", True)
    assert "2 different non-rectangular clips" in issue["detail"]


def test_the_same_clip_path_pushed_twice_is_one_clip():
    # a rounded box clipped inside itself: 28 fills of one corpus sheet
    triangle = [("l", (0, 0), (20, 0)), ("l", (20, 0), (0, 10)), ("l", (0, 10), (0, 0))]
    rows = [clip(items=triangle), dict(clip(items=triangle), level=1), fill(level=2)]
    result = resolve_covered_clip_fills(rows)
    assert result[0]["items"] == triangle
    (issue,) = clip_fill_issues(result)
    assert issue["action"] == "clip-path" and issue["severity"] == "info"


def test_a_path_clip_that_shows_everything_the_other_can_show_is_set_aside():
    big = [("l", (-50, -50), (90, -50)), ("l", (90, -50), (20, 60)), ("l", (20, 60), (-50, -50))]
    small = [("l", (2, 2), (12, 2)), ("l", (12, 2), (2, 8)), ("l", (2, 8), (2, 2))]
    rows = [clip(items=big, bounds=(-50, -50, 90, 60)),
            dict(clip(items=small, bounds=(2, 2, 12, 8)), level=1), fill(level=2)]
    result = resolve_covered_clip_fills(rows)
    assert result[0]["items"] == small
    # two shapes that really do cut each other are still not guessed at
    other = [("l", (0, 0), (20, 0)), ("l", (20, 0), (20, 10)), ("l", (20, 10), (0, 0))]
    triangle = [("l", (0, 0), (20, 0)), ("l", (20, 0), (0, 10)), ("l", (0, 10), (0, 0))]
    result = resolve_covered_clip_fills([clip(items=triangle), dict(clip(items=other), level=1), fill(level=2)])
    assert result == [] and clip_fill_issues(result)[0]["action"] == "dropped-unsupported"
    # and clip paths that do not meet paint nothing
    far = [("l", (100, 100), (120, 100)), ("l", (120, 100), (100, 110)), ("l", (100, 110), (100, 100))]
    result = resolve_covered_clip_fills([clip(items=triangle), dict(clip(items=far, bounds=(100, 100, 120, 110)), level=1),
                                         fill(level=2, bounds=(0, 0, 200, 200))])
    assert result == [] and clip_fill_issues(result)[0]["action"] == "dropped-invisible"


def page_minus(box):
    mask = clip(items=[("re", (0, 0, 100, 100), 1), ("re", box, 1)], bounds=(0, 0, 100, 100))
    return mask


def test_a_rule_clipped_by_one_page_minus_a_box_clip_per_gap_keeps_its_pieces():
    # an underline that skips descenders: one rule, one "page minus a small box" clip per gap
    rule = fill(level=2, bounds=(10, 50, 90, 51))
    rows = [page_minus((20, 49, 25, 52)), dict(page_minus((60, 49, 70, 52)), level=1), rule]
    result = resolve_covered_clip_fills(rows)
    assert result[0]["even_odd"] is True and result[0]["bcs_compound_clip_fill"]
    assert sorted(contours_of(result[0]), key=lambda loop: min(loop)) == [
        frozenset({(10, 50), (20, 50), (20, 51), (10, 51)}),
        frozenset({(25, 50), (60, 50), (60, 51), (25, 51)}),
        frozenset({(70, 50), (90, 50), (90, 51), (70, 51)}),
    ]
    (issue,) = clip_fill_issues(result)
    assert issue["action"] == "polygon-rect" and issue["severity"] == "info"
    # a rule that falls wholly inside the gaps is not painted
    hidden = resolve_covered_clip_fills([page_minus((0, 40, 60, 60)), dict(page_minus((50, 40, 100, 60)), level=1), rule])
    assert hidden == [] and clip_fill_issues(hidden)[0]["action"] == "dropped-invisible"
    # a rule the gaps do not reach comes back as the rectangle it is
    clear = resolve_covered_clip_fills([page_minus((0, 0, 5, 5)), dict(page_minus((95, 95, 100, 100)), level=1), rule])
    assert clear[0]["items"] == [("re", (10, 50, 90, 51), 1)]


def test_an_l_shaped_region_is_one_loop_with_its_inner_corner():
    block = fill(level=2, bounds=(0, 0, 10, 10))
    rows = [page_minus((5, 5, 100, 100)), dict(page_minus((200, 200, 300, 300)), level=1), block]
    (loop,) = contours_of(resolve_covered_clip_fills(rows)[0])
    assert loop == frozenset({(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)})


def test_regions_that_meet_only_at_a_corner_are_separate_simple_loops():
    checker = clip(items=[("re", (0, 0, 5, 5), 1), ("re", (5, 5, 10, 10), 1)], bounds=(0, 0, 10, 10))
    other = clip(level=1, items=[("re", (0, 0, 10, 10), 1), ("re", (20, 20, 30, 30), 1)], bounds=(0, 0, 10, 10))
    for rows in ([checker, other, fill(level=2, bounds=(-1, -1, 9, 9))],
                 [dict(other, level=0), dict(checker, level=1), fill(level=2, bounds=(-1, -1, 9, 9))]):
        loops = contours_of(resolve_covered_clip_fills(rows)[0])
        assert sorted(loops, key=min) == [frozenset({(0, 0), (5, 0), (5, 5), (0, 5)}),
                                          frozenset({(5, 5), (9, 5), (9, 9), (5, 9)})]


def test_a_rectangular_parent_clip_does_not_make_the_intersection_unprovable():
    result = resolve_covered_clip_fills([rect_clip((-1, -1, 21, 11)), clip(level=1), fill(level=2)])
    assert result[0]["items"] == clip()["items"]
    (issue,) = clip_fill_issues(result)
    assert (issue["reason"], issue["action"], issue["exact"]) == ("nested", "clip-path", True)

    cut = resolve_covered_clip_fills([rect_clip((0, 0, 10, 10)), clip(level=1), fill(level=2)])
    assert tuple(cut[0]["rect"]) == (0, 0, 10, 10)
    assert cut[0]["bcs_clip_fill_resolution"] == "polygon-rect"


def test_a_translucent_fill_keeps_its_opacity_instead_of_refusing_the_page():
    result = resolve_covered_clip_fills([clip(), fill(fill_opacity=0.5)])
    assert result[0]["bcs_compound_clip_fill"] is True
    assert result[0]["fill_opacity"] == 0.5
    (issue,) = clip_fill_issues(result)
    assert (issue["reason"], issue["action"], issue["exact"]) == ("not-opaque", "clip-path", True)


def test_rectangle_through_a_rectangular_clip_becomes_the_exact_overlap():
    paint = fill(bounds=(0, 0, 20, 10))
    result = resolve_covered_clip_fills([rect_clip((5, 0, 30, 10)), paint])
    assert result[0]["items"] == [("re", (5, 0, 20, 10), 1)]
    assert tuple(result[0]["rect"]) == (5, 0, 20, 10)
    assert "bcs_compound_clip_fill" not in result[0]
    assert paint["rect"] == (0, 0, 20, 10)
    (issue,) = clip_fill_issues(result)
    assert (issue["action"], issue["exact"], issue["severity"]) == ("rect-intersection", True, "info")


def test_a_fill_the_page_never_shows_is_left_out_quietly():
    result = resolve_covered_clip_fills([rect_clip((100, 100, 110, 110)), fill()])
    assert result == []
    (issue,) = clip_fill_issues(result)
    assert (issue["action"], issue["severity"], issue["dropped"]) == ("dropped-invisible", "info", True)
    assert summarize_clip_fill_issues(clip_fill_issues(result)) == ""


def test_curved_clip_paths_are_cut_after_flattening_and_reported_as_approximate():
    # a D shape: straight left edge, bulging right side
    dee = [("l", (0, 0), (10, 0)), ("c", (10, 0), (24, 0), (24, 10), (10, 10)),
           ("l", (10, 10), (0, 10)), ("l", (0, 10), (0, 0))]
    result = resolve_covered_clip_fills([clip(items=dee, bounds=(0, 0, 20.5, 10)), fill(bounds=(0, 0, 15, 10))])
    row = result[0]
    assert row["bcs_clip_fill_resolution"] == "polygon-rect-flattened"
    xs = [p[0] for _, a, b in row["items"] for p in (a, b)]
    assert max(xs) == 15 and min(xs) == 0
    (issue,) = clip_fill_issues(result)
    assert (issue["exact"], issue["severity"], issue["dropped"]) == (False, "warning", False)
    assert "flattened" in summarize_clip_fill_issues([issue])


@pytest.mark.parametrize("rows", [
    [{"type": "clip", "level": 0, "scissor": (0, 0, 20, 10), "items": []}, fill()],
    [{"type": "clip", "level": 0, "scissor": (0, 0, float("inf"), 10), "items": clip()["items"]}, fill()],
    [clip(), fill(bounds=(0, 0, float("nan"), 10))],
    [clip(items=[("zz", (0, 0), (1, 1)), ("l", (1, 1), (9, 9)), ("l", (9, 9), (0, 0))]), fill(bounds=(0, 0, 10, 10))],
])
def test_malformed_clips_cost_one_fill_not_the_document(rows):
    stroke = {"type": "s", "level": 0, "rect": (40, 0, 60, 5), "items": [("l", (40, 0), (60, 5))]}
    result = resolve_covered_clip_fills(rows + [stroke])
    assert result == [stroke]
    (issue,) = clip_fill_issues(result)
    assert issue["dropped"] and issue["severity"] == "warning"
    assert "1 clipped fill(s) could not be resolved" in summarize_clip_fill_issues([issue])


def test_a_second_pass_changes_nothing_and_keeps_what_the_first_pass_recorded():
    # Hosts hand resolved rows back through extract_page(drawings=...). The clip
    # rows are gone by then, so a second pass that forgot the record would erase it.
    first = resolve_covered_clip_fills([clip(), fill(bounds=(0, 0, 10, 10)), rect_clip((5, 0, 30, 10)), fill()])
    second = resolve_covered_clip_fills(first)
    assert second == first
    assert clip_fill_issues(second) == clip_fill_issues(first)
    assert len(clip_fill_issues(second)) == 2


def nonzero_clip(items, bounds=(0, 0, 20, 10)):
    mask = clip(items=items, bounds=bounds)
    mask["even_odd"] = False
    return mask


def square(x0, y0, x1, y1, clockwise=False):
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if clockwise:
        corners.reverse()
    return [("l", corners[i], corners[(i + 1) % 4]) for i in range(4)]


def test_nonzero_winding_is_handed_to_hosts_as_rings_that_mean_the_same_under_even_odd():
    # No host runs a winding-aware tessellator; two of them abort the document
    # on a multi-contour nonzero fill. Same direction = solid, opposite = hole.
    solid = nonzero_clip(square(0, 0, 20, 10) + square(5, 2, 15, 8))
    result = resolve_covered_clip_fills([solid, fill(bounds=(0, 0, 10, 10))])
    # the inner square winds the same way: no hole, so what shows is the rectangle itself
    assert result[0]["items"] == [("re", (0, 0, 10, 10), 1)]
    assert not result[0].get("bcs_compound_clip_fill")

    holed = nonzero_clip(square(0, 0, 20, 10) + diamond(5, 5, 2, clockwise=True))
    result = resolve_covered_clip_fills([holed, fill(bounds=(0, 0, 10, 10))])
    assert result[0]["even_odd"] is True
    assert contours_of(result[0]) == [
        frozenset({(0, 0), (10, 0), (10, 10), (0, 10)}),
        frozenset({(5, 3), (7, 5), (5, 7), (3, 5)}),
    ]
    same_way = nonzero_clip(square(0, 0, 20, 10) + diamond(5, 5, 2))
    result = resolve_covered_clip_fills([same_way, fill(bounds=(0, 0, 10, 10))])
    assert result[0]["items"] == [("re", (0, 0, 10, 10), 1)]

    apart = nonzero_clip(square(0, 0, 8, 10) + square(9, 0, 20, 10, clockwise=True))
    result = resolve_covered_clip_fills([apart, fill(bounds=(0, 0, 10, 10))])
    assert result[0]["even_odd"] is True and len(contours_of(result[0])) == 2


def test_crossing_nonzero_contours_are_not_guessed_at():
    crossing = nonzero_clip(diamond(6, 5, 5) + diamond(12, 5, 5))
    stroke = {"type": "s", "level": 0, "rect": (40, 0, 60, 5), "items": [("l", (40, 0), (60, 5))]}
    result = resolve_covered_clip_fills([crossing, fill(bounds=(0, 0, 15, 10)), stroke])
    assert result == [stroke]
    (issue,) = clip_fill_issues(result)
    assert issue["dropped"] and issue["severity"] == "warning" and "cross" in issue["detail"]


def test_crossing_rectangles_are_exact_on_their_own_grid():
    overlapping = nonzero_clip(square(0, 0, 12, 10) + square(8, 2, 20, 8))
    result = resolve_covered_clip_fills([overlapping, fill(bounds=(0, 0, 15, 10))])
    assert contours_of(result[0]) == [
        frozenset({(0, 0), (12, 0), (12, 2), (15, 2), (15, 8), (12, 8), (12, 10), (0, 10)})]
    # drawn in opposite directions, the overlap cancels under nonzero winding
    cancelling = nonzero_clip(square(0, 0, 12, 10) + square(8, 2, 20, 8, clockwise=True))
    result = resolve_covered_clip_fills([cancelling, fill(bounds=(0, 0, 15, 10))])
    assert sorted(len(loop) for loop in contours_of(result[0])) == [4, 8]


def test_cut_paths_use_the_same_point_type_as_the_source_rows():
    class Point:
        def __init__(self, x, y):
            self.x, self.y = x, y

        def __getitem__(self, index):
            return (self.x, self.y)[index]

    items = [("l", Point(0, 0), Point(20, 0)), ("l", Point(20, 0), Point(0, 10)),
             ("l", Point(0, 10), Point(0, 0))]
    result = resolve_covered_clip_fills([clip(items=items), fill(bounds=(0, 0, 10, 10))])
    assert result[0]["bcs_compound_clip_fill"]
    # primitive_extractor reads a two-point "l" only when both ends carry .x
    assert all(isinstance(a, Point) and isinstance(b, Point) for _, a, b in result[0]["items"])


def test_a_rectangle_a_hair_short_of_the_clip_path_takes_the_path_not_a_sliver_cut():
    # 84% of the fills that aborted corpus documents were this: "x y w h re" rounding
    # leaves the flood rectangle 0.002-0.022 pt short of the path it is meant to cover.
    mask = clip()
    short = fill(bounds=(0, 0, 19.98, 10))
    result = resolve_covered_clip_fills([mask, short])
    assert result[0]["items"] == mask["items"]
    assert result[0]["rect"] == mask["scissor"]
    (issue,) = clip_fill_issues(result)
    assert issue["action"] == "clip-path" and issue["severity"] == "info"
    # a real partial cover is still cut
    cut = resolve_covered_clip_fills([mask, fill(bounds=(0, 0, 19.0, 10))])
    assert clip_fill_issues(cut)[0]["action"] == "polygon-rect"


def test_an_inverted_scissor_is_an_empty_clip_and_nothing_shows():
    # PyMuPDF's scissor is a running intersection; off-page clips leave it inverted.
    empty = clip(bounds=(30, 0, 25, 10))
    result = resolve_covered_clip_fills([rect_clip((0, 0, 100, 100)), dict(empty, level=1), fill(level=2)])
    assert result == []
    (issue,) = clip_fill_issues(result)
    assert issue["action"] == "dropped-invisible" and issue["severity"] == "info"


def test_a_whole_nonzero_clip_path_is_reduced_to_rings_made_of_its_own_items():
    outer, hole, island = square(0, 0, 20, 10), square(5, 2, 15, 8, clockwise=True), square(16, 4, 18, 6)
    mask = nonzero_clip(outer + hole + island)   # the island winds with the outer ring: no ring of its own
    result = resolve_covered_clip_fills([mask, fill()])
    assert result[0]["even_odd"] is True
    assert result[0]["items"] == outer + hole
    assert clip_fill_issues(result) == []


def test_a_nested_rectangle_item_has_no_known_direction_and_is_not_guessed():
    # PyMuPDF reports the same orientation flag for both drawing directions of a
    # rectangle, so under nonzero winding a nested "re" may be a hole or solid.
    frame = nonzero_clip(square(0, 0, 20, 10) + [("re", (5, 2, 15, 8), 1)])
    result = resolve_covered_clip_fills([frame, fill()])
    assert result == []
    (issue,) = clip_fill_issues(result)
    assert issue["dropped"] and issue["severity"] == "warning" and issue["reason"] == "nonzero-winding"
    # side by side, direction cannot matter: both are painted
    apart = nonzero_clip([("re", (0, 0, 8, 10), 1), ("re", (10, 0, 20, 10), -1)])
    result = resolve_covered_clip_fills([apart, fill()])
    assert result[0]["items"] == apart["items"] and result[0]["even_odd"] is True
    # and even-odd never needed a direction
    assert resolve_covered_clip_fills([clip(), fill()])[0]["items"] == clip()["items"]


def test_a_clip_path_too_large_to_check_is_dropped_not_waited_for(monkeypatch):
    import pdfcadcore.drawing_clips as module
    monkeypatch.setattr(module, "_MAX_CROSSING_TESTS", 10)
    many = nonzero_clip([item for k in range(8) for item in square(k * 2, 0, k * 2 + 1, 10)])
    result = resolve_covered_clip_fills([many, fill()])
    assert result == [] and clip_fill_issues(result)[0]["dropped"]


def test_a_clip_made_only_of_rectangles_still_yields_segments_the_extractor_can_read():
    # Found in three hosts at once: no line point to copy the point type from, so the cut
    # path came out as bare tuples and extract_page raised TypeError for the whole document.
    import pymupdf

    from pdfcadcore.primitive_extractor import extract_page

    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, b"q 10 10 80 80 re 30 30 40 40 re W* n 0 g 0 0 50 100 re f Q")
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
    rows = get_clip_aware_drawings(page)
    (row,) = [r for r in rows if r.get("bcs_compound_clip_fill")]
    assert all(hasattr(a, "x") and hasattr(b, "x") for _, a, b in row["items"])
    # a C: the frame's left half, open where the cut runs through the counter
    assert len(row["items"]) == 8
    page_data = extract_page(page, 1)
    assert [p for p in page_data.primitives if getattr(p, "clip_fill_group_id", None)]


def test_a_clip_path_with_a_non_finite_point_costs_that_fill_and_says_so():
    broken = clip(items=[("l", (0, 0), (20, 0)), ("l", (20, 0), (float("nan"), 10)), ("l", (float("nan"), 10), (0, 0))])
    for rows in ([broken, fill()], [broken, fill(bounds=(0, 0, 10, 10))]):
        result = resolve_covered_clip_fills(rows)
        assert result == []
        (issue,) = clip_fill_issues(result)
        assert (issue["reason"], issue["action"], issue["severity"]) == ("no-finite-bounds", "dropped-unsupported", "warning")


def _page(stream, font=False):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=100, height=100)
    if font:
        page.insert_font(fontname="helv")
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, stream)
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
    return page


def test_a_flood_rectangle_under_a_text_clip_is_dropped_and_reported_not_flooded():
    # PyMuPDF emits no row for a text clip: the fill just arrives one level deeper.
    page = _page(b"q BT /helv 40 Tf 7 Tr 10 40 Td (D042) Tj ET 0 0 1 rg 0 0 100 100 re f Q "
                 b"0 1 0 rg 5 5 10 10 re f", font=True)
    rows = get_clip_aware_drawings(page)
    assert [tuple(r["fill"]) for r in rows if r["type"] == "f"] == [(0.0, 1.0, 0.0)]  # the unclipped one stays
    (issue,) = clip_fill_issues(rows)
    assert (issue["reason"], issue["action"], issue["severity"], issue["dropped"]) == (
        "unexpressed-clip", "dropped-unsupported", "warning", True)
    assert issue["fill"] == [0.0, 0.0, 1.0]


def test_a_text_clip_inside_a_path_clip_is_still_recognised():
    page = _page(b"q 10 10 m 90 10 l 50 90 l h W n BT /helv 40 Tf 7 Tr 10 40 Td (D042) Tj ET "
                 b"0 0 1 rg 0 0 100 100 re f Q", font=True)
    rows = get_clip_aware_drawings(page)
    assert [r for r in rows if r["type"] == "f"] == []
    assert clip_fill_issues(rows)[0]["reason"] == "unexpressed-clip"


def test_levels_without_structural_rows_mean_nothing_on_a_second_pass():
    # Resolved rows keep their levels after the clip and group rows are gone; hosts hand them
    # back in (extract_page(drawings=...)). Nothing may be dropped then.
    grouped = [{"type": "group", "level": 0, "rect": (0, 0, 20, 10)}, fill(level=1)]
    first = resolve_covered_clip_fills(grouped, rows_from_page=True)
    assert first == [fill(level=1)] and clip_fill_issues(first) == []
    assert resolve_covered_clip_fills(list(first)) == [fill(level=1)]
    assert resolve_covered_clip_fills([fill(level=1)]) == [fill(level=1)]
    # and straight from a page, a group is a scope like any clip
    page = _page(b"q 0 0 1 rg 0 0 100 100 re f Q")
    assert len(get_clip_aware_drawings(page)) == 1


def test_issue_records_are_json_safe_whatever_the_row_carries():
    import json

    odd = fill(bounds=(0, 0, 10, 10), fill=(float("nan"), 0, 0), fill_opacity=float("inf"))
    result = resolve_covered_clip_fills([clip(), odd])
    (issue,) = clip_fill_issues(result)
    assert issue["fill"] is None and issue["fill_opacity"] is None
    json.dumps(clip_fill_issues(result), allow_nan=False)


def test_even_odd_contours_that_cross_are_delivered_but_not_called_exact():
    # The PDF leaves the overlap unpainted; a host that builds rings with counters may fill it.
    crossing = clip(items=diamond(6, 5, 5) + diamond(12, 5, 5), bounds=(1, 0, 17, 10))
    result = resolve_covered_clip_fills([crossing, fill()])
    assert result[0]["items"] == crossing["items"] and result[0]["even_odd"] is True
    (issue,) = clip_fill_issues(result)
    assert (issue["reason"], issue["action"], issue["exact"], issue["severity"], issue["dropped"]) == (
        "crossing-contours", "clip-path", False, "warning", False)
    assert "approximate" in summarize_clip_fill_issues(clip_fill_issues(result))
    # nested or apart is the ordinary case and stays silent
    assert clip_fill_issues(resolve_covered_clip_fills([clip(), fill()])) == []


def test_the_retired_exception_still_imports_for_hosts_that_name_it():
    assert issubclass(UnsupportedClipFillError, ValueError)
    assert clip_fill_issues([fill(level=0)]) == []


def test_float32_transform_roundoff_does_not_turn_full_cover_into_intersection():
    result = resolve_covered_clip_fills([clip(), fill(bounds=(0, 0, 19.9995, 10))])
    assert result[0]["bcs_compound_clip_fill"] is True
    assert clip_fill_issues(result) == []


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

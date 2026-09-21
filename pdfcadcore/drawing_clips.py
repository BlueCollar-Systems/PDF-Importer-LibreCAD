"""Resolve rectangle fills painted through PDF clip paths, one fill at a time.

A rectangle filled through a clip is how PDF producers draw an arbitrary filled
shape: "clip to the shape, then flood its bounding box". Emitting that rectangle
unclipped floods the sheet, so it is never done. Emitting nothing for the whole
document because one such fill could not be resolved is just as wrong: a single
unprovable fill used to abort a sheet of several hundred thousand paths.

The rule here is per fill:

* rectangle through rectangular clips       -> the exact intersection rectangle
* rectangle covering one path clip          -> the clip path itself (compound fill),
                                               vertices and curves untouched
* rectangle partly covering one path clip   -> the clip path cut to the visible
                                               rectangle (exact for line paths,
                                               flattened for curves, and said so)
* rectangle under a clip the parser does
  not express (text, stroke, image mask)    -> that ONE fill is dropped
* anything that cannot be proven            -> that ONE fill is dropped

Every fill that did not take the plain path is recorded on the returned list as
``clip_fill_issues`` so a host can tell the operator. Nothing in this module
raises for a drawing it does not understand.

This is still not a general polygon intersection engine. Several
non-rectangular clips active at once are resolved only when all but one of them
provably make no difference (the same path pushed twice, or a shape that covers
everything the others can show), or when every one of them is a set of
axis-aligned rectangles; otherwise that fill is reported and dropped.
"""
from __future__ import annotations

import math


class UnsupportedClipFillError(ValueError):
    """Kept so existing imports keep working; the resolver no longer raises it.

    One clipped fill that cannot be resolved is a fact about that fill, to be
    reported, not a reason to refuse the document it sits in.
    """


class ClipAwareDrawings(list):
    """Paint rows, plus what happened to every clipped fill that needed care."""

    def __init__(self, rows=(), issues=()):
        super().__init__(rows)
        self.clip_fill_issues = list(issues)


def clip_fill_issues(rows):
    """The issue records carried by a resolver result (empty for a plain list)."""
    return list(getattr(rows, "clip_fill_issues", ()) or ())


# Curves in a clip path are flattened only when the path has to be cut; one
# hundredth of a PDF point is 3.5 micrometres at 1:1.
_FLATTEN_TOLERANCE = 0.01
_MAX_CURVE_SEGMENTS = 256


# Producers write "x y w h re" with rounded width and height, so the flood
# rectangle routinely stops a few thousandths of a point short of the clip path
# it is meant to cover (corpus: median 0.002 pt, worst 0.022 pt). Cutting the
# path there would shave real vertices into slivers; 0.05 pt is 18 micrometres
# at 1:1 and the path's own geometry is the better answer.
_COVER_TOLERANCE = 0.05


def _finite4(value):
    try:
        coords = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if len(coords) != 4 or not all(math.isfinite(v) for v in coords):
        return None
    return coords


def _rect(value):
    coords = _finite4(value)
    if coords is None or coords[2] < coords[0] or coords[3] < coords[1]:
        return None
    return coords


def _contains(outer, inner, tolerance=0.001):
    # MuPDF's single-precision coordinates can differ by a few ULPs after a
    # transform. One thousandth of a PDF point is below 0.4 micrometres at 1:1.
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _intersection(a, b):
    """Overlap of two rectangles, or None when they share no area."""
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    if box[2] - box[0] <= 1e-9 or box[3] - box[1] <= 1e-9:
        return None
    return box


def _single_rectangle(row):
    items = row.get("items") or []
    return len(items) == 1 and items[0][0] == "re"


def _xy(point):
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    return float(point[0]), float(point[1])


def _quad_corners(quad):
    """Corners of a PyMuPDF quad in drawing order (ul, ur, lr, ll)."""
    if hasattr(quad, "ul"):
        return [_xy(quad.ul), _xy(quad.ur), _xy(quad.lr), _xy(quad.ll)]
    ul, ur, ll, lr = (_xy(p) for p in quad)
    return [ul, ur, lr, ll]


def _flatten_cubic(p0, p1, p2, p3):
    """Points after p0 along a cubic, within _FLATTEN_TOLERANCE of the curve."""
    ddx = max(abs(p0[0] - 2 * p1[0] + p2[0]), abs(p1[0] - 2 * p2[0] + p3[0]))
    ddy = max(abs(p0[1] - 2 * p1[1] + p2[1]), abs(p1[1] - 2 * p2[1] + p3[1]))
    # Deviation of n equal-parameter chords from a cubic is at most 0.75*d/n^2.
    count = math.ceil(math.sqrt(0.75 * math.hypot(ddx, ddy) / _FLATTEN_TOLERANCE)) or 1
    count = max(1, min(_MAX_CURVE_SEGMENTS, count))
    points = []
    for step in range(1, count + 1):
        t = step / count
        s = 1.0 - t
        a, b, c, d = s * s * s, 3 * s * s * t, 3 * s * t * t, t * t * t
        points.append((
            a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
        ))
    return points


class _Contour(list):
    """Points of one closed contour, the path items it came from, and whether
    the order of the points is the order the producer drew them in."""

    def __init__(self, points=(), indices=(), directed=True):
        super().__init__(points)
        self.indices = list(indices)
        self.directed = directed


def _contours(items):
    """Closed contours of a clip path, and whether any curve was flattened.

    PyMuPDF records a move only as the next segment's start point, so a segment
    that does not start where the previous one ended opens a new contour.

    A rectangle or quad item has lost its drawing direction: PyMuPDF's
    orientation flag follows the vertical sense of the second edge only, so the
    same flag is reported for both directions (checked against MuPDF's own
    nonzero rendering). Such contours are marked ``directed=False``.
    """
    contours = []
    current = _Contour()
    curved = False

    def flush():
        nonlocal current
        if len(current) >= 3:
            contours.append(current)
        current = _Contour()

    for index, item in enumerate(items):
        kind = item[0]
        if kind == "l":
            start, end = _xy(item[1]), _xy(item[2])
        elif kind == "c":
            start = _xy(item[1])
            end = None
        elif kind == "re":
            flush()
            box = _rect(item[1])
            if box is None:
                raise ValueError("clip path rectangle is not finite")
            contours.append(_Contour(
                [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])], [index], False))
            continue
        elif kind == "qu":
            flush()
            contours.append(_Contour(_quad_corners(item[1]), [index], False))
            continue
        else:
            raise ValueError(f"clip path item {kind!r} is not understood")
        if current and current[-1] != start:
            flush()
        if not current:
            current.append(start)
        current.indices.append(index)
        if kind == "l":
            current.append(end)
        else:
            curved = True
            current.extend(_flatten_cubic(start, _xy(item[2]), _xy(item[3]), _xy(item[4])))
        if len(current) > 2 and current[-1] == current[0]:
            # Back at its start: this subpath is closed. Two subpaths that begin at
            # the same corner must not be read as one figure-of-eight contour.
            flush()
    flush()
    for contour in contours:
        if len(contour) > 1 and contour[0] == contour[-1]:
            contour.pop()
    return [c for c in contours if len(c) >= 3], curved


def _clip_contour(points, box):
    """Sutherland-Hodgman: one closed contour cut to an axis-aligned rectangle."""
    edges = (
        (0, box[0], 1.0), (0, box[2], -1.0),
        (1, box[1], 1.0), (1, box[3], -1.0),
    )
    output = points
    for axis, limit, sign in edges:
        if not output:
            break
        source, output = output, []
        previous = source[-1]
        previous_inside = (previous[axis] - limit) * sign >= 0.0
        for point in source:
            inside = (point[axis] - limit) * sign >= 0.0
            if inside != previous_inside:
                span = point[axis] - previous[axis]
                t = (limit - previous[axis]) / span if span else 0.0
                crossing = [
                    previous[0] + t * (point[0] - previous[0]),
                    previous[1] + t * (point[1] - previous[1]),
                ]
                crossing[axis] = limit
                output.append(tuple(crossing))
            if inside:
                output.append(point)
            previous, previous_inside = point, inside
    cleaned = _Contour((), getattr(points, "indices", ()), getattr(points, "directed", True))
    for point in output:
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return cleaned if len(cleaned) >= 3 else []


def _path_bounds(items):
    """Bounding box of a clip path's own geometry.

    A nested clip row's ``scissor`` is already cut by its parents, so it says
    where the clip can show, not how far the path itself extends.
    """
    xs, ys = [], []
    for item in items:
        kind = item[0]
        if kind == "re":
            box = _rect(item[1])
            if box is None:
                return None
            xs += [box[0], box[2]]
            ys += [box[1], box[3]]
        elif kind == "qu":
            for x, y in _quad_corners(item[1]):
                xs.append(x)
                ys.append(y)
        elif kind in {"l", "c"}:
            for point in item[1:]:
                x, y = _xy(point)
                xs.append(x)
                ys.append(y)
        else:
            # A path operator this module does not know cannot be vouched for.
            raise ValueError(f"clip path item {kind!r} is not understood")
    if not xs or not all(math.isfinite(v) for v in xs + ys):
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _signed_area(points):
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def _inside(point, polygon):
    """Even-odd point-in-polygon; ``point`` is never on an edge when called."""
    x, y = point
    hit = False
    for index, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(index + 1) % len(polygon)]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _interior_point(polygon):
    """A point strictly inside a contour, clear of any edge it shares with a sibling.

    Contours cut to the same rectangle lie along the same cut line, so a vertex
    cannot stand in for the contour when asking which contour contains which.
    """
    size = max(
        max(p[0] for p in polygon) - min(p[0] for p in polygon),
        max(p[1] for p in polygon) - min(p[1] for p in polygon),
    )
    step = size * 1e-4
    for index, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(index + 1) % len(polygon)]
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= step:
            continue
        mid = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        normal = (-(y1 - y0) / length * step, (x1 - x0) / length * step)
        for sign in (1.0, -1.0):
            candidate = (mid[0] + sign * normal[0], mid[1] + sign * normal[1])
            if _inside(candidate, polygon):
                return candidate
    return None


# Pairwise contour and edge tests are quadratic; a clip path large enough to make
# that slow is dropped and reported instead of stalling the import.
_MAX_CROSSING_TESTS = 4_000_000


def _bounds(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _properly_cross(a, b, c, d):
    """True when segment ab passes through segment cd; touching or overlapping is not crossing.

    Contours cut to the same rectangle run along the same cut line, and nested
    rings may share a corner. Neither changes which ring is inside which.
    """
    def side(p, q, r):
        value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (value > 0) - (value < 0)

    s1, s2, s3, s4 = side(a, b, c), side(a, b, d), side(c, d, a), side(c, d, b)
    return s1 * s2 < 0 and s3 * s4 < 0


def _contours_cross(first, second, budget):
    """(crossed, tests spent). ``budget`` bounds the work; exceeding it counts as crossed."""
    spent = 0
    fb, sb = _bounds(first), _bounds(second)
    if fb[0] > sb[2] or sb[0] > fb[2] or fb[1] > sb[3] or sb[1] > fb[3]:
        return False, spent
    for index, a in enumerate(first):
        b = first[(index + 1) % len(first)]
        ax0, ax1 = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
        ay0, ay1 = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
        if ax1 < sb[0] or ax0 > sb[2] or ay1 < sb[1] or ay0 > sb[3]:
            continue
        for other_index, c in enumerate(second):
            d = second[(other_index + 1) % len(second)]
            spent += 1
            if spent > budget:
                return True, spent
            if max(c[0], d[0]) < ax0 or min(c[0], d[0]) > ax1 or max(c[1], d[1]) < ay0 or min(c[1], d[1]) > ay1:
                continue
            if _properly_cross(a, b, c, d):
                return True, spent
    return False, spent


_MAX_OVERLAP_TESTS = 200_000


def _any_cross(contours):
    """True when two contours properly cross (or the check ran out of budget)."""
    budget = _MAX_OVERLAP_TESTS
    for index, contour in enumerate(contours):
        for other in contours[index + 1:]:
            crossed, spent = _contours_cross(contour, other, budget)
            budget -= spent
            if crossed:
                return True
    return False


_CROSSING_DETAIL = ("the clip path's even-odd contours cross; the PDF leaves their overlap unpainted, "
                    "which a host that builds rings with counters may fill")


def _even_odd_rings(contours):
    """Rings whose even-odd fill equals the nonzero-winding fill of ``contours``.

    Hosts build a clipped fill from rings with counters; none of them runs a
    winding-aware tessellator. For contours that nest without crossing, the
    nonzero region is bounded by exactly those contours across which the
    winding number changes between zero and non-zero; keeping only those gives
    rings that nest filled/empty/filled, which is what even-odd draws. Returns
    None when the nesting cannot be established, so the caller does not guess.

    A contour whose drawing direction was lost (``directed=False``) counts as
    either direction; the answer is used only when it is the same both ways.
    """
    rings = []
    for contour in contours:
        area = _signed_area(contour)
        probe = _interior_point(contour) if area else None
        if probe is None:
            if abs(area) > 1e-9:
                return None
            continue  # a sliver with no interior paints nothing
        orientation = 1 if area > 0 else -1
        rings.append((contour, orientation if getattr(contour, "directed", True) else 0,
                      probe, _bounds(contour)))
    budget = _MAX_CROSSING_TESTS - len(rings) * len(rings)
    if budget < 0:
        return None
    for index, (contour, _, _, _) in enumerate(rings):
        for other, _, _, _ in rings[index + 1:]:
            crossed, spent = _contours_cross(contour, other, budget)
            budget -= spent
            if crossed:
                return None  # overlapping figures: nesting says nothing about their union
    kept = []
    for index, (contour, orientation, probe, _box) in enumerate(rings):
        outside = 0   # winding contributed by the directed contours around this one
        unknown = 0   # contours around this one whose direction was lost
        for other_index, (other, other_orientation, other_probe, other_box) in enumerate(rings):
            if other_index == index:
                continue
            if not (other_box[0] <= probe[0] <= other_box[2] and other_box[1] <= probe[1] <= other_box[3]):
                continue
            budget -= len(other)
            if budget < 0:
                return None
            if not _inside(probe, other):
                continue
            if _inside(other_probe, contour):
                return None  # each inside the other: the contours cross
            outside += other_orientation
            unknown += other_orientation == 0
        verdicts = {
            (winding != 0) != (winding + own != 0)
            for winding in range(outside - unknown, outside + unknown + 1, 2)
            for own in ((orientation,) if orientation else (1, -1))
        }
        if len(verdicts) != 1:
            return None  # solid or hole depends on a direction PyMuPDF did not keep
        if verdicts.pop():
            kept.append(contour)
    return kept


def _like_point(sample, x, y):
    """A point of the kind the source rows use, so consumers read it the same way."""
    if hasattr(sample, "x") and hasattr(sample, "y") and not isinstance(sample, tuple):
        try:
            return type(sample)(x, y)
        except Exception:
            pass
    return (x, y)


def _like_rect(sample, box):
    if hasattr(sample, "x0") and not isinstance(sample, tuple):
        try:
            return type(sample)(*box)
        except Exception:
            pass
    return tuple(box)


def _sample_point(items, row):
    """A point object of the kind the source rows use, to build emitted segments from.

    The extractor reads a two-point "l" item only when both ends carry ``.x``.
    A clip made only of rectangles or quads has no line point to copy, so the
    corner of one of its rectangles, or of the fill's own rectangle, stands in.
    """
    for item in items:
        if item[0] in {"l", "c"}:
            return item[1]
    for item in list(items) + list(row.get("items") or ()):
        corner = getattr(item[1], "tl", None) if item[0] == "re" else getattr(item[1], "ul", None)
        if corner is not None:
            return corner
    return None


def _items_finite(items):
    """False when any coordinate of a clip path is NaN or infinite."""
    try:
        for item in items:
            kind = item[0]
            if kind == "re":
                if _finite4(item[1]) is None:
                    return False
            elif kind == "qu":
                if not all(math.isfinite(v) for point in _quad_corners(item[1]) for v in point):
                    return False
            elif kind in {"l", "c"}:
                if not all(math.isfinite(v) for point in item[1:] for v in _xy(point)):
                    return False
    except (TypeError, ValueError, IndexError):
        return False
    return True


def _preserve_clip_outline_edges(rows):
    """Keep artwork strokes aligned with the exact clip fill they outline.

    A fitted circle can cross the polygon mask's counter and leave a crescent
    between them. Mark nearby source strokes to retain their actual vertices.
    The grid bounds the lookup work on dense sheets; source path items are
    never changed, including rows that do not intersect a mask.
    """
    bounds = [_rect(row.get("rect")) for row in rows if row.get("bcs_compound_clip_fill")]
    bounds = [box for box in bounds if box is not None]
    if not bounds:
        return rows
    cell = max(1.0, max(abs(v) for box in bounds for v in box) / 32.0)
    grid = {}
    for index, box in enumerate(bounds):
        for x in range(math.floor(box[0] / cell), math.floor(box[2] / cell) + 1):
            for y in range(math.floor(box[1] / cell), math.floor(box[3] / cell) + 1):
                grid.setdefault((x, y), []).append(index)
    xmin = min(key[0] for key in grid)
    xmax = max(key[0] for key in grid)
    ymin = min(key[1] for key in grid)
    ymax = max(key[1] for key in grid)
    output = []
    for row in rows:
        box = _rect(row.get("rect")) if row.get("type") in {"s", "fs"} else None
        overlap = False
        if box is not None:
            candidates = set()
            for x in range(max(xmin, math.floor(box[0] / cell)), min(xmax, math.floor(box[2] / cell)) + 1):
                for y in range(max(ymin, math.floor(box[1] / cell)), min(ymax, math.floor(box[3] / cell)) + 1):
                    candidates.update(grid.get((x, y), ()))
            overlap = any(
                box[0] <= bounds[i][2] and box[2] >= bounds[i][0]
                and box[1] <= bounds[i][3] and box[3] >= bounds[i][1]
                for i in candidates
            )
        if overlap:
            row = dict(row, bcs_preserve_source_edges=True)
        output.append(row)
    return output


def _finite_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _issue(row, seqno, reason, action, exact, detail):
    dropped = action.startswith("dropped")
    fill = row.get("fill")
    if isinstance(fill, (tuple, list)):
        fill = [_finite_or_none(v) for v in fill]
        fill = None if any(v is None for v in fill) else fill
    elif fill is not None:
        fill = _finite_or_none(fill)
    return {
        "seqno": seqno,
        "reason": reason,
        "action": action,
        "exact": bool(exact),
        # A fill the page never shows is not a loss; anything approximated or
        # dropped while visible is something the operator should hear about.
        "severity": "info" if exact and action != "dropped-unsupported" else "warning",
        "dropped": dropped,
        "detail": detail,
        "paint_rect": list(_rect(row.get("rect")) or ()),
        "fill": fill,
        "fill_opacity": _finite_or_none(row.get("fill_opacity", 1.0)),
    }


def _compound_fill(row, seqno, items, bounds, even_odd, resolution):
    replacement = dict(row)
    replacement.update(
        items=items,
        rect=bounds,
        even_odd=bool(even_odd),
        closePath=True,
        color=None,
        width=None,
        bcs_compound_clip_fill=True,
        bcs_clip_fill_group_id=f"clip-fill:{seqno}",
    )
    if resolution:
        replacement["bcs_clip_fill_resolution"] = resolution
    return replacement


def _path_key(clip):
    """Value identity of a clip path: producers push the same clip more than once."""
    key = [bool(clip.get("even_odd", False))]
    for item in clip["items"]:
        kind = item[0]
        if kind == "re":
            key.append((kind, _rect(item[1])))
        elif kind == "qu":
            key.append((kind, tuple(_quad_corners(item[1]))))
        else:
            key.append((kind,) + tuple(_xy(point) for point in item[1:]))
    return tuple(key)


def _covers(clip, box):
    """True when the clip path provably shows all of ``box``.

    Only one contour may reach the box, and cutting it to the box must give the
    box back; then no other contour can change what shows there under either
    fill rule.
    """
    contours, _ = _contours(clip["items"])
    pieces = [cut for cut in (_clip_contour(contour, box) for contour in contours) if cut]
    if len(pieces) != 1:
        return False
    area = (box[2] - box[0]) * (box[3] - box[1])
    return abs(abs(_signed_area(pieces[0])) - area) <= 1e-9 * max(1.0, area)


_MAX_GRID_TESTS = 400_000


def _axis_rectangle(contour):
    """(x0, y0, x1, y1) when the contour is an axis-aligned rectangle, else None."""
    if len(contour) != 4:
        return None
    xs = sorted({point[0] for point in contour})
    ys = sorted({point[1] for point in contour})
    if len(xs) != 2 or len(ys) != 2 or len(set(contour)) != 4:
        return None
    return (xs[0], ys[0], xs[1], ys[1])


def _rectangle_set_region(visible, clips):
    """Boundary loops of ``visible`` seen through clips made only of axis-aligned rectangles.

    Returns None when a clip is not such a set, when the work would be large, or
    when nonzero winding would depend on a direction the parser did not keep.
    Every coordinate that matters is an edge of some rectangle, so testing one
    point per grid cell decides the whole cell exactly.
    """
    masks = []
    for clip in clips:
        contours, curved = _contours(clip["items"])
        rectangles = [(_axis_rectangle(contour), contour) for contour in contours]
        if curved or not rectangles or any(box is None for box, _ in rectangles):
            return None
        masks.append((bool(clip.get("even_odd", False)), rectangles))
    xs = {visible[0], visible[2]}
    ys = {visible[1], visible[3]}
    for _, rectangles in masks:
        for box, _ in rectangles:
            xs.update(x for x in (box[0], box[2]) if visible[0] < x < visible[2])
            ys.update(y for y in (box[1], box[3]) if visible[1] < y < visible[3])
    xs, ys = sorted(xs), sorted(ys)
    if (len(xs) - 1) * (len(ys) - 1) * sum(len(rectangles) for _, rectangles in masks) > _MAX_GRID_TESTS:
        return None

    def shows(x, y):
        for even_odd, rectangles in masks:
            around = [contour for box, contour in rectangles
                      if box[0] < x < box[2] and box[1] < y < box[3]]
            if even_odd or len(around) < 2:
                if len(around) % 2 == 0 if even_odd else not around:
                    return False
                continue
            if not all(getattr(contour, "directed", True) for contour in around):
                return None
            if sum(1 if _signed_area(contour) > 0 else -1 for contour in around) == 0:
                return False
        return True

    inside = set()
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            verdict = shows((xs[i] + xs[i + 1]) / 2.0, (ys[j] + ys[j + 1]) / 2.0)
            if verdict is None:
                return None
            if verdict:
                inside.add((i, j))
    # Edges between a shown cell and a hidden one, walked with the shown side on the left.
    following = {}
    for i, j in inside:
        corners = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
        neighbours = ((i, j - 1), (i + 1, j), (i, j + 1), (i - 1, j))
        for side in range(4):
            if neighbours[side] not in inside:
                following.setdefault(corners[side], []).append(corners[(side + 1) % 4])
    loops = []
    while following:
        # Where two shown cells meet only at a corner, two edges leave that corner.
        # Turning towards the shown side keeps each loop simple instead of pinched.
        start = next((node for node, targets in following.items() if len(targets) == 1), None)
        if start is None:
            start = next(iter(following))
        loop, node, heading = [], start, None
        while True:
            loop.append(node)
            targets = following[node]
            if len(targets) > 1 and heading is not None:
                targets.sort(key=lambda t: heading[0] * (t[1] - node[1]) - heading[1] * (t[0] - node[0]))
            target = targets.pop()
            if not targets:
                del following[node]
            heading = (target[0] - node[0], target[1] - node[1])
            node = target
            if node == start:
                break
        points = [(xs[i], ys[j]) for i, j in loop]
        corners = [point for index, point in enumerate(points)
                   if (points[index - 1][0] == point[0]) != (point[0] == points[(index + 1) % len(points)][0])]
        if len(corners) >= 4:
            loops.append(corners)
    return loops


def _rectilinear_fill(row, seqno, reason, loops, clip):
    """(replacement, issue) for a region found on the rectangle grid."""
    if not loops:
        return None, _issue(row, seqno, reason, "dropped-invisible", True,
                            "nothing of the fill shows through its clips")
    if len(loops) == 1 and len(loops[0]) == 4:
        return _rectangle_fill(row, _bounds(loops[0])), _issue(
            row, seqno, reason, "rect-intersection", True, "rectangle cut to its rectangular clips")
    sample = _sample_point(clip["items"], row)
    items = [("l", _like_point(sample, *point), _like_point(sample, *loop[(index + 1) % len(loop)]))
             for loop in loops for index, point in enumerate(loop)]
    bounds = _like_rect(clip.get("scissor"), _bounds([point for loop in loops for point in loop]))
    return (_compound_fill(row, seqno, items, bounds, True, "polygon-rect"),
            _issue(row, seqno, reason, "polygon-rect", True,
                   "rectangle cut to clips that are sets of axis-aligned rectangles"))


def _rectangle_fill(row, visible):
    replacement = dict(row)
    source = row["items"][0]
    replacement.update(
        items=[("re", _like_rect(source[1], visible), source[2] if len(source) > 2 else 1)],
        rect=_like_rect(row.get("rect"), visible),
        bcs_clip_fill_resolution="rect-intersection",
    )
    return replacement


def _resolve_one(row, active, seqno):
    """(replacement row or None, issue or None) for one clipped rectangle fill."""
    paint = _rect(row.get("rect"))
    if paint is None:
        return None, _issue(row, seqno, "no-finite-bounds", "dropped-unsupported", False,
                            "the fill has no finite bounds")

    rectangles = []
    paths = []
    for clip in active:
        scissor = _rect(clip.get("scissor"))
        if scissor is None and _finite4(clip.get("scissor")) is not None:
            # PyMuPDF's scissor is the running intersection of the clip bounds; an
            # inverted one is that intersection coming up empty. Nothing shows.
            return None, _issue(row, seqno, "nested" if len(active) != 1 else "partial-cover",
                                "dropped-invisible", True, "an active clip is empty; nothing shows through it")
        if scissor is None or not clip.get("items") or not _items_finite(clip["items"]):
            # An empty, unbounded or non-finite clip row cannot be vouched for. What
            # shows through it is unknown, so the fill cannot be drawn honestly.
            return None, _issue(row, seqno, "no-finite-bounds", "dropped-unsupported", False,
                                "an active clip has no finite bounds, no path, or a non-finite point")
        if _single_rectangle(clip):
            rectangles.append(scissor)
        else:
            paths.append((clip, scissor))

    if not paths and all(_contains(box, paint) for box in rectangles):
        # A rectangle already inside rectangular masks is not clipped.
        return row, None

    if row.get("fill") is None:
        return None, _issue(row, seqno, "not-opaque", "dropped-invisible", True,
                            "the fill row carries no fill colour; nothing is painted")

    # What the first-generation resolver would have refused, kept as the reason
    # so a report reads the same way the old error messages did.
    if len(active) != 1:
        reason = "nested"
    elif paths and not _contains(paint, paths[0][1]):
        reason = "partial-cover"
    elif not paths:
        reason = "partial-cover"
    elif row.get("fill_opacity", 1.0) != 1.0:
        reason = "not-opaque"
    else:
        reason = None

    visible = paint
    for box in rectangles:
        visible = _intersection(visible, box)
        if visible is None:
            return None, _issue(row, seqno, reason or "partial-cover", "dropped-invisible", True,
                                "the fill lies wholly outside a rectangular clip")

    if not paths:
        return _rectangle_fill(row, visible), _issue(row, seqno, reason, "rect-intersection", True,
                                                     "rectangle cut to its rectangular clips")

    if len(paths) > 1:
        distinct = {}
        for clip, scissor in paths:
            distinct.setdefault(_path_key(clip), (clip, scissor))
        paths = list(distinct.values())
    if len(paths) > 1:
        # Whatever is painted lies inside every clip path's bounds. A path that
        # shows all of that region takes nothing away and can be set aside.
        region = visible
        for clip, _ in paths:
            own = _path_bounds(clip["items"])
            if own is None:
                return None, _issue(row, seqno, "no-finite-bounds", "dropped-unsupported", False,
                                    "an active clip path has no finite bounds")
            region = _intersection(region, own)
            if region is None:
                return None, _issue(row, seqno, reason, "dropped-invisible", True,
                                    "the active clip paths share no area with the fill")
        paths = [(clip, scissor) for clip, scissor in paths if not _covers(clip, region)]
        visible = region
        if not paths:
            return _rectangle_fill(row, visible), _issue(
                row, seqno, reason, "rect-intersection", True,
                "the visible rectangle lies inside every clip path")
    if len(paths) > 1:
        loops = _rectangle_set_region(visible, [clip for clip, _ in paths])
        if loops is None:
            return None, _issue(row, seqno, "nested", "dropped-unsupported", False,
                                f"{len(paths)} different non-rectangular clips are active; "
                                "their intersection is not computed")
        return _rectilinear_fill(row, seqno, reason, loops, paths[0][0])

    clip, scissor = paths[0]
    even_odd = bool(clip.get("even_odd", False))
    unprovable = ("the clip path fills by nonzero winding and its contours cross, or nest a "
                  "rectangle whose drawing direction the parser did not keep; the filled "
                  "region is not computed")
    own = _path_bounds(clip["items"]) if reason is not None else scissor
    # The plain case keeps the first resolver's exact rule. Every newly handled
    # case must contain the path's own extent: a parent clip can already have
    # cut the scissor down to something the path itself overruns.
    if own is not None and _contains(visible, own, _COVER_TOLERANCE):
        items = list(clip["items"])
        contours, _ = _contours(items)
        crossing = even_odd and len(contours) > 1 and _any_cross(contours)
        if len(contours) > 1 and not even_odd:
            # No host fills by nonzero winding; hand them rings that mean the same
            # under even-odd, made of the path's own items.
            rings = _even_odd_rings(contours)
            if rings is None:
                return None, _issue(row, seqno, reason or "nonzero-winding", "dropped-unsupported",
                                    False, unprovable)
            keep = sorted(index for ring in rings for index in ring.indices)
            items, even_odd = [items[index] for index in keep], True
            if not items:
                return None, _issue(row, seqno, reason or "nonzero-winding", "dropped-invisible",
                                    True, "the clip path encloses no area")
        replacement = _compound_fill(row, seqno, items, clip["scissor"], even_odd,
                                     None if reason is None else "clip-path")
        if crossing:
            return replacement, _issue(row, seqno, reason or "crossing-contours", "clip-path", False,
                                       _CROSSING_DETAIL)
        if reason is None:
            return replacement, None
        return replacement, _issue(row, seqno, reason, "clip-path", True,
                                   "the fill covers the whole clip path; the path is the painted shape")

    if _intersection(visible, scissor) is None:
        return None, _issue(row, seqno, reason, "dropped-invisible", True,
                            "the fill does not overlap its clip path")

    # Rectangles first: the grid returns clean loops, where cutting ring by ring
    # would leave a counter sharing an edge with the ring around it.
    loops = _rectangle_set_region(visible, [clip])
    if loops is not None:
        return _rectilinear_fill(row, seqno, reason, loops, clip)

    contours, curved = _contours(clip["items"])
    sample = _sample_point(clip["items"], row)
    pieces = [cut for cut in (_clip_contour(contour, visible) for contour in contours) if cut]
    crossing = even_odd and len(pieces) > 1 and _any_cross(pieces)
    if len(pieces) > 1 and not even_odd:
        rings = _even_odd_rings(pieces)
        if rings is None:
            return None, _issue(row, seqno, reason, "dropped-unsupported", False, unprovable)
        pieces, even_odd = rings, True
    if len(pieces) == 1:
        area = (visible[2] - visible[0]) * (visible[3] - visible[1])
        if abs(abs(_signed_area(pieces[0])) - area) <= 1e-9 * max(1.0, area):
            # The rectangle lies wholly inside the clip region: it is painted as drawn.
            return _rectangle_fill(row, visible), _issue(
                row, seqno, reason, "rect-intersection", True,
                "the visible rectangle lies inside the clip path")
    items = []
    xs, ys = [], []
    for cut in pieces:
        for index, point in enumerate(cut):
            following = cut[(index + 1) % len(cut)]
            items.append(("l", _like_point(sample, *point), _like_point(sample, *following)))
            xs.append(point[0])
            ys.append(point[1])
    if not items:
        return None, _issue(row, seqno, reason, "dropped-invisible", True,
                            "no part of the clip path lies inside the fill")
    bounds = _like_rect(clip.get("scissor"), (min(xs), min(ys), max(xs), max(ys)))
    action = "polygon-rect-flattened" if curved else "polygon-rect"
    replacement = _compound_fill(row, seqno, items, bounds, even_odd, action)
    detail = ("clip path cut to the visible rectangle; its curves were flattened to within "
              f"{_FLATTEN_TOLERANCE} pt") if curved else "clip path cut to the visible rectangle"
    if crossing:
        detail += "; " + _CROSSING_DETAIL
    return replacement, _issue(row, seqno, reason, action, not curved and not crossing, detail)


def resolve_covered_clip_fills(drawings, *, rows_from_page=False):
    """Return paint rows, resolving rectangle fills painted through clips.

    ``rows_from_page`` says the rows are exactly what ``get_drawings(extended=True)``
    returned, every clip and group row still in place. Only then can a rectangle
    fill nested deeper than the clip/group rows around it be recognised as painted
    through a clip PyMuPDF does not express (text, stroke-path and image-mask
    clips raise the level but leave no row) and be dropped instead of flooding.
    Resolved rows keep their levels after the structural rows are gone, so the
    rule must stay off for a second pass; that is the default.

    ``drawings`` is the result of ``get_drawings(extended=True)``. Clip/group
    rows are structural, not paint. Rows other than a clipped rectangle fill keep
    their geometry; overlapping artwork strokes are marked to prevent later
    circle fitting. A fill that cannot be resolved is dropped and recorded, never
    returned as its unclipped rectangle, and never a reason to raise. The caller
    owns the returned rows; input dictionaries/items are not changed. Running the
    resolver over its own output is a no-op, because clip rows do not survive it.
    """
    active = []
    groups = []
    resolved = []
    # Hosts hand the resolved rows back in (extract_page(drawings=...)); the clip
    # rows are gone by then, so what the first pass recorded is all there is.
    issues = clip_fill_issues(drawings)
    for index, row in enumerate(drawings):
        level = int(row.get("level", 0))
        active = [clip for clip in active if int(clip.get("level", 0)) < level]
        groups = [group for group in groups if int(group.get("level", 0)) < level]
        kind = row.get("type")
        if kind == "clip":
            active.append(row)
            continue
        if kind == "group":
            groups.append(row)
            continue
        unexpressed = rows_from_page and level > len(active) + len(groups)
        if not (active or unexpressed) or kind != "f" or not _single_rectangle(row):
            resolved.append(row)
            continue

        seqno = row.get("seqno", index)
        try:
            if unexpressed:
                replacement, issue = None, _issue(
                    row, seqno, "unexpressed-clip", "dropped-unsupported", False,
                    "the fill is painted through a clip the parser does not express (a text, "
                    "stroke or image-mask clip); what shows of it is unknown")
            else:
                replacement, issue = _resolve_one(row, active, seqno)
        except Exception as error:  # one malformed fill must not cost the page
            replacement = None
            issue = _issue(row, seqno, "resolver-error", "dropped-unsupported", False,
                           f"{type(error).__name__}: {error}")
        if replacement is not None:
            resolved.append(replacement)
        if issue is not None:
            issues.append(issue)
    return ClipAwareDrawings(_preserve_clip_outline_edges(resolved), issues)


def summarize_clip_fill_issues(issues):
    """One operator-readable sentence, or '' when every fill resolved plainly."""
    issues = list(issues or ())
    dropped = [i for i in issues if i.get("dropped") and i.get("severity") == "warning"]
    approximated = [i for i in issues if not i.get("dropped") and i.get("severity") == "warning"]
    if not dropped and not approximated:
        return ""
    parts = []
    if dropped:
        parts.append(f"{len(dropped)} clipped fill(s) could not be resolved and were left out")
    if approximated:
        parts.append(f"{len(approximated)} clipped fill(s) are approximate (flattened curves or crossing contours)")
    seqnos = ", ".join(str(i.get("seqno")) for i in (dropped + approximated)[:8])
    more = len(dropped) + len(approximated) - 8
    return "; ".join(parts) + f" (drawing order {seqnos}" + (f" and {more} more" if more > 0 else "") + ")"


def get_clip_aware_drawings(page):
    """Fetch extended drawing rows once, including the PDF clipping context."""
    extended = True
    try:
        rows = page.get_drawings(extended=True)
    except TypeError as error:
        # Older simple page adapters have no keyword parameter. Do not swallow
        # a TypeError raised inside the drawing parser itself.
        if "unexpected keyword argument 'extended'" not in str(error):
            raise
        rows = page.get_drawings()
        extended = False
    from .page_paint_bounds import page_visible_drawings
    # page_visible_drawings removes paint rows only; every clip and group row survives it.
    return resolve_covered_clip_fills(page_visible_drawings(page, rows), rows_from_page=extended)

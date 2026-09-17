"""Resolve the exact vector mask of a rectangle that completely paints a clip.

This is deliberately not a general polygon intersection engine. Ordinary paint
rows remain unchanged. A covered clip becomes one compound fill so consumers
can preserve its counters, rather than painting the clip's bounding rectangle.
"""
from __future__ import annotations

import math


class UnsupportedClipFillError(ValueError):
    """A clipped rectangle needs an intersection this resolver cannot prove."""


def _rect(value):
    try:
        coords = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if len(coords) != 4 or not all(math.isfinite(v) for v in coords):
        return None
    if coords[2] < coords[0] or coords[3] < coords[1]:
        return None
    return coords


def _contains(outer, inner):
    # MuPDF's single-precision coordinates can differ by a few ULPs after a
    # transform. One thousandth of a PDF point is below 0.4 micrometres at 1:1.
    tolerance = 0.001
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[2] >= inner[2] - tolerance
        and outer[3] >= inner[3] - tolerance
    )


def _single_rectangle(row):
    items = row.get("items") or []
    return len(items) == 1 and items[0][0] == "re"


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


def resolve_covered_clip_fills(drawings):
    """Return paint rows, resolving completely covered opaque clip fills.

    ``drawings`` is the result of ``get_drawings(extended=True)``. Clip/group
    rows are structural, not paint. Rows outside this bounded rectangle-fill
    operation keep their geometry; overlapping artwork strokes are marked to
    prevent later circle fitting. Do not describe this as general clipping
    support. Partial or nested intersections of candidate rectangle fills fail
    explicitly instead of returning an inaccurate bounding-box replacement.
    The caller owns the returned rows; input dictionaries/items are not changed.
    """
    active = []
    resolved = []
    for index, row in enumerate(drawings):
        level = int(row.get("level", 0))
        active = [clip for clip in active if int(clip.get("level", 0)) < level]
        kind = row.get("type")
        if kind == "clip":
            active.append(row)
            continue
        if kind == "group":
            continue
        if not active or kind != "f" or not _single_rectangle(row):
            resolved.append(row)
            continue

        paint_bounds = _rect(row.get("rect"))
        clip = active[-1]
        clip_bounds = _rect(clip.get("scissor"))
        seqno = row.get("seqno", index)
        if paint_bounds is None or clip_bounds is None or not clip.get("items"):
            raise UnsupportedClipFillError(f"Clipped fill {seqno} has no finite clip bounds/path")
        if all(
            _single_rectangle(parent)
            and _rect(parent.get("scissor")) is not None
            and _contains(_rect(parent.get("scissor")), paint_bounds)
            for parent in active
        ):
            # A rectangle already inside rectangular masks is not clipped.
            resolved.append(row)
            continue
        if len(active) != 1:
            raise UnsupportedClipFillError(f"Clipped fill {seqno} needs a nested vector intersection")
        if not _contains(paint_bounds, clip_bounds):
            raise UnsupportedClipFillError(f"Clipped fill {seqno} only partially covers its vector mask")
        if row.get("fill_opacity", 1.0) != 1.0 or row.get("fill") is None:
            raise UnsupportedClipFillError(f"Clipped fill {seqno} is not an opaque fill")

        replacement = dict(row)
        replacement.update(
            items=list(clip["items"]),
            rect=clip["scissor"],
            even_odd=bool(clip.get("even_odd", False)),
            closePath=True,
            color=None,
            width=None,
            bcs_compound_clip_fill=True,
            bcs_clip_fill_group_id=f"clip-fill:{seqno}",
        )
        resolved.append(replacement)
    return _preserve_clip_outline_edges(resolved)


def get_clip_aware_drawings(page):
    """Fetch extended drawing rows once, including the PDF clipping context."""
    try:
        rows = page.get_drawings(extended=True)
    except TypeError as error:
        # Older simple page adapters have no keyword parameter. Do not swallow
        # a TypeError raised inside the drawing parser itself.
        if "unexpected keyword argument 'extended'" not in str(error):
            raise
        rows = page.get_drawings()
    return resolve_covered_clip_fills(rows)

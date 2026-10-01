"""Reject only paints proven wholly outside the visible page or an active clip.

Stroke centerlines alone are insufficient: caps, joins and miters can still
touch the page. The renderer's complete paint bounds provide that evidence.
Axis-aligned, undashed, butt-capped single lines can also be cut exactly at
the page boundary. Other partially intersecting paths remain unchanged.
"""
from __future__ import annotations

import math


def _box(value):
    try:
        box = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[0] > box[2] or box[1] > box[3]:
        return None
    return box


def _outside(a, page):
    return a[2] < page[0] or a[0] > page[2] or a[3] < page[1] or a[1] > page[3]


def _extends_beyond(a, page):
    return a[0] < page[0] or a[1] < page[1] or a[2] > page[2] or a[3] > page[3]


def retain_visible_paints(drawings, page_bounds, bboxlog):
    """Preserve order/row identities except renderer-certified off-page paints."""
    bounds = _box(page_bounds)
    if bounds is None:
        return drawings
    kept = []
    expected = {"f": ("fill-path",), "s": ("stroke-path",), "fs": ("fill-path", "stroke-path")}
    for row in drawings:
        geometric = _box(row.get("rect"))
        kinds = expected.get(row.get("type"))
        seq = row.get("seqno")
        evidence = []
        if geometric is not None and _outside(geometric, bounds) and kinds and type(seq) is int and seq >= 0:
            for index, kind in enumerate(kinds):
                if seq + index >= len(bboxlog):
                    break
                entry = bboxlog[seq + index]
                if not isinstance(entry, (tuple, list)) or len(entry) < 2 or entry[0] != kind:
                    break
                paint = _box(entry[1])
                if paint is None or not _outside(paint, bounds):
                    break
                evidence.append(paint)
        if not kinds or len(evidence) != len(kinds):
            kept.append(row)
    return kept


def retain_clip_visible_paints(drawings, bboxlog):
    """Keep structural rows and any paint not proved outside an active scissor.

    A scissor bounds its clip; disjoint full renderer paint bounds therefore
    prove zero visible ink even for a nonrectangular clip. Touching or partially
    intersecting paint is deliberately unchanged. No centerline-only proof is
    sufficient because caps, miters or the stroke width can reach the clip.
    """
    active = []
    kept = []
    kinds = {"s": ("stroke-path",), "f": ("fill-path",),
             "fs": ("fill-path", "stroke-path")}
    for row in drawings:
        level = row.get("level", 0)
        if type(level) is not int or level < 0:
            return drawings  # malformed scope cannot authorize a removal
        active = [(depth, bounds) for depth, bounds in active if depth < level]
        if row.get("type") == "clip":
            bounds = _box(row.get("scissor"))
            if bounds is not None:
                active.append((level, bounds))
            kept.append(row)
            continue
        expected = kinds.get(row.get("type"))
        seq = row.get("seqno")
        paints = []
        if active and expected and type(seq) is int and seq >= 0:
            for offset, kind in enumerate(expected):
                if seq + offset >= len(bboxlog):
                    break
                entry = bboxlog[seq + offset]
                if not isinstance(entry, (tuple, list)) or len(entry) < 2 or entry[0] != kind:
                    break
                paint = _box(entry[1])
                if paint is None:
                    break
                paints.append(paint)
        if (not expected or len(paints) != len(expected)
                or not any(all(_outside(paint, clip) for paint in paints)
                           for _depth, clip in active)):
            kept.append(row)
    return kept


def clip_axis_page_lines(drawings, page_bounds, bboxlog):
    """Preserve the complete visible ink of simple lines crossing the page.

    Cutting a horizontal or vertical butt-capped line along its own axis
    does not change any ink inside the page. Its full transverse stroke
    width must be inside the page; round caps, dashes, diagonal/compound
    paths and absent renderer evidence are not covered by this proof.
    Source rows and their point objects are never mutated.
    """
    bounds = _box(page_bounds)
    if bounds is None:
        return drawings
    kept = []
    for row in drawings:
        replacement = row
        try:
            items = row.get("items", ())
            caps = row.get("lineCap")
            seq = row.get("seqno")
            width = float(row.get("width", float("nan")))
            if (row.get("type") != "s" or len(items) != 1
                    or len(items[0]) != 3 or items[0][0] != "l"
                    or not isinstance(caps, (tuple, list)) or len(caps) != 3
                    or any(type(cap) not in (int, float) or cap != 0 for cap in caps)
                    or str(row.get("dashes", "")).strip() != "[] 0"
                    or row.get("closePath") is not False
                    or not math.isfinite(width) or width <= 0
                    or type(seq) is not int or seq < 0 or seq >= len(bboxlog)):
                kept.append(row)
                continue
            entry = bboxlog[seq]
            if (not isinstance(entry, (tuple, list)) or len(entry) < 2
                    or entry[0] != "stroke-path"):
                kept.append(row)
                continue
            paint = _box(entry[1])
            start, end = items[0][1:]
            x0, y0 = map(float, start)
            x1, y1 = map(float, end)
            if (paint is None or not all(math.isfinite(v) for v in (x0, y0, x1, y1))
                    or not (paint[0] <= min(x0, x1) <= max(x0, x1) <= paint[2]
                            and paint[1] <= min(y0, y1) <= max(y0, y1) <= paint[3])):
                kept.append(row)
                continue
            radius = width / 2.0
            new_start, new_end = None, None
            if (y0 == y1 and bounds[1] <= y0 - radius
                    and y0 + radius <= bounds[3]
                    and min(x0, x1) < bounds[2] and max(x0, x1) > bounds[0]):
                new_start = (min(max(x0, bounds[0]), bounds[2]), y0)
                new_end = (min(max(x1, bounds[0]), bounds[2]), y1)
            elif (x0 == x1 and bounds[0] <= x0 - radius
                  and x0 + radius <= bounds[2]
                  and min(y0, y1) < bounds[3] and max(y0, y1) > bounds[1]):
                new_start = (x0, min(max(y0, bounds[1]), bounds[3]))
                new_end = (x1, min(max(y1, bounds[1]), bounds[3]))
            if new_start is not None and (new_start != (x0, y0) or new_end != (x1, y1)):
                def point_like(original, xy):
                    if isinstance(original, tuple):
                        return tuple(xy)
                    if isinstance(original, list):
                        return list(xy)
                    return type(original)(*xy)
                replacement = dict(row)
                replacement["items"] = [("l", point_like(start, new_start), point_like(end, new_end))]
                rectangle = (min(new_start[0], new_end[0]), min(new_start[1], new_end[1]),
                             max(new_start[0], new_end[0]), max(new_start[1], new_end[1]))
                original_rect = row.get("rect")
                replacement["rect"] = (type(original_rect)(rectangle)
                                       if original_rect is not None and not isinstance(original_rect, (tuple, list))
                                       else rectangle)
                replacement["page_line_clip_proof"] = {
                    "kind": "axis_butt_line_visible_page_intersection",
                    "source_seqno": seq, "page_bounds": bounds,
                    "source_points": ((x0, y0), (x1, y1)),
                    "delivered_points": (new_start, new_end),
                }
        except (AttributeError, IndexError, TypeError, ValueError, RuntimeError):
            replacement = row
        kept.append(replacement)
    return kept


def page_visible_drawings(page, drawings):
    try:
        rect = page.rect
        rotation = int(getattr(page, "rotation", 0))
        if rotation:
            rect = rect * page.derotation_matrix
        bounds = _box(rect)
        has_clips = any(row.get("type") == "clip" for row in drawings)
        if bounds is None or (not has_clips and not any(
                _box(row.get("rect")) is not None and _extends_beyond(_box(row["rect"]), bounds)
                for row in drawings if row.get("type") in ("f", "s", "fs"))):
            return drawings
        bboxlog = page.get_bboxlog()
        rows = retain_clip_visible_paints(drawings, bboxlog) if has_clips else drawings
        rows = retain_visible_paints(rows, bounds, bboxlog)
        return clip_axis_page_lines(rows, bounds, bboxlog)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        # Missing renderer evidence cannot justify deleting source paint.
        return drawings

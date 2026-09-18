"""Reject only paints proven wholly outside the PDF's visible page rectangle.

Stroke centerlines alone are insufficient: caps, joins and miters can still
touch the page. The renderer's complete paint bounds provide that evidence.
Partially intersecting paths are retained unchanged; this is not a general
path-clipping implementation.
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


def page_visible_drawings(page, drawings):
    try:
        rect = page.rect
        rotation = int(getattr(page, "rotation", 0))
        if rotation:
            rect = rect * page.derotation_matrix
        bounds = _box(rect)
        if bounds is None or not any(_box(row.get("rect")) is not None and _outside(_box(row["rect"]), bounds)
                                     for row in drawings if row.get("type") in ("f", "s", "fs")):
            return drawings
        return retain_visible_paints(drawings, bounds, page.get_bboxlog())
    except (AttributeError, TypeError, ValueError, RuntimeError):
        # Missing renderer evidence cannot justify deleting source paint.
        return drawings

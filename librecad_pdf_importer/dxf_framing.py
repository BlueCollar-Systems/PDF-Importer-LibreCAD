"""Persist a whole-drawing, straight-on modelspace view without moving entities."""
from __future__ import annotations

import math


def finite_bounds(minimum, maximum):
    """Read a valid XY extent, excluding DXF's unset inverted sentinel bounds."""
    try:
        x0, y0 = tuple(minimum)[:2]
        x1, y1 = tuple(maximum)[:2]
        bounds = tuple(float(value) for value in (x0, y0, x1, y1))
    except (TypeError, ValueError):
        return None
    x0, y0, x1, y1 = bounds
    if not all(math.isfinite(value) for value in bounds) or x0 > x1 or y0 > y1:
        return None
    return bounds


def union_bounds(first, second):
    if first is None:
        return second
    if second is None:
        return first
    return (min(first[0], second[0]), min(first[1], second[1]),
            max(first[2], second[2]), max(first[3], second[3]))


def frame_modelspace(doc, bounds):
    """Set page extents and an untwisted +Z view which contains both dimensions."""
    valid = finite_bounds(bounds[:2], bounds[2:])
    if valid is None:
        raise ValueError("Cannot frame non-finite or inverted drawing bounds")
    x0, y0, x1, y1 = valid
    msp = doc.modelspace()
    extmin, extmax = (x0, y0, 0.0), (x1, y1, 0.0)
    msp.dxf.extmin, msp.dxf.extmax = extmin, extmax
    msp.dxf.limmin, msp.dxf.limmax = (x0, y0), (x1, y1)
    doc.header["$EXTMIN"], doc.header["$EXTMAX"] = extmin, extmax
    doc.header["$LIMMIN"], doc.header["$LIMMAX"] = (x0, y0), (x1, y1)
    current = doc.viewports.get("*Active")
    aspect = float(current[0].dxf.aspect_ratio) if current else 1.34
    if not math.isfinite(aspect) or aspect <= 0:
        aspect = 1.34
    height = max(1.0, y1 - y0, (x1 - x0) / aspect) * 1.1
    # LibreCAD 2.2's RS_FilterDXFRW::addVport reconstructs the pixel offset
    # as window_size - 2 * center * factor; writeVports uses its inverse.
    # Consequently its saved center is half the visible upper-right world
    # corner, not the standard DXF geometric center. Encode that convention
    # without moving geometry. At a different window aspect the importer
    # expands the visible range left/down, retaining the complete batch.
    # https://github.com/LibreCAD/LibreCAD/blob/v2.2.1.5/librecad/src/lib/filters/rs_filterdxfrw.cpp
    center = ((x0 + x1 + height * aspect) / 4,
              (y0 + y1 + height) / 4)
    doc.set_modelspace_vport(height, center=center,
                            dxfattribs={"aspect_ratio": aspect,
                                        "direction": (0, 0, 1),
                                        "target": (0, 0, 0),
                                        "view_twist": 0, "view_mode": 0})

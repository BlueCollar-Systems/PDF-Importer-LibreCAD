# -*- coding: utf-8 -*-
# dxf_builder.py -- Convert pdfcadcore Primitives to ezdxf DXF entities
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Translates a list of :class:`PageData` objects produced by *pdfcadcore* into
an :mod:`ezdxf` ``Drawing``.  Handles geometry mapping, layers, colors,
line-weights, and dash-pattern linetypes.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import ezdxf
from ezdxf import colors as ezdxf_colors
from ezdxf import bbox as ezdxf_bbox
from ezdxf.units import MM

from dataclasses import replace as _dc_replace

from pdfcadcore.primitives import PageData, Primitive
from pdfcadcore.import_config import ImportConfig

from dxf_text_builder import build_text

# ---------------------------------------------------------------------------
# DXF version string -> ezdxf ``dxfversion`` keyword
# ---------------------------------------------------------------------------
_VERSION_MAP: Dict[str, str] = {
    "R12":   "R12",
    "R2000": "R2000",
    "R2004": "R2004",
    "R2007": "R2007",
    "R2010": "R2010",
    "R2013": "R2013",
    "R2018": "R2018",
}

# Standard linetypes that mirror common dash patterns
_STANDARD_LINETYPES: List[Tuple[str, str, List[float]]] = [
    # (name, description, pattern_elements)
    # Pattern elements: positive = dash, negative = gap, 0 = dot
    ("DASHED",   "Dashed __ __ __",        [0.75, -0.25]),
    ("DOTTED",   "Dotted . . . .",         [0.05, -0.25]),
    ("DASHDOT",  "Dash-dot __ . __ .",     [0.75, -0.25, 0.0, -0.25]),
    ("DASHDOTDOT", "Dash-dot-dot __ . . ", [0.75, -0.25, 0.0, -0.25, 0.0, -0.25]),
    ("CENTER",   "Center ____ _ ____ _",   [1.25, -0.25, 0.25, -0.25]),
    ("PHANTOM",  "Phantom ____ _ _ ____",  [1.25, -0.25, 0.25, -0.25, 0.25, -0.25]),
]


# ---------------------------------------------------------------------------
# ACI (AutoCAD Color Index) helpers
# ---------------------------------------------------------------------------
# Basic ACI mapping for R12 which lacks true-color support
_ACI_TABLE: List[Tuple[int, int, int, int]] = [
    (255, 0,   0,   1),   # red
    (255, 255, 0,   2),   # yellow
    (0,   255, 0,   3),   # green
    (0,   255, 255, 4),   # cyan
    (0,   0,   255, 5),   # blue
    (255, 0,   255, 6),   # magenta
    (255, 255, 255, 7),   # white / default
    (128, 128, 128, 8),   # gray
    (192, 192, 192, 9),   # light gray
]


def _rgb_to_aci(r: float, g: float, b: float) -> int:
    """Convert RGB (0-1 floats) to the nearest AutoCAD Color Index."""
    ri, gi, bi = round(r * 255), round(g * 255), round(b * 255)
    # Near-white -> 7 (renders as white on dark bg / black on light bg)
    if ri > 245 and gi > 245 and bi > 245:
        return 7
    best_aci = 7
    best_dist = float("inf")
    for cr, cg, cb, idx in _ACI_TABLE:
        d = (ri - cr) ** 2 + (gi - cg) ** 2 + (bi - cb) ** 2
        if d < best_dist:
            best_dist = d
            best_aci = idx
    return best_aci


def _true_color_int(r: float, g: float, b: float) -> int:
    """Pack RGB (0-1 floats) into a 24-bit DXF true-color integer."""
    ri, gi, bi = round(r * 255), round(g * 255), round(b * 255)
    # Invert near-white to black for visibility on light backgrounds.
    luminance = 0.299 * ri + 0.587 * gi + 0.114 * bi
    if luminance > 230:
        ri, gi, bi = 0, 0, 0
    return ezdxf_colors.rgb2int((ri, gi, bi))


# ---------------------------------------------------------------------------
# Dash-pattern classification
# ---------------------------------------------------------------------------
def _classify_dash(pattern: list | None) -> str | None:
    """Return the best-matching standard linetype name for *pattern*."""
    if not pattern:
        return None
    total = sum(abs(v) for v in pattern if isinstance(v, (int, float)))
    if total < 0.01:
        return None
    n = len(pattern)
    if n == 1:
        return "DASHED"
    if n == 2:
        dash, gap = abs(pattern[0]), abs(pattern[1])
        if dash < 0.01:
            return "DOTTED"
        if gap > dash * 2.0:
            return "DASHED"
        return "CENTER"  # Short gap relative to dash -> center line style
    if n == 4:
        # dash-gap-dot-gap  or  dash-gap-dash-gap
        if abs(pattern[2]) < 0.05:
            return "DASHDOT"
        return "CENTER"
    if n >= 6:
        dots = sum(1 for v in pattern if abs(v) < 0.05)
        if dots >= 2:
            return "DASHDOTDOT"
        return "PHANTOM"
    return "DASHED"


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------
def _safe_layer_name(name: str) -> str:
    """Sanitise a string for use as a DXF layer name."""
    # DXF forbids: <>/\":;?*|=`
    for ch in '<>/\\":;?*|=`':
        name = name.replace(ch, "_")
    return name.strip() or "0"


def _ensure_layer(
    doc: ezdxf.document.Drawing,
    name: str,
    color: int | None = None,
    true_color: int | None = None,
) -> None:
    """Create layer *name* if it does not already exist."""
    if name not in doc.layers:
        kwargs: dict = {}
        if color is not None:
            kwargs["color"] = color
        if true_color is not None:
            kwargs["true_color"] = true_color
        doc.layers.add(name, dxfattribs=kwargs)


# ---------------------------------------------------------------------------
# Entity attribute builder
# ---------------------------------------------------------------------------
def _make_attribs(
    prim: Primitive,
    layer_name: str,
    config: ImportConfig,
    is_r12: bool,
) -> dict:
    """Build the ``dxfattribs`` dict for an ezdxf entity."""
    attribs: dict = {"layer": layer_name}

    # Color — prefer fill for fill-only shapes (stroke may be absent/None).
    rgb = prim.fill_color or prim.stroke_color
    if config.group_by_color and rgb:
        r, g, b = rgb
        if is_r12:
            attribs["color"] = _rgb_to_aci(r, g, b)
        else:
            attribs["true_color"] = _true_color_int(r, g, b)

    # Lineweight (in 1/100 mm, clamped to DXF valid range 0..211)
    # Backward compatible with either attribute spelling.
    assign_lw = bool(
        getattr(config, "assign_linewidth", getattr(config, "assign_lineweight", True))
    )
    if assign_lw and prim.line_width and not is_r12:
        # Convert line_width from points to mm, then to DXF 1/100mm units.
        # DXF lineweight 0 means "bylayer"; minimum valid weight is 5 (0.05mm).
        width_mm = float(prim.line_width) * (25.4 / 72.0)
        lw = int(max(5, min(211, round(width_mm * 100))))
        attribs["lineweight"] = lw

    return attribs


# ---------------------------------------------------------------------------
# Geometry writers
# ---------------------------------------------------------------------------
def _add_line(msp, prim: Primitive, attribs: dict) -> int:
    """Add a LINE entity. Returns 1."""
    p0, p1 = prim.points[0], prim.points[1]
    msp.add_line(start=p0, end=p1, dxfattribs=attribs)
    return 1


def _has_curvature(points, threshold=0.1) -> bool:
    """Check if a polyline has significant curvature (not just straight segments).

    Returns True if at least 3 consecutive-segment angle changes exceed
    *threshold* (~6 degrees), indicating the polyline likely originated
    from Bezier linearisation rather than straight-line geometry.
    """
    if len(points) < 4:
        return False
    angle_changes = 0
    for i in range(1, len(points) - 1):
        dx1 = points[i][0] - points[i - 1][0]
        dy1 = points[i][1] - points[i - 1][1]
        dx2 = points[i + 1][0] - points[i][0]
        dy2 = points[i + 1][1] - points[i][1]
        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 > 0.01 and len2 > 0.01:
            cross = dx1 * dy2 - dy1 * dx2
            sin_angle = cross / (len1 * len2)
            if abs(sin_angle) > threshold:  # >~6 degrees
                angle_changes += 1
    return angle_changes >= 3  # At least 3 direction changes = curved


def _add_polyline(msp, prim: Primitive, attribs: dict) -> int:
    """Add an LWPOLYLINE, or a SPLINE for curved polylines. Returns 1."""
    # For open, dense polylines with curvature, use SPLINE for better
    # Bezier fidelity in downstream CAD programs.
    if not prim.closed and len(prim.points) >= 8 and _has_curvature(prim.points):
        try:
            points_3d = [(x, y, 0) for x, y in prim.points]
            msp.add_spline(points_3d, dxfattribs=attribs)
            return 1
        except Exception:
            pass  # Fall through to LWPOLYLINE
    msp.add_lwpolyline(
        prim.points,
        close=prim.closed,
        dxfattribs=attribs,
    )
    return 1


def _add_arc(msp, prim: Primitive, attribs: dict) -> int:
    """Add an ARC entity (angles in degrees). Returns 1."""
    if prim.center is None or prim.radius is None:
        return _add_polyline(msp, prim, attribs)
    start = prim.start_angle or 0.0
    end = prim.end_angle or 360.0
    # Degenerate arc (start == end) -> treat as full circle to avoid
    # zero-length entity that confuses some CAD viewers.
    if math.isclose(start, end, abs_tol=1e-6):
        end = (end + 359.999) % 360.0
    msp.add_arc(
        center=prim.center,
        radius=prim.radius,
        start_angle=start,
        end_angle=end,
        dxfattribs=attribs,
    )
    return 1


def _add_circle(msp, prim: Primitive, attribs: dict) -> int:
    """Add a CIRCLE entity. Returns 1."""
    if prim.center is None or prim.radius is None:
        return _add_polyline(msp, prim, attribs)
    msp.add_circle(
        center=prim.center,
        radius=prim.radius,
        dxfattribs=attribs,
    )
    return 1


def _add_closed_loop(msp, prim: Primitive, attribs: dict) -> int:
    """Add a closed LWPOLYLINE. Returns 1."""
    msp.add_lwpolyline(prim.points, close=True, dxfattribs=attribs)
    return 1


def _add_rect(msp, prim: Primitive, attribs: dict) -> int:
    """Add a rectangle as a closed LWPOLYLINE (4 corners). Returns 1."""
    pts = prim.points
    if len(pts) < 4:
        return _add_polyline(msp, prim, attribs)
    msp.add_lwpolyline(pts[:4], close=True, dxfattribs=attribs)
    return 1


# Dispatch table: primitive type -> writer function
_WRITERS = {
    "line":        _add_line,
    "polyline":    _add_polyline,
    "arc":         _add_arc,
    "circle":      _add_circle,
    "closed_loop": _add_closed_loop,
    "rect":        _add_rect,
}


# ---------------------------------------------------------------------------
# DXF framing (LibreCAD / QCAD auto-zoom on open)
# ---------------------------------------------------------------------------
def _apply_dxf_framing(
    doc: ezdxf.document.Drawing,
    pages_data: List[PageData],
    stack_multiplier: float = 1.2,
) -> None:
    """Set $EXTMIN/$EXTMAX, limits, and modelspace VPORT for host auto-fit."""
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    def _track(x: float, y: float) -> None:
        nonlocal min_x, min_y, max_x, max_y
        min_x = min(min_x, float(x))
        min_y = min(min_y, float(y))
        max_x = max(max_x, float(x))
        max_y = max(max_y, float(y))

    stack_y = 0.0
    for page in pages_data:
        dy = stack_y
        _track(0.0, dy)
        _track(float(page.width), float(page.height) + dy)
        for ti in page.text_items:
            _track(ti.insertion[0], ti.insertion[1] + dy)
            if ti.bbox:
                x0, y0, x1, y1 = ti.bbox
                _track(x0, y0 + dy)
                _track(x1, y1 + dy)
        stack_y -= float(page.height) * stack_multiplier

    msp = doc.modelspace()
    ext = ezdxf_bbox.extents(msp)
    if ext.has_data:
        _track(ext.extmin.x, ext.extmin.y)
        _track(ext.extmax.x, ext.extmax.y)

    if min_x > max_x or min_y > max_y:
        return

    extmin = (float(min_x), float(min_y), 0.0)
    extmax = (float(max_x), float(max_y), 0.0)
    msp.dxf.extmin = extmin
    msp.dxf.extmax = extmax
    msp.dxf.limmin = (float(min_x), float(min_y))
    msp.dxf.limmax = (float(max_x), float(max_y))
    doc.header["$EXTMIN"] = extmin
    doc.header["$EXTMAX"] = extmax
    doc.header["$LIMMIN"] = (float(min_x), float(min_y))
    doc.header["$LIMMAX"] = (float(max_x), float(max_y))
    center = (
        (float(min_x) + float(max_x)) * 0.5,
        (float(min_y) + float(max_y)) * 0.5,
    )
    height = max(1.0, float(max_y) - float(min_y))
    width = max(1.0, float(max_x) - float(min_x))
    doc.set_modelspace_vport(max(height, width) * 1.1, center=center)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_dxf(
    pages_data: List[PageData],
    config: ImportConfig,
    dxf_version: str = "R2010",
) -> ezdxf.document.Drawing:
    """Build an ezdxf ``Drawing`` from a list of :class:`PageData`.

    Parameters
    ----------
    pages_data:
        One :class:`PageData` per converted PDF page.
    config:
        Import configuration controlling color, text, dash mapping, etc.
    dxf_version:
        Target DXF version string (e.g. ``"R2010"``).

    Returns
    -------
    ezdxf.document.Drawing
        The fully-built DXF document, ready for ``doc.saveas(path)``.
    """
    ver = _VERSION_MAP.get(dxf_version, "R2010")
    is_r12 = ver == "R12"

    doc = ezdxf.new(dxfversion=ver)
    doc.units = MM
    doc.header["$INSUNITS"] = 4  # millimeters
    msp = doc.modelspace()

    # Register standard linetypes (skip for R12 -- limited support)
    if not is_r12 and config.map_dashes:
        for lt_name, lt_desc, lt_pattern in _STANDARD_LINETYPES:
            if lt_name not in doc.linetypes:
                doc.linetypes.add(
                    lt_name,
                    pattern=lt_pattern,
                    description=lt_desc,
                )

    entity_count = 0
    text_count = 0

    # Multi-page stacking: shift each page downward by accumulated heights.
    _stack_offset_y = 0.0
    _STACK_MULTIPLIER = 1.2  # 20% gap between pages

    for page in pages_data:
        page_layer = _safe_layer_name(f"Page_{page.page_number}")
        _ensure_layer(doc, page_layer)

        # Track OCG layers already created for this page
        ocg_created: set[str] = set()

        # Create a hatch layer if hatch_mode is "group"
        hatch_layer = _safe_layer_name(f"Hatch_Page_{page.page_number}")
        hatch_layer_created = False

        dy = _stack_offset_y

        for _raw_prim in page.primitives:
            # Apply page stacking offset (non-destructive copy)
            if dy != 0.0:
                prim = _dc_replace(
                    _raw_prim,
                    points=[(x, y + dy) for x, y in _raw_prim.points],
                    center=(_raw_prim.center[0], _raw_prim.center[1] + dy) if _raw_prim.center else None,
                    bbox=(_raw_prim.bbox[0], _raw_prim.bbox[1] + dy, _raw_prim.bbox[2], _raw_prim.bbox[3] + dy) if _raw_prim.bbox else None,
                )
            else:
                prim = _raw_prim

            # Determine layer name
            if "hatch_line" in prim.generic_tags:
                # Place hatch entities on a dedicated Hatch layer
                if not hatch_layer_created:
                    _ensure_layer(doc, hatch_layer)
                    hatch_layer_created = True
                layer = hatch_layer
            elif prim.layer_name:
                layer = _safe_layer_name(prim.layer_name)
                if layer not in ocg_created:
                    _ensure_layer(doc, layer)
                    ocg_created.add(layer)
            else:
                layer = page_layer

            attribs = _make_attribs(prim, layer, config, is_r12)

            # Linetype from dash pattern
            if config.map_dashes and prim.dash_pattern and not is_r12:
                lt = _classify_dash(prim.dash_pattern)
                if lt and lt in doc.linetypes:
                    attribs["linetype"] = lt

            writer = _WRITERS.get(prim.type, _add_polyline)
            entity_count += writer(msp, prim, attribs)

        # Text entities — editable TEXT for labels/3d_text; geometry mode skips TEXT
        if config.import_text and config.text_mode not in ("none", "geometry"):
            for ti in page.text_items:
                # Apply page stacking offset to text insertion point
                if dy != 0.0:
                    ti = _dc_replace(
                        ti,
                        insertion=(ti.insertion[0], ti.insertion[1] + dy),
                    )
                layer = page_layer
                build_text(
                    ti,
                    msp,
                    layer,
                    config,
                    is_r12,
                    target_app="librecad",
                    dxf_version=dxf_version,
                )
                text_count += 1

        # Advance stacking offset for the next page
        _stack_offset_y -= page.height * _STACK_MULTIPLIER

    _apply_dxf_framing(doc, pages_data, stack_multiplier=_STACK_MULTIPLIER)
    return doc, entity_count, text_count

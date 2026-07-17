# -*- coding: utf-8 -*-
"""Preserve PDF nominal text height for native host text modes.

Glyph bboxes are useful for placement, hit testing, and diagnostics, but they
are not the text size. Editable host text (Draft labels, ShapeStrings, Blender
font curves, DXF TEXT) must use the PDF nominal font height exactly once so an
imported page matches a PDF viewer at the same scale.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional, Tuple

_DEFAULT_FONT_PT = 3.0


def span_bbox_pdf(span: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """Return a normalized PDF user-space bbox for one span, if available."""
    bbox = span.get("bbox")
    if bbox and len(bbox) >= 4:
        try:
            x0, y0, x1, y1 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            return None
        vals = (x0, y0, x1, y1)
        if not all(math.isfinite(v) for v in vals):
            return None
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    return None


def normalize_text_angle_deg(angle_deg: float) -> float:
    """Map arbitrary degrees into [-90, 90] for axis selection."""
    angle = float(angle_deg)
    while angle <= -90.0:
        angle += 180.0
    while angle > 90.0:
        angle -= 180.0
    return angle


def bbox_glyph_height_pt(
    bbox: Tuple[float, float, float, float],
    angle_deg: float = 0.0,
) -> float:
    """Return glyph height in PDF points from an axis-aligned span bbox."""
    x0, y0, x1, y1 = bbox
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    if width <= 1e-9 and height <= 1e-9:
        return 0.0
    norm = abs(normalize_text_angle_deg(angle_deg))
    if norm >= 45.0:
        return min(width, height) if width > 1e-9 and height > 1e-9 else max(width, height)
    return height if height > 1e-9 else width


def bbox_glyph_width_pt(
    bbox: Tuple[float, float, float, float],
    angle_deg: float = 0.0,
) -> float:
    """Return glyph run width in PDF points from an axis-aligned span bbox."""
    x0, y0, x1, y1 = bbox
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    if width <= 1e-9 and height <= 1e-9:
        return 0.0
    norm = abs(normalize_text_angle_deg(angle_deg))
    if norm >= 45.0:
        return max(width, height)
    return width if width > 1e-9 else height


def effective_span_font_size_pt(
    span: Dict[str, Any],
    angle_deg: float = 0.0,
) -> float:
    """Return the nominal PDF font size in points.

    ``angle_deg`` is accepted for compatibility with older callers. It must not
    influence size; bboxes and rotation are placement data.
    """
    del angle_deg
    size_pt = _positive_span_number(span, ("nominal_size", "font_size", "size"))
    if size_pt is not None:
        return size_pt

    raw_pt = _positive_span_number(span, ("raw_size", "raw_font_size", "tf_size"))
    matrix = _span_text_matrix(span)
    if raw_pt is not None and matrix is not None:
        return effective_font_size_from_text_matrix(raw_pt, matrix)
    if raw_pt is not None:
        return raw_pt
    return _DEFAULT_FONT_PT


def _default_estimate_text_width_units(text: str) -> float:
    units = 0.0
    for ch in str(text or ""):
        if ch.isdigit():
            units += 0.55
        elif ch in " /'-\".":
            units += 0.30
        elif ch in "MW@#%":
            units += 0.95
        else:
            units += 0.65
    return units


def estimate_text_width_units(text: str) -> float:
    """Return an approximate width, in font-size units, for one text run."""
    return _default_estimate_text_width_units(text)


def calibrate_text_size_to_bbox(
    text: str,
    font_size: float,
    bbox: Optional[Tuple[float, float, float, float]],
    angle_deg: float = 0.0,
    *,
    min_size: float = 0.1,
    estimate_width_units: Optional[Callable[[str], float]] = None,
) -> float:
    """Return host text size without bbox-derived calibration.

    Kept as a compatibility shim for older host code. ``bbox`` and
    ``estimate_width_units`` are intentionally ignored so native text height
    remains tied to the nominal PDF size.
    """
    del text, bbox, angle_deg, estimate_width_units
    try:
        fitted = float(font_size)
    except (TypeError, ValueError):
        return font_size
    if fitted <= 0.0:
        return fitted
    del min_size
    return fitted


def fit_font_size_to_span_bbox(
    text: str,
    font_size_host: float,
    span: Dict[str, Any],
    scale: float,
    angle_deg: float = 0.0,
    estimate_width_units: Optional[Callable[[str], float]] = None,
) -> float:
    """Return host text size without fitting it to span bbox.

    This compatibility shim prevents older renderer paths from shrinking or
    growing native text after the extractor has already supplied nominal size.
    """
    del text, span, scale, angle_deg, estimate_width_units
    try:
        fitted = float(font_size_host)
    except (TypeError, ValueError):
        return font_size_host
    if fitted <= 0.0:
        return fitted
    return fitted


def _positive_span_number(span: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for key in keys:
        try:
            value = float(span.get(key, 0.0) or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(value) and value > 0.0:
            return value
    return None


def _span_text_matrix(span: Dict[str, Any]) -> Optional[Tuple[float, ...]]:
    for key in ("text_matrix", "matrix", "transform", "trm"):
        value = span.get(key)
        if value and len(value) >= 4:
            try:
                matrix = tuple(float(v) for v in value[:6])
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(v) for v in matrix[:4]):
                return matrix
    return None


def text_matrix_scale_factors(text_matrix: Tuple[float, ...]) -> Tuple[float, float]:
    """Return (along, normal) scale magnitudes from a PDF text matrix."""
    if not text_matrix or len(text_matrix) < 4:
        return 1.0, 1.0
    a, b, c, d = (
        float(text_matrix[0]),
        float(text_matrix[1]),
        float(text_matrix[2]),
        float(text_matrix[3]),
    )
    along = math.hypot(a, b)
    normal = math.hypot(c, d)
    return along, normal


def effective_font_size_from_text_matrix(
    font_size: float,
    text_matrix: Tuple[float, ...],
) -> float:
    """Compute text height from the text-matrix vertical axis."""
    along, normal = text_matrix_scale_factors(text_matrix)
    scale = normal if normal >= 1e-6 else along
    if scale < 1e-6:
        return float(font_size)
    return float(font_size) * scale


__all__ = [
    "bbox_glyph_height_pt",
    "bbox_glyph_width_pt",
    "calibrate_text_size_to_bbox",
    "effective_font_size_from_text_matrix",
    "effective_span_font_size_pt",
    "estimate_text_width_units",
    "fit_font_size_to_span_bbox",
    "normalize_text_angle_deg",
    "span_bbox_pdf",
    "text_matrix_scale_factors",
]

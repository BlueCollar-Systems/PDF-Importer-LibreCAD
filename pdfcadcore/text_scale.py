# -*- coding: utf-8 -*-
"""Reconcile PDF text font size (Tf) with span bbox / CTM effects.

Shop drawings often apply non-uniform or nested transforms so ``span.size``
from PyMuPDF can disagree with the measured span bbox.  Host renderers that
map Tf directly into model space (ShapeString, Blender curves, DXF TEXT height)
will look too large or too small when only one side of that relationship is
honored.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, Optional, Tuple

# Ratio thresholds — tuned on synthetic CTM fixtures and prior shop-drawing QA.
_BBOX_SIZE_LOW_RATIO = 0.75
_BBOX_SIZE_HIGH_RATIO = 1.35
_BBOX_FIT_MARGIN = 0.96
_MIN_FONT_PT = 1.0


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
    """Pick a PDF font size reconciled with the span bbox when they diverge."""
    try:
        size_pt = max(float(span.get("size", 0.0) or 0.0), 0.0)
    except (TypeError, ValueError):
        size_pt = 0.0
    if size_pt <= 0.0:
        size_pt = 3.0

    bbox = span_bbox_pdf(span)
    if not bbox:
        return max(size_pt, _MIN_FONT_PT)

    bbox_h = bbox_glyph_height_pt(bbox, angle_deg)
    if bbox_h <= 1e-6:
        return max(size_pt, _MIN_FONT_PT)

    ratio = bbox_h / size_pt
    if ratio >= _BBOX_SIZE_HIGH_RATIO or ratio <= _BBOX_SIZE_LOW_RATIO:
        return max(bbox_h * _BBOX_FIT_MARGIN, _MIN_FONT_PT)
    return max(size_pt, _MIN_FONT_PT)


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


def fit_font_size_to_span_bbox(
    text: str,
    font_size_host: float,
    span: Dict[str, Any],
    scale: float,
    angle_deg: float = 0.0,
    estimate_width_units: Optional[Callable[[str], float]] = None,
) -> float:
    """Clamp (and when needed grow) host font size to match the PDF span bbox."""
    try:
        fitted = float(font_size_host)
    except (TypeError, ValueError):
        return font_size_host
    if fitted <= 0.0:
        return fitted

    bbox = span_bbox_pdf(span)
    if not bbox:
        return max(0.1, fitted)

    x0, y0, x1, y1 = bbox
    bbox_w_pdf = max(0.0, x1 - x0)
    bbox_h_pdf = max(0.0, y1 - y0)
    if bbox_w_pdf <= 1e-6 or bbox_h_pdf <= 1e-6:
        return max(0.1, fitted)

    s = max(float(scale), 1e-12)
    norm_angle = abs(normalize_text_angle_deg(angle_deg))
    along_pdf = bbox_glyph_width_pt(bbox, angle_deg)
    normal_pdf = bbox_glyph_height_pt(bbox, angle_deg)

    width_fn = estimate_width_units or _default_estimate_text_width_units
    estimated_width_pdf = width_fn(text) * fitted / s
    if estimated_width_pdf > along_pdf * 1.08 and estimated_width_pdf > 1e-9:
        width_ratio = (along_pdf * 0.98) / estimated_width_pdf
        if math.isfinite(width_ratio) and width_ratio > 0.0:
            fitted *= max(0.25, min(1.0, width_ratio))

    height_cap_fc = normal_pdf * s * 1.12
    if height_cap_fc >= 0.1 and fitted > height_cap_fc * 1.08:
        fitted = height_cap_fc

    return max(0.1, fitted)


def text_matrix_scale_factors(text_matrix: Tuple[float, ...]) -> Tuple[float, float]:
    """Return (along, normal) scale magnitudes from a PDF text matrix."""
    if not text_matrix or len(text_matrix) < 4:
        return 1.0, 1.0
    a, b, c, d = (float(text_matrix[0]), float(text_matrix[1]),
                  float(text_matrix[2]), float(text_matrix[3]))
    along = math.hypot(a, b)
    normal = math.hypot(c, d)
    return along, normal


def effective_font_size_from_text_matrix(
    font_size: float,
    text_matrix: Tuple[float, ...],
) -> float:
    """Compute user-space font size honoring non-uniform text matrices."""
    along, normal = text_matrix_scale_factors(text_matrix)
    scale = max(along, normal)
    if scale < 1e-6:
        return float(font_size)
    return float(font_size) * scale


__all__ = [
    "bbox_glyph_height_pt",
    "bbox_glyph_width_pt",
    "effective_font_size_from_text_matrix",
    "effective_span_font_size_pt",
    "fit_font_size_to_span_bbox",
    "normalize_text_angle_deg",
    "span_bbox_pdf",
    "text_matrix_scale_factors",
]

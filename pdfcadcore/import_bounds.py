# -*- coding: utf-8 -*-
"""Shared import bounding boxes for autofit and golden bbox gates."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple, Union

from .primitives import NormalizedText, PageData, Primitive

DEFAULT_PADDING_FRACTION = 0.02
DEFAULT_MIN_PADDING_MM = 1.0
# Content span this many times larger than the page frame is an autofit
# outlier (origin spoke, leaked Z, runaway annot). Geometry is kept; framing
# uses the page rectangle so zoom-to-fit cannot send the camera to infinity.
PAGE_OUTLIER_SPAN_FACTOR = 8.0
_ORTHOGONAL_Y_ABS = 1.0e-9
_ORTHOGONAL_Z_VS_X = 0.01


@dataclass(frozen=True)
class ImportBounds:
    """Axis-aligned bounds in PageData model units (mm)."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float
    unit: str = "mm"

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(0.0, self.max_y - self.min_y)

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.min_x + self.max_x) * 0.5, (self.min_y + self.max_y) * 0.5)

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.min_x, self.min_y, self.max_x, self.max_y)

    def with_padding(
        self,
        fraction: float = DEFAULT_PADDING_FRACTION,
        min_padding_mm: float = DEFAULT_MIN_PADDING_MM,
    ) -> "ImportBounds":
        span = max(self.width, self.height, min_padding_mm)
        pad = max(span * fraction, min_padding_mm)
        return ImportBounds(
            self.min_x - pad,
            self.min_y - pad,
            self.max_x + pad,
            self.max_y + pad,
            unit=self.unit,
        )


def sheet_xy(point: Any) -> Optional[Tuple[float, float]]:
    """Project a 2- or 3-tuple onto the sheet plane (host-neutral).

    Finite ``(x, y)`` stays ``(x, y)``. A 3-tuple whose |Z| dominates a
    near-zero Y (PDF Y leaked into Z, so the drawing stands up like a fence)
    uses ``(x, z)`` as sheet XY. Non-finite values are dropped. Units are
    whatever the caller already uses; the heuristic is scale-free aside from
    a tiny Y-zero epsilon.
    """
    if point is None:
        return None
    try:
        x = float(point[0])
    except (TypeError, ValueError, IndexError):
        return None
    try:
        y = float(point[1]) if len(point) > 1 else 0.0
    except (TypeError, ValueError, IndexError):
        y = 0.0
    z = 0.0
    try:
        if len(point) > 2:
            z = float(point[2])
    except (TypeError, ValueError, IndexError):
        z = 0.0
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    if (
        math.isfinite(z)
        and abs(z) > _ORTHOGONAL_Y_ABS
        and abs(y) <= _ORTHOGONAL_Y_ABS
        and abs(z) > abs(x) * _ORTHOGONAL_Z_VS_X
    ):
        y = z
        if not math.isfinite(y):
            return None
    return (x, y)


def _page_frame(page: PageData) -> Tuple[float, float, float, float]:
    width = float(getattr(page, "width", 0.0) or 0.0)
    height = float(getattr(page, "height", 0.0) or 0.0)
    if not math.isfinite(width) or width <= 0.0:
        width = 1.0
    if not math.isfinite(height) or height <= 0.0:
        height = 1.0
    return (0.0, 0.0, width, height)


def _box_exceeds_page(
    box: Tuple[float, float, float, float],
    page: PageData,
) -> bool:
    frame = _page_frame(page)
    frame_w = max(frame[2] - frame[0], 1.0)
    frame_h = max(frame[3] - frame[1], 1.0)
    span_w = box[2] - box[0]
    span_h = box[3] - box[1]
    return (
        span_w > PAGE_OUTLIER_SPAN_FACTOR * frame_w
        or span_h > PAGE_OUTLIER_SPAN_FACTOR * frame_h
    )


def _bbox_from_points(points: Sequence[Any]) -> Optional[Tuple[float, float, float, float]]:
    xs = []
    ys = []
    for pt in points or ():
        xy = sheet_xy(pt)
        if xy is None:
            continue
        xs.append(xy[0])
        ys.append(xy[1])
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_from_primitive(primitive: Primitive) -> Optional[Tuple[float, float, float, float]]:
    if primitive.bbox:
        box = primitive.bbox
        try:
            return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        except (TypeError, ValueError, IndexError):
            pass
    if primitive.points:
        return _bbox_from_points(primitive.points)
    if primitive.center and primitive.radius is not None:
        xy = sheet_xy(primitive.center)
        if xy is None:
            return None
        cx, cy = xy
        radius = float(primitive.radius)
        return (cx - radius, cy - radius, cx + radius, cy + radius)
    return None


def _bbox_from_text(text: NormalizedText) -> Optional[Tuple[float, float, float, float]]:
    if text.bbox:
        box = text.bbox
        try:
            return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        except (TypeError, ValueError, IndexError):
            pass
    if text.insertion:
        xy = sheet_xy(text.insertion)
        if xy is None:
            return None
        x, y = xy
        return (x, y, x, y)
    return None


def _merge_bbox(
    acc: Optional[Tuple[float, float, float, float]],
    box: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    if acc is None:
        return box
    return (min(acc[0], box[0]), min(acc[1], box[1]), max(acc[2], box[2]), max(acc[3], box[3]))


def _bounds_for_page(
    page: PageData,
    *,
    include_page_frame: bool,
) -> Optional[Tuple[float, float, float, float]]:
    merged: Optional[Tuple[float, float, float, float]] = None
    skipped_outlier = False

    for primitive in page.primitives:
        box = _bbox_from_primitive(primitive)
        if box is None:
            continue
        if _box_exceeds_page(box, page):
            skipped_outlier = True
            continue
        merged = _merge_bbox(merged, box)

    for text in page.text_items:
        box = _bbox_from_text(text)
        if box is None:
            continue
        if _box_exceeds_page(box, page):
            skipped_outlier = True
            continue
        merged = _merge_bbox(merged, box)

    if merged is None and (include_page_frame or skipped_outlier):
        return _page_frame(page)

    return merged


def compute_import_bounds(
    pages: Union[PageData, Sequence[PageData]],
    *,
    include_page_frame: bool = True,
    padding_fraction: float = DEFAULT_PADDING_FRACTION,
    min_padding_mm: float = DEFAULT_MIN_PADDING_MM,
    apply_padding: bool = True,
) -> Optional[ImportBounds]:
    """
    Compute union bounds for one or more imported pages.

    Returns padded bounds suitable for host autofit when ``apply_padding`` is True.
    Far outliers and orthogonal Z leakage are ignored for framing only.
    """
    if isinstance(pages, PageData):
        page_list = [pages]
    else:
        page_list = list(pages)

    if not page_list:
        return None

    merged: Optional[Tuple[float, float, float, float]] = None
    for page in page_list:
        page_bounds = _bounds_for_page(page, include_page_frame=include_page_frame)
        if page_bounds is not None:
            merged = _merge_bbox(merged, page_bounds)

    if merged is None:
        return None

    if include_page_frame:
        frame_w = max(float(page.width or 0.0) for page in page_list)
        frame_h = max(float(page.height or 0.0) for page in page_list)
        content_w = merged[2] - merged[0]
        content_h = merged[3] - merged[1]
        if (
            content_w > PAGE_OUTLIER_SPAN_FACTOR * max(frame_w, 1.0)
            or content_h > PAGE_OUTLIER_SPAN_FACTOR * max(frame_h, 1.0)
        ):
            merged = (
                0.0,
                0.0,
                max(frame_w, 1.0),
                max(frame_h, 1.0),
            )

    bounds = ImportBounds(merged[0], merged[1], merged[2], merged[3])
    if apply_padding:
        return bounds.with_padding(
            fraction=padding_fraction,
            min_padding_mm=min_padding_mm,
        )
    return bounds


__all__ = [
    "DEFAULT_MIN_PADDING_MM",
    "DEFAULT_PADDING_FRACTION",
    "PAGE_OUTLIER_SPAN_FACTOR",
    "ImportBounds",
    "compute_import_bounds",
    "sheet_xy",
]

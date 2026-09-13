# -*- coding: utf-8 -*-
# generic_recognizer.py — Domain-neutral recognition
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .primitives import PageData, Primitive, RecognitionConfig
from .geometry_cleanup import circle_fit
from . import generic_classifier as gc
from . import document_profiler as dp
from . import dimension_parser as dim_parser
import math


@dataclass
class GenericResults:
    circles: list = field(default_factory=list)
    closed_boundaries: list = field(default_factory=list)
    repeated_patterns: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    title_block_bbox: object = None
    dimension_assocs: list = field(default_factory=list)
    page_profile: object = None


def analyze(page_data: PageData, config: RecognitionConfig = None) -> GenericResults:
    if config is None:
        config = RecognitionConfig()
    gc.classify_text(page_data)
    gc.classify_primitives(page_data)
    profile = dp.profile(page_data)

    circles = []
    for p in page_data.primitives:
        if p.type == "circle" and p.center and p.radius:
            circles.append({
                "center": p.center,
                "radius": p.radius,
                "prim_id": p.id,
                "rms": 0.0,
            })
            continue
        npts = len(p.points or [])
        if (
            p.type == "closed_loop"
            and p.closed
            and npts >= 6
        ):
            fit = circle_fit(p.points)
            if fit and fit[3] < config.circle_fit_tol:
                circles.append({"center":(fit[0],fit[1]),"radius":fit[2],"prim_id":p.id,"rms":fit[3]})

    boundaries = [{"prim_id":p.id,"area":p.area,"bbox":p.bbox}
                  for p in page_data.primitives
                  if p.type=="closed_loop" and p.closed and p.area and p.area>=config.closed_loop_min_area]
    boundaries.sort(key=lambda b: -(b["area"] or 0))

    groups = {}
    for p in page_data.primitives:
        if p.type=="closed_loop" and p.area and p.area > 1.0:
            k = f"{round(p.area)}_{len(p.points or [])}"
            groups.setdefault(k,[]).append(p)
    patterns = [{"prim_ids":[q.id for q in g],"count":len(g)} for g in groups.values() if len(g)>=3]

    tables = gc.detect_tables(page_data)
    tb_bbox = gc.detect_title_block(page_data)

    dim_assocs = associate_dimensions(
        page_data.text_items,
        page_data.primitives,
        config.dimension_assoc_radius,
    )

    return GenericResults(circles=circles, closed_boundaries=boundaries,
        repeated_patterns=patterns, tables=tables, title_block_bbox=tb_bbox,
        dimension_assocs=dim_assocs, page_profile=profile)


def associate_dimensions(text_items, primitives, radius: float) -> list:
    """Nearest-primitive association for dimension-like text.

    Uses a uniform grid so a page with thousands of primitives does not pay
    O(text × primitives). Tie-breaking matches the historical all-pairs loop:
    the first primitive in ``primitives`` at the strictly nearer distance wins.
    """
    indexed = _primitive_centers(primitives)
    grid, cell = _build_center_grid(indexed, radius)
    dim_assocs = []
    for txt in text_items:
        if "dimension_like" not in txt.generic_tags:
            continue
        pd = dim_parser.parse(txt.text)
        if pd.value is None or pd.confidence < 0.3:
            continue
        nearest = _nearest_center(
            grid,
            cell,
            txt.insertion[0],
            txt.insertion[1],
            radius,
        )
        dim_assocs.append({
            "text_id": txt.id,
            "text": txt.text,
            "value": pd.value,
            "kind": pd.kind,
            "nearest_prim_id": nearest.id if nearest is not None else None,
        })
    return dim_assocs


def _primitive_centers(primitives) -> List[Tuple[int, float, float, Primitive]]:
    indexed = []
    for index, prim in enumerate(primitives):
        bbox = prim.bbox
        if not bbox:
            continue
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        indexed.append((index, cx, cy, prim))
    return indexed


def _build_center_grid(
    indexed: List[Tuple[int, float, float, Primitive]],
    radius: float,
) -> Tuple[Dict[Tuple[int, int], List[Tuple[int, float, float, Primitive]]], float]:
    cell = float(radius) if radius and radius > 0.0 else 75.0
    grid: Dict[Tuple[int, int], List[Tuple[int, float, float, Primitive]]] = {}
    for item in indexed:
        _, cx, cy, _prim = item
        key = (int(math.floor(cx / cell)), int(math.floor(cy / cell)))
        grid.setdefault(key, []).append(item)
    return grid, cell


def _nearest_center(
    grid: Dict[Tuple[int, int], List[Tuple[int, float, float, Primitive]]],
    cell: float,
    x: float,
    y: float,
    radius: float,
) -> Optional[Primitive]:
    gx = int(math.floor(x / cell))
    gy = int(math.floor(y / cell))
    span = int(math.ceil(radius / cell)) if cell > 0.0 else 1
    nearest = None
    nearest_index = None
    nearest_dist = radius
    for dx in range(-span, span + 1):
        for dy in range(-span, span + 1):
            for index, cx, cy, prim in grid.get((gx + dx, gy + dy), ()):
                dist = math.hypot(x - cx, y - cy)
                if dist < nearest_dist:
                    nearest = prim
                    nearest_index = index
                    nearest_dist = dist
                elif (
                    nearest_index is not None
                    and dist == nearest_dist
                    and index < nearest_index
                ):
                    nearest = prim
                    nearest_index = index
    return nearest

# -*- coding: utf-8 -*-
# PDFPrimitives.py — Host-neutral intermediate data model for FreeCAD
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
All recognition modules operate on these structures, NOT on FreeCAD objects.
Rule 2: Recognizers must operate on normalized primitives, not host entities.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_next_id = 0
def next_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id

def reset_ids():
    global _next_id
    _next_id = 0


@dataclass
class RecognitionConfig:
    vertex_merge_tol: float = 0.1        # mm
    min_segment_len: float = 0.05        # mm
    loop_close_tol: float = 0.5          # mm
    region_padding: float = 25.0         # mm
    text_assoc_radius: float = 50.0      # mm
    dimension_assoc_radius: float = 75.0 # mm
    circle_min_diameter: float = 5.0     # mm
    circle_max_diameter: float = 100.0   # mm
    circle_fit_tol: float = 0.25         # mm RMS
    closed_loop_min_aspect: float = 1.5
    closed_loop_min_area: float = 100.0  # sq mm
    confidence_threshold: float = 0.60


@dataclass
class Primitive:
    id: int
    type: str              # "line", "arc", "circle", "polyline", "closed_loop", "rect"
    points: List[Tuple[float, float]]
    center: Optional[Tuple[float, float]] = None
    radius: Optional[float] = None
    start_angle: Optional[float] = None
    end_angle: Optional[float] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    stroke_color: Optional[Tuple[float, float, float]] = None
    fill_color: Optional[Tuple[float, float, float]] = None
    dash_pattern: Optional[list] = None
    dash_phase: float = 0.0
    line_width: Optional[float] = None
    layer_name: Optional[str] = None
    closed: bool = False
    area: Optional[float] = None
    page_number: int = 0
    generic_tags: List[str] = field(default_factory=list)


@dataclass
class NormalizedText:
    id: int
    text: str
    normalized: str        # uppercased, cleaned
    insertion: Tuple[float, float] = (0.0, 0.0)
    bbox: Optional[Tuple[float, float, float, float]] = None
    font_size: float = 3.0 # mm
    rotation: float = 0.0  # degrees
    font_name: str = ""
    color: Optional[Tuple[float, float, float]] = None  # RGB 0-1
    page_number: int = 0
    generic_tags: List[str] = field(default_factory=list)
    domain_tags: List[dict] = field(default_factory=list)


@dataclass
class PageData:
    page_number: int
    width: float           # mm
    height: float          # mm
    primitives: List[Primitive] = field(default_factory=list)
    text_items: List[NormalizedText] = field(default_factory=list)
    layers: List[str] = field(default_factory=list)
    xobject_names: List[str] = field(default_factory=list)


@dataclass
class ParsedDimension:
    raw_text: str
    kind: str = "unknown"  # linear, diameter, radius, slot, scale, unknown
    value: object = None   # float or dict
    units: Optional[str] = None
    quantity: Optional[int] = None
    normalized_text: str = ""
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)


@dataclass
class Region:
    id: int = 0
    page_number: int = 0
    bbox: Optional[Tuple[float, float, float, float]] = None
    primitive_ids: List[int] = field(default_factory=list)
    text_ids: List[int] = field(default_factory=list)
    region_type: str = "unknown"
    label: str = ""
    is_titleblock: bool = False
    confidence: float = 0.0


@dataclass
class PageProfile:
    page_number: int = 0
    primary_type: str = "unknown"
    scores: Dict[str, float] = field(default_factory=dict)
    has_layers: bool = False
    has_text: bool = False
    has_dimensions: bool = False
    circle_count: int = 0
    closed_loop_count: int = 0
    line_count: int = 0
    text_count: int = 0
    titleblock_likely: bool = False


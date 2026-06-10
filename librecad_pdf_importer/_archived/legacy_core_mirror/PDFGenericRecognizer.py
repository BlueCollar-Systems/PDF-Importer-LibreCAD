# -*- coding: utf-8 -*-
# PDFGenericRecognizer.py — Domain-neutral recognition
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
from dataclasses import dataclass, field
from .PDFPrimitives import PageData, RecognitionConfig
from .PDFGeometryCleanup import circle_fit
from . import PDFGenericClassifier as gc
from . import PDFDocumentProfiler as dp
from . import PDFDimensionParser as dim_parser
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
        if p.type == "closed_loop" and p.closed and p.points and len(p.points) >= 6:
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

    dim_assocs = []
    for txt in page_data.text_items:
        if "dimension_like" not in txt.generic_tags: continue
        pd = dim_parser.parse(txt.text)
        if pd.value is None or pd.confidence < 0.3: continue
        nearest, nd = None, config.dimension_assoc_radius
        for p in page_data.primitives:
            if not p.bbox: continue
            pcx = (p.bbox[0]+p.bbox[2])/2; pcy = (p.bbox[1]+p.bbox[3])/2
            d = math.hypot(txt.insertion[0]-pcx, txt.insertion[1]-pcy)
            if d < nd: nearest, nd = p, d
        dim_assocs.append({"text_id":txt.id,"text":txt.text,"value":pd.value,
                          "kind":pd.kind,"nearest_prim_id":nearest.id if nearest else None})

    return GenericResults(circles=circles, closed_boundaries=boundaries,
        repeated_patterns=patterns, tables=tables, title_block_bbox=tb_bbox,
        dimension_assocs=dim_assocs, page_profile=profile)


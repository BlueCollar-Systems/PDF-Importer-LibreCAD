# -*- coding: utf-8 -*-
# PDFDocumentProfiler.py — Auto page-type detection
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
from .PDFPrimitives import PageData, PageProfile


def profile(page_data: PageData) -> PageProfile:
    """Score page type. Returns PageProfile."""
    prims = page_data.primitives
    texts = page_data.text_items

    lines = sum(1 for p in prims if p.type == "line")
    closed = sum(1 for p in prims if p.type == "closed_loop")
    polylines = sum(1 for p in prims if p.type == "polyline")
    total_geom = len(prims)

    dim_texts = sum(1 for t in texts if "dimension_like" in t.generic_tags)
    scale_texts = sum(1 for t in texts if "scale_like" in t.generic_tags)
    tb_texts = sum(1 for t in texts if "titleblock_like" in t.generic_tags)
    callout_texts = sum(1 for t in texts if "callout_like" in t.generic_tags)
    total_text = len(texts)
    has_layers = bool(page_data.layers)

    # Circles
    circles = 0
    from .PDFGeometryCleanup import circle_fit
    for p in prims:
        if p.type == "closed_loop" and p.points and len(p.points) >= 8:
            fit = circle_fit(p.points)
            if fit and fit[3] < 0.5:
                circles += 1

    scores = {}

    s = 0.20 * (circles > 3) + 0.15 * (callout_texts > 2) + 0.15 * (dim_texts > 5)
    s += 0.10 * (closed > 10) + 0.10 * (tb_texts > 2) + 0.10 * (scale_texts > 0)
    scores["fabrication"] = min(s, 1.0)

    s = 0.20 * (lines > 50) + 0.15 * (dim_texts > 3) + 0.15 * has_layers
    s += 0.10 * (closed > 5) + 0.10 * (scale_texts > 0) + 0.10 * (tb_texts > 0)
    scores["cad_drawing"] = min(s, 1.0)

    s = 0.20 * (lines > 100) + 0.15 * has_layers + 0.15 * (dim_texts > 10)
    s += 0.10 * (total_text > 30) - 0.15 * (circles > 10)
    scores["architectural"] = min(max(s, 0), 1.0)

    s = 0.30 * (total_geom > 20 and dim_texts == 0) + 0.20 * (polylines > lines)
    s += 0.10 * (total_text < 5) - 0.20 * has_layers - 0.20 * (dim_texts > 2)
    scores["vector_art"] = min(max(s, 0), 1.0)

    s = 0.90 if total_geom == 0 and total_text == 0 else 0.0
    # Profile score category name -- distinct namespace from BCS-ARCH-001
    # import modes. Renamed from the legacy "raster_only" label to avoid
    # collision with the deleted preset name. Scored when the page has
    # zero vectors and zero text, which strongly implies a scanned/
    # rendered image.
    scores["blank_or_image"] = s

    primary = max(scores, key=scores.get) if scores else "unknown"
    if max(scores.values(), default=0) < 0.25:
        primary = "cad_drawing" if total_geom > 0 else "unknown"

    return PageProfile(
        page_number=page_data.page_number, primary_type=primary,
        scores=scores, has_layers=has_layers, has_text=total_text > 0,
        has_dimensions=dim_texts > 0, circle_count=circles,
        closed_loop_count=closed, line_count=lines, text_count=total_text,
        titleblock_likely=tb_texts > 2
    )


def suggest_mode(profile: PageProfile) -> str:
    """Text-rendering suggestion hint (legacy; informational only).

    Not used for BCS-ARCH-001 import_mode selection.
    """
    t = profile.primary_type
    if t == "fabrication":
        return "tech_drawing_hint"
    elif t == "architectural":
        return "architectural_hint"
    elif t in ("vector_art", "blank_or_image"):
        return "none"
    return "generic"


# -*- coding: utf-8 -*-
# document_profiler.py — Auto page-type detection
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
from .primitives import PageData, PageProfile
from .geometry_cleanup import circle_fit


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

    circles = sum(1 for p in prims if p.type == "circle")
    for p in prims:
        if p.type == "circle":
            continue
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
    scores["raster_only"] = s

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


def suggest_mode(profile_result: PageProfile) -> str:
    """Text-rendering suggestion hint (legacy; informational only).

    Returns one of "technical" | "architectural" | "none" | "generic".
    Host adapters may use this to pre-select a text_mode UI default.
    NOT used for import_mode selection — see suggest_import_mode.
    """
    t = profile_result.primary_type
    if t == "fabrication":
        return "technical"
    elif t == "architectural":
        return "architectural"
    elif t in ("vector_art", "raster_only"):
        return "none"
    return "generic"


# --------------------------------------------------------------------
# BCS-ARCH-001 Auto-mode resolution.
#
# When ImportConfig.import_mode == "auto", the extractor calls this
# helper per page to decide which strategy to use. The decision uses
# the existing classify_page_content() heuristics; no new thresholds
# are introduced here.
# --------------------------------------------------------------------
def suggest_import_mode(
    classification: dict,
    page_drawing_count: int,
    page_text_count: int,
    page_has_images: bool,
    user_ignore_images: bool = False,
) -> tuple:
    """Resolve Auto mode to one of "vector" | "raster" | "hybrid".

    Args:
        classification: result dict from auto_mode.classify_page_content()
            with key "type" in {"vectors", "glyph_flood", "fill_art",
            "raster_candidate"}.
        page_drawing_count: number of vector drawings on the page.
        page_text_count: number of text items on the page.
        page_has_images: True if page has embedded raster imagery.
        user_ignore_images: True if the caller passed --ignore-images.

    Returns:
        (resolved_mode, reason_string) tuple.

    BCS-ARCH-001 Rule 9: the reason string must be human-readable so
    the host adapter can show the user what Auto chose and why.
    """
    ctype = classification.get("type", "") if isinstance(classification, dict) else ""

    # No vector content and no text at all -> must be raster
    if page_drawing_count == 0 and page_text_count == 0:
        return ("raster", "No vector content on page -- rendered image")

    if ctype == "vectors":
        if page_has_images and not user_ignore_images:
            return ("hybrid", "Vectors + embedded raster imagery")
        return ("vector", "Standard vector content")

    if ctype in ("glyph_flood", "fill_art"):
        # Known-garbage vector content: would produce thousands of useless
        # tiny primitives. Raster is the correct output.
        detail = classification.get("reason", ctype) if isinstance(classification, dict) else ctype
        return ("raster", f"{ctype}: {detail}")

    if ctype == "raster_candidate":
        return ("raster", "Raster-dominated page")

    # Fallback: assume vector content
    return ("vector", "Fallback (unclassified) -- defaulting to vector")

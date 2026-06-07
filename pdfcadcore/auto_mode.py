# -*- coding: utf-8 -*-
# auto_mode.py -- Auto-mode detection heuristics for PDF content classification
# BlueCollar Systems -- BUILT. NOT BOUGHT.
"""
Classifies PDF page content to prevent garbage output on certain PDF types:
- Glyph floods (OCR-like PDFs with thousands of tiny vector glyphs)
- Fill-art floods (decorative/map PDFs with mostly fills)

Heuristics ported from the FreeCAD importer's _looks_like_vector_glyph_flood()
and _looks_like_fill_art_flood() functions.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ── Glyph-flood thresholds ──────────────────────────────────────────
AUTO_GLYPH_DRAWING_THRESHOLD = 1500
AUTO_GLYPH_FILL_RATIO = 0.75
AUTO_GLYPH_TINY_RECT_RATIO = 0.45
AUTO_GLYPH_TEXT_BLOCK_THRESHOLD = 50
AUTO_GLYPH_WORD_THRESHOLD = 400
AUTO_GLYPH_STROKE_SPARSE_RATIO = 0.05

# ── Fill-art flood thresholds ───────────────────────────────────────
AUTO_FILL_DRAWING_THRESHOLD = 400
AUTO_FILL_HEAVY_RATIO = 0.60
AUTO_FILL_STROKE_MAX = 0.22
AUTO_FILL_PURE_RATIO = 0.95
AUTO_FILL_PURE_STROKE_MAX = 0.02
AUTO_FILL_PURE_MIN_GROUPS = 12
AUTO_FILL_PURE_MIN_ITEMS = 24
AUTO_FILL_PURE_LARGE_RECT_RATIO = 0.03


def classify_page_content(
    drawings: List[Dict[str, Any]],
    text_blocks_count: int = 0,
    text_words_count: int = 0,
    page_area: float = 0.0,
) -> Dict[str, Any]:
    """Classify page content type from raw PyMuPDF drawings.

    Call this on the result of ``fitz_page.get_drawings()`` *before*
    primitive extraction to decide whether a page should be imported
    as vectors, skipped, or converted to raster.

    Parameters
    ----------
    drawings:
        Raw PyMuPDF drawing groups from ``page.get_drawings()``.
    text_blocks_count:
        Number of text blocks on the page (from ``page.get_text("blocks")``).
    text_words_count:
        Number of words on the page (from ``page.get_text("words")``).
    page_area:
        Media-box area in PDF points squared (width * height). Used for
        large-rectangle heuristics on pure-fill decorative pages.

    Returns
    -------
    dict
        ``type``  -- ``'vectors'`` | ``'glyph_flood'`` | ``'fill_art'``
                     | ``'raster_candidate'``
        ``reason`` -- human-readable explanation
        ``drawing_count`` -- total drawing groups
        ``stats`` -- detailed numeric statistics
    """
    if not drawings:
        return {
            "type": "raster_candidate",
            "reason": "No vector content",
            "drawing_count": 0,
            "stats": {},
        }

    total = len(drawings)

    # ── Compute per-drawing statistics ──────────────────────────────
    has_fill = 0
    has_stroke = 0
    fill_only = 0
    tiny_rects = 0
    total_item_count = 0
    max_rect_ratio = 0.0

    for d in drawings:
        items = d.get("items", [])
        total_item_count += len(items)
        f = d.get("fill")
        s = d.get("color") or d.get("stroke")

        if f is not None:
            has_fill += 1
        if s is not None:
            has_stroke += 1
        if f is not None and s is None:
            fill_only += 1

        # Tiny rect detection: single 're' item with small bounds
        if len(items) == 1 and items[0][0] == "re":
            rect = d.get("rect")
            if rect is not None:
                # rect is a fitz.Rect or tuple (x0, y0, x1, y1)
                try:
                    if hasattr(rect, "width"):
                        w, h = rect.width, rect.height
                    else:
                        w = abs(rect[2] - rect[0])
                        h = abs(rect[3] - rect[1])
                    if w < 2.0 and h < 2.0:
                        tiny_rects += 1
                    if page_area > 0.0:
                        ratio = (w * h) / page_area
                        if ratio > max_rect_ratio:
                            max_rect_ratio = ratio
                except (TypeError, IndexError):
                    tiny_rects += 1
            else:
                tiny_rects += 1

    fill_ratio = has_fill / total if total > 0 else 0
    stroke_ratio = has_stroke / total if total > 0 else 0
    fill_only_ratio = fill_only / total if total > 0 else 0
    tiny_rect_ratio = tiny_rects / total if total > 0 else 0
    avg_items = total_item_count / float(total) if total > 0 else 0.0

    stats = {
        "total": total,
        "has_fill": has_fill,
        "has_stroke": has_stroke,
        "fill_only": fill_only,
        "tiny_rects": tiny_rects,
        "fill_ratio": fill_ratio,
        "stroke_ratio": stroke_ratio,
        "fill_only_ratio": fill_only_ratio,
        "tiny_rect_ratio": tiny_rect_ratio,
        "total_item_count": total_item_count,
        "avg_items_per_group": avg_items,
        "max_rect_ratio": max_rect_ratio,
    }

    # ── Glyph flood detection ──────────────────────────────────────
    if (
        total >= AUTO_GLYPH_DRAWING_THRESHOLD
        and fill_ratio >= AUTO_GLYPH_FILL_RATIO
        and tiny_rect_ratio >= AUTO_GLYPH_TINY_RECT_RATIO
        and stroke_ratio <= AUTO_GLYPH_STROKE_SPARSE_RATIO
    ):
        return {
            "type": "glyph_flood",
            "reason": (
                f"{total} drawings, {fill_ratio:.0%} fills, "
                f"{tiny_rect_ratio:.0%} tiny rects"
            ),
            "drawing_count": total,
            "stats": stats,
        }

    # Text-density variant of glyph flood — requires BOTH high text density
    # AND glyph-like drawing characteristics (sparse strokes, high fills).
    # Without the fill/stroke check, normal shop drawings with many
    # dimension labels get falsely flagged.
    if (
        total >= AUTO_GLYPH_DRAWING_THRESHOLD
        and (
            text_blocks_count >= AUTO_GLYPH_TEXT_BLOCK_THRESHOLD
            or text_words_count >= AUTO_GLYPH_WORD_THRESHOLD
        )
        and stroke_ratio <= AUTO_GLYPH_STROKE_SPARSE_RATIO
        and fill_ratio >= AUTO_GLYPH_FILL_RATIO
    ):
        return {
            "type": "glyph_flood",
            "reason": (
                f"High text density ({text_blocks_count} blocks, "
                f"{text_words_count} words) with glyph-like draws "
                f"({fill_ratio:.0%} fills, {stroke_ratio:.0%} strokes)"
            ),
            "drawing_count": total,
            "stats": stats,
        }

    # ── Fill-art flood detection ───────────────────────────────────
    # Decorative/map art uses simple 1–3 item groups; real CAD plans have
    # many path items per drawing group (avg_items >> 5).
    pure_fill = (
        fill_only_ratio >= AUTO_FILL_PURE_RATIO
        and stroke_ratio <= AUTO_FILL_PURE_STROKE_MAX
        and avg_items <= 5.0
    )
    if pure_fill and total >= AUTO_FILL_PURE_MIN_GROUPS:
        if (
            total_item_count >= AUTO_FILL_PURE_MIN_ITEMS
            or max_rect_ratio >= AUTO_FILL_PURE_LARGE_RECT_RATIO
        ):
            return {
                "type": "fill_art",
                "reason": (
                    f"Pure fill art ({fill_only_ratio:.0%} fill-only, "
                    f"avg {avg_items:.1f} items/group) in {total} drawings"
                ),
                "drawing_count": total,
                "stats": stats,
            }

    if total >= AUTO_FILL_DRAWING_THRESHOLD:
        if (
            fill_only_ratio >= AUTO_FILL_HEAVY_RATIO
            and stroke_ratio <= AUTO_FILL_STROKE_MAX
            and avg_items <= 5.0
        ):
            return {
                "type": "fill_art",
                "reason": (
                    f"{fill_only_ratio:.0%} fill-only, "
                    f"{stroke_ratio:.0%} strokes, "
                    f"avg {avg_items:.1f} items/group in {total} drawings"
                ),
                "drawing_count": total,
                "stats": stats,
            }

    # ── Normal vector content ──────────────────────────────────────
    return {
        "type": "vectors",
        "reason": "Normal vector content",
        "drawing_count": total,
        "stats": stats,
    }

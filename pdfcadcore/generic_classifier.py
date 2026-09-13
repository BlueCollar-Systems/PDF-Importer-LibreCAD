# -*- coding: utf-8 -*-
# generic_classifier.py — Domain-neutral classification
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""Classifies text and primitives generically. Domain-neutral."""
from __future__ import annotations
import re
from .primitives import PageData


_NOTE_RE = re.compile(r"\b(NOTE|NOTES|N\.?T\.?S\.?|SEE\s+DWG)\b")
_QTY_RE = re.compile(r"\b(QTY|EA|EACH|PCS)\b")
_REV_RE = re.compile(r"\bREV[.\s]?[A-Z0-9]?\b")
_DETAIL_RE = re.compile(r"\b(DETAIL|SECTION|VIEW|ELEVATION)\s+[A-Z]")
_SCALE_WORD_RE = re.compile(r"\b(SCALE|SC\.?|SCL\.?)\b")
_SCALE_RATIO_RE = re.compile(r"\d+\s*:\s*\d+")
_TITLEBLOCK_RE = re.compile(r"\b(DRAWN|CHECKED|APPROVED|PROJECT|JOB|DATE|SHEET)\b")
_DIM_EQ_RE = re.compile(r'\d+(?:\.\d+)?(?:\s*/\s*\d+)?\s*["\u2033]?\s*=\s*\d')
_DIM_UNIT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(MM|CM|IN|FT|M)\b")

def classify_text(page_data: PageData):
    """Add generic tags to text items (in place)."""
    for txt in page_data.text_items:
        tags = list(txt.generic_tags)
        tu = txt.normalized
        if _NOTE_RE.search(tu):
            if "note_indicator" not in tags:
                tags.append("note_indicator")
        if _QTY_RE.search(tu):
            if "quantity_indicator" not in tags:
                tags.append("quantity_indicator")
        if _REV_RE.search(tu):
            if "revision_like" not in tags:
                tags.append("revision_like")
        if _DETAIL_RE.search(tu):
            if "detail_reference" not in tags:
                tags.append("detail_reference")
        if _SCALE_WORD_RE.search(tu) or _SCALE_RATIO_RE.search(tu):
            if "scale_like" not in tags:
                tags.append("scale_like")
        if _TITLEBLOCK_RE.search(tu):
            if "titleblock_like" not in tags:
                tags.append("titleblock_like")
        if _DIM_EQ_RE.search(tu) or _DIM_UNIT_RE.search(tu):
            if "dimension_like" not in tags:
                tags.append("dimension_like")
        txt.generic_tags = tags


def classify_primitives(page_data: PageData):
    """Add generic tags to primitives (in place)."""
    page_area = page_data.width * page_data.height
    for p in page_data.primitives:
        tags = list(p.generic_tags)
        if p.type == "closed_loop" and p.area and p.area > page_area * 0.7:
            if p.points and len(p.points) <= 5 and "page_border" not in tags:
                tags.append("page_border")
        if p.type == "closed_loop" and p.area and p.area < 50.0:
            if p.points and len(p.points) <= 5 and "possible_table_cell" not in tags:
                tags.append("possible_table_cell")
        if p.dash_pattern and "dashed_line" not in tags:
            tags.append("dashed_line")
        if p.line_width is not None and p.line_width < 0.3 and "thin_line" not in tags:
            tags.append("thin_line")
        p.generic_tags = tags


def detect_title_block(page_data: PageData):
    """Returns bbox (x0,y0,x1,y1) of likely title block or None."""
    tb = [t for t in page_data.text_items if "titleblock_like" in t.generic_tags]
    if len(tb) < 2:
        return None
    xs = [t.insertion[0] for t in tb]
    ys = [t.insertion[1] for t in tb]
    bbox = (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)
    if bbox[3] < page_data.height * 0.4:
        return bbox
    return None


def detect_tables(page_data: PageData):
    """Find clusters of small rectangles -> table regions."""
    cells = [p for p in page_data.primitives
             if "possible_table_cell" in p.generic_tags]
    if len(cells) < 4:
        return []
    tables = []
    used = set()
    for i, c in enumerate(cells):
        if i in used:
            continue
        cluster = [c]
        used.add(i)
        for j, o in enumerate(cells):
            if j in used:
                continue
            if c.bbox and o.bbox and _bboxes_adjacent(c.bbox, o.bbox, 12.0):
                cluster.append(o)
                used.add(j)
        if len(cluster) >= 4:
            all_x = [v for c2 in cluster for v in (c2.bbox[0], c2.bbox[2]) if c2.bbox]
            all_y = [v for c2 in cluster for v in (c2.bbox[1], c2.bbox[3]) if c2.bbox]
            tables.append({"bbox": (min(all_x), min(all_y), max(all_x), max(all_y)),
                           "cell_count": len(cluster)})
    return tables


def _bboxes_adjacent(b1, b2, threshold):
    gap_x = max(b1[0] - b2[2], b2[0] - b1[2], 0)
    gap_y = max(b1[1] - b2[3], b2[1] - b1[3], 0)
    return gap_x < threshold and gap_y < threshold

# -*- coding: utf-8 -*-
# PDFPrimitiveExtractor.py — PyMuPDF → normalized Primitives
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
THE SEAM: converts PyMuPDF page data into host-neutral Primitives.
Rule 1: Parser modules must not know about domain-specific logic.
"""
from __future__ import annotations
import math
import re
from typing import List, Tuple

from .PDFPrimitives import (
    Primitive, NormalizedText, PageData, next_id
)

MM_PER_PT = 25.4 / 72.0


def _xy(obj) -> Tuple[float, float]:
    if hasattr(obj, "x") and hasattr(obj, "y"):
        return float(obj.x), float(obj.y)
    if isinstance(obj, (tuple, list)) and len(obj) >= 2:
        return float(obj[0]), float(obj[1])
    return 0.0, 0.0


def _norm_color(col) -> Tuple[float, float, float]:
    if col is None:
        return (0.0, 0.0, 0.0)
    try:
        if isinstance(col, (int, float)):
            g = max(0.0, min(1.0, float(col)))
            return (g, g, g)
        vals = [max(0.0, min(1.0, float(c))) for c in col]
        if len(vals) >= 4:
            # CMYK -> RGB conversion for print-oriented PDFs.
            c, m, y, k = vals[0], vals[1], vals[2], vals[3]
            r = (1.0 - c) * (1.0 - k)
            g = (1.0 - m) * (1.0 - k)
            b = (1.0 - y) * (1.0 - k)
            return (
                max(0.0, min(1.0, r)),
                max(0.0, min(1.0, g)),
                max(0.0, min(1.0, b)),
            )
        while len(vals) < 3:
            vals.append(vals[-1] if vals else 0.0)
        return (vals[0], vals[1], vals[2])
    except (TypeError, ValueError, AttributeError):
        return (0.0, 0.0, 0.0)


def _append_linearized_cubic(
    current_pts: List[Tuple[float, float]],
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    *,
    max_samples: int = 32,
) -> None:
    """Append a cubic Bezier segment as a polyline."""
    if not current_pts:
        current_pts.append(p0)
    samples = max(4, min(max_samples, int(math.ceil(_dist(p0, p3) / 0.5))))
    for i in range(1, samples + 1):
        t = i / float(samples)
        current_pts.append(_bezier_pt(p0, p1, p2, p3, t))


def _quad_to_points(
    quad_obj,
    page_h: float,
    flip_y: bool,
    scale: float,
) -> List[Tuple[float, float]]:
    """Convert a PyMuPDF Quad into a closed 4-point polyline."""
    corners = []
    try:
        corners = [
            _xy(quad_obj.ul),
            _xy(quad_obj.ur),
            _xy(quad_obj.lr),
            _xy(quad_obj.ll),
        ]
    except AttributeError:
        try:
            seq = list(quad_obj)
            if len(seq) >= 4:
                corners = [_xy(seq[0]), _xy(seq[1]), _xy(seq[3]), _xy(seq[2])]
        except (TypeError, ValueError):
            corners = []

    out = [_to_mm(x, y, page_h, flip_y, scale) for x, y in corners]
    if len(out) >= 4:
        out.append(out[0])
    return out


def extract_page(page, page_num: int, scale: float = 1.0,
                 flip_y: bool = True) -> PageData:
    """Extract normalized primitives from a PyMuPDF page."""
    # NOTE: Do NOT reset_ids() here — IDs must be unique across all pages
    # in a multi-page import. reset_ids() is called once at import start.

    page_h = page.rect.height
    page_w_mm = page.rect.width * MM_PER_PT * scale
    page_h_mm = page.rect.height * MM_PER_PT * scale

    primitives = []
    drawings = page.get_drawings()

    for path_group in drawings:
        items = path_group.get("items", [])
        if not items:
            continue

        stroke = _norm_color(path_group.get("color") or path_group.get("stroke"))
        fill = _norm_color(path_group.get("fill"))
        width = path_group.get("width")
        dashes = path_group.get("dashes")
        close_path = path_group.get("closePath", False)
        layer_name = path_group.get("oc") or path_group.get("layer")

        # Build point sequences per sub-path
        current_pts: List[Tuple[float, float]] = []
        sub_paths: List[Tuple[List[Tuple[float, float]], bool]] = []

        def flush(closed: bool, _sub_paths=sub_paths):
            nonlocal current_pts
            if len(current_pts) >= 2:
                _sub_paths.append((current_pts[:], closed))
            current_pts = []

        for item in items:
            kind = item[0]
            data = item[1:]

            if kind == "m":
                flush(False)
                x, y = _parse_point(data)
                px, py = _to_mm(x, y, page_h, flip_y, scale)
                current_pts = [(px, py)]

            elif kind == "l":
                if len(data) >= 2 and hasattr(data[0], "x") and hasattr(data[1], "x"):
                    x0, y0 = _xy(data[0])
                    x1, y1 = _xy(data[1])
                    p0 = _to_mm(x0, y0, page_h, flip_y, scale)
                    p1 = _to_mm(x1, y1, page_h, flip_y, scale)
                    if not current_pts:
                        current_pts.append(p0)
                    current_pts.append(p1)
                else:
                    x, y = _parse_point(data)
                    current_pts.append(_to_mm(x, y, page_h, flip_y, scale))

            elif kind == "c":
                if len(data) == 4 and all(hasattr(d, "x") for d in data):
                    pts = [_xy(d) for d in data]
                else:
                    pts = _parse_cubic(data)
                p0 = _to_mm(pts[0][0], pts[0][1], page_h, flip_y, scale)
                p1 = _to_mm(pts[1][0], pts[1][1], page_h, flip_y, scale)
                p2 = _to_mm(pts[2][0], pts[2][1], page_h, flip_y, scale)
                p3 = _to_mm(pts[3][0] if len(pts) > 3 else pts[2][0],
                            pts[3][1] if len(pts) > 3 else pts[2][1],
                            page_h, flip_y, scale)
                _append_linearized_cubic(current_pts, p0, p1, p2, p3)

            elif kind == "re":
                flush(False)
                x, y, w, h = _parse_rect(data)
                c1 = _to_mm(x, y, page_h, flip_y, scale)
                c2 = _to_mm(x + w, y, page_h, flip_y, scale)
                c3 = _to_mm(x + w, y + h, page_h, flip_y, scale)
                c4 = _to_mm(x, y + h, page_h, flip_y, scale)
                sub_paths.append(([c1, c2, c3, c4, c1], True))

            elif kind == "qu":
                flush(False)
                quad = data[0] if data else None
                pts = _quad_to_points(quad, page_h, flip_y, scale) if quad is not None else []
                if len(pts) >= 5:
                    sub_paths.append((pts, True))

            elif kind == "h":
                flush(True)

            elif kind == "v":
                # PDF "v": c1 is current point, then (c2, end).
                if len(data) >= 2 and current_pts:
                    c2x, c2y = _xy(data[0])
                    ex, ey = _xy(data[1])
                    p0 = current_pts[-1]
                    p1 = p0
                    p2 = _to_mm(c2x, c2y, page_h, flip_y, scale)
                    p3 = _to_mm(ex, ey, page_h, flip_y, scale)
                    _append_linearized_cubic(current_pts, p0, p1, p2, p3)

            elif kind == "y":
                # PDF "y": (c1, end), c2 equals end.
                if len(data) >= 2 and current_pts:
                    c1x, c1y = _xy(data[0])
                    ex, ey = _xy(data[1])
                    p0 = current_pts[-1]
                    p1 = _to_mm(c1x, c1y, page_h, flip_y, scale)
                    p3 = _to_mm(ex, ey, page_h, flip_y, scale)
                    p2 = p3
                    _append_linearized_cubic(current_pts, p0, p1, p2, p3)

        flush(close_path)

        for pts, is_closed in sub_paths:
            if len(pts) < 2:
                continue
            # Dedup consecutive
            cleaned = [pts[0]]
            for p in pts[1:]:
                if _dist(p, cleaned[-1]) > 0.01:
                    cleaned.append(p)
            if len(cleaned) < 2:
                continue

            xs = [p[0] for p in cleaned]
            ys = [p[1] for p in cleaned]
            bbox = (min(xs), min(ys), max(xs), max(ys))

            area = None
            if is_closed and len(cleaned) >= 3:
                area = _polygon_area(cleaned)

            ptype = "line" if len(cleaned) == 2 else ("closed_loop" if is_closed else "polyline")

            primitives.append(Primitive(
                id=next_id(), type=ptype, points=cleaned,
                bbox=bbox, stroke_color=stroke, fill_color=fill,
                dash_pattern=dashes, line_width=width,
                layer_name=layer_name, closed=is_closed,
                area=area, page_number=page_num
            ))

    # Text extraction
    text_items = _extract_text(page, page_h, page_num, flip_y, scale)

    return PageData(
        page_number=page_num,
        width=page_w_mm, height=page_h_mm,
        primitives=primitives, text_items=text_items,
        layers=[], xobject_names=[]
    )


def _extract_text(page, page_h, page_num, flip_y, scale) -> List[NormalizedText]:
    items = []
    try:
        tdict = page.get_text("dict")
    except (RuntimeError, TypeError, ValueError):
        return items

    for block in tdict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text_dir = line.get("dir", (1.0, 0.0))
            dx = float(text_dir[0]) if text_dir else 1.0
            dy = float(text_dir[1]) if text_dir else 0.0
            angle = -math.degrees(math.atan2(dy, dx))
            for span in spans:
                text = str(span.get("text", "")).strip()
                if not text:
                    continue

                origin = span.get("origin")
                if origin and len(origin) >= 2:
                    x, y = float(origin[0]), float(origin[1])
                else:
                    bb = span.get("bbox") or line.get("bbox", (0, 0, 0, 0))
                    x = float(bb[0]) if len(bb) >= 1 else 0.0
                    y = float(bb[3] if len(bb) >= 4 else (bb[1] if len(bb) >= 2 else 0.0))

                px, py = _to_mm(x, y, page_h, flip_y, scale)
                size = max(float(span.get("size", 3)), 1.0) * MM_PER_PT * scale
                font = str(span.get("font", ""))

                # Extract text color from span
                text_color = _norm_color(span.get("color"))

                bbox_mm = None
                sb = span.get("bbox")
                if sb and len(sb) >= 4:
                    x0, y0, x1, y1 = map(float, sb[:4])
                    if flip_y:
                        by0 = (page_h - max(y0, y1)) * MM_PER_PT * scale
                        by1 = (page_h - min(y0, y1)) * MM_PER_PT * scale
                    else:
                        by0 = min(y0, y1) * MM_PER_PT * scale
                        by1 = max(y0, y1) * MM_PER_PT * scale
                    bx0 = min(x0, x1) * MM_PER_PT * scale
                    bx1 = max(x0, x1) * MM_PER_PT * scale
                    bbox_mm = (bx0, by0, bx1, by1)

                normalized = text.upper().replace("  ", " ").strip()
                generic_tags = _classify_generic(text)

                items.append(NormalizedText(
                    id=next_id(), text=text, normalized=normalized,
                    insertion=(px, py), bbox=bbox_mm, font_size=size,
                    rotation=angle, font_name=font, color=text_color,
                    page_number=page_num, generic_tags=generic_tags
                ))
    items = _merge_stacked_fractions(items)
    return items


_SLASH_RE = re.compile(r'^[/\u2044\u2215]$')
_DIGITS_RE = re.compile(r'^\d{1,4}$')
_VALID_DENOMS = (2, 4, 8, 16, 32, 64)
_FRAC_X_OVERLAP_MM = 5.0
_FRAC_Y_SPREAD_MM = 4.5


def _split_concatenated_fraction(digits: str):
    s = digits.strip()
    if not s.isdigit() or len(s) < 2:
        return None
    for denom in sorted(_VALID_DENOMS, reverse=True):
        denom_s = str(denom)
        if len(s) <= len(denom_s) or not s.endswith(denom_s):
            continue
        numer_s = s[:-len(denom_s)]
        if numer_s.isdigit() and 0 < int(numer_s) < denom:
            return numer_s, denom_s
    return None


def _merge_stacked_fractions(items: List[NormalizedText]) -> List[NormalizedText]:
    if len(items) < 2:
        return items

    by_page: dict[int, list[int]] = {}
    for idx, item in enumerate(items):
        by_page.setdefault(item.page_number, []).append(idx)

    merged_indices: set[int] = set()
    replacements: dict[int, NormalizedText] = {}

    for page_num, indices in by_page.items():
        slash_idxs = [i for i in indices if _SLASH_RE.match(items[i].text.strip())]
        for slash_idx in slash_idxs:
            if slash_idx in merged_indices:
                continue
            slash = items[slash_idx]
            sx, sy = slash.insertion

            concat_candidates = []
            for candidate_idx in indices:
                if candidate_idx == slash_idx or candidate_idx in merged_indices:
                    continue
                candidate = items[candidate_idx]
                candidate_text = candidate.text.strip()
                if not candidate_text.isdigit() or len(candidate_text) < 2:
                    continue
                cx, cy = candidate.insertion
                if abs(cx - sx) > _FRAC_X_OVERLAP_MM or abs(cy - sy) > _FRAC_Y_SPREAD_MM:
                    continue
                split = _split_concatenated_fraction(candidate_text)
                if split is not None:
                    concat_candidates.append((candidate_idx, split))

            if len(concat_candidates) == 1:
                candidate_idx, (numer_s, denom_s) = concat_candidates[0]
                candidate = items[candidate_idx]
                sizes = [candidate.font_size, slash.font_size]
                if max(sizes) <= 2.0 * min(sizes):
                    merged_text = f"{numer_s}/{denom_s}"
                    merged = NormalizedText(
                        id=next_id(),
                        text=merged_text,
                        normalized=merged_text.upper().strip(),
                        insertion=slash.insertion,
                        bbox=_merged_bbox(candidate.bbox, slash.bbox),
                        font_size=sum(sizes) / 2.0,
                        rotation=slash.rotation,
                        font_name=slash.font_name or candidate.font_name,
                        color=slash.color or candidate.color,
                        page_number=page_num,
                        generic_tags=_classify_generic(merged_text),
                    )
                    merged_indices.update([candidate_idx, slash_idx])
                    replacements[slash_idx] = merged
                    continue

            digit_candidates = []
            for candidate_idx in indices:
                if candidate_idx == slash_idx or candidate_idx in merged_indices:
                    continue
                candidate = items[candidate_idx]
                candidate_text = candidate.text.strip()
                if not _DIGITS_RE.match(candidate_text):
                    continue
                if len(candidate_text) >= 2 and _split_concatenated_fraction(candidate_text) is not None:
                    continue
                cx, cy = candidate.insertion
                if abs(cx - sx) <= _FRAC_X_OVERLAP_MM and abs(cy - sy) <= _FRAC_Y_SPREAD_MM:
                    digit_candidates.append(candidate_idx)

            if len(digit_candidates) < 2:
                continue

            digit_candidates.sort(key=lambda i: abs(items[i].insertion[1] - sy))
            best_pair = None
            best_spread = _FRAC_Y_SPREAD_MM + 1.0
            for left in range(len(digit_candidates)):
                for right in range(left + 1, len(digit_candidates)):
                    a_idx = digit_candidates[left]
                    b_idx = digit_candidates[right]
                    spread = abs(items[a_idx].insertion[1] - items[b_idx].insertion[1])
                    if spread > _FRAC_Y_SPREAD_MM or spread < 0.3:
                        continue
                    a_val = int(items[a_idx].text.strip())
                    b_val = int(items[b_idx].text.strip())
                    if a_val < b_val:
                        numer_idx, denom_idx = a_idx, b_idx
                    elif b_val < a_val:
                        numer_idx, denom_idx = b_idx, a_idx
                    else:
                        continue
                    denom_val = int(items[denom_idx].text.strip())
                    numer_val = int(items[numer_idx].text.strip())
                    if denom_val not in _VALID_DENOMS or numer_val >= denom_val:
                        continue
                    if spread < best_spread:
                        best_spread = spread
                        best_pair = (numer_idx, denom_idx)

            if best_pair is None:
                continue

            numer_idx, denom_idx = best_pair
            numer = items[numer_idx]
            denom = items[denom_idx]
            sizes = [numer.font_size, slash.font_size, denom.font_size]
            if max(sizes) <= 2.0 * min(sizes):
                merged_text = f"{numer.text.strip()}/{denom.text.strip()}"
                merged = NormalizedText(
                    id=next_id(),
                    text=merged_text,
                    normalized=merged_text.upper().strip(),
                    insertion=slash.insertion,
                    bbox=_merged_bbox(numer.bbox, slash.bbox, denom.bbox),
                    font_size=sum(sizes) / 3.0,
                    rotation=slash.rotation,
                    font_name=slash.font_name or numer.font_name,
                    color=slash.color or numer.color,
                    page_number=page_num,
                    generic_tags=_classify_generic(merged_text),
                )
                merged_indices.update([numer_idx, slash_idx, denom_idx])
                replacements[slash_idx] = merged

    if not merged_indices:
        return items

    return [
        replacements[idx] if idx in replacements else item
        for idx, item in enumerate(items)
        if idx not in merged_indices or idx in replacements
    ]


def _merged_bbox(*boxes):
    vals = [box for box in boxes if box is not None]
    if not vals:
        return None
    return (
        min(box[0] for box in vals),
        min(box[1] for box in vals),
        max(box[2] for box in vals),
        max(box[3] for box in vals),
    )


def _classify_generic(text: str) -> list:
    """Domain-neutral text tags — domain-neutral."""
    tags = []
    t = text.strip()
    tu = t.upper()

    if re.search(r"\d+['']\s*[-–]?\s*\d", t) or re.search(r"\d+\s*/\s*\d+", t):
        tags.append("dimension_like")
    if re.search(r'\d+\.?\d*\s*(?:"|mm|cm|in|ft)', t, re.I):
        tags.append("dimension_like")
    if re.search(r"SCALE[:\s]*\d", tu) or re.search(r"\d+\s*:\s*\d+", t):
        tags.append("scale_like")
    if re.search(r"\b(DRAWN|CHECKED|DATE|SCALE|REV|SHEET|PROJECT|DWG|TITLE)\b", tu):
        tags.append("titleblock_like")
    if re.search(r"Ø|\bDIA\b|\bRAD\b|\bR\d", t, re.I):
        tags.append("callout_like")
    if re.search(r"\b(DETAIL|SECTION|SEC|VIEW|ELEVATION)\s+[A-Z]", tu):
        tags.append("detail_reference")
    if len(t) > 1 and len(t) < 60 and re.search(r"[A-Z]{2,}", tu):
        tags.append("label_like")
    return tags


# ── Coordinate helpers ──

def _to_mm(x, y, page_h, flip_y, scale):
    if flip_y:
        y = page_h - y
    return x * MM_PER_PT * scale, y * MM_PER_PT * scale


def _parse_point(data):
    if len(data) >= 1 and hasattr(data[0], "x"):
        return _xy(data[0])
    if len(data) >= 2:
        return float(data[0]), float(data[1])
    return 0.0, 0.0


def _parse_cubic(data):
    if len(data) == 3 and all(hasattr(d, "x") for d in data):
        return [_xy(d) for d in data]
    if len(data) >= 6:
        return [(float(data[0]), float(data[1])),
                (float(data[2]), float(data[3])),
                (float(data[4]), float(data[5]))]
    if len(data) == 4:
        return [_xy(d) for d in data]
    return [(0, 0), (0, 0), (0, 0)]


def _parse_rect(data):
    if len(data) >= 1 and hasattr(data[0], "x0"):
        r = data[0]
        return float(r.x0), float(r.y0), float(r.x1) - float(r.x0), float(r.y1) - float(r.y0)
    if len(data) >= 4:
        return float(data[0]), float(data[1]), float(data[2]), float(data[3])
    return 0.0, 0.0, 0.0, 0.0


def _bezier_pt(p0, p1, p2, p3, t):
    u = 1.0 - t
    return (u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0],
            u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1])


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _polygon_area(pts):
    n = len(pts)
    a = 0.0
    for i in range(n):
        j = (i + 1) % n
        a += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
    return abs(a) / 2.0


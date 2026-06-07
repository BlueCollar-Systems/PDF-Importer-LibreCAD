# -*- coding: utf-8 -*-
# primitive_extractor.py — PyMuPDF -> normalized Primitives
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
THE SEAM: converts PyMuPDF page data into host-neutral Primitives.
Rule 1: Parser modules must not know about domain-specific logic.
"""
from __future__ import annotations
import math
import re
from typing import List, Optional, Tuple

from .primitives import (
    Primitive, NormalizedText, PageData, next_id
)

MM_PER_PT = 25.4 / 72.0


def _xy(obj) -> Tuple[float, float]:
    if hasattr(obj, "x") and hasattr(obj, "y"):
        return float(obj.x), float(obj.y)
    if isinstance(obj, (tuple, list)) and len(obj) >= 2:
        return float(obj[0]), float(obj[1])
    return 0.0, 0.0


def _norm_color(col) -> Optional[Tuple[float, float, float]]:
    if col is None:
        return None
    try:
        if isinstance(col, (int, float)):
            g = max(0.0, min(1.0, float(col)))
            return (g, g, g)
        vals = [max(0.0, min(1.0, float(c))) for c in col]
        if len(vals) >= 4:
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
        return None


def _parse_dashes(raw) -> Tuple[Optional[list], float]:
    """Parse PyMuPDF dash patterns into a (dash_array, phase) tuple.

    PyMuPDF returns dashes as strings like ``'[ 6 6 ] 0'`` (array + phase)
    or as actual lists/tuples.  Returns ``(None, 0.0)`` for solid lines.
    """
    if raw is None:
        return None, 0.0
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s.startswith("[]") or s == "() 0":
            return None, 0.0
        # Extract numbers between brackets: "[ 6 6 ] 0" -> [6.0, 6.0]
        bracket = s.find("[")
        bracket_end = s.find("]")
        if bracket >= 0 and bracket_end > bracket:
            inner = s[bracket + 1:bracket_end].strip()
            if not inner:
                return None, 0.0
            try:
                nums = [float(x) for x in inner.split()]
            except ValueError:
                return None, 0.0
            if not nums:
                return None, 0.0
            # Extract phase after closing bracket: "[ 6 6 ] 3" -> phase=3.0
            phase = 0.0
            after = s[bracket_end + 1:].strip()
            if after:
                try:
                    phase = float(after)
                except ValueError:
                    pass
            return nums, phase
        return None, 0.0
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None, 0.0
        # Could be ([6,6], 0) tuple or flat [6,6]
        if len(raw) == 2 and isinstance(raw[0], (list, tuple)):
            phase = 0.0
            try:
                phase = float(raw[1])
            except (TypeError, ValueError):
                pass
            return (list(raw[0]) if raw[0] else None), phase
        try:
            nums = [float(x) for x in raw]
            return (nums if nums else None), 0.0
        except (TypeError, ValueError):
            return None, 0.0
    return None, 0.0


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


def _page_mediabox_height(page) -> float:
    """Media-box height for Y-flip (PDF user space, not crop-relative)."""
    try:
        mbox = page.mediabox
        return float(mbox.height)
    except AttributeError:
        return float(page.rect.height)


def extract_page(page, page_num: int, scale: float = 1.0,
                 flip_y: bool = True) -> PageData:
    """Extract normalized primitives from a PyMuPDF page."""
    try:
        mbox = page.mediabox
        page_w_pts = float(mbox.width)
        page_h_pts = float(mbox.height)
    except AttributeError:
        page_w_pts = float(page.rect.width)
        page_h_pts = float(page.rect.height)
    page_h = page_h_pts
    page_w_mm = page_w_pts * MM_PER_PT * scale
    page_h_mm = page_h_pts * MM_PER_PT * scale

    primitives = []
    drawings = page.get_drawings()

    for path_group in drawings:
        items = path_group.get("items", [])
        if not items:
            continue

        stroke = _norm_color(path_group.get("color") or path_group.get("stroke"))
        fill = _norm_color(path_group.get("fill"))
        width = path_group.get("width")
        dashes, dash_phase = _parse_dashes(path_group.get("dashes"))
        close_path = path_group.get("closePath", False)
        layer_name = path_group.get("oc") or path_group.get("layer")

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
                dash_pattern=dashes, dash_phase=dash_phase,
                line_width=width,
                layer_name=layer_name, closed=is_closed,
                area=area, page_number=page_num
            ))

    text_items = _extract_text(page, page_h_pts, page_num, flip_y, scale)

    return PageData(
        page_number=page_num,
        width=page_w_mm, height=page_h_mm,
        primitives=primitives, text_items=text_items,
        layers=[], xobject_names=[]
    )


def _span_baseline_pdf(span: dict, line: dict) -> Tuple[float, float]:
    """Return PDF user-space (x, baseline_y) for one span.

    PyMuPDF ``origin`` is usually the baseline anchor.  When it is missing or
    an outlier, fall back to bbox bottom minus descender — same approach as the
    FreeCAD host importer so DXF/CAD text does not sit on dimension geometry.
    """
    origin = span.get("origin")
    ox = oy = None
    if origin and len(origin) >= 2:
        try:
            ox, oy = float(origin[0]), float(origin[1])
        except (TypeError, ValueError):
            ox = oy = None

    sb = span.get("bbox")
    size_pt = max(float(span.get("size", 3)), 1.0)
    desc = abs(float(span.get("descender", 0.15)))
    baseline_bbox = None
    if sb and len(sb) >= 4:
        x0 = float(sb[0])
        y1 = max(float(sb[1]), float(sb[3]))
        baseline_bbox = (x0, y1 - desc * size_pt)

    if ox is not None and oy is not None:
        if baseline_bbox is not None:
            drift = abs(oy - baseline_bbox[1])
            drift_tol = max(0.9, size_pt * 0.28)
            if drift <= drift_tol:
                return ox, oy
        return ox, oy

    if baseline_bbox is not None:
        return baseline_bbox

    lb = line.get("bbox", (0, 0, 0, 0))
    if lb and len(lb) >= 4:
        y1 = max(float(lb[1]), float(lb[3]))
        return float(lb[0]), y1 - desc * size_pt
    return 0.0, 0.0


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
            # Snap tiny floating jitter to axis to improve text/line alignment.
            if abs(dx) < 1e-7:
                dx = 0.0
            if abs(dy) < 1e-7:
                dy = 0.0
            angle = -math.degrees(math.atan2(dy, dx))

            # Process individual spans to preserve per-glyph positioning.
            # CAD PDFs often store a visual "line" as multiple positioned
            # spans; collapsing them into one string at the first-span
            # origin causes alignment drift and label overlap in viewers.
            for span in spans:
                text = str(span.get("text", "")).strip()
                if not text:
                    continue

                x, y = _span_baseline_pdf(span, line)
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
                    insertion=(px, py), bbox=bbox_mm,
                    font_size=size, rotation=angle, font_name=font,
                    color=text_color,
                    page_number=page_num, generic_tags=generic_tags
                ))
    items = _merge_stacked_fractions(items)
    return items


# ── Stacked-fraction merger ──
# Some CAD PDFs encode fractions like "15/16" as three separate text spans
# stacked vertically: numerator, slash, denominator.  This post-processor
# detects unambiguous stacked-fraction groups and merges them into a single
# NormalizedText so downstream importers see e.g. "15/16" instead of three
# overlapping items.

_SLASH_RE = re.compile(r'^[/\u2044\u2215]$')   # slash, fraction slash, division slash
_DIGITS_RE = re.compile(r'^\d{1,4}$')           # 1-4 digit number
# Concatenated numerator+denominator: e.g. "716" = 7/16, "1116" = 11/16.
# Valid denominators for imperial fractions.
_VALID_DENOMS = (2, 4, 8, 16, 32, 64)

# Thresholds (mm).  5 pt ≈ 1.76 mm, 6 pt ≈ 2.12 mm.
_FRAC_X_OVERLAP_MM = 5.0   # max horizontal gap between items to consider co-located
_FRAC_Y_SPREAD_MM = 4.5    # max total vertical spread for the whole group


def _split_concatenated_fraction(digits: str):
    """Try to split a concatenated digit string into (numerator, denominator).

    E.g. "716" -> ("7", "16"), "1116" -> ("11", "16"), "316" -> ("3", "16").
    Returns None if no valid split is found.
    """
    s = digits.strip()
    if not s.isdigit() or len(s) < 2:
        return None
    # Try splitting: denominator is a known fraction denominator at the end
    for d in sorted(_VALID_DENOMS, reverse=True):
        ds = str(d)
        if len(s) > len(ds) and s.endswith(ds):
            numer = s[:-len(ds)]
            if numer.isdigit():
                n = int(numer)
                # Numerator must be less than denominator for a proper fraction
                if 0 < n < d:
                    return (numer, ds)
    return None


def _merge_stacked_fractions(items: List[NormalizedText]) -> List[NormalizedText]:
    """Merge stacked fraction spans into one.

    Handles two PDF encoding patterns:
    1. Two items: concatenated digits + "/" (e.g. "716" + "/" -> "7/16")
       This is the most common pattern in CAD PDFs.
    2. Three items: separate numerator + "/" + denominator (e.g. "15", "/", "16")
       Only matched when neither digit item is itself a concatenated fraction.
    """
    if len(items) < 2:
        return items

    # Group candidates by page
    by_page: dict[int, list[int]] = {}
    for idx, it in enumerate(items):
        by_page.setdefault(it.page_number, []).append(idx)

    merged_indices: set[int] = set()
    replacements: dict[int, NormalizedText] = {}  # keyed by slash index

    for page_num, indices in by_page.items():
        # Find slash items on this page
        slash_idxs = [i for i in indices if _SLASH_RE.match(items[i].text.strip())]

        for si in slash_idxs:
            if si in merged_indices:
                continue
            slash = items[si]
            sx = slash.insertion[0]
            sy = slash.insertion[1]

            # ----------------------------------------------------------
            # Pattern A: Concatenated digits + slash (e.g. "716" + "/")
            # Try this FIRST — it is the most common and unambiguous.
            # ----------------------------------------------------------
            concat_candidates = []
            for ci in indices:
                if ci == si or ci in merged_indices:
                    continue
                cand = items[ci]
                ct = cand.text.strip()
                if not ct.isdigit() or len(ct) < 2:
                    continue
                cx = cand.insertion[0]
                cy = cand.insertion[1]
                if abs(cx - sx) > _FRAC_X_OVERLAP_MM:
                    continue
                if abs(cy - sy) > _FRAC_Y_SPREAD_MM:
                    continue
                split = _split_concatenated_fraction(ct)
                if split is not None:
                    concat_candidates.append((ci, split))

            if len(concat_candidates) == 1:
                ci, (numer_s, denom_s) = concat_candidates[0]
                cand = items[ci]
                sizes = [cand.font_size, slash.font_size]
                if max(sizes) <= 2.0 * min(sizes):
                    merged_text = f"{numer_s}/{denom_s}"
                    avg_size = sum(sizes) / 2.0
                    merged_item = NormalizedText(
                        id=next_id(),
                        text=merged_text,
                        normalized=merged_text.upper().strip(),
                        insertion=slash.insertion,
                        bbox=_merged_bbox(cand.bbox, slash.bbox),
                        font_size=avg_size,
                        rotation=slash.rotation,
                        font_name=slash.font_name or cand.font_name,
                        color=slash.color or cand.color,
                        page_number=page_num,
                        generic_tags=_classify_generic(merged_text),
                    )
                    merged_indices.update([ci, si])
                    replacements[si] = merged_item
                    continue

            # ----------------------------------------------------------
            # Pattern B: Three separate items (numerator + slash + denom)
            # Only if Pattern A didn't match. Require that neither digit
            # is itself a concatenated fraction (to avoid grabbing whole
            # numbers that sit next to an already-handled concat fraction).
            # ----------------------------------------------------------
            digit_candidates = []
            for ci in indices:
                if ci == si or ci in merged_indices:
                    continue
                cand = items[ci]
                ct = cand.text.strip()
                if not _DIGITS_RE.match(ct):
                    continue
                # Skip items that are concatenated fractions — those belong
                # to Pattern A with a different slash.
                if len(ct) >= 2 and _split_concatenated_fraction(ct) is not None:
                    continue
                cx = cand.insertion[0]
                cy = cand.insertion[1]
                if abs(cx - sx) > _FRAC_X_OVERLAP_MM:
                    continue
                if abs(cy - sy) > _FRAC_Y_SPREAD_MM:
                    continue
                digit_candidates.append(ci)

            if len(digit_candidates) >= 2:
                # Try all pairs to find a valid numerator/denominator.
                # Sort by closeness to slash Y so we prefer the tightest pair.
                digit_candidates.sort(key=lambda i: abs(items[i].insertion[1] - sy))
                best_pair = None
                best_spread = _FRAC_Y_SPREAD_MM + 1
                for ai in range(len(digit_candidates)):
                    for bi in range(ai + 1, len(digit_candidates)):
                        ca, cb = digit_candidates[ai], digit_candidates[bi]
                        ya = items[ca].insertion[1]
                        yb = items[cb].insertion[1]
                        spread = abs(ya - yb)
                        if spread > _FRAC_Y_SPREAD_MM or spread < 0.3:
                            continue
                        try:
                            va = int(items[ca].text.strip())
                            vb = int(items[cb].text.strip())
                        except ValueError:
                            continue
                        if va < vb:
                            ni, di = ca, cb
                        elif vb < va:
                            ni, di = cb, ca
                        else:
                            continue
                        d_val = int(items[di].text.strip())
                        n_val = int(items[ni].text.strip())
                        if d_val not in _VALID_DENOMS or n_val >= d_val:
                            continue
                        if spread < best_spread:
                            best_spread = spread
                            best_pair = (ni, di)
                if best_pair is not None:
                    numer_idx, denom_idx = best_pair
                    numer = items[numer_idx]
                    denom = items[denom_idx]
                    sizes = [numer.font_size, slash.font_size, denom.font_size]
                    if max(sizes) <= 2.0 * min(sizes):
                        merged_text = f"{numer.text.strip()}/{denom.text.strip()}"
                        avg_size = sum(sizes) / 3.0
                        merged_item = NormalizedText(
                            id=next_id(),
                            text=merged_text,
                            normalized=merged_text.upper().strip(),
                            insertion=slash.insertion,
                            bbox=_merged_bbox(numer.bbox, slash.bbox, denom.bbox),
                            font_size=avg_size,
                            rotation=slash.rotation,
                            font_name=slash.font_name or numer.font_name,
                            color=slash.color or numer.color,
                            page_number=page_num,
                            generic_tags=_classify_generic(merged_text),
                        )
                        merged_indices.update([numer_idx, si, denom_idx])
                        replacements[si] = merged_item
                        continue

            # ----------------------------------------------------------
            # Pattern C: Horizontal fraction (e.g. "3" + "/" + "4" on one line)
            # ----------------------------------------------------------
            horiz_digits = []
            for ci in indices:
                if ci == si or ci in merged_indices:
                    continue
                cand = items[ci]
                ct = cand.text.strip()
                if not _DIGITS_RE.match(ct):
                    continue
                if len(ct) >= 2 and _split_concatenated_fraction(ct) is not None:
                    continue
                cx = cand.insertion[0]
                cy = cand.insertion[1]
                if abs(cy - sy) > 1.2:
                    continue
                horiz_digits.append(ci)

            left = [ci for ci in horiz_digits if items[ci].insertion[0] < sx - 0.05]
            right = [ci for ci in horiz_digits if items[ci].insertion[0] > sx + 0.05]
            if len(left) == 1 and len(right) == 1:
                numer_idx, denom_idx = left[0], right[0]
                numer = items[numer_idx]
                denom = items[denom_idx]
                try:
                    n_val = int(numer.text.strip())
                    d_val = int(denom.text.strip())
                except ValueError:
                    n_val = d_val = -1
                if d_val in _VALID_DENOMS and 0 < n_val < d_val:
                    gap_l = sx - numer.insertion[0]
                    gap_r = denom.insertion[0] - sx
                    if gap_l <= 8.0 and gap_r <= 8.0:
                        sizes = [numer.font_size, slash.font_size, denom.font_size]
                        if max(sizes) <= 2.0 * min(sizes):
                            merged_text = f"{numer.text.strip()}/{denom.text.strip()}"
                            avg_size = sum(sizes) / 3.0
                            merged_item = NormalizedText(
                                id=next_id(),
                                text=merged_text,
                                normalized=merged_text.upper().strip(),
                                insertion=slash.insertion,
                                bbox=_merged_bbox(numer.bbox, slash.bbox, denom.bbox),
                                font_size=avg_size,
                                rotation=slash.rotation,
                                font_name=slash.font_name or numer.font_name,
                                color=slash.color or numer.color,
                                page_number=page_num,
                                generic_tags=_classify_generic(merged_text),
                            )
                            merged_indices.update([numer_idx, si, denom_idx])
                            replacements[si] = merged_item

    if not merged_indices:
        return items

    # Rebuild list: keep non-merged items, insert merged items at slash position
    result = []
    for idx, it in enumerate(items):
        if idx in merged_indices:
            if idx in replacements:
                result.append(replacements[idx])
            # else: skip (numerator or denominator that was merged)
        else:
            result.append(it)
    return result


def _merged_bbox(*boxes):
    """Return the union bounding box of one or more (x0,y0,x1,y1) or None boxes."""
    vals = [b for b in boxes if b is not None]
    if not vals:
        return None
    x0 = min(b[0] for b in vals)
    y0 = min(b[1] for b in vals)
    x1 = max(b[2] for b in vals)
    y1 = max(b[3] for b in vals)
    return (x0, y0, x1, y1)


def _classify_generic(text: str) -> list:
    tags = []
    t = text.strip()
    tu = t.upper()
    if re.search(r"\d+['']\s*[-\u2013]?\s*\d", t) or re.search(r"\d+\s*/\s*\d+", t):
        tags.append("dimension_like")
    if re.search(r'\d+\.?\d*\s*(?:"|mm|cm|in|ft)', t, re.I):
        tags.append("dimension_like")
    if re.search(r"SCALE[:\s]*\d", tu) or re.search(r"\d+\s*:\s*\d+", t):
        tags.append("scale_like")
    if re.search(r"\b(DRAWN|CHECKED|DATE|SCALE|REV|SHEET|PROJECT|DWG|TITLE)\b", tu):
        tags.append("titleblock_like")
    if re.search(r"\u00D8|\bDIA\b|\bRAD\b|\bR\d", t, re.I):
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

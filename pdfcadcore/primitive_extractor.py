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
    NormalizedText,
    PageData,
    Primitive,
    TextCharLayout,
    next_id,
)
from .geometry_cleanup import promote_circular_primitives
from .text_scale import effective_span_font_size_pt

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
        if isinstance(col, int) and not isinstance(col, bool):
            if col < 0:
                return None
            packed = int(col) & 0xFFFFFF
            return (
                ((packed >> 16) & 0xFF) / 255.0,
                ((packed >> 8) & 0xFF) / 255.0,
                (packed & 0xFF) / 255.0,
            )
        if isinstance(col, float):
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
    to_model,
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

    out = [to_model(x, y) for x, y in corners]
    if len(out) >= 4:
        out.append(out[0])
    return out


def _page_rotation(page) -> int:
    """Return the PDF /Rotate entry (0, 90, 180, 270) normalised to [0,360)."""
    try:
        rot = int(getattr(page, "rotation", 0) or 0)
    except (TypeError, ValueError):
        rot = 0
    return rot % 360


def _page_mediabox_height(page) -> float:
    """Media-box height for Y-flip accounting for PDF /Rotate.

    PDF user-space coordinates are defined in the *unrotated* mediabox, but
    PyMuPDF applies /Rotate when building ``page.rect``.  For 90°/270° pages
    the viewer swaps width↔height, so we must use the rotated dimension as the
    Y-flip baseline to match what ``get_drawings`` / ``get_text`` actually
    returns (which is already in the *rotated* display space).
    """
    rot = _page_rotation(page)
    try:
        mbox = page.mediabox
        w, h = float(mbox.width), float(mbox.height)
    except AttributeError:
        w, h = float(page.rect.width), float(page.rect.height)
    if rot in (90, 270):
        # Rotated page: display height == mediabox width
        return w
    return h


def _collect_page_layers(primitives: List[Primitive]) -> List[str]:
    """Return sorted unique OCG/layer names present on a page."""
    names: set[str] = set()
    for prim in primitives:
        layer = prim.layer_name
        if layer is not None:
            name = str(layer).strip()
            if name:
                names.add(name)
    return sorted(names)


def extract_page(
    page,
    page_num: int,
    scale: float = 1.0,
    flip_y: bool = True,
    detect_arcs: bool = True,
    arc_fit_tol_mm: float = 0.05,
    min_arc_angle_deg: float = 5.0,
    arc_min_pts: int = 5,
) -> PageData:
    """Extract normalized primitives from a PyMuPDF page."""
    # ``page.rect`` is the authoritative visible CropBox + UserUnit + /Rotate
    # extent. PyMuPDF drawing/text coordinates remain crop-local source points;
    # apply the page rotation matrix once before the model Y flip.
    page_rect = page.rect
    page_w_pts = float(page_rect.width)
    page_h_pts = float(page_rect.height)
    rotation_matrix = _page_rotation_transform(
        page_rect,
        getattr(page, "rotation_matrix", None),
    )

    def to_model(x, y):
        return _page_point_to_mm(
            x, y, rotation_matrix, page_h_pts, flip_y, scale
        )

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
        try:
            width = float(width) * MM_PER_PT * scale if width is not None else None
        except (TypeError, ValueError):
            width = None
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
                px, py = to_model(x, y)
                current_pts = [(px, py)]

            elif kind == "l":
                if len(data) >= 2 and hasattr(data[0], "x") and hasattr(data[1], "x"):
                    x0, y0 = _xy(data[0])
                    x1, y1 = _xy(data[1])
                    p0 = to_model(x0, y0)
                    p1 = to_model(x1, y1)
                    if not current_pts:
                        current_pts.append(p0)
                    current_pts.append(p1)
                else:
                    x, y = _parse_point(data)
                    current_pts.append(to_model(x, y))

            elif kind == "c":
                if len(data) == 4 and all(hasattr(d, "x") for d in data):
                    pts = [_xy(d) for d in data]
                else:
                    pts = _parse_cubic(data)
                p0 = to_model(pts[0][0], pts[0][1])
                p1 = to_model(pts[1][0], pts[1][1])
                p2 = to_model(pts[2][0], pts[2][1])
                p3 = to_model(
                    pts[3][0] if len(pts) > 3 else pts[2][0],
                    pts[3][1] if len(pts) > 3 else pts[2][1],
                )
                _append_linearized_cubic(current_pts, p0, p1, p2, p3)

            elif kind == "re":
                flush(False)
                x, y, w, h = _parse_rect(data)
                c1 = to_model(x, y)
                c2 = to_model(x + w, y)
                c3 = to_model(x + w, y + h)
                c4 = to_model(x, y + h)
                sub_paths.append(([c1, c2, c3, c4, c1], True))

            elif kind == "qu":
                flush(False)
                quad = data[0] if data else None
                pts = _quad_to_points(quad, to_model) if quad is not None else []
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
                    p2 = to_model(c2x, c2y)
                    p3 = to_model(ex, ey)
                    _append_linearized_cubic(current_pts, p0, p1, p2, p3)

            elif kind == "y":
                # PDF "y": (c1, end), c2 equals end.
                if len(data) >= 2 and current_pts:
                    c1x, c1y = _xy(data[0])
                    ex, ey = _xy(data[1])
                    p0 = current_pts[-1]
                    p1 = to_model(c1x, c1y)
                    p3 = to_model(ex, ey)
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

    if detect_arcs:
        # Performance gate: only pass polylines that have enough points to
        # form a plausible arc and meet the minimum angle span.  This avoids
        # running the full Kasa circle-fit on thousands of short lines in
        # dense drawings, cutting per-page time significantly on large PDFs.
        #
        # Partition in a single pass. Every Primitive has a unique ``id`` so
        # no two are value-equal; splitting by the candidate predicate yields
        # exactly the same two lists (and order) as the previous
        # ``p not in arc_candidates`` membership test, but in O(n) instead of
        # O(n^2) dataclass __eq__ comparisons (the dominant cost on
        # primitive-dense pages).
        arc_candidates = []
        non_candidates = []
        for p in primitives:
            if p.type in ("polyline", "closed_loop") and len(p.points or []) >= arc_min_pts:
                arc_candidates.append(p)
            else:
                non_candidates.append(p)
        promote_circular_primitives(
            arc_candidates,
            arc_fit_tol_mm=arc_fit_tol_mm,
            min_arc_angle_deg=min_arc_angle_deg,
        )
        primitives = non_candidates + arc_candidates

    text_items = _extract_text(
        page,
        page_h_pts,
        page_num,
        flip_y,
        scale,
        to_model=to_model,
    )
    layers = _collect_page_layers(primitives)

    page_data = PageData(
        page_number=page_num,
        width=page_w_mm, height=page_h_mm,
        primitives=primitives, text_items=text_items,
        layers=layers, xobject_names=[]
    )
    from .generic_classifier import classify_text
    from .resolved_scale import resolve_page_scale

    classify_text(page_data)
    page_data.resolved_scale = resolve_page_scale(page_data)
    return page_data


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
    try:
        size_pt = float(span.get("size", 3))
    except (TypeError, ValueError):
        size_pt = 3.0
    if not math.isfinite(size_pt) or size_pt <= 0.0:
        size_pt = 3.0
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


def _span_quad_pdf(line: dict, span: dict):
    """Return one source span quad as UL, UR, LR, LL coordinates."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover
            import fitz  # type: ignore
        quad = fitz.recover_quad(line.get("dir", (1.0, 0.0)), span)
        return tuple(_xy(point) for point in (quad.ul, quad.ur, quad.lr, quad.ll))
    except (AttributeError, ImportError, KeyError, RuntimeError, TypeError, ValueError):
        bbox = span.get("bbox")
        if bbox and len(bbox) >= 4:
            x0, y0, x1, y1 = map(float, bbox[:4])
            return (
                (min(x0, x1), min(y0, y1)),
                (max(x0, x1), min(y0, y1)),
                (max(x0, x1), max(y0, y1)),
                (min(x0, x1), max(y0, y1)),
            )
    return None


def _quad_points(value):
    """Normalize a PyMuPDF Quad or a four/flat-eight point sequence."""
    if value is None:
        return None
    try:
        if all(hasattr(value, name) for name in ("ul", "ur", "lr", "ll")):
            return tuple(_xy(getattr(value, name)) for name in ("ul", "ur", "lr", "ll"))
        values = list(value)
        if len(values) == 4:
            points = tuple(_xy(point) for point in values)
            if all(len(point) == 2 for point in points):
                return points
        if len(values) == 8:
            return tuple(
                (float(values[index]), float(values[index + 1]))
                for index in range(0, 8, 2)
            )
    except (AttributeError, TypeError, ValueError):
        return None
    return None


def _char_quad_pdf(line: dict, span: dict, char: dict):
    explicit = _quad_points(char.get("quad"))
    if explicit is not None:
        return explicit
    try:
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover
            import fitz  # type: ignore
        quad = fitz.recover_char_quad(line.get("dir", (1.0, 0.0)), span, char)
        recovered = _quad_points(quad)
        if recovered is not None:
            return recovered
    except (AttributeError, ImportError, KeyError, RuntimeError, TypeError, ValueError):
        pass
    bbox = char.get("bbox")
    if bbox and len(bbox) >= 4:
        x0, y0, x1, y1 = map(float, bbox[:4])
        return (
            (min(x0, x1), min(y0, y1)),
            (max(x0, x1), min(y0, y1)),
            (max(x0, x1), max(y0, y1)),
            (min(x0, x1), max(y0, y1)),
        )
    return None


def _trace_glyph_queues(page):
    """Bind raw characters to the PDF glyph IDs from this exact page trace."""
    queues = {}
    try:
        traces = page.get_texttrace()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return queues
    for trace in traces or ():
        font = str(trace.get("font", "") or "")
        for entry in trace.get("chars", ()) or ():
            try:
                if isinstance(entry, dict):
                    raw_unicode = entry.get("unicode", entry.get("c"))
                    raw_glyph = entry.get("glyph", entry.get("gid"))
                    codepoint = ord(raw_unicode) if isinstance(raw_unicode, str) else int(raw_unicode)
                    glyph_id = int(raw_glyph)
                else:
                    codepoint = int(entry[0])
                    glyph_id = int(entry[1])
            except (IndexError, TypeError, ValueError):
                continue
            queues.setdefault((font, codepoint), []).append(glyph_id)
    return queues


def _pop_trace_glyph_id(queues, font: str, text: str):
    if not text:
        return None
    key = (str(font or ""), ord(text[0]))
    candidates = queues.get(key)
    if not candidates:
        return None
    return candidates.pop(0)


def _span_text_and_chars(span: dict):
    chars = tuple(span.get("chars", ()) or ())
    if chars:
        return "".join(str(char.get("c", "") or "") for char in chars), chars
    return str(span.get("text", "") or ""), ()


def _character_layout(line, span, font, to_model, glyph_queues):
    layouts = []
    for char in tuple(span.get("chars", ()) or ()):
        text = str(char.get("c", "") or "")
        if text == "":
            continue
        quad = _char_quad_pdf(line, span, char)
        bbox = char.get("bbox")
        if not bbox or len(bbox) < 4 or quad is None:
            continue
        x0, y0, x1, y1 = map(float, bbox[:4])
        source_bbox = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        origin = char.get("origin")
        if origin and len(origin) >= 2:
            source_origin = (float(origin[0]), float(origin[1]))
        else:
            source_origin = tuple(quad[3])
        target_quad = tuple(to_model(x, y) for x, y in quad)
        target_origin = to_model(*source_origin)
        layouts.append(TextCharLayout(
            text=text,
            glyph_id=_pop_trace_glyph_id(glyph_queues, font, text),
            source_origin_pdf=source_origin,
            source_bbox_pdf=source_bbox,
            source_quad_pdf=tuple(quad),
            target_origin=tuple(target_origin),
            target_quad=target_quad,
            advance_width=_dist(target_quad[0], target_quad[1]),
            glyph_height=_dist(target_quad[0], target_quad[3]),
        ))
    return tuple(layouts)


def _extract_text(
    page,
    page_h,
    page_num,
    flip_y,
    scale,
    *,
    page_w=None,
    rotation=0,
    to_model=None,
) -> List[NormalizedText]:
    items = []
    if to_model is None:
        raw_page_w = float(page_w if page_w is not None else 0.0)
        to_model = lambda x, y: _to_mm(  # noqa: E731
            x,
            y,
            page_h,
            flip_y,
            scale,
            page_w=raw_page_w,
            rotation=rotation,
        )
    try:
        tdict = page.get_text("rawdict")
    except (AssertionError, RuntimeError, TypeError, ValueError):
        try:
            tdict = page.get_text("dict")
        except (RuntimeError, TypeError, ValueError):
            return items
    try:
        from .embedded_fonts import EmbeddedFontCatalog

        font_catalog = EmbeddedFontCatalog.from_page(page, page_num)
    except (ImportError, RuntimeError, TypeError, ValueError):
        font_catalog = None
    glyph_queues = _trace_glyph_queues(page)

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
            origin_model = to_model(0.0, 0.0)
            direction_model = to_model(dx, dy)
            angle = math.degrees(
                math.atan2(
                    direction_model[1] - origin_model[1],
                    direction_model[0] - origin_model[0],
                )
            )

            # Process individual spans to preserve per-glyph positioning.
            # CAD PDFs often store a visual "line" as multiple positioned
            # spans; collapsing them into one string at the first-span
            # origin causes alignment drift and label overlap in viewers.
            for span in spans:
                text, raw_chars = _span_text_and_chars(span)
                if text == "":
                    continue

                x, y = _span_baseline_pdf(span, line)
                px, py = to_model(x, y)
                size_pt = effective_span_font_size_pt(span, angle)
                size = size_pt * MM_PER_PT * scale
                font = str(span.get("font", ""))
                try:
                    descender_ratio = float(span.get("descender", 0.0) or 0.0)
                except (TypeError, ValueError):
                    descender_ratio = 0.0
                baseline_descent = max(0.0, -descender_ratio) * size

                # Extract text color from span
                text_color = _norm_color(span.get("color"))

                bbox_mm = None
                source_bbox_pdf = None
                sb = span.get("bbox")
                if sb and len(sb) >= 4:
                    x0, y0, x1, y1 = map(float, sb[:4])
                    source_bbox_pdf = (
                        min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
                    )

                source_quad_pdf = _span_quad_pdf(line, span)
                model_quad = (
                    tuple(to_model(xq, yq) for xq, yq in source_quad_pdf)
                    if source_quad_pdf
                    else None
                )
                if model_quad:
                    qxs = [point[0] for point in model_quad]
                    qys = [point[1] for point in model_quad]
                    bbox_mm = (min(qxs), min(qys), max(qxs), max(qys))
                    advance_width = _dist(model_quad[0], model_quad[1])
                    glyph_height = _dist(model_quad[0], model_quad[3])
                else:
                    advance_width = 0.0
                    glyph_height = 0.0

                font_asset = font_catalog.for_span(font) if font_catalog else None
                font_failure = (
                    None
                    if font_asset is not None
                    else font_catalog.failure_for_span(font) if font_catalog else None
                )

                normalized = text.upper().replace("  ", " ").strip()
                generic_tags = _classify_generic(text)
                char_layout = (
                    _character_layout(line, span, font, to_model, glyph_queues)
                    if raw_chars
                    else ()
                )

                items.append(NormalizedText(
                    # Text identity is page-local source order. It must not
                    # change with vector density or earlier imported documents.
                    id=len(items) + 1, text=text, normalized=normalized,
                    insertion=(px, py), bbox=bbox_mm,
                    font_size=size, rotation=angle, font_name=font,
                    color=text_color,
                    page_number=page_num, generic_tags=generic_tags,
                    source_bbox_pdf=source_bbox_pdf,
                    source_quad_pdf=source_quad_pdf,
                    target_quad_model=model_quad,
                    advance_width=advance_width,
                    glyph_height=glyph_height,
                    baseline_descent=baseline_descent,
                    source_char_layout=char_layout,
                    requires_individual_positioning=bool(char_layout),
                    font_asset=font_asset,
                    font_failure=font_failure,
                ))
    # Stacked-fraction spans ("7" over "16", or "716" + "/") ARE the
    # dimension value 7/16 on fabrication drawings; extraction owns this
    # semantic merge (RB-16 cross-host golden, stacked-fraction-extract).
    # Representation modes govern HOW a delivered value renders, never WHAT
    # the value is — the render stage must not alter it further.
    items = _merge_stacked_fractions(items)
    # Text identity is page-local source order (see the id note above). The
    # merger allocates replacement ids from the global counter, so re-index
    # after merging to keep ids deterministic and dense regardless of global
    # counter state or earlier imported documents.
    for index, item in enumerate(items):
        item.id = index + 1
    return items


# ── Stacked-fraction merger ──
# Some CAD PDFs encode fractions like "15/16" as three separate text spans
# stacked vertically: numerator, slash, denominator.  This post-processor
# detects unambiguous stacked-fraction groups and merges them into a single
# NormalizedText so downstream importers see e.g. "15/16" instead of three
# overlapping items.

_SLASH_RE = re.compile(r'^[/\u2044\u2215]$')   # slash, fraction slash, division slash
_DIGITS_RE = re.compile(r'^\d{1,4}$')           # 1-4 digit number
_FRACTION_TEXT_RE = re.compile(r'^\d{1,3}\s*/\s*\d{1,3}$')
# Concatenated numerator+denominator: e.g. "716" = 7/16, "1116" = 11/16.
# Valid denominators for imperial fractions.
_VALID_DENOMS = (2, 4, 8, 16, 32, 64)

# Thresholds (mm).  5 pt ≈ 1.76 mm, 6 pt ≈ 2.12 mm.
_FRAC_X_OVERLAP_MM = 5.0   # max horizontal gap between items to consider co-located
_FRAC_Y_SPREAD_MM = 4.5    # max total vertical spread for the whole group
_FRAC_STACKED_SCALE = 0.6  # scale factor for stacked fractions to match original footprint


def _prefer_fraction_digit_candidates(indices: List[int], items: List[NormalizedText]) -> List[int]:
    """Drop nearby whole-number digits when smaller fraction digits are present."""
    if len(indices) <= 2:
        return indices

    sizes = [max(float(items[i].font_size or 0.0), 0.0) for i in indices]
    positive_sizes = [s for s in sizes if s > 0.0]
    if len(positive_sizes) < 2:
        return indices

    min_size = min(positive_sizes)
    max_size = max(positive_sizes)
    if max_size <= min_size * 1.10:
        return indices

    small = [
        idx
        for idx in indices
        if max(float(items[idx].font_size or 0.0), 0.0) <= min_size * 1.12
    ]
    return small if len(small) >= 2 else indices


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


def _merged_fraction_fidelity(parts: List[NormalizedText]) -> dict:
    """Fidelity fields for a merged stacked-fraction replacement item.

    The merged text (e.g. "7/16") is a semantic value whose characters no
    longer map 1:1 onto any single source span, so per-character layout is
    intentionally dropped and the merged item positions as a whole string at
    the slash insertion (the documented legacy merged-fraction path).
    Source/target quads are the unscaled union of the constituent spans;
    font identity follows the numerator digits (``parts[0]``) with the
    remaining parts as fallback.
    """
    fields: dict = {
        "source_char_layout": (),
        "requires_individual_positioning": False,
    }

    src_union = _merged_bbox(*[part.source_bbox_pdf for part in parts])
    if src_union is not None:
        x0, y0, x1, y1 = src_union
        fields["source_bbox_pdf"] = src_union
        # UL, UR, LR, LL in PDF space (y grows downward).
        fields["source_quad_pdf"] = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))

    points = [
        point
        for part in parts
        if part.target_quad_model
        for point in part.target_quad_model
    ]
    if points:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        # UL, UR, LR, LL in model space (y grows upward); q0->q1 spans the
        # baseline direction and q0->q3 the vertical extent, matching
        # ``_extract_text``.
        quad = ((x0, y1), (x1, y1), (x1, y0), (x0, y0))
        fields["target_quad_model"] = quad
        fields["advance_width"] = _dist(quad[0], quad[1])
        fields["glyph_height"] = _dist(quad[0], quad[3])

    fields["baseline_descent"] = max(
        [part.baseline_descent for part in parts] or [0.0]
    )
    for part in parts:
        if part.font_asset is not None:
            fields["font_asset"] = part.font_asset
            break
    if fields.get("font_asset") is None:
        for part in parts:
            if part.font_failure is not None:
                fields["font_failure"] = part.font_failure
                break
    return fields


def _merge_stacked_fractions(items: List[NormalizedText]) -> List[NormalizedText]:
    """Merge stacked fraction spans into one.

    Handles two PDF encoding patterns:
    1. Two items: concatenated digits + "/" (e.g. "716" + "/" -> "7/16")
       This is the most common pattern in CAD PDFs.
    2. Three items: separate numerator + "/" + denominator (e.g. "15", "/", "16")
       Only matched when neither digit item is itself a concatenated fraction.

    NOTE: Merged fractions use reduced font_size (~0.6x) to match stacked footprint.
    Replacement items take ids from the global counter; ``_extract_text``
    re-indexes its output afterwards so pipeline ids stay page-local and
    deterministic.
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
                    distance = abs(cx - sx) + abs(cy - sy)
                    concat_candidates.append((ci, split, distance))

            if concat_candidates:
                concat_candidates.sort(key=lambda entry: entry[2])
                _nearest_idx, nearest_split, nearest_distance = concat_candidates[0]
                different_close = any(
                    split != nearest_split and distance <= nearest_distance + 1.0
                    for _ci, split, distance in concat_candidates[1:]
                )
                selected_indices = [
                    ci
                    for ci, split, distance in concat_candidates
                    if split == nearest_split and distance <= nearest_distance + _FRAC_Y_SPREAD_MM
                ]
                if not different_close and selected_indices:
                    numer_s, denom_s = nearest_split
                    selected = [items[ci] for ci in selected_indices]
                    sizes = [item.font_size for item in selected] + [slash.font_size]
                else:
                    sizes = []
                if sizes and min(sizes) > 0 and max(sizes) <= 2.0 * min(sizes):
                    merged_text = f"{numer_s}/{denom_s}"
                    avg_size = sum(sizes) / float(len(sizes))
                    # Apply stacked fraction scale to match original footprint
                    stacked_size = avg_size * _FRAC_STACKED_SCALE
                    first = selected[0]
                    merged_item = NormalizedText(
                        id=next_id(),
                        text=merged_text,
                        normalized=merged_text.upper().strip(),
                        insertion=slash.insertion,
                        bbox=_merged_bbox(
                            *[item.bbox for item in selected],
                            slash.bbox,
                            scale_width=_FRAC_STACKED_SCALE,
                        ),
                        font_size=stacked_size,
                        rotation=slash.rotation,
                        font_name=slash.font_name or first.font_name,
                        color=slash.color or first.color,
                        page_number=page_num,
                        generic_tags=_classify_generic(merged_text),
                        **_merged_fraction_fidelity(selected + [slash]),
                    )
                    merged_indices.update(selected_indices + [si])
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
                digit_candidates = _prefer_fraction_digit_candidates(digit_candidates, items)
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
                        # Apply stacked fraction scale to match original footprint
                        stacked_size = avg_size * _FRAC_STACKED_SCALE
                        merged_item = NormalizedText(
                            id=next_id(),
                            text=merged_text,
                            normalized=merged_text.upper().strip(),
                            insertion=slash.insertion,
                            bbox=_merged_bbox(numer.bbox, slash.bbox, denom.bbox, scale_width=_FRAC_STACKED_SCALE),
                            font_size=stacked_size,
                            rotation=slash.rotation,
                            font_name=slash.font_name or numer.font_name,
                            color=slash.color or numer.color,
                            page_number=page_num,
                            generic_tags=_classify_generic(merged_text),
                            **_merged_fraction_fidelity([numer, slash, denom]),
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
                            # Apply stacked fraction scale to match original footprint
                            stacked_size = avg_size * _FRAC_STACKED_SCALE
                            merged_item = NormalizedText(
                                id=next_id(),
                                text=merged_text,
                                normalized=merged_text.upper().strip(),
                                insertion=slash.insertion,
                                bbox=_merged_bbox(numer.bbox, slash.bbox, denom.bbox, scale_width=_FRAC_STACKED_SCALE),
                                font_size=stacked_size,
                                rotation=slash.rotation,
                                font_name=slash.font_name or numer.font_name,
                                color=slash.color or numer.color,
                                page_number=page_num,
                                generic_tags=_classify_generic(merged_text),
                                **_merged_fraction_fidelity([numer, slash, denom]),
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
    return _dedupe_fraction_overlays(result)


def _bbox_center(box):
    if not box:
        return None
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _bbox_gap(a, b) -> float:
    if not a or not b:
        return 0.0
    x_gap = max(a[0] - b[2], b[0] - a[2], 0.0)
    y_gap = max(a[1] - b[3], b[1] - a[3], 0.0)
    return max(x_gap, y_gap)


def _fraction_overlay_duplicate(a: NormalizedText, b: NormalizedText) -> bool:
    """Return True for duplicate fraction overlays emitted by CAD text stacks."""
    ta = (a.text or "").strip().replace(" ", "")
    tb = (b.text or "").strip().replace(" ", "")
    if ta != tb or not _FRACTION_TEXT_RE.match(ta):
        return False
    if a.page_number != b.page_number:
        return False
    try:
        if abs(float(a.rotation or 0.0) - float(b.rotation or 0.0)) > 1.0:
            return False
    except (TypeError, ValueError):
        pass
    ca = _bbox_center(a.bbox)
    cb = _bbox_center(b.bbox)
    if ca is None or cb is None:
        return False
    return (
        abs(ca[0] - cb[0]) <= _FRAC_X_OVERLAP_MM
        and abs(ca[1] - cb[1]) <= (_FRAC_Y_SPREAD_MM + 1.0)
        and _bbox_gap(a.bbox, b.bbox) <= 1.0
    )


def _slash_fraction_overlay_duplicate(slash: NormalizedText, fraction: NormalizedText) -> bool:
    """Return True when a leftover slash is already represented by a fraction."""
    if not _SLASH_RE.match((slash.text or "").strip()):
        return False
    text = (fraction.text or "").strip().replace(" ", "")
    if not _FRACTION_TEXT_RE.match(text):
        return False
    if slash.page_number != fraction.page_number:
        return False
    try:
        if abs(float(slash.rotation or 0.0) - float(fraction.rotation or 0.0)) > 1.0:
            return False
    except (TypeError, ValueError):
        pass
    cs = _bbox_center(slash.bbox)
    cf = _bbox_center(fraction.bbox)
    if cs is None or cf is None:
        return False
    return (
        abs(cs[0] - cf[0]) <= _FRAC_X_OVERLAP_MM
        and abs(cs[1] - cf[1]) <= (_FRAC_Y_SPREAD_MM + 1.0)
        and _bbox_gap(slash.bbox, fraction.bbox) <= 1.0
    )


def _fraction_dedupe_score(item: NormalizedText) -> tuple:
    """Prefer the tighter/smaller fraction footprint when overlays collide."""
    box = item.bbox or (0.0, 0.0, 0.0, 0.0)
    width = max(float(box[2]) - float(box[0]), 0.0)
    height = max(float(box[3]) - float(box[1]), 0.0)
    size = max(float(item.font_size or 0.0), 0.0)
    return (size, width * height, width)


def _dedupe_fraction_overlays(items: List[NormalizedText]) -> List[NormalizedText]:
    """Collapse same-position duplicate fractions left by PDF overlay glyphs."""
    kept: List[NormalizedText] = []
    for item in items:
        replace_at = None
        for idx, existing in enumerate(kept):
            if _fraction_overlay_duplicate(existing, item):
                replace_at = idx
                break
        if replace_at is None:
            kept.append(item)
        elif _fraction_dedupe_score(item) < _fraction_dedupe_score(kept[replace_at]):
            kept[replace_at] = item

    return [
        item
        for item in kept
        if not (
            _SLASH_RE.match((item.text or "").strip())
            and any(
                other is not item and _slash_fraction_overlay_duplicate(item, other)
                for other in kept
            )
        )
    ]


def _merged_bbox(*boxes, scale_width=1.0):
    """Return the union bounding box of one or more (x0,y0,x1,y1) or None boxes.

    Args:
        *boxes: Bounding boxes to merge
        scale_width: Optional width scaling factor (e.g., for stacked fractions)
    """
    vals = [b for b in boxes if b is not None]
    if not vals:
        return None
    x0 = min(b[0] for b in vals)
    y0 = min(b[1] for b in vals)
    x1 = max(b[2] for b in vals)
    y1 = max(b[3] for b in vals)

    # Apply width scaling if requested
    if scale_width != 1.0:
        center_x = (x0 + x1) / 2.0
        width = (x1 - x0) * scale_width
        x0 = center_x - width / 2.0
        x1 = center_x + width / 2.0

    return (x0, y0, x1, y1)


# Precompiled classifier patterns.  ``_classify_generic`` runs once per text
# span (thousands of times on text-heavy sheets); precompiling avoids a regex
# cache lookup on every call.  Patterns and flags are unchanged, so matches are
# identical to the previous inline ``re.search`` calls.
_GEN_DIM_FEET = re.compile(r"\d+['']\s*[-\u2013]?\s*\d")
_GEN_DIM_FRAC = re.compile(r"\d+\s*/\s*\d+")
_GEN_DIM_UNIT = re.compile(r'\d+\.?\d*\s*(?:"|mm|cm|in|ft)', re.I)
_GEN_SCALE_KW = re.compile(r"SCALE[:\s]*\d")
_GEN_SCALE_RATIO = re.compile(r"\d+\s*:\s*\d+")
_GEN_TITLEBLOCK = re.compile(r"\b(DRAWN|CHECKED|DATE|SCALE|REV|SHEET|PROJECT|DWG|TITLE)\b")
_GEN_CALLOUT = re.compile(r"\u00D8|\bDIA\b|\bRAD\b|\bR\d", re.I)
_GEN_DETAIL = re.compile(r"\b(DETAIL|SECTION|SEC|VIEW|ELEVATION)\s+[A-Z]")
_GEN_LABEL = re.compile(r"[A-Z]{2,}")


def _classify_generic(text: str) -> list:
    tags = []
    t = text.strip()
    tu = t.upper()
    if _GEN_DIM_FEET.search(t) or _GEN_DIM_FRAC.search(t):
        tags.append("dimension_like")
    if _GEN_DIM_UNIT.search(t):
        tags.append("dimension_like")
    if _GEN_SCALE_KW.search(tu) or _GEN_SCALE_RATIO.search(t):
        tags.append("scale_like")
    if _GEN_TITLEBLOCK.search(tu):
        tags.append("titleblock_like")
    if _GEN_CALLOUT.search(t):
        tags.append("callout_like")
    if _GEN_DETAIL.search(tu):
        tags.append("detail_reference")
    if len(t) > 1 and len(t) < 60 and _GEN_LABEL.search(tu):
        tags.append("label_like")
    return tags


# ── Coordinate helpers ──


def _matrix_components(matrix) -> Tuple[float, float, float, float, float, float]:
    if matrix is None:
        return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0
    try:
        return tuple(float(getattr(matrix, key)) for key in "abcdef")  # type: ignore[return-value]
    except (AttributeError, TypeError, ValueError):
        try:
            values = tuple(float(value) for value in matrix)
        except (TypeError, ValueError):
            return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0
        if len(values) >= 6:
            return values[:6]  # type: ignore[return-value]
        return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0


def _page_rotation_transform(page_rect, rotation_matrix):
    """Return one crop-local source-to-display affine transform.

    Some PyMuPDF versions expose matrix translation in default user-space
    units even though extracted coordinates and ``page.rect`` already include
    ``/UserUnit``. Preserve the matrix's linear rotation and derive the finite
    crop-local translation from the visible rectangle.
    """

    a, b, c, d, _e, _f = _matrix_components(rotation_matrix)
    width = float(page_rect.width)
    height = float(page_rect.height)
    swaps_axes = abs(b) + abs(c) > abs(a) + abs(d)
    source_width = height if swaps_axes else width
    source_height = width if swaps_axes else height
    linear_corners = (
        (0.0, 0.0),
        (a * source_width, b * source_width),
        (c * source_height, d * source_height),
        (
            a * source_width + c * source_height,
            b * source_width + d * source_height,
        ),
    )
    min_x = min(point[0] for point in linear_corners)
    min_y = min(point[1] for point in linear_corners)
    return (
        a,
        b,
        c,
        d,
        float(getattr(page_rect, "x0", 0.0)) - min_x,
        float(getattr(page_rect, "y0", 0.0)) - min_y,
    )


def _transform_pdf_point(x, y, rotation_matrix) -> Tuple[float, float]:
    a, b, c, d, e, f = _matrix_components(rotation_matrix)
    return a * float(x) + c * float(y) + e, b * float(x) + d * float(y) + f


def _transform_pdf_vector(dx, dy, rotation_matrix) -> Tuple[float, float]:
    a, b, c, d, _e, _f = _matrix_components(rotation_matrix)
    return a * float(dx) + c * float(dy), b * float(dx) + d * float(dy)


def _page_point_to_mm(x, y, rotation_matrix, page_h, flip_y, scale):
    display_x, display_y = _transform_pdf_point(x, y, rotation_matrix)
    if flip_y:
        display_y = float(page_h) - display_y
    factor = MM_PER_PT * float(scale)
    return display_x * factor, display_y * factor


def _to_mm(
    x,
    y,
    page_h,
    flip_y,
    scale,
    *,
    page_w=None,
    rotation=0,
):
    """Map unrotated PyMuPDF page coordinates to model millimetres once."""
    x = float(x)
    y = float(y)
    raw_h = float(page_h)
    raw_w = float(page_w if page_w is not None and page_w > 0 else 0.0)
    rot = int(rotation or 0) % 360
    if rot == 90:
        x, y = raw_h - y, x
        display_h = raw_w
    elif rot == 180:
        x, y = raw_w - x, raw_h - y
        display_h = raw_h
    elif rot == 270:
        x, y = y, raw_w - x
        display_h = raw_w
    else:
        display_h = raw_h
    if flip_y:
        y = display_h - y
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

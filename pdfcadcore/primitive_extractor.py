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
from typing import List, NamedTuple, Optional, Tuple

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


def _composite_alpha(color, alpha):
    """Composite a constant alpha (PDF /CA, /ca) into ``color`` against the white page.

    CAD hosts have no page compositor (LibreCAD has no transparency at all), so the
    only way a 40 % black separator bar or a 50 % grey label can look the way the
    PDF viewer shows it is to deliver the colour the viewer actually paints on white:
    ``a * c + (1 - a) * 1``. ``alpha`` is 0.0-1.0; None / non-finite / >= 1 leave the
    colour untouched (opaque content is bit-identical to before); < 0 clamps to 0.
    """
    if color is None or alpha is None:
        return color
    try:
        a = float(alpha)
    except (TypeError, ValueError):
        return color
    if math.isnan(a) or a >= 1.0:
        return color
    a = max(0.0, a)
    try:
        return tuple(max(0.0, min(1.0, a * float(c) + (1.0 - a))) for c in color)
    except (TypeError, ValueError):
        return color


# PyMuPDF span char_flags bits: 16 = filled, 32 = stroked (text render mode paints).
_SPAN_PAINTED_FLAGS = 16 | 32


def _span_alpha(span) -> Optional[float]:
    """PyMuPDF text spans carry ``alpha`` as an int 0-255 (drawings use 0.0-1.0).

    Invisible text (render mode 3, e.g. the OCR layer of a scanned sheet) is reported
    by PyMuPDF with ``alpha`` 0 and ``char_flags`` lacking both paint bits -- that is
    MuPDF's invisible-text encoding, not a PDF constant alpha, so it must not be
    composited (it would turn the hidden OCR text white). Its colour is left as-is,
    exactly as before.
    """
    if not hasattr(span, "get"):
        return None
    flags = span.get("char_flags")
    if flags is not None:
        try:
            if int(flags) & _SPAN_PAINTED_FLAGS == 0:
                return None
        except (TypeError, ValueError):
            pass
    raw = span.get("alpha")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) or v > 1.0:
        return max(0.0, min(1.0, v / 255.0))
    return max(0.0, min(1.0, v))


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

        stroke = _composite_alpha(
            _norm_color(path_group.get("color") or path_group.get("stroke")),
            path_group.get("stroke_opacity"),
        )
        fill = _composite_alpha(_norm_color(path_group.get("fill")), path_group.get("fill_opacity"))
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

                # Extract text color from span; constant alpha is composited
                # against the white page (see _composite_alpha).
                text_color = _composite_alpha(_norm_color(span.get("color")), _span_alpha(span))

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

# All recognition thresholds are ratios of observed font size.  Fixed model-
# space millimetres are not stable under user scale or PDF transforms.
_FRAC_ROTATION_TOL_DEG = 1.0
_FRAC_CANDIDATE_RADIUS_EM = 5.0
_FRAC_AXIS_EPS_EM = 0.10
_FRAC_INLINE_NORMAL_TOL_EM = 0.75
_FRAC_STACK_ALONG_TOL_EM = 1.75
_FRAC_STACK_NORMAL_MAX_EM = 3.5


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


class _FractionProposal(NamedTuple):
    kind: str
    encoding: str
    semantic_text: str
    slash_indices: Tuple[int, ...]
    numerator_indices: Tuple[int, ...]
    denominator_indices: Tuple[int, ...]
    source_char_layout: Tuple[TextCharLayout, ...]


def _finite_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _finite_point(value) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) == 2
        and all(_finite_number(component) for component in value)
    )


def _finite_quad(value) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) == 4
        and all(_finite_point(point) for point in value)
    )


def _angle_delta(left, right) -> float:
    try:
        return abs((float(left) - float(right) + 180.0) % 360.0 - 180.0)
    except (TypeError, ValueError):
        return math.inf


def _valid_character_layout(char, rotation: float) -> bool:
    if not isinstance(char, TextCharLayout):
        return False
    if not isinstance(char.text, str) or len(char.text) != 1:
        return False
    if char.glyph_id is not None and (
        not isinstance(char.glyph_id, int) or isinstance(char.glyph_id, bool)
    ):
        return False
    if not _finite_point(char.source_origin_pdf) or not _finite_point(char.target_origin):
        return False
    if not _finite_quad(char.source_quad_pdf) or not _finite_quad(char.target_quad):
        return False
    bbox = char.source_bbox_pdf
    if (
        not isinstance(bbox, (tuple, list))
        or len(bbox) != 4
        or not all(_finite_number(value) for value in bbox)
        or float(bbox[2]) < float(bbox[0])
        or float(bbox[3]) < float(bbox[1])
    ):
        return False
    if not _finite_number(char.advance_width) or float(char.advance_width) <= 0.0:
        return False
    if not _finite_number(char.glyph_height) or float(char.glyph_height) <= 0.0:
        return False
    q0, q1 = char.target_quad[0], char.target_quad[1]
    quad_rotation = math.degrees(
        math.atan2(float(q1[1]) - float(q0[1]), float(q1[0]) - float(q0[0]))
    )
    return _angle_delta(quad_rotation, rotation) <= _FRAC_ROTATION_TOL_DEG


def _exact_item_layout(item: NormalizedText) -> Optional[Tuple[TextCharLayout, ...]]:
    layout = item.source_char_layout
    text = str(item.text or "").strip()
    if not isinstance(layout, tuple) or not layout or not text:
        return None
    if len(layout) != len(text) or len({id(char) for char in layout}) != len(layout):
        return None
    if any(not _valid_character_layout(char, item.rotation) for char in layout):
        return None
    if "".join(char.text for char in layout) != text:
        return None
    return layout


def _orientations_compatible(*items: NormalizedText) -> bool:
    if not items:
        return False
    rotation = items[0].rotation
    return all(
        _angle_delta(rotation, item.rotation) <= _FRAC_ROTATION_TOL_DEG
        for item in items[1:]
    )


def _font_scale(*items: NormalizedText) -> Optional[float]:
    values = []
    for item in items:
        if not _finite_number(item.font_size) or float(item.font_size) <= 0.0:
            return None
        values.append(float(item.font_size))
    values.sort()
    return values[len(values) // 2] if values else None


def _sizes_compatible(*items: NormalizedText) -> bool:
    values = [float(item.font_size) for item in items if _finite_number(item.font_size)]
    return (
        len(values) == len(items)
        and min(values) > 0.0
        and max(values) <= 2.0 * min(values)
    )


def _layout_centroid(layout: Tuple[TextCharLayout, ...]) -> Tuple[float, float]:
    count = float(len(layout))
    return (
        sum(float(char.target_origin[0]) for char in layout) / count,
        sum(float(char.target_origin[1]) for char in layout) / count,
    )


def _local_offset(
    point: Tuple[float, float],
    anchor: Tuple[float, float],
    rotation: float,
    scale: float,
) -> Tuple[float, float]:
    angle = math.radians(float(rotation))
    dx = float(point[0]) - float(anchor[0])
    dy = float(point[1]) - float(anchor[1])
    along = (dx * math.cos(angle) + dy * math.sin(angle)) / scale
    normal = (-dx * math.sin(angle) + dy * math.cos(angle)) / scale
    return along, normal


def _candidate_near_slash(
    item: NormalizedText,
    layout: Optional[Tuple[TextCharLayout, ...]],
    slash: NormalizedText,
    slash_layout: Tuple[TextCharLayout, ...],
) -> bool:
    scale = _font_scale(item, slash)
    if scale is None:
        return False
    point = _layout_centroid(layout) if layout else tuple(item.insertion)
    anchor = _layout_centroid(slash_layout)
    along, normal = _local_offset(point, anchor, slash.rotation, scale)
    return (
        abs(along) <= _FRAC_CANDIDATE_RADIUS_EM
        and abs(normal) <= _FRAC_CANDIDATE_RADIUS_EM
    )


def _fraction_encoding(
    numerator_layout: Tuple[TextCharLayout, ...],
    slash_layout: Tuple[TextCharLayout, ...],
    denominator_layout: Tuple[TextCharLayout, ...],
    numerator: NormalizedText,
    slash: NormalizedText,
    denominator: NormalizedText,
) -> Optional[str]:
    if not _orientations_compatible(numerator, slash, denominator):
        return None
    scale = _font_scale(numerator, slash, denominator)
    if scale is None:
        return None
    anchor = _layout_centroid(slash_layout)
    numer_along, numer_normal = _local_offset(
        _layout_centroid(numerator_layout), anchor, slash.rotation, scale
    )
    denom_along, denom_normal = _local_offset(
        _layout_centroid(denominator_layout), anchor, slash.rotation, scale
    )
    vertical = (
        numer_normal >= _FRAC_AXIS_EPS_EM
        and denom_normal <= -_FRAC_AXIS_EPS_EM
        and max(abs(numer_normal), abs(denom_normal)) <= _FRAC_STACK_NORMAL_MAX_EM
        and max(abs(numer_along), abs(denom_along)) <= _FRAC_STACK_ALONG_TOL_EM
    )
    horizontal = (
        numer_along <= -_FRAC_AXIS_EPS_EM
        and denom_along >= _FRAC_AXIS_EPS_EM
        and max(abs(numer_along), abs(denom_along)) <= _FRAC_CANDIDATE_RADIUS_EM
        and max(abs(numer_normal), abs(denom_normal)) <= _FRAC_INLINE_NORMAL_TOL_EM
    )
    if vertical == horizontal:
        return None
    return "vertical" if vertical else "horizontal"


def _semantic_fraction_layout(
    numerator_layout: Tuple[TextCharLayout, ...],
    slash_layout: Tuple[TextCharLayout, ...],
    denominator_layout: Tuple[TextCharLayout, ...],
    semantic_text: str,
) -> Optional[Tuple[TextCharLayout, ...]]:
    layout = numerator_layout + slash_layout + denominator_layout
    if len(layout) != len(semantic_text):
        return None
    if len({id(char) for char in layout}) != len(layout):
        return None
    if "".join(char.text for char in layout) != semantic_text:
        return None
    if semantic_text.count("/") != 1 or sum(char.text == "/" for char in layout) != 1:
        return None
    return layout


def _safe_equal(left, right) -> bool:
    if left is right:
        return True
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _rendering_bindings_compatible(*items: NormalizedText) -> bool:
    """Require one exact item-level rendering binding for a merged value."""
    if not items:
        return False
    reference = items[0]
    attributes = ("font_name", "font_asset", "font_failure", "color")
    return all(
        _safe_equal(getattr(reference, name), getattr(item, name))
        for item in items[1:]
        for name in attributes
    )


def _observed_overlay_equivalent(left: NormalizedText, right: NormalizedText) -> bool:
    if _angle_delta(left.rotation, right.rotation) > 1e-9:
        return False
    attributes = (
        "text",
        "normalized",
        "insertion",
        "bbox",
        "font_size",
        "font_name",
        "color",
        "page_number",
        "generic_tags",
        "domain_tags",
        "source_bbox_pdf",
        "source_quad_pdf",
        "target_quad_model",
        "advance_width",
        "glyph_height",
        "baseline_descent",
        "source_char_layout",
        "requires_individual_positioning",
        "positioned_character",
        "source_glyph_id",
        "font_asset",
        "font_failure",
    )
    return all(
        _safe_equal(getattr(left, name), getattr(right, name))
        for name in attributes
    )


def _proposal_consumed(proposal: _FractionProposal) -> set[int]:
    return set(
        proposal.slash_indices
        + proposal.numerator_indices
        + proposal.denominator_indices
    )


def _proposal_equivalent(
    left: _FractionProposal,
    right: _FractionProposal,
    items: List[NormalizedText],
) -> bool:
    if (
        left.kind != right.kind
        or left.encoding != right.encoding
        or left.semantic_text != right.semantic_text
    ):
        return False
    role_pairs = (
        (left.slash_indices, right.slash_indices),
        (left.numerator_indices, right.numerator_indices),
        (left.denominator_indices, right.denominator_indices),
    )
    for left_indices, right_indices in role_pairs:
        if bool(left_indices) != bool(right_indices):
            return False
        if left_indices and not _observed_overlay_equivalent(
            items[left_indices[0]], items[right_indices[0]]
        ):
            return False
    return True


def _combine_equivalent_proposals(
    left: _FractionProposal,
    right: _FractionProposal,
) -> _FractionProposal:
    return left._replace(
        slash_indices=tuple(sorted(set(left.slash_indices + right.slash_indices))),
        numerator_indices=tuple(
            sorted(set(left.numerator_indices + right.numerator_indices))
        ),
        denominator_indices=tuple(
            sorted(set(left.denominator_indices + right.denominator_indices))
        ),
    )


def _insertion_near_slash(item: NormalizedText, slash: NormalizedText) -> bool:
    scale = _font_scale(item, slash)
    if scale is None or not _finite_point(item.insertion) or not _finite_point(slash.insertion):
        return False
    along, normal = _local_offset(
        tuple(item.insertion), tuple(slash.insertion), slash.rotation, scale
    )
    return (
        abs(along) <= _FRAC_CANDIDATE_RADIUS_EM
        and abs(normal) <= _FRAC_CANDIDATE_RADIUS_EM
    )


def _proposal_for_slash(
    items: List[NormalizedText],
    indices: List[int],
    slash_index: int,
) -> Tuple[Optional[_FractionProposal], set[int]]:
    slash = items[slash_index]
    slash_layout = _exact_item_layout(slash)
    if slash_layout is None or str(slash.text or "").strip() != "/":
        blocked = {slash_index}
        blocked.update(
            index
            for index in indices
            if index != slash_index
            and str(items[index].text or "").strip().isdigit()
            and _orientations_compatible(items[index], slash)
            and _insertion_near_slash(items[index], slash)
        )
        return None, blocked

    candidates: List[Tuple[int, Tuple[TextCharLayout, ...]]] = []
    invalid_candidates: set[int] = set()
    for index in indices:
        if index == slash_index:
            continue
        item = items[index]
        text = str(item.text or "").strip()
        if not _DIGITS_RE.match(text) or not _orientations_compatible(item, slash):
            continue
        layout = _exact_item_layout(item)
        near = _candidate_near_slash(item, layout, slash, slash_layout)
        if not near:
            continue
        if layout is None:
            invalid_candidates.add(index)
        else:
            candidates.append((index, layout))

    if invalid_candidates:
        return None, invalid_candidates | {slash_index}

    concatenated: List[_FractionProposal] = []
    for index, layout in candidates:
        item = items[index]
        split = _split_concatenated_fraction(item.text)
        if split is None or not _sizes_compatible(item, slash):
            continue
        numerator_text, denominator_text = split
        split_at = len(numerator_text)
        numerator_layout = layout[:split_at]
        denominator_layout = layout[split_at:]
        semantic_text = f"{numerator_text}/{denominator_text}"
        semantic_layout = _semantic_fraction_layout(
            numerator_layout,
            slash_layout,
            denominator_layout,
            semantic_text,
        )
        encoding = _fraction_encoding(
            numerator_layout,
            slash_layout,
            denominator_layout,
            item,
            slash,
            item,
        )
        if semantic_layout is None:
            return None, {index, slash_index}
        if encoding is None:
            continue
        if not _rendering_bindings_compatible(item, slash):
            return None, {index, slash_index}
        concatenated.append(
            _FractionProposal(
                kind="concatenated",
                encoding=encoding,
                semantic_text=semantic_text,
                slash_indices=(slash_index,),
                numerator_indices=(index,),
                denominator_indices=(),
                source_char_layout=semantic_layout,
            )
        )

    separate_candidates = [
        (index, layout)
        for index, layout in candidates
        if _split_concatenated_fraction(items[index].text) is None
    ]
    separate: List[_FractionProposal] = []
    for left_offset, (left_index, left_layout) in enumerate(separate_candidates):
        for right_index, right_layout in separate_candidates[left_offset + 1:]:
            left_item = items[left_index]
            right_item = items[right_index]
            try:
                left_value = int(left_item.text.strip())
                right_value = int(right_item.text.strip())
            except ValueError:
                continue
            if left_value < right_value:
                numerator_index, numerator_layout = left_index, left_layout
                denominator_index, denominator_layout = right_index, right_layout
            elif right_value < left_value:
                numerator_index, numerator_layout = right_index, right_layout
                denominator_index, denominator_layout = left_index, left_layout
            else:
                continue
            numerator = items[numerator_index]
            denominator = items[denominator_index]
            denominator_value = int(denominator.text.strip())
            numerator_value = int(numerator.text.strip())
            if denominator_value not in _VALID_DENOMS or not 0 < numerator_value < denominator_value:
                continue
            if not _sizes_compatible(numerator, slash, denominator):
                continue
            semantic_text = f"{numerator.text.strip()}/{denominator.text.strip()}"
            semantic_layout = _semantic_fraction_layout(
                numerator_layout,
                slash_layout,
                denominator_layout,
                semantic_text,
            )
            encoding = _fraction_encoding(
                numerator_layout,
                slash_layout,
                denominator_layout,
                numerator,
                slash,
                denominator,
            )
            if semantic_layout is None:
                return None, {numerator_index, slash_index, denominator_index}
            if encoding is None:
                continue
            if not _rendering_bindings_compatible(numerator, slash, denominator):
                return None, {numerator_index, slash_index, denominator_index}
            separate.append(
                _FractionProposal(
                    kind="separate",
                    encoding=encoding,
                    semantic_text=semantic_text,
                    slash_indices=(slash_index,),
                    numerator_indices=(numerator_index,),
                    denominator_indices=(denominator_index,),
                    source_char_layout=semantic_layout,
                )
            )

    if concatenated and separate:
        blocked = {slash_index}
        for proposal in concatenated + separate:
            blocked.update(_proposal_consumed(proposal))
        return None, blocked
    raw = concatenated or separate
    if not raw:
        return None, set()
    collapsed = raw[0]
    for proposal in raw[1:]:
        if not _proposal_equivalent(collapsed, proposal, items):
            blocked = {slash_index}
            for value in raw:
                blocked.update(_proposal_consumed(value))
            return None, blocked
        collapsed = _combine_equivalent_proposals(collapsed, proposal)
    return collapsed, set()


def _proposal_parts(
    proposal: _FractionProposal,
    items: List[NormalizedText],
) -> Tuple[NormalizedText, ...]:
    numerator = items[proposal.numerator_indices[0]]
    slash = items[proposal.slash_indices[0]]
    if proposal.kind == "concatenated":
        return numerator, slash
    return numerator, slash, items[proposal.denominator_indices[0]]


def _build_fraction_item(
    proposal: _FractionProposal,
    items: List[NormalizedText],
) -> NormalizedText:
    parts = _proposal_parts(proposal, items)
    anchor = items[proposal.slash_indices[0]]
    primary = items[proposal.numerator_indices[0]]
    font_asset = anchor.font_asset if anchor.font_asset is not None else primary.font_asset
    font_failure = (
        anchor.font_failure if anchor.font_failure is not None else primary.font_failure
    )
    return NormalizedText(
        id=next_id(),
        text=proposal.semantic_text,
        normalized=proposal.semantic_text.upper().strip(),
        insertion=anchor.insertion,
        bbox=_merged_bbox(*[part.bbox for part in parts]),
        font_size=anchor.font_size,
        rotation=anchor.rotation,
        font_name=anchor.font_name or primary.font_name,
        color=anchor.color if anchor.color is not None else primary.color,
        page_number=anchor.page_number,
        generic_tags=_classify_generic(proposal.semantic_text),
        source_bbox_pdf=_merged_bbox(*[part.source_bbox_pdf for part in parts]),
        source_quad_pdf=None,
        target_quad_model=None,
        advance_width=0.0,
        glyph_height=0.0,
        baseline_descent=anchor.baseline_descent,
        source_char_layout=proposal.source_char_layout,
        requires_individual_positioning=True,
        font_asset=font_asset,
        font_failure=font_failure,
    )


def _merge_stacked_fractions(items: List[NormalizedText]) -> List[NormalizedText]:
    """Merge only fractions with complete, unambiguous source placement truth.

    Recognition is performed in the slash's font-relative baseline/normal
    frame.  A replacement is published only when every semantic character has
    exactly one observed character layout and every competing candidate is
    either absent or a proven equivalent overlay.
    """
    if len(items) < 2:
        return items

    by_page: dict[int, list[int]] = {}
    for index, item in enumerate(items):
        by_page.setdefault(item.page_number, []).append(index)

    merged_indices: set[int] = set()
    replacements: dict[int, NormalizedText] = {}

    for indices in by_page.values():
        slash_indices = [
            index
            for index in indices
            if _SLASH_RE.match(str(items[index].text or "").strip())
        ]
        proposals: List[_FractionProposal] = []
        blocked_indices: set[int] = set()
        for slash_index in slash_indices:
            proposal, blocked = _proposal_for_slash(items, indices, slash_index)
            blocked_indices.update(blocked)
            if proposal is not None:
                proposals.append(proposal)

        proposals = [
            proposal
            for proposal in proposals
            if not (_proposal_consumed(proposal) & blocked_indices)
        ]

        # Equivalent overlays may yield duplicate proposals.  Collapse them
        # only after every observed field (including char layout/glyph ids)
        # proves equality apart from the source item id.
        changed = True
        while changed:
            changed = False
            for left_index in range(len(proposals)):
                for right_index in range(left_index + 1, len(proposals)):
                    left = proposals[left_index]
                    right = proposals[right_index]
                    if not (_proposal_consumed(left) & _proposal_consumed(right)):
                        continue
                    if not _proposal_equivalent(left, right, items):
                        continue
                    proposals[left_index] = _combine_equivalent_proposals(left, right)
                    proposals.pop(right_index)
                    changed = True
                    break
                if changed:
                    break

        conflicted: set[int] = set()
        for left_index in range(len(proposals)):
            for right_index in range(left_index + 1, len(proposals)):
                if _proposal_consumed(proposals[left_index]) & _proposal_consumed(
                    proposals[right_index]
                ):
                    conflicted.update((left_index, right_index))

        for proposal_index, proposal in enumerate(proposals):
            if proposal_index in conflicted:
                continue
            consumed = _proposal_consumed(proposal)
            if consumed & merged_indices:
                continue
            replacement_index = proposal.slash_indices[0]
            replacements[replacement_index] = _build_fraction_item(proposal, items)
            merged_indices.update(consumed)

    if not merged_indices:
        return items

    result: List[NormalizedText] = []
    for index, item in enumerate(items):
        if index not in merged_indices:
            result.append(item)
        elif index in replacements:
            result.append(replacements[index])
    return result


def _merged_bbox(*boxes):
    """Return the exact union of observed bounding boxes, or None."""
    values = [box for box in boxes if box is not None]
    if not values:
        return None
    return (
        min(box[0] for box in values),
        min(box[1] for box in values),
        max(box[2] for box in values),
        max(box[3] for box in values),
    )


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

"""Bounded renderer evidence for final unclipped rectangular PDF paints."""
from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_RECT = re.compile(r"\s*M\s*(" + _NUMBER + r")[ ,]+(" + _NUMBER + r")\s*H\s*(" + _NUMBER
                   + r")\s*V\s*(" + _NUMBER + r")\s*H\s*(" + _NUMBER + r")\s*Z\s*")


def _rgb(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return None
    return tuple(int(value[i:i+2], 16) / 255 for i in (1, 3, 5))


def _close(a, b, tolerance):
    return len(a) == len(b) and all(math.isfinite(x) and math.isfinite(y)
                                  and abs(x-y) <= tolerance for x, y in zip(a, b, strict=True))


def rect_pair_matches(fill, stroke, raw):
    """Verify a renderer pair against raw paint without assuming PDF defaults."""
    try:
        if any(key in node.attrib for node in (fill, stroke) for key in ("clip-path", "mask", "filter", "opacity")):
            return False
        if fill.tag.rsplit("}", 1)[-1] != "path" or stroke.tag.rsplit("}", 1)[-1] != "path":
            return False
        if fill.get("d") != stroke.get("d") or fill.get("transform") != stroke.get("transform"):
            return False
        match = _RECT.fullmatch(fill.get("d", ""))
        if match is None:
            return False
        x0, y0, x1, y1, final_x = map(float, match.groups())
        if x0 != final_x or x0 == x1 or y0 == y1:
            return False
        transform = fill.get("transform", "")
        if not transform.startswith("matrix(") or not transform.endswith(")"):
            return False
        a, b, c, d, e, f = [float(v) for v in re.split(r"[ ,]+", transform[7:-1].strip())]
        if not all(math.isfinite(v) for v in (a, b, c, d, e, f)):
            return False
        scale2, second = a*a+b*b, c*c+d*d
        if scale2 <= 0 or abs(scale2-second) > scale2*1e-8 or abs(a*c+b*d) > scale2*1e-8:
            return False
        corners = [(a*x+c*y+e, b*x+d*y+f) for x, y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
        xs, ys = zip(*corners, strict=True)
        bounds = (min(xs), min(ys), max(xs), max(ys))
        if not _close(bounds, tuple(raw["rect"]), .001):
            return False
        miter = float(stroke.get("stroke-miterlimit", "nan"))
        if stroke.get("stroke-linejoin") != "miter" or not math.isfinite(miter) or miter < math.sqrt(2):
            return False
        if stroke.get("stroke-dasharray") or stroke.get("fill") != "none":
            return False
        if not _close((float(stroke.get("stroke-width", "nan"))*math.sqrt(scale2),), (float(raw["width"]),), .0001):
            return False
        if not _close((float(fill.get("fill-opacity", "1")),), (float(raw["fill_opacity"]),), 1e-5):
            return False
        if float(stroke.get("stroke-opacity", "1")) != 1:
            return False
        fill_rgb, stroke_rgb = _rgb(fill.get("fill")), _rgb(stroke.get("stroke"))
        return (fill_rgb is not None and stroke_rgb is not None
                and _close(fill_rgb, tuple(raw["fill"]), 1/255 + 1e-6)
                and _close(stroke_rgb, tuple(raw["color"]), 1/255 + 1e-6))
    except (TypeError, ValueError, KeyError, OverflowError):
        return False


def final_svg_rectangles(svg, rows):
    """Require direct-root final path pairs: no inherited clipping or groups."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return False
    if any(key in root.attrib for key in ("clip-path", "mask", "filter", "opacity", "transform")):
        return False
    count = len(rows)
    children = list(root)
    if not count or len(children) < 2*count:
        return False
    tail = children[-2*count:]
    return all(rect_pair_matches(tail[2*i], tail[2*i+1], row) for i, row in enumerate(rows))


def _box(points):
    points = list(points)
    if len(points) == 5 and points[0] == points[-1]:
        points.pop()
    if len(points) != 4 or len(set(points)) != 4:
        return None
    if not all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in points):
        return None
    xs, ys = zip(*points, strict=True)
    box = min(xs), min(ys), max(xs), max(ys)
    if set(points) != {(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])}:
        return None
    if not all((a[0] == b[0]) != (a[1] == b[1]) for a, b in zip(points, points[1:] + points[:1], strict=True)):
        return None
    return box


def _object_tokens(source):
    """Read COS names/references, ignoring comments and literal/hex strings.

    This is deliberately not a content-stream parser. MuPDF supplies decoded
    object dictionaries; stream bytes are never interpreted as resource keys.
    """
    tokens = []
    i = 0
    delimiters = "()<>[]{}/%\x00\t\n\f\r "
    while i < len(source):
        c = source[i]
        if c.isspace() or c == '\x00':
            i += 1
        elif c == '%':
            while i < len(source) and source[i] not in '\r\n':
                i += 1
        elif c == '(':
            depth = 1
            i += 1
            while depth and i < len(source):
                if source[i] == '\\':
                    i += 2
                    continue
                depth += (source[i] == '(') - (source[i] == ')')
                i += 1
            if depth:
                raise ValueError('Unterminated PDF literal')
            tokens.append('STRING')
        elif c == '<' and not source.startswith('<<', i):
            end = source.find('>', i + 1)
            if end < 0:
                raise ValueError('Unterminated PDF hex string')
            i = end + 1
            tokens.append('STRING')
        elif c == '/':
            end = i + 1
            while end < len(source) and source[end] not in delimiters:
                end += 1
            name = source[i + 1:end]
            if re.search(r'#(?![0-9a-fA-F]{2})', name):
                raise ValueError('Invalid escaped PDF name')
            name = re.sub(r'#([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), name)
            tokens.append('/' + name)
            i = end
        elif c in '<>':
            tokens.append(source[i:i + 2] if source[i:i + 2] in ('<<', '>>') else c)
            i += len(tokens[-1])
        elif c in '[]{}':
            tokens.append(c)
            i += 1
        elif c == ')':
            raise ValueError('Unexpected PDF literal end')
        else:
            end = i + 1
            while end < len(source) and source[end] not in delimiters:
                end += 1
            tokens.append(source[i:end])
            i = end
    return tokens


def _normal_blend_proof(page):
    """Conservatively qualify the reachable catalog, including Form resources.

    Any group or soft-mask declaration is excluded, even on another page.
    Only absent/default Normal or an explicit scalar /Normal is supported.
    Missing object evidence rejects the optimization instead of guessing.
    """
    try:
        doc = page.parent
        pending = [doc.pdf_catalog(), page.xref]
        seen = set()
        digest = hashlib.sha256()
        while pending:
            xref = pending.pop()
            if xref in seen:
                continue
            if not 0 < xref < doc.xref_length():
                return None
            seen.add(xref)
            source = doc.xref_object(xref, compressed=False)
            if not source or source.strip() == 'null':
                return None
            tokens = _object_tokens(source)
            for i, token in enumerate(tokens):
                if token in ('/Group', '/SMask'):
                    return None
                if token == '/BM' and tokens[i + 1:i + 2] != ['/Normal']:
                    return None
                if token in ('/TR', '/TR2') and tokens[i + 1:i + 2] not in (['/Identity'], ['/Default']):
                    return None
                if i >= 2 and token == 'R':
                    if not tokens[i-2].isdigit() or not tokens[i-1].isdigit():
                        return None
                    pending.append(int(tokens[i-2]))
            digest.update(str(xref).encode('ascii') + b':' + source.encode('utf8') + b'\n')
        return dict(scope='reachable catalog and selected page objects',
                    object_count=len(seen), object_dictionary_sha256=digest.hexdigest(),
                    blend_mode='Normal', groups='absent', soft_masks='absent',
                    source='original PDF object dictionaries, not SVG inference')
    except (AttributeError, IndexError, RuntimeError, TypeError, ValueError, OverflowError):
        return None


def bind_final_rect_paints(page, page_data):
    """Bind only source-proven final translucent rectangles to model primitives.

    Output describes the whole original fill rectangle. The consumer retains
    its original opaque centered stroke and owns native paint ordering.
    Unqualified sources return no records; this is not generic PDF compositing.
    """
    by_order = {}
    for primitive in page_data.primitives:
        order = primitive.source_draw_order
        if type(order) is int:
            by_order.setdefault(order, []).append(primitive)
    candidates = {}
    for raw in getattr(page_data, '_source_drawings', ()):
        order = raw.get('seqno')
        if type(order) is not int or len(by_order.get(order, ())) != 1:
            continue
        primitive = by_order[order][0]
        items = raw.get('items') or ()
        if (raw.get('level') != 0 or raw.get('type') != 'fs'
                or len(items) != 1 or items[0][0] != 're'
                or primitive.type not in {'rect', 'closed_loop'}
                or primitive.clip_fill_group_id
                or not 0.0 < primitive.fill_opacity < 1.0
                or primitive.stroke_opacity != 1.0
                or primitive.source_fill_color is None
                or primitive.source_stroke_color is None
                or primitive.dash_pattern or raw.get('lineJoin') != 0
                or not primitive.line_width or primitive.line_width <= 0):
            continue
        try:
            raw_matches = (
                _close(tuple(raw['fill']), tuple(primitive.source_fill_color), 1e-7)
                and _close(tuple(raw['color']), tuple(primitive.source_stroke_color), 1e-7)
                and _close((float(raw['fill_opacity']),), (primitive.fill_opacity,), 1e-7)
                and _close((float(raw['stroke_opacity']),), (primitive.stroke_opacity,), 1e-7)
                and math.isfinite(float(raw['width'])) and float(raw['width']) > 0
                and math.isfinite(primitive.line_width))
        except (TypeError, ValueError, KeyError, OverflowError):
            raw_matches = False
        if not raw_matches:
            continue
        bounds = _box(primitive.points)
        if bounds is not None and primitive.line_width < min(bounds[2]-bounds[0], bounds[3]-bounds[1]):
            candidates[order] = (primitive, bounds, raw)
    if not candidates:
        return []
    log = page.get_bboxlog()
    end = len(log)
    suffix = []
    while end >= 2 and end - 2 in candidates:
        order = end - 2
        if log[order][0] != 'fill-path' or log[order + 1][0] != 'stroke-path':
            break
        suffix.append(candidates[order])
        end -= 2
    suffix.reverse()
    if not suffix:
        return []
    normal = _normal_blend_proof(page)
    if normal is None:
        return []
    svg = page.get_svg_image(text_as_path=True)
    if not final_svg_rectangles(svg, [raw for _, _, raw in suffix]):
        return []
    proof = dict(schema='bcs.final-normal-rectangle-paint/1',
                 normal_blend=normal, svg_sha256=hashlib.sha256(svg.encode('utf8')).hexdigest(),
                 complete_final_paint_suffix=[raw['seqno'] for _, _, raw in suffix],
                 bboxlog_paint_count=len(log), source_clipping='direct-root SVG pairs and level0 raw paints',
                 stroke='opaque centered solid miter, explicit source miter limit >=sqrt(2)')
    return [dict(primitive_id=primitive.id, seqno=raw['seqno'],
                 source_bbox_pdf=list(raw['rect']), model_bounds=list(bounds),
                 fill_rgb=list(primitive.source_fill_color), fill_opacity=primitive.fill_opacity,
                 stroke_rgb=list(primitive.source_stroke_color), stroke_width_pdf=raw['width'],
                 stroke_width_model=primitive.line_width, proof=proof)
            for primitive, bounds, raw in suffix]


"""Source-proven dash intervals for literal straight PDF strokes only."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import xml.etree.ElementTree as ET

from pdfcadcore.primitive_extractor import _page_rotation_transform, _transform_pdf_point

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(_NUMBER + r"|[a-zA-Z]")
_SVG_TOL_PT = 0.0002  # MuPDF SVG decimal serialization, not geometry snapping.
_MAX_DASHES = 4096


@dataclass(frozen=True)
class SourceLineDashes:
    source_seqno: int
    source_start_pdf: tuple[float, float]
    source_end_pdf: tuple[float, float]
    pattern_pdf: tuple[float, ...]
    phase_pdf: float
    visible_source_interval: tuple[float, float]
    segments_model: tuple[tuple[tuple[float, float], tuple[float, float]], ...]
    line_cap: int
    dots_model: tuple[tuple[float, float], ...] = ()
    dot_radius_model: float = 0.0


def _numbers(text):
    residue = re.sub(_NUMBER, "", text)
    if residue.strip(" ,\t\r\n"):
        raise ValueError("unsupported SVG numeric syntax")
    result = tuple(float(value) for value in re.findall(_NUMBER, text))
    if not all(math.isfinite(value) for value in result):
        raise ValueError("non-finite source dash numbers")
    return result


def _literal_line(path):
    tokens = _TOKEN.findall(path)
    if re.sub(_TOKEN, "", path).strip(" ,\t\r\n"):
        return None
    if len(tokens) not in {5, 6} or tokens[0] not in {"M", "m"}:
        return None
    try:
        x, y = float(tokens[1]), float(tokens[2])
        command = tokens[3]
        if len(tokens) == 5 and command in {"H", "h"}:
            end = (float(tokens[4]) + (x if command == "h" else 0), y)
        elif len(tokens) == 5 and command in {"V", "v"}:
            end = (x, float(tokens[4]) + (y if command == "v" else 0))
        elif len(tokens) == 6 and command in {"L", "l"}:
            end = (float(tokens[4]) + (x if command == "l" else 0),
                   float(tokens[5]) + (y if command == "l" else 0))
        else:
            return None
        return (x, y), end
    except ValueError:
        return None


def _point(point, matrix):
    x, y = point
    a, b, c, d, e, f = matrix
    return x*a+y*c+e, x*b+y*d+f


def _near(a, b, tolerance=_SVG_TOL_PT):
    return math.dist(a, b) <= tolerance


def _renderer_lines(page):
    root = ET.fromstring(page.get_svg_image(text_as_path=False))
    rotation = _page_rotation_transform(page.rect, page.rotation_matrix)
    a, b, c, d, e, f = rotation
    determinant = a*d-b*c
    derotation = (d/determinant, -b/determinant, -c/determinant, a/determinant,
                  (c*f-d*e)/determinant, (b*e-a*f)/determinant)
    rows = []

    def visit(node, unsupported_ancestor=False):
        # MuPDF applies the paint CTM on each path. Never ignore a transformed
        # ancestor if a future renderer changes that contract.
        blocked = unsupported_ancestor
        if node.tag.rsplit("}", 1)[-1] != "path":
            blocked = blocked or bool(node.get("transform"))
        attrs = node.attrib
        if (not blocked and node.tag.rsplit("}", 1)[-1] == "path"
                and "stroke-dasharray" in attrs and attrs.get("fill") == "none"):
            line = _literal_line(attrs.get("d", ""))
            matrix_match = re.fullmatch(r"matrix\((.*)\)", attrs.get("transform", ""))
            if line and matrix_match:
                try:
                    matrix = _numbers(matrix_match.group(1))
                    if len(matrix) != 6:
                        raise ValueError("invalid paint CTM")
                    determinant = matrix[0]*matrix[3]-matrix[1]*matrix[2]
                    expansion = math.sqrt(abs(determinant))
                    start, end = (_point(_point(point, matrix), derotation) for point in line)
                    local_length = math.dist(*line)
                    length = math.dist(start, end)
                    pattern = _numbers(attrs["stroke-dasharray"])
                    phase = float(attrs.get("stroke-dashoffset", "0"))
                    width = float(attrs.get("stroke-width", "1"))
                    color = attrs.get("stroke", "")
                    cap = {"butt": 0, "round": 1, "square": 2}.get(attrs.get("stroke-linecap", "butt"))
                    if (expansion <= 0 or local_length <= 0 or length <= 0
                            or not pattern or any(value < 0 for value in pattern) or not any(pattern)
                            or not math.isfinite(phase) or not math.isfinite(width)
                            or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or cap is None):
                        raise ValueError("unsupported straight stroke paint")
                    rgb = tuple(int(color[i:i+2], 16)/255 for i in (1, 3, 5))
                    rows.append({"start": start, "end": end, "pattern": pattern,
                                 "phase": phase, "expansion": expansion,
                                 "along_scale": length/local_length, "width": width,
                                 "color": rgb, "cap": cap,
                                 "similarity": math.isclose(math.hypot(matrix[0], matrix[1]),
                                                            math.hypot(matrix[2], matrix[3]), rel_tol=1e-9, abs_tol=0)
                                 and abs(matrix[0]*matrix[2]+matrix[1]*matrix[3]) <= 1e-9*abs(determinant)})
                except (ValueError, TypeError, ZeroDivisionError):
                    pass  # Not certified; existing native linetype remains.
        for child in node:
            visit(child, blocked)
    visit(root)
    return rows


def dash_intervals(length, pattern, phase, visible=(0.0, 1.0), limit=_MAX_DASHES):
    """Exact positive-length dash/gap walk, including odd-array repetition."""
    values = tuple(float(value) for value in pattern)
    if (not values or any(not math.isfinite(v) or v <= 0 for v in values)
            or not math.isfinite(length) or length <= 0 or not math.isfinite(phase)):
        raise ValueError("source dash pattern requires finite positive lengths")
    if len(values) % 2:
        values += values
    total = sum(values)
    position = -(phase % total)
    index = 0
    intervals = []
    # Start near the visible region, preserving the original phase exactly.
    lower, upper = visible[0]*length, visible[1]*length
    if not (0 <= lower <= upper <= length):
        raise ValueError("invalid visible source line interval")
    if lower == upper:
        return ()
    if lower > position:
        position += math.floor((lower-position)/total)*total
    steps = 0
    while position < upper:
        end = position + values[index]
        if index % 2 == 0 and end > lower:
            intervals.append((max(position, lower), min(end, upper)))
            if len(intervals) > limit:
                raise ValueError("source straight dash segment budget exceeded")
        position = end
        index = (index+1) % len(values)
        steps += 1
        if steps > limit*len(values)*2:
            raise ValueError("source straight dash iteration budget exceeded")
    return tuple(intervals)


def round_dot_dash_intervals(length, pattern, phase, limit=_MAX_DASHES):
    """Literal round-cap painted dots; zero gaps/empty patterns stay unsupported.

    A zero painted length has circular ink under a round cap. It must never be
    discarded, enlarged to a short LINE, or confused with a zero-length gap.
    This deliberately requires an unclipped complete source segment.
    """
    values = tuple(float(value) for value in pattern)
    if len(values) % 2:
        values += values
    if (not values or not all(math.isfinite(v) and v >= 0 for v in values)
            or any(v <= 0 for v in values[1::2]) or not any(v == 0 for v in values[::2])
            or not math.isfinite(length) or length <= 0 or not math.isfinite(phase)):
        raise ValueError("unsupported round-dot dash pattern")
    position, index, steps = -(phase % sum(values)), 0, 0
    segments, dots = [], []
    while position <= length:
        end = position + values[index]
        if index % 2 == 0:
            if values[index] == 0 and 0 <= position <= length:
                dots.append(position)
            elif end > 0 and position < length:
                segments.append((max(0., position), min(length, end)))
        position = end
        index = (index + 1) % len(values)
        steps += 1
        if len(segments) + len(dots) > limit or steps > limit*len(values)*2:
            raise ValueError("source round-dot dash budget exceeded")
    return tuple(segments), tuple(dots)


def _unclipped_round_dot_strokes(page, page_bounds):
    """Full round ink must fit actual rectangular clips; no blend approximation."""
    from .nontext_composite import _source_group_declarations
    try:
        _source_group_declarations(page)
    except (ValueError, RuntimeError):
        return {}  # Flattened group flags alone do not prove knockout absence.
    clips, groups, result, seen = [], [], {}, set()
    for row in page.get_drawings(extended=True):
        level = row.get('level', 0)
        clips = [entry for entry in clips if entry.get('level', 0) < level]
        groups = [entry for entry in groups if entry.get('level', 0) < level]
        if row.get('type') == 'clip':
            clips.append(row)
            continue
        if row.get('type') == 'group':
            groups.append(row)
            continue
        seq = row.get('seqno')
        if type(seq) is not int:
            continue
        if seq in seen:
            result.pop(seq, None)
            continue
        seen.add(seq)
        items = row.get('items') or ()
        if (row.get('type') != 's' or row.get('fill') is not None or row.get('stroke_opacity') != 1
                or len(items) != 1 or items[0][0] != 'l' or row.get('closePath')
                or set(row.get('lineCap', ())) != {1}
                or any(group.get('opacity', 1) != 1 or group.get('blendmode', 'Normal') != 'Normal'
                       or group.get('knockout', False) for group in groups)):
            continue
        radius = float(row.get('width', 0))/2
        start, end = items[0][1:]
        bounds = (min(start[0], end[0])-radius, min(start[1], end[1])-radius,
                  max(start[0], end[0])+radius, max(start[1], end[1])+radius)
        if radius <= 0 or not all(math.isfinite(v) for v in (*bounds, radius)):
            continue
        masks = [page_bounds]
        for clip in clips:
            paths = clip.get('items') or ()
            if len(paths) != 1 or paths[0][0] != 're':
                break
            masks.append(tuple(paths[0][1]))
        if len(masks) != len(clips)+1 or any(len(box) != 4 or not all(math.isfinite(v) for v in box)
                or box[0] > bounds[0] or box[1] > bounds[1] or box[2] < bounds[2] or box[3] < bounds[3] for box in masks):
            continue
        result[seq] = row
    return result


def bind_source_line_dashes(page, page_data, scale, flip_y):
    candidates = [p for p in page_data.primitives if p.type == "line"
                  and len(p.points or ()) == 2 and p.stroke_color is not None
                  and p.fill_color is None and p.dash_pattern]
    if not candidates:
        return {}
    raw = {row["seqno"]: row for row in page.get_drawings() if "seqno" in row}
    try:
        svg_rows = _renderer_lines(page)
    except (ValueError, RuntimeError, ET.ParseError):
        # An unavailable renderer proof cannot authorize new dash geometry.
        # Extraction.summary() lists these source IDs as native approximations.
        return {}
    qualified = {}
    matrix = _page_rotation_transform(page.rect, page.rotation_matrix)
    page_height = float(page.rect.height)
    factor = float(scale)*25.4/72
    dot_strokes = None

    def model(point):
        x, y = _transform_pdf_point(point[0], point[1], matrix)
        return x*factor, (page_height-y if flip_y else y)*factor

    for primitive in candidates:
        source = raw.get(primitive.source_draw_order)
        if (not source or source.get("closePath") or len(source["items"]) != 1
                or source["items"][0][0] != "l" or source.get("fill") is not None):
            continue
        _kind, raw_start, raw_end = source["items"][0]
        start, end = tuple(raw_start), tuple(raw_end)
        length = math.dist(start, end)
        match = re.fullmatch(r"\s*\[([^]]*)\]\s*("+_NUMBER+r")\s*", source.get("dashes", ""))
        if length <= 0 or not match:
            continue
        pattern, phase = _numbers(match.group(1)), float(match.group(2))
        matches = []
        for row in svg_rows:
            if not (_near(start, row["start"]) and _near(end, row["end"])):
                continue
            if len(pattern) != len(row["pattern"]):
                continue
            if any(abs(a-b*row["expansion"]) > _SVG_TOL_PT
                   for a, b in zip(pattern, row["pattern"], strict=True)):
                continue
            if abs(phase-row["phase"]*row["expansion"]) > _SVG_TOL_PT:
                continue
            if abs(source["width"]-row["width"]*row["expansion"]) > _SVG_TOL_PT:
                continue
            if any(abs(a-b) > 1/255 for a, b in zip(source["color"], row["color"], strict=True)):
                continue
            if set(source.get("lineCap", ())) != {row["cap"]}:
                continue
            matches.append(row)
        if not matches or any(row != matches[0] for row in matches):
            continue
        row = matches[0]
        target_start, target_end = model(start), model(end)
        dx, dy = target_end[0]-target_start[0], target_end[1]-target_start[1]
        denominator = dx*dx+dy*dy
        if denominator <= 0:
            continue
        parameters = []
        for point in primitive.points:
            t = ((point[0]-target_start[0])*dx+(point[1]-target_start[1])*dy)/denominator
            projected = (target_start[0]+t*dx, target_start[1]+t*dy)
            if math.dist(point, projected) > 1e-9 or not -1e-12 <= t <= 1+1e-12:
                break
            parameters.append(max(0.0, min(1.0, t)))
        if len(parameters) != 2:
            continue
        visible = tuple(sorted(parameters))
        exact_pattern = tuple(value*row["along_scale"] for value in row["pattern"])
        exact_phase = row["phase"]*row["along_scale"]
        dots, dot_radius = (), 0.0
        try:
            if 0 in exact_pattern:
                if row['cap'] != 1 or not row['similarity'] or visible != (0.0, 1.0):
                    continue
                if dot_strokes is None:
                    a, b, c, d, e, f = matrix
                    determinant = a*d-b*c
                    inverse = (d/determinant, -b/determinant, -c/determinant, a/determinant,
                               (c*f-d*e)/determinant, (b*e-a*f)/determinant)
                    corners = [_point(point, inverse) for point in
                               ((0, 0), (page.rect.width, 0), (page.rect.width, page.rect.height), (0, page.rect.height))]
                    page_bounds = (min(p[0] for p in corners), min(p[1] for p in corners),
                                   max(p[0] for p in corners), max(p[1] for p in corners))
                    dot_strokes = _unclipped_round_dot_strokes(page, page_bounds)
                if source['seqno'] not in dot_strokes:
                    continue
                intervals, dots = round_dot_dash_intervals(length, exact_pattern, exact_phase)
                dot_radius = float(source['width'])*abs(factor)/2
            else:
                intervals = dash_intervals(length, exact_pattern, exact_phase, visible)
        except ValueError:
            continue
        segments = tuple(((target_start[0]+a/length*dx, target_start[1]+a/length*dy),
                          (target_start[0]+b/length*dx, target_start[1]+b/length*dy))
                         for a, b in intervals)
        qualified[primitive.id] = SourceLineDashes(
            int(source["seqno"]), start, end, exact_pattern, exact_phase,
            visible, segments, row["cap"],
            tuple((target_start[0]+position/length*dx, target_start[1]+position/length*dy) for position in dots),
            dot_radius,
        )
    return qualified

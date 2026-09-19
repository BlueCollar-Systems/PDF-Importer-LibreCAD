"""Exact physical footprints for short, solid, round-cap PDF ink strokes.

A DXF lineweight cannot represent the source cap geometry reliably. Keep the
original centerline and add an exact editable HATCH footprint. This bounded helper does not implement dash, join, clip, or blend rules.
"""
from __future__ import annotations

import math
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pdfcadcore.primitive_extractor import _page_rotation_transform, _transform_pdf_point
from .image_paint_order import CAP_BOUND_MARGIN_PDF

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_LINE = re.compile(r"\s*M\s*(" + _NUMBER + r")[ ,]+(" + _NUMBER
                   + r")\s*([LHV]?)\s*(" + _NUMBER + r")(?:[ ,]+(" + _NUMBER + r"))?\s*")


def short_round_stroke(row):
    """Return a source capsule, or None for a path outside this exact case."""
    items = row.get("items") or ()
    caps = row.get("lineCap")
    if (row.get("type") != "s" or row.get("closePath")
            or row.get("fill") is not None or row.get("color") is None
            or row.get("dashes") not in (None, "[] 0")
            or not isinstance(caps, (tuple, list)) or len(caps) != 3
            or any(cap != 1 for cap in caps)
            or len(items) != 1 or len(items[0]) != 3 or items[0][0] != "l"):
        return None
    try:
        start, end = (tuple(float(v) for v in point) for point in items[0][1:])
        width = float(row["width"])
        alpha = float(row.get("stroke_opacity", 1))
    except (KeyError, TypeError, ValueError):
        return None
    if (len(start) != 2 or len(end) != 2
            or not all(math.isfinite(v) for v in (*start, *end, width, alpha))
            or width <= 0 or alpha != 1):
        return None
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length > width:
        return None
    return {"start": start, "end": end, "width": width,
            "length": length, "area": width * length + math.pi * (width / 2) ** 2}


def capsule_edges(capsule):
    """Analytic boundary as lines and three-point semicircles in PDF units."""
    start, end = capsule["start"], capsule["end"]
    length, radius = capsule["length"], capsule["width"] / 2
    ux, uy = ((end[0] - start[0]) / length, (end[1] - start[1]) / length) if length else (1., 0.)
    nx, ny = -uy * radius, ux * radius
    a = (start[0] + nx, start[1] + ny)
    b = (end[0] + nx, end[1] + ny)
    c = (end[0] - nx, end[1] - ny)
    d = (start[0] - nx, start[1] - ny)
    right = (end[0] + ux * radius, end[1] + uy * radius)
    left = (start[0] - ux * radius, start[1] - uy * radius)
    if not length:
        return [("arc", a, right, c), ("arc", c, left, a)]
    return [("line", a, b), ("arc", b, right, c),
            ("line", c, d), ("arc", d, left, a)]


def _box(value):
    try:
        result = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if len(result) != 4 or not all(math.isfinite(v) for v in result):
        return None
    return result if result[0] <= result[2] and result[1] <= result[3] else None


def unclipped_capsules(rows, page_bounds):
    """Prove full physical cap coverage inside page and rectangular clips.

    Nonrectangular and partially intersecting masks remain outside this helper.
    Group blend metadata is retained separately: a geometric footprint is not
    evidence that the CAD viewport reproduced the PDF's compositing operation.
    """
    page_bounds = _box(page_bounds)
    if page_bounds is None:
        return {}
    clips, groups, result, seen = [], [], {}, set()
    for row in rows:
        level = row.get("level", 0)
        clips = [entry for entry in clips if entry.get("level", 0) < level]
        groups = [entry for entry in groups if entry.get("level", 0) < level]
        if row.get("type") == "clip":
            clips.append(row)
            continue
        if row.get("type") == "group":
            groups.append(row)
            continue
        capsule, seq = short_round_stroke(row), row.get("seqno")
        if capsule is None or type(seq) is not int or any(group.get("opacity", 1) != 1 for group in groups):
            continue
        if seq in seen:
            result.pop(seq, None)
            continue
        seen.add(seq)
        radius = capsule["width"] / 2
        start, end = capsule["start"], capsule["end"]
        bounds = (min(start[0], end[0]) - radius, min(start[1], end[1]) - radius,
                  max(start[0], end[0]) + radius, max(start[1], end[1]) + radius)
        masks = [page_bounds]
        for clip in clips:
            items = clip.get("items") or ()
            if len(items) != 1 or len(items[0]) < 2 or items[0][0] != "re":
                break
            box = _box(items[0][1])
            if box is None:
                break
            masks.append(box)
        if len(masks) != len(clips) + 1 or any(
                box[0] > bounds[0] or box[1] > bounds[1]
                or box[2] < bounds[2] or box[3] < bounds[3] for box in masks):
            continue
        result[seq] = {"capsule": capsule, "clip_bounds": masks,
                       "source_blend_modes": [group.get("blendmode", "Normal") for group in groups]}
    return result


def bind_source_capsules(page, page_data, display_to_model):
    """Bind full source ink to one unchanged literal centerline in the model."""
    by_order = {}
    for primitive in page_data.primitives:
        by_order.setdefault(primitive.source_draw_order, []).append(primitive)
    candidates = [row for row in getattr(page_data, '_source_drawings', ())
                  if short_round_stroke(row) is not None and row.get('seqno') in by_order]
    if not candidates:
        return []
    rotation = _page_rotation_transform(page.rect, getattr(page, 'rotation_matrix', None))
    a, b, c, d, e, f = rotation
    det = a*d-b*c
    derotation = (d/det, -b/det, -c/det, a/det, (c*f-d*e)/det, (b*e-a*f)/det)
    corners = [_transform_pdf_point(x, y, derotation) for x, y in
               ((0, 0), (page.rect.width, 0), (page.rect.width, page.rect.height), (0, page.rect.height))]
    bounds = (min(p[0] for p in corners), min(p[1] for p in corners),
              max(p[0] for p in corners), max(p[1] for p in corners))
    rows = page.get_drawings(extended=True)
    proofs = bind_similarity_strokes(unclipped_capsules(rows, bounds), rows,
                                    page.get_svg_image(text_as_path=True), derotation)
    paint_log = page.get_bboxlog()
    unit = math.hypot(display_to_model[0], display_to_model[1])

    def model(point):
        return _transform_pdf_point(*_transform_pdf_point(*point, rotation), display_to_model)

    result = []
    for raw in candidates:
        seq = raw['seqno']
        proof = proofs.get(seq)
        primitives = by_order.get(seq, ())
        if proof is None or len(primitives) != 1:
            continue
        primitive = primitives[0]
        capsule = proof['capsule']
        radius = capsule['width']/2
        ink_bounds = (min(capsule['start'][0], capsule['end'][0])-radius,
                      min(capsule['start'][1], capsule['end'][1])-radius,
                      max(capsule['start'][0], capsule['end'][0])+radius,
                      max(capsule['start'][1], capsule['end'][1])+radius)
        if seq >= len(paint_log) or paint_log[seq][0] != 'stroke-path':
            continue
        renderer_bounds = _box(paint_log[seq][1])
        if renderer_bounds is not None:
            x0, y0, x1, y1 = renderer_bounds
            renderer_bounds = (x0-CAP_BOUND_MARGIN_PDF, y0-CAP_BOUND_MARGIN_PDF,
                               x1+CAP_BOUND_MARGIN_PDF, y1+CAP_BOUND_MARGIN_PDF)
        if (renderer_bounds is None or renderer_bounds[0] > ink_bounds[0]
                or renderer_bounds[1] > ink_bounds[1] or renderer_bounds[2] < ink_bounds[2]
                or renderer_bounds[3] < ink_bounds[3]):
            continue  # Ordering absence must use bounds covering the entire cap.
        endpoints = [model(capsule['start']), model(capsule['end'])]
        if (primitive.type != 'line' or primitive.fill_color is not None
                or primitive.dash_pattern or primitive.clip_fill_group_id
                or len(primitive.points or ()) != 2
                or primitive.source_stroke_color is None
                or any(math.dist(p, q) > 1e-9 for p, q in zip(endpoints, primitive.points, strict=True))
                or not math.isclose(primitive.line_width or 0, capsule['width']*unit, abs_tol=1e-9, rel_tol=0)
                or primitive.stroke_opacity != 1
                or any(abs(p-q) > 1e-9 for p, q in zip(raw['color'], primitive.source_stroke_color, strict=True))):
            continue
        result.append(dict(schema='bcs.source-round-stroke/1', primitive_id=primitive.id,
                           source_seqno=seq, source_rgb=list(raw['color']), source_page=page_data.page_number,
                           source_proof=proof, source_to_display=list(rotation),
                           display_to_model=list(display_to_model),
                           centerline_model=endpoints, width_model=capsule['width']*unit,
                           area_model=capsule['area']*unit*unit,
                           edges_model=[(kind, *(model(p) for p in points))
                                        for kind, *points in capsule_edges(capsule)]))
    if result:
        # Record the original file now, while its extracted geometry is bound;
        # export must not certify old vectors against a subsequently edited PDF.
        source_path = Path(page.parent.name)
        with source_path.open('rb') as source_stream:
            source_sha = hashlib.file_digest(source_stream, 'sha256').hexdigest()
        for row in result:
            row['source_pdf_sha256'] = source_sha
    return result


def verify_model_capsule(proof, primitive, source_sha256):
    """Reject stale source files or changed normalized centerlines at export."""
    if (proof['source_pdf_sha256'] != source_sha256 or proof['primitive_id'] != primitive.id
            or proof['source_seqno'] != primitive.source_draw_order
            or primitive.type != 'line' or primitive.closed or primitive.dash_pattern
            or primitive.fill_color is not None or primitive.stroke_opacity != 1
            or primitive.source_stroke_color is None or len(primitive.points or ()) != 2
            or any(math.dist(a, b) > 1e-9 for a, b in zip(proof['centerline_model'], primitive.points, strict=True))
            or not math.isclose(proof['width_model'], primitive.line_width or 0, abs_tol=1e-9, rel_tol=0)
            or tuple(proof['source_rgb']) != tuple(primitive.source_stroke_color)):
        raise RuntimeError('Source stroke ink no longer matches original PDF or model centerline')


def bind_similarity_strokes(proofs, rows, svg, svg_to_source=None):
    """Reject circular-cap inference unless the renderer proves a similarity CTM.

    MuPDF's flattened drawing width alone is insufficient: a nonuniform source
    transform gives an elliptical cap. Bind a unique visible SVG stroke using
    its endpoints, color, width and cap; never infer a missing transform.
    """
    try:
        root = ET.fromstring(svg)
    except (ET.ParseError, TypeError):
        return {}
    parents = {child: parent for parent in root.iter() for child in parent}
    candidates = {}
    for node in root.iter():
        if (node.tag.rsplit("}", 1)[-1] != "path" or node.get("fill") != "none"
                or node.get("stroke-linecap") != "round"
                or node.get("stroke-dasharray") or node.get("stroke-opacity", "1") != "1"
                or any(key in node.attrib for key in ("filter", "mask", "opacity", "style"))):
            continue
        parent, permitted = parents.get(node), True
        while parent is not None:
            tag = parent.tag.rsplit("}", 1)[-1]
            if (tag not in ("g", "svg")
                    or any(key in parent.attrib for key in ("transform", "filter", "mask", "opacity", "stroke-dasharray"))
                    or parent.get("style", "") not in ("", "mix-blend-mode:multiply")):
                permitted = False
                break
            parent = parents.get(parent)
        match = _LINE.fullmatch(node.get("d", ""))
        matrix = node.get("transform", "")
        rgb = node.get("stroke", "")
        if (not permitted or match is None or not matrix.startswith("matrix(")
                or not matrix.endswith(")") or re.fullmatch(r"#[0-9a-fA-F]{6}", rgb) is None):
            continue
        try:
            a, b, c, d, e, f = map(float, re.split(r"[ ,]+", matrix[7:-1].strip()))
            width = float(node.get("stroke-width", "nan"))
            x, y = float(match[1]), float(match[2])
            if match[3] in ("", "L") and match[5] is not None:
                end = (float(match[4]), float(match[5]))
            elif match[3] == "H" and match[5] is None:
                end = (float(match[4]), y)
            elif match[3] == "V" and match[5] is None:
                end = (x, float(match[4]))
            else:
                continue
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (a, b, c, d, e, f, width, x, y, *end)) or width <= 0:
            continue
        scale2 = a*a + b*b
        if scale2 <= 0 or abs(scale2 - c*c - d*d) > scale2*1e-8 or abs(a*c + b*d) > scale2*1e-8:
            continue
        start, end = [(a*px + c*py + e, b*px + d*py + f) for px, py in ((x, y), end)]
        if svg_to_source is not None:
            aa, bb, cc, dd, ee, ff = svg_to_source
            start, end = [(aa*px + cc*py + ee, bb*px + dd*py + ff) for px, py in (start, end)]
        item = dict(start=start, end=end, width=width*math.sqrt(scale2),
                    rgb=tuple(int(rgb[i:i+2], 16)/255 for i in (1, 3, 5)),
                    matrix=[a, b, c, d, e, f], path=node.get("d"))
        key = (math.floor(start[0]/.01), math.floor(start[1]/.01))
        candidates.setdefault(key, []).append(item)
    # Match every candidate source stroke, even one rejected by the clipping
    # guard. One renderer path must never certify two coincident source paints
    # with different CTMs (a circle can otherwise falsely certify an ellipse).
    bindings, use_count = {}, {}
    for row in rows:
        capsule = short_round_stroke(row)
        if capsule is None:
            continue
        seq = row.get("seqno")
        start, end, width = capsule["start"], capsule["end"], capsule["width"]
        color = row["color"]
        key = (math.floor(start[0]/.01), math.floor(start[1]/.01))
        matches = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for item in candidates.get((key[0]+dx, key[1]+dy), ()):
                    if (max(abs(x-y) for x, y in zip(start+end, item["start"]+item["end"], strict=True)) <= .001
                            and abs(width-item["width"]) <= .0001
                            and max(abs(x-y) for x, y in zip(color, item["rgb"], strict=True)) <= 1/255 + 1e-6):
                        matches.append(item)
        if len(matches) == 1:
            item = matches[0]
            bindings[seq] = item
            use_count[id(item)] = use_count.get(id(item), 0) + 1
    result = {}
    for seq, proof in proofs.items():
        item = bindings.get(seq)
        if item is not None and use_count[id(item)] == 1:
            result[seq] = dict(proof, source_svg_stroke=item)
    return result


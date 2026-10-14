"""Prove complete planar block closures before repairing owned-copy Z scales.

No document mutation occurs here. Native LibreCAD can save a planar INSERT
with Z scale zero; replacing only that scale by one is safe only when every
referenced geometric definition remains exactly in the XY plane.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math

from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.math import Vec3

from .drawing_copy import DrawingCopyError

MAX_RECORDS = 1_000_000
MAX_DEPTH = 32
SUPPORTED = {"LINE", "POINT", "SOLID", "TRACE", "LWPOLYLINE", "POLYLINE",
             "CIRCLE", "ARC", "ELLIPSE", "SPLINE", "HATCH", "TEXT", "MTEXT",
             "ATTRIB", "ATTDEF", "IMAGE"}


def _fail():
    raise DrawingCopyError("A flat block's zero Z scale could not be safely restored. "
                           "Its complete geometry must be planar and supported. "
                           "The original was kept; open the PDF separately.")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail()
    return float(value)


def _point(value, *, dimensions=3):
    values = tuple(value)
    if len(values) != dimensions:
        _fail()
    values = tuple(_number(v) for v in values)
    if dimensions == 3 and values[2] != 0:
        _fail()
    return values[:2]


def _get(entity, key, default=None):
    return entity.dxf.get(key, default) if entity.DXFATTRIBS.get(key) is not None else default


def _normal(entity):
    if Vec3(_get(entity, "extrusion", (0, 0, 1))) != Vec3(0, 0, 1):
        _fail()
    if _number(_get(entity, "thickness", 0)) != 0:
        _fail()


def _spline(points, weights, knots, degree, *, dimensions=3):
    points = [_point(point, dimensions=dimensions) for point in points]
    degree = _number(degree)
    if not points or int(degree) != degree or degree < 1 or len(points) < degree + 1:
        _fail()
    weights = [_number(weight) for weight in weights]
    knots = [_number(knot) for knot in knots]
    if (weights and (len(weights) != len(points) or any(weight <= 0 for weight in weights))
            or len(knots) != len(points) + degree + 1
            or any(a > b for a, b in zip(knots, knots[1:], strict=False))):
        _fail()
    return points


def _bulges(vertices, closed):
    points = [(x, y) for x, y, _ in vertices]
    pairs = list(zip(vertices, vertices[1:], strict=False))
    if closed and vertices:
        pairs.append((vertices[-1], vertices[0]))
    for (x, y, bulge), (end_x, end_y, _) in pairs:
        if bulge:
            radius = math.hypot(end_x - x, end_y - y) / 4 * (abs(bulge) + 1 / abs(bulge))
            extent = _number(2 * radius)
            points += [(x - extent, y - extent), (x + extent, y + extent)]
    return points


def _geometry(entity):
    """Bind each supported entity's full typed geometric definition."""
    kind = entity.dxftype()
    # These text payloads carry geometry outside their ordinary DXF attribute
    # roster.  Exporting MTEXT columns can also synchronize linked entities.
    # Reject them before any tag collection until their complete definitions
    # and occurrence contexts have a dedicated qualification implementation.
    if (kind in {"ATTRIB", "ATTDEF"} and entity.has_embedded_mtext_entity
            or kind == "MTEXT" and entity.has_columns):
        _fail()
    _normal(entity)
    points = []
    if kind == "LINE":
        points = [_point(entity.dxf.start), _point(entity.dxf.end)]
    elif kind == "POINT":
        points = [_point(entity.dxf.location)]
    elif kind in {"SOLID", "TRACE"}:
        points = [_point(getattr(entity.dxf, "vtx" + str(index))) for index in range(4)]
    elif kind == "LWPOLYLINE":
        if _number(entity.dxf.get("elevation", 0)) != 0:
            _fail()
        vertices = []
        for x, y, start, end, bulge in entity.get_points("xyseb"):
            vertices.append((_number(x), _number(y), _number(bulge)))
            for value in (start, end, bulge):
                _number(value)
        points += _bulges(vertices, entity.closed)
    elif kind == "POLYLINE":
        if not (entity.is_2d_polyline or entity.is_3d_polyline) or entity.is_polygon_mesh or entity.is_poly_face_mesh:
            _fail()
        points.append(_point(entity.dxf.get("elevation", (0, 0, 0))))
        vertices = []
        for vertex in entity.vertices:
            _normal(vertex)
            points.append(_point(vertex.dxf.location))
            for key in ("start_width", "end_width", "bulge"):
                _number(vertex.dxf.get(key, 0))
            vertices.append((*_point(vertex.dxf.location), _number(vertex.dxf.get("bulge", 0))))
        points += _bulges(vertices, entity.is_closed)
    elif kind in {"CIRCLE", "ARC"}:
        x, y = _point(entity.dxf.center)
        radius = _number(entity.dxf.radius)
        if radius < 0:
            _fail()
        points = [(x - radius, y - radius), (x + radius, y + radius)]
        if kind == "ARC":
            _number(entity.dxf.start_angle); _number(entity.dxf.end_angle)
    elif kind == "ELLIPSE":
        x, y = _point(entity.dxf.center)
        ax, ay = _point(entity.dxf.major_axis)
        ratio = _number(entity.dxf.ratio)
        if not 0 < ratio <= 1:
            _fail()
        radius = math.hypot(ax, ay)
        points = [(x - radius, y - radius), (x + radius, y + radius)]
        _number(entity.dxf.start_param); _number(entity.dxf.end_param)
    elif kind == "SPLINE":
        points = _spline(entity.control_points, entity.weights, entity.knots, entity.dxf.degree)
        points += [_point(point) for point in entity.fit_points]
        for key in ("start_tangent", "end_tangent"):
            value = entity.dxf.get(key)
            if value is not None:
                points.append(_point(value))
    elif kind == "HATCH":
        points.append(_point(entity.dxf.elevation))
        for path in entity.paths:
            if type(path).__name__ == "PolylinePath":
                vertices = []
                for x, y, bulge in path.vertices:
                    vertices.append((_number(x), _number(y), _number(bulge)))
                points += _bulges(vertices, path.is_closed)
            elif type(path).__name__ == "EdgePath":
                for edge in path.edges:
                    typ = type(edge).__name__
                    if typ == "LineEdge":
                        points += [_point(edge.start, dimensions=2), _point(edge.end, dimensions=2)]
                    elif typ in {"ArcEdge", "EllipseEdge"}:
                        x, y = _point(edge.center, dimensions=2)
                        if typ == "ArcEdge":
                            radius = _number(edge.radius)
                            _number(edge.start_angle); _number(edge.end_angle)
                        else:
                            ax, ay = _point(edge.major_axis, dimensions=2)
                            ratio = _number(edge.ratio)
                            if not 0 < ratio <= 1:
                                _fail()
                            radius = math.hypot(ax, ay)
                            _number(edge.start_angle); _number(edge.end_angle)
                        if radius < 0:
                            _fail()
                        points += [(x - radius, y - radius), (x + radius, y + radius)]
                    elif typ == "SplineEdge":
                        points += _spline(edge.control_points, edge.weights, edge.knot_values, edge.degree, dimensions=2)
                        points += [_point(point, dimensions=2) for point in edge.fit_points]
                        for tangent in (edge.start_tangent, edge.end_tangent):
                            if tangent is not None:
                                points.append(_point(tangent, dimensions=2))
                    else:
                        _fail()
            else:
                _fail()
        points += [_point(point, dimensions=2) for point in entity.seeds]
    elif kind in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
        points = [_point(entity.dxf.insert)]
        for key in ("align_point", "text_direction"):
            value = _get(entity, key)
            if value is not None:
                points.append(_point(value))
    elif kind == "IMAGE":
        points = [_point(entity.dxf.insert), _point(entity.dxf.u_pixel), _point(entity.dxf.v_pixel)]
        points += [_point(point, dimensions=2) for point in entity.boundary_path]
        _point(entity.dxf.image_size)
    else:
        _fail()
    return points


def _qualify_planar_insert_repairs(document, *, cancel_check=lambda: None,
                                  max_records=MAX_RECORDS, max_depth=MAX_DEPTH):
    """Return original handles and positive proofs; never expand repeated DAGs."""
    if (isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 1
            or isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= MAX_DEPTH):
        _fail()
    cancel_check()
    candidates = []
    roots = []
    for index, entity in enumerate(document.entitydb.values()):
        if index % 256 == 0:
            cancel_check()
        if entity.is_alive and entity.dxftype() == "INSERT":
            roots.append(entity)
            if entity.dxf.get("zscale", 1) == 0:
                candidates.append(entity)
    if not candidates:
        return []
    blocks = {}
    records = 0
    coordinate_count = 0

    def tagged(entity):
        nonlocal records, coordinate_count
        cancel_check()
        records += 1
        if records > max_records:
            _fail()
        collector = TagCollector(optional=True)
        entity.export_dxf(collector)
        tags = []
        magnitude = 1.0
        for index, tag in enumerate(collector.tags):
            if index % 256 == 0:
                cancel_check()
            if isinstance(tag.value, float):
                value = _number(tag.value)
                magnitude = max(magnitude, abs(value))
                coordinate_count += 1
                if coordinate_count > max_records * 32:
                    _fail()
            tags.append((tag.code, list(tag.value) if isinstance(tag.value, Vec3) else tag.value))
        signature = hashlib.sha256(json.dumps(tags, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return signature, magnitude

    def inserted(entity, ancestors):
        _normal(entity)
        if (entity.dxf.get("column_count", 1) != 1 or entity.dxf.get("row_count", 1) != 1):
            _fail()
        _point(entity.dxf.insert)
        for axis in "xyz":
            scale = _number(entity.dxf.get(axis + "scale", 1))
            if axis != "z" and scale == 0:
                _fail()
        _number(entity.dxf.get("rotation", 0))
        name = entity.dxf.name
        key = name.casefold()
        if key in ancestors or name not in document.blocks or len(ancestors) >= max_depth:
            _fail()
        proof = block(name, ancestors)
        if len(ancestors) + proof["depth"] > max_depth:
            _fail()
        bounds = proof["bounds"]
        matrix = entity.matrix44()
        corners = [matrix.transform((x, y, 0)) for x in bounds[::2] for y in bounds[1::2]]
        points = [_point(point) for point in corners]
        attribute_signatures = []
        for attribute in entity.attribs:
            attribute_points, attribute_signature = leaf(attribute)
            points += attribute_points
            attribute_signatures.append(attribute_signature)
        if attribute_signatures:
            proof = dict(proof, sha256=hashlib.sha256(json.dumps([proof["sha256"], attribute_signatures], separators=(",", ":")).encode()).hexdigest())
        return points, proof

    def leaf(entity):
        if entity.dxftype() not in SUPPORTED:
            _fail()
        points = _geometry(entity)
        for point in points:
            _point(point, dimensions=2)
        signature, magnitude = tagged(entity)
        # This conservative envelope binds all finite numeric definition data,
        # including bulges, widths and text dimensions, not only authored points.
        envelope = magnitude * 4
        _number(envelope)
        points += [(-envelope, -envelope), (envelope, envelope)]
        return points, signature

    def block(name, ancestors):
        key = name.casefold()
        if key in blocks:
            return blocks[key]
        cancel_check()
        layout = document.blocks.get(name)
        if layout.block.is_xref or layout.block.is_xref_overlay:
            _fail()
        base = _point(layout.block.dxf.base_point)
        roster = []
        points = [base]
        depth = 1
        types = Counter()
        for entity in layout.entities_in_redraw_order():
            if entity.dxftype() == "INSERT":
                child_points, child = inserted(entity, ancestors | {key})
                signature, _ = tagged(entity)
                points += child_points
                depth = max(depth, child["depth"] + 1)
                types.update(child["types"])
                roster.append([signature, child["sha256"]])
            else:
                child_points, signature = leaf(entity)
                points += child_points
                types[entity.dxftype()] += 1
                roster.append([signature])
        bounds = [min(x for x, _ in points), min(y for _, y in points),
                  max(x for x, _ in points), max(y for _, y in points)]
        proof = {"depth": depth, "bounds": bounds, "types": dict(types),
                 "sha256": hashlib.sha256(json.dumps([base, roster], separators=(",", ":"), allow_nan=False).encode()).hexdigest()}
        blocks[key] = proof
        return proof

    plans = []
    for entity in candidates:
        cancel_check()
        _points, proof = inserted(entity, set())
        signature, _ = tagged(entity)
        plans.append({"handle": str(entity.dxf.handle), "definition_sha256": signature,
                      "closure_sha256": proof["sha256"], "closure_depth": proof["depth"],
                      "expanded_leaf_types": proof["types"],
                      "exact_local_and_transformed_Z_zero": True,
                      "exact_positive_Z_extrusion_and_zero_thickness": True})
    # Validate every occurrence of the referenced closure in its ancestor
    # context, without expanding repeated instances. Cached block envelopes
    # propagate finite ranges through each owning definition and root.
    relevant = {entity.dxf.name.casefold() for entity in candidates}
    changed = True
    while changed:
        changed = False
        for entity in roots:
            cancel_check()
            if entity.dxf.name.casefold() in relevant:
                owner = document.entitydb.get(entity.dxf.get("owner", ""))
                if owner is None or owner.dxftype() != "BLOCK_RECORD":
                    _fail()
                name = owner.dxf.name.casefold()
                if name not in relevant:
                    relevant.add(name)
                    changed = True
    for entity in roots:
        if entity.dxf.name.casefold() in relevant:
            inserted(entity, set())
            tagged(entity)
    cancel_check()
    return plans


def qualify_planar_insert_repairs(document, **options):
    try:
        return _qualify_planar_insert_repairs(document, **options)
    except (AttributeError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        _fail()

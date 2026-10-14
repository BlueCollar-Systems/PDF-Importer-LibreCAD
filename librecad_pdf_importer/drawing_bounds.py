"""Meaningful drawing frames, without treating invalid LAYOUT caches as bounds.

Authored finite HEADER frames are authoritative (including PDF sheet margins).
The fallback is a conservative visible planar control envelope, never a claim
of exact text, paint, or font bounds. Unsupported active geometry fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ezdxf.math import Vec3

from .drawing_copy import DrawingCopyCancelled, DrawingCopyError
from .planar_blocks import MAX_DEPTH, MAX_RECORDS, _geometry, _normal, _number, _point

LEAF_TYPES = {"LINE", "POINT", "SOLID", "TRACE", "LWPOLYLINE", "POLYLINE",
              "CIRCLE", "ARC", "ELLIPSE", "SPLINE", "HATCH", "IMAGE"}


def _fail():
    raise DrawingCopyError("The drawing's bounds could not be safely established. "
                           "Save a standard DXF copy in LibreCAD to refresh its bounds. "
                           "The original was kept; open the PDF separately.")


def _vector(value):
    values = tuple(value)
    if len(values) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                               or not math.isfinite(v) for v in values):
        _fail()
    return tuple(float(v) for v in values)


@dataclass(frozen=True)
class DrawingBounds:
    minimum: tuple
    maximum: tuple
    provenance: str

    def record(self):
        return {"minimum": list(self.minimum), "maximum": list(self.maximum),
                "provenance": self.provenance}


def declared_bounds(document):
    low, high = document.header.get("$EXTMIN"), document.header.get("$EXTMAX")
    if low is None or high is None:
        return None
    low, high = _vector(low), _vector(high)
    if any(a > b for a, b in zip(low, high, strict=True)):
        return None
    return DrawingBounds(low, high, "declared_HEADER_frame")


def _union(bounds, provenance="conservative_visible_planar_control_geometry"):
    bounds = [value for value in bounds if value is not None]
    if not bounds:
        return None
    return DrawingBounds(tuple(min(value.minimum[i] for value in bounds) for i in range(3)),
                         tuple(max(value.maximum[i] for value in bounds) for i in range(3)), provenance)


def _conservative_bounds(document, cancel_check, max_records):
    records = 0
    cache = {}

    def budget(amount=1):
        nonlocal records
        cancel_check()
        records += amount
        if records > max_records:
            _fail()

    def visible(entity, inherited_layer):
        name = entity.dxf.get("layer", "0")
        if inherited_layer is not None and name.casefold() == "0":
            name = inherited_layer
        if name not in document.layers:
            _fail()
        layer = document.layers.get(name)
        if layer.is_off() or layer.is_frozen() or entity.dxf.get("invisible", 0):
            return None
        if entity.dxftype() in {"ATTRIB", "ATTDEF"} and entity.dxf.get("flags", 0) & 1:
            return None
        return name

    def payload_budget(entity):
        kind = entity.dxftype()
        if kind == "LWPOLYLINE":
            budget(len(entity))
        elif kind == "POLYLINE":
            if not entity.vertices:
                _fail()
            budget(len(entity.vertices))
        elif kind == "SPLINE":
            budget(sum(len(value) for value in (entity.control_points, entity.fit_points,
                                                entity.knots, entity.weights)))
        elif kind == "HATCH":
            if not entity.paths:
                _fail()
            budget(len(entity.paths) + len(entity.seeds))
            for path in entity.paths:
                if type(path).__name__ == "PolylinePath":
                    budget(len(path.vertices))
                elif type(path).__name__ == "EdgePath":
                    budget(len(path.edges))
                    for edge in path.edges:
                        if type(edge).__name__ == "SplineEdge":
                            budget(sum(len(value) for value in (edge.control_points, edge.fit_points,
                                                                edge.knot_values, edge.weights)))
        elif kind == "IMAGE":
            budget(len(entity.boundary_path))

    def visit(entity, ancestors, inherited_layer=None):
        budget()
        layer = visible(entity, inherited_layer)
        if layer is None:
            return None, 0
        if entity.dxftype() == "INSERT":
            _normal(entity)
            _point(entity.dxf.insert)
            for axis in "xyz":
                if _number(entity.dxf.get(axis + "scale", 1)) == 0:
                    _fail()
            _number(entity.dxf.get("rotation", 0))
            if entity.dxf.get("row_count", 1) != 1 or entity.dxf.get("column_count", 1) != 1:
                _fail()
            name = entity.dxf.name
            key = name.casefold()
            if key in ancestors or name not in document.blocks or len(ancestors) >= MAX_DEPTH:
                _fail()
            context = key, layer.casefold()
            if context not in cache:
                block = document.blocks.get(name)
                if block.block.is_xref or block.block.is_xref_overlay:
                    _fail()
                _point(block.block.dxf.base_point)
                children = [visit(child, ancestors | {key}, layer) for child in block]
                cache[context] = (_union(row[0] for row in children),
                                  1 + max((row[1] for row in children), default=0))
            local, depth = cache[context]
            if len(ancestors) + depth > MAX_DEPTH:
                _fail()
            attached = [visit(attribute, ancestors, layer)[0] for attribute in entity.attribs]
            transformed = None
            if local is not None:
                matrix = entity.matrix44()
                corners = [_vector(matrix.transform((x, y, z)))
                           for x in (local.minimum[0], local.maximum[0])
                           for y in (local.minimum[1], local.maximum[1])
                           for z in (local.minimum[2], local.maximum[2])]
                if any(point[2] != 0 for point in corners):
                    _fail()
                transformed = DrawingBounds(tuple(min(p[i] for p in corners) for i in range(3)),
                                            tuple(max(p[i] for p in corners) for i in range(3)), "transformed_control_envelope")
            return _union([transformed, *attached]), depth
        if entity.dxftype() not in LEAF_TYPES or entity.proxy_graphic:
            _fail()
        payload_budget(entity)
        points = _geometry(entity)
        # Full typed controls bound curves without approximate font/bbox tools.
        width = 0.0
        if entity.dxftype() == "LWPOLYLINE":
            width = max([abs(_number(entity.dxf.get("const_width", 0))),
                         *(abs(_number(v)) for row in entity.get_points("se") for v in row)])
        elif entity.dxftype() == "POLYLINE":
            width = max([abs(_number(entity.dxf.get(key, 0))) for key in ("default_start_width", "default_end_width")]
                        + [abs(_number(vertex.dxf.get(key, 0))) for vertex in entity.vertices
                           for key in ("start_width", "end_width")])
        elif entity.dxftype() == "IMAGE":
            origin, u, v = (Vec3(getattr(entity.dxf, key)) for key in ("insert", "u_pixel", "v_pixel"))
            size = entity.dxf.image_size
            if size.x <= 0 or size.y <= 0:
                _fail()
            pixel_points = [(-1, -1), (size.x + 1, size.y + 1), *entity.boundary_path]
            points = [_point(origin + u * x + v * y) for x in (min(p[0] for p in pixel_points), max(p[0] for p in pixel_points))
                      for y in (min(p[1] for p in pixel_points), max(p[1] for p in pixel_points))]
        # Acute wide-polyline miters can extend arbitrarily beyond the control
        # bbox plus the width. Require a declared frame until complete join
        # geometry has a separately qualified envelope. No entity is rewritten.
        if width != 0:
            _fail()
        if not points:
            _fail()
        low = _vector((min(p[0] for p in points), min(p[1] for p in points), 0))
        high = _vector((max(p[0] for p in points), max(p[1] for p in points), 0))
        return DrawingBounds(low, high, "conservative_visible_planar_control_geometry"), 0

    result = _union(visit(entity, set())[0] for entity in document.modelspace())
    cancel_check()
    return result


def document_bounds(document, *, cancel_check=lambda: None, max_records=MAX_RECORDS):
    cancel_check()
    try:
        declared = declared_bounds(document)
        if declared is not None:
            return declared
        if max_records is None:
            max_records = MAX_RECORDS
        if isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= MAX_RECORDS:
            _fail()
        return _conservative_bounds(document, cancel_check, max_records)
    except DrawingCopyCancelled:
        raise
    except (DrawingCopyError, AttributeError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        error = DrawingCopyError("The drawing's bounds could not be safely established. "
            "Save a standard DXF copy in LibreCAD to refresh its bounds. "
            "The original was kept; open the PDF separately.")
        raise error from exc


def merged_bounds(base, incoming, scale):
    scale = _number(scale)
    if scale <= 0:
        _fail()
    if incoming is not None:
        incoming = DrawingBounds(_vector(Vec3(incoming.minimum) * scale),
                                 _vector(Vec3(incoming.maximum) * scale), incoming.provenance)
    result = _union([base, incoming], "union_of_input_frames_in_base_units")
    if result is None:
        _fail()
    return result

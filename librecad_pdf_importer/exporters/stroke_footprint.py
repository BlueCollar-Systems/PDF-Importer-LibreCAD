"""Editable analytic HATCH coverage for source-proven round ink strokes."""
from __future__ import annotations

import json
import math

from ezdxf.entities.boundary_paths import ArcEdge, LineEdge

APPID = 'BCS_SOURCE_STROKE_INK'


def _geometry(hatch):
    if (hatch.dxftype() != 'HATCH' or hatch.dxf.solid_fill != 1
            or hatch.dxf.associative != 0 or hatch.dxf.hatch_style != 0
            or hatch.dxf.pattern_name != 'SOLID'
            or tuple(hatch.dxf.elevation) != (0, 0, 0)
            or tuple(hatch.dxf.extrusion) != (0, 0, 1)
            or len(hatch.paths) != 1 or not hasattr(hatch.paths[0], 'edges')):
        raise RuntimeError('Source stroke ink lost its planar solid HATCH representation')
    result = []
    for edge in hatch.paths[0].edges:
        if isinstance(edge, LineEdge):
            result.append(['line', *edge.start, *edge.end])
        elif isinstance(edge, ArcEdge):
            result.append(['arc', *edge.center, edge.radius, edge.start_angle, edge.end_angle, bool(edge.ccw)])
        else:
            raise RuntimeError('Source stroke ink contains an unplanned boundary')
    return result


def add_capsule(doc, layout, proof, rgb, layer, offset_y, source_sha256):
    hatch = layout.add_hatch(color=256, dxfattribs={'layer': layer})
    hatch.dxf.true_color = (int(round(rgb[0]*255)) << 16 | int(round(rgb[1]*255)) << 8
                            | int(round(rgb[2]*255)))
    path = hatch.paths.add_edge_path(flags=1)
    for kind, *points in proof['edges_model']:
        mapped = [(float(x), float(y)+offset_y) for x, y in points]
        if kind == 'line':
            path.add_line(*mapped)
        else:
            start, middle, end = mapped
            center = ((start[0]+end[0])/2, (start[1]+end[1])/2)
            radius = math.dist(start, center)
            ccw = ((start[0]-center[0])*(middle[1]-center[1])
                   - (start[1]-center[1])*(middle[0]-center[0])) > 0
            angles = [math.degrees(math.atan2(p[1]-center[1], p[0]-center[0])) % 360 for p in (start, end)]
            # DXF stores clockwise arcs using swapped start/end angles; ezdxf
            # exposes them as the native values with the ccw flag unchanged.
            if not ccw:
                angles.reverse()
            path.add_arc(center, radius, *angles, ccw=ccw)
    if APPID not in doc.appids:
        doc.appids.add(APPID)
    record = {**proof, 'source_pdf_sha256': source_sha256, 'export_page_offset_y': offset_y,
              'hatch_handle': str(hatch.dxf.handle),
              'representation': 'editable analytic HATCH footprint; source centerline retained'}
    metadata = json.dumps(record, sort_keys=True, separators=(',', ':'))
    hatch.set_xdata(APPID, [(1000, metadata[i:i+240]) for i in range(0, len(metadata), 240)])
    expectation = dict(handle=str(hatch.dxf.handle), metadata=metadata, geometry=_geometry(hatch),
                       layer=layer, true_color=hatch.dxf.true_color)
    return record, expectation


def verify_capsules(doc, expectations):
    for expected in expectations:
        hatch = doc.entitydb.get(expected['handle'])
        if hatch is None:
            raise RuntimeError('Source stroke ink HATCH is missing after serialization')
        actual = _geometry(hatch)
        if len(actual) != len(expected['geometry']):
            raise RuntimeError('Source stroke ink boundary count changed')
        for row, wanted in zip(actual, expected['geometry'], strict=True):
            if (row[0] != wanted[0] or len(row) != len(wanted)
                    or any(not math.isclose(a, b, abs_tol=1e-9, rel_tol=0)
                           for a, b in zip(row[1:], wanted[1:], strict=True))):
                raise RuntimeError('Source stroke ink geometry changed')
        if (not hatch.has_xdata(APPID)
                or ''.join(tag.value for tag in hatch.get_xdata(APPID)) != expected['metadata']):
            raise RuntimeError('Source stroke ink identity changed')
        if (hatch.dxf.layer != expected['layer'] or hatch.dxf.true_color != expected['true_color']
                or hatch.dxf.invisible or hatch.dxf.transparency):
            raise RuntimeError('Source stroke ink color or visibility changed')
        layer = doc.layers.get(hatch.dxf.layer)
        if layer.is_off() or layer.is_frozen():
            raise RuntimeError('Source stroke ink layer is hidden')
        centerline = expected.get('centerline')
        line = doc.entitydb.get(centerline['handle']) if centerline else None
        if (line is None or line.dxftype() != 'LINE'
                or tuple(line.dxf.start) != tuple(centerline['start'])
                or tuple(line.dxf.end) != tuple(centerline['end'])
                or line.dxf.layer != expected['layer'] or line.dxf.invisible):
            raise RuntimeError('Source stroke ink retained centerline changed')


def bind_centerline(doc, line, record, expectation):
    """Bind the preserved editable line independently of its physical HATCH."""
    expected_points = [(x, y+record['export_page_offset_y'], 0)
                       for x, y in record['centerline_model']]
    actual = [tuple(line.dxf.start), tuple(line.dxf.end)]
    if (line.dxftype() != 'LINE' or any(not math.isclose(a, b, abs_tol=1e-9, rel_tol=0)
            for point, wanted in zip(actual, expected_points, strict=True)
            for a, b in zip(point, wanted, strict=True))):
        raise RuntimeError('Source stroke ink retained centerline was not delivered')
    expectation['centerline'] = dict(handle=str(line.dxf.handle), start=actual[0], end=actual[1])
    record['centerline_handle'] = str(line.dxf.handle)
    encoded = json.dumps(record, sort_keys=True, separators=(',', ':'))
    hatch = doc.entitydb[expectation['handle']]
    hatch.set_xdata(APPID, [(1000, encoded[i:i+240]) for i in range(0, len(encoded), 240)])
    expectation['metadata'] = encoded

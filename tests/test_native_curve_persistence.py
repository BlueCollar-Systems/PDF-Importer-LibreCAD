"""Sampled PDF paths must not turn into refitted LibreCAD splines on save."""
from __future__ import annotations

import math

import ezdxf
import pymupdf
import pytest

from dxf_builder import _add_polyline, build_dxf
from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import Primitive


def vertices(entity):
    if entity.dxftype() == "POLYLINE":
        assert entity.is_2d_polyline
        return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
    assert entity.dxftype() == "LWPOLYLINE"
    return list(entity.get_points("xy"))


@pytest.mark.parametrize("version", ["R12", "R2007", "R2018"])
@pytest.mark.parametrize("closed", [False, True])
def test_dense_angular_path_retains_its_actual_vertices(version, closed, tmp_path):
    # Dense hand-drawn vertices can have many turns without being Bezier controls.
    points = [(float(i), float((i % 3) * 7)) for i in range(19)]
    primitive = Primitive(id=1, type="polyline", points=points, closed=closed)
    doc = ezdxf.new(version)
    _add_polyline(doc.modelspace(), primitive, {"color": 2})
    output = tmp_path / "angular.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    entity = next(iter(reopened.modelspace()))
    assert len(reopened.modelspace()) == 1
    assert not list(reopened.modelspace().query("SPLINE"))
    assert vertices(entity) == points
    assert (entity.is_closed if version == "R12" else entity.closed) == closed
    assert entity.dxf.color == 2
    audit = reopened.audit()
    assert not audit.errors and not audit.fixes


def cubic_point(points, t):
    a, b, c, d = points
    s = 1 - t
    return (s**3*a[0] + 3*s*s*t*b[0] + 3*s*t*t*c[0] + t**3*d[0],
            s**3*a[1] + 3*s*s*t*b[1] + 3*s*t*t*c[1] + t**3*d[1])


def segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length2 = dx*dx+dy*dy
    t = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2))
    return math.dist(p, (a[0]+t*dx, a[1]+t*dy))


@pytest.mark.parametrize("writer", ["legacy", "adapter"])
@pytest.mark.parametrize("version", ["R12", "R2007", "R2018"])
@pytest.mark.parametrize("scale", [1.0, 2.5])
def test_real_pdf_cubic_keeps_source_approximation_without_refitting(writer, version, scale, tmp_path):
    controls = [(20, 150), (80, 20), (220, 280), (280, 150)]
    pdf = tmp_path / "cubic.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.draw_bezier(*(pymupdf.Point(*p) for p in controls))
        doc.save(pdf)
    extraction = extract_document(str(pdf), ExtractionOptions(
        scale=scale, import_text=False, import_images=False,
        detect_arcs=False, import_mode="vector",
    ))
    try:
        data = extraction.pages[0].page_data
        assert len(data.primitives) == 1
        primitive = data.primitives[0]
        admitted = list(primitive.points)
        assert 8 <= len(admitted) <= 33
        output = tmp_path / "cubic.dxf"
        if writer == "legacy":
            config = ImportConfig.auto()
            config.import_text = False
            doc, _, _ = build_dxf([data], config, version)
            doc.saveas(output)
        else:
            export_to_dxf(extraction, str(output), DxfExportOptions(
                include_text=False, include_images=False, dxf_version=version,
            ))
        reopened = ezdxf.readfile(output)
        entities = list(reopened.modelspace())
        assert len(entities) == 1
        assert not list(reopened.modelspace().query("SPLINE"))
        delivered = vertices(entities[0])
        assert len(delivered) == len(admitted)
        for original, final in zip(admitted, delivered):
            assert final == pytest.approx(original, abs=1e-10)
        # Independent source-curve checks: do not call the extractor's sampler.
        expected = [(x*25.4/72*scale, (300-y)*25.4/72*scale) for x, y in controls]
        assert delivered[0] == pytest.approx(expected[0], abs=1e-9)
        assert delivered[-1] == pytest.approx(expected[-1], abs=1e-9)
        worst = max(min(segment_distance(cubic_point(expected, i/512), a, b)
                        for a, b in zip(delivered, delivered[1:])) for i in range(513))
        assert worst < 0.10*scale, "This fixture must stay close to the analytic source cubic."
        audit = reopened.audit()
        assert not audit.errors and not audit.fixes
    finally:
        extraction.cleanup_temporary_assets()


def test_existing_proven_circle_promotion_is_not_replaced_by_polyline(tmp_path):
    pdf = tmp_path / "circle.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.draw_circle((150, 150), 60)
        doc.save(pdf)
    extraction = extract_document(str(pdf), ExtractionOptions(
        import_text=False, import_images=False, import_mode="vector",
    ))
    try:
        output = tmp_path / "circle.dxf"
        export_to_dxf(extraction, str(output), DxfExportOptions(include_text=False, include_images=False))
        reopened = ezdxf.readfile(output)
        assert list(reopened.modelspace().query("CIRCLE ARC"))
        assert not list(reopened.modelspace().query("SPLINE"))
    finally:
        extraction.cleanup_temporary_assets()

"""Source-bound cap geometry must survive extraction, transform and DXF save."""
import copy
import math

import ezdxf
from ezdxf.entities.boundary_paths import ArcEdge
import pymupdf
import pytest

from librecad_pdf_importer.core.document import ExtractionOptions, extract_document
from librecad_pdf_importer.core.stroke_footprint import bind_source_capsules
from librecad_pdf_importer.exporters import dxf_exporter as exporter


def source(tmp_path, end=(30.01, 40), rotation=0, stream=None):
    filename = tmp_path/'source.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=120)
        if stream is None:
            page.draw_line((30, 40), end, width=12, lineCap=1, color=(1, .5, .25))
        else:
            xref = doc.get_new_xref()
            doc.update_object(xref, '<<>>')
            doc.update_stream(xref, stream)
            page.set_contents(xref)
        page.set_rotation(rotation)
        doc.save(filename)
    return filename


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('flip_y', [False, True])
@pytest.mark.parametrize('end', [(30.01, 40), (33, 44), (30, 40)])
def test_real_source_exact_hatch_area_and_continuity(tmp_path, rotation, flip_y, end):
    pdf = source(tmp_path, end, rotation)
    extraction = extract_document(str(pdf), options=ExtractionOptions(import_mode='vector',
        scale=2, flip_y=flip_y, detect_arcs=False))
    try:
        page = extraction.pages[0]
        assert len(page.page_data.primitives) == 1
        assert len(page.source_capsules) == 1
        result = exporter.export_to_dxf(extraction, str(tmp_path/'out.dxf'), exporter.DxfExportOptions(
            include_text=False, include_images=False))
        assert len(result.source_capsules) == 1
        saved = ezdxf.readfile(result.output_path)
        hatch, = saved.modelspace().query('HATCH')
        line, = saved.modelspace().query('LINE')
        expected = page.source_capsules[0]
        assert list(line.dxf.start)[:2] == pytest.approx(expected['centerline_model'][0])
        assert list(line.dxf.end)[:2] == pytest.approx(expected['centerline_model'][1])
        edges = hatch.paths[0].edges
        area = 0
        for index, edge in enumerate(edges):
            a, b = edge.real_start_point, edge.real_end_point
            assert b.isclose(edges[(index+1) % len(edges)].real_start_point, abs_tol=1e-10)
            if isinstance(edge, ArcEdge):
                assert edge.radius == pytest.approx(12/2 * 25.4/72*2)
                t0, t1 = math.radians(edge.start_angle), math.radians(edge.end_angle)
                sweep = (t1-t0) % (2*math.pi)
                assert sweep == pytest.approx(math.pi)
                integral = edge.radius**2*sweep + edge.radius*(edge.center.x*(math.sin(t1)-math.sin(t0))
                           - edge.center.y*(math.cos(t1)-math.cos(t0)))
                area += integral * (1 if edge.ccw else -1)/2
            else:
                area += (a.x*b.y-b.x*a.y)/2
        exact_source_length = math.dist((30, 40), end)
        # MuPDF stores coordinates as float32; compare to its original source
        # endpoints, not the decimal used to generate the fixture.
        source_cap = expected['source_proof']['capsule']
        assert source_cap['length'] == pytest.approx(exact_source_length, abs=2e-6)
        assert abs(area) == pytest.approx((12*source_cap['length']+math.pi*36)*(25.4/72*2)**2, abs=1e-9)
    finally:
        extraction.cleanup_temporary_assets()


@pytest.mark.parametrize('change', ['point', 'width', 'color', 'duplicate'])
def test_source_capsule_cannot_bind_changed_model(tmp_path, change):
    pdf = source(tmp_path)
    extraction = extract_document(str(pdf), options=ExtractionOptions(import_mode='vector'))
    page_data = extraction.pages[0].page_data
    primitive = page_data.primitives[0]
    if change == 'point':
        primitive.points[1] = (99, 99)
    elif change == 'width':
        primitive.line_width *= 2
    elif change == 'color':
        primitive.source_stroke_color = (0, 0, 0)
    else:
        page_data.primitives.append(copy.deepcopy(primitive))
    with pymupdf.open(pdf) as doc:
        assert not bind_source_capsules(doc[0], page_data, extraction.pages[0].display_to_model)
    extraction.cleanup_temporary_assets()


@pytest.mark.parametrize('stream', [
    b'q 2 0 0 1 0 0 cm 12 w 1 J 1 .5 .25 RG 30 40 m 30.01 40 l S Q',
    b'q 29 79 2 2 re W n 12 w 1 J 1 .5 .25 RG 30 80 m 30.01 80 l S Q',
    b'q 12 w 0 J 1 .5 .25 RG 30 80 m 30.01 80 l S Q',
    b'q 12 w 1 J [1 1] 0 d 1 .5 .25 RG 30 80 m 30.01 80 l S Q',
])
def test_unsupported_caps_are_not_invented(tmp_path, stream):
    extraction = extract_document(str(source(tmp_path, stream=stream)), options=ExtractionOptions(import_mode='vector'))
    assert not extraction.pages[0].source_capsules
    extraction.cleanup_temporary_assets()


@pytest.mark.parametrize('change', ['radius', 'identity', 'color', 'layer', 'plane', 'centerline'])
def test_corrupt_saved_cap_is_not_published(tmp_path, monkeypatch, change):
    extraction = extract_document(str(source(tmp_path)), options=ExtractionOptions(import_mode='vector'))
    original = exporter._reopen_candidate_for_verification
    def corrupted(*args, **kwargs):
        doc, auditor = original(*args, **kwargs)
        hatch, = doc.modelspace().query('HATCH')
        if change == 'radius':
            next(edge for edge in hatch.paths[0].edges if isinstance(edge, ArcEdge)).radius *= 2
        elif change == 'identity':
            hatch.set_xdata('BCS_SOURCE_STROKE_INK', [(1000, '{}')])
        elif change == 'color':
            hatch.dxf.true_color = 0
        elif change == 'plane':
            hatch.dxf.elevation = (0, 0, 1)
        elif change == 'centerline':
            next(iter(doc.modelspace().query('LINE'))).dxf.end = (99, 99, 0)
        else:
            doc.layers.get(hatch.dxf.layer).freeze()
        return doc, auditor
    monkeypatch.setattr(exporter, '_reopen_candidate_for_verification', corrupted)
    output = tmp_path/'out.dxf'
    with pytest.raises(RuntimeError, match='Source stroke ink'):
        exporter.export_to_dxf(extraction, str(output), exporter.DxfExportOptions(include_text=False))
    assert not output.exists()
    extraction.cleanup_temporary_assets()


@pytest.mark.parametrize('change', ['model', 'source_file'])
def test_stale_source_binding_is_not_used_at_export(tmp_path, change):
    pdf = source(tmp_path)
    extraction = extract_document(str(pdf), options=ExtractionOptions(import_mode='vector'))
    if change == 'model':
        extraction.pages[0].page_data.primitives[0].points[0] = (3, 4)
    else:
        source(tmp_path, end=(32, 40))
    output = tmp_path/'out.dxf'
    with pytest.raises(RuntimeError, match='no longer matches'):
        exporter.export_to_dxf(extraction, str(output), exporter.DxfExportOptions(include_text=False))
    assert not output.exists()
    extraction.cleanup_temporary_assets()

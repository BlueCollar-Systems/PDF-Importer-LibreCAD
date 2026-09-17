import ezdxf
import pymupdf
import pytest

from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions, _add_compound_filled_paths, export_to_dxf,
)
from librecad_pdf_importer.importer import run_import


OUTER = [(0, 0), (20, 0), (20, 10), (0, 10), (0, 0)]
COUNTER = [(5, 2), (15, 2), (15, 8), (5, 8), (5, 2)]


def triangle_area(entity):
    a, b, c = entity.dxf.vtx0, entity.dxf.vtx1, entity.dxf.vtx2
    return abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))/2


def test_even_odd_clip_keeps_empty_counter_after_native_solid_reopen(tmp_path):
    doc = ezdxf.new('R2010')
    entities = _add_compound_filled_paths(doc.modelspace(), [OUTER, COUNTER], (0,0,0), {}, is_r12=False, even_odd=True)
    assert entities and all(entity.dxftype() == 'SOLID' for entity in entities)
    target = tmp_path/'compound.dxf'; doc.saveas(target)
    reopened = ezdxf.readfile(target)
    solids = list(reopened.modelspace().query('SOLID'))
    assert sum(map(triangle_area,solids)) == pytest.approx(200-60)
    assert all(vertex.z == 0 for entity in solids for vertex in entity.vertices())
    assert not list(reopened.modelspace().query('HATCH'))


def test_r12_counter_is_empty_space_in_native_solid_geometry():
    doc = ezdxf.new('R12')
    entities = _add_compound_filled_paths(doc.modelspace(), [OUTER, COUNTER], (0,0,0), {}, is_r12=True, even_odd=True)
    assert entities and all(entity.dxftype() == 'SOLID' for entity in entities)
    assert sum(map(triangle_area,entities)) == pytest.approx(200-60)
    assert all(vertex.z == 0 for entity in entities for vertex in entity.vertices())


def test_multi_contour_nonzero_is_not_silently_treated_as_even_odd():
    doc = ezdxf.new('R2010')
    with pytest.raises(RuntimeError, match='winding-aware'):
        _add_compound_filled_paths(doc.modelspace(), [OUTER, COUNTER], (0,0,0), {}, is_r12=False, even_odd=False)
    assert len(doc.modelspace()) == 0


@pytest.mark.parametrize('mode', ['auto', 'vector'])
def test_real_pdf_clip_survives_cached_extraction_and_two_page_export(tmp_path, mode):
    source = tmp_path/'clip-source.pdf'
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=100, height=100)
        page.draw_rect(page.rect)
        doc.update_stream(page.get_contents()[0],
            b'q 10 10 80 80 re 30 30 40 40 re W* n 0 g 0 0 100 100 re f Q')
    doc.save(source); doc.close()
    run = run_import(str(source), mode=mode, overrides={'import_text':False})
    output = tmp_path/'clip.dxf'
    export_to_dxf(run.extraction, str(output), DxfExportOptions(include_text=False, include_images=False))
    reopened = ezdxf.readfile(output)
    solids = list(reopened.modelspace().query('SOLID'))
    assert solids
    assert sum(map(triangle_area,solids)) == pytest.approx(2*(80**2-40**2)*(25.4/72)**2)
    assert all(len(page.page_data.primitives) == 2 for page in run.extraction.pages)
    assert all(primitive.clip_fill_group_id for page in run.extraction.pages for primitive in page.page_data.primitives)
    assert min(vertex.y for solid in solids for vertex in solid.vertices()) < 0


def test_white_compound_knockout_is_not_inverted_to_black():
    doc = ezdxf.new('R2010')
    entities = _add_compound_filled_paths(doc.modelspace(), [OUTER, COUNTER], (1,1,1), {}, is_r12=False, even_odd=True)
    assert entities and all(entity.dxf.true_color == 0xFEFEFE for entity in entities)
    assert all(entity.dxf.color != 7 for entity in entities)


def test_overlapping_bounding_boxes_do_not_make_disjoint_shapes_into_counters():
    concave = [(0,0),(10,0),(10,2),(2,2),(2,10),(0,10)]
    separate = [(4,4),(8,4),(8,8),(4,8)]
    doc = ezdxf.new('R2010')
    entities = _add_compound_filled_paths(doc.modelspace(), [concave,separate], (0,0,0), {}, is_r12=False, even_odd=True)
    assert sum(map(triangle_area,entities)) == pytest.approx(36+16)


def test_nested_counter_island_uses_actual_containment_and_even_odd_depth():
    island = [(7,4),(13,4),(13,6),(7,6)]
    doc = ezdxf.new('R2010')
    entities = _add_compound_filled_paths(doc.modelspace(), [COUNTER,island,OUTER], (0,0,0), {}, is_r12=False, even_odd=True)
    assert sum(map(triangle_area,entities)) == pytest.approx(200-60+12)

from types import SimpleNamespace
import pytest

from pdfcadcore.page_paint_bounds import retain_visible_paints, page_visible_drawings


@pytest.mark.parametrize('kind,log', [('f',[('fill-path',(-8,1,-2,2))]),
    ('s',[('stroke-path',(-9,0,-1,3))]),
    ('fs',[('fill-path',(-8,1,-2,2)),('stroke-path',(-9,0,-1,3))])])
def test_renderer_proves_wholly_offpage_paint(kind,log):
    outside={'type':kind,'seqno':0,'rect':(-8,1,-2,2)}
    inside={'type':'s','seqno':40,'rect':(1,1,2,2)}
    structural={'type':'clip','level':0}
    assert retain_visible_paints([structural,outside,inside],(0,0,10,10),log)==[structural,inside]


@pytest.mark.parametrize('log', [[('stroke-path',(-9,0,1,3))], [],
    [('fill-path',(-9,0,-1,3))], [('stroke-path',(float('nan'),0,-1,3))]])
def test_wide_stroke_or_missing_proof_must_be_retained(log):
    row={'type':'s','seqno':0,'rect':(-8,1,-2,2)}
    assert retain_visible_paints([row],(0,0,10,10),log)==[row]


def test_partial_path_and_boundary_touch_are_unchanged():
    rows=[{'type':'s','seqno':0,'rect':(-2,1,2,2)}, {'type':'f','seqno':1,'rect':(-2,1,0,2)}]
    assert retain_visible_paints(rows,(0,0,10,10),[('stroke-path',(-3,0,3,3)),('fill-path',(-2,1,0,2))])==rows


def test_no_additional_renderer_inventory_for_inpage_drawings():
    rows=[{'type':'s','seqno':0,'rect':(1,1,2,2)}]
    page=SimpleNamespace(rect=(0,0,10,10),get_bboxlog=lambda:pytest.fail('unexpected inventory'))
    assert page_visible_drawings(page,rows) is rows


def test_rotated_native_page_retains_same_visible_source_geometry():
    import fitz
    pdf=fitz.open();page=pdf.new_page(width=200,height=100)
    page.draw_line((10,10),(50,50));page.draw_line((-100,10),(-80,10))
    for rotation in (0,90,180,270):
        page.set_rotation(rotation)
        rows=page.get_drawings(extended=True)
        kept=page_visible_drawings(page,rows)
        assert len(kept)==1
        assert tuple(kept[0]['rect'])==(10.,10.,50.,50.)

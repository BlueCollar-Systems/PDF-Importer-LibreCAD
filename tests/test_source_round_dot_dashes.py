"""Retain real round-dot dash ink instead of continuous native linetype guesses."""
from copy import deepcopy
import math

import ezdxf
import pymupdf as fitz
import pytest

from pdfcadcore.primitive_extractor import extract_page
from librecad_pdf_importer.core.source_line_dashes import (
    bind_source_line_dashes, round_dot_dash_intervals,
)
from librecad_pdf_importer.exporters.dxf_exporter import (
    _add_source_dash_block, _verify_serialized_source_dash_blocks,
)


def source(*, rotation=0, cap=1, morph=None, clip=False, opacity=1):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.draw_line((20, 50), (120, 50), dashes='[20 3 0 3] 0',
                   width=2, lineCap=cap, morph=morph, stroke_opacity=opacity)
    if clip:
        # Original clip intersects the round ink, so this narrow helper must
        # keep it unqualified, rather than drawing the full uncut circle.
        xref = page.get_contents()[0]
        doc.update_stream(xref, b'q 19 149.5 102 1 re W n\n' + doc.xref_stream(xref) + b'\nQ')
    page.set_rotation(rotation)
    return doc, page


def test_literal_round_dots_keep_phase_and_zero_ink_length():
    segments, dots = round_dot_dash_intervals(80, (20, 3, 0, 3), 0)
    assert segments == ((0, 20), (26, 46), (52, 72), (78, 80))
    assert dots == (23, 49, 75)
    assert round_dot_dash_intervals(30, (20, 3, 0, 3), 23) == (((3, 23), (29, 30)), (0, 26))
    assert round_dot_dash_intervals(5, (0, 4), 0) == ((), (0, 4))


@pytest.mark.parametrize('pattern', [(0, 0), (2, 0), (0, 3, 2), (-1, 3), (float('nan'), 3)])
def test_ambiguous_or_empty_dot_patterns_rejected(pattern):
    with pytest.raises(ValueError):
        round_dot_dash_intervals(80, pattern, 0)


def test_dense_dots_fail_budget_without_dropping_ink():
    with pytest.raises(ValueError, match='budget'):
        round_dot_dash_intervals(80, (0, .001), 0, limit=20)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_round_dots_bind_to_original_width_position_and_rotation(rotation):
    doc, page = source(rotation=rotation)
    data = extract_page(page, 1, scale=2)
    proof = next(iter(bind_source_line_dashes(page, data, 2, True).values()))
    assert len(proof.dots_model) == 3
    assert proof.dot_radius_model == pytest.approx(2*25.4/72)
    assert math.dist(proof.dots_model[0], proof.dots_model[1]) == pytest.approx(26*2*25.4/72)
    assert len(proof.segments_model) == 4
    doc.close()


@pytest.mark.parametrize('options', [
    {'cap': 0}, {'cap': 2}, {'opacity': .5}, {'clip': True},
    {'morph': (fitz.Point(0, 0), fitz.Matrix(2, 0, .5, 1, 0, 0))},
])
def test_dot_support_does_not_fabricate_caps_clips_or_ellipses(options):
    doc, page = source(**options)
    assert not bind_source_line_dashes(page, extract_page(page, 1), 1, True)
    doc.close()


def test_partial_visible_centerline_is_not_full_round_dot_proof():
    doc, page = source()
    data = extract_page(page, 1)
    data.primitives[0].points[0] = tuple((a+b)/2 for a, b in zip(*data.primitives[0].points, strict=True))
    assert not bind_source_line_dashes(page, data, 1, True)
    doc.close()


def test_original_knockout_group_is_not_hidden_by_flattened_renderer_flags():
    doc, page = source()
    doc.xref_set_key(page.xref, 'Group', '<< /S /Transparency /K true /I true >>')
    page = doc.reload_page(page)
    assert not bind_source_line_dashes(page, extract_page(page, 1), 1, True)
    doc.close()


@pytest.mark.parametrize('mutation', [None, 'radius', 'center', 'count', 'fill', 'hidden', 'layer', 'identity'])
def test_round_dot_native_hatches_survive_readback_and_reject_mutation(tmp_path, mutation):
    source_doc, page = source()
    data = extract_page(page, 1)
    proof = next(iter(bind_source_line_dashes(page, data, 1, True).values()))
    doc = ezdxf.new('R2018')
    expected = _add_source_dash_block(doc, doc.modelspace(), data.primitives[0], proof,
                                     {'layer': '0', 'color': 256, 'true_color': 0}, 17)
    dots = list(doc.blocks[expected['name']].query('HATCH'))
    assert len(dots) == 3 and len(list(doc.blocks[expected['name']].query('LINE'))) == 4
    if mutation == 'radius': dots[0].paths[0].edges[0].radius *= 2
    elif mutation == 'center': dots[0].paths[0].edges[0].center = (999, 999)
    elif mutation == 'count': doc.blocks[expected['name']].delete_entity(dots[0])
    elif mutation == 'fill': dots[0].dxf.solid_fill = 0
    elif mutation == 'hidden': dots[0].dxf.invisible = 1
    elif mutation == 'layer': doc.layers.get('0').off()
    elif mutation == 'identity': expected['dots'][0]['handle'] = 'FFFF'
    target = tmp_path / 'dots.dxf'
    doc.saveas(target)
    actual = ezdxf.readfile(target)
    if mutation:
        with pytest.raises(RuntimeError):
            _verify_serialized_source_dash_blocks(actual, [deepcopy(expected)])
    else:
        _verify_serialized_source_dash_blocks(actual, [deepcopy(expected)])
    source_doc.close()

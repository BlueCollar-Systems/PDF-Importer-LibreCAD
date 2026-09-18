"""A special alpha delivery requires affirmative original paint evidence."""
import copy

import pymupdf
import pytest

from librecad_pdf_importer.core.final_rect_paint import (
    _normal_blend_proof,
    _object_tokens,
    bind_final_rect_paints,
    final_svg_rectangles,
)
from pdfcadcore.primitive_extractor import extract_page


@pytest.fixture
def drawing():
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=150)
        page.insert_text((10, 30), 'Original text below alpha')
        page.draw_rect((10, 10, 90, 35), fill=(0, 1, 1), color=(0, 1, 1),
                       width=2, fill_opacity=.3)
        yield doc, page


def test_complete_original_and_model_binding(drawing):
    _, page = drawing
    data = extract_page(page, 1, detect_arcs=False)
    result = bind_final_rect_paints(page, data)
    assert len(result) == 1
    row = result[0]
    primitive = next(p for p in data.primitives if p.id == row['primitive_id'])
    assert row['source_bbox_pdf'] == [10, 10, 90, 35]
    assert row['model_bounds'] == pytest.approx([min(p[0] for p in primitive.points),
        min(p[1] for p in primitive.points), max(p[0] for p in primitive.points), max(p[1] for p in primitive.points)])
    assert row['fill_rgb'] == [0, 1, 1]
    assert row['fill_opacity'] == pytest.approx(.3)
    assert row['stroke_width_pdf'] == 2
    assert row['stroke_width_model'] == primitive.line_width
    assert row['proof']['normal_blend']['blend_mode'] == 'Normal'


@pytest.mark.parametrize('declaration', [
    '/BM /Multiply', '/B#4d /Multiply', '/BM [/Normal /Multiply]',
    '/SMask /None', '/S#4dask << /S /Luminosity >>',
    '/Group << /S /Transparency >>', '/Gr#6fup << /S /Transparency >>',
    '/TR /Unsupported',
])
def test_non_normal_mask_or_group_is_unqualified_even_in_nested_form(drawing, declaration):
    doc, page = drawing
    resource = doc.get_new_xref()
    doc.update_object(resource, '<< /Type /XObject /Subtype /Form ' + declaration + ' >>')
    doc.xref_set_key(page.xref, 'PrivateProofResource', f'{resource} 0 R')
    assert _normal_blend_proof(page) is None
    assert bind_final_rect_paints(page, extract_page(page, 1, detect_arcs=False)) == []


def test_explicit_normal_and_strings_are_safe(drawing):
    doc, page = drawing
    doc.xref_set_key(page.xref, 'PrivateProof', '<< /BM /Normal /TR /Identity /Note (/SMask /Group 99 0 R) >>')
    assert _normal_blend_proof(page)['blend_mode'] == 'Normal'
    assert len(bind_final_rect_paints(page, extract_page(page, 1, detect_arcs=False))) == 1


def test_source_lexer_ignores_strings_comments_and_decodes_names():
    tokens = _object_tokens('<< /Name (abc \\( /BM /Multiply) /Hex <2f534d61736b> % /Group\n /B#4d /Normal /Ref 5 0 R >>')
    assert '/Group' not in tokens and '/Multiply' not in tokens
    assert tokens.count('/BM') == 1 and tokens[-4:] == ['5', '0', 'R', '>>']


def test_later_text_or_image_blocks_suffix(drawing):
    _, page = drawing
    page.insert_text((10, 60), 'Later text')
    assert bind_final_rect_paints(page, extract_page(page, 1, detect_arcs=False)) == []


def test_no_final_candidate_does_not_scan_document_resources(drawing, monkeypatch):
    import librecad_pdf_importer.core.final_rect_paint as module
    _, page = drawing
    page.insert_text((10, 60), 'Later text')
    def unexpected(_page):
        raise AssertionError('Resource scan is unnecessary without eligible final paint')
    monkeypatch.setattr(module, '_normal_blend_proof', unexpected)
    assert bind_final_rect_paints(page, extract_page(page, 1, detect_arcs=False)) == []


@pytest.mark.parametrize('mutation', ['duplicate', 'clipped', 'dash', 'level', 'opaque', 'wrong_raw_alpha', 'wrong_raw_rgb'])
def test_ambiguous_or_unsupported_primitive_rejected(drawing, mutation):
    _, page = drawing
    data = extract_page(page, 1, detect_arcs=False)
    primitive = next(p for p in data.primitives if p.fill_opacity < 1)
    if mutation == 'duplicate':
        data.primitives.append(copy.deepcopy(primitive))
    elif mutation == 'clipped':
        primitive.clip_fill_group_id = 'clip'
    elif mutation == 'dash':
        primitive.dash_pattern = [1, 2]
    elif mutation == 'level':
        data._source_drawings[-1]['level'] = 1
    elif mutation == 'wrong_raw_alpha':
        primitive.fill_opacity = .2
    elif mutation == 'wrong_raw_rgb':
        primitive.source_fill_color = (1, 0, 0)
    else:
        primitive.fill_opacity = 1
    assert bind_final_rect_paints(page, data) == []


def test_renderer_proof_rejects_unknown_clip_width_and_miter(drawing):
    _, page = drawing
    svg, rows = page.get_svg_image(), page.get_drawings()
    assert final_svg_rectangles(svg, rows)
    for bad in [svg.replace('stroke-miterlimit="10"', ''),
                svg.replace('stroke-miterlimit="10"', 'stroke-miterlimit="1"'),
                svg.replace('stroke-width="2"', 'stroke-width="3"'),
                svg.replace('<path ', '<path clip-path="url(#unknown)" ')]:
        assert not final_svg_rectangles(bad, rows)

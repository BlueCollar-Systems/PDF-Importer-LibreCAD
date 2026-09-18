from types import SimpleNamespace

import pymupdf as fitz
import pytest

from librecad_pdf_importer.core.document import _inline_image_blocks, _inline_delivery_image_bytes, _InlineImageDecodeIncomplete


def source_pair():
    pixels = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 2), False)
    pixels.clear_with(0)
    mask = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 3, 2), False)
    mask.clear_with(0)
    mask.set_pixel(1, 0, (255,))
    common = dict(width=3, height=2, transform=(30., 0., 0., 20., 70., 40.), bbox=(70,40,100,60))
    info = dict(common, number=77, xref=0, digest=pixels.digest)
    block = dict(common, number=76, type=1, image=pixels.tobytes("png"), mask=mask.tobytes("png"))
    return info, block


def test_annotation_image_numbers_may_differ_but_pixels_transform_and_mask_survive():
    info, block = source_pair()
    page = SimpleNamespace(get_image_info=lambda **k:[info], get_text=lambda *a:{"blocks":[block]})
    pairs = _inline_image_blocks(page)
    assert pairs == [(info,block)]
    result = fitz.Pixmap(_inline_delivery_image_bytes(block))
    assert result.alpha == 1 and (result.width,result.height)==(3,2)
    assert [result.pixel(x,y)[-1] for y in range(2) for x in range(3)] == [0,255,0,0,0,0]


@pytest.mark.parametrize("fault", ["pixels", "transform", "duplicate"])
def test_numbers_alone_cannot_authorize_an_unmatched_image(fault):
    info, block = source_pair();block["number"]=info["number"]
    infos=[info]
    if fault=="pixels":info["digest"]=b"x"*16
    elif fault=="transform":info["transform"]=(30.,0.,0.,20.,71.,40.)
    else:infos.append(dict(info))
    page=SimpleNamespace(get_image_info=lambda **k:infos,get_text=lambda *a:{"blocks":[block]})
    with pytest.raises(_InlineImageDecodeIncomplete):_inline_image_blocks(page)


def test_matching_xobject_occurrence_cannot_steal_inline_mask():
    info, block = source_pair()
    prior = dict(info, xref=42, number=75)
    prior_block = dict(block, number=74)
    prior_block.pop("mask")
    page = SimpleNamespace(get_image_info=lambda **k:[prior, info],
        get_text=lambda *a:{"blocks":[prior_block, block]})
    assert _inline_image_blocks(page) == [(info, block)]

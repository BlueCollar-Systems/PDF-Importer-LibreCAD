"""Opening DXF view frames the sheet face-on."""
from __future__ import annotations

import ezdxf

from dxf_builder import _apply_dxf_framing
from pdfcadcore.primitives import PageData


def _active_vport(doc):
    found = [vp for vp in doc.viewports if vp.dxf.name == "*Active"]
    assert len(found) == 1
    return found[0]


def test_landscape_sheet_viewport_contains_the_page_and_records_its_aspect():
    page = PageData(page_number=1, width=431.8, height=279.4)  # 17 x 11 in
    doc = ezdxf.new()
    _apply_dxf_framing(doc, [page])
    vport = _active_vport(doc)
    # Longer side plus margin, so a square window still contains the print.
    assert vport.dxf.height >= max(page.width, page.height)
    # Not left at the default square aspect.
    assert vport.dxf.aspect_ratio > 1.2
    center = vport.dxf.center
    assert abs(center.x - page.width / 2.0) < 5.0
    assert abs(center.y - page.height / 2.0) < 5.0
    extmin = doc.header["$EXTMIN"]
    extmax = doc.header["$EXTMAX"]
    assert extmax[0] - extmin[0] >= page.width
    assert extmax[1] - extmin[1] >= page.height


def test_portrait_sheet_aspect_is_narrower_than_square():
    page = PageData(page_number=1, width=215.9, height=279.4)
    doc = ezdxf.new()
    _apply_dxf_framing(doc, [page])
    vport = _active_vport(doc)
    assert vport.dxf.aspect_ratio < 0.9
    assert vport.dxf.height >= page.height

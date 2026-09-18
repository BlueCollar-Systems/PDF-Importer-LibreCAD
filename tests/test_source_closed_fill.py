import pytest
from types import SimpleNamespace
from pdfcadcore import primitive_extractor as pe
from pdfcadcore.fitz_loader import import_fitz

@pytest.mark.parametrize("fill,closing_gap,expected", [
    ((0, 0, 0), 0, "closed_loop"),
    ((0, 0, 0), .1, "polyline"),
    (None, 0, "polyline"),
])
def test_source_repeated_endpoint_is_closed_fill_without_close_operator(monkeypatch, fill, closing_gap, expected):
    fitz = import_fitz()
    points = [fitz.Point(*p) for p in ((10,10),(10,20),(15,20),(15,10),(10+closing_gap,10))]
    row = dict(type="f" if fill else "s", closePath=False, fill=fill,
               color=None if fill else (0,0,0), seqno=1,
               rect=fitz.Rect(10,10,15,20),
               items=[("l",a,b) for a,b in zip(points[:-1],points[1:], strict=True)])
    monkeypatch.setattr(pe, "_extract_text", lambda *args, **kwargs: [])
    result = pe.extract_page(SimpleNamespace(rect=fitz.Rect(0,0,100,100)),1,
                             detect_arcs=False,drawings=[row])
    primitive=result.primitives[0]
    assert primitive.type == expected
    assert primitive.closed == (expected=="closed_loop")
    assert len(primitive.points)==5
    assert primitive.fill_color==fill
    assert primitive.source_draw_order==1


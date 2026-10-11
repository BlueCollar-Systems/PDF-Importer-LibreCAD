"""White source paint remains white enough to mask ink and show on dark panels.

Exact white uses RGB254 to avoid LibreCAD's print inversion. Pale tints and
composited washes retain their source channels rather than becoming black.
"""
from __future__ import annotations

from ezdxf.colors import int2rgb

from librecad_pdf_importer.exporters import dxf_exporter as X
import dxf_builder as B


def _tc(rgb):
    attribs = {}
    X._apply_color(attribs, rgb)
    return int2rgb(attribs["true_color"])


def test_white_uses_fixed_light_paint_and_near_white_keeps_source():
    assert _tc((1.0, 1.0, 1.0)) == (254, 254, 254)
    assert _tc((0.99, 0.99, 0.99)) == (252, 252, 252)
    assert int2rgb(B._true_color_int(1.0, 1.0, 1.0)) == (254, 254, 254)


def test_pale_tints_and_composited_washes_keep_their_colour():
    assert _tc((0.95, 0.95, 0.95)) == (242, 242, 242)   # 5 % black wash
    assert _tc((1.0, 1.0, 0.7)) == (255, 255, 178)      # 30 % yellow highlight
    assert _tc((0.6, 0.6, 0.6)) == (153, 153, 153)      # 40 % black separator bar
    assert int2rgb(B._true_color_int(1.0, 1.0, 0.7)) == (255, 255, 178)


def test_white_knockout_mask_layer_is_visible_noninverting_source_paint():
    import ezdxf
    doc = ezdxf.new()
    X._ensure_layer(doc, "page_0001$0$P001_RGB_255_255_255", (1.0, 1.0, 1.0))
    layer = doc.layers.get("page_0001$0$P001_RGB_255_255_255")
    assert layer.is_off() is False
    assert int2rgb(layer.dxf.true_color) == (254, 254, 254)

    # Standard non-white layers should remain ON by default
    X._ensure_layer(doc, "page_0001$0$P001_RGB_000_000_000", (0.0, 0.0, 0.0))
    normal_layer = doc.layers.get("page_0001$0$P001_RGB_000_000_000")
    assert normal_layer.is_off() is False

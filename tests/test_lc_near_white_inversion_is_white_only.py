"""LibreCAD inverts white ink to black (white-on-white would be invisible on its default
background). That inversion must be limited to genuinely white ink: pdfcadcore now
composites constant alpha against the page, so a 5 % black wash arrives as 242 grey and
a 30 % yellow highlight as (255, 255, 178) -- a luminance threshold turned those solid
black, the opposite of what the PDF viewer shows."""
from __future__ import annotations

from ezdxf.colors import int2rgb

from librecad_pdf_importer.exporters import dxf_exporter as X
import dxf_builder as B


def _tc(rgb):
    attribs = {}
    X._apply_color(attribs, rgb)
    return int2rgb(attribs["true_color"])


def test_pure_and_near_white_ink_still_inverts_to_black():
    assert _tc((1.0, 1.0, 1.0)) == (0, 0, 0)
    assert _tc((0.99, 0.99, 0.99)) == (0, 0, 0)
    assert int2rgb(B._true_color_int(1.0, 1.0, 1.0)) == (0, 0, 0)


def test_pale_tints_and_composited_washes_keep_their_colour():
    assert _tc((0.95, 0.95, 0.95)) == (242, 242, 242)   # 5 % black wash
    assert _tc((1.0, 1.0, 0.7)) == (255, 255, 178)      # 30 % yellow highlight
    assert _tc((0.6, 0.6, 0.6)) == (153, 153, 153)      # 40 % black separator bar
    assert int2rgb(B._true_color_int(1.0, 1.0, 0.7)) == (255, 255, 178)

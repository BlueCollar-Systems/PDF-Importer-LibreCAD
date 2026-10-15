"""Exact per-span source pipe intervals; no native application is launched."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import math
from pathlib import Path

import ezdxf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
import pytest

import dxf_text_builder as builder
from test_librecad_native_text_weight import _source


def _pipe_font(path, *, contour="rectangle"):
    order = [".notdef", "space", "bar", "H", "P", "A"]
    strings = {}
    for name in order:
        pen = T2CharStringPen(600, None)
        if name == "bar":
            pen.moveTo((275, -250))
            pen.lineTo((326, -250))
            if contour == "triangle":
                pen.lineTo((300, 825))
            elif contour == "curve":
                pen.curveTo((500, -100), (500, 700), (326, 825))
                pen.lineTo((275, 825))
            else:
                pen.lineTo((326, 825))
                pen.lineTo((275, 825))
            pen.closePath()
            if contour == "multiple":
                pen.moveTo((400, 0))
                pen.lineTo((420, 0))
                pen.lineTo((420, 200))
                pen.closePath()
        elif name != "space":
            pen.moveTo((0, 0))
            pen.lineTo((500, 0))
            pen.lineTo((500, 700))
            pen.lineTo((0, 700))
            pen.closePath()
        strings[name] = pen.getCharString()
    font = FontBuilder(1000, isTTF=False)
    font.setupGlyphOrder(order)
    font.setupCharacterMap({32: "space", 124: "bar", 72: "H", 80: "P", 65: "A"})
    font.setupHorizontalMetrics({name: (600, 0) for name in order})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupNameTable({"familyName": "Fictional Pipe", "styleName": "Regular",
                         "psName": "FictionalPipe", "fullName": "Fictional Pipe"})
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                  usWinDescent=200, sCapHeight=700)
    font.setupPost()
    font.setupCFF("FictionalPipe", {"FullName": "Fictional Pipe", "FamilyName": "Fictional Pipe",
                                  "Weight": "Regular", "FontMatrix": [.001, 0, 0, .001, 0, 0]},
                  strings, {"StdVW": 51, "StdHW": 52})
    font.save(path)
    font.font.close()
    return path


@pytest.fixture
def native_fonts(tmp_path, monkeypatch):
    from test_librecad_native_linear_font import ROMANS, UNICODE

    installation = tmp_path / "selected-native"
    installation.mkdir()
    executable = installation / "LibreCAD.exe"
    executable.write_bytes(b"fictional installation; never executed")
    fonts = installation / "resources/fonts"
    fonts.mkdir(parents=True)
    unicode = fonts / "unicode.lff"
    unicode.write_text(UNICODE + "[007C]\n0,-3;0,9\n\n", encoding="utf-8")
    (fonts / "romans.lff").write_text(ROMANS + "[007C]\n0,-3;0,9\n\n", encoding="utf-8")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(unicode))
    builder.reset_text_styles()
    return executable, unicode


def _case(tmp_path, native_fonts, *, text=" | | ", rotation=0.0, contour="rectangle"):
    path = _pipe_font(tmp_path / "source.otf", contour=contour)
    item, resolution = _source(path, text=text, rotation=rotation)
    resolution = replace(resolution, source_cap_height_ratio=.7)
    selected = builder._resolve_librecad_unicode_lff(str(native_fonts[0]), fresh=True)
    return item, resolution, selected, 2.45


@pytest.mark.parametrize("rotation", [0.0, 37.0, 90.0, 180.0])
def test_bound_source_rectangle_detects_native_interval_loss_without_cross_item_claim(
    tmp_path, native_fonts, rotation,
):
    item, resolution, selected, height = _case(tmp_path, native_fonts, rotation=rotation)
    before = Path(resolution.filename).read_bytes()
    proof = builder._source_vertical_pipe_rule_loss(item, resolution, selected, height)
    assert proof is not None
    assert proof["rule"] == "exact_source_rectangular_vertical_pipe_interval_v1"
    assert proof["font_sha256"] == hashlib.sha256(before).hexdigest()
    assert proof["source_glyph_name"] == "bar"
    assert proof["pipe_glyph_count"] == proof["shortened_pipe_count"] == 2
    assert proof["max_interval_loss"] > 0
    assert proof["cross_item_connectivity_verified"] is False
    assert len(proof["intervals"]) == 2
    for row in proof["intervals"]:
        assert row["source_interval"] == pytest.approx([-.875, 2.8875], abs=1e-12)
        assert row["native_interval"] == pytest.approx([-3 * height / 9, height], abs=1e-12)
        assert row["loss_below"] == pytest.approx(.875 - 3 * height / 9, abs=1e-12)
        assert row["loss_above"] == pytest.approx(2.8875 - height, abs=1e-12)
    assert proof["max_interval_loss"] == pytest.approx(.4375, abs=1e-12)
    assert item.text == " | | " and Path(resolution.filename).read_bytes() == before


def test_native_vertical_range_covering_actual_source_does_not_force_outlines(tmp_path, native_fonts):
    item, resolution, _selected, height = _case(tmp_path, native_fonts)
    executable, unicode = native_fonts
    unicode.write_text(unicode.read_text().replace("0,-3;0,9", "0,-8;0,16"), encoding="utf-8")
    adequate = builder._resolve_librecad_unicode_lff(str(executable), fresh=True)
    assert builder._source_vertical_pipe_rule_loss(item, resolution, adequate, height) is None


def test_stale_native_font_bytes_or_unqualified_curved_pipe_cannot_certify_loss(tmp_path, native_fonts):
    item, resolution, selected, height = _case(tmp_path, native_fonts)
    executable, unicode = native_fonts
    assert builder._source_vertical_pipe_rule_loss(item, resolution, selected, height) is not None
    unicode.write_text(unicode.read_text().replace("0,-3;0,9", "0,-3;0,9,A1"), encoding="utf-8")
    assert builder._source_vertical_pipe_rule_loss(item, resolution, selected, height) is None
    curved = builder._resolve_librecad_unicode_lff(str(executable), fresh=True)
    assert builder._source_vertical_pipe_rule_loss(item, resolution, curved, height) is None


@pytest.mark.parametrize("text", ["", "   ", "P|A", "|P|", "PA"])
def test_words_mixed_content_and_blank_spans_are_not_semantic_rule_guesses(tmp_path, native_fonts, text):
    item, resolution, selected, height = _case(tmp_path, native_fonts, text=text)
    assert builder._source_vertical_pipe_rule_loss(item, resolution, selected, height) is None


@pytest.mark.parametrize("contour", ["triangle", "curve", "multiple"])
def test_unproved_nonrectangular_or_multiple_source_contours_are_unknown(tmp_path, native_fonts, contour):
    item, resolution, selected, height = _case(tmp_path, native_fonts, contour=contour)
    assert builder._source_vertical_pipe_rule_loss(item, resolution, selected, height) is None


@pytest.mark.parametrize("fault", ["missing-font", "changed-font", "invalid-font", "gid", "binding", "layout", "baseline", "shear", "nonfinite", "height"])
def test_missing_or_changed_source_authority_and_invalid_frames_cannot_certify_loss(
    tmp_path, native_fonts, fault,
):
    item, resolution, selected, height = _case(tmp_path, native_fonts)
    path = Path(resolution.filename)
    if fault == "missing-font":
        path.unlink()
    elif fault == "changed-font":
        path.write_bytes(path.read_bytes() + b"changed exact source bytes")
    elif fault == "invalid-font":
        path.write_bytes(b"not an exact font program")
        resolution = replace(resolution, asset_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    elif fault == "layout":
        item = replace(item, source_char_layout=())
    elif fault == "height":
        height = math.nan
    else:
        layout = list(item.source_char_layout)
        index = item.text.index("|")
        char = layout[index]
        if fault == "gid": char = replace(char, glyph_id=99999)
        elif fault == "binding": char = replace(char, source_font_binding_verified=False)
        elif fault == "baseline": char = replace(char, target_origin=(999, 999))
        elif fault == "shear":
            char = replace(char, target_quad=tuple((x + .2 * y, y) for x, y in char.target_quad),
                           target_origin=(char.target_origin[0] + .2 * char.target_origin[1], char.target_origin[1]))
        else: char = replace(char, target_quad=((math.nan, 0), *char.target_quad[1:]))
        layout[index] = char
        item = replace(item, source_char_layout=tuple(layout))
    assert builder._source_vertical_pipe_rule_loss(item, resolution, selected, height) is None


@pytest.mark.parametrize("adequate,content,outlined", [
    (False, "  | |  ", True), (True, "  | |  ", False), (False, " P|A ", False),
])
def test_actual_courier_PDF_pipe_interval_choice_retains_complete_literal_and_source(
    tmp_path, native_fonts, monkeypatch, adequate, content, outlined,
):
    import pymupdf
    import dxf_import_engine as engine
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    from pdfcadcore.import_config import ImportConfig

    executable, unicode = native_fonts
    if adequate:
        unicode.write_text(unicode.read_text().replace("0,-3;0,9", "0,-8;0,16"), encoding="utf-8")
    source = tmp_path / "fictional-pipe-rules.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_text((72, 90), content, fontname="cour", fontsize=12)
        pdf.save(source)
    original = source.read_bytes()
    verifier = exporter._verify_serialized_text_deliveries
    calls = []

    def capture(doc, deliveries, **kwargs):
        verifier(doc, deliveries, **kwargs)
        calls.append((deliveries, kwargs))

    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", capture)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "pipe.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(executable))
    assert stats["text_delivery"]["delivered"] == ("glyphs" if outlined else "text")
    physical = ezdxf.readfile(output)
    text, = physical.modelspace().query("TEXT")
    assert text.dxf.text == content
    assert physical.layers.get(text.dxf.layer).is_frozen() is outlined
    deliveries, kwargs = calls[-1]
    if not outlined:
        assert text.dxf.lineweight > 0 and text.dxf.halign == text.dxf.valign == 0
        assert deliveries[0]["attempts"][-1]["evidence"]["parent_source_font_equivalence_verified"] is False
    else:
        assert any(a["evidence"].get("source_vertical_rule", {}).get("rule") ==
                   "exact_source_rectangular_vertical_pipe_interval_v1" for a in deliveries[0]["attempts"])
        assert any(e.dxftype() == "SOLID" for block in physical.blocks for e in block)
    checkpoint = next((tmp_path / "pipe_resume").glob("page_*.dxf"))
    verifier(ezdxf.readfile(checkpoint), deliveries, **kwargs)
    if adequate:
        changed = ezdxf.readfile(checkpoint)
        changed_text, = changed.modelspace().query("TEXT")
        changed_text.dxf.height /= 10
        forged = deepcopy(deliveries)
        forged[0]["attempts"][-1]["evidence"]["expected_height"] = changed_text.dxf.height
        # The cached transform claim colludes with the physical height, while
        # original trusted source frames still prove missing pipe ink.
        with pytest.raises(RuntimeError, match="shortens the original source vertical rule"):
            verifier(changed, forged, **kwargs)
    assert source.read_bytes() == original

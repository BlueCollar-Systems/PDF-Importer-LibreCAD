"""Native font safety retains source strings, rule ink and copy isolation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import ezdxf
import pymupdf
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

import dxf_import_engine as engine
import dxf_text_builder as builder
from librecad_pdf_importer import drawing_insert
from librecad_runtime import resolve_librecad_runtime_binding
from pdfcadcore.import_config import ImportConfig


def _rule_font(path, *, advance=600, notch=False):
    def rectangle(x0, y0, x1, y1):
        pen = TTGlyphPen(None)
        pen.moveTo((x0, y0))
        pen.lineTo((x1, y0))
        pen.lineTo((x1, y1))
        if notch:
            pen.lineTo((x0 + 20, y1))
            pen.lineTo((x0, y1 - 20))
        else:
            pen.lineTo((x0, y1))
        pen.closePath()
        return pen.glyph()

    font = FontBuilder(1000, isTTF=True)
    font.setupGlyphOrder([".notdef", "space", "underscore", "H", "x"])
    font.setupCharacterMap({32: "space", 95: "underscore", 72: "H", 120: "x"})
    font.setupGlyf({".notdef": rectangle(0, 0, 500, 700),
                   "space": TTGlyphPen(None).glyph(),
                   "underscore": rectangle(0, -100, 600, -50),
                   "H": rectangle(0, 0, 500, 700), "x": rectangle(0, 0, 500, 500)})
    font.setupHorizontalMetrics({name: (advance, 0) for name in font.font.getGlyphOrder()})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                 usWinDescent=200, sxHeight=500, sCapHeight=700)
    font.setupNameTable({"familyName": "Fictional Courier Rule", "styleName": "Regular",
                        "uniqueFontIdentifier": "FictionalCourierRule",
                        "fullName": "Fictional Courier Rule", "psName": "FictionalCourierRule"})
    font.setupPost()
    font.setupMaxp()
    font.save(path)


@pytest.mark.parametrize("editable", [False, True])
@pytest.mark.parametrize("source_kind", ["connected", "gapped", "nonrectangular", "courier-capsule"])
def test_exact_embedded_continuous_rules_use_outlines_and_keep_full_search_text(
    tmp_path, monkeypatch, editable, source_kind,
):
    root = tmp_path / "host"
    root.mkdir()
    executable = root / "LibreCAD.exe"
    executable.write_bytes(b"selected native installation")
    lff = root / "resources/fonts/unicode.lff"
    lff.parent.mkdir(parents=True)
    lff.write_text("# Format: LibreCAD Font 1\n# Encoding: UTF-8\n# LetterSpacing: 3\n"
                   "[005F]\n0,-3;11,-3\n\n", encoding="utf-8")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(lff))
    font = tmp_path / "courier-rule.ttf"
    _rule_font(font, advance=700 if source_kind == "gapped" else 600,
               notch=source_kind == "nonrectangular")
    source = tmp_path / "fictional-courier-rules.pdf"
    content = "  __________  "
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=400, height=250)
        if source_kind != "courier-capsule":
            page.insert_font(fontname="Rule", fontfile=str(font))
        page.insert_text((30, 80), content, fontname="cour" if source_kind == "courier-capsule" else "Rule", fontsize=12)
        pdf.save(source)
    before = source.read_bytes()
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "rule.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=editable, librecad_executable=str(executable))
    report = json.loads(Path(stats["import_report_path"]).read_text())
    # Connected source ink rejects native spacing; the remaining fictional
    # TTF inputs have no measurable outline stem (their only reference glyph,
    # "H", is a solid box). Neither may silently remain near-zero-weight
    # visible native TEXT.
    outlined = True
    assert stats["text_delivery"]["delivered"] == ("glyphs" if outlined else "text")
    assert report["text_items_degraded_total"] == 0
    page_report = json.loads(next((tmp_path / "rule_resume").glob("*import_report.json")).read_text())
    serialized = json.dumps(page_report)
    assert ("exact_source_rectangular_underline_join_v1" in serialized) is (source_kind == "connected")
    assert ("exact_source_capsule_underline_midline_join_v1" in serialized) is (source_kind == "courier-capsule")
    if editable and source_kind in {"gapped", "nonrectangular"}:
        assert "source-bound positive TrueType outline pen" in serialized
    physical = ezdxf.readfile(output)
    search, = physical.modelspace().query("TEXT")
    assert search.dxf.text == content
    assert physical.layers.get(search.dxf.layer).is_frozen() is outlined
    assert bool(len(physical.modelspace().query("INSERT"))) is outlined
    assert source.read_bytes() == before


@pytest.mark.parametrize("route", ["page-xref", "saved-copy"])
def test_native_saved_romans_alias_survives_actual_physical_copy_with_conflict(tmp_path, route):
    source = ezdxf.new("R2010")
    source.units = 4
    style = source.styles.add("romans#bcs-1", font="romans#bcs-1", dxfattribs={"width": 0.75, "flags": 4})
    source.modelspace().add_text("  EDITABLE ROMANS  ", dxfattribs={
        "style": style.dxf.name, "insert": (4, 5), "height": 3, "width": 1.4, "rotation": 33,
    })
    child = source.blocks.new("Child")
    child.add_attdef("MARK", (1, 2), text="NESTED ROMANS", dxfattribs={"style": style.dxf.name})
    source.modelspace().add_blockref("Child", (8, 9))
    engine.frame_modelspace(source, (0, 0, 30, 30))
    incoming = tmp_path / "page_0001.dxf"
    source.saveas(incoming)
    original = incoming.read_bytes()
    if route == "page-xref":
        output = tmp_path / "assembly.dxf"
        engine._assemble_checkpoints([incoming], str(output))
    else:
        base = ezdxf.new("R2010")
        base.units = 4
        base.styles.add("romans#bcs-1", font="foreign.ttf", dxfattribs={"width": 1.7})
        base.modelspace().add_text("BASE", dxfattribs={"style": "romans#bcs-1"})
        engine.frame_modelspace(base, (0, 0, 30, 30))
        base_path = tmp_path / "base.dxf"
        base.saveas(base_path)
        base_before = base_path.read_bytes()
        output = drawing_insert.insert_into_saved_drawing_copy(base_path, incoming, tmp_path / "copy.dxf").drawing
        assert base_path.read_bytes() == base_before
    copied = ezdxf.readfile(output)
    imported = [e for e in copied.entitydb.values() if e.is_alive and e.dxftype() in {"TEXT", "ATTDEF"}
                and "ROMANS" in str(e.dxf.text)]
    assert len(imported) == 2
    for entity in imported:
        assert entity.dxf.style.lower().split("#")[0] == "romans"
        actual = copied.styles.get(entity.dxf.style)
        assert actual.dxf.font == "romans#bcs-1" and actual.dxf.width == 0.75 and actual.dxf.flags == 4
    if route == "saved-copy":
        assert copied.styles.get("romans#bcs-1").dxf.font == "foreign.ttf"
        assert copied.styles.get("romans#bcs-1").dxf.width == 1.7
    assert incoming.read_bytes() == original


def test_optional_linear_font_absence_and_byte_changes_are_part_of_resume_identity(tmp_path, monkeypatch):
    executable = tmp_path / "LibreCAD.exe"
    executable.write_bytes(b"native executable")
    unicode = tmp_path / "resources/fonts/unicode.lff"
    unicode.parent.mkdir(parents=True)
    unicode.write_bytes(b"bound Unicode")
    monkeypatch.delenv("BCS_LIBRECAD_UNICODE_LFF", raising=False)
    missing = resolve_librecad_runtime_binding(str(executable)).identity_payload()
    romans = unicode.with_name("romans.lff")
    romans.write_bytes(b"bound Romans v1")
    present = resolve_librecad_runtime_binding(str(executable)).identity_payload()
    assert missing != present
    assert present["romans_lff_candidates"][0]["sha256"] == hashlib.sha256(romans.read_bytes()).hexdigest()
    romans.write_bytes(b"bound Romans v2")
    assert present != resolve_librecad_runtime_binding(str(executable)).identity_payload()


def test_near_isotropic_large_radius_cannot_hide_a_native_join_error():
    metrics = builder._LibreCadLffMetrics("[0050]\n0,0;0,2000000000000,A1\n\n")
    resolution = builder._LibreCadLffResolution(verified=True, layout_metrics=metrics)
    assert builder._native_lff_stroke_safety(resolution, "P", 1, 1) is True
    assert builder._native_lff_stroke_safety(resolution, "P", 1, 1 + 1e-13) is False
    assert builder._native_lff_stroke_safety(resolution, "P", float("nan"), 1) is False


def test_continuity_probe_refuses_collapsed_target_and_invalid_font_without_failing_item(tmp_path, monkeypatch):
    # Use native-shaped original frames and a real exact rectangular font;
    # only the independently tested affine readback is substituted below.
    from pdfcadcore.primitives import NormalizedText, TextCharLayout

    font = tmp_path / "rule.ttf"
    _rule_font(font)
    digest = hashlib.sha256(font.read_bytes()).hexdigest()
    from fontTools.ttLib import TTFont
    with TTFont(font) as program:
        gid = program.getGlyphID("underscore")
    layout = tuple(TextCharLayout(
        text="_", glyph_id=gid, source_origin_pdf=(i * 6, 0), source_bbox_pdf=(i * 6, -8, i * 6 + 6, 2),
        source_quad_pdf=((i * 6, -8), (i * 6 + 6, -8), (i * 6 + 6, 2), (i * 6, 2)),
        target_origin=(i * 6, 0), target_quad=((i * 6, 8), (i * 6 + 6, 8), (i * 6 + 6, -2), (i * 6, -2)),
        advance_width=6, glyph_height=10, source_font_size_pdf=10,
        source_font_ascender=.8, source_font_descender=-.2, source_writing_mode=0,
        source_font_program_sha256=digest, source_font_binding_verified=True,
        source_font_character_codepoint=95,
    ) for i in range(2))
    item = NormalizedText(1, "__", "__", source_char_layout=layout)
    resolution = builder._ExactFontResolution(source_name="Fictional Courier Rule", filename=str(font), exact=True, asset_sha256=digest)
    assert builder._source_continuous_underline(item, resolution)["connected_pairs"] == 1
    monkeypatch.setattr(builder, "_source_character_affine_axes", lambda char: ((0, 0), (0, 10)))
    assert builder._source_continuous_underline(item, resolution) is None
    monkeypatch.undo()
    assert builder._source_continuous_underline(replace(item, source_char_layout=()), resolution) is None
    font.write_bytes(b"invalid font container")
    assert builder._source_continuous_underline(item, replace(resolution,
        asset_sha256=hashlib.sha256(font.read_bytes()).hexdigest())) is None


CAPSULE = [
    ("moveTo", ((585, -116),)),
    ("curveTo", ((607, -116), (618, -107), (618, -90))),
    ("curveTo", ((618, -73), (607, -65), (585, -65))),
    ("lineTo", ((15, -65),)),
    ("curveTo", ((-6, -65), (-17, -74), (-17, -90))),
    ("curveTo", ((-17, -107), (-6, -116), (15, -116))),
    ("closePath", ()),
]


def test_capsule_admission_proves_its_filled_midline_without_assuming_box_fill():
    kind, _band, line = builder._source_underline_midline(CAPSULE)
    assert kind == "capsule" and line == [(-17, -90), (618, -90)]
    # These exact four monotone source cap quadrants have a 35-unit filled
    # midline overlap when the next original Courier glyph starts600 later.
    assert line[1][0] - (600 + line[0][0]) == 35


@pytest.mark.parametrize("mutation", ["open", "multi", "overshoot", "nonmonotone", "midline", "side", "nonfinite"])
def test_unknown_or_non_simple_capsule_cannot_authorize_rule_fallback(mutation):
    import copy
    ops = copy.deepcopy(CAPSULE)
    if mutation == "open":
        ops[-1] = ("endPath", ())
    elif mutation == "multi":
        ops += CAPSULE
    elif mutation == "overshoot":
        ops[1] = ("curveTo", ((619, -116), (618, -107), (618, -90)))
    elif mutation == "nonmonotone":
        ops[1] = ("curveTo", ((617, -116), (607, -107), (618, -90)))
    elif mutation == "midline":
        ops[4] = ("curveTo", ((-6, -65), (-17, -74), (-17, -89)))
    elif mutation == "side":
        ops[3] = ("lineTo", ((15, -64),))
    else:
        ops[1] = ("curveTo", ((float("nan"), -116), (618, -107), (618, -90)))
    assert builder._source_underline_midline(ops) is None

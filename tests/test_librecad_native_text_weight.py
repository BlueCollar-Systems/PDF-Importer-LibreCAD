"""Source-bound native pen admission and physical serialization, without a CAD app."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import math
import os
from pathlib import Path

import ezdxf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont
import pytest

import dxf_text_builder as builder
from pdfcadcore.primitives import NormalizedText, TextCharLayout


def _cff(path, *, vertical=51, horizontal=52, matrix=None):
    order = [".notdef", "space", "P", "A", "H"]
    strings = {}
    for name in order:
        pen = T2CharStringPen(600, None)
        if name != "space":
            pen.moveTo((50, 0))
            pen.lineTo((550, 0))
            pen.lineTo((550, 700))
            pen.lineTo((50, 700))
            pen.closePath()
        strings[name] = pen.getCharString()
    font = FontBuilder(1000, isTTF=False)
    font.setupGlyphOrder(order)
    font.setupCharacterMap({32: "space", 80: "P", 65: "A", 72: "H"})
    font.setupHorizontalMetrics({name: (600, 0) for name in order})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupNameTable({"familyName": "Fictional Stem", "styleName": "Regular",
                         "psName": "FictionalStem", "fullName": "Fictional Stem"})
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                  usWinDescent=200, sCapHeight=700)
    font.setupPost()
    metrics = {}
    if vertical is not None:
        metrics["StdVW"] = vertical
    if horizontal is not None:
        metrics["StdHW"] = horizontal
    font.setupCFF("FictionalStem", {"FullName": "Fictional Stem", "FamilyName": "Fictional Stem",
                                  "Weight": "Regular", "FontMatrix": matrix or [.001, 0, 0, .001, 0, 0]},
                  strings, metrics)
    font.save(path)
    font.font.close()
    return path


def _source(path, *, text=" P A ", nx=3.5, ny=3.5, rotation=0.0):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with TTFont(path) as font:
        cmap = font.getBestCmap()
        glyphs = {char: font.getGlyphID(cmap[ord(char)]) for char in text}
    angle = math.radians(rotation)

    def target(x, y):
        return (11 + x * math.cos(angle) - y * math.sin(angle),
                23 + x * math.sin(angle) + y * math.cos(angle))

    layout = []
    for index, char in enumerate(text):
        x = 6.0 * index
        tx = .6 * nx * index
        layout.append(TextCharLayout(
            text=char, glyph_id=glyphs[char], source_origin_pdf=(x, 0),
            source_bbox_pdf=(x, -8, x + 6, 2),
            source_quad_pdf=((x, -8), (x + 6, -8), (x + 6, 2), (x, 2)),
            target_origin=target(tx, 0),
            target_quad=(target(tx, .8 * ny), target(tx + .6 * nx, .8 * ny),
                         target(tx + .6 * nx, -.2 * ny), target(tx, -.2 * ny)),
            advance_width=.6 * nx, glyph_height=ny,
            source_font_size_pdf=10, source_font_ascender=.8,
            source_font_descender=-.2, source_writing_mode=0,
            source_font_program_sha256=digest, source_font_binding_verified=True,
        ))
    item = NormalizedText(id=1, text=text, normalized=text.upper(), insertion=target(0, 0),
                          font_size=math.sqrt(nx * ny), rotation=rotation,
                          advance_width=len(text) * .6 * nx, source_char_layout=tuple(layout))
    resolution = builder._ExactFontResolution(
        source_name="Fictional Stem", filename=str(path), exact=True,
        resolution_source="installed_exact_font", asset_sha256=digest,
    )
    return item, resolution


@pytest.mark.parametrize("rotation,nx,ny", [(0, 3.5, 3.5), (37, 3.5, 3.5), (90, 3.49, 3.5)])
def test_actual_cff_metrics_follow_bound_model_axes_and_disclose_quantization(tmp_path, rotation, nx, ny):
    path = _cff(tmp_path / "source.otf")
    item, resolution = _source(path, nx=nx, ny=ny, rotation=rotation)
    original = deepcopy(item)
    proof = builder._source_native_text_lineweight(item, resolution)
    assert item == original
    assert proof["native_text_lineweight"] == 18
    assert proof["native_text_lineweight_mm"] == .18
    assert proof["native_text_source_stem_StdVW"] == 51
    assert proof["native_text_source_stem_StdHW"] == 52
    assert proof["native_text_source_stem_widths_mm"] == pytest.approx({
        "vertical": 51 * nx / 1000, "horizontal": 52 * ny / 1000,
    })
    expected = max(51 * nx / 1000, 52 * ny / 1000)
    assert proof["native_text_source_stem_width_mm"] == pytest.approx(expected)
    assert proof["native_text_lineweight_quantization_error_mm"] == pytest.approx(.18 - expected)
    assert proof["native_text_source_stem_frames_checked"] == 2
    assert proof["native_text_source_stem_font_sha256"] == resolution.asset_sha256
    assert proof["native_text_source_stem_approximation"] is True
    assert proof["native_text_weight_source_ink_parity_verified"] is False


@pytest.mark.parametrize("vertical,horizontal,matrix", [
    (None, 52, None), (51, None, None), (0, 52, None), (-51, 52, None),
    (51, 0, None), (1, 1, None), (1000, 1000, None),
    (51, 52, [.002, 0, 0, .001, 0, 0]),
])
def test_missing_invalid_or_unrepresentable_cff_stems_cannot_create_a_default_pen(
    tmp_path, vertical, horizontal, matrix,
):
    path = _cff(tmp_path / "unsupported.otf", vertical=vertical, horizontal=horizontal, matrix=matrix)
    item, resolution = _source(path)
    with pytest.raises(builder._RepresentationImpossible, match="source-bound positive CFF pen"):
        builder._source_native_text_lineweight(item, resolution)


def test_exact_truetype_without_measurable_outline_stems_remains_unproved(deterministic_exact_font):
    # The fixture's glyphs are solid boxes: no CFF hints and no stem to measure.
    item, resolution = _source(Path(deterministic_exact_font))
    with pytest.raises(builder._RepresentationImpossible,
                       match="source-bound positive TrueType outline pen: .*measurable vertical stem"):
        builder._source_native_text_lineweight(item, resolution)


@pytest.mark.parametrize("fault", ["glyph", "binding", "font-sha", "layout", "nominal-em", "shear", "baseline", "frame-varies", "nonfinite"])
def test_invalid_original_character_authority_or_frame_is_refused(tmp_path, fault):
    path = _cff(tmp_path / "bound.otf")
    item, resolution = _source(path, text="PA")
    first, second = item.source_char_layout
    if fault == "glyph":
        first = replace(first, glyph_id=second.glyph_id)
    elif fault == "binding":
        first = replace(first, source_font_binding_verified=False)
    elif fault == "font-sha":
        first = replace(first, source_font_program_sha256="0" * 64)
    elif fault == "layout":
        item = replace(item, text="PP")
    elif fault == "nominal-em":
        item = replace(item, font_size=7)
    elif fault == "shear":
        quad = tuple((x + .2 * y, y) for x, y in first.target_quad)
        first = replace(first, target_quad=quad,
                        target_origin=(first.target_origin[0] + .2 * first.target_origin[1], first.target_origin[1]))
    elif fault == "baseline":
        first = replace(first, target_origin=(999, 999))
    elif fault == "frame-varies":
        # Rotate the second intact affine frame alone: same em size, different native axes.
        ox, oy = second.target_origin
        second = replace(second, target_quad=tuple((ox - (y - oy), oy + (x - ox))
                                                   for x, y in second.target_quad))
    else:
        first = replace(first, target_quad=((math.nan, 0), *first.target_quad[1:]))
    item = replace(item, source_char_layout=(first, second))
    with pytest.raises(builder._RepresentationImpossible):
        builder._source_native_text_lineweight(item, resolution)


def test_cached_cff_metrics_do_not_replace_a_fresh_font_byte_check(tmp_path):
    path = _cff(tmp_path / "changing.otf")
    item, resolution = _source(path)
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 18
    stat = path.stat()
    original = path.read_bytes()
    path.write_bytes(original + b"changed-but-same-cached-stem-hints")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(builder._RepresentationImpossible, match="bytes changed"):
        builder._source_native_text_lineweight(item, resolution)


@pytest.fixture
def native_fonts(tmp_path, monkeypatch):
    from test_librecad_native_linear_font import ROMANS, UNICODE

    installation = tmp_path / "selected-native"
    installation.mkdir()
    executable = installation / "LibreCAD.exe"
    executable.write_bytes(b"fictional installation; never run")
    fonts = installation / "resources/fonts"
    fonts.mkdir(parents=True)
    (fonts / "unicode.lff").write_text(UNICODE, encoding="utf-8")
    (fonts / "romans.lff").write_text(ROMANS, encoding="utf-8")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(fonts / "unicode.lff"))
    builder.reset_text_styles()
    return executable


def test_editable_pipeline_writes_source_pen_and_rejects_physical_or_claimed_weight_changes(
    native_fonts, tmp_path, monkeypatch,
):
    import pymupdf
    import dxf_import_engine as engine
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    from pdfcadcore.import_config import ImportConfig

    source = tmp_path / "fictional-courier.pdf"
    content = "  PAPA  "
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_text((72, 90), content, fontname="cour", fontsize=12)
        pdf.save(source)
    original_source = source.read_bytes()
    verifier = exporter._verify_serialized_text_deliveries
    calls = []

    def capture(doc, deliveries, **kwargs):
        verifier(doc, deliveries, **kwargs)
        calls.append((deliveries, kwargs))

    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", capture)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "weighted.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["delivered"] == "text"
    actual, = ezdxf.readfile(output).modelspace().query("TEXT")
    assert actual.dxf.text == content
    assert actual.dxf.halign == actual.dxf.valign == 0
    deliveries, kwargs = calls[-1]
    evidence = deliveries[0]["attempts"][-1]["evidence"]
    assert actual.dxf.lineweight == evidence["native_text_lineweight"] > 0
    assert evidence["native_text_lineweight_source_verified"] is True
    assert evidence["native_text_weight_source_ink_parity_verified"] is False
    assert evidence["parent_source_font_equivalence_verified"] is False
    assert evidence["parent_visual_fidelity_verified"] is False
    assert deliveries[0]["attempts"][-1]["visual_verified"] is False
    checkpoint = next((tmp_path / "weighted_resume").glob("page_*.dxf"))
    physical = ezdxf.readfile(checkpoint)
    verifier(physical, deliveries, **kwargs)
    native, = physical.modelspace().query("TEXT")
    old_weight = native.dxf.lineweight
    for changed in (0, 13 if old_weight != 13 else 25):
        native.dxf.lineweight = changed
        with pytest.raises(RuntimeError, match="source-bound native TEXT lineweight"):
            verifier(physical, deliveries, **kwargs)
        forged = deepcopy(deliveries)
        forged[0]["attempts"][-1]["evidence"]["native_text_lineweight"] = changed
        forged[0]["attempts"][-1]["evidence"]["native_text_lineweight_mm"] = changed / 100
        with pytest.raises(RuntimeError, match="source-bound native TEXT lineweight"):
            verifier(physical, forged, **kwargs)
    native.dxf.lineweight = old_weight
    with pytest.raises(RuntimeError, match="native pen authority is missing"):
        verifier(physical, deliveries, **dict(kwargs, trusted_native_text_sources={}))
    _item, resolution = next(iter(kwargs["trusted_native_text_sources"].values()))
    bound = Path(resolution.filename).resolve()
    # The source cache may otherwise be shared by unrelated tests or assets.
    # This conversion stages its private authority inside this test's output.
    assert bound.is_relative_to(tmp_path.resolve())
    original_font = bound.read_bytes()
    try:
        bound.write_bytes(original_font + b"changed source hint authority")
        with pytest.raises(RuntimeError, match="source native pen changed"):
            verifier(physical, deliveries, **kwargs)
    finally:
        bound.write_bytes(original_font)
    assert bound.read_bytes() == original_font
    assert source.read_bytes() == original_source


def test_default_glyph_delivery_does_not_restyle_search_carriers(native_fonts, tmp_path):
    import pymupdf
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    source = tmp_path / "fictional-default.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_text((72, 90), "PAPA", fontname="cour", fontsize=12)
        pdf.save(source)
    config = ImportConfig.auto()
    config.text_mode = "glyphs"
    output = tmp_path / "glyphs.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=False, librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["delivered"] == "glyphs"
    doc = ezdxf.readfile(output)
    text, = doc.modelspace().query("TEXT")
    assert text.dxf.text == "PAPA"
    assert doc.layers.get(text.dxf.layer).is_frozen()
    assert not text.dxf.hasattr("lineweight") or text.dxf.lineweight <= 0
    assert any(entity.dxftype() == "SOLID" for block in doc.blocks for entity in block)


def test_truetype_without_measurable_stems_descends_to_exact_glyphs_without_inventing_a_pen(
    native_fonts, deterministic_exact_font, tmp_path,
):
    """A TrueType program whose outlines show no stem keeps exact glyphs.

    The embedded fixture's glyphs are solid boxes, wider than any admitted
    stem, so no pen is measured and none is invented: the item descends to
    exact outlines with its full search string, and the report says why.
    """
    import json
    import pymupdf
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    source = tmp_path / "fictional-truetype.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_font(fontname="BoundTTF", fontfile=str(deterministic_exact_font))
        page.insert_text((72, 90), "PAPA", fontname="BoundTTF", fontsize=12)
        pdf.save(source)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "unproved.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["delivered"] == "glyphs"
    assert stats["text_delivery"]["editable_text_item_count"] == 0
    doc = ezdxf.readfile(output)
    assert any(entity.dxftype() == "SOLID" for block in doc.blocks for entity in block)
    assert not doc.modelspace().query("IMAGE")
    for text in doc.modelspace().query("TEXT"):
        assert doc.layers.get(text.dxf.layer).is_frozen()
        assert text.dxf.text == "PAPA"
        assert not text.dxf.hasattr("lineweight") or text.dxf.lineweight <= 0
    session = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    page_report = json.loads(Path(session["page_reports"][0]).read_text(encoding="utf-8"))
    reasons = [transition["reason_code"] for transition in page_report["extra"]["fallback_transitions"]]
    assert reasons and all(
        "source-bound positive TrueType outline pen" in reason
        and "measurable vertical stem" in reason for reason in reasons)
    assert page_report["extra"]["editable_text"]["item_count"] == 0
    assert page_report["extra"]["editable_text"]["pen_sources"] == {}


def test_r12_editable_courier_uses_exact_glyphs_and_full_search_without_invalid_pen(
    native_fonts, tmp_path, monkeypatch,
):
    import pymupdf
    import dxf_import_engine as engine
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    from pdfcadcore.import_config import ImportConfig

    source = tmp_path / "fictional-courier-r12.pdf"
    content = "  PAPA  "
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_text((72, 90), content, fontname="cour", fontsize=12)
        pdf.save(source)
    verifier = exporter._verify_serialized_text_deliveries
    calls = []

    def capture(doc, deliveries, **kwargs):
        verifier(doc, deliveries, **kwargs)
        calls.append(deliveries)

    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", capture)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "legacy.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           dxf_version="R12", editable_text=True,
                           librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["delivered"] == "glyphs"
    assert "R12 cannot serialize a source-bound positive native TEXT lineweight" in str(calls[-1])
    doc = ezdxf.readfile(output)
    assert doc.dxfversion == "AC1009"
    text, = doc.modelspace().query("TEXT")
    assert text.dxf.text == content
    assert doc.layers.get(text.dxf.layer).is_frozen()
    assert not text.dxf.hasattr("lineweight")
    assert any(entity.dxftype() == "SOLID" for block in doc.blocks for entity in block)


def test_positive_physical_pen_expands_native_ink_envelope_without_changing_cursor(native_fonts):
    selected = builder._resolve_librecad_lff(str(native_fonts), font_name="romans", fresh=True)
    doc = ezdxf.new("R2018")
    doc.styles.add("romans", font="romans")
    text = doc.modelspace().add_text("PA", dxfattribs={
        "style": "romans", "height": 9.0, "rotation": 37,
        "insert": (11.25, 23.5), "lineweight": 0,
    })
    builder._fit_text_advance(text, 20.0, parent_fit_alignment=True, native_lff=selected)
    hairline = builder._librecad_native_layout(text, selected)
    text.dxf.lineweight = 18
    positive = builder._librecad_native_layout(text, selected)
    assert positive["native_lff_lineweight"] == 18
    assert positive["native_lff_pen_width_mm"] == .18
    assert positive["native_lff_actual_advance"] == hairline["native_lff_actual_advance"]
    assert positive["native_lff_rotated_ink_envelope"] == hairline["native_lff_rotated_ink_envelope"]
    assert positive["native_lff_estimated_pen_envelope"] == pytest.approx(tuple(
        value + delta for value, delta in zip(
            hairline["native_lff_rotated_ink_envelope"], (-.09, -.09, .09, .09), strict=True)
    ))

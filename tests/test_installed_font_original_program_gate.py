"""Actual same-width fonts must not authorize different visible contours."""
from dataclasses import replace
import hashlib
from pathlib import Path

import ezdxf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
import pymupdf as fitz
import pytest

import dxf_text_builder as builder
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitive_extractor import extract_page


def font_program(path, shape):
    font = FontBuilder(1000, isTTF=True)
    order = [".notdef", "A", "x", "space"]
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        if name in {"A", "x"}:
            top = 700 if name == "A" else 500
            points = [(0, 0), (400, 0), (200, top)] if shape == "triangle" else [
                (0, 0), (400, 0), (400, top), (0, top)]
            pen.moveTo(points[0])
            for point in points[1:]:
                pen.lineTo(point)
            pen.closePath()
        glyphs[name] = pen.glyph()
    font.setupGlyphOrder(order)
    font.setupGlyf(glyphs)
    font.setupHorizontalMetrics({name: (500, 0) for name in order})
    font.setupHorizontalHeader(ascent=1000, descent=0)
    font.setupCharacterMap({65: "A", 120: "x", 32: "space"})
    font.setupNameTable({"familyName": "Same Source Family", "styleName": "Regular",
        "fullName": "Same Source Family Regular", "psName": "SameSourceFamily-Regular",
        "uniqueFontIdentifier": "same-source-family-" + shape})
    font.setupOS2(sTypoAscender=1000, sTypoDescender=0, usWinAscent=1000,
                 usWinDescent=0, sxHeight=500, sCapHeight=700)
    font.setupPost()
    font.setupMaxp()
    font.save(path)
    return path


@pytest.fixture
def source_and_candidates(tmp_path):
    original = font_program(tmp_path / "original-triangle.ttf", "triangle")
    other = font_program(tmp_path / "deceptive-rectangle.ttf", "rectangle")
    source = tmp_path / "original-program.pdf"
    with fitz.open() as document:
        page = document.new_page(width=100, height=100)
        page.insert_font(fontname="source", fontfile=str(original))
        page.insert_text((20, 40), "A", fontname="source", fontsize=12)
        document.save(source)
    with fitz.open(source) as document:
        [item] = extract_page(document[0], 1).text_items
    assert item.font_asset is not None
    [character] = item.source_char_layout
    assert character.source_font_binding_verified is True
    assert character.source_font_program_sha256 == hashlib.sha256(original.read_bytes()).hexdigest()
    # Retain the real original character evidence while exercising resolution
    # from an installed file rather than the attached embedded asset.
    item.font_asset = None
    item.font_failure = None
    return item, original, other


def resolution(path):
    return builder._ExactFontResolution(source_name="SameSourceFamily-Regular",
        family="Same Source Family", style="Regular", filename=str(path), exact=True,
        resolution_source="installed_exact_font", source_cap_height_ratio=.7,
        asset_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def test_same_advance_and_numeric_gid_different_contours_rejected(source_and_candidates):
    item, original, other = source_and_candidates
    outlines = []
    for path in (original, other):
        with TTFont(path) as program:
            spacing = builder._installed_font_advance_proof(item.source_char_layout[0], program, "A")
            assert spacing["verified"] is True
            assert spacing["proof_scope"] == "source_spacing_only"
            assert spacing["exact_contours_verified"] is False
            assert program.getGlyphID("A") == item.source_char_layout[0].glyph_id
            pen = RecordingPen()
            program.getGlyphSet()["A"].draw(pen)
            outlines.append(pen.value)
    assert outlines[0] != outlines[1]
    assert builder._positioned_source_glyph_names(item.source_char_layout, resolution(original)) == ["A"]
    with pytest.raises(builder._RepresentationImpossible, match="original source program"):
        builder._positioned_source_glyph_names(item.source_char_layout, resolution(other))


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_actual_delivery_requires_original_program_and_reopens(source_and_candidates, monkeypatch, tmp_path, mode):
    item, original, other = source_and_candidates
    for path, expected in ((original, True), (other, False)):
        builder.reset_text_styles()
        monkeypatch.setattr(builder, "_resolve_exact_font", lambda _name, path=path: resolution(path))
        doc = ezdxf.new("R2010")
        result = builder.build_text(item, doc.modelspace(), "TEXT", ImportConfig(text_mode=mode),
            target_app="librecad", dxf_version="R2010", return_delivery_result=True)
        assert result.verified is expected, result.failure_reason
        if expected:
            assert result.final_representation == mode
            assert list(doc.modelspace()) and not doc.modelspace().query("IMAGE")
            saved = tmp_path / (mode + ".dxf")
            doc.saveas(saved)
            reopened = ezdxf.readfile(saved)
            assert len(reopened.modelspace()) == len(doc.modelspace())
            assert not reopened.audit().errors
        else:
            assert not list(doc.modelspace())
            assert all(attempt.outcome != "verified" for attempt in result.attempts)


def test_unbound_or_changed_installed_program_never_certified(source_and_candidates):
    item, original, _other = source_and_candidates
    candidate = resolution(original)
    unbound = tuple(replace(c, source_font_binding_verified=False) for c in item.source_char_layout)
    with pytest.raises(builder._RepresentationImpossible, match="original source program"):
        builder._positioned_source_glyph_names(unbound, candidate)
    original.write_bytes(original.read_bytes() + b"changed-after-resolution")
    with pytest.raises(ValueError, match="cannot be inspected"):
        builder._positioned_source_glyph_names(item.source_char_layout, candidate)

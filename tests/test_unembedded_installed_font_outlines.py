"""Text set in a font the PDF does not embed is outlined from the installed face.

PDFsharp/Tekla sheets name Arial, "Arial,Bold", ArialNarrow or ArialBlack and
embed no font program. The glyph id MuPDF reports for such text belongs to its
built-in stand-in face; coincident numeric IDs do not bind the installed font.
Requiring that equality sent stacked fractions and condensed table
entry to a raster patch. The installed face is bound instead by what the PDF
does declare for a non-embedded font: each character's advance (/Widths).

Every fixture is synthetic and generated here: a small TrueType font built with
fontTools stands in for the "installed" face, and the PDFs name it without
embedding it. No host font is needed.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from types import SimpleNamespace

import ezdxf
from ezdxf.disassemble import recursive_decompose
from ezdxf.fonts.font_face import FontFace
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
import pytest

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

import dxf_import_engine
import dxf_text_builder as builder
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import
from pdfcadcore.import_config import ImportConfig

UNITS = 2048
PDF_FONT_NAME = "BCSAdvanceProof"


# ------------------------------------------------- PDF base-font names ----

def test_family_name_is_spaced_from_a_pdf_base_font_token():
    assert builder._spaced_family_name("ArialBlack") == "Arial Black"
    assert builder._spaced_family_name("ArialRoundedMTBold") == "Arial Rounded MT Bold"
    assert builder._spaced_family_name("SegoeUISemibold") == "Segoe UI Semibold"
    assert builder._spaced_family_name("Tahoma,") == "Tahoma"
    assert builder._spaced_family_name("Franklin-Gothic_Book") == "Franklin Gothic Book"


def _face(filename, family, style, weight, width=5):
    return FontFace(filename=filename, family=family, style=style, weight=weight, width=width)


_FACES = (
    _face("arial.ttf", "Arial", "Regular", 400),
    _face("arialbd.ttf", "Arial", "Bold", 700),
    _face("ariali.ttf", "Arial", "Italic", 400),
    _face("arialbi.ttf", "Arial", "Bold Italic", 700),
    _face("ariblk.ttf", "Arial Black", "Regular", 900),
    _face("ARIALN.TTF", "Arial Narrow", "Regular", 400, width=3),
    _face("ARIALNB.TTF", "Arial Narrow", "Bold", 700, width=3),
    _face("ARLRDBD.TTF", "Arial Rounded MT Bold", "Regular", 400),
    _face("tahoma.ttf", "Tahoma", "Regular", 400),
    _face("tahomabd.ttf", "Tahoma", "Bold", 700),
    _face("onlybold.ttf", "Only Bold", "Bold", 700),
    _face("upright.ttf", "Upright", "Regular", 400),
)


def _best_match(family="sans-serif", style="Regular", weight=400, width=5, italic=False):
    """The selection ezdxf's font cache makes: family prefix, style, then weight."""
    # (ezdxf.fonts.font_manager.FontCache.find_best_match_ex, ezdxf 1.4)
    entries = [face for face in _FACES if face.family.lower().startswith(family.lower())]
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]
    styled = [face for face in entries if style.lower() in face.style.lower()]
    if len(styled) == 1:
        return styled[0]
    entries = styled or entries
    return sorted(
        entries,
        key=lambda face: (
            abs(face.weight - weight), face.is_italic is not italic, abs(face.width - width),
        ),
    )[0]


@pytest.fixture
def fake_font_cache(monkeypatch, tmp_path):
    """A font cache with known faces, so name mapping is tested on every host."""
    program = tmp_path / "program.ttf"
    program.write_bytes(b"not parsed by the name mapping")
    monkeypatch.setattr(builder.ezdxf_fonts, "find_best_match", _best_match)
    monkeypatch.setattr(builder, "_installed_font_metrics", lambda filename: (0.7, "ab" * 32))
    monkeypatch.setattr(builder, "_outline_engine_font_name", lambda filename: filename)
    monkeypatch.setattr(
        builder.ezdxf_fonts.font_manager, "get_ttf_font",
        lambda name: SimpleNamespace(reader=SimpleNamespace(file=SimpleNamespace(name=str(program)))),
    )


def _resolve(name):
    # The session fixture wraps the resolver and hands every other name on.
    return builder._resolve_exact_font(name)


@pytest.mark.parametrize(("pdf_name", "family", "style"), [
    ("Arial", "Arial", "Regular"),
    ("ArialMT", "Arial", "Regular"),
    ("Arial,Bold", "Arial", "Bold"),
    ("Arial-BoldMT", "Arial", "Bold"),
    ("Arial,Italic", "Arial", "Italic"),
    ("Arial,BoldItalic", "Arial", "Bold Italic"),
    ("ABCDEF+Arial-BoldMT", "Arial", "Bold"),
    ("ArialNarrow", "Arial Narrow", "Regular"),
    ("ArialNarrow,Bold", "Arial Narrow", "Bold"),
    ("ArialBlack", "Arial Black", "Regular"),
    ("Arial-Black", "Arial Black", "Regular"),
    ("Tahoma,Bold", "Tahoma", "Bold"),
    ("Tahoma", "Tahoma", "Regular"),
    ("ArialRoundedMTBold", "Arial Rounded MT Bold", "Regular"),
])
def test_pdf_base_font_name_resolves_to_the_installed_face(fake_font_cache, pdf_name, family, style):
    resolution = _resolve(pdf_name)
    assert resolution.exact, resolution.reason
    assert (resolution.family, resolution.style) == (family, style)
    assert resolution.resolution_source == "installed_exact_font"
    assert resolution.filename


@pytest.mark.parametrize("pdf_name", [
    "OnlyBold",            # the family has no regular face
    "Upright,Bold",        # the family has no bold face
    "Upright,Italic",      # the family has no italic face
    "ArialBlack,Italic",   # the heavy family has no italic face
    "Helvetica",           # not installed at all
    "ArialUnicode",        # a different family that only starts the same
])
def test_a_face_the_name_does_not_ask_for_is_never_substituted(fake_font_cache, pdf_name):
    resolution = _resolve(pdf_name)
    assert not resolution.exact
    assert resolution.filename == ""


@pytest.mark.parametrize(("face", "family", "bold", "italic", "expected"), [
    (_face("a.ttf", "Arial Black", "Regular", 900), "Arial Black", False, False, True),
    (_face("a.ttf", "Arial", "Bold", 700), "Arial", False, False, False),
    (_face("a.ttf", "Arial", "Bold", 700), "Arial", True, False, True),
    (_face("a.ttf", "Arial", "Regular", 400), "Arial", True, False, False),
    (_face("a.ttf", "Arial", "Italic", 400), "Arial", False, False, False),
    (_face("a.ttf", "Arial", "Italic", 400), "Arial", False, True, True),
    (_face("a.ttf", "Arial Narrow", "Regular", 400), "Arial", False, False, False),
    (_face("a.ttf", "Segoe UI Semibold", "Regular", 600), "Segoe UI Semibold", False, False, True),
])
def test_installed_face_equivalence_rule(face, family, bold, italic, expected):
    assert builder._installed_face_is_source_equivalent(
        face, family, bold=bold, italic=italic,
    ) is expected


# ---------------------------------------------------- the stand-in face ----

def _advance(codepoint: int) -> int:
    """Design-unit advances that do not land on whole 1/1000 em values."""
    if codepoint == 0x2F:
        return 569
    if 0x30 <= codepoint <= 0x39:
        return 1139
    return 1000 + (codepoint % 9) * 61


def _box(top: int, right: int):
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((right, 0))
    pen.lineTo((right, top))
    pen.lineTo((100, top))
    pen.closePath()
    return pen.glyph()


@pytest.fixture(scope="module")
def installed_face(tmp_path_factory) -> Path:
    """A font whose glyph ids are NOT the ones MuPDF's stand-in face reports."""
    order = [".notdef", ".null", "nonmarkingreturn", "space"]
    cmap = {32: "space"}
    for codepoint in range(33, 256):
        order.append(f"uni{codepoint:04X}")
        cmap[codepoint] = order[-1]
    glyphs = {name: TTGlyphPen(None).glyph() for name in order[:4]}
    glyphs[".notdef"] = _box(1400, 900)
    metrics = {".notdef": (1024, 100), ".null": (0, 0), "nonmarkingreturn": (569, 0), "space": (569, 0)}
    for codepoint, name in cmap.items():
        if name == "space":
            continue
        glyphs[name] = _box(1062 if codepoint == ord("x") else 1466, _advance(codepoint) - 120)
        metrics[name] = (_advance(codepoint), 100)
    font = FontBuilder(UNITS, isTTF=True)
    font.setupGlyphOrder(order)
    font.setupCharacterMap(cmap)
    font.setupGlyf(glyphs)
    font.setupHorizontalMetrics(metrics)
    font.setupHorizontalHeader(ascent=1854, descent=-434)
    font.setupOS2(sTypoAscender=1854, sTypoDescender=-434, usWinAscent=1854,
                  usWinDescent=434, sxHeight=1062, sCapHeight=1466)
    font.setupNameTable({"familyName": "BCS Advance Proof", "styleName": "Regular"})
    font.setupPost()
    font.setupMaxp()
    path = tmp_path_factory.mktemp("bcs_advance_proof") / "bcs-advance-proof.ttf"
    font.save(str(path))
    return path


@pytest.fixture
def resolve_to_installed_face(installed_face, monkeypatch):
    """The PDF's font name resolves to the stand-in face, as an installed font."""
    ratio, digest = builder._installed_font_metrics(str(installed_face))
    assert digest == hashlib.sha256(installed_face.read_bytes()).hexdigest()

    def resolve(name):
        return builder._ExactFontResolution(
            source_name=str(name), family="BCS Advance Proof", style="Regular",
            filename=str(installed_face), exact=True,
            reason="exact installed source-font match",
            resolution_source="installed_exact_font",
            source_cap_height_ratio=ratio, asset_sha256=digest,
        )

    monkeypatch.setattr(builder, "_resolve_exact_font", resolve)
    return installed_face


def _truncated(codepoint: int) -> int:
    """What PDFsharp writes: the font's advance cut down to whole 1/1000 em."""
    return (569 if codepoint == 32 else _advance(codepoint)) * 1000 // UNITS


def _write_pdf(path: Path, widths=_truncated) -> Path:
    """A stacked fraction, a condensed word, a plain word and vertical text."""
    with fitz.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((60, 50), "13", fontsize=8)
        page.insert_text((60, 62), "16", fontsize=8)
        page.insert_text((59, 58), "/", fontsize=10)
        page.insert_text((120, 60), "Grade A572", fontsize=9,
                         morph=(fitz.Point(120, 60), fitz.Matrix(0.9, 1.1)))
        page.insert_text((120, 100), "Plain 12", fontsize=9)
        page.insert_text((230, 150), "1/4", fontsize=9, rotate=90)
        xref = page.get_fonts(full=True)[0][0]
        # Named, not embedded, with its own advances: what PDFsharp writes.
        document.xref_set_key(xref, "BaseFont", f"/{PDF_FONT_NAME}")
        document.xref_set_key(xref, "Subtype", "/TrueType")
        document.xref_set_key(xref, "FirstChar", "32")
        document.xref_set_key(xref, "LastChar", "126")
        document.xref_set_key(
            xref, "Widths",
            "[" + " ".join(str(widths(codepoint)) for codepoint in range(32, 127)) + "]",
        )
        document.save(path)
    return path


def _export(tmp_path: Path, name: str, widths=_truncated, text_mode: str = "text"):
    source = _write_pdf(tmp_path / f"{name}.pdf", widths)
    run = run_import(str(source), mode="vector", overrides={"pages": "1", "text_mode": text_mode})
    output = tmp_path / f"{name}.dxf"
    result = export_to_dxf(
        run.extraction, str(output),
        DxfExportOptions(include_images=False, text_mode=text_mode, dxf_version="R2010"),
    )
    items = {item.text: item for item in run.extraction.pages[0].page_data.text_items}
    deliveries = {}
    for item in items.values():
        source_id = builder._source_id(item)
        deliveries[item.text] = next(
            delivery for delivery in result.text_deliveries if delivery["source_id"] == source_id
        )
    doc = ezdxf.readfile(output)
    run.close()
    return doc, result, items, deliveries


def _verified_attempt(delivery):
    return next(attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified")


def _outline_bbox(doc, delivery):
    points = []
    for handle in delivery["entity_handles"]:
        entity = doc.entitydb.get(handle)
        assert entity.dxftype() == "INSERT"
        for leaf in recursive_decompose([entity]):
            assert leaf.dxftype() == "SOLID"
            for vertex in (leaf.dxf.vtx0, leaf.dxf.vtx1, leaf.dxf.vtx2, leaf.dxf.vtx3):
                points.append((vertex.x, vertex.y))
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def test_fixture_is_the_real_case(tmp_path, resolve_to_installed_face):
    """No program in the PDF, stand-in glyph ids, and the PDF's own advances."""
    source = _write_pdf(tmp_path / "case.pdf")
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    items = {item.text: item for item in run.extraction.pages[0].page_data.text_items}
    assert set(items) == {"13/16", "Grade A572", "Plain 12", "1/4"}
    with TTFont(str(resolve_to_installed_face)) as program:
        cmap = program.getBestCmap()
        for item in items.values():
            assert item.font_name == PDF_FONT_NAME and item.font_asset is None
            assert builder._positioned_empty_font_program_proven(item)
            for character in item.source_char_layout:
                # MuPDF numbers its stand-in face, never the named font.
                assert character.glyph_id != program.getGlyphID(cmap[ord(character.text)])
    assert builder._positioned_fraction_layout(items["13/16"]) is not None
    assert builder._source_affine_layout(items["Grade A572"]) is not None   # unequal x/y scale
    assert builder._source_affine_layout(items["1/4"]) is not None          # fraction text
    assert builder._source_affine_layout(items["Plain 12"]) is not None
    run.close()


@pytest.mark.parametrize("text_mode", ["text", "labels", "3d_text", "glyphs", "geometry"])
def test_unembedded_font_text_is_outlined_not_rastered(tmp_path, resolve_to_installed_face, text_mode):
    doc, result, items, deliveries = _export(tmp_path, f"outlined-{text_mode}", text_mode=text_mode)
    assert not doc.modelspace().query("IMAGE")
    assert result.image_count == 0
    for text, delivery in deliveries.items():
        assert delivery["verified"] is True, (text, delivery["failure_reason"])
        assert delivery["final_representation"] == ("geometry" if text_mode == "geometry" else "glyphs"), text
        assert not delivery.get("degraded"), text
    for text in ("13/16", "Grade A572", "1/4", "Plain 12"):
        attempt = _verified_attempt(deliveries[text])
        evidence = attempt["evidence"]
        assert attempt["strategy"] == "positioned_source_glyph_outlines"
        assert evidence["installed_font_glyph_binding"] == "unicode_cmap_with_pdf_advance_proof"
        assert evidence["font_resolution_source"] == "installed_exact_font"
        proofs = evidence["installed_font_advance_proofs"]
        visible = [character for character in text if not character.isspace()]
        assert [proof["character"] for proof in proofs] == visible
        for proof in proofs:
            error = abs(proof["observed_advance_per_mille"] - proof["installed_advance_per_mille"])
            assert proof["verified"] is True
            assert error <= proof["tolerance_per_mille"] < 1.5
        assert evidence["installed_font_advance_max_error_per_mille"] < 1.0
        assert evidence["positioned_source_font_glyphs_verified"] is True
    assert _verified_attempt(deliveries["Plain 12"])["strategy"] == "positioned_source_glyph_outlines"


def test_outlines_sit_in_the_source_character_frames(tmp_path, resolve_to_installed_face):
    doc, _result, items, deliveries = _export(tmp_path, "placed")
    millimetre = 25.4 / 72.0
    for text in ("13/16", "Grade A572", "1/4"):
        item = items[text]
        x0, y0, x1, y1 = _outline_bbox(doc, deliveries[text])
        bx0, by0, bx1, by1 = item.bbox
        assert bx0 - 1e-6 <= x0 < x1 <= bx1 + 1e-6, text
        assert by0 - 1e-6 <= y0 < y1 <= by1 + 1e-6, text
    # The condensed word: 9 pt set 0.9 wide and 1.1 high. Its boxes are 1466
    # units tall and start 100 units right of each origin, in em units of 2048.
    x0, y0, x1, y1 = _outline_bbox(doc, deliveries["Grade A572"])
    em_x, em_y = 9 * 0.9 * millimetre, 9 * 1.1 * millimetre
    origin_x, baseline = 120 * millimetre, (200 - 60) * millimetre
    assert y0 == pytest.approx(baseline, abs=1e-4)
    assert y1 - y0 == pytest.approx(1466 / UNITS * em_y, abs=1e-4)
    assert x0 == pytest.approx(origin_x + 100 / UNITS * em_x, abs=1e-4)
    # Vertical text: reading upward, so the glyph tops point to -x.
    x0, y0, x1, y1 = _outline_bbox(doc, deliveries["1/4"])
    assert x1 == pytest.approx(230 * millimetre, abs=1e-4)
    assert x1 - x0 == pytest.approx(1466 / UNITS * 9 * millimetre, abs=1e-4)


@pytest.mark.parametrize("widths", [
    _truncated,
    lambda codepoint: round((569 if codepoint == 32 else _advance(codepoint)) * 1000 / UNITS),
    lambda codepoint: -(-(569 if codepoint == 32 else _advance(codepoint)) * 1000 // UNITS),
], ids=["truncated", "rounded", "rounded-up"])
def test_every_whole_unit_rounding_of_the_font_advance_is_accepted(
        tmp_path, resolve_to_installed_face, widths):
    doc, _result, _items, deliveries = _export(tmp_path, "rounding", widths=widths)
    assert not doc.modelspace().query("IMAGE")
    assert {delivery["final_representation"] for delivery in deliveries.values()} == {"glyphs"}


def test_a_face_with_other_advances_is_rejected_and_the_item_is_rastered(
        tmp_path, resolve_to_installed_face):
    """Same name, different metrics: not the source font. Raster stays the last resort."""
    def other_font(codepoint):
        return _truncated(codepoint) + (3 if chr(codepoint) in "1G" else 0)

    doc, result, items, deliveries = _export(tmp_path, "other-metrics", widths=other_font)
    rastered = {text for text, delivery in deliveries.items()
                if delivery["final_representation"] == "raster"}
    assert rastered == {"13/16", "Grade A572", "1/4", "Plain 12"}
    assert len(doc.modelspace().query("IMAGE")) == 4
    for text in sorted(rastered):
        delivery = deliveries[text]
        assert delivery["verified"] is True
        receipts = [attempt["evidence"]["installed_font_rejection"]
                    for attempt in delivery["attempts"]
                    if "installed_font_rejection" in attempt["evidence"]]
        assert receipts
        for receipt in receipts:
            proof = receipt["advance_width_proof"]
            assert receipt["reason"] == "source_advance_mismatch"
            assert receipt["character"] in "1G" and proof["character"] == receipt["character"]
            assert proof["verified"] is False
            error = abs(proof["observed_advance_per_mille"] - proof["installed_advance_per_mille"])
            assert error > proof["tolerance_per_mille"]
            assert 2.0 < error < 4.0
    # The isotropic string's digit must prove the same advance too.
    assert deliveries["Plain 12"]["final_representation"] == "raster"


def test_advance_proof_needs_the_source_character_frame(resolve_to_installed_face):
    """Without the original em frame there is nothing to measure: no proof."""
    from test_positioned_fraction_dxf_delivery import _positioned_fraction

    legacy = _positioned_fraction("vertical").source_char_layout[0]
    assert legacy.source_font_size_pdf is None
    with TTFont(str(resolve_to_installed_face)) as program:
        proof = builder._installed_font_advance_proof(legacy, program, "uni0031")
    assert proof["verified"] is False
    assert "no measurable source advance" in proof["reason"]


def test_advance_tolerance_is_one_glyph_space_unit_plus_frame_noise(tmp_path, resolve_to_installed_face):
    source = _write_pdf(tmp_path / "tolerance.pdf")
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    item = next(item for item in run.extraction.pages[0].page_data.text_items
                if item.text == "Grade A572")
    character = item.source_char_layout[0]
    assert builder._INSTALLED_ADVANCE_TOLERANCE_PER_MILLE == 1.0
    with TTFont(str(resolve_to_installed_face)) as program:
        proof = builder._installed_font_advance_proof(character, program, "uni0047")
        wrong = builder._installed_font_advance_proof(character, program, "uni0031")
    assert proof["verified"] is True
    assert proof["installed_advance_per_mille"] == pytest.approx(_advance(ord("G")) * 1000 / UNITS)
    assert proof["observed_advance_per_mille"] == pytest.approx(_truncated(ord("G")), abs=0.05)
    assert 1.0 < proof["tolerance_per_mille"] < 1.2
    assert wrong["verified"] is False   # the digit's advance, not this letter's
    assert math.isfinite(wrong["tolerance_per_mille"])
    run.close()


def test_blank_installed_space_inside_a_positioned_run_needs_no_advance(tmp_path, resolve_to_installed_face):
    """Word spacing owns a space's advance; an empty glyph draws nothing anywhere."""
    def wide_space(codepoint):
        return 900 if codepoint == 32 else _truncated(codepoint)

    doc, _result, _items, deliveries = _export(tmp_path, "space", widths=wide_space)
    assert deliveries["Grade A572"]["final_representation"] == "glyphs"
    proofs = _verified_attempt(deliveries["Grade A572"])["evidence"]["installed_font_advance_proofs"]
    assert " " not in [proof["character"] for proof in proofs]
    assert not doc.modelspace().query("IMAGE")


def test_resume_identity_covers_the_installed_font_rule(monkeypatch):
    """A page given raster patches under another rule is rebuilt, not resumed."""
    config = ImportConfig.auto()
    first, payload = dxf_import_engine._resume_options_identity(config, "R2010")
    assert payload["installed_font_rule"] == {
        "rule": "installed_face_named_by_pdf_bound_by_declared_advance",
        "advance_tolerance_per_mille": 1.0,
        "visible_character_advance_required": True,
        "original_character_frames_required": True,
    }
    monkeypatch.setattr(builder, "_INSTALLED_FONT_RULE", "another rule")
    second, _payload = dxf_import_engine._resume_options_identity(config, "R2010")
    assert second != first


@pytest.mark.parametrize("coincident_gid", [True, False])
def test_wrong_installed_advance_cannot_hide_behind_a_glyph_id(
        tmp_path, resolve_to_installed_face, coincident_gid):
    """A renderer and installed program can number unrelated glyphs equally."""
    from dataclasses import replace

    source = _write_pdf(tmp_path / "wrong-advance.pdf", lambda cp: _truncated(cp) + 30)
    with run_import(str(source), mode="vector", overrides={"pages": "1"}) as run:
        item = next(item for item in run.extraction.pages[0].page_data.text_items
                    if item.text == "Grade A572")
        character = item.source_char_layout[0]
        with TTFont(resolve_to_installed_face) as program:
            glyph = program.getBestCmap()[ord(character.text)]
            gid = program.getGlyphID(glyph)
        character = replace(character, glyph_id=gid if coincident_gid else gid + 1)
        proofs = []
        with pytest.raises(builder._RepresentationImpossible) as caught:
            builder._positioned_source_glyph_names(
                [character], builder._resolve_exact_font(PDF_FONT_NAME), advance_proofs=proofs)
        rejection = caught.value.installed_font_rejection
        assert rejection["reason"] == "source_advance_mismatch"
        assert rejection["advance_width_proof"]["verified"] is False
        assert proofs == []


def test_matching_installed_ids_still_record_each_visible_advance(tmp_path, resolve_to_installed_face):
    from dataclasses import replace

    source = _write_pdf(tmp_path / "matching-ids.pdf")
    with run_import(str(source), mode="vector", overrides={"pages": "1"}) as run:
        item = next(item for item in run.extraction.pages[0].page_data.text_items
                    if item.text == "Grade A572")
        with TTFont(resolve_to_installed_face) as program:
            cmap = program.getBestCmap()
            layout = [replace(char, glyph_id=program.getGlyphID(cmap[ord(char.text)]))
                      for char in item.source_char_layout]
        proofs = []
        names = builder._positioned_source_glyph_names(
            layout, builder._resolve_exact_font(PDF_FONT_NAME),
            empty_glyph_names=set(), advance_proofs=proofs)
        assert len(names) == len(layout)
        assert [proof["character_index"] for proof in proofs] == [
            i for i, char in enumerate(layout) if not char.text.isspace()]
        assert all(proof["verified"] for proof in proofs)


@pytest.mark.parametrize("mutation", [None, "proof", "font", "frame", "index", "false-success"])
def test_equal_id_mismatch_receipt_binds_fresh_font_and_source_frame(
        tmp_path, resolve_to_installed_face, mutation):
    import copy
    from dataclasses import replace

    source = _write_pdf(tmp_path / "equal-id-rejection.pdf", lambda cp: _truncated(cp) + 30)
    with run_import(str(source), mode="vector", overrides={"pages": "1"}) as run:
        item = next(item for item in run.extraction.pages[0].page_data.text_items
                    if item.text == "Grade A572")
        with TTFont(resolve_to_installed_face) as program:
            cmap = program.getBestCmap()
            item.source_char_layout = tuple(
                replace(char, glyph_id=program.getGlyphID(cmap[ord(char.text)]))
                for char in item.source_char_layout)
        builder.reset_text_styles()
        doc = ezdxf.new('R2010')
        outcome = builder.build_text(item, doc.modelspace(), 'TEXT', ImportConfig(text_mode='glyphs'),
            target_app='librecad', dxf_version='R2010', return_delivery_result=True)
        assert not outcome.verified and outcome.terminal_fallback_authorized
        assert not list(doc.modelspace())
        attempt = copy.deepcopy(next(a for a in outcome.attempts
                                     if 'installed_font_rejection' in a.evidence))
        receipt = attempt.evidence['installed_font_rejection']
        assert receipt['observed_glyph_id'] == receipt['resolved_glyph_id']
        assert builder._installed_font_rejection_bound_to_item(item, attempt)
        if mutation == 'proof':
            receipt['advance_width_proof']['installed_advance_per_mille'] += 10
        elif mutation == 'font':
            attempt.evidence['resolved_font_filename'] = str(tmp_path/'missing.ttf')
        elif mutation == 'frame':
            item.source_char_layout = (replace(item.source_char_layout[0], source_font_size_pdf=99),
                                       *item.source_char_layout[1:])
        elif mutation == 'index':
            receipt['character_index'] = 1
        elif mutation == 'false-success':
            receipt['advance_width_proof']['verified'] = True
        assert builder._installed_font_rejection_bound_to_item(item, attempt) is (mutation is None)


def _write_literal_pdf(path, content, *, affine=False):
    with fitz.open() as document:
        page = document.new_page(width=450, height=200)
        options = {"morph": (fitz.Point(40, 60), fitz.Matrix(.9, 1.1))} if affine else {}
        page.insert_text((40, 60), content, fontsize=9, **options)
        xref = page.get_fonts(full=True)[0][0]
        for key, value in (
            ("BaseFont", f"/{PDF_FONT_NAME}"), ("Subtype", "/TrueType"),
            ("FirstChar", "32"), ("LastChar", "255"),
            ("Widths", "[" + " ".join(str(_truncated(cp)) for cp in range(32, 256)) + "]"),
        ):
            document.xref_set_key(xref, key, value)
        document.save(path)
    return path


@pytest.mark.parametrize("mode", ["text", "labels", "3d_text", "glyphs", "geometry"])
@pytest.mark.parametrize("affine", [False, True])
@pytest.mark.parametrize("content", [r"ABC %%d \P \S1/2; {DEF}", "ABC ^", "Élév 90°"])
def test_literal_source_characters_survive_every_mode_and_dxf_reopen(
        tmp_path, resolve_to_installed_face, mode, affine, content):
    """No DXF-format interpretation may remove or replace original characters."""
    source = _write_literal_pdf(tmp_path / "literal.pdf", content, affine=affine)
    with run_import(str(source), mode="vector", overrides={"pages": "1", "text_mode": mode}) as run:
        [item] = run.extraction.pages[0].page_data.text_items
        assert item.text == content
        before = [(char.text, char.source_origin_pdf, char.target_quad)
                  for char in item.source_char_layout]
        assert "".join(row[0] for row in before) == content
        builder.reset_text_styles()
        output = tmp_path / "literal.dxf"
        result = export_to_dxf(run.extraction, str(output), DxfExportOptions(
            include_images=False, text_mode=mode, dxf_version="R2010"))
        [delivery] = result.text_deliveries
        assert delivery["verified"] and not delivery.get("degraded"), delivery
        assert delivery["final_representation"] == ("geometry" if mode == "geometry" else "glyphs")
        attempt = _verified_attempt(delivery)
        assert attempt["strategy"] == "positioned_source_glyph_outlines"
        evidence = attempt["evidence"]
        assert "".join(evidence["positioned_character_text"]) == content
        visible = [c for c in content if not c.isspace()]
        assert [proof["character"] for proof in evidence["installed_font_advance_proofs"]] == visible
        assert all(proof["verified"] for proof in evidence["installed_font_advance_proofs"])
        reopened = ezdxf.readfile(output)
        assert not reopened.audit().has_errors and not reopened.modelspace().query("IMAGE")
        entities = [reopened.entitydb[handle] for handle in delivery["entity_handles"]]
        if mode == "geometry":
            # This fixture's every visible glyph is exactly one rectangular face.
            assert len(entities) == 2 * len(visible)
            assert {e.dxftype() for e in entities} == {"SOLID"}
        else:
            [parent] = entities
            assert parent.dxftype() == "INSERT"
            assert len(reopened.blocks[parent.dxf.name].query("INSERT")) == len(visible)
        assert before == [(char.text, char.source_origin_pdf, char.target_quad)
                          for char in item.source_char_layout]


@pytest.mark.parametrize("mode", ["text", "labels", "3d_text", "glyphs", "geometry"])
@pytest.mark.parametrize("damage", ["missing", "origin"])
def test_isotropic_source_frame_absence_or_corruption_never_authorizes_fallback(
        tmp_path, resolve_to_installed_face, mode, damage):
    from dataclasses import replace
    source = _write_literal_pdf(tmp_path / "damaged-frame.pdf", "Plain 12")
    with run_import(str(source), mode="vector", overrides={"pages": "1"}) as run:
        [item] = run.extraction.pages[0].page_data.text_items
        if damage == "missing":
            item.source_char_layout = tuple(replace(c, source_font_size_pdf=None)
                                            for c in item.source_char_layout)
        else:
            first = item.source_char_layout[0]
            item.source_char_layout = (replace(first, source_origin_pdf=(
                first.source_origin_pdf[0] + 5, first.source_origin_pdf[1])), *item.source_char_layout[1:])
        builder.reset_text_styles()
        drawing = ezdxf.new("R2010")
        result = builder.build_text(item, drawing.modelspace(), "TEXT", ImportConfig(text_mode=mode),
            target_app="librecad", dxf_version="R2010", return_delivery_result=True)
        assert not result.verified and not result.terminal_fallback_authorized
        assert not list(drawing.modelspace())

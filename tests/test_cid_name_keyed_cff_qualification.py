"""PDF container labels never override original CFF program structure."""
from io import BytesIO
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont

from pdfcadcore import embedded_fonts as fonts


def test_public_name_keyed_cff_is_qualified_and_existing_converter_preserves_glyphs():
    original = fitz.Font("helv").buffer
    assert fonts._canonical_source_font_format(original, "cid") == "cff"
    source = CFFFontSet()
    source.decompile(BytesIO(original), None, isCFF2=False)
    top = source.topDictIndex[0]
    assert "ROS" not in top.rawDict and "FDArray" not in top.rawDict
    converted = fonts._cff_to_otf(original, "Nimbus Sans Regular")
    with TTFont(BytesIO(converted), lazy=False) as font:
        assert font.getGlyphOrder() == list(top.charset)
        assert fonts._fonttools_loadable(converted)
        assert font["CFF "].cff.topDictIndex[0].CharStrings.charStrings.keys() == top.CharStrings.charStrings.keys()


@pytest.mark.parametrize("program", [b"", b"not a font", b"\x02\x00\x04\x04", b"\x01\x00\x04\x04", b"\x01\x00\xff\x00bad"])
def test_wrong_malformed_or_cff2_program_is_not_relabelled(program):
    with pytest.raises(fonts.ExactFontSourceImpossible):
        fonts._canonical_source_font_format(program, "cid")


@pytest.mark.parametrize("raw_dict", [
    {"ROS": ("Adobe", "Identity", 0), "Private": object()},
    {"FDArray": object(), "Private": object()},
    {"FDSelect": object(), "Private": object()},
    {},
])
def test_cid_keyed_or_missing_private_program_is_not_qualified(monkeypatch, raw_dict):
    class Candidate:
        def decompile(self, *_args, **_kwargs):
            self.topDictIndex = [SimpleNamespace(rawDict=raw_dict, charset=[".notdef", "A"])]
    monkeypatch.setattr("fontTools.cffLib.CFFFontSet", Candidate)
    with pytest.raises(fonts.ExactFontSourceImpossible, match="CID-keyed"):
        fonts._canonical_source_font_format(b"\x01\x00\x04\x04", "cid")


@pytest.mark.parametrize("count", [0, 2])
def test_empty_or_multiple_font_sets_do_not_select_a_first_font(monkeypatch, count):
    class Candidate:
        def decompile(self, *_args, **_kwargs):
            self.topDictIndex = [SimpleNamespace(rawDict={"Private": object()}, charset=[".notdef"])] * count
    monkeypatch.setattr("fontTools.cffLib.CFFFontSet", Candidate)
    with pytest.raises(fonts.ExactFontSourceImpossible, match="exactly one"):
        fonts._canonical_source_font_format(b"\x01\x00\x04\x04", "cid")


def test_glyph_work_bound_applies_before_qualification(monkeypatch):
    monkeypatch.setattr(fonts, "MAX_EMBEDDED_FONT_GLYPHS", 2)
    with pytest.raises(fonts.ExactFontSourceImpossible, match="glyph limit"):
        fonts._canonical_source_font_format(fitz.Font("helv").buffer, "cid")


@pytest.mark.parametrize("order", [[], ["A"], ["A", ".notdef"]])
def test_missing_or_noncanonical_notdef_does_not_qualify(monkeypatch, order):
    class Candidate:
        def decompile(self, *_args, **_kwargs):
            self.topDictIndex = [SimpleNamespace(rawDict={"Private": object()}, charset=order)]
    monkeypatch.setattr("fontTools.cffLib.CFFFontSet", Candidate)
    with pytest.raises(fonts.ExactFontSourceImpossible, match="canonical glyph order"):
        fonts._canonical_source_font_format(b"\x01\x00\x04\x04", "cid")


def test_original_empty_space_proof_uses_canonical_cff_not_container_label():
    with fitz.open() as document:
        page = document.new_page(width=200, height=100)
        page.insert_font(fontname="F1", fontbuffer=fitz.Font("helv").buffer)
        page.insert_text((10, 50), "A B", fontname="F1")
        catalog = fonts.EmbeddedFontCatalog.from_page(page, 1)
        assert catalog._candidates
        asset = catalog._candidates[0]
        assert asset.source_format == "cff" and asset.source_inventory_format == "cid"
        assert catalog._original_space_is_empty(asset) is True

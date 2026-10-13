"""A symbolic subset's observed original space ID can prove its empty ink."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from types import MappingProxyType

import pymupdf as fitz
import pytest
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

from pdfcadcore import embedded_fonts
from pdfcadcore.embedded_fonts import EmbeddedFontCatalog
from pdfcadcore.primitive_extractor import _raw_text_with_source_quads


def symbolic_subset_pdf(font_path, *, visible_space=False, observed_space=True):
    """Keep CID/ToUnicode/source glyphs while removing the font's Unicode cmap."""
    font = TTFont(font_path)
    space_name = font.getBestCmap()[32]
    space_id = font.getGlyphID(space_name)
    if visible_space:
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0)); pen.lineTo((500, 0)); pen.lineTo((500, 700)); pen.closePath()
        font["glyf"][space_name] = pen.glyph()
    original = BytesIO()
    font.save(original)
    pdf = fitz.open()
    page = pdf.new_page(width=240, height=160)
    page.insert_font(fontname="F1", fontbuffer=original.getvalue())
    if observed_space:
        page.insert_text((20, 40), "A B", fontname="F1", fontsize=12)
    page.insert_text((20, 80), "A", fontname="F1", fontsize=12)
    page.insert_text((33, 80), "B", fontname="F1", fontsize=12)

    table = newTable("cmap")
    table.tableVersion = 0
    symbol = CmapSubtable.newSubtable(4)
    symbol.platformID, symbol.platEncID, symbol.language = 3, 0, 0
    symbol.cmap = {0xF000 + i: name for i, name in enumerate(font.getGlyphOrder())}
    table.tables = [symbol]
    font["cmap"] = table
    font["post"].formatType = 3.0
    symbolic = BytesIO()
    font.save(symbolic)
    font.close()
    stream_xrefs = [int(pdf.xref_get_key(xref, "FontFile2")[1].split()[0])
                    for xref in range(1, pdf.xref_length())
                    if pdf.xref_get_key(xref, "FontFile2")[0] == "xref"]
    assert len(stream_xrefs) == 1
    pdf.update_stream(stream_xrefs[0], symbolic.getvalue())
    encoded = pdf.tobytes()
    pdf.close()
    return fitz.open(stream=encoded, filetype="pdf"), space_id


def prepared_catalog(pdf):
    page = pdf[0]
    raw = _raw_text_with_source_quads(page)
    catalog = EmbeddedFontCatalog.from_page(page, 1, source_text=raw)
    spans = [s for b in raw["blocks"] for line in b.get("lines", ()) for s in line["spans"]]
    synthetic = next(s for s in spans if any(c.get("source_synthetic_spacing") for c in s["chars"]))
    return catalog, synthetic


def test_symbolic_subset_uses_an_observed_space_id_and_original_empty_glyph(deterministic_exact_font):
    pdf, space_id = symbolic_subset_pdf(deterministic_exact_font)
    try:
        original_objects = [(pdf.xref_object(i), pdf.xref_stream_raw(i)) for i in range(1, pdf.xref_length())]
        catalog, span = prepared_catalog(pdf)
        assert any(char[0] == 32 and char[1] == space_id
                   for trace in pdf[0].get_texttrace() for char in trace["chars"])
        asset = catalog._candidates[0]
        with TTFont(BytesIO(asset.source_bytes)) as font:
            assert 32 not in (font.getBestCmap() or {})
            assert "space" not in font.getGlyphOrder()
        bound, failure = catalog.resolve_span(span["font"], span["chars"])
        assert failure is None
        assert bound.source_sha256 == sha256(asset.source_bytes).hexdigest()
        assert bound.source_binding_method == "original_textpage_character_program_sha256"
        assert any(c.get("source_synthetic_spacing") is True for c in span["chars"])
        assert [(pdf.xref_object(i), pdf.xref_stream_raw(i)) for i in range(1, pdf.xref_length())] == original_objects
    finally:
        pdf.close()


@pytest.mark.parametrize("visible,observed", [(True, True), (False, False)])
def test_visible_or_unobserved_source_space_cannot_certify_inferred_spacing(
    deterministic_exact_font, visible, observed
):
    pdf, _ = symbolic_subset_pdf(deterministic_exact_font,
                                visible_space=visible, observed_space=observed)
    try:
        catalog, span = prepared_catalog(pdf)
        bound, failure = catalog.resolve_span(span["font"], span["chars"])
        assert bound is None
        assert failure.reason == "synthetic_space_zero_ink_unverified"
    finally:
        pdf.close()


def test_family_only_trace_mapping_cannot_replace_original_program_binding(
    deterministic_exact_font, monkeypatch
):
    pdf, _ = symbolic_subset_pdf(deterministic_exact_font)
    try:
        original = embedded_fonts._page_program_glyph_maps
        def without_program_map(*args):
            original(*args)  # Retain real inferred-spacing occurrence flags.
            return {}, set()
        monkeypatch.setattr(embedded_fonts, "_page_program_glyph_maps", without_program_map)
        catalog, span = prepared_catalog(pdf)
        assert catalog._candidates
        bound, failure = catalog.resolve_span(span["font"], span["chars"])
        assert bound is None
        assert failure.reason == "synthetic_space_zero_ink_unverified"
    finally:
        pdf.close()


def test_ambiguous_original_program_does_not_gain_a_space_proof(deterministic_exact_font, monkeypatch):
    pdf, _ = symbolic_subset_pdf(deterministic_exact_font)
    try:
        original = embedded_fonts._page_program_glyph_maps
        def ambiguous(*args):
            maps, _ = original(*args)
            return maps, set(maps)
        monkeypatch.setattr(embedded_fonts, "_page_program_glyph_maps", ambiguous)
        catalog = EmbeddedFontCatalog.from_page(pdf[0], 1)
        assert not catalog._candidates
        assert not catalog._source_space_glyph_ids
    finally:
        pdf.close()


@pytest.mark.parametrize("glyph_id", [True, -1, 1000, 65535, 10**10])
def test_observed_space_glyph_id_is_finite_bounded_and_not_a_boolean(deterministic_exact_font, glyph_id):
    pdf, _ = symbolic_subset_pdf(deterministic_exact_font)
    try:
        catalog, _span = prepared_catalog(pdf)
        asset = catalog._candidates[0]
        catalog._source_space_glyph_ids = MappingProxyType({asset.source_sha256: glyph_id})
        assert not catalog._original_space_is_empty(asset)
    finally:
        pdf.close()


def test_changed_original_bytes_cannot_reuse_a_cached_space_proof(deterministic_exact_font):
    pdf, _ = symbolic_subset_pdf(deterministic_exact_font)
    try:
        catalog, _span = prepared_catalog(pdf)
        asset = catalog._candidates[0]
        assert catalog._original_space_is_empty(asset)
        assert not catalog._original_space_is_empty(replace(asset, source_bytes=b"wrong original program"))
        assert not catalog._original_space_is_empty(replace(asset, source_sha256="0" * 64))
    finally:
        pdf.close()

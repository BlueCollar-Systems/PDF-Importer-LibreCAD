"""Original renderer character programs disambiguate same-name PDF subsets."""
from collections import deque
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from pdfcadcore.embedded_fonts import EmbeddedFontCatalog, source_control_zero_ink_proof
from pdfcadcore.primitive_extractor import (
    _raw_text_with_source_quads, _source_character_font_digest,
    _source_font_occurrence_keys, extract_page,
)


def subset_pdf(font_path):
    pdf = fitz.open()
    page = pdf.new_page(width=240, height=160)
    for resource, visible, hidden, origin in (
        ("F1", "A", "B", (20, 40)), ("F2", "B", "A", (20, 90)),
    ):
        font = TTFont(font_path)
        missing = font.getBestCmap()[ord(hidden)]
        font["glyf"][missing] = TTGlyphPen(None).glyph()
        font["hmtx"].metrics[missing] = (0, 0)
        output = BytesIO()
        font.save(output)
        font.close()
        page.insert_font(fontname=resource, fontbuffer=output.getvalue())
        page.insert_text(origin, visible * 2, fontname=resource, fontsize=16)
    return pdf


@pytest.mark.parametrize("in_form", [False, True])
def test_complementary_subsets_bind_actual_character_programs(deterministic_exact_font, in_form):
    source = subset_pdf(deterministic_exact_font)
    pdf = fitz.open()
    if in_form:
        page = pdf.new_page(width=400, height=200)
        page.show_pdf_page(fitz.Rect(20, 10, 260, 170), source, 0)
    else:
        pdf.insert_pdf(source)
        page = pdf[0]
    catalog = EmbeddedFontCatalog.from_page(page, 1)
    raw = _raw_text_with_source_quads(page)
    items = extract_page(page, 1).text_items
    assert len(items) == 2
    assert len({item.font_name for item in items}) == 1
    assert catalog.for_span(items[0].font_name) is None
    assert catalog.failure_for_span(items[0].font_name).reason == "ambiguous_exact_embedded_font_match"
    expected = {
        sha256(pdf.extract_font(rec[0])[3]).hexdigest(): rec[0]
        for rec in page.get_fonts(full=True)
    }
    assert len(expected) == 2
    for item in items:
        asset = item.font_asset
        assert item.font_failure is None
        assert asset.source_xref == expected[asset.source_sha256]
        assert asset.source_binding_method == "original_textpage_character_program_sha256"
        assert asset.source_program_candidates == ((asset.source_xref, asset.resource_name),)
        assert len(item.source_char_layout) == 2
        assert all(c.source_font_binding_verified for c in item.source_char_layout)
        assert all(c.source_font_program_sha256 == asset.source_sha256 for c in item.source_char_layout)
        assert all(c.source_font_character_codepoint == ord(item.text[0]) for c in item.source_char_layout)
        font = TTFont(BytesIO(asset.usable_bytes))
        assert font["glyf"][font.getBestCmap()[ord(item.text[0])]].numberOfContours > 0
        font.close()
    # Copying a borrowed font buffer must not empty or change renderer state.
    assert _raw_text_with_source_quads(page) == raw
    assert page.get_pixmap().samples == page.get_pixmap().samples
    pdf.close()
    source.close()


def test_mixed_partial_and_wrong_program_spans_fail_closed(deterministic_exact_font):
    pdf = subset_pdf(deterministic_exact_font)
    page = pdf[0]
    catalog = EmbeddedFontCatalog.from_page(page, 1)
    spans = [s for b in _raw_text_with_source_quads(page)["blocks"]
             for line in b.get("lines", ()) for s in line["spans"]]
    name = spans[0]["font"]
    a, b = spans[0]["chars"][0], spans[1]["chars"][0]
    for chars, reason in (
        ([a, b], "mixed_source_font_programs_in_span"),
        ([a, {**a, "source_font_program_sha256": ""}], "incomplete_source_font_character_binding"),
        ([{**a, "source_font_binding_verified": False}], "incomplete_source_font_character_binding"),
        ([{**a, "source_font_program_sha256": "0" * 64}], "source_character_font_program_not_in_pdf_inventory"),
    ):
        asset, failure = catalog.resolve_span(name, chars)
        assert asset is None
        assert failure.reason == reason
    assert catalog.resolve_span(name, [{}])[0] is None
    pdf.close()


def test_identical_program_resources_report_all_candidates(deterministic_exact_font):
    pdf = subset_pdf(deterministic_exact_font)
    page = pdf[0]
    original = EmbeddedFontCatalog.from_page(page, 1)
    asset = original._candidates[0]
    catalog = EmbeddedFontCatalog(1, {}, {}, [asset, replace(asset, source_xref=999, resource_name="Another")])
    char = {"source_font_program_sha256": asset.source_sha256, "source_font_binding_verified": True}
    bound, failure = catalog.resolve_span(asset.span_font_name, [char])
    assert failure is None
    assert bound.source_program_candidates == tuple(sorted(((asset.source_xref, asset.resource_name), (999, "Another"))))
    pdf.close()


def test_coincident_character_occurrences_require_complete_same_program_census():
    key = ("A", 1.25, 2.5)
    raw = {"blocks": [{"type": 0, "lines": [{"spans": [{"chars": [
        {"c": "A", "origin": (1.25, 2.5)}, {"c": "A", "origin": (1.25, 2.5)}]}]}]}]}
    def queue(*digests):
        return {key: deque((None, {"source_font_program_sha256": d}) for d in digests)}
    assert _source_font_occurrence_keys(raw, queue("a", "a")) == {key}
    for values in (("a", "b"), ("a",), ("a", "a", "a"), ("", "")):
        assert _source_font_occurrence_keys(raw, queue(*values)) == set()


def test_optional_buffer_copy_api_and_work_bound_are_fail_closed(monkeypatch):
    from pdfcadcore import embedded_fonts
    buffer = SimpleNamespace(this=123, len=4)
    font = SimpleNamespace(buffer=buffer)
    calls = []
    api = SimpleNamespace(ll_fz_buffer_extract_copy=lambda b: calls.append(b) or b"font")
    cache = {}
    assert _source_character_font_digest(font, api, cache) == sha256(b"font").hexdigest()
    assert _source_character_font_digest(font, api, cache) == sha256(b"font").hexdigest()
    assert calls == [buffer]
    assert _source_character_font_digest(font, SimpleNamespace(), {}) == ""
    monkeypatch.setattr(embedded_fonts, "MAX_EMBEDDED_FONT_BYTES", 3)
    assert _source_character_font_digest(font, api, {}) == ""
    assert calls == [buffer]


def test_visible_annotation_font_is_bound_to_its_own_appearance_resource():
    pdf = fitz.open()
    page = pdf.new_page(width=240, height=160)
    page.insert_text((20, 30), "Page", fontname="cour")
    annotation = page.add_freetext_annot(fitz.Rect(20, 50, 180, 100), "NOTE", fontsize=16, fontname="helv")
    annotation.update()
    # Reopen original bytes so normal annotation appearance is finalized.
    original = pdf.tobytes()
    pdf.close()
    with fitz.open(stream=original, filetype="pdf") as document:
        page = document[0]
        def objects():
            return tuple((document.xref_object(i), document.xref_stream_raw(i))
                         for i in range(1, document.xref_length()))
        original_objects = objects()
        assert not any(rec[3] == "Helvetica" for rec in page.get_fonts(full=True))
        catalog = EmbeddedFontCatalog.from_page(page, 1)
        assert catalog.for_span("Helvetica") is None
        item = next(t for t in extract_page(page, 1).text_items if t.text == "NOTE")
        assert item.font_failure is None
        asset = item.font_asset
        assert asset.source_origin == "pdf_base14_renderer_font"
        assert document.extract_font(asset.source_xref)[0] == "Helvetica"
        assert asset.source_binding_method == "original_textpage_character_program_sha256"
        assert all(c.source_font_program_sha256 == asset.source_sha256 for c in item.source_char_layout)
        assert all(c.source_font_binding_verified for c in item.source_char_layout)
        assert objects() == original_objects


def control_item():
    pdf = fitz.open()
    page = pdf.new_page(width=160, height=120)
    page.insert_text((30, 30), "A", fontname="cour", fontsize=11)
    page.insert_text((30, 60), "X", fontname="cour", fontsize=11)
    pdf.update_stream(page.get_contents()[-1], b"BT /cour 11 Tf 30 60 Td <0a> Tj ET")
    item = next(t for t in extract_page(page, 1).text_items if t.text == "\n")
    pdf.close()
    return item


def test_unencoded_control_keeps_original_semantics_and_exact_empty_glyph_proof():
    item = control_item()
    char = item.source_char_layout[0]
    assert char.source_font_character_codepoint == 10
    assert char.source_glyph_trace_codepoint == 0xFFFD
    assert char.glyph_id == 0
    proof = source_control_zero_ink_proof(item)
    assert proof["glyph_bounds"] is None and proof["original_glyph_bounds"] is None
    assert proof["characters"] == [{"codepoint": 10, "trace_codepoint": 65533,
        "origin_pdf": list(char.source_origin_pdf), "advance_width": char.advance_width}]
    assert proof["source_program_sha256"] == item.font_asset.source_sha256
    for mutation in (
        {"glyph_id": None}, {"glyph_id": 1}, {"source_glyph_trace_codepoint": None},
        {"source_font_binding_verified": False}, {"source_font_program_sha256": "0" * 64},
    ):
        assert source_control_zero_ink_proof(replace(item, source_char_layout=(replace(char, **mutation),))) is None
    assert source_control_zero_ink_proof(replace(item, text=" ")) is None


@pytest.mark.parametrize("mutated", ["original", "usable"])
def test_visible_notdef_cannot_be_certified_as_zero_ink(mutated, deterministic_exact_font):
    item = control_item()
    font = TTFont(deterministic_exact_font)
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0)); pen.lineTo((500, 0)); pen.lineTo((500, 700)); pen.closePath()
    font["glyf"][font.getGlyphOrder()[0]] = pen.glyph()
    output = BytesIO()
    font.save(output)
    font.close()
    data = output.getvalue()
    digest = sha256(data).hexdigest()
    if mutated == "original":
        asset = replace(item.font_asset, source_bytes=data, source_sha256=digest, source_format="ttf")
        item = replace(item, font_asset=asset, source_char_layout=tuple(
            replace(c, source_font_program_sha256=digest) for c in item.source_char_layout))
    else:
        item = replace(item, font_asset=replace(item.font_asset, usable_bytes=data, usable_sha256=digest))
    assert source_control_zero_ink_proof(item) is None


def test_nonembedded_custom_font_keeps_original_absence_proof():
    with fitz.open() as pdf:
        page = pdf.new_page(width=160, height=120)
        page.insert_text((20, 40), "Example", fontname="helv")
        font_xref = page.get_fonts()[0][0]
        pdf.xref_set_key(font_xref, "BaseFont", "/UnembeddedFixtureSans")
        original = pdf.tobytes()
    with fitz.open(stream=original, filetype="pdf") as pdf:
        item = extract_page(pdf[0], 1).text_items[0]
        # MuPDF really did substitute a renderer program, but it is not an
        # embedded source program and must not erase the PDF absence proof.
        assert all(c.source_font_program_sha256 for c in item.source_char_layout)
        assert item.font_asset is None
        failure = item.font_failure
        assert failure.source_xref == font_xref
        assert failure.span_font_name == "UnembeddedFixtureSans"
        assert failure.reason == "embedded_font_asset_build_failed"
        assert failure.detail == "embedded font stream is empty"
        assert failure.proof_category == "source_specific_impossibility"

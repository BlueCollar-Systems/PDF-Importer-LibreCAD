"""Failed exact programs retain evidence without borrowing font-name identity."""
from dataclasses import replace
from hashlib import sha256

import pymupdf as fitz
import pytest

from pdfcadcore.embedded_fonts import (
    EmbeddedFontAsset, EmbeddedFontCatalog, EmbeddedFontFailure,
)
from pdfcadcore.primitive_extractor import extract_page


PROGRAM = "ab" * 32


def failure(**changes):
    original = EmbeddedFontFailure(
        1, "Nimbus Sans Regular", "embedded_font_asset_build_failed", 7,
        "ExactFontSourceImpossible", "unsupported embedded font format: cid",
        "source_specific_impossibility",
    )
    return replace(original, **changes)


def character(**changes):
    return {"source_font_program_sha256": PROGRAM,
            "source_font_binding_verified": True, **changes}


def catalog(*failures, candidates=()):
    return EmbeddedFontCatalog(
        1, {}, {row.span_font_name: row for row in failures}, candidates,
        [(PROGRAM, row) for row in failures],
    )


def test_verified_same_program_retains_failure_across_observed_name_spelling():
    original = failure()
    asset, actual = catalog(original).resolve_span("NimbusSans-Regular", [character()])
    assert asset is None
    assert actual == replace(original, span_font_name="NimbusSans-Regular")
    assert original.span_font_name == "Nimbus Sans Regular"


@pytest.mark.parametrize("characters,reason", [
    ([character(source_font_program_sha256="cd" * 32)], "source_character_font_program_not_in_pdf_inventory"),
    ([character(source_font_program_sha256="")], "incomplete_source_font_character_binding"),
    ([{}], "incomplete_source_font_character_binding"),
    ([], "incomplete_source_font_character_binding"),
    ([character(source_font_binding_verified=False)], "incomplete_source_font_character_binding"),
    ([character(), character(source_font_program_sha256="cd" * 32)], "mixed_source_font_programs_in_span"),
    ([character(), character(source_font_program_sha256="")], "incomplete_source_font_character_binding"),
])
def test_missing_different_mixed_or_unverified_program_cannot_borrow_failure(characters, reason):
    for observed in ("Nimbus Sans Regular", "NimbusSans-Regular"):
        asset, actual = catalog(failure()).resolve_span(observed, characters)
        assert asset is None
        assert actual.reason == reason
        assert actual.proof_category == "source_font_binding_unverified_for_item"


@pytest.mark.parametrize("changes", [
    {"source_xref": 8}, {"detail": "different source limitation"},
    {"proof_category": "runtime_capability_unavailable_for_item"},
])
def test_distinct_failure_evidence_for_the_same_program_is_ambiguous(changes):
    asset, actual = catalog(failure(), failure(**changes)).resolve_span("NimbusSans-Regular", [character()])
    assert asset is None
    assert actual.reason == "ambiguous_source_font_program_failure"
    assert actual.proof_category == "source_font_binding_unverified_for_item"


def test_identical_repeated_inventory_failure_does_not_invent_ambiguity():
    asset, actual = catalog(failure(), failure()).resolve_span("NimbusSans-Regular", [character()])
    assert asset is None
    assert actual == failure(span_font_name="NimbusSans-Regular")


@pytest.mark.parametrize("changes", [
    {"source_xref": None}, {"source_xref": 0}, {"source_xref": True},
    {"page_number": 2}, {"reason": "unknown_source_failure"},
])
def test_page_resource_and_failure_kind_must_be_bound(changes):
    asset, actual = catalog(failure(**changes)).resolve_span("NimbusSans-Regular", [character()])
    assert asset is None
    assert actual.reason == "source_font_failure_identity_unverified"
    assert actual.proof_category == "source_font_binding_unverified_for_item"


def supported_asset():
    return EmbeddedFontAsset(
        1, "Inventory Name", "Inventory Name", 4, "F1", "TrueType", "Identity-H",
        "ttf", "embedded_pdf_font", b"source", PROGRAM, "ttf", b"usable", "cd" * 32,
        "sha256:" + "cd" * 32,
    )


def test_supported_same_program_happy_path_and_candidate_resources_are_unchanged():
    original = supported_asset()
    other = replace(original, source_xref=5, resource_name="F2")
    supported = EmbeddedFontCatalog(1, {}, {}, [original, other])
    asset, actual = supported.resolve_span("Observed Different Spelling", [character()])
    assert actual is None
    assert asset.source_sha256 == PROGRAM
    assert asset.source_binding_method == "original_textpage_character_program_sha256"
    assert asset.source_program_candidates == ((4, "F1"), (5, "F2"))


def test_successful_asset_and_conflicting_failed_build_cannot_select_by_name():
    asset, actual = catalog(failure(), candidates=[supported_asset()]).resolve_span("NimbusSans-Regular", [character()])
    assert asset is None
    assert actual.reason == "ambiguous_source_font_program_failure"


def test_empty_stream_absence_keeps_renderer_substitute_actualtext_route():
    absent = failure(detail="embedded font stream is empty")
    isolated = EmbeddedFontCatalog(1, {}, {absent.span_font_name: absent})
    asset, actual = isolated.resolve_span(absent.span_font_name, [character(
        source_font_program_sha256="cd" * 32, source_font_binding_verified=False)])
    assert asset is None
    assert actual is absent


def test_empty_stream_absence_cannot_override_a_known_program_binding():
    original = supported_asset()
    absent = failure(span_font_name=original.span_font_name, detail="embedded font stream is empty")
    mixed = EmbeddedFontCatalog(1, {}, {absent.span_font_name: absent}, [original])
    asset, actual = mixed.resolve_span(absent.span_font_name, [character()])
    assert actual is None
    assert asset.source_sha256 == PROGRAM
    asset, actual = mixed.resolve_span(absent.span_font_name, [character(source_font_binding_verified=False)])
    assert asset is None
    assert actual.reason == "incomplete_source_font_character_binding"


def test_runtime_failure_category_is_preserved_without_claiming_source_impossibility():
    original = failure(proof_category="runtime_capability_unavailable_for_item", error_type="ImportError")
    asset, actual = catalog(original).resolve_span("NimbusSans-Regular", [character()])
    assert asset is None
    assert actual.proof_category == "runtime_capability_unavailable_for_item"
    assert actual.error_type == "ImportError"


def test_unrelated_failed_program_does_not_replace_proved_type3_absence():
    type3 = EmbeddedFontFailure(
        1, "Type3Observed", "embedded_type3_font_program_unavailable", None,
        "ExactFontSourceImpossible", "PDF Type3 resource has no extractable font program",
        "source_specific_impossibility",
    )
    other = failure()
    mixed = EmbeddedFontCatalog(1, {}, {type3.span_font_name: type3, other.span_font_name: other},
                                program_failures=[(PROGRAM, other)])
    asset, actual = mixed.resolve_span("Type3Observed", [{}])
    assert asset is None
    assert actual is type3
    # That independent absence does not become a name-only alias for CID.
    _, unresolved = mixed.resolve_span("NimbusSans-Regular", [{}])
    assert unresolved.reason == "incomplete_source_font_character_binding"


def test_real_public_cid_labeled_name_keyed_font_binds_the_original_cff_program():
    document = fitz.open()
    try:
        page = document.new_page(width=240, height=160)
        page.insert_font(fontname="SyntheticControlFont", fontbuffer=fitz.Font("helv").buffer)
        page.insert_text((15, 130), "BLENDER CONTROL", fontname="SyntheticControlFont", fontsize=10)
        item = extract_page(page, 1).text_items[0]
        record = page.get_fonts(full=True)[0]
        expected = sha256(document.extract_font(record[0])[3]).hexdigest()
        assert item.font_failure is None
        assert item.font_asset.source_format == "cff"
        assert item.font_asset.source_inventory_format == record[1] == "cid"
        assert item.font_asset.source_inventory_type == record[2] == "Type0"
        assert item.font_asset.span_font_name == item.font_name
        assert item.font_asset.source_xref == record[0]
        assert item.font_asset.source_sha256 == expected
        assert all(c.source_font_binding_verified and c.source_font_program_sha256 == expected
                   for c in item.source_char_layout)
    finally:
        document.close()

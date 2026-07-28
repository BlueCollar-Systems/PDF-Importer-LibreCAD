from __future__ import annotations

import hashlib

from pdfcadcore.page_visual import (
    page_visual_fallback_proof_verified,
    page_visual_proof_digest,
)
from pdfcadcore.source_ink import (
    SOURCE_INK_EVIDENCE_AUTHORITY,
    SOURCE_INK_EVIDENCE_SCHEMA,
    source_ink_evidence_digest,
    source_ink_evidence_verified,
)


def _page_visual_proof(source_item_id: str) -> dict:
    pdf_sha256 = "a" * 64
    raw_digest = "b" * 64
    importer_identity = "test-host/1"
    proof = {
        "schema": "pdf_page_visual_fallback_proof_v1",
        "page_specific_proven_impossible": True,
        "pdf_sha256": pdf_sha256,
        "page_number": 2,
        "source_item_id": source_item_id,
        "requested_type": "labels",
        "attempted_type": "labels",
        "reason_code": "no_canonical_text_source_items",
        "attempted_sources_complete": True,
        "cleanup_complete": True,
        "created_entity_ids": [],
        "removed_entity_ids": [],
        "importer_identity": importer_identity,
        "evidence": {
            "text_dictionary_present": True,
            "canonical_source_item_count": 0,
            "source_item_ids": [],
            "source_scope": "page_visual",
            "visible_source_text_found": False,
            "raw_text_dictionary_sha256": raw_digest,
            "raw_text_block_count": 1,
        },
        "attempted_source_results": [
            {
                "source": "pymupdf_raw_text_dictionary",
                "outcome": "no_canonical_text_source_items",
                "importer_identity": importer_identity,
                "pdf_sha256": pdf_sha256,
                "page_number": 2,
                "source_item_id": source_item_id,
                "source_item_ids": [],
                "canonical_source_item_count": 0,
                "raw_text_dictionary_sha256": raw_digest,
                "visible_source_text_found": False,
            }
        ],
    }
    proof["proof_sha256"] = page_visual_proof_digest(proof)
    return proof


def test_page_visual_proof_accepts_exact_host_neutral_source_identity() -> None:
    source_item_id = "page_visual:2"
    proof = _page_visual_proof(source_item_id)

    assert page_visual_fallback_proof_verified(
        proof,
        expected_pdf_sha256="a" * 64,
        expected_page_number=2,
        expected_source_scope_id=source_item_id,
        expected_requested_type="labels",
        expected_attempted_type="labels",
        expected_raw_text_dictionary_sha256="b" * 64,
    )


def _source_ink_evidence(source_item_id: str) -> tuple[dict, dict]:
    font_identity = {"raw_name": "Exact Test", "normalized_key": "exact test"}
    source_text = " "
    evidence = {
        "schema": SOURCE_INK_EVIDENCE_SCHEMA,
        "authority": SOURCE_INK_EVIDENCE_AUTHORITY,
        "pdf_sha256": "c" * 64,
        "page_number": 2,
        "source_item_id": source_item_id,
        "source_text": source_text,
        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "font_identity": font_identity,
        "all_characters_physically_resolved": True,
        "classification": "zero_visible_ink",
        "zero_ink_characters_layout_only": True,
        "font_asset_bindings": [],
        "glyph_id_sequence": [None],
        "characters": [
            {
                "source_index": 0,
                "character": source_text,
                "authority": "pymupdf_rawdict_synthetic_character",
                "physically_resolved": True,
                "zero_visible_ink": True,
                "layout_only_zero_ink": True,
                "synthetic": True,
                "glyph_id": None,
                "font_asset_binding": None,
            }
        ],
    }
    evidence["evidence_sha256"] = source_ink_evidence_digest(evidence)
    expected = {
        "expected_pdf_sha256": "c" * 64,
        "expected_page_number": 2,
        "expected_source_item_id": source_item_id,
        "expected_source_text": source_text,
        "expected_font_identity": font_identity,
        "expected_font_asset_bindings": [],
        "expected_glyph_id_sequence": [None],
    }
    return evidence, expected


def test_source_ink_proof_accepts_exact_host_neutral_source_identity() -> None:
    evidence, expected = _source_ink_evidence("text_span:2:17")

    assert source_ink_evidence_verified(evidence, **expected)


def test_shared_proofs_reject_padded_source_identity() -> None:
    padded = " page:2:text:17 "
    evidence, expected = _source_ink_evidence(padded)
    assert not source_ink_evidence_verified(evidence, **expected)

    proof = _page_visual_proof(" page_visual:2 ")
    assert not page_visual_fallback_proof_verified(
        proof,
        expected_pdf_sha256="a" * 64,
        expected_page_number=2,
        expected_source_scope_id=" page_visual:2 ",
        expected_requested_type="labels",
        expected_attempted_type="labels",
        expected_raw_text_dictionary_sha256="b" * 64,
    )

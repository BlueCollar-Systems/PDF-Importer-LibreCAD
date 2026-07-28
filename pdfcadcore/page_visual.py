"""Page-scoped proof for visual fallback when a PDF exposes no text item.

A page is deliberately not treated as a semantic text item.  The proof binds
the exact PDF/page observation which makes structural text representations
unavailable, while allowing a verified full-page raster to preserve appearance.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, Optional


PAGE_VISUAL_FALLBACK_PROOF_SCHEMA = "pdf_page_visual_fallback_proof_v1"
PAGE_VISUAL_REASON_CODE = "no_canonical_text_source_items"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _canonical_value(value: Any) -> Any:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("raw text dictionary contains a non-finite number")
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        return {
            "__bytes_length__": len(payload),
            "__bytes_sha256__": hashlib.sha256(payload).hexdigest(),
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("raw text dictionary contains a non-string key")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    raise ValueError("raw text dictionary contains an unsupported value")


def raw_text_dictionary_digest(raw_text_dictionary: Dict[str, Any]) -> str:
    """Digest PyMuPDF rawdict data, including image bytes without embedding them."""

    if not isinstance(raw_text_dictionary, dict):
        raise ValueError("raw text dictionary must be a dictionary")
    payload = json.dumps(
        _canonical_value(raw_text_dictionary),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def page_visual_proof_digest(proof: Dict[str, Any]) -> str:
    """Return a canonical digest for one page-scoped impossibility proof."""

    payload = dict(proof or {})
    payload.pop("proof_sha256", None)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def page_visual_fallback_proof_verified(
    proof: Any,
    *,
    expected_pdf_sha256: str,
    expected_page_number: int,
    expected_source_scope_id: str,
    expected_requested_type: str,
    expected_attempted_type: str,
    expected_raw_text_dictionary_sha256: Optional[str] = None,
) -> bool:
    """Verify one proof against independently held PDF/page/ladder identity."""

    if (
        not isinstance(proof, dict)
        or not isinstance(expected_pdf_sha256, str)
        or _SHA256_RE.fullmatch(expected_pdf_sha256) is None
        or type(expected_page_number) is not int
        or expected_page_number <= 0
        or not isinstance(expected_source_scope_id, str)
        or not expected_source_scope_id
        or expected_source_scope_id != expected_source_scope_id.strip()
        or not isinstance(expected_requested_type, str)
        or not expected_requested_type
        or expected_requested_type != expected_requested_type.strip()
        or not isinstance(expected_attempted_type, str)
        or not expected_attempted_type
        or expected_attempted_type != expected_attempted_type.strip()
        or (
            expected_raw_text_dictionary_sha256 is not None
            and (
                not isinstance(expected_raw_text_dictionary_sha256, str)
                or _SHA256_RE.fullmatch(expected_raw_text_dictionary_sha256) is None
            )
        )
    ):
        return False

    evidence = proof.get("evidence")
    results = proof.get("attempted_source_results")
    created_ids = proof.get("created_entity_ids")
    removed_ids = proof.get("removed_entity_ids")
    proof_sha256 = proof.get("proof_sha256")
    if (
        proof.get("schema") != PAGE_VISUAL_FALLBACK_PROOF_SCHEMA
        or proof.get("page_specific_proven_impossible") is not True
        or "item_specific_proven_impossible" in proof
        or proof.get("pdf_sha256") != expected_pdf_sha256
        or proof.get("page_number") != expected_page_number
        or proof.get("source_item_id") != expected_source_scope_id
        or proof.get("requested_type") != expected_requested_type
        or proof.get("attempted_type") != expected_attempted_type
        or proof.get("reason_code") != PAGE_VISUAL_REASON_CODE
        or proof.get("attempted_sources_complete") is not True
        or proof.get("cleanup_complete") is not True
        or not isinstance(evidence, dict)
        or evidence.get("text_dictionary_present") is not True
        or evidence.get("canonical_source_item_count") != 0
        or evidence.get("source_item_ids") != []
        or evidence.get("source_scope") != "page_visual"
        or evidence.get("visible_source_text_found") is not False
        or not isinstance(evidence.get("raw_text_dictionary_sha256"), str)
        or _SHA256_RE.fullmatch(evidence.get("raw_text_dictionary_sha256")) is None
        or (
            expected_raw_text_dictionary_sha256 is not None
            and evidence.get("raw_text_dictionary_sha256")
            != expected_raw_text_dictionary_sha256
        )
        or type(evidence.get("raw_text_block_count")) is not int
        or evidence.get("raw_text_block_count") < 0
        or not isinstance(results, list)
        or len(results) != 1
        or not isinstance(created_ids, list)
        or not isinstance(removed_ids, list)
        or any(
            not isinstance(entity_id, str)
            or not entity_id
            or entity_id != entity_id.strip()
            for entity_id in created_ids + removed_ids
        )
        or len(created_ids) != len(set(created_ids))
        or len(removed_ids) != len(set(removed_ids))
        or set(created_ids) != set(removed_ids)
        or not isinstance(proof_sha256, str)
        or _SHA256_RE.fullmatch(proof_sha256) is None
    ):
        return False

    [result] = results
    return bool(
        isinstance(result, dict)
        and result.get("source") == "pymupdf_raw_text_dictionary"
        and result.get("outcome") == "no_canonical_text_source_items"
        and result.get("importer_identity") == proof.get("importer_identity")
        and result.get("pdf_sha256") == expected_pdf_sha256
        and result.get("page_number") == expected_page_number
        and result.get("source_item_id") == expected_source_scope_id
        and result.get("source_item_ids") == []
        and result.get("canonical_source_item_count") == 0
        and result.get("raw_text_dictionary_sha256")
        == evidence.get("raw_text_dictionary_sha256")
        and result.get("visible_source_text_found") is False
        and proof_sha256 == page_visual_proof_digest(proof)
    )

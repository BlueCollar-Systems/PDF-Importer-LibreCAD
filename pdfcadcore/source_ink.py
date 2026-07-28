"""Physical PDF character-evidence sealing shared by delivery and reports.

Unicode content is never paint authority.  Callers must supply the exact source
identity they already hold so a re-digested proof cannot be replayed across a
PDF, page, item, font asset, or glyph sequence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Dict, List, Optional


SOURCE_INK_EVIDENCE_SCHEMA = "pdf_source_ink_evidence_v1"
SOURCE_INK_EVIDENCE_AUTHORITY = "pymupdf_rawdict_texttrace_exact_font"
SOURCE_INK_CLASSIFICATIONS = frozenset(
    {"visible_ink", "zero_visible_ink", "mixed_visible_and_zero_ink"}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_LAYOUT_ONLY_GLYPH_NAMES = frozenset(
    {
        "space",
        "nbspace",
        "nonbreakingspace",
        "uni00a0",
        "tab",
        "uni0009",
    }
)


def layout_only_glyph_name(value: Any) -> bool:
    """Identify font-declared spacing glyphs without consulting Unicode text."""

    return bool(
        isinstance(value, str)
        and value.strip().lower().replace("_", "").replace("-", "")
        in _LAYOUT_ONLY_GLYPH_NAMES
    )


def source_ink_evidence_digest(evidence: Dict[str, Any]) -> str:
    """Return the canonical digest for one source-ink evidence record."""

    payload = dict(evidence or {})
    payload.pop("evidence_sha256", None)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def verified_font_asset_binding(asset: Any) -> Optional[Dict[str, Any]]:
    """Bind declared font metadata only when it matches the exact asset bytes."""

    try:
        source_bytes = bytes(asset.source_bytes)
        usable_bytes = bytes(asset.usable_bytes)
        source_sha256 = str(asset.source_sha256 or "").strip().lower()
        usable_sha256 = str(asset.usable_sha256 or "").strip().lower()
        asset_id = str(asset.asset_id or "").strip()
        source_xref = asset.source_xref
        values = {
            "base_font_name": str(asset.base_font_name or "").strip(),
            "span_font_name": str(asset.span_font_name or "").strip(),
            "source_format": str(asset.source_format or "").strip().lower(),
            "usable_format": str(asset.usable_format or "").strip().lower(),
            "source_origin": str(asset.source_origin or "").strip(),
        }
    except (AttributeError, TypeError, ValueError):
        return None
    if (
        not source_bytes
        or not usable_bytes
        or type(source_xref) is not int
        or source_xref <= 0
        or _SHA256_RE.fullmatch(source_sha256) is None
        or _SHA256_RE.fullmatch(usable_sha256) is None
        or hashlib.sha256(source_bytes).hexdigest() != source_sha256
        or hashlib.sha256(usable_bytes).hexdigest() != usable_sha256
        or asset_id != "sha256:" + usable_sha256
        or any(not value for value in values.values())
    ):
        return None
    return {
        "asset_id": asset_id,
        "source_xref": source_xref,
        "source_font_sha256": source_sha256,
        "usable_font_sha256": usable_sha256,
        **values,
    }


def _font_identity_valid(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    raw_name = value.get("raw_name")
    normalized_key = value.get("normalized_key")
    return bool(
        isinstance(raw_name, str)
        and raw_name
        and raw_name == raw_name.strip()
        and isinstance(normalized_key, str)
        and normalized_key
        and normalized_key == normalized_key.strip()
    )


def _finite_number(value: Any) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _font_asset_binding_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    source_sha256 = value.get("source_font_sha256")
    usable_sha256 = value.get("usable_font_sha256")
    return bool(
        isinstance(source_sha256, str)
        and _SHA256_RE.fullmatch(source_sha256) is not None
        and isinstance(usable_sha256, str)
        and _SHA256_RE.fullmatch(usable_sha256) is not None
        and value.get("asset_id") == "sha256:" + usable_sha256
        and type(value.get("source_xref")) is int
        and value.get("source_xref") > 0
        and all(
            isinstance(value.get(name), str)
            and bool(value.get(name))
            and value.get(name) == value.get(name).strip()
            for name in (
                "base_font_name",
                "span_font_name",
                "source_format",
                "usable_format",
                "source_origin",
            )
        )
    )


def _glyph_bounds_valid(value: Any) -> bool:
    return bool(
        value is None
        or (
            isinstance(value, (list, tuple))
            and len(value) == 4
            and all(_finite_number(component) for component in value)
        )
    )


def source_ink_evidence_verified(
    evidence: Any,
    *,
    expected_pdf_sha256: str,
    expected_page_number: int,
    expected_source_item_id: str,
    expected_source_text: str,
    expected_font_identity: Dict[str, Any],
    expected_font_asset_bindings: List[Dict[str, Any]],
    expected_glyph_id_sequence: List[Optional[int]],
) -> bool:
    """Validate one sealed record against an independently supplied source item."""

    if (
        not isinstance(evidence, dict)
        or not isinstance(expected_pdf_sha256, str)
        or _SHA256_RE.fullmatch(expected_pdf_sha256) is None
        or type(expected_page_number) is not int
        or expected_page_number <= 0
        or not isinstance(expected_source_item_id, str)
        or not expected_source_item_id
        or expected_source_item_id != expected_source_item_id.strip()
        or not isinstance(expected_source_text, str)
        or not expected_source_text
        or not _font_identity_valid(expected_font_identity)
        or not isinstance(expected_font_asset_bindings, list)
        or not isinstance(expected_glyph_id_sequence, list)
    ):
        return False

    characters = evidence.get("characters")
    asset_bindings = evidence.get("font_asset_bindings")
    glyph_id_sequence = evidence.get("glyph_id_sequence")
    classification = evidence.get("classification")
    zero_ink_characters_layout_only = evidence.get(
        "zero_ink_characters_layout_only"
    )
    digest = evidence.get("evidence_sha256")
    if (
        evidence.get("schema") != SOURCE_INK_EVIDENCE_SCHEMA
        or evidence.get("authority") != SOURCE_INK_EVIDENCE_AUTHORITY
        or evidence.get("pdf_sha256") != expected_pdf_sha256
        or evidence.get("page_number") != expected_page_number
        or evidence.get("source_item_id") != expected_source_item_id
        or evidence.get("source_text") != expected_source_text
        or evidence.get("source_text_sha256")
        != hashlib.sha256(expected_source_text.encode("utf-8")).hexdigest()
        or evidence.get("font_identity") != expected_font_identity
        or evidence.get("all_characters_physically_resolved") is not True
        or classification not in SOURCE_INK_CLASSIFICATIONS
        or type(zero_ink_characters_layout_only) is not bool
        or not isinstance(characters, list)
        or not characters
        or not isinstance(asset_bindings, list)
        or asset_bindings != expected_font_asset_bindings
        or any(not _font_asset_binding_valid(binding) for binding in asset_bindings)
        or len({binding["asset_id"] for binding in asset_bindings})
        != len(asset_bindings)
        or not isinstance(glyph_id_sequence, list)
        or glyph_id_sequence != expected_glyph_id_sequence
        or len(glyph_id_sequence) != len(characters)
        or not isinstance(digest, str)
        or _SHA256_RE.fullmatch(digest) is None
    ):
        return False

    resolved_text: List[str] = []
    zero_flags: List[bool] = []
    for index, record in enumerate(characters):
        if not isinstance(record, dict):
            return False
        character = record.get("character")
        authority = record.get("authority")
        glyph_id = record.get("glyph_id")
        font_binding = record.get("font_asset_binding")
        if (
            not isinstance(character, str)
            or not character
            or record.get("source_index") != index
            or record.get("physically_resolved") is not True
            or type(record.get("zero_visible_ink")) is not bool
            or glyph_id != glyph_id_sequence[index]
            or authority
            not in {
                "pymupdf_rawdict_synthetic_character",
                "pymupdf_texttrace_nonpainting_render_mode",
                "exact_pdf_font_glyph_bounds",
            }
        ):
            return False

        if authority == "pymupdf_rawdict_synthetic_character":
            if (
                record.get("synthetic") is not True
                or record.get("zero_visible_ink") is not True
                or record.get("layout_only_zero_ink") is not True
                or glyph_id is not None
                or (
                    font_binding is not None
                    and (
                        not _font_asset_binding_valid(font_binding)
                        or font_binding not in asset_bindings
                    )
                )
            ):
                return False
        else:
            opacity = record.get("opacity")
            bounds = record.get("glyph_bounds")
            advance_width = record.get("advance_width")
            layout_only_zero_ink = record.get("layout_only_zero_ink")
            if (
                record.get("synthetic") is not False
                or type(glyph_id) is not int
                or glyph_id < 0
                or not isinstance(record.get("glyph_name"), str)
                or not record.get("glyph_name")
                or type(record.get("trace_type")) is not int
                or not _finite_number(opacity)
                or not _glyph_bounds_valid(bounds)
                or not _finite_number(advance_width)
                or float(advance_width) < 0.0
                or type(layout_only_zero_ink) is not bool
                or not _font_asset_binding_valid(font_binding)
                or font_binding not in asset_bindings
            ):
                return False
            expected_layout_only = bool(
                bounds is None
                and float(advance_width) > 0.0
                and layout_only_glyph_name(record.get("glyph_name"))
            )
            if layout_only_zero_ink != expected_layout_only:
                return False
            if authority == "pymupdf_texttrace_nonpainting_render_mode":
                if (
                    record.get("zero_visible_ink") is not True
                    or (
                        record.get("trace_type") != 3
                        and float(opacity) > 0.0
                    )
                ):
                    return False
            elif (
                record.get("trace_type") == 3
                or float(opacity) <= 0.0
                or record.get("zero_visible_ink") != (bounds is None)
            ):
                return False

        resolved_text.append(character)
        zero_flags.append(record["zero_visible_ink"])

    expected_classification = (
        "zero_visible_ink"
        if all(zero_flags)
        else "mixed_visible_and_zero_ink"
        if any(zero_flags)
        else "visible_ink"
    )
    zero_layout_flags = [
        record.get("layout_only_zero_ink")
        for record in characters
        if record["zero_visible_ink"]
    ]
    expected_layout_only = bool(
        zero_layout_flags and all(flag is True for flag in zero_layout_flags)
    )
    return bool(
        "".join(resolved_text) == expected_source_text
        and classification == expected_classification
        and zero_ink_characters_layout_only == expected_layout_only
        and digest == source_ink_evidence_digest(evidence)
    )

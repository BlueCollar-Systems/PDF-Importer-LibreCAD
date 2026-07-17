# -*- coding: utf-8 -*-
"""Build bcs.parts_bootstrap/1.0 sidecar from BOM text evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .model3d_intent import (
    _FEET_INCH_RE,
    _MARK_RE,
    _MEMBER_RE,
    _PLATE_RE,
    _member_from_match,
    parse_fraction_inches,
)

SCHEMA = "bcs.parts_bootstrap/1.0"

_QUAN_RE = re.compile(r"\b(?:QUAN|QTY|QTY\.|Q\.)\s*[:.]?\s*(\d+)\b", re.IGNORECASE)
_LEADING_QUAN_RE = re.compile(r"^\s*(\d+)\s+")
_PROFILE_FROM_ROW = re.compile(
    r"\b("
    r"PL\s*" + r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*\"?\s*[xX]\s*[^\s]+"
    r"|W\d{1,3}\s?[xX]\s?\d{1,3}(?:\.\d+)?"
    r"|L\d{1,2}\s?[xX]\s?\d{1,2}\s?[xX]\s?(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
    r"|HSS\d{1,2}(?:\.\d+)?\s?[xX]\s?\d{1,2}(?:\.\d+)?\s?[xX]\s?(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
    r"|PIPE\d{1,2}(?:STD|XS|XXS)"
    r"|C\d{1,2}\s?[xX]\s?\d{1,3}(?:\.\d+)?"
    r")\b",
    re.IGNORECASE,
)
_MARK_LINE_RE = re.compile(
    r"^[A-Za-z]{1,3}\d{3,6}(?:[A-Za-z]{1,4}\d*)?$|^\d{3,6}[A-Za-z]{1,4}\d*$",
    re.IGNORECASE,
)
_QTY_LINE_RE = re.compile(r"^\d+$")
_WEIGHT_LINE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_HEADER_LINES = {
    "BILL OF MATERIAL",
    "QUAN",
    "QTY",
    "MARK",
    "DESCRIPTION",
    "LENGTH",
    "TOTAL WT.",
    "TOTAL  WT.",
    "REMARKS",
}


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feet_inches_to_inches(text: str) -> Optional[float]:
    m = _FEET_INCH_RE.search(text or "")
    if not m:
        return None
    feet = int(m.group(1))
    inches = parse_fraction_inches(m.group(2) or "0") or 0.0
    return feet * 12.0 + inches


def _is_length_line(text: str) -> bool:
    return _feet_inches_to_inches(text) is not None


def _is_header_line(text: str) -> bool:
    return text.strip().upper() in _HEADER_LINES


def _part_kind(profile: str) -> str:
    return "plate" if profile.upper().startswith("PL") else "member"


def _profile_hint_from_text(text: str) -> Optional[str]:
    for pm in _PLATE_RE.finditer(text):
        return re.sub(r"\s+", "", pm.group(0)).upper()
    for mm in _MEMBER_RE.finditer(text):
        cand = _member_from_match(mm)
        if cand is not None:
            return cand.designation
    m = _PROFILE_FROM_ROW.search(text)
    if m:
        return re.sub(r"\s+", "", m.group(1)).upper()
    return None


def _quantity_from_text(text: str) -> int:
    m = _QUAN_RE.search(text or "")
    if m:
        try:
            return max(1, int(m.group(1)))
        except ValueError:
            pass
    m = _LEADING_QUAN_RE.match(text or "")
    if m:
        try:
            return max(1, int(m.group(1)))
        except ValueError:
            pass
    return 1


def _normalize_text_item(item: Any) -> tuple[str, Optional[int]]:
    if isinstance(item, str):
        return item, None
    if isinstance(item, dict):
        text = item.get("text")
        page = item.get("page")
        return str(text or ""), page
    text = getattr(item, "text", None)
    if not isinstance(text, str):
        text = str(item or "")
    page = getattr(item, "page", None)
    try:
        page_int = int(page) if page is not None else None
    except (TypeError, ValueError):
        page_int = None
    return text, page_int


def _extract_sequence_rows(items: List[tuple[str, Optional[int]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    idx = 0
    while idx + 3 < len(items):
        mark, page = items[idx]
        qty, _ = items[idx + 1]
        description, _ = items[idx + 2]
        length_text, _ = items[idx + 3]
        if (
            _is_header_line(mark)
            or not _MARK_LINE_RE.match(mark)
            or not _QTY_LINE_RE.match(qty)
            or _profile_hint_from_text(description) is None
            or not _is_length_line(length_text)
        ):
            idx += 1
            continue

        cursor = idx + 4
        total_weight = None
        remarks = None
        grade = None
        if cursor < len(items) and _WEIGHT_LINE_RE.match(items[cursor][0]):
            total_weight = float(items[cursor][0])
            cursor += 1
        if cursor < len(items) and not _MARK_LINE_RE.match(items[cursor][0]) and not _is_header_line(items[cursor][0]):
            remarks = items[cursor][0]
            cursor += 1
        current_starts_next_row = (
            cursor + 1 < len(items)
            and _MARK_LINE_RE.match(items[cursor][0])
            and _QTY_LINE_RE.match(items[cursor + 1][0])
        )
        if cursor < len(items) and not current_starts_next_row and not _is_header_line(items[cursor][0]):
            grade = items[cursor][0]
            cursor += 1

        profile = _profile_hint_from_text(description) or description
        row: Dict[str, Any] = {
            "piece_mark": mark,
            "quantity": int(qty),
            "description": description,
            "profile_hint": profile,
            "kind": _part_kind(profile),
            "length_in": round(_feet_inches_to_inches(length_text) or 0.0, 4),
            "length_text": length_text,
            "source": {
                "page": page or 1,
                "line_start": idx,
                "line_end": cursor - 1,
            },
        }
        if total_weight is not None:
            row["total_weight_lb"] = total_weight
        if remarks:
            row["remarks"] = remarks
        if grade:
            row["grade"] = grade
        rows.append(row)
        idx = cursor
    return rows


def extract_bootstrap_rows(
    text_items: Iterable[Any],
    *,
    span_map: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Extract BOM row candidates from normalized text lines."""
    normalized_items = [
        _normalize_text_item(item)
        for item in text_items
    ]
    normalized_items = [
        (text.strip(), page)
        for text, page in normalized_items
        if text and text.strip()
    ]
    sequence_rows = _extract_sequence_rows(normalized_items)
    if sequence_rows:
        return sequence_rows

    rows: List[Dict[str, Any]] = []
    seen_marks: set[str] = set()

    for text, page in normalized_items:

        mark_m = _MARK_RE.search(text)
        profile = _profile_hint_from_text(text)
        if not mark_m and not profile:
            continue

        piece_mark = mark_m.group(1) if mark_m else None
        if not piece_mark and profile:
            piece_mark = profile
        if not piece_mark:
            continue

        key = piece_mark.lower()
        if key in seen_marks:
            continue
        seen_marks.add(key)

        row: Dict[str, Any] = {
            "piece_mark": piece_mark,
            "quantity": _quantity_from_text(text),
        }
        if profile:
            row["profile_hint"] = profile
            if profile.upper().startswith("PL"):
                row["kind"] = "plate"
            else:
                row["kind"] = "member"
        length_in = _feet_inches_to_inches(text)
        if length_in is not None:
            row["length_in"] = round(length_in, 4)
        if page is not None and page > 0:
            row["page"] = page

        if span_map and piece_mark in span_map:
            row["span_ids"] = list(span_map[piece_mark])

        rows.append(row)

    return rows


def build_parts_bootstrap(
    pdf_path: str,
    *,
    page_count: int = 0,
    rows: Optional[List[Dict[str, Any]]] = None,
    import_build_stamp: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a valid bcs.parts_bootstrap/1.0 payload."""
    part_rows = list(rows or [])
    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "rows": part_rows,
        "parts": part_rows,
        "part_count": len(part_rows),
        "source_pdf": {
            "file": str(Path(pdf_path).name),
            "pages": int(page_count or 0),
        },
        "tables": [
            {
                "name": "BILL OF MATERIAL",
                "row_count": len(part_rows),
                "rows": part_rows,
            }
        ] if part_rows else [],
    }
    if pdf_path and Path(pdf_path).is_file():
        payload["source_pdf"]["sha256"] = _sha256_file(pdf_path)
    if import_build_stamp:
        payload["import_build_stamp"] = dict(import_build_stamp)
    if not part_rows:
        payload["note"] = "no BOM rows detected"
    else:
        payload["note"] = "BOM row extraction from drawing text"
    return payload


def build_parts_bootstrap_stub(
    pdf_path: str,
    *,
    page_count: int = 0,
    rows: Optional[List[Dict[str, Any]]] = None,
    import_build_stamp: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Backward-compatible alias for build_parts_bootstrap."""
    return build_parts_bootstrap(
        pdf_path,
        page_count=page_count,
        rows=rows,
        import_build_stamp=import_build_stamp,
    )


def write_parts_bootstrap_sidecar(
    output_path: str,
    pdf_path: str,
    *,
    page_count: int = 0,
    rows: Optional[List[Dict[str, Any]]] = None,
    text_items: Optional[Iterable[Any]] = None,
    import_build_stamp: Optional[Dict[str, Any]] = None,
) -> str:
    from .atomic_io import atomic_write_text

    path = Path(output_path)
    extracted = list(rows or [])
    if not extracted and text_items is not None:
        extracted = extract_bootstrap_rows(text_items)
    manifest = build_parts_bootstrap(
        pdf_path,
        page_count=page_count,
        rows=extracted,
        import_build_stamp=import_build_stamp,
    )
    return atomic_write_text(
        path, json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    )


__all__ = [
    "SCHEMA",
    "build_parts_bootstrap",
    "build_parts_bootstrap_stub",
    "extract_bootstrap_rows",
    "write_parts_bootstrap_sidecar",
]

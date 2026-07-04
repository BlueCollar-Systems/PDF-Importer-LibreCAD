# -*- coding: utf-8 -*-
"""Build bcs.parts_bootstrap/1.0 sidecar from BOM text evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from pdfcadcore.model3d_intent import (
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


def extract_bootstrap_rows(
    text_items: Iterable[Any],
    *,
    span_map: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Extract BOM row candidates from normalized text lines."""
    rows: List[Dict[str, Any]] = []
    seen_marks: set[str] = set()

    for item in text_items:
        text, page = _normalize_text_item(item)
        if not text or not text.strip():
            continue

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
    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "rows": list(rows or []),
        "source_pdf": {
            "file": str(Path(pdf_path).name),
            "pages": int(page_count or 0),
        },
    }
    if pdf_path and Path(pdf_path).is_file():
        payload["source_pdf"]["sha256"] = _sha256_file(pdf_path)
    if import_build_stamp:
        payload["import_build_stamp"] = dict(import_build_stamp)
    if not rows:
        payload["note"] = "no BOM rows detected"
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
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    extracted = list(rows or [])
    if not extracted and text_items is not None:
        extracted = extract_bootstrap_rows(text_items)
    manifest = build_parts_bootstrap(
        pdf_path,
        page_count=page_count,
        rows=extracted,
        import_build_stamp=import_build_stamp,
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return str(path)


__all__ = [
    "SCHEMA",
    "build_parts_bootstrap",
    "build_parts_bootstrap_stub",
    "extract_bootstrap_rows",
    "write_parts_bootstrap_sidecar",
]

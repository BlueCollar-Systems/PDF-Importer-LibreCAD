#!/usr/bin/env python3
"""P0 extract_page golden for private/web/stacked_fraction_spacing.pdf (PRIVATE-11)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from corpus_paths import require_manifest_pdf  # noqa: E402
from pdfcadcore.primitive_extractor import extract_page  # noqa: E402

try:
    import pymupdf as fitz  # noqa: E402
except ImportError:  # pragma: no cover
    import fitz  # type: ignore  # noqa: E402


def _golden() -> dict:
    root = Path(os.environ.get("BCS_PRIVATE_VALIDATION_ROOT") or r"__private_validation_assets_not_configured__")
    path = root / "conformance-vectors" / "stacked-fraction-extract-golden.json"
    if not path.is_file():
        pytest.skip(f"golden file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_stacked_fraction_spacing_extract_page_matches_golden() -> None:
    golden = _golden()
    pdf_path = require_manifest_pdf(str(golden.get("manifest_entry_id") or "PRIVATE-11"), p0=True)
    doc = fitz.open(str(pdf_path))
    try:
        page_data = extract_page(doc[0], int(golden.get("page") or 1))
    finally:
        doc.close()

    texts = [item.text.strip() for item in page_data.text_items]
    for want in golden.get("expected_merged_fractions") or []:
        assert want in texts, f"expected merged fraction {want!r} in {texts!r}"
    for whole in golden.get("expected_whole_numbers") or []:
        assert whole in texts, f"expected whole number {whole!r} in {texts!r}"
    for bad in golden.get("forbidden_merges") or []:
        assert bad not in texts, f"forbidden merge {bad!r} in {texts!r}"

    max_size = float(golden.get("max_merged_font_size_mm") or 2.5)
    merged_set = set(golden.get("expected_merged_fractions") or [])
    for item in page_data.text_items:
        token = item.text.strip()
        if token in merged_set and item.font_size > max_size:
            pytest.fail(f"{token!r} font_size {item.font_size:.2f}mm exceeds {max_size}")

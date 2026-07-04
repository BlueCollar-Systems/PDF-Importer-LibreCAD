# -*- coding: utf-8 -*-
"""Minimal parts bootstrap sidecar builder (bcs.parts_bootstrap/1.0) — stub emitter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "bcs.parts_bootstrap/1.0"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parts_bootstrap_stub(
    pdf_path: str,
    *,
    page_count: int = 0,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a valid sidecar payload; BOM row extraction is deferred."""

    payload: Dict[str, Any] = {
        "schema": SCHEMA,
        "rows": list(rows or []),
        "source_pdf": {
            "file": str(Path(pdf_path).name),
            "pages": int(page_count or 0),
        },
        "note": "stub emitter — automated piece-mark extraction deferred",
    }
    if pdf_path and Path(pdf_path).is_file():
        payload["source_pdf"]["sha256"] = _sha256_file(pdf_path)
    return payload


def write_parts_bootstrap_sidecar(
    output_path: str,
    pdf_path: str,
    *,
    page_count: int = 0,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_parts_bootstrap_stub(
        pdf_path,
        page_count=page_count,
        rows=rows,
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return str(path)


__all__ = [
    "SCHEMA",
    "build_parts_bootstrap_stub",
    "write_parts_bootstrap_sidecar",
]

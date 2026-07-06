#!/usr/bin/env python3
"""Resolve PDF test corpus paths via BCS_CORPUS_ROOT."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_CORPUS_ROOTS = (Path(r"C:\1pdf-test-corpus"),)


def resolve_corpus_root(candidates: Optional[Iterable[Path]] = None) -> Optional[Path]:
    """Return the first existing corpus root from env or known defaults."""
    env_root = os.environ.get("BCS_CORPUS_ROOT") or os.environ.get("PDF_TEST_CORPUS")
    ordered: List[Path] = []
    if env_root:
        ordered.append(Path(env_root))
    ordered.extend(candidates or DEFAULT_CORPUS_ROOTS)
    for root in ordered:
        if root.is_dir():
            return root.resolve()
    return None


def resolve_corpus_pdf(relative_name: str, *, subdir: str = "") -> Optional[Path]:
    """Resolve a PDF under the corpus root, trying common subfolders."""
    root = resolve_corpus_root()
    if root is None:
        return None

    rel = Path(relative_name)
    search_dirs = [root]
    if subdir:
        search_dirs.insert(0, root / subdir)
    for folder_name in ("web-acquired", "pdfs"):
        candidate = root / folder_name
        if candidate.is_dir():
            search_dirs.append(candidate)

    for base in search_dirs:
        direct = base / rel
        if direct.is_file():
            return direct.resolve()
        if rel.suffix.lower() != ".pdf":
            with_pdf = base / f"{rel.name}.pdf"
            if with_pdf.is_file():
                return with_pdf.resolve()
    return None


def require_corpus_root() -> Path:
    root = resolve_corpus_root()
    if root is None:
        raise FileNotFoundError(
            "PDF corpus not found. Set BCS_CORPUS_ROOT or place files under C:\\1pdf-test-corpus."
        )
    return root


def load_manifest(root: Optional[Path] = None) -> Dict[str, Any]:
    corpus_root = root or require_corpus_root()
    manifest_path = corpus_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json missing under {corpus_root}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_manifest_entry(entry_id: str, *, root: Optional[Path] = None) -> Optional[Path]:
    corpus_root = root or resolve_corpus_root()
    if corpus_root is None:
        return None
    manifest = load_manifest(corpus_root)
    for entry in manifest.get("entries", []):
        if str(entry.get("id")) != str(entry_id):
            continue
        rel = entry.get("local_path")
        if not rel:
            return None
        pdf_path = corpus_root / str(rel)
        if pdf_path.is_file():
            return pdf_path.resolve()
        return None
    return None


def require_manifest_pdf(entry_id: str, *, p0: bool = False) -> Path:
    pdf_path = resolve_manifest_entry(entry_id)
    if pdf_path is not None:
        return pdf_path
    message = (
        f"Corpus manifest entry {entry_id!r} not available. "
        "Set BCS_CORPUS_ROOT to a checkout of pdf-test-corpus."
    )
    if p0:
        raise FileNotFoundError(message)
    raise unittest_skip(message)


def unittest_skip(message: str) -> Exception:
    try:
        import unittest

        return unittest.SkipTest(message)
    except ImportError:  # pragma: no cover
        return FileNotFoundError(message)


if __name__ == "__main__":
    root = resolve_corpus_root()
    print(root if root else "MISSING")

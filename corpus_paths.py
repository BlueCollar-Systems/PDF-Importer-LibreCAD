#!/usr/bin/env python3
"""Resolve PDF test corpus paths without Desktop-specific absolute paths."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional

DEFAULT_CORPUS_ROOTS = (
    Path(r"C:\1pdf-test-corpus"),
    Path.home() / "Desktop" / "PDFTest Files",
    Path(r"C:\Users\Rowdy Payton\Desktop\PDFTest Files"),
)


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
    for folder_name in ("PDFTest Files", "web-acquired", "pdfs", "New folder (2)"):
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


if __name__ == "__main__":
    root = resolve_corpus_root()
    print(root if root else "MISSING")

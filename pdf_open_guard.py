# -*- coding: utf-8 -*-
# pdf_open_guard.py -- typed open-time gate for malformed PDFs.
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Clean rejection for unsupported/malformed PDFs (encrypted, empty, non-PDF,
zero-page) so importers report a clear reason instead of a raw traceback.
Host-agnostic; reuses the existing pdfcadcore fitz loader when available.
"""
from __future__ import annotations

from pdfcadcore.fitz_loader import PdfOpenError as PdfOpenError, safe_open


def precheck_pdf(path: str) -> None:
    """Raise :class:`PdfOpenError` with a clean reason if ``path`` cannot be
    imported; return ``None`` when it looks importable. Opens briefly and
    closes -- negligible overhead versus the full import."""
    doc = safe_open(path)
    try:
        return None
    finally:
        try:
            doc.close()
        except Exception:
            pass

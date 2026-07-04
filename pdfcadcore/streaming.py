# -*- coding: utf-8 -*-
# streaming.py — per-page streaming extraction for heavy PDFs
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Per-page streaming for Attachment-C-class PDFs (large files, many pages).

Hosts iterate pages one at a time instead of extracting the whole document
up front, keeping memory flat and letting the UI update between pages. A
progress callback receives per-page timing so hosts can warn on slow pages
(soft budget, D7) and the user can cancel mid-import without losing the
pages already built.

Usage (host adapter):

    from pdfcadcore import iter_pages

    def on_progress(p):
        ui.update(f"page {p.page_index}/{p.total_pages}")
        return not user_cancelled()      # False stops the stream

    for page_number, page_data in iter_pages(pdf_path, progress=on_progress):
        build_host_geometry(page_data)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator, List, Optional, Sequence, Tuple

from .primitive_extractor import extract_page
from .primitives import PageData

#: D7 soft budget: a page slower than this is flagged ``over_budget`` so the
#: host can surface a "this document is heavy" hint or a page-range prompt.
DEFAULT_SOFT_BUDGET_S = 15.0


@dataclass
class PageProgress:
    """Progress snapshot passed to the ``progress`` callback after each page."""
    page_number: int        # 1-based page number in the PDF
    page_index: int         # 1-based position in the requested sequence
    total_pages: int        # number of pages requested
    elapsed_s: float        # extraction time for this page
    total_elapsed_s: float  # extraction time so far for the whole stream
    primitive_count: int
    text_count: int
    over_budget: bool       # elapsed_s exceeded the soft budget


def _open_source(source: Any) -> Tuple[Any, bool]:
    """Return ``(document, owns_document)`` for a path or open Document."""
    if hasattr(source, "load_page") or hasattr(source, "page_count"):
        return source, False
    from .fitz_loader import safe_open
    return safe_open(str(source)), True


def _normalize_pages(requested: Optional[Sequence[int]], total: int) -> List[int]:
    """Clamp a 1-based page list to the document; default is all pages."""
    if not requested:
        return list(range(1, total + 1))
    return [p for p in requested if 1 <= p <= total]


def iter_pages(
    source: Any,
    pages: Optional[Sequence[int]] = None,
    *,
    progress: Optional[Callable[[PageProgress], Any]] = None,
    soft_budget_s: float = DEFAULT_SOFT_BUDGET_S,
    scale: float = 1.0,
    flip_y: bool = True,
    detect_arcs: bool = True,
    arc_fit_tol_mm: float = 0.05,
    min_arc_angle_deg: float = 5.0,
    arc_min_pts: int = 5,
) -> Iterator[Tuple[int, PageData]]:
    """Stream ``(page_number, PageData)`` tuples one page at a time.

    Parameters
    ----------
    source:
        PDF path (``str`` / ``os.PathLike``) or an already-open PyMuPDF
        ``Document``. A document passed in stays open; a path is opened
        and closed by the generator.
    pages:
        Optional 1-based page numbers. Out-of-range entries are skipped.
        Default: every page.
    progress:
        Called after each page with a :class:`PageProgress`. Returning
        ``False`` (exactly) stops the stream — pages already yielded stay
        valid, so hosts keep the geometry built so far on cancel.
    soft_budget_s:
        Per-page soft time budget; pages slower than this are flagged
        ``over_budget`` in the progress snapshot (D7 default 15 s).

    Remaining keyword arguments are forwarded to
    :func:`pdfcadcore.primitive_extractor.extract_page`.
    """
    doc, owns_doc = _open_source(source)
    try:
        total = int(getattr(doc, "page_count", None) or len(doc))
        wanted = _normalize_pages(pages, total)
        total_elapsed = 0.0

        for idx, page_number in enumerate(wanted, start=1):
            t0 = time.perf_counter()
            page = doc.load_page(page_number - 1)
            page_data = extract_page(
                page,
                page_num=page_number,
                scale=scale,
                flip_y=flip_y,
                detect_arcs=detect_arcs,
                arc_fit_tol_mm=arc_fit_tol_mm,
                min_arc_angle_deg=min_arc_angle_deg,
                arc_min_pts=arc_min_pts,
            )
            elapsed = time.perf_counter() - t0
            total_elapsed += elapsed

            yield page_number, page_data

            if progress is not None:
                keep_going = progress(PageProgress(
                    page_number=page_number,
                    page_index=idx,
                    total_pages=len(wanted),
                    elapsed_s=elapsed,
                    total_elapsed_s=total_elapsed,
                    primitive_count=len(page_data.primitives),
                    text_count=len(page_data.text_items),
                    over_budget=elapsed > soft_budget_s,
                ))
                if keep_going is False:
                    break
    finally:
        if owns_doc:
            doc.close()

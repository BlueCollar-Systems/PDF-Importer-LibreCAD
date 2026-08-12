# -*- coding: utf-8 -*-
# streaming.py — per-page streaming extraction for heavy PDFs
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Per-page streaming for large multipage technical-document PDFs.

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

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Iterator, List, Optional, Sequence, Tuple

from . import ir_cache
from .primitive_extractor import extract_page
from .primitives import PageData
from .stage_timing import StageTimer

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


def _extract_with_cache(
    page,
    page_number: int,
    pdf_path: Optional[str],
    cache_key_fn: Optional[Callable[..., Optional[str]]],
    scale: float,
    flip_y: bool,
    detect_arcs: bool,
    arc_fit_tol_mm: float,
    min_arc_angle_deg: float,
    arc_min_pts: int,
) -> Tuple[PageData, float, bool]:
    """Extract a page, using disk cache when available. Returns (data, elapsed, from_cache)."""
    key = None
    if pdf_path and cache_key_fn:
        key = cache_key_fn(
            pdf_path=pdf_path,
            page_number=page_number,
            scale=scale,
            flip_y=flip_y,
            detect_arcs=detect_arcs,
            arc_fit_tol_mm=arc_fit_tol_mm,
            min_arc_angle_deg=min_arc_angle_deg,
            arc_min_pts=arc_min_pts,
        )
        cached = ir_cache.load_ir(key)
        if cached is not None:
            return cached, 0.0, True
    t0 = time.perf_counter()
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
    if key is not None:
        try:
            ir_cache.save_ir(key, page_data)
        except Exception:
            pass
    return page_data, elapsed, False


def _extract_page_worker_with_cache(
    payload: Tuple[str, int, bool, float, bool, bool, float, float, int]
) -> Tuple[int, PageData, float]:
    """Module-level picklable worker for parallel page extraction."""
    from .fitz_loader import safe_open

    (
        pdf_path,
        page_number,
        use_cache,
        scale,
        flip_y,
        detect_arcs,
        arc_fit_tol_mm,
        min_arc_angle_deg,
        arc_min_pts,
    ) = payload
    key = None
    if use_cache:
        key = ir_cache.cache_key(
            pdf_path=pdf_path,
            page_number=page_number,
            scale=scale,
            flip_y=flip_y,
            detect_arcs=detect_arcs,
            arc_fit_tol_mm=arc_fit_tol_mm,
            min_arc_angle_deg=min_arc_angle_deg,
            arc_min_pts=arc_min_pts,
        )
        cached = ir_cache.load_ir(key)
        if cached is not None:
            return page_number, cached, 0.0
    t0 = time.perf_counter()
    with safe_open(pdf_path) as doc:
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
    if key is not None:
        try:
            ir_cache.save_ir(key, page_data)
        except Exception:
            pass
    return page_number, page_data, elapsed


def _extract_pages_parallel(
    pdf_path: str,
    wanted: List[int],
    cache_key_fn: Optional[Callable[..., Optional[str]]],
    scale: float,
    flip_y: bool,
    detect_arcs: bool,
    arc_fit_tol_mm: float,
    min_arc_angle_deg: float,
    arc_min_pts: int,
    max_workers: Optional[int],
) -> List[Tuple[int, PageData, float]]:
    """Extract pages concurrently; each worker opens its own PyMuPDF document.

    PageData is picklable (plain dataclasses), but fitz.Page is not, so workers
    open the source path independently. Caching is checked inside each worker
    so identical re-runs remain fast.
    """
    payloads = [
        (
            pdf_path,
            page_number,
            cache_key_fn is not None,
            scale,
            flip_y,
            detect_arcs,
            arc_fit_tol_mm,
            min_arc_angle_deg,
            arc_min_pts,
        )
        for page_number in wanted
    ]

    workers = max_workers
    if workers is None:
        workers = int(os.environ.get("BCS_PDF_IMPORT_MAX_WORKERS", 0)) or None
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_page_worker_with_cache, payload): payload[1] for payload in payloads}
        results = []
        for future in as_completed(futures):
            results.append(future.result())
    return results


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
    parallel: bool = False,
    max_workers: Optional[int] = None,
    use_cache: bool = False,
    stage_timing: Optional[StageTimer] = None,
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
    parallel:
        Extract pages concurrently using a process pool. This uses more
        memory because results are buffered until the slowest page in the
        set finishes, but it is significantly faster for multi-page PDFs
        because PyMuPDF releases the GIL during parsing. Host-object
        creation is still sequential because pages are yielded in order.
    max_workers:
        Number of parallel workers when ``parallel=True``. Defaults to the
        number of logical CPUs or ``BCS_PDF_IMPORT_MAX_WORKERS``.
    use_cache:
        Persist extracted ``PageData`` to a disk cache keyed by source PDF
        SHA-256 + extraction parameters. Re-importing the same PDF with the
        same options skips the PDF parsing phase entirely. The cached IR is
        bit-identical to a fresh extraction, so visual accuracy is unchanged.
    stage_timing:
        Optional :class:`pdfcadcore.stage_timing.StageTimer`. When supplied it
        receives ``extract_ms`` (time spent in this generator turning the PDF
        into ``PageData``) and ``host_build_ms`` (time the caller spent between
        one yield and the next, i.e. building host objects from what it was
        handed). The host needs no changes to be measured: a generator already
        knows when it is running and when its consumer is. Read the timer after
        the loop finishes. Omitting it changes nothing about the pages yielded.

    Remaining keyword arguments are forwarded to
    :func:`pdfcadcore.primitive_extractor.extract_page`.
    """
    pdf_path: Optional[str] = None
    if isinstance(source, (str, os.PathLike)):
        pdf_path = str(source)
    elif isinstance(getattr(source, "name", None), str):
        pdf_path = source.name

    doc, owns_doc = _open_source(source)
    try:
        total = int(getattr(doc, "page_count", None) or len(doc))
        wanted = _normalize_pages(pages, total)
        total_elapsed = 0.0
        cache_key_fn = ir_cache.cache_key if use_cache else None
        # A throwaway timer when the caller supplied none keeps this a single code path.
        # The cost is one perf_counter pair per stage and the result is never read, so
        # behaviour is identical whether or not the caller is measuring.
        timer = stage_timing if stage_timing is not None else StageTimer()

        with timer.measure("extract_ms"):
            if parallel and pdf_path:
                results = _extract_pages_parallel(
                    pdf_path=pdf_path,
                    wanted=wanted,
                    cache_key_fn=cache_key_fn,
                    scale=scale,
                    flip_y=flip_y,
                    detect_arcs=detect_arcs,
                    arc_fit_tol_mm=arc_fit_tol_mm,
                    min_arc_angle_deg=min_arc_angle_deg,
                    arc_min_pts=arc_min_pts,
                    max_workers=max_workers,
                )
            else:
                results = []
                for page_number in wanted:
                    page = doc.load_page(page_number - 1)
                    page_data, elapsed, _ = _extract_with_cache(
                        page,
                        page_number,
                        pdf_path,
                        cache_key_fn,
                        scale,
                        flip_y,
                        detect_arcs,
                        arc_fit_tol_mm,
                        min_arc_angle_deg,
                        arc_min_pts,
                    )
                    results.append((page_number, page_data, elapsed))

            results.sort(key=lambda x: wanted.index(x[0]))

        for idx, (page_number, page_data, elapsed) in enumerate(results, start=1):
            total_elapsed += elapsed
            timer.note_page()
            _yielded_at = time.perf_counter()
            yield page_number, page_data
            # Control only returns here once the consumer has finished with this page,
            # so the gap is host-side construction, not extraction. This is why the
            # split needs no cooperation from the host.
            timer.add("host_build_ms", (time.perf_counter() - _yielded_at) * 1000.0)

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

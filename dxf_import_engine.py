# -*- coding: utf-8 -*-
# dxf_import_engine.py -- Pipeline orchestrator: PDF -> pdfcadcore -> DXF
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Top-level conversion pipeline.  Ties together PyMuPDF extraction,
pdfcadcore recognition, and ezdxf DXF building.
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Dict, List, Optional

# Ensure project root is importable
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import ezdxf

from pdfcadcore.primitives import PageData, RecognitionConfig
from pdfcadcore.primitive_extractor import extract_page
from pdfcadcore.import_config import ImportConfig
from pdfcadcore import recognition, reset_ids
from pdfcadcore.auto_mode import classify_page_content
from pdfcadcore.hatch_detector import tag_hatch_primitives
from pdfcadcore.geometry_cleanup import cleanup_primitives

from dxf_builder import build_dxf
from dxf_text_builder import reset_text_styles


def _convert_via_package(
    input_path: str,
    output_path: str,
    config: ImportConfig,
    dxf_version: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, int]:
    """Full BCS-ARCH-001 pipeline (auto/raster/hybrid + raster pages)."""
    from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
    from librecad_pdf_importer.importer import run_import

    def _log(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    overrides = {
        "user_scale": config.user_scale,
        "import_text": config.import_text,
        "text_mode": config.text_mode,
        "pages": config.pages,
        "ignore_images": config.ignore_images,
        "raster_fallback": config.raster_fallback,
        "raster_dpi": config.raster_dpi,
        "detect_arcs": config.detect_arcs,
        "arc_fit_tol_mm": config.arc_fit_tol_mm,
        "map_dashes": config.map_dashes,
    }
    _log(f"Using package pipeline for mode={config.import_mode}...")
    run = run_import(input_path, mode=config.import_mode, overrides=overrides)
    export = export_to_dxf(
        run.extraction,
        output_path,
        DxfExportOptions(
            include_text=bool(config.import_text) and config.text_mode != "geometry",
            text_mode=str(config.text_mode or "labels"),
            include_images=not config.ignore_images,
            group_by_page=True,
            prefer_source_layers=True,
            attach_metadata=True,
            dxf_version=dxf_version,
            map_dashes=bool(config.map_dashes),
        ),
    )
    text_count = run.extraction.text_count if config.import_text else 0
    return {
        "pages": len(run.extraction.pages),
        "entities": export.entity_count,
        "text_items": text_count,
    }


def convert(
    input_path: str,
    output_path: str,
    config: Optional[ImportConfig] = None,
    dxf_version: str = "R2010",
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, int]:
    """Convert a PDF file to DXF.

    Parameters
    ----------
    input_path:
        Path to the source PDF.
    output_path:
        Destination path for the DXF file.
    config:
        Import configuration.  Defaults to :meth:`ImportConfig.auto` (BCS-ARCH-001).
    dxf_version:
        Target DXF version (``"R12"`` through ``"R2018"``).
    progress_callback:
        Optional callable receiving status strings during processing.

    Returns
    -------
    dict
        Statistics: ``pages``, ``entities``, ``text_items``.
    """
    if config is None:
        config = ImportConfig.auto()

    if config.import_mode in ("auto", "raster", "hybrid"):
        return _convert_via_package(
            input_path, output_path, config, dxf_version, progress_callback
        )

    def _log(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    # ------------------------------------------------------------------
    # 1. Reset ID counter (keeps IDs predictable per conversion)
    # ------------------------------------------------------------------
    reset_ids()
    reset_text_styles()

    # ------------------------------------------------------------------
    # 2. Open PDF with PyMuPDF
    # ------------------------------------------------------------------
    _log("Opening PDF...")
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
    except ImportError:
        try:
            import fitz  # Legacy fallback
        except ImportError as exc:
            raise ImportError(
                "PyMuPDF (fitz) is required.  Install with:  pip install PyMuPDF"
            ) from exc

    pdf_doc = fitz.open(input_path)
    total_pages = pdf_doc.page_count

    # Determine which pages to convert
    if config.pages is not None:
        page_indices = [p for p in config.pages if 0 <= p < total_pages]
    else:
        page_indices = list(range(total_pages))

    if not page_indices:
        pdf_doc.close()
        raise ValueError(
            f"No valid pages to convert (PDF has {total_pages} page(s))."
        )

    _log(f"PDF opened: {total_pages} page(s), converting {len(page_indices)}")

    # ------------------------------------------------------------------
    # 3. Extract pages via pdfcadcore (with auto-mode, cleanup, hatch)
    # ------------------------------------------------------------------
    pages_data: List[PageData] = []

    for page_num in page_indices:
        _log(f"Extracting page {page_num + 1}/{total_pages}...")
        fitz_page = pdf_doc.load_page(page_num)

        # 3a. Auto-mode classification (before extraction)
        if config.import_mode == "auto":
            raw_drawings = fitz_page.get_drawings()
            text_blocks = fitz_page.get_text("blocks") or []
            text_words = fitz_page.get_text("words") or []
            mbox = fitz_page.mediabox
            page_area = float(mbox.width) * float(mbox.height)
            classification = classify_page_content(
                raw_drawings,
                text_blocks_count=len(text_blocks),
                text_words_count=len(text_words),
                page_area=page_area,
            )
            if classification["type"] in ("glyph_flood", "fill_art"):
                _log(
                    f"Auto-mode: {classification['reason']} — "
                    f"decorative page; vector extraction may be sparse "
                    f"(page {page_num + 1})"
                )

        # 3b. Extract primitives
        page_data = extract_page(
            fitz_page,
            page_num=page_num + 1,   # 1-based for display / layer names
            scale=config.user_scale,
            flip_y=config.flip_y,
            detect_arcs=config.detect_arcs,
            arc_fit_tol_mm=config.arc_fit_tol_mm,
            min_arc_angle_deg=config.min_arc_angle_deg,
        )

        # 3c. Geometry cleanup (remove micro-segments)
        if config.cleanup_level != "conservative" or config.min_seg_len > 0:
            cleanup_stats = cleanup_primitives(
                page_data.primitives,
                cleanup_level=config.cleanup_level,
            )
            if config.verbose and cleanup_stats.get("removed_micro", 0) > 0:
                _log(f"Cleanup: removed "
                     f"{cleanup_stats['removed_micro']} micro-segments "
                     f"on page {page_num + 1}")

        # 3d. Hatch detection (post-extraction, on primitives)
        if config.hatch_mode != "import":
            hatch_ids = tag_hatch_primitives(page_data.primitives)
            if hatch_ids:
                if config.hatch_mode == "skip":
                    page_data.primitives = [
                        p for p in page_data.primitives
                        if p.id not in hatch_ids
                    ]
                elif config.hatch_mode == "group":
                    for p in page_data.primitives:
                        if p.id in hatch_ids:
                            p.generic_tags.append("hatch_line")

        pages_data.append(page_data)

    pdf_doc.close()

    # ------------------------------------------------------------------
    # 4. Optional recognition pass
    # ------------------------------------------------------------------
    if config.detect_arcs or config.make_faces:
        rec_config = RecognitionConfig()
        for page_data in pages_data:
            _log(f"Recognition on page {page_data.page_number}...")
            recognition.run(page_data, mode="auto", config=rec_config)

    # ------------------------------------------------------------------
    # 5. Build DXF document
    # ------------------------------------------------------------------
    _log("Building DXF...")
    doc, entity_count, text_count = build_dxf(
        pages_data, config, dxf_version=dxf_version,
    )

    # ------------------------------------------------------------------
    # 6. Save DXF
    # ------------------------------------------------------------------
    _log(f"Saving DXF to {output_path}...")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    doc.saveas(output_path)

    # ------------------------------------------------------------------
    # 7. Optional validation
    # ------------------------------------------------------------------
    if config.verbose:
        _log("Validating output...")
        try:
            test_doc = ezdxf.readfile(output_path)
            auditor = test_doc.audit()
            if auditor.has_errors:
                _log(f"  Validation warnings: {len(auditor.errors)} issue(s)")
            else:
                _log("  Validation passed.")
        except Exception as exc:  # noqa: BLE001
            _log(f"  Validation skipped: {exc}")

    # ------------------------------------------------------------------
    # 8. Return stats
    # ------------------------------------------------------------------
    _log("Done.")
    return {
        "pages": len(page_indices),
        "entities": entity_count,
        "text_items": text_count,
    }

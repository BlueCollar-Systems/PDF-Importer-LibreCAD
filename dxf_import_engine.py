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
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Ensure project root is importable
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pdfcadcore.import_config import ImportConfig


def _default_import_report_path(output_path: str) -> str:
    stem = Path(output_path).with_suffix("")
    return str(stem) + "_import_report.json"


def _convert_via_package(
    input_path: str,
    output_path: str,
    config: ImportConfig,
    dxf_version: str,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Full BCS-ARCH-001 pipeline (auto/raster/hybrid + raster pages)."""
    from librecad_pdf_importer.exporters.dxf_exporter import (
        DxfExportOptions,
        TextRepresentationDeliveryError,
        export_to_dxf,
        summarize_text_delivery,
    )
    from librecad_pdf_importer.importer import (
        failure_import_report_path,
        run_import,
        write_import_report,
    )

    def _log(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    report_path = _default_import_report_path(output_path)
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
        "import_report_path": report_path,
    }
    t0 = time.perf_counter()
    _log(f"Using package pipeline for mode={config.import_mode}...")
    t_phase = time.perf_counter()
    run = run_import(input_path, mode=config.import_mode, overrides=overrides)
    run_import_ms = (time.perf_counter() - t_phase) * 1000.0
    try:
        t_phase = time.perf_counter()
        try:
            export = export_to_dxf(
                run.extraction,
                output_path,
                DxfExportOptions(
                    include_text=bool(config.import_text),
        text_mode=str(config.text_mode or "text"),
                    include_images=not config.ignore_images,
                    group_by_page=True,
                    prefer_source_layers=True,
                    attach_metadata=True,
                    dxf_version=dxf_version,
                    map_dashes=bool(config.map_dashes),
                    provenance_opts=run.config,
                ),
            )
        except TextRepresentationDeliveryError as exc:
            failure_path = failure_import_report_path(output_path, run)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            write_import_report(
                run,
                failure_path,
                elapsed_ms=elapsed_ms,
                performance_phases={
                    "run_import_ms": run_import_ms,
                    "export_dxf_ms": (time.perf_counter() - t_phase) * 1000.0,
                    "total_ms": elapsed_ms,
                },
            )
            run.import_report_path = failure_path
            exc.failure_report_path = failure_path
            exc.args = (f"{exc}\nComplete failure report: {failure_path}",)
            _log(f"Import stopped; complete failure report: {failure_path}")
            raise
        export_dxf_ms = (time.perf_counter() - t_phase) * 1000.0
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        write_import_report(
            run,
            report_path,
            elapsed_ms=elapsed_ms,
            performance_phases={
                "run_import_ms": run_import_ms,
                "export_dxf_ms": export_dxf_ms,
                "total_ms": elapsed_ms,
            },
        )
        text_count = run.extraction.text_count if config.import_text else 0
        text_delivery = summarize_text_delivery(
            str(config.text_mode or "none") if config.import_text else "none",
            export.text_deliveries,
            report_path=report_path,
        )
        _log(
            "Text delivery: requested={requested}; delivered={delivered}; "
            "fallback={fallback}; items={items}; report={report}".format(
                requested=text_delivery["requested"],
                delivered=text_delivery["delivered"],
                fallback="yes" if text_delivery["fallback_used"] else "no",
                items=text_delivery["item_count"],
                report=text_delivery["report_path"],
            )
        )
        return {
            "pages": len(run.extraction.pages),
            "entities": export.entity_count,
            "text_items": text_count,
            "import_report_path": report_path,
            "text_delivery": text_delivery,
        }
    finally:
        run.close()


def convert(
    input_path: str,
    output_path: str,
    config: Optional[ImportConfig] = None,
    dxf_version: str = "R2010",
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
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

    canonical_modes = ("auto", "vector", "raster", "hybrid")
    if config.import_mode not in canonical_modes:
        raise ValueError(
            f"Unknown import mode: {config.import_mode!r}. "
            "Valid modes: auto, vector, raster, hybrid (BCS-ARCH-001)."
        )
    return _convert_via_package(
        input_path, output_path, config, dxf_version, progress_callback
    )

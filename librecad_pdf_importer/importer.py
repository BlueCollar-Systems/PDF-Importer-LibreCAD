"""Mode-driven import orchestration for LibreCAD PDF importer (BCS-ARCH-001)."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from pdfcadcore.import_bounds import compute_import_bounds
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.import_report import build_import_report

from .core.document import DocumentExtraction, ExtractionOptions, extract_document


@dataclass
class ImportRun:
    extraction: DocumentExtraction
    config: ImportConfig
    import_report_path: Optional[str] = None


def _pymupdf_version() -> str:
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        import fitz  # type: ignore
    return str(getattr(fitz, "__version__", "") or "")


def write_import_report(
    run: ImportRun,
    output_path: str,
    *,
    importer_version: str = "1.0.14",
    host_version: str = "",
    elapsed_ms: float = 0.0,
) -> str:
    """Emit bcs.import_report/1.1 JSON for one import run."""
    extraction = run.extraction
    pages = extraction.pages
    layer_names: set[str] = set()
    resolved_scale = None
    for page in pages:
        layer_names.update(page.page_data.layers or [])
        rs = page.page_data.resolved_scale
        if rs and rs.confidence > 0 and (
            resolved_scale is None or rs.confidence > resolved_scale.get("confidence", 0)
        ):
            resolved_scale = {
                "factor": rs.factor,
                "notation": rs.notation,
                "source": rs.source,
                "confidence": rs.confidence,
                "fallback_reason": rs.fallback_reason,
            }

    bounds = None
    page_data = [p.page_data for p in pages]
    if page_data:
        bounds_obj = compute_import_bounds(page_data)
        if bounds_obj is not None:
            bounds = [round(v, 1) for v in bounds_obj.as_tuple()]

    fallback_used = any(
        (p.resolved_mode or "") == "raster" for p in pages
    )
    fallback_reason = next(
        (p.resolved_reason for p in pages if (p.resolved_mode or "") == "raster"),
        None,
    )

    report = build_import_report(
        host_app="librecad",
        host_version=host_version,
        runtime_lang="python",
        runtime_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        importer_version=importer_version,
        pdf_path=extraction.pdf_path,
        mode=run.config.import_mode,
        pages=len(pages),
        primitive_count=extraction.primitive_count,
        text_count=extraction.text_count,
        layer_count=len(layer_names),
        bbox=bounds,
        elapsed_ms=elapsed_ms,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        pdf_engine_version=_pymupdf_version(),
        extra={
            "resolved_scale": resolved_scale,
            "auto_mode": extraction.summary().get("auto_mode"),
        },
    )
    report.write_json(output_path)
    return output_path


def _mode_config(mode: str) -> ImportConfig:
    """Dispatch a BCS-ARCH-001 mode name to the matching ImportConfig.

    The four valid modes are: auto, vector, raster, hybrid.
    No preset names are accepted; any other value raises ValueError.
    """
    key = (mode or "auto").strip().lower()
    if key == "auto":
        return ImportConfig.auto()
    if key == "vector":
        return ImportConfig.vector()
    if key == "raster":
        return ImportConfig.raster()
    if key == "hybrid":
        return ImportConfig.hybrid()
    raise ValueError(
        f"Unknown import mode: {mode!r}. "
        "Valid modes: auto, vector, raster, hybrid (BCS-ARCH-001)."
    )


def run_import(pdf_path: str, mode: str = "auto",
               overrides: Optional[Dict[str, Any]] = None) -> ImportRun:
    cfg = _mode_config(mode)
    for key, value in (overrides or {}).items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)

    opts = ExtractionOptions(
        pages=cfg.pages,
        scale=cfg.user_scale,
        flip_y=cfg.flip_y,
        import_text=cfg.import_text,
        import_images=not cfg.ignore_images,
        import_mode=cfg.import_mode,
        raster_fallback=cfg.raster_fallback,
        raster_dpi=cfg.raster_dpi,
        detect_arcs=cfg.detect_arcs,
        arc_fit_tol_mm=cfg.arc_fit_tol_mm,
    )

    extraction = extract_document(pdf_path, opts)
    run = ImportRun(extraction=extraction, config=cfg)

    report_path = (overrides or {}).get("import_report_path")
    if report_path:
        run.import_report_path = write_import_report(run, str(report_path), elapsed_ms=0.0)

    return run


def apply_uniform_scale(extraction: DocumentExtraction, factor: float) -> None:
    if factor <= 0:
        raise ValueError("Scale factor must be positive.")

    for page in extraction.pages:
        data = page.page_data
        data.width *= factor
        data.height *= factor

        for primitive in data.primitives:
            primitive.points = [(x * factor, y * factor) for x, y in (primitive.points or [])]
            if primitive.center:
                primitive.center = (primitive.center[0] * factor, primitive.center[1] * factor)
            if primitive.radius is not None:
                primitive.radius *= factor
            if primitive.bbox:
                x0, y0, x1, y1 = primitive.bbox
                primitive.bbox = (x0 * factor, y0 * factor, x1 * factor, y1 * factor)
            if primitive.line_width is not None:
                primitive.line_width *= factor
            if primitive.area is not None:
                primitive.area *= factor * factor

        for txt in data.text_items:
            tx, ty = txt.insertion
            txt.insertion = (tx * factor, ty * factor)
            if txt.bbox:
                x0, y0, x1, y1 = txt.bbox
                txt.bbox = (x0 * factor, y0 * factor, x1 * factor, y1 * factor)
            txt.font_size *= factor

        for image in page.images:
            image.x_mm *= factor
            image.y_mm *= factor
            image.width_mm *= factor
            image.height_mm *= factor

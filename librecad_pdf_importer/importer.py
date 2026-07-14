"""Mode-driven import orchestration for LibreCAD PDF importer (BCS-ARCH-001)."""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from pdfcadcore.import_bounds import compute_import_bounds
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.import_report import build_actual_text_entity_types, build_import_report
from pdfcadcore.model3d_intent import analyze_model3d_intent

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


def _importer_version() -> str:
    try:
        from pdf2dxf import __version__

        return str(__version__ or "")
    except (ImportError, AttributeError):
        return ""


def _normalized_text_mode(text_mode: Any) -> str:
    mode = str(text_mode or "labels").strip().lower()
    return "3d_text" if mode == "text3d" else mode


def _text_mode_fallback_for_report(config: ImportConfig, text_source_spans: int) -> Optional[Dict[str, Any]]:
    """Return the real text substitution record accumulated during export.

    LibreCAD has no true 3D text, so its documented alias is a permanent
    host-limit fallback.  Outline failures are recorded by dxf_exporter only
    after it knows the source TEXT was retained in the DXF.
    """
    if not bool(getattr(config, "import_text", False)):
        return None
    requested = _normalized_text_mode(getattr(config, "text_mode", "labels"))
    if requested == "3d_text":
        return {
            "requested": "3d_text",
            "delivered": "labels",
            "reason": "host_2d_no_3d_text",
            "count": max(0, int(text_source_spans or 0)),
        }

    records = list(getattr(config, "_text_mode_fallbacks", []) or [])
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and _normalized_text_mode(record.get("requested")) == requested
        and str(record.get("delivered") or "").strip()
        and str(record.get("reason") or "").strip()
    ]
    if not matching:
        return None

    first = matching[0]
    return {
        "requested": requested,
        "delivered": str(first.get("delivered") or "").strip(),
        "reason": str(first.get("reason") or "").strip(),
        "count": sum(max(0, int(record.get("count", 0) or 0)) for record in matching),
    }


def write_import_report(
    run: ImportRun,
    output_path: str,
    *,
    importer_version: Optional[str] = None,
    host_version: str = "",
    elapsed_ms: float = 0.0,
    performance_phases: Optional[Dict[str, float]] = None,
    helper_timings_ms: Optional[Dict[str, float]] = None,
) -> str:
    """Emit bcs.import_report/1.1 JSON for one import run."""
    extraction = run.extraction
    pages = extraction.pages
    layer_names: set[str] = set()
    resolved_scale = None
    scale_hints = {
        "title_block_detected": False,
        "dimension_count": 0,
        "alternate_scale_factors": [],
    }
    alternate_factors: set[float] = set()
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
        if rs and rs.factor and rs.confidence > 0:
            alternate_factors.add(float(rs.factor))
        profile = getattr(page, "profile", None)
        if profile and getattr(profile, "titleblock_likely", False):
            scale_hints["title_block_detected"] = True

    bounds = None
    page_data = [p.page_data for p in pages]
    if page_data:
        bounds_obj = compute_import_bounds(page_data)
        if bounds_obj is not None:
            bounds = [round(v, 1) for v in bounds_obj.as_tuple()]

    text_items = [
        txt
        for page in pages
        for txt in (page.page_data.text_items or [])
    ]
    text_source_spans = len(text_items)
    text_glyph_estimate = sum(len(str(getattr(txt, "text", "") or "")) for txt in text_items)

    fallback_used = any(
        (p.resolved_mode or "") == "raster" for p in pages
    )
    fallback_reason = next(
        (p.resolved_reason for p in pages if (p.resolved_mode or "") == "raster"),
        None,
    )

    from pdfcadcore.fitz_loader import sample_process_mb

    phases = dict(performance_phases or {})
    if elapsed_ms > 0 and "total_ms" not in phases:
        phases["total_ms"] = float(elapsed_ms)

    extra = {
        "resolved_scale": resolved_scale,
        "scale_hints": {
            **scale_hints,
            "alternate_scale_factors": sorted(alternate_factors),
        },
        "auto_mode": extraction.summary().get("auto_mode"),
        "model_3d_intent": analyze_model3d_intent(
            text_items,
            host_supports_3d=False,
        ).to_dict(),
        "model_3d": {
            "supported": False,
            "enabled": False,
            "mode": "off",
            "solids_created": 0,
            "skipped_reason": "LibreCAD is a 2D DXF host; use SketchUp, FreeCAD, or Blender for generated solids.",
        },
    }
    requested_text_mode = _normalized_text_mode(run.config.text_mode)
    delivered_text_entity_counts = dict(
        getattr(run.config, "_delivered_text_entity_counts", {}) or {}
    )
    delivered_font_rendered = None
    if delivered_text_entity_counts:
        try:
            delivered_font_rendered = bool(
                int(delivered_text_entity_counts.get("dxf_text", 0) or 0)
            )
        except (TypeError, ValueError):
            delivered_font_rendered = None
    if run.config.import_text and requested_text_mode != "none":
        extra["actual_text_entity_types"] = build_actual_text_entity_types(
            host_app="librecad",
            text_mode=requested_text_mode,
            count=extraction.text_count,
            font_rendered=delivered_font_rendered,
            examples=[
                str(getattr(txt, "text", "") or "")[:20]
                for txt in text_items[:3]
                if str(getattr(txt, "text", "") or "").strip()
            ],
            delivered_counts=delivered_text_entity_counts or None,
        )

    text_fallback = _text_mode_fallback_for_report(run.config, text_source_spans)

    report = build_import_report(
        host_app="librecad",
        host_version=host_version,
        runtime_lang="python",
        runtime_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        importer_version=importer_version or _importer_version(),
        pdf_path=extraction.pdf_path,
        mode=run.config.import_mode,
        pages=len(pages),
        primitive_count=extraction.primitive_count,
        text_count=extraction.text_count,
        layer_count=len(layer_names),
        bbox=bounds,
        elapsed_ms=elapsed_ms,
        performance_phases=phases or None,
        helper_timings_ms=helper_timings_ms,
        peak_mb=sample_process_mb(),
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        pdf_engine_version=_pymupdf_version(),
        import_text=bool(run.config.import_text),
        text_mode=requested_text_mode,
        text_source_spans=text_source_spans,
        text_glyph_estimate=text_glyph_estimate,
        text_fallback=text_fallback,
        extra=extra,
    )

    provenance_objects = list(getattr(run.config, "_source_provenance_objects", []) or [])
    if provenance_objects:
        from pdfcadcore.source_provenance import (
            SCHEMA,
            ensure_import_session_id,
            write_source_provenance_sidecar,
        )

        session_id = ensure_import_session_id(run.config)
        sidecar_path = str(Path(output_path).with_name("source_provenance.json"))
        build_stamp = str((report.report_meta or {}).get("build_stamp") or "")
        write_source_provenance_sidecar(
            output_path=sidecar_path,
            import_session_id=session_id,
            pdf_path=extraction.pdf_path,
            objects=provenance_objects,
            host_app="librecad",
            importer_version=importer_version or _importer_version(),
            build_stamp=build_stamp,
            page_count=len(pages) or None,
        )
        report.extra["source_provenance_path"] = Path(sidecar_path).name
        report.extra["source_provenance"] = {
            "schema": SCHEMA,
            "import_session_id": session_id,
            "object_count": len(provenance_objects),
        }

    from pdfcadcore.parts_bootstrap import extract_bootstrap_rows, write_parts_bootstrap_sidecar

    bootstrap_path = str(Path(output_path).with_name("parts_bootstrap.json"))
    bootstrap_rows = extract_bootstrap_rows(text_items)
    build_stamp = str((report.report_meta or {}).get("build_stamp") or "")
    import_build_stamp = {
        "host": "librecad",
        "semver": importer_version or _importer_version(),
    }
    if build_stamp:
        import_build_stamp["build_stamp"] = build_stamp
    write_parts_bootstrap_sidecar(
        bootstrap_path,
        extraction.pdf_path,
        page_count=len(pages) or 0,
        rows=bootstrap_rows,
        import_build_stamp=import_build_stamp,
    )
    report.extra["parts_bootstrap"] = {
        "schema": "bcs.parts_bootstrap/1.0",
        "sidecar_path": Path(bootstrap_path).name,
        "row_count": len(bootstrap_rows),
        "note": "BOM row extraction from drawing text" if bootstrap_rows else "no BOM rows detected",
    }

    report.write_json(output_path)
    try:
        import_build_stamp["report_sha256"] = hashlib.sha256(
            Path(output_path).read_bytes()
        ).hexdigest()
        write_parts_bootstrap_sidecar(
            bootstrap_path,
            extraction.pdf_path,
            page_count=len(pages) or 0,
            rows=bootstrap_rows,
            import_build_stamp=import_build_stamp,
        )
    except OSError:
        pass
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
    incoming = overrides or {}
    if "text_mode" not in incoming:
        cfg.text_mode = "labels"
    for key, value in incoming.items():
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
    if cfg.import_text and str(cfg.text_mode or "labels") != "none":
        try:
            from pdfcadcore.source_provenance import ensure_import_session_id

            ensure_import_session_id(cfg)
        except ImportError:
            pass

    report_path = incoming.get("import_report_path")
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

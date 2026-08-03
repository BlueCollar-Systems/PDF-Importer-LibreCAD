# -*- coding: utf-8 -*-
# dxf_import_engine.py -- Pipeline orchestrator: PDF -> pdfcadcore -> DXF
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Top-level conversion pipeline.  Ties together PyMuPDF extraction,
pdfcadcore recognition, and ezdxf DXF building.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import marshal
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import uuid

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.math import Matrix44
from ezdxf.xref import ConflictPolicy, load_modelspace

# Ensure project root is importable
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pdfcadcore.import_config import ImportConfig
from conversion_control import ActivePageCancelled, check_cancel
from librecad_runtime import resolve_librecad_runtime_binding


class ResumeMismatchError(RuntimeError):
    """Existing certified work belongs to a different source or option set."""


class ConversionCancelled(RuntimeError):
    """User cancellation after preserving every already-certified page."""

    def __init__(self, completed_pages: int, total_pages: int, output_path: str):
        self.completed_pages = int(completed_pages)
        self.total_pages = int(total_pages)
        self.output_path = str(output_path)
        super().__init__(
            f"Conversion cancelled. Certified pages were kept: "
            f"{self.completed_pages}/{self.total_pages}. Resume with the same PDF and options."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _engine_sha256() -> str:
    """Identify loose-source or frozen engine bytes without assuming ``__file__`` exists."""
    source_path = Path(__file__).resolve()
    if source_path.is_file():
        return _sha256(source_path)
    loader = globals().get("__loader__")
    get_code = getattr(loader, "get_code", None)
    code = get_code(__name__) if callable(get_code) else None
    if code is None:
        raise RuntimeError("Cannot establish conversion-engine identity for resume safety.")
    return hashlib.sha256(marshal.dumps(code)).hexdigest()


def _dxf_asset_inventory(dxf_path: Path, containment_root: Path) -> list[dict[str, str]]:
    """Hash every external image needed to reopen *dxf_path* safely."""
    drawing = Path(dxf_path).resolve()
    root = Path(containment_root).resolve()
    document = ezdxf.readfile(drawing)
    inventory: list[dict[str, str]] = []
    for definition in document.objects.query("IMAGEDEF"):
        raw_path = Path(str(definition.dxf.filename))
        asset = raw_path.resolve() if raw_path.is_absolute() else (drawing.parent / raw_path).resolve()
        if not asset.is_relative_to(root):
            raise RuntimeError(f"DXF image asset escapes its conversion directory: {asset}")
        if not asset.is_file():
            raise FileNotFoundError(f"DXF image asset is missing: {asset}")
        inventory.append(
            {
                "file": asset.relative_to(root).as_posix(),
                "sha256": _sha256(asset),
            }
        )
    return sorted(inventory, key=lambda item: item["file"])


def _asset_inventory_matches(records: object, containment_root: Path) -> bool:
    if not isinstance(records, list):
        return False
    root = Path(containment_root).resolve()
    for record in records:
        if not isinstance(record, dict):
            return False
        relative = record.get("file")
        expected = record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            return False
        asset = (root / relative).resolve()
        if not asset.is_relative_to(root) or not asset.is_file() or _sha256(asset) != expected:
            return False
    return True


def _resume_options_identity(
    config: ImportConfig,
    dxf_version: str,
    librecad_executable: Optional[str] = None,
) -> tuple[str, dict]:
    from pdf2dxf import __version__

    librecad_binding = resolve_librecad_runtime_binding(librecad_executable)
    payload = {
        "importer_version": str(__version__),
        "engine_sha256": _engine_sha256(),
        "dxf_version": str(dxf_version),
        "librecad_runtime_binding": librecad_binding.identity_payload(),
        "config": asdict(config),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest(), payload


def _selected_page_indices(input_path: str, config: ImportConfig) -> list[int]:
    configured = getattr(config, "pages", None)
    if configured is not None:
        pages = sorted({int(page) for page in configured if int(page) >= 0})
        if not pages:
            raise ValueError("No valid pages were selected.")
        return pages
    from pdfcadcore.fitz_loader import safe_open

    with safe_open(input_path) as document:
        return list(range(len(document)))


def _assemble_checkpoints(checkpoints: list[Path], output_path: str) -> None:
    if not checkpoints:
        return
    output = Path(output_path).expanduser().resolve()
    sources = [ezdxf.readfile(path) for path in checkpoints]
    target = ezdxf.new(dxfversion=sources[0].dxfversion)
    target.units = sources[0].units
    target_msp = target.modelspace()
    stack_offset = 0.0
    delivered_asset_root = output.with_name(f"{output.stem}_assets") / "resume"
    for checkpoint, source in zip(checkpoints, sources, strict=True):
        for image_definition in source.objects.query("IMAGEDEF"):
            raw_path = Path(str(image_definition.dxf.filename))
            source_asset = (
                raw_path.resolve()
                if raw_path.is_absolute()
                else (checkpoint.parent / raw_path).resolve()
            )
            if not source_asset.is_file():
                raise FileNotFoundError(
                    f"Certified checkpoint image asset is missing: {source_asset}"
                )
            delivered_asset_root.mkdir(parents=True, exist_ok=True)
            delivered_asset = delivered_asset_root / (
                _sha256(source_asset) + source_asset.suffix.lower()
            )
            if delivered_asset.is_file():
                if _sha256(delivered_asset) != _sha256(source_asset):
                    raise RuntimeError(
                        f"Resume image digest collision: {delivered_asset.name}"
                    )
            else:
                shutil.copy2(source_asset, delivered_asset)
            image_definition.dxf.filename = os.path.relpath(
                delivered_asset,
                output.parent,
            ).replace("\\", "/")
        before = {entity.dxf.handle for entity in target_msp}
        source_extents = ezdxf_bbox.extents(source.modelspace(), fast=False)
        load_modelspace(
            source,
            target,
            conflict_policy=ConflictPolicy.XREF_PREFIX,
        )
        added = [entity for entity in target_msp if entity.dxf.handle not in before]
        if stack_offset:
            transform = Matrix44.translate(0.0, -stack_offset, 0.0)
            for entity in added:
                transformer = getattr(entity, "transform", None)
                if callable(transformer):
                    transformer(transform)
        if source_extents.has_data:
            height = max(1.0, float(source_extents.extmax.y - source_extents.extmin.y))
        else:
            height = 1.0
        stack_offset += height * 1.2

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.partial{output.suffix}")
    target.saveas(temporary)
    ezdxf.readfile(temporary)
    os.replace(temporary, output)


def _write_resumable_summary(
    output_path: str,
    manifest: Dict[str, Any],
    selected_pages: list[int],
) -> str:
    output = Path(output_path).expanduser().resolve()
    summary_path = output.with_name(f"{output.stem}_import_report.json")
    completed = manifest.get("completed", {})
    page_records = [completed[str(page)] for page in selected_pages if str(page) in completed]
    payload = {
        "schema": "bcs.resumable_import_report/1.0",
        "result": "complete" if len(page_records) == len(selected_pages) else "cancelled",
        "input_sha256": manifest["source_sha256"],
        "options_sha256": manifest["options_sha256"],
        "pages_requested": [page + 1 for page in selected_pages],
        "pages_certified": [record["page_number"] for record in page_records],
        "page_reports": [record.get("import_report_path", "") for record in page_records],
        "output": str(output),
    }
    _atomic_json(summary_path, payload)
    return str(summary_path)


def _ensure_assembled(
    checkpoints: list[Path],
    output_path: str,
    manifest: Dict[str, Any],
    manifest_path: Path,
) -> bool:
    """Build once, then trust only an exact checkpoint/output digest binding."""
    if not checkpoints:
        return False
    checkpoint_digests = [
        {"file": checkpoint.name, "sha256": _sha256(checkpoint)}
        for checkpoint in checkpoints
    ]
    identity = hashlib.sha256(
        json.dumps(checkpoint_digests, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    output = Path(output_path).expanduser().resolve()
    prior = manifest.get("assembled") or {}
    if (
        output.is_file()
        and prior.get("checkpoint_set_sha256") == identity
        and prior.get("output_sha256") == _sha256(output)
        and _asset_inventory_matches(prior.get("assets"), output.parent)
    ):
        return False
    _assemble_checkpoints(checkpoints, str(output))
    manifest["assembled"] = {
        "checkpoint_set_sha256": identity,
        "output_sha256": _sha256(output),
        "page_count": len(checkpoints),
        "assets": _dxf_asset_inventory(output, output.parent),
    }
    _atomic_json(manifest_path, manifest)
    return True


def _convert_resumable(
    input_path: str,
    output_path: str,
    config: ImportConfig,
    dxf_version: str,
    progress_callback: Optional[Callable[[str], None]],
    cancel_requested: Optional[Callable[[], bool]],
    restart_on_resume_mismatch: bool,
    librecad_executable: Optional[str],
) -> Dict[str, Any]:
    source = Path(input_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    session_dir = output.with_name(f"{output.stem}_resume")
    manifest_path = session_dir / "session.json"
    source_sha256 = _sha256(source)
    options_sha256, options = _resume_options_identity(
        config,
        dxf_version,
        librecad_executable,
    )
    selected_pages = _selected_page_indices(str(source), config)
    manifest: Dict[str, Any] = {
        "schema": "bcs.librecad_resume/1.0",
        "source_sha256": source_sha256,
        "options_sha256": options_sha256,
        "options": options,
        "completed": {},
    }
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_mismatch = existing.get("source_sha256") != source_sha256
        options_mismatch = existing.get("options_sha256") != options_sha256
        if source_mismatch or options_mismatch:
            if not restart_on_resume_mismatch:
                mismatch = "PDF bytes" if source_mismatch else "options or importer bytes"
                raise ResumeMismatchError(
                    f"The existing resume session uses different {mismatch}; choose a new output path."
                )
            expected = output.with_name(f"{output.stem}_resume")
            if session_dir.resolve() != expected.resolve() or session_dir.parent != output.parent:
                raise RuntimeError("Refusing to reset an unexpected resume directory.")
            shutil.rmtree(session_dir)
            session_dir.mkdir(parents=True, exist_ok=False)
            _atomic_json(manifest_path, manifest)
        else:
            manifest = existing
    else:
        session_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(manifest_path, manifest)

    completed = manifest.setdefault("completed", {})
    resumed_pages = 0
    converted_pages = 0
    total = len(selected_pages)
    for position, page_index in enumerate(selected_pages, start=1):
        key = str(page_index)
        checkpoint = session_dir / f"page_{page_index + 1:04d}.dxf"
        record = completed.get(key)
        if (
            isinstance(record, dict)
            and checkpoint.is_file()
            and record.get("sha256") == _sha256(checkpoint)
            and _asset_inventory_matches(record.get("assets"), session_dir)
        ):
            resumed_pages += 1
            if progress_callback:
                progress_callback(f"Page {position}/{total} certified (resumed)")
            continue
        completed.pop(key, None)
        if cancel_requested and cancel_requested():
            certified = [session_dir / completed[str(page)]["file"] for page in selected_pages if str(page) in completed]
            _ensure_assembled(certified, str(output), manifest, manifest_path)
            _write_resumable_summary(str(output), manifest, selected_pages)
            raise ConversionCancelled(len(certified), total, str(output))

        page_config = copy.deepcopy(config)
        page_config.pages = [page_index]
        try:
            page_stats = _convert_via_package(
                str(source),
                str(checkpoint),
                page_config,
                dxf_version,
                progress_callback,
                cancel_requested=cancel_requested,
                librecad_executable=librecad_executable,
            )
        except ActivePageCancelled as exc:
            checkpoint.unlink(missing_ok=True)
            certified = [
                session_dir / completed[str(page)]["file"]
                for page in selected_pages
                if str(page) in completed
            ]
            _ensure_assembled(certified, str(output), manifest, manifest_path)
            _write_resumable_summary(str(output), manifest, selected_pages)
            raise ConversionCancelled(len(certified), total, str(output)) from exc
        completed[key] = {
            "page_number": page_index + 1,
            "file": checkpoint.name,
            "sha256": _sha256(checkpoint),
            "entities": int(page_stats.get("entities", 0)),
            "text_items": int(page_stats.get("text_items", 0)),
            "import_report_path": str(page_stats.get("import_report_path", "")),
            "text_delivery": dict(page_stats.get("text_delivery") or {}),
            "assets": _dxf_asset_inventory(checkpoint, session_dir),
        }
        _atomic_json(manifest_path, manifest)
        converted_pages += 1
        if progress_callback:
            progress_callback(f"Page {position}/{total} certified")

    certified_paths = [session_dir / completed[str(page)]["file"] for page in selected_pages]
    _ensure_assembled(certified_paths, str(output), manifest, manifest_path)
    report_path = _write_resumable_summary(str(output), manifest, selected_pages)
    records = [completed[str(page)] for page in selected_pages]
    deliveries = [record.get("text_delivery") or {} for record in records]
    delivered = {str(item.get("delivered") or "none") for item in deliveries}
    requested = {str(item.get("requested") or "none") for item in deliveries}
    return {
        "pages": total,
        "entities": sum(int(record.get("entities", 0)) for record in records),
        "text_items": sum(int(record.get("text_items", 0)) for record in records),
        "import_report_path": report_path,
        "resumed_pages": resumed_pages,
        "converted_pages": converted_pages,
        "text_delivery": {
            "requested": next(iter(requested)) if len(requested) == 1 else "mixed",
            "delivered": next(iter(delivered)) if len(delivered) == 1 else "mixed",
            "fallback_used": any(bool(item.get("fallback_used")) for item in deliveries),
            "item_count": sum(int(item.get("item_count", 0)) for item in deliveries),
            "report_path": report_path,
        },
    }


def _default_import_report_path(output_path: str) -> str:
    stem = Path(output_path).with_suffix("")
    return str(stem) + "_import_report.json"


def _convert_via_package(
    input_path: str,
    output_path: str,
    config: ImportConfig,
    dxf_version: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    librecad_executable: Optional[str] = None,
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
        "_cancel_requested": cancel_requested,
        "_progress_callback": progress_callback,
    }
    t0 = time.perf_counter()
    _log(f"Using package pipeline for mode={config.import_mode}...")
    check_cancel(cancel_requested, "before page extraction")
    t_phase = time.perf_counter()
    run = run_import(input_path, mode=config.import_mode, overrides=overrides)
    run_import_ms = (time.perf_counter() - t_phase) * 1000.0
    try:
        check_cancel(cancel_requested, "before DXF export")
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
                    librecad_executable=librecad_executable,
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
    *,
    resumable: bool = False,
    cancel_requested: Optional[Callable[[], bool]] = None,
    restart_on_resume_mismatch: bool = False,
    librecad_executable: Optional[str] = None,
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
    if resumable:
        return _convert_resumable(
            input_path,
            output_path,
            config,
            dxf_version,
            progress_callback,
            cancel_requested,
            restart_on_resume_mismatch,
            librecad_executable,
        )
    return _convert_via_package(
        input_path,
        output_path,
        config,
        dxf_version,
        progress_callback,
        cancel_requested=cancel_requested,
        librecad_executable=librecad_executable,
    )

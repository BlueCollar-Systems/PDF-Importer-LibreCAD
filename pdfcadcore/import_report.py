# -*- coding: utf-8 -*-
"""Shared import_report.json schema for BlueCollar PDF importers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "bcs.import_report/1.1"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_strings(values: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_fidelity_diagnostics(
    *,
    primitive_count: int = 0,
    text_count: int = 0,
    layer_count: int = 0,
    warnings: int = 0,
    fallback_used: bool = False,
    fallback_reason: Optional[str] = None,
    import_text: Optional[bool] = None,
    text_mode: Optional[str] = None,
    text_source_spans: Optional[int] = None,
    text_glyph_estimate: Optional[int] = None,
) -> Dict[str, Any]:
    """Return portable, user-facing fidelity signals for support and UI."""

    primitives = int(primitive_count or 0)
    text_entities = int(text_count or 0)
    layers = int(layer_count or 0)
    warning_count = int(warnings or 0)
    source_spans = int(text_source_spans or 0)
    glyph_estimate = int(text_glyph_estimate or 0)
    mode = str(text_mode or "").strip()
    reason = str(fallback_reason or "").strip()

    if primitives >= 50:
        quality_level = "high"
        signals = ["good_vector_content"]
    elif primitives >= 10:
        quality_level = "moderate"
        signals = ["limited_vector_content"]
    elif primitives > 0:
        quality_level = "low"
        signals = ["very_limited_vector_content"]
    else:
        quality_level = "empty"
        signals = ["no_vector_geometry_created"]

    actions: List[str] = []
    if fallback_used:
        signals.append("fallback_used")
        if "raster" in reason.lower():
            actions.append(
                "If editable geometry is required, retry Vector or Hybrid mode and confirm the PDF contains vector data."
            )
        else:
            actions.append("Review the fallback reason and attach the import report when requesting support.")

    if warning_count:
        signals.append("warnings_present")
        actions.append("Review the warning count and last import log before trusting the drawing for production use.")

    if layers == 0:
        signals.append("no_pdf_layers_detected")
    elif layers > 0:
        signals.append("pdf_layers_preserved")

    if import_text is False:
        signals.append("text_import_disabled")
    elif mode:
        signals.append(f"text_mode_{mode}")
        if mode in {"glyphs", "geometry"}:
            actions.append("Use Labels or 3D Text mode when editable text is more important than exact glyph outlines.")
        elif mode in {"labels", "3d_text"}:
            actions.append("Use Geometry or Glyphs mode when exact visual text outlines are more important than editability.")

    if import_text and source_spans > 0 and text_entities == 0:
        signals.append("source_text_seen_but_no_text_entities_created")
        actions.append("Retest with another text mode and compare the text_source_spans count against visible text.")

    if glyph_estimate >= 1000:
        signals.append("dense_text_glyph_workload")
        actions.append("For heavy PDFs on older PCs, import one page first and compare Labels versus Glyphs/Geometry performance.")

    return {
        "quality_level": quality_level,
        "signals": _unique_strings(signals),
        "recommended_actions": _unique_strings(actions),
    }


_HOST_LABELS = {
    "freecad": "FreeCAD",
    "librecad": "LibreCAD",
    "blender": "Blender",
    "sketchup": "SketchUp",
}


def _basename(path: str) -> str:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return name or "the PDF"


def _format_text_mode(mode: str) -> str:
    key = str(mode or "").strip().lower()
    labels = {
        "geometry": "geometry text",
        "glyphs": "glyph geometry",
        "3d_text": "3D text",
        "labels": "labels",
        "outlines": "outlines",
    }
    return labels.get(key, key.replace("_", " ") if key else "")


def build_human_summary(report: ImportReport | Dict[str, Any]) -> str:
    """One plain-English paragraph describing what happened during import."""

    data = report.to_dict() if isinstance(report, ImportReport) else dict(report or {})
    host_key = str((data.get("host") or {}).get("app") or "importer").lower()
    host = _HOST_LABELS.get(host_key, host_key.title() or "Importer")

    input_block = data.get("input") or {}
    result = data.get("result") or {}
    perf = data.get("performance") or {}
    fallback = data.get("fallback") or {}
    extra = data.get("extra") or {}
    diagnostics = extra.get("diagnostics") or {}

    pages = int(input_block.get("pages") or 0)
    primitives = int(result.get("primitives") or 0)
    text_count = int(result.get("text_entities") or 0)
    layers = int(result.get("layers") or 0)
    warnings = int(result.get("warnings") or 0)
    elapsed_ms = float(perf.get("elapsed_ms") or 0.0)
    elapsed_s = elapsed_ms / 1000.0 if elapsed_ms > 0 else 0.0

    mode = str(data.get("mode") or "auto")
    text_mode = _format_text_mode(str(extra.get("text_mode") or ""))
    pdf_name = _basename(str(input_block.get("file") or ""))

    parts: List[str] = []
    page_phrase = f"{pages} page{'s' if pages != 1 else ''}" if pages else "the PDF"
    parts.append(f"Imported {page_phrase} from {pdf_name} into {host} using {mode} mode")

    if text_mode:
        parts[-1] += f" with {text_mode}"

    outcome = []
    if primitives:
        outcome.append(f"{primitives} vector primitive{'s' if primitives != 1 else ''}")
    if text_count:
        outcome.append(f"{text_count} text item{'s' if text_count != 1 else ''}")
    if layers:
        outcome.append(f"{layers} PDF layer{'s' if layers != 1 else ''}")

    if outcome:
        parts.append("Created " + ", ".join(outcome))
    else:
        parts.append("No editable geometry was created")

    if elapsed_s > 0:
        parts.append(f"in {elapsed_s:.1f}s")

    scale = extra.get("resolved_scale") or {}
    if isinstance(scale, dict) and scale.get("factor"):
        notation = str(scale.get("notation") or "").strip()
        source = str(scale.get("source") or "drawing").replace("_", " ")
        scale_bit = f"Scale resolved from {source}"
        if notation:
            scale_bit += f" ({notation})"
        conf = scale.get("confidence")
        if conf is not None:
            try:
                scale_bit += f", confidence {float(conf) * 100:.0f}%"
            except (TypeError, ValueError):
                pass
        parts.append(scale_bit)

    auto_reason = str(extra.get("auto_reason") or "").strip()
    if auto_reason and mode == "auto":
        parts.append(f"Auto mode chose this path because {auto_reason.rstrip('.')}")

    if fallback.get("used"):
        reason = str(fallback.get("reason") or "fallback").replace("_", " ")
        parts.append(f"Raster or degraded fallback was used ({reason})")
    elif primitives > 0:
        parts.append("Vector extraction completed without raster fallback")

    quality = str(diagnostics.get("quality_level") or "").strip()
    if quality:
        parts.append(f"Overall fidelity: {quality}")

    if warnings:
        parts.append(
            f"{warnings} warning{'s' if warnings != 1 else ''} recorded — review the import log before production use"
        )

    paragraph = ". ".join(part.rstrip(".") for part in parts if part).strip()
    if paragraph and not paragraph.endswith("."):
        paragraph += "."
    return paragraph


@dataclass
class ImportReport:
    """Cross-host import report aligned with board Q-03-a."""

    schema: str = SCHEMA
    host: Dict[str, str] = field(default_factory=dict)
    runtime: Dict[str, str] = field(default_factory=dict)
    importer: Dict[str, str] = field(default_factory=dict)
    pdf_engine: Dict[str, str] = field(default_factory=dict)
    input: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    performance: Dict[str, Any] = field(default_factory=dict)
    fallback: Dict[str, Any] = field(default_factory=lambda: {"used": False, "reason": None})
    mode: str = "auto"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    def write_json(self, output_path: str, indent: int = 2) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(indent=indent) + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportReport":
        return cls(
            schema=str(data.get("schema", SCHEMA)),
            host=dict(data.get("host", {}) or {}),
            runtime=dict(data.get("runtime", {}) or {}),
            importer=dict(data.get("importer", {}) or {}),
            pdf_engine=dict(data.get("pdf_engine", {}) or {}),
            input=dict(data.get("input", {}) or {}),
            result=dict(data.get("result", {}) or {}),
            performance=dict(data.get("performance", {}) or {}),
            fallback=dict(data.get("fallback", {}) or {"used": False, "reason": None}),
            mode=str(data.get("mode", "auto")),
            extra=dict(data.get("extra", {}) or {}),
        )

    @classmethod
    def read_json(cls, input_path: str) -> "ImportReport":
        return cls.from_dict(json.loads(Path(input_path).read_text(encoding="utf-8")))


def build_import_report(
    *,
    host_app: str,
    host_version: str = "",
    runtime_lang: str = "python",
    runtime_version: str = "",
    importer_version: str = "",
    pdf_path: str,
    mode: str = "auto",
    pages: int = 0,
    primitive_count: int = 0,
    text_count: int = 0,
    layer_count: int = 0,
    bbox: Optional[List[float]] = None,
    warnings: int = 0,
    elapsed_ms: float = 0.0,
    peak_mb: float = 0.0,
    performance_phases: Optional[Dict[str, float]] = None,
    helper_timings_ms: Optional[Dict[str, float]] = None,
    fallback_used: bool = False,
    fallback_reason: Optional[str] = None,
    pdf_engine_name: str = "pymupdf",
    pdf_engine_version: str = "",
    pdf_engine_wheel_tag: str = "",
    import_text: Optional[bool] = None,
    text_mode: Optional[str] = None,
    text_source_spans: Optional[int] = None,
    text_glyph_estimate: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ImportReport:
    input_block: Dict[str, Any] = {
        "file": str(pdf_path),
        "pages": int(pages),
    }
    try:
        if pdf_path and Path(pdf_path).is_file():
            input_block["sha256"] = _sha256_file(pdf_path)
    except OSError:
        pass

    extra_block = dict(extra or {})
    if import_text is not None:
        extra_block.setdefault("import_text", bool(import_text))
    if text_mode is not None:
        extra_block.setdefault("text_mode", str(text_mode))
    if text_source_spans is not None:
        extra_block.setdefault("text_source_spans", int(text_source_spans))
    if text_glyph_estimate is not None:
        extra_block.setdefault("text_glyph_estimate", int(text_glyph_estimate))
    extra_block.setdefault(
        "diagnostics",
        build_fidelity_diagnostics(
            primitive_count=primitive_count,
            text_count=text_count,
            layer_count=layer_count,
            warnings=warnings,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            import_text=import_text,
            text_mode=text_mode,
            text_source_spans=text_source_spans,
            text_glyph_estimate=text_glyph_estimate,
        ),
    )

    performance_block: Dict[str, Any] = {
        "elapsed_ms": float(elapsed_ms),
        "peak_mb": float(peak_mb),
    }
    if performance_phases:
        phases = {
            str(k): float(v)
            for k, v in performance_phases.items()
            if v is not None
        }
        if phases:
            performance_block["phases"] = phases
    if helper_timings_ms:
        helpers = {
            str(k): float(v)
            for k, v in helper_timings_ms.items()
            if v is not None
        }
        if helpers:
            performance_block["helpers_ms"] = helpers

    report = ImportReport(
        host={"app": host_app, "version": host_version},
        runtime={"lang": runtime_lang, "version": runtime_version},
        importer={"version": importer_version},
        pdf_engine={
            "name": pdf_engine_name,
            "version": pdf_engine_version,
            "wheel_tag": pdf_engine_wheel_tag,
        },
        input=input_block,
        result={
            "primitives": int(primitive_count),
            "text_entities": int(text_count),
            "layers": int(layer_count),
            "bbox": bbox,
            "warnings": int(warnings),
        },
        performance=performance_block,
        fallback={"used": bool(fallback_used), "reason": fallback_reason},
        mode=mode,
        extra=extra_block,
    )
    report.extra.setdefault("human_summary", build_human_summary(report))
    return report


__all__ = [
    "SCHEMA",
    "ImportReport",
    "build_fidelity_diagnostics",
    "build_human_summary",
    "build_import_report",
]

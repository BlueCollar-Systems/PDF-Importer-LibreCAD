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

    return ImportReport(
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


__all__ = ["SCHEMA", "ImportReport", "build_import_report"]

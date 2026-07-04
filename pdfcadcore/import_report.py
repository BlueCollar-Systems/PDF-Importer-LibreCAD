# -*- coding: utf-8 -*-
"""Shared import_report.json schema for BlueCollar PDF importers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .preflight_copy import SCALE_CROSSCHECK_BANNER

SCHEMA = "bcs.import_report/1.1"
SCALE_TRUST_CONFIDENCE = 0.70
SCALE_DIMENSION_TENSION_CONFIDENCE = 0.85
SCALE_FACTOR_DISAGREE_RATIO = 0.15
PERFORMANCE_HINT_ENTITY_THRESHOLD = 50_000
PERFORMANCE_HINT_PEAK_MB = 1024.0


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


def build_scale_crosscheck(extra: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Non-blocking scale warning when detection is weak or sources disagree."""

    scale = extra.get("resolved_scale") or {}
    if not isinstance(scale, dict):
        scale = {}

    hints = extra.get("scale_hints") or {}
    if not isinstance(hints, dict):
        hints = {}

    title_block = bool(hints.get("title_block_detected"))
    dimension_count = int(hints.get("dimension_count") or 0)
    alternate_factors = hints.get("alternate_scale_factors") or []
    if not isinstance(alternate_factors, list):
        alternate_factors = []

    warnings: List[str] = []
    reasons: List[str] = []

    conf: Optional[float] = None
    raw_conf = scale.get("confidence")
    if raw_conf is not None:
        try:
            conf = float(raw_conf)
        except (TypeError, ValueError):
            conf = None

    factor = scale.get("factor")
    fallback = str(scale.get("fallback_reason") or "").strip()
    source = str(scale.get("source") or "").strip()

    if fallback == "no_scale_detected" or not factor:
        warnings.append(
            "No drawing scale was detected in the title block or page text — verify manually before takeoff."
        )
        reasons.append("no_scale_detected")
    elif conf is not None and conf < SCALE_TRUST_CONFIDENCE:
        warnings.append(
            f"Scale detection confidence is low ({conf * 100:.0f}%) — verify with manual scale tools before takeoff."
        )
        reasons.append("low_confidence")

    if title_block and source and source != "titleblock" and factor:
        warnings.append(
            "A title block was detected but scale came from other page text — compare the title-block notation."
        )
        reasons.append("titleblock_source_mismatch")

    if (
        title_block
        and dimension_count >= 3
        and conf is not None
        and conf < SCALE_DIMENSION_TENSION_CONFIDENCE
        and factor
    ):
        warnings.append(
            f"Title-block scale may disagree with {dimension_count} detected dimension strings — spot-check one known dimension."
        )
        reasons.append("titleblock_dimension_tension")

    try:
        primary = float(factor) if factor else None
    except (TypeError, ValueError):
        primary = None

    if primary and primary > 0 and alternate_factors:
        for alt in alternate_factors:
            try:
                alt_factor = float(alt)
            except (TypeError, ValueError):
                continue
            if alt_factor <= 0:
                continue
            if abs(alt_factor - primary) / max(primary, alt_factor) > SCALE_FACTOR_DISAGREE_RATIO:
                warnings.append(
                    "Multiple scale notations on the sheet disagree — confirm which scale applies to this view."
                )
                reasons.append("conflicting_scale_notations")
                break

    if not warnings:
        return None

    return {
        "level": "warn",
        "reasons": _unique_strings(reasons),
        "messages": _unique_strings(warnings),
        "banner": SCALE_CROSSCHECK_BANNER,
        "user_message": SCALE_CROSSCHECK_BANNER,
    }


def build_font_embedding_hints(doc: Any) -> Dict[str, Any]:
    """Detect non-embedded PDF fonts that may substitute on the host OS."""

    if doc is None:
        return {}
    non_embedded: List[str] = []
    try:
        page_count = len(doc)
    except TypeError:
        return {}
    for page_index in range(page_count):
        try:
            page = doc[page_index]
            fonts = page.get_fonts(full=True)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            continue
        for entry in fonts or []:
            if len(entry) < 6:
                continue
            extension = str(entry[1] or "").strip().lower()
            # PyMuPDF get_fonts(full=True) returns:
            # xref, extension, type, basefont, resource name, encoding, referencer.
            # extension == "n/a" is the practical signal for base/non-embedded fonts.
            embedded = bool(extension and extension != "n/a")
            if embedded:
                continue
            name = str(entry[3] or entry[4] or "unknown").strip()
            if name and name not in non_embedded:
                non_embedded.append(name)
    if not non_embedded:
        return {}
    sample = ", ".join(non_embedded[:5])
    if len(non_embedded) > 5:
        sample += f" (+{len(non_embedded) - 5} more)"
    note = (
        f"Non-embedded PDF fonts detected ({sample}) — Labels mode may substitute "
        "Windows or CAD fonts on this PC; use Outlines or Glyphs for exact appearance."
    )
    return {
        "non_embedded_fonts": non_embedded,
        "font_substitution_note": note,
    }


def build_pdf_interactive_note(doc: Any) -> Dict[str, Any]:
    """Warn when PDF contains JavaScript or open actions (never executed by importers)."""

    if doc is None:
        return {}

    def key_present(xref: int, key: str) -> bool:
        try:
            value = doc.xref_get_key(xref, key)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        if not value:
            return False
        if isinstance(value, tuple):
            kind = str(value[0] or "").strip().lower()
            raw = str(value[1] or "").strip().lower()
            return kind not in {"", "null"} and raw not in {"", "null"}
        return str(value).strip().lower() not in {"", "null"}

    flags: List[str] = []
    try:
        js = doc.get_js() if hasattr(doc, "get_js") else None
        if js:
            flags.append("JavaScript")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        catalog = doc.pdf_catalog()
        if catalog and key_present(catalog, "OpenAction"):
            flags.append("OpenAction")
        if catalog and key_present(catalog, "AA"):
            flags.append("AdditionalActions")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    try:
        for xref in range(1, int(doc.xref_length())):
            if key_present(xref, "JS") or key_present(xref, "JavaScript"):
                flags.append("JavaScript")
                break
            try:
                subtype = doc.xref_get_key(xref, "S")
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
            raw = " ".join(str(part) for part in subtype) if isinstance(subtype, tuple) else str(subtype)
            if "JavaScript" in raw:
                flags.append("JavaScript")
                break
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    if not flags:
        return {}
    flags = _unique_strings(flags)
    joined = ", ".join(flags)
    return {
        "pdf_interactive_flags": flags,
        "pdf_interactive_note": (
            f"PDF contains document scripts or actions ({joined}) — import uses static "
            "geometry only; scripts are not executed."
        ),
    }


def build_report_meta(
    *,
    host_app: str,
    importer_version: str,
    report_sha256: str = "",
    imported_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Return report_meta block with build_stamp for support and T-01 checks."""

    host = str(host_app or "").strip().lower()
    semver = str(importer_version or "").strip()
    sha = str(report_sha256 or "").strip().lower()
    stamp_parts = [part for part in (host, semver) if part]
    if sha:
        stamp_parts.append(f"report {sha[:12]}")
    return {
        "build_stamp": " · ".join(stamp_parts),
        "host": host,
        "semver": semver,
        "report_sha256": sha,
        "imported_at": imported_at or datetime.now(timezone.utc).isoformat(),
    }


def build_performance_hint(
    *,
    primitive_count: int = 0,
    text_count: int = 0,
    peak_mb: float = 0.0,
) -> Optional[str]:
    """Plain-English hint for weak PCs on large imports."""

    entities = int(primitive_count or 0) + int(text_count or 0)
    peak = float(peak_mb or 0.0)
    if entities >= PERFORMANCE_HINT_ENTITY_THRESHOLD or peak >= PERFORMANCE_HINT_PEAK_MB:
        return (
            "Large PDF — on PCs with less than 8 GB RAM, import one page at a time "
            "using the Pages field."
        )
    return None


def _pdf_audit_extras(pdf_path: str) -> Dict[str, Any]:
    """Open PDF briefly for font/interactive audits (best-effort)."""

    path = str(pdf_path or "").strip()
    if not path or not Path(path).is_file():
        return {}
    try:
        from .fitz_loader import safe_open
    except ImportError:
        return {}
    doc = None
    merged: Dict[str, Any] = {}
    try:
        doc = safe_open(path)
        merged.update(build_font_embedding_hints(doc))
        merged.update(build_pdf_interactive_note(doc))
    except (OSError, RuntimeError, TypeError, ValueError):
        return merged
    finally:
        if doc is not None:
            try:
                doc.close()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
    return merged


def build_model_3d_extra(
    host_app: str,
    *,
    enabled: bool = False,
    stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Honest model_3d block for import_report.extra (R8-1)."""

    if stats:
        return dict(stats)
    host = str(host_app or "").lower()
    if host == "librecad":
        return {
            "supported": False,
            "enabled": False,
            "reason": "2D host — PDF import produces planar DXF only",
        }
    return {
        "supported": host in ("freecad", "blender", "sketchup"),
        "enabled": bool(enabled),
    }


def enrich_import_report_extras(report: "ImportReport") -> None:
    """Attach scale cross-check, performance hint, and refresh human_summary."""

    crosscheck = build_scale_crosscheck(report.extra)
    if crosscheck:
        report.extra["scale_crosscheck"] = crosscheck
    perf = report.performance if isinstance(report.performance, dict) else {}
    result = report.result if isinstance(report.result, dict) else {}
    hint = build_performance_hint(
        primitive_count=int(result.get("primitives") or 0),
        text_count=int(result.get("text_entities") or 0),
        peak_mb=float(perf.get("peak_mb") or 0.0),
    )
    if hint:
        report.extra["performance_hint"] = hint
    if "model_3d" not in report.extra:
        host = str((report.host or {}).get("app") or "")
        report.extra["model_3d"] = build_model_3d_extra(host)
    report.extra["human_summary"] = build_human_summary(report)


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

    crosscheck = extra.get("scale_crosscheck") or {}
    if isinstance(crosscheck, dict):
        banner = str(crosscheck.get("banner") or crosscheck.get("user_message") or "").strip()
        if banner:
            parts.append(f"Scale note: {banner.rstrip('.')}")

    font_note = str(extra.get("font_substitution_note") or "").strip()
    if font_note:
        parts.append(font_note.rstrip("."))

    interactive_note = str(extra.get("pdf_interactive_note") or "").strip()
    if interactive_note:
        parts.append(interactive_note.rstrip("."))

    perf_hint = str(extra.get("performance_hint") or "").strip()
    if perf_hint:
        parts.append(perf_hint.rstrip("."))

    paragraph = ". ".join(part.rstrip(".") for part in parts if part).strip()
    if paragraph and not paragraph.endswith("."):
        paragraph += "."
    return paragraph


@dataclass
class TextEntityVerification:
    """Text entity type verification for cross-host consistency."""

    entity_type: str = ""  # "label", "glyphs", "geometry", "3d_text"
    count: int = 0
    font_rendered: bool = False
    examples: List[str] = field(default_factory=list)
    native_label: int = 0
    native_3d_text: int = 0
    outline_curve_or_mesh: int = 0
    raw_geometry_edges: int = 0
    dxf_text: int = 0
    fallback_geometry: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_actual_text_entity_types(
    *,
    host_app: str,
    text_mode: str,
    count: int = 0,
    font_rendered: Optional[bool] = None,
    examples: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return the shared actual_text_entity_types payload."""

    host = str(host_app or "").strip().lower()
    mode = str(text_mode or "").strip().lower()
    total = max(0, int(count or 0))
    rendered = font_rendered
    if rendered is None:
        rendered = mode in {"labels", "label", "3d_text", "text3d"}

    info = TextEntityVerification(
        entity_type=mode,
        count=total,
        font_rendered=bool(rendered),
        examples=list(examples or [])[:3],
    )
    if total <= 0 or mode in {"", "none"}:
        return info.to_dict()

    if host == "librecad":
        if mode in {"labels", "label", "3d_text", "text3d"}:
            info.dxf_text = total
        elif mode in {"glyphs", "geometry", "outlines"}:
            info.raw_geometry_edges = total
        else:
            info.fallback_geometry = total
    elif host == "blender":
        if mode in {"labels", "label", "3d_text", "text3d"}:
            info.native_3d_text = total
        elif mode in {"glyphs", "geometry", "outlines"}:
            info.outline_curve_or_mesh = total
        else:
            info.fallback_geometry = total
    elif host == "freecad":
        if mode in {"labels", "label"}:
            info.native_label = total
        elif mode in {"3d_text", "text3d"}:
            info.native_3d_text = total
        elif mode in {"glyphs", "geometry", "outlines"}:
            info.outline_curve_or_mesh = total
        else:
            info.fallback_geometry = total
    elif host == "sketchup":
        if mode in {"labels", "label"}:
            info.native_label = total
        elif mode in {"3d_text", "text3d"}:
            info.native_3d_text = total
        elif mode in {"glyphs", "geometry", "outlines"}:
            info.outline_curve_or_mesh = total
        else:
            info.fallback_geometry = total
    return info.to_dict()


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
    report_meta: Dict[str, Any] = field(default_factory=dict)
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
            report_meta=dict(data.get("report_meta", {}) or {}),
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
    report_sha256 = ""
    try:
        if pdf_path and Path(pdf_path).is_file():
            report_sha256 = _sha256_file(pdf_path)
            input_block["sha256"] = report_sha256
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
    if pdf_path:
        extra_block.update(_pdf_audit_extras(pdf_path))

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
        report_meta=build_report_meta(
            host_app=host_app,
            importer_version=importer_version,
            report_sha256=report_sha256,
        ),
        extra=extra_block,
    )
    enrich_import_report_extras(report)
    return report


__all__ = [
    "SCHEMA",
    "SCALE_TRUST_CONFIDENCE",
    "PERFORMANCE_HINT_ENTITY_THRESHOLD",
    "PERFORMANCE_HINT_PEAK_MB",
    "ImportReport",
    "build_fidelity_diagnostics",
    "build_actual_text_entity_types",
    "build_report_meta",
    "build_font_embedding_hints",
    "build_human_summary",
    "build_pdf_interactive_note",
    "build_performance_hint",
    "build_scale_crosscheck",
    "build_model_3d_extra",
    "enrich_import_report_extras",
    "build_import_report",
]

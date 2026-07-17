# -*- coding: utf-8 -*-
"""Shared import_report.json schema for BlueCollar PDF importers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .preflight_copy import SCALE_CROSSCHECK_BANNER

SCHEMA = "bcs.import_report/1.1"
SCALE_TRUST_CONFIDENCE = 0.70
SCALE_DIMENSION_TENSION_CONFIDENCE = 0.85
SCALE_FACTOR_DISAGREE_RATIO = 0.15
PERFORMANCE_HINT_ENTITY_THRESHOLD = 50_000
PERFORMANCE_HINT_PEAK_MB = 1024.0


def _require_finite_json_numbers(value: Any, path: str = "") -> None:
    """Reject NaN and infinities with the exact report path that contains them."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"non-finite JSON number at {path or '<root>'}: {value!r}"
            )
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _require_finite_json_numbers(child, child_path)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            _require_finite_json_numbers(child, child_path)


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


def build_text_mode_fallback(
    *,
    requested: str,
    delivered: str,
    reason: str,
    count: int = 0,
) -> Optional[Dict[str, Any]]:
    """Normalize a text-mode substitution record for the fallback block.

    TEXTMODE-1 (owner directive 2026-07-13): mode substitution is never
    silent — the report carries requested mode, delivered mode, and reason.
    Returns ``None`` when there is no real substitution (missing modes or
    requested == delivered) so callers can pass the result straight to
    ``build_import_report(text_fallback=...)``.
    """
    req = str(requested or "").strip().lower()
    dlv = str(delivered or "").strip().lower()
    why = str(reason or "").strip()
    if not req or not dlv or req == dlv:
        return None
    try:
        n = int(count or 0)
    except (TypeError, ValueError):
        n = 0
    return {
        "requested": req,
        "delivered": dlv,
        "reason": why or "unspecified",
        "count": max(0, n),
    }


def build_fidelity_diagnostics(
    *,
    primitive_count: int = 0,
    text_count: int = 0,
    image_count: int = 0,
    layer_count: int = 0,
    warnings: int = 0,
    fallback_used: bool = False,
    fallback_reason: Optional[str] = None,
    import_text: Optional[bool] = None,
    text_mode: Optional[str] = None,
    text_source_spans: Optional[int] = None,
    text_glyph_estimate: Optional[int] = None,
    text_fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return portable, user-facing fidelity signals for support and UI."""

    primitives = int(primitive_count or 0)
    text_entities = int(text_count or 0)
    images = int(image_count or 0)
    layers = int(layer_count or 0)
    warning_count = int(warnings or 0)
    source_spans = int(text_source_spans or 0)
    glyph_estimate = int(text_glyph_estimate or 0)
    mode = str(text_mode or "").strip()
    if primitives >= 50:
        quality_level = "high"
        signals = ["good_vector_content"]
    elif primitives >= 10:
        quality_level = "moderate"
        signals = ["limited_vector_content"]
    elif primitives > 0:
        quality_level = "low"
        signals = ["very_limited_vector_content"]
    elif images > 0:
        quality_level = "raster"
        signals = ["raster_or_image_content_delivered"]
    else:
        quality_level = "empty"
        signals = ["no_vector_geometry_created"]

    actions: List[str] = []
    if fallback_used:
        signals.append("fallback_used")
        actions.append(
            "Inspect the item-specific proof and correct the importer while keeping "
            "the requested representation unchanged."
        )

    if text_fallback:
        signals.append("text_mode_fallback")
        requested_mode = str(text_fallback.get("requested") or "").strip()
        delivered_mode = str(text_fallback.get("delivered") or "").strip()
        if requested_mode and delivered_mode:
            actions.append(
                f"Requested text mode '{requested_mode}' was delivered as '{delivered_mode}' — "
                "see fallback.text in this report for the reason."
            )

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
        actions.append(
            "Confirm each source item reports the requested text representation "
            "with verified content, placement, rotation, width, and height."
        )

    if import_text and source_spans > 0 and text_entities == 0:
        signals.append("source_text_seen_but_no_text_entities_created")
        actions.append(
            "Treat missing delivered text entities as a failed import; inspect the "
            "item attempt history without changing the requested representation."
        )

    if glyph_estimate >= 1000:
        signals.append("dense_text_glyph_workload")
        actions.append(
            "For heavy PDFs on older PCs, diagnose one page first while keeping "
            "the requested representation unchanged."
        )

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
        f"Non-embedded PDF fonts detected ({sample}); preserve the requested "
        "representation, report any parent-native font substitution as "
        "source-font non-equivalent, and use an item fallback only after proof."
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


def build_import_contract_ready(report: "ImportReport") -> Dict[str, Any]:
    """Aggregate report-contract readiness for app/Report Doctor gates."""

    extra = report.extra if isinstance(report.extra, dict) else {}
    result = report.result if isinstance(report.result, dict) else {}
    meta = report.report_meta if isinstance(report.report_meta, dict) else {}

    open_failure = extra.get("open_failure")
    has_stamp = bool(str(meta.get("build_stamp") or "").strip())
    has_crosscheck = "scale_crosscheck" in extra
    text_count = int(result.get("text_entities") or 0)
    has_entity_types = "actual_text_entity_types" in extra
    text_ok = text_count <= 0 or has_entity_types
    status = str(extra.get("result_status") or result.get("status") or "success").lower()
    terminal_failure = extra.get("terminal_failure")
    result_succeeded = status not in {
        "failed",
        "error",
        "incomplete",
        "cancelled",
        "pending",
        "pending_export",
    } and terminal_failure is None
    source_spans = int(extra.get("text_source_spans") or 0)
    import_text_enabled = extra.get("import_text") is not False
    delivery = extra.get("text_representation_delivery")
    text_delivery_ok = (
        not import_text_enabled
        or source_spans <= 0
        or (
            isinstance(delivery, dict)
            and (
                delivery.get("required") is False
                or delivery.get("verified") is True
            )
        )
    )
    ready = (
        has_stamp
        and has_crosscheck
        and text_ok
        and text_delivery_ok
        and result_succeeded
        and open_failure is None
    )

    return {
        "ready": ready,
        "checks": {
            "build_stamp": has_stamp,
            "scale_crosscheck": has_crosscheck,
            "actual_text_entity_types": text_ok,
            "text_delivery": text_delivery_ok,
            "result_succeeded": result_succeeded,
            # Compatibility spelling retained for existing Report Doctor clients.
            "successful_result": result_succeeded,
            "no_terminal_failure": terminal_failure is None,
            "no_open_failure": open_failure is None,
        },
        "note": (
            "ready for contract consumers"
            if ready
            else "one or more import report contract checks need review"
        ),
    }


def enrich_import_report_extras(report: "ImportReport") -> None:
    """Attach shared derived fields and refresh human_summary."""

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
    report.extra["import_contract_ready"] = build_import_contract_ready(report)


def _format_text_mode(mode: str) -> str:
    key = str(mode or "").strip().lower()
    labels = {
        "geometry": "geometry text",
        "glyphs": "glyph geometry",
        "3d_text": "3D text",
        "text": "flat editable text",
        "labels": "labels",
        "outlines": "outlines",
        "raster": "item-scoped raster text",
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
    image_count = int(result.get("images") or 0)
    layers = int(result.get("layers") or 0)
    warnings = int(result.get("warnings") or 0)
    elapsed_ms = float(perf.get("elapsed_ms") or 0.0)
    elapsed_s = elapsed_ms / 1000.0 if elapsed_ms > 0 else 0.0

    mode = str(data.get("mode") or "auto")
    text_mode = _format_text_mode(str(extra.get("text_mode") or ""))
    pdf_name = _basename(str(input_block.get("file") or ""))

    parts: List[str] = []
    page_phrase = f"{pages} page{'s' if pages != 1 else ''}" if pages else "the PDF"
    result_status = str(
        extra.get("result_status") or result.get("status") or "success"
    ).lower()
    if result_status in {"failed", "error", "cancelled"}:
        parts.append(
            f"Import failed for {page_phrase} from {pdf_name} in {host} using {mode} mode"
        )
    elif result_status in {"incomplete", "pending", "pending_export"}:
        parts.append(
            f"Import is incomplete for {page_phrase} from {pdf_name} in {host} using {mode} mode"
        )
    else:
        parts.append(f"Imported {page_phrase} from {pdf_name} into {host} using {mode} mode")

    if text_mode:
        parts[-1] += f" with {text_mode}"

    outcome = []
    if primitives:
        outcome.append(f"{primitives} vector primitive{'s' if primitives != 1 else ''}")
    if text_count:
        outcome.append(f"{text_count} text item{'s' if text_count != 1 else ''}")
    if image_count:
        outcome.append(
            f"{image_count} raster/image placement{'s' if image_count != 1 else ''}"
        )
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

    entity_type: str = ""  # text, labels, 3d_text, glyphs, geometry, raster, mixed
    count: int = 0
    font_rendered: bool = False
    examples: List[str] = field(default_factory=list)
    native_label: int = 0
    native_text: int = 0
    native_3d_text: int = 0
    glyph_curve: int = 0
    geometry_mesh: int = 0
    raster_patch: int = 0
    outline_curve_or_mesh: int = 0
    raw_geometry_edges: int = 0
    raster_text_patch: int = 0
    dxf_text: int = 0
    raster_image: int = 0
    fallback_geometry: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


#: Bucket names hosts may report as DELIVERED entity counts (TEXTMODE-1).
TEXT_ENTITY_DELIVERED_BUCKETS = (
    "native_label",
    "native_text",
    "native_3d_text",
    "glyph_curve",
    "geometry_mesh",
    "raster_patch",
    "outline_curve_or_mesh",
    "raw_geometry_edges",
    "raster_text_patch",
    "dxf_text",
    "raster_image",
    "fallback_geometry",
)

_DELIVERED_ENTITY_TYPES = {
    "native_label": "labels",
    "native_text": "text",
    "native_3d_text": "3d_text",
    "glyph_curve": "glyphs",
    "geometry_mesh": "geometry",
    "outline_curve_or_mesh": "glyphs",
    "raw_geometry_edges": "geometry",
    "raster_patch": "raster",
    "raster_text_patch": "raster",
    "dxf_text": "text",
    "raster_image": "raster",
    "fallback_geometry": "geometry",
}


def build_actual_text_entity_types(
    *,
    host_app: str,
    text_mode: str,
    count: int = 0,
    font_rendered: Optional[bool] = None,
    examples: Optional[List[str]] = None,
    delivered_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Return the shared actual_text_entity_types payload.

    When ``delivered_counts`` is provided (mapping TEXT_ENTITY_DELIVERED_BUCKETS
    names to counts the host actually created), the payload reflects DELIVERED
    entities instead of being derived from the requested ``text_mode`` string
    (TEXTMODE-1: the report must be able to tell the truth when delivered
    differs from requested). Without it, the historical requested-mode
    derivation is used — fully backward compatible.
    """

    host = str(host_app or "").strip().lower()
    mode = str(text_mode or "").strip().lower()
    total = max(0, int(count or 0))
    rendered = font_rendered
    if rendered is None:
        rendered = mode in {
            "text",
            "native_text",
            "labels",
            "label",
            "3d_text",
            "text3d",
        }

    info = TextEntityVerification(
        entity_type=mode,
        count=total,
        font_rendered=bool(rendered),
        examples=list(examples or [])[:3],
    )
    if delivered_counts is not None:
        delivered_buckets: List[str] = []
        for bucket in TEXT_ENTITY_DELIVERED_BUCKETS:
            try:
                value = int(delivered_counts.get(bucket, 0) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                setattr(info, bucket, value)
                delivered_buckets.append(bucket)

        # Blender reports specific curve/mesh buckets plus the historical
        # outline aggregate. Count the aggregate only when no specific bucket
        # was supplied, so compatibility fields cannot double-count entities.
        count_buckets = list(delivered_buckets)
        if {"glyph_curve", "geometry_mesh"} & set(delivered_counts):
            count_buckets = [
                bucket for bucket in count_buckets
                if bucket != "outline_curve_or_mesh"
            ]
            info.outline_curve_or_mesh = max(
                int(info.outline_curve_or_mesh or 0),
                int(info.glyph_curve or 0) + int(info.geometry_mesh or 0),
            )
        delivered_total = sum(int(getattr(info, bucket, 0) or 0) for bucket in count_buckets)
        info.count = delivered_total
        if not delivered_buckets:
            info.entity_type = "none"
            info.font_rendered = False
            return info.to_dict()

        delivered_types = {
            _DELIVERED_ENTITY_TYPES[bucket] for bucket in delivered_buckets
        }
        info.entity_type = (
            next(iter(delivered_types)) if len(delivered_types) == 1 else "mixed"
        )
        if font_rendered is None:
            info.font_rendered = bool(
                {"native_label", "native_text", "native_3d_text", "dxf_text"}
                & set(delivered_buckets)
            )
        return info.to_dict()
    if total <= 0 or mode in {"", "none"}:
        return info.to_dict()

    if host == "librecad":
        if mode in {"text", "labels", "label", "3d_text", "text3d"}:
            info.dxf_text = total
        elif mode in {"glyphs", "geometry", "outlines"}:
            info.raw_geometry_edges = total
        else:
            info.fallback_geometry = total
    elif host == "blender":
        if mode in {"labels", "label"}:
            info.native_label = total
        elif mode in {"text"}:
            info.native_text = total
        elif mode in {"3d_text", "text3d"}:
            info.native_3d_text = total
        elif mode in {"glyphs"}:
            info.glyph_curve = total
            info.outline_curve_or_mesh = total
        elif mode in {"geometry", "outlines"}:
            info.geometry_mesh = total
            info.outline_curve_or_mesh = total
        elif mode == "raster":
            info.raster_patch = total
        else:
            info.fallback_geometry = total
    elif host == "freecad":
        if mode in {"text", "native_text"}:
            info.native_text = total
        elif mode in {"labels", "label"}:
            info.native_label = total
        elif mode in {"3d_text", "text3d"}:
            info.native_3d_text = total
        elif mode in {"glyphs", "geometry", "outlines"}:
            info.outline_curve_or_mesh = total
        elif mode in {"raster", "raster_text_patch"}:
            info.raster_text_patch = total
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
        payload = self.to_dict()
        _require_finite_json_numbers(payload)
        return json.dumps(
            payload,
            indent=indent,
            sort_keys=False,
            allow_nan=False,
        )

    def write_json(self, output_path: str, indent: int = 2) -> None:
        from .atomic_io import atomic_write_text

        atomic_write_text(output_path, self.to_json(indent=indent) + "\n")

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
    image_count: int = 0,
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
    text_fallback: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ImportReport:
    # TEXTMODE-1: a text-mode substitution is a loud fallback. Normalize the
    # host-supplied record; a real substitution marks fallback.used and adds
    # the fallback.text block {requested, delivered, reason, count}.
    text_fallback_block = None
    if text_fallback:
        text_fallback_block = build_text_mode_fallback(
            requested=str(text_fallback.get("requested") or ""),
            delivered=str(text_fallback.get("delivered") or ""),
            reason=str(text_fallback.get("reason") or ""),
            count=text_fallback.get("count") or 0,
        )
    effective_fallback_used = bool(fallback_used) or text_fallback_block is not None
    effective_fallback_reason = fallback_reason
    if text_fallback_block is not None and not effective_fallback_reason:
        effective_fallback_reason = (
            "text_mode_fallback: "
            f"{text_fallback_block['requested']} -> {text_fallback_block['delivered']} "
            f"({text_fallback_block['reason']})"
        )

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
            image_count=image_count,
            layer_count=layer_count,
            warnings=warnings,
            fallback_used=effective_fallback_used,
            fallback_reason=effective_fallback_reason,
            import_text=import_text,
            text_mode=text_mode,
            text_source_spans=text_source_spans,
            text_glyph_estimate=text_glyph_estimate,
            text_fallback=text_fallback_block,
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

    fallback_block: Dict[str, Any] = {
        "used": bool(effective_fallback_used),
        "reason": effective_fallback_reason,
    }
    if text_fallback_block is not None:
        fallback_block["text"] = text_fallback_block

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
            "images": int(image_count),
            "layers": int(layer_count),
            "bbox": bbox,
            "warnings": int(warnings),
        },
        performance=performance_block,
        fallback=fallback_block,
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
    "TEXT_ENTITY_DELIVERED_BUCKETS",
    "ImportReport",
    "build_fidelity_diagnostics",
    "build_text_mode_fallback",
    "build_actual_text_entity_types",
    "build_report_meta",
    "build_font_embedding_hints",
    "build_human_summary",
    "build_pdf_interactive_note",
    "build_performance_hint",
    "build_scale_crosscheck",
    "build_model_3d_extra",
    "build_import_contract_ready",
    "enrich_import_report_extras",
    "build_import_report",
]

"""DXF export adapter for LibreCAD workflows."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

import ezdxf
from ezdxf import path as ezdxf_path
from ezdxf.colors import RGB, aci2rgb, rgb2int
from ezdxf.units import MM
try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from ..core.document import DocumentExtraction

from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitive_extractor import (
    _page_rotation_transform,
    _transform_pdf_point,
)

from dxf_text_builder import (
    TextDeliveryAttempt,
    TextDeliveryResult,
    _block_reference_handles,
    _build_physical_glyph_ink_proof,
    _glyph_block_name_binds_source,
    _outline_reference_handles,
    _source_identity_sha256,
    _validate_parent_lff_ink_proof,
    _validate_physical_glyph_ink_proof,
    _visible_ink_expected,
    build_text,
    reset_text_styles,
    verify_serialized_outline_geometry,
)


@dataclass
class DxfExportOptions:
    include_text: bool = True
    text_mode: str = "text"
    include_images: bool = True
    group_by_page: bool = True
    prefer_source_layers: bool = True
    attach_metadata: bool = True
    dxf_version: str = "R2018"
    map_dashes: bool = True
    # Page arrangement for multi-page exports:
    # - "spread": stack pages with a 20% gap (default)
    # - "compact": stack pages with small configurable gap
    # - "touch": stack pages edge-to-edge (no gap)
    # - "overlay": place all pages on same origin
    page_arrangement: str = "spread"
    page_gap_ratio: float = 0.02
    provenance_opts: Optional[Any] = None


class TextRepresentationDeliveryError(RuntimeError):
    """A requested text item could not be verified or safely substituted."""

    def __init__(self, message: str, delivery: TextDeliveryResult):
        super().__init__(message)
        self.delivery = delivery
        self.failure_report_path = ""


@dataclass
class DxfExportResult:
    output_path: str
    entity_count: int
    layer_count: int
    image_count: int
    text_fallbacks: List[Dict[str, Any]] = field(default_factory=list)
    delivered_text_entity_counts: Dict[str, int] = field(default_factory=dict)
    text_deliveries: List[Dict[str, Any]] = field(default_factory=list)


def _normalized_text_mode(text_mode: str) -> str:
    mode = str(text_mode or "text").strip().lower()
    if mode == "text3d":
        return "3d_text"
    if mode == "native_text":
        return "text"
    return mode


def _delivered_text_entity_bucket(delivered_kind: str) -> str:
    kind = str(delivered_kind or "").strip().lower()
    if kind == "native_3d_text":
        return "native_3d_text"
    if kind == "dxf_native_text":
        return "dxf_text"
    if kind == "glyph_block_reference":
        return "outline_curve_or_mesh"
    if kind == "raw_geometry_edges":
        return "raw_geometry_edges"
    if kind == "raster_image":
        return "raster_image"
    return "dxf_text"


def summarize_text_delivery(
    requested: str,
    deliveries: List[Dict[str, Any]],
    *,
    report_path: str,
) -> Dict[str, Any]:
    """Return the loud, evidence-derived representation result shown to users."""

    requested_mode = _normalized_text_mode(requested)
    items = list(deliveries or [])
    final_modes = {
        _normalized_text_mode(str(item.get("final_representation") or ""))
        for item in items
        if item.get("final_representation")
    }
    delivered = (
        next(iter(final_modes))
        if len(final_modes) == 1
        else ("mixed" if final_modes else "none")
    )
    fallback_count = sum(bool(item.get("fallback_used")) for item in items)
    entity_count = sum(len(item.get("entity_handles") or []) for item in items)
    failures = [
        str(item.get("source_id") or "unknown")
        for item in items
        if item.get("verified") is not True or not item.get("final_representation")
    ]
    return {
        "requested": requested_mode,
        "delivered": delivered,
        "verified": not failures,
        "fallback_used": fallback_count > 0,
        "fallback_item_count": fallback_count,
        "item_count": len(items),
        "entity_count": entity_count,
        "failed_source_ids": failures,
        "report_path": str(report_path),
    }


def _fallback_reason_code(delivery: TextDeliveryResult) -> str:
    requested = _normalized_text_mode(delivery.requested_representation)
    if delivery.final_representation == "raster":
        return "structural_representations_failed_verification"
    if requested in {"glyphs", "geometry", "outlines"}:
        return "text2path_failed"
    return "requested_representation_failed_verification"


def _append_text_fallback(
    records: List[Dict[str, Any]],
    *,
    requested: str,
    delivered: str,
    reason: str,
    count: int,
) -> None:
    """Accumulate one mode substitution without losing repeated spans."""
    for record in records:
        if (
            record.get("requested") == requested
            and record.get("delivered") == delivered
            and record.get("reason") == reason
        ):
            record["count"] = int(record.get("count", 0) or 0) + int(count)
            return
    records.append(
        {
            "requested": requested,
            "delivered": delivered,
            "reason": reason,
            "count": int(count),
        }
    )


def _serialized_entity(doc: Any, handle: str, source_id: str) -> Any:
    entity = doc.entitydb.get(str(handle))
    if entity is None or not getattr(entity, "is_alive", True):
        raise RuntimeError(
            f"serialized text delivery {source_id}: missing live handle {handle}"
        )
    return entity


def _strict_finite_number(value: Any) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _strict_finite_vector(value: Any, *, length: int) -> Optional[Tuple[Any, ...]]:
    try:
        values = tuple(value)
    except TypeError:
        return None
    if len(values) != length or not all(_strict_finite_number(item) for item in values):
        return None
    return values


def _source_zero_text_page_proof(
    source_pdf: Path,
    page_number: int,
) -> Dict[str, Any]:
    """Re-read one exact source page and prove that it has no PDF text objects."""

    with fitz.open(str(source_pdf)) as source_doc:
        if page_number <= 0 or page_number > len(source_doc):
            raise RuntimeError(f"source page {page_number} is outside the PDF")
        page = source_doc[page_number - 1]
        plain_text = str(page.get_text("text") or "")
        words = list(page.get_text("words") or [])
        raw = dict(page.get_text("rawdict") or {})
        text_blocks = [
            block
            for block in list(raw.get("blocks") or [])
            if int(block.get("type", -1)) == 0
        ]
        lines = [
            line
            for block in text_blocks
            for line in list(block.get("lines") or [])
        ]
        spans = [
            span
            for line in lines
            for span in list(line.get("spans") or [])
        ]
        characters = [
            char
            for span in spans
            for char in list(span.get("chars") or [])
        ]
        raw_character_text = "".join(str(char.get("c") or "") for char in characters)
        source_image_xrefs = sorted(
            {
                int(image[0])
                for image in page.get_images(full=True)
                if image and int(image[0]) > 0
            }
        )
        payload: Dict[str, Any] = {
            "schema": "bcs.source_zero_text_page_proof/1.0",
            "source_page_number": int(page_number),
            "page_rotation_degrees": int(page.rotation or 0),
            "display_page_rect": [float(value) for value in page.rect],
            "media_box": [float(value) for value in page.mediabox],
            "plain_text_length": len(plain_text),
            "plain_text_sha256": hashlib.sha256(plain_text.encode("utf-8")).hexdigest(),
            "word_count": len(words),
            "text_block_count": len(text_blocks),
            "line_count": len(lines),
            "span_count": len(spans),
            "character_count": len(characters),
            "raw_character_text_sha256": hashlib.sha256(
                raw_character_text.encode("utf-8")
            ).hexdigest(),
            "source_image_xrefs": source_image_xrefs,
        }
        payload["verified_zero_text"] = bool(
            plain_text == ""
            and not words
            and not text_blocks
            and not lines
            and not spans
            and not characters
            and raw_character_text == ""
        )
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        payload["proof_sha256"] = hashlib.sha256(canonical).hexdigest()
        return payload


def _page_visual_image_artifact(
    expected: "_SerializedImageExpectation",
    *,
    reactor_handle: str,
    source_xref: int,
) -> Dict[str, Any]:
    return {
        "image_handle": expected.image_handle,
        "image_def_handle": expected.image_def_handle,
        "image_def_reactor_handle": str(reactor_handle),
        "source_xref": int(source_xref),
        "asset_path": str(expected.asset_path.resolve()),
        "asset_sha256": expected.asset_sha256,
        "pixel_size": list(expected.size_in_pixel),
        "insert": list(expected.insert),
        "u_vector_in_units": list(expected.u_vector_in_units),
        "v_vector_in_units": list(expected.v_vector_in_units),
    }


def _verify_page_visual_raster_delivery(
    doc: Any,
    delivery: Dict[str, Any],
    final_attempt: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    expected_source_pdf_path: Path,
    expected_source_pdf_sha256: str,
) -> None:
    """Verify a source-zero-text page against its already-delivered IMAGE entities."""

    source_id = str(delivery.get("source_id") or "")
    requested = _normalized_text_mode(delivery.get("requested_representation"))
    attempts = list(delivery.get("attempts") or [])
    if requested == "raster":
        ladder_ok = len(attempts) == 1 and attempts[0] is final_attempt
    else:
        failed = attempts[:-1]
        ladder_ok = bool(
            len(attempts) == 2
            and attempts[-1] is final_attempt
            and len(failed) == 1
            and str(failed[0].get("source_id") or "") == source_id
            and _normalized_text_mode(failed[0].get("attempted_representation"))
            == requested
            and failed[0].get("outcome") == "impossible"
            and failed[0].get("cleanup_verified") is True
            and not failed[0].get("created_entity_handles")
            and not failed[0].get("entity_handles")
        )
    if not ladder_ok:
        raise RuntimeError(
            f"serialized text delivery {source_id}: page visual fallback ladder changed"
        )
    if (
        final_attempt.get("strategy") != "existing_page_image_terminal_raster"
        or final_attempt.get("type_verified") is not True
        or final_attempt.get("visual_verified") is not True
        or final_attempt.get("cleanup_verified") is not True
    ):
        raise RuntimeError(
            f"serialized text delivery {source_id}: page visual terminal is unverified"
        )

    page_number = int(expected["page_number"])
    source_path = Path(str(expected_source_pdf_path)).expanduser().resolve()
    if not source_path.is_file():
        raise RuntimeError(
            f"serialized text delivery {source_id}: source PDF is missing"
        )
    actual_source_sha = _file_sha256(source_path)
    if (
        not expected_source_pdf_sha256
        or actual_source_sha != expected_source_pdf_sha256
        or str(expected.get("source_pdf_sha256") or "") != actual_source_sha
    ):
        raise RuntimeError(
            f"serialized text delivery {source_id}: source PDF digest changed"
        )
    fresh_zero_proof = _source_zero_text_page_proof(source_path, page_number)
    expected_zero_proof = dict(expected.get("source_zero_text_proof") or {})
    evidence = dict(final_attempt.get("evidence") or {})
    if (
        expected_zero_proof.get("verified_zero_text") is not True
        or fresh_zero_proof != expected_zero_proof
        or evidence.get("source_zero_text_proof") != expected_zero_proof
        or Path(str(evidence.get("source_pdf_path") or "")).expanduser().resolve()
        != source_path
        or str(evidence.get("source_pdf_sha256") or "") != actual_source_sha
        or evidence.get("source_page_number") != page_number
        or evidence.get("source_id") != source_id
    ):
        raise RuntimeError(
            f"serialized text delivery {source_id}: source-zero-text proof changed"
        )

    expected_bindings = list(expected.get("image_bindings") or [])
    expected_artifacts = [
        _page_visual_image_artifact(
            binding["expectation"],
            reactor_handle=str(binding["reactor_handle"]),
            source_xref=int(binding["source_xref"]),
        )
        for binding in expected_bindings
    ]
    expected_handles = [artifact["image_handle"] for artifact in expected_artifacts]
    expected_support = [
        handle
        for artifact in expected_artifacts
        for handle in (
            artifact["image_def_handle"],
            artifact["image_def_reactor_handle"],
        )
    ]
    if (
        list(map(str, delivery.get("entity_handles") or [])) != expected_handles
        or list(map(str, delivery.get("support_entity_handles") or []))
        != expected_support
        or list(delivery.get("referenced_entity_handles") or [])
        or evidence.get("image_artifacts") != expected_artifacts
        or evidence.get("image_entity_handles") != expected_handles
        or evidence.get("image_entity_count") != len(expected_handles)
        or evidence.get("existing_image_entity_reused") is not True
        or evidence.get("duplicate_image_entities_created") is not False
    ):
        raise RuntimeError(
            f"serialized text delivery {source_id}: existing IMAGE binding changed"
        )

    all_images = list(doc.modelspace().query("IMAGE"))
    for artifact in expected_artifacts:
        expected_insert = tuple(float(value) for value in artifact["insert"])
        expected_u = tuple(float(value) for value in artifact["u_vector_in_units"])
        expected_v = tuple(float(value) for value in artifact["v_vector_in_units"])

        def _same_artifact(
            image: Any,
            *,
            _artifact: Dict[str, Any] = artifact,
            _expected_insert: Tuple[float, ...] = expected_insert,
            _expected_u: Tuple[float, ...] = expected_u,
            _expected_v: Tuple[float, ...] = expected_v,
        ) -> bool:
            actual_insert = tuple(float(value) for value in image.dxf.insert)
            actual_u = tuple(
                float(value) * float(image.dxf.image_size.x)
                for value in image.dxf.u_pixel
            )
            actual_v = tuple(
                float(value) * float(image.dxf.image_size.y)
                for value in image.dxf.v_pixel
            )
            return bool(
                str(image.dxf.image_def_handle or "")
                == _artifact["image_def_handle"]
                and all(
                    math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                    for left, right in zip(
                        actual_insert + actual_u + actual_v,
                        _expected_insert + _expected_u + _expected_v,
                        strict=True,
                    )
                )
            )

        matching = [image for image in all_images if _same_artifact(image)]
        if (
            len(matching) != 1
            or str(matching[0].dxf.handle or "") != artifact["image_handle"]
            or str(matching[0].dxf.image_def_reactor_handle or "")
            != artifact["image_def_reactor_handle"]
        ):
            raise RuntimeError(
                f"serialized text delivery {source_id}: duplicate or altered page IMAGE"
            )


def _attached_attribute_is_visible(doc: Any, attribute: Any) -> bool:
    raw_invisible = attribute.dxf.get("invisible", 0)
    if (
        isinstance(raw_invisible, bool)
        or not isinstance(raw_invisible, int)
        or raw_invisible not in (0, 1)
    ):
        return True
    if raw_invisible == 1:
        return False
    if bool(getattr(attribute, "is_invisible", False)):
        return False
    try:
        transparency = float(attribute.transparency)
    except (TypeError, ValueError):
        transparency = 0.0
    if math.isfinite(transparency) and math.isclose(
        transparency,
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        return False
    try:
        layer = doc.layers.get(str(attribute.dxf.layer or "0"))
    except Exception:
        return True
    if not layer.is_on() or layer.is_frozen():
        return False
    if not _visible_ink_expected(str(attribute.dxf.text or "")):
        return False
    raw_height = attribute.dxf.get("height", None)
    if _strict_finite_number(raw_height) and float(raw_height) <= 0.0:
        return False
    return True


def _verify_serialized_text_deliveries(
    doc: Any,
    deliveries: List[Dict[str, Any]],
    *,
    expected_source_pdf_path: Optional[Path] = None,
    expected_source_pdf_sha256: str = "",
    expected_text_sources: Optional[Dict[str, Tuple[Any, ImportConfig]]] = None,
    expected_page_visual_sources: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Reconcile accepted item evidence against the re-opened DXF candidate."""

    expected_types = {
        "text": {"TEXT"},
        "glyphs": {"INSERT"},
        "geometry": {"LWPOLYLINE", "POLYLINE", "SOLID", "HATCH"},
        "raster": {"IMAGE"},
        "3d_text": {"TEXT"},
    }
    source_ids: set[str] = set()
    main_handles: set[str] = set()
    source_digest_cache: Dict[str, str] = {}
    for delivery in deliveries:
        source_id = str(delivery.get("source_id") or "")
        representation = str(delivery.get("final_representation") or "")
        if not source_id or source_id in source_ids:
            raise RuntimeError(
                f"serialized text delivery has invalid or duplicate source id: {source_id!r}"
            )
        source_ids.add(source_id)
        if representation == "labels":
            raise RuntimeError(
                f"serialized text delivery {source_id}: native Label is unsupported "
                "by DXF; TEXT/MTEXT report aliases are rejected"
            )
        if delivery.get("verified") is not True or representation not in expected_types:
            raise RuntimeError(
                f"serialized text delivery {source_id}: unverified final representation"
            )
        entity_handles = [str(value) for value in delivery.get("entity_handles") or []]
        support_handles = [
            str(value) for value in delivery.get("support_entity_handles") or []
        ]
        referenced_handles = [
            str(value) for value in delivery.get("referenced_entity_handles") or []
        ]
        if not entity_handles or main_handles.intersection(entity_handles):
            raise RuntimeError(
                f"serialized text delivery {source_id}: missing or duplicate main handles"
            )
        main_handles.update(entity_handles)
        entities = [
            _serialized_entity(doc, handle, source_id) for handle in entity_handles
        ]
        actual_types = {entity.dxftype() for entity in entities}
        if not actual_types.issubset(expected_types[representation]):
            raise RuntimeError(
                f"serialized text delivery {source_id}: expected {representation}, "
                f"found {sorted(actual_types)}"
            )
        if representation == "3d_text":
            for entity in entities:
                depth = float(getattr(entity.dxf, "thickness", 0.0) or 0.0)
                extrusion = tuple(
                    float(value)
                    for value in getattr(entity.dxf, "extrusion", (0.0, 0.0, 0.0))
                )
                depth_ok = math.isfinite(depth) and depth > 0.0
                extrusion_ok = len(extrusion) == 3 and all(
                    math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
                    for left, right in zip(
                        extrusion,
                        (0.0, 0.0, 1.0),
                        strict=True,
                    )
                )
                if not depth_ok or not extrusion_ok:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: 3D TEXT lost "
                        "its non-zero thickness or +Z extrusion"
                    )
        for handle in support_handles + referenced_handles:
            _serialized_entity(doc, handle, source_id)

        verified_attempts = [
            attempt
            for attempt in delivery.get("attempts") or []
            if attempt.get("outcome") == "verified"
        ]
        if len(verified_attempts) != 1:
            raise RuntimeError(
                f"serialized text delivery {source_id}: expected one verified attempt"
            )
        final_attempt = verified_attempts[0]
        if str(final_attempt.get("source_id") or "") != source_id:
            raise RuntimeError(
                f"serialized text delivery {source_id}: verified attempt source mismatch"
            )
        if str(final_attempt.get("attempted_representation") or "") != representation:
            raise RuntimeError(
                f"serialized text delivery {source_id}: verified attempt representation "
                "does not match the final representation"
            )
        if set(map(str, final_attempt.get("entity_handles") or [])) != set(
            entity_handles
        ) or set(map(str, final_attempt.get("support_entity_handles") or [])) != set(
            support_handles
        ) or set(map(str, final_attempt.get("referenced_entity_handles") or [])) != set(
            referenced_handles
        ):
            raise RuntimeError(
                f"serialized text delivery {source_id}: attempt handles disagree"
            )

        evidence = dict(final_attempt.get("evidence") or {})
        expected_source = (
            expected_text_sources.get(source_id)
            if expected_text_sources is not None
            else None
        )
        expected_page_visual = (
            expected_page_visual_sources.get(source_id)
            if expected_page_visual_sources is not None
            else None
        )
        if (
            expected_text_sources is not None
            and expected_source is None
            and expected_page_visual is None
        ):
            raise RuntimeError(
                f"serialized text delivery {source_id}: source identity is unbound"
            )
        if expected_page_visual is not None:
            if representation != "raster" or expected_source_pdf_path is None:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: page visual terminal is not raster-bound"
                )
            _verify_page_visual_raster_delivery(
                doc,
                delivery,
                final_attempt,
                expected_page_visual,
                expected_source_pdf_path=expected_source_pdf_path,
                expected_source_pdf_sha256=expected_source_pdf_sha256,
            )
            continue
        physical_proof = evidence.get("physical_glyph_ink_proof")
        physical_proof_valid: Optional[bool] = None
        if physical_proof is not None:
            physical_proof_valid = _validate_physical_glyph_ink_proof(
                physical_proof,
                expected_text_item=(
                    expected_source[0] if expected_source is not None else None
                ),
                expected_config=(
                    expected_source[1] if expected_source is not None else None
                ),
            )
            if (
                not physical_proof_valid
                or evidence.get("physical_glyph_ink_proof_valid") is not True
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: physical glyph proof "
                    "is not bound to the selected source"
                )

        if representation in {"text", "labels", "3d_text"}:
            if len(entities) != 1 or entities[0].dxftype() not in {"TEXT", "MTEXT"}:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: native text entity mismatch"
                )
            native = entities[0]
            evidence = dict(final_attempt.get("evidence") or {})
            actual_content = str(
                native.dxf.text
                if native.dxftype() == "TEXT"
                else native.plain_text()
            )
            expected_content = str(evidence.get("delivered_content") or "")
            expected_insert = tuple(
                float(value) for value in evidence.get("expected_insert") or []
            )
            actual_insert = tuple(
                float(value) for value in tuple(native.dxf.insert)[:2]
            )
            expected_height = float(evidence.get("expected_height") or 0.0)
            actual_height = float(
                native.dxf.height
                if native.dxftype() == "TEXT"
                else native.dxf.char_height
            )
            expected_rotation = float(evidence.get("expected_rotation") or 0.0)
            actual_rotation = float(native.dxf.rotation or 0.0)
            scalar_values_ok = bool(
                len(expected_insert) == 2
                and expected_height > 0.0
                and actual_content == expected_content
                and all(
                    math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                    for left, right in zip(
                        actual_insert,
                        expected_insert,
                        strict=True,
                    )
                )
                and math.isclose(
                    actual_height,
                    expected_height,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    actual_rotation,
                    expected_rotation,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            )
            if not scalar_values_ok:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: content or transform changed"
                )

            style = doc.styles.get(str(native.dxf.style or ""))
            parent_font = str(evidence.get("parent_native_font_candidate") or "")
            if parent_font:
                if str(style.dxf.font or "").strip().lower() != parent_font.lower():
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: parent font binding changed"
                    )

            if str(evidence.get("target_app") or "").strip().lower() == "librecad":
                parent_lff_proof = evidence.get("parent_native_lff_ink_proof")
                actual_style_font = str(style.dxf.font or "")
                parent_lff_valid = _validate_parent_lff_ink_proof(
                    parent_lff_proof,
                    expected_text=actual_content,
                    expected_style_font=actual_style_font,
                )
                if (
                    not parent_lff_valid
                    or evidence.get("parent_native_lff_ink_proof_valid") is not True
                    or evidence.get("source_zero_ink_physically_proven") is not True
                    or evidence.get("parent_delivered_lff_zero_ink_proven") is not True
                    or evidence.get("source_and_parent_zero_ink_match_verified") is not True
                    or parent_lff_proof.get("status") != "empty"
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: native LibreCAD "
                        "TEXT lacks exact source-and-delivered zero-ink proof"
                    )

            if evidence.get("fit_alignment_verified"):
                target_width = float(evidence.get("expected_advance_width") or 0.0)
                if native.dxftype() != "TEXT" or int(native.dxf.halign or 0) != 5:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: FIT alignment changed"
                    )
                align_point = tuple(
                    float(value) for value in tuple(native.dxf.align_point)[:2]
                )
                angle = math.radians(expected_rotation)
                expected_endpoint = (
                    expected_insert[0] + target_width * math.cos(angle),
                    expected_insert[1] + target_width * math.sin(angle),
                )
                if target_width <= 0.0 or not all(
                    math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                    for left, right in zip(
                        align_point,
                        expected_endpoint,
                        strict=True,
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: FIT width changed"
                    )

        outline_delivery_entities: List[Any] = []
        if representation == "glyphs":
            if len(entities) != 1:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: glyph outline parent mismatch"
                )
            support_set = set(support_handles)
            for insert in entities:
                try:
                    block = doc.blocks.get(str(insert.dxf.name))
                except Exception as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph block missing"
                    ) from exc
                exact_support = [
                    str(value.dxf.handle or "")
                    for value in (
                        *(() if doc.dxfversion == "AC1009" else (block.block_record,)),
                        block.block,
                        block.endblk,
                        *list(block),
                    )
                    if str(value.dxf.handle or "")
                ]
                if set(exact_support) != support_set or exact_support != support_handles:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph support mismatch"
                    )
                try:
                    exact_referenced = _outline_reference_handles(
                        doc,
                        [insert, *list(block)],
                    )
                except (TypeError, ValueError, AttributeError) as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph reference "
                        "dependency closure is invalid"
                    ) from exc
                if exact_referenced != referenced_handles:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph referenced handles "
                        "do not match the physical layer dependency closure"
                    )
                evidence = dict(final_attempt.get("evidence") or {})
                expected_block_name = str(evidence.get("block_name") or "")
                expected_source_digest = str(
                    evidence.get("source_identity_sha256") or ""
                )
                owned_block_names = list(final_attempt.get("owned_block_names") or [])
                if (
                    evidence.get("source_identity_physical_verified") is not True
                    or expected_source_digest != _source_identity_sha256(source_id)
                    or not _glyph_block_name_binds_source(
                        expected_block_name,
                        source_id,
                    )
                    or owned_block_names != [expected_block_name]
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: physical block source "
                        "identity changed"
                    )
                actual_reference_handles = _block_reference_handles(
                    doc,
                    expected_block_name,
                )
                recorded_reference_handles = list(
                    evidence.get("actual_block_reference_handles") or []
                )
                if (
                    evidence.get("expected_block_reference_count") != 1
                    or evidence.get("block_reference_ownership_verified") is not True
                    or recorded_reference_handles != [str(insert.dxf.handle or "")]
                    or actual_reference_handles != [str(insert.dxf.handle or "")]
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: duplicate or unowned "
                        "glyph block reference"
                    )
                expected_layer_name = str(evidence.get("expected_block_layer") or "")
                expected_layer_handle = str(
                    evidence.get("expected_block_layer_handle") or ""
                )
                if (
                    not expected_layer_name
                    or not expected_layer_handle
                    or expected_layer_handle not in referenced_handles
                    or evidence.get("expected_block_layer_on") is not True
                    or evidence.get("expected_block_layer_frozen") is not False
                    or evidence.get("block_insert_layer_verified") is not True
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph layer evidence "
                        "incomplete"
                    )
                try:
                    layer_record = doc.layers.get(expected_layer_name)
                except Exception as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: expected glyph layer missing"
                    ) from exc
                if (
                    str(insert.dxf.layer or "") != expected_layer_name
                    or str(layer_record.dxf.handle or "") != expected_layer_handle
                    or not layer_record.is_on()
                    or layer_record.is_frozen()
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph parent layer "
                        "identity or visual state changed"
                    )
                expected_layer_transparency = evidence.get(
                    "expected_block_layer_transparency"
                )
                actual_layer_transparency = layer_record.transparency
                if (
                    not _strict_finite_number(expected_layer_transparency)
                    or not _strict_finite_number(actual_layer_transparency)
                    or not math.isclose(
                        float(actual_layer_transparency),
                        float(expected_layer_transparency),
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    or not math.isclose(
                        float(expected_layer_transparency),
                        0.0,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph parent layer "
                        "transparent visual state changed"
                    )
                if (
                    evidence.get("expected_block_in_modelspace") is not True
                    or evidence.get("block_insert_modelspace_verified") is not True
                    or str(insert.dxf.owner or "") != str(doc.modelspace().layout_key)
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph parent is not "
                        "owned by modelspace"
                    )
                raw_expected_invisible = evidence.get("expected_block_invisible")
                raw_actual_invisible = insert.dxf.get("invisible", 0)
                if (
                    evidence.get("block_insert_invisible_state_verified") is not True
                    or isinstance(raw_expected_invisible, bool)
                    or not isinstance(raw_expected_invisible, int)
                    or raw_expected_invisible != 0
                    or isinstance(raw_actual_invisible, bool)
                    or not isinstance(raw_actual_invisible, int)
                    or raw_actual_invisible != raw_expected_invisible
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph parent visible "
                        "state changed"
                    )
                expected_transparency = evidence.get("expected_block_transparency")
                actual_transparency = insert.transparency
                if (
                    evidence.get("block_insert_transparency_verified") is not True
                    or not _strict_finite_number(expected_transparency)
                    or not _strict_finite_number(actual_transparency)
                    or not math.isclose(
                        float(actual_transparency),
                        float(expected_transparency),
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph parent transparent "
                        "visual state changed"
                    )
                visible_attributes = [
                    attribute
                    for attribute in insert.attribs
                    if _attached_attribute_is_visible(doc, attribute)
                ]
                if (
                    evidence.get("expected_visible_attached_attribute_count") != 0
                    or evidence.get("block_insert_attached_content_verified") is not True
                    or visible_attributes
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: unexpected visible "
                        "attached attribute content"
                    )
                raw_expected_insert = _strict_finite_vector(
                    evidence.get("expected_block_insert") or (),
                    length=3,
                )
                raw_actual_insert = _strict_finite_vector(
                    insert.dxf.insert,
                    length=3,
                )
                if (
                    not expected_block_name
                    or str(insert.dxf.name) != expected_block_name
                    or raw_expected_insert is None
                    or raw_actual_insert is None
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph outline transform changed"
                    )
                expected_insert = tuple(float(value) for value in raw_expected_insert)
                actual_insert = tuple(float(value) for value in raw_actual_insert)
                if not all(
                    math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
                    for left, right in zip(
                        actual_insert,
                        expected_insert,
                        strict=True,
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph outline transform changed"
                    )
                expected_aci = evidence.get("block_insert_aci")
                actual_aci = insert.dxf.get("color", 256)
                expected_true_color = evidence.get("block_insert_true_color")
                actual_true_color = (
                    int(insert.dxf.true_color)
                    if insert.dxf.hasattr("true_color")
                    else None
                )
                if (
                    evidence.get("block_insert_color_verified") is not True
                    or isinstance(expected_aci, bool)
                    or not isinstance(expected_aci, int)
                    or isinstance(actual_aci, bool)
                    or not isinstance(actual_aci, int)
                    or actual_aci != expected_aci
                    or (
                        expected_true_color is not None
                        and (
                            isinstance(expected_true_color, bool)
                            or not isinstance(expected_true_color, int)
                        )
                    )
                    or actual_true_color != expected_true_color
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph outline color changed"
                    )
                expected_transform_values = [
                    evidence.get("expected_block_rotation"),
                    evidence.get("expected_block_xscale"),
                    evidence.get("expected_block_yscale"),
                    evidence.get("expected_block_zscale"),
                    evidence.get("expected_block_row_spacing"),
                    evidence.get("expected_block_column_spacing"),
                ]
                expected_count_values = [
                    evidence.get("expected_block_row_count"),
                    evidence.get("expected_block_column_count"),
                ]
                expected_extrusion = evidence.get("expected_block_extrusion")
                expected_base_point = evidence.get("expected_block_base_point")
                if (
                    evidence.get("block_insert_transform_verified") is not True
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        for value in expected_transform_values
                    )
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 1
                        for value in expected_count_values
                    )
                    or not isinstance(expected_extrusion, (list, tuple))
                    or len(expected_extrusion) != 3
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        for value in expected_extrusion
                    )
                    or not isinstance(expected_base_point, (list, tuple))
                    or len(expected_base_point) != 3
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        for value in expected_base_point
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph transform "
                        "evidence incomplete"
                    )
                (
                    expected_rotation,
                    expected_xscale,
                    expected_yscale,
                    expected_zscale,
                    expected_row_spacing,
                    expected_column_spacing,
                ) = map(
                    float,
                    expected_transform_values,
                )
                expected_row_count, expected_column_count = map(
                    int,
                    expected_count_values,
                )
                raw_actual_transform_values = (
                    insert.dxf.get("rotation", 0.0),
                    insert.dxf.get("xscale", 1.0),
                    insert.dxf.get("yscale", 1.0),
                    insert.dxf.get("zscale", 1.0),
                    insert.dxf.get("row_spacing", 0.0),
                    insert.dxf.get("column_spacing", 0.0),
                )
                raw_actual_row_count = insert.dxf.get("row_count", 1)
                raw_actual_column_count = insert.dxf.get("column_count", 1)
                raw_actual_extrusion = _strict_finite_vector(
                    insert.dxf.get("extrusion", (0.0, 0.0, 1.0)),
                    length=3,
                )
                raw_actual_base_point = _strict_finite_vector(
                    block.block.dxf.base_point,
                    length=3,
                )
                if (
                    not all(
                        _strict_finite_number(value)
                        for value in raw_actual_transform_values
                    )
                    or isinstance(raw_actual_row_count, bool)
                    or not isinstance(raw_actual_row_count, int)
                    or raw_actual_row_count < 1
                    or isinstance(raw_actual_column_count, bool)
                    or not isinstance(raw_actual_column_count, int)
                    or raw_actual_column_count < 1
                    or raw_actual_extrusion is None
                    or raw_actual_base_point is None
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph outline "
                        "transform changed"
                    )
                (
                    actual_rotation,
                    actual_xscale,
                    actual_yscale,
                    actual_zscale,
                    actual_row_spacing,
                    actual_column_spacing,
                ) = map(float, raw_actual_transform_values)
                actual_row_count = raw_actual_row_count
                actual_column_count = raw_actual_column_count
                actual_extrusion = tuple(
                    float(value) for value in raw_actual_extrusion
                )
                actual_base_point = tuple(
                    float(value) for value in raw_actual_base_point
                )
                if (
                    actual_row_count != expected_row_count
                    or actual_column_count != expected_column_count
                    or (
                        expected_row_count > 1
                        and not math.isclose(
                            actual_row_spacing,
                            expected_row_spacing,
                            rel_tol=0.0,
                            abs_tol=1e-12,
                        )
                    )
                    or (
                        expected_column_count > 1
                        and not math.isclose(
                            actual_column_spacing,
                            expected_column_spacing,
                            rel_tol=0.0,
                            abs_tol=1e-12,
                        )
                    )
                    or not all(
                        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
                        for left, right in zip(
                            (
                                actual_rotation,
                                actual_xscale,
                                actual_yscale,
                                actual_zscale,
                                *actual_extrusion,
                                *actual_base_point,
                            ),
                            (
                                expected_rotation,
                                expected_xscale,
                                expected_yscale,
                                expected_zscale,
                                *(float(value) for value in expected_extrusion),
                                *(float(value) for value in expected_base_point),
                            ),
                            strict=True,
                        )
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph outline "
                        "transform changed"
                    )
                outline_delivery_entities = list(block)

        if representation == "geometry":
            if support_handles:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: geometry has unexpected support"
                )
            evidence = dict(final_attempt.get("evidence") or {})
            if (
                evidence.get("expected_geometry_in_modelspace") is not True
                or evidence.get("geometry_modelspace_ownership_verified") is not True
                or any(
                    str(entity.dxf.owner or "") != str(doc.modelspace().layout_key)
                    for entity in entities
                )
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: geometry modelspace "
                    "ownership changed"
                )
            try:
                exact_referenced = _outline_reference_handles(doc, entities)
            except (TypeError, ValueError, AttributeError) as exc:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: geometry reference "
                    "dependency closure is invalid"
                ) from exc
            if exact_referenced != referenced_handles:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: geometry referenced handles "
                    "do not match the physical layer dependency closure"
                )
            outline_delivery_entities = entities

        if representation in {"glyphs", "geometry"}:
            evidence = dict(final_attempt.get("evidence") or {})
            if not verify_serialized_outline_geometry(
                outline_delivery_entities,
                evidence,
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: source-bound outline "
                    "geometry, contour topology, or solid fill changed"
                )

        if representation == "raster":
            evidence = dict(final_attempt.get("evidence") or {})
            source_match = re.fullmatch(r"text_span:([0-9]+):([0-9]+)", source_id)
            evidence_page = evidence.get("source_page_number")
            evidence_bbox = _strict_finite_vector(
                evidence.get("source_bbox_pdf"),
                length=4,
            )
            proof_bbox = _strict_finite_vector(
                physical_proof.get("source_bbox_pdf")
                if isinstance(physical_proof, dict)
                else None,
                length=4,
            )
            selected_item = expected_source[0] if expected_source is not None else None
            selected_page = (
                getattr(selected_item, "page_number", None)
                if selected_item is not None
                else int(source_match.group(1)) if source_match is not None else None
            )
            selected_bbox = (
                _strict_finite_vector(
                    getattr(selected_item, "source_bbox_pdf", None),
                    length=4,
                )
                if selected_item is not None
                else proof_bbox
            )
            if (
                source_match is None
                or isinstance(evidence_page, bool)
                or not isinstance(evidence_page, int)
                or isinstance(selected_page, bool)
                or not isinstance(selected_page, int)
                or evidence.get("source_id") != source_id
                or evidence_page != selected_page
                or int(source_match.group(1)) != selected_page
                or physical_proof_valid is not True
                or not isinstance(physical_proof, dict)
                or physical_proof.get("source_id") != source_id
                or physical_proof.get("source_page_number") != selected_page
                or evidence_bbox is None
                or proof_bbox is None
                or selected_bbox is None
                or tuple(evidence_bbox) != tuple(proof_bbox)
                or tuple(evidence_bbox) != tuple(selected_bbox)
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: source-derived raster "
                    "mismatch (selected source page or item binding changed)"
                )
            source_pixels_sampled = evidence.get("source_pixels_sampled") is True
            if source_pixels_sampled:
                if (
                    evidence.get("visible_ink_verified") is not True
                    or evidence.get("zero_ink_verified") is not False
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: sampled source clip "
                        "contains no verified visible ink"
                    )
                source_clip = list(evidence.get("source_clip_pdf") or [])
                if len(source_clip) != 4 or not all(
                    isinstance(value, (int, float)) and math.isfinite(float(value))
                    for value in source_clip
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: sampled source clip "
                        "evidence is incomplete"
                    )
            else:
                if (
                    final_attempt.get("strategy") != "sealed_physical_zero_ink_png"
                    or evidence.get("source_zero_ink_physically_proven") is not True
                    or evidence.get("zero_ink_verified") is not True
                    or evidence.get("visible_ink_verified") is not False
                    or physical_proof_valid is not True
                    or physical_proof.get("status") != "empty"
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: transparent raster "
                        "lacks sealed physical empty-glyph proof"
                    )
            asset_path = Path(str(evidence.get("asset_path") or ""))
            expected_sha = str(evidence.get("asset_sha256") or "")
            if not asset_path.is_file() or not expected_sha:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster asset missing"
                )
            if hashlib.sha256(asset_path.read_bytes()).hexdigest() != expected_sha:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster asset hash mismatch"
                )
            if source_pixels_sampled:
                evidence_source = Path(
                    str(evidence.get("source_pdf_path") or "")
                ).expanduser().resolve()
                bound_source = (
                    Path(expected_source_pdf_path).expanduser().resolve()
                    if expected_source_pdf_path is not None
                    else evidence_source
                )
                if evidence_source != bound_source or not bound_source.is_file():
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: source-derived raster "
                        "mismatch (source PDF binding changed)"
                    )
                proof_source_path = Path(
                    str(physical_proof.get("source_pdf_path") or "")
                ).expanduser().resolve()
                if (
                    proof_source_path != evidence_source
                    or str(physical_proof.get("source_pdf_sha256") or "")
                    != str(evidence.get("source_pdf_sha256") or "")
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: source-derived raster "
                        "mismatch (physical proof PDF binding changed)"
                    )
                source_key = str(bound_source)
                actual_source_sha = source_digest_cache.get(source_key)
                if actual_source_sha is None:
                    actual_source_sha = _file_sha256(bound_source)
                    source_digest_cache[source_key] = actual_source_sha
                reported_source_sha = str(evidence.get("source_pdf_sha256") or "")
                if (
                    not reported_source_sha
                    or reported_source_sha != actual_source_sha
                    or (
                        expected_source_pdf_sha256
                        and actual_source_sha != expected_source_pdf_sha256
                    )
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: source-derived raster "
                        "mismatch (source PDF digest changed)"
                    )
                try:
                    page_number = int(evidence.get("source_page_number"))
                    raster_dpi = int(evidence.get("raster_dpi"))
                    if (
                        isinstance(evidence.get("source_page_number"), bool)
                        or isinstance(evidence.get("raster_dpi"), bool)
                        or page_number <= 0
                        or raster_dpi < 72
                    ):
                        raise ValueError("invalid page or DPI")
                    fresh, fresh_clip, fresh_rotation = _render_source_text_clip(
                        bound_source,
                        page_number=page_number,
                        source_bbox_pdf=evidence.get("source_bbox_pdf"),
                        raster_dpi=raster_dpi,
                    )
                    staged = fitz.Pixmap(str(asset_path))
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: source-derived raster "
                        f"mismatch ({exc})"
                    ) from exc
                reported_clip = [
                    float(value) for value in evidence.get("source_clip_pdf") or []
                ]
                reported_rotation = [
                    float(value)
                    for value in evidence.get("source_to_display_rotation") or []
                ]
                geometry_matches = bool(
                    len(reported_clip) == len(fresh_clip) == 4
                    and len(reported_rotation) == len(fresh_rotation)
                    and all(
                        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                        for left, right in zip(
                            reported_clip,
                            fresh_clip,
                            strict=True,
                        )
                    )
                    and all(
                        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                        for left, right in zip(
                            reported_rotation,
                            fresh_rotation,
                            strict=True,
                        )
                    )
                )
                pixels_match = bool(
                    staged.width == fresh.width
                    and staged.height == fresh.height
                    and int(staged.n) == int(fresh.n)
                    and bool(staged.alpha) is bool(fresh.alpha)
                    and bytes(staged.samples) == bytes(fresh.samples)
                    and evidence.get("source_render_samples_sha256")
                    == hashlib.sha256(bytes(fresh.samples)).hexdigest()
                    and _pixmap_contains_ink(fresh)
                    and _pixmap_contains_ink(staged)
                )
                if not geometry_matches or not pixels_match:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: source-derived raster mismatch"
                    )
            if len(entities) != 1:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster must own one IMAGE"
                )
            raster = entities[0]
            target_bbox = [
                float(value) for value in evidence.get("target_bbox_model") or []
            ]
            pixel_size = [
                int(value) for value in evidence.get("pixel_size") or []
            ]
            if len(target_bbox) != 4 or len(pixel_size) != 2:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster evidence incomplete"
                )
            expected_insert = (target_bbox[0], target_bbox[1])
            expected_size = (
                target_bbox[2] - target_bbox[0],
                target_bbox[3] - target_bbox[1],
            )
            actual_insert = tuple(float(value) for value in tuple(raster.dxf.insert)[:2])
            actual_size = (
                math.hypot(raster.dxf.u_pixel.x, raster.dxf.u_pixel.y)
                * float(raster.dxf.image_size.x),
                math.hypot(raster.dxf.v_pixel.x, raster.dxf.v_pixel.y)
                * float(raster.dxf.image_size.y),
            )
            placement_ok = all(
                math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                for left, right in zip(
                    actual_insert + actual_size,
                    expected_insert + expected_size,
                    strict=True,
                )
            )
            if not placement_ok:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster placement changed"
                )
            image_def_handle = str(raster.dxf.image_def_handle or "")
            reactor_handle = str(raster.dxf.image_def_reactor_handle or "")
            exact_support = {
                handle for handle in (image_def_handle, reactor_handle) if handle
            }
            if exact_support != set(support_handles):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster support mismatch"
                )
            image_def = _serialized_entity(doc, image_def_handle, source_id)
            actual_asset_path = Path(
                str(image_def.dxf.filename or "")
            ).expanduser().resolve()
            actual_pixels = (
                int(round(float(image_def.dxf.image_size.x))),
                int(round(float(image_def.dxf.image_size.y))),
            )
            if (
                image_def.dxftype() != "IMAGEDEF"
                or actual_asset_path != asset_path.expanduser().resolve()
                or actual_pixels != tuple(pixel_size)
                or not (int(raster.dxf.flags or 0) & 8)
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster asset binding changed"
                )
        else:
            evidence = dict(final_attempt.get("evidence") or {})
            if evidence.get("font_asset_id"):
                font_path = Path(str(evidence.get("resolved_font_filename") or ""))
                font_sha = str(evidence.get("font_asset_sha256") or "")
                if not font_path.is_file() or not font_sha:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: embedded font asset missing"
                    )
                if hashlib.sha256(font_path.read_bytes()).hexdigest() != font_sha:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: embedded font hash mismatch"
                    )


@dataclass
class _PendingRasterAsset:
    path: Path
    content: bytes


@dataclass(frozen=True)
class _StagedImageAsset:
    source_path: Path
    path: Path
    sha256: str
    size_px: Tuple[int, int]


@dataclass(frozen=True)
class _SerializedImageExpectation:
    image_handle: str
    image_def_handle: str
    asset_path: Path
    asset_sha256: str
    insert: Tuple[float, float, float]
    size_in_units: Tuple[float, float]
    size_in_pixel: Tuple[int, int]
    u_vector_in_units: Tuple[float, float, float]
    v_vector_in_units: Tuple[float, float, float]


@dataclass
class _AssetTransaction:
    files: List[Path] = field(default_factory=list)
    directories: List[Path] = field(default_factory=list)
    committed: bool = False

    def register_file(self, path: Path) -> None:
        if path not in self.files:
            self.files.append(path)

    def register_directory(self, path: Path) -> None:
        if path not in self.directories:
            self.directories.append(path)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        if self.committed:
            return
        for path in reversed(self.files):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        for path in reversed(self.directories):
            try:
                path.rmdir()
            except OSError:
                pass


def _stage_embedded_font_assets(
    extraction: DocumentExtraction,
    asset_root: Path,
    transaction: _AssetTransaction,
) -> Dict[str, str]:
    """Stage exact source font programs in this output's unique asset set."""

    from pdfcadcore.atomic_io import atomic_write_bytes

    assets: Dict[str, Any] = {}
    for page in extraction.pages:
        for item in page.page_data.text_items:
            asset = getattr(item, "font_asset", None)
            if asset is None:
                continue
            previous = assets.get(str(asset.asset_id))
            if previous is not None and bytes(previous.usable_bytes) != bytes(
                asset.usable_bytes
            ):
                raise RuntimeError(
                    f"embedded font asset identity collision: {asset.asset_id}"
                )
            assets[str(asset.asset_id)] = asset

    if not assets:
        return {}
    font_root = asset_root / "fonts"
    font_root.mkdir(parents=True, exist_ok=True)
    transaction.register_directory(asset_root.parent)
    transaction.register_directory(asset_root)
    transaction.register_directory(font_root)
    paths: Dict[str, str] = {}
    for asset_id, asset in sorted(assets.items()):
        content = bytes(asset.usable_bytes)
        digest = hashlib.sha256(content).hexdigest()
        if digest != str(asset.usable_sha256):
            raise RuntimeError(f"embedded font source digest mismatch: {asset_id}")
        extension = str(asset.usable_format or "otf").lower().lstrip(".")
        if extension not in {"otf", "ttf"}:
            raise RuntimeError(f"unsupported staged font format: {extension}")
        path = font_root / f"{digest}.{extension}"
        atomic_write_bytes(path, content)
        transaction.register_file(path)
        paths[asset_id] = str(path)
    return paths


def _normalized_image_source_path(raw_path: str) -> str:
    return str(Path(raw_path).expanduser().resolve())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_image_assets(
    extraction: DocumentExtraction,
    asset_root: Path,
    transaction: _AssetTransaction,
) -> Dict[str, _StagedImageAsset]:
    """Copy every extracted image into this accepted DXF's owned asset set."""

    from pdfcadcore.atomic_io import atomic_write_bytes

    source_paths = sorted(
        {
            _normalized_image_source_path(str(placement.path))
            for page in extraction.pages
            for placement in page.images
        }
    )
    if not source_paths:
        return {}

    image_root = asset_root / "images"
    image_root.mkdir(parents=True, exist_ok=True)
    transaction.register_directory(asset_root.parent)
    transaction.register_directory(asset_root)
    transaction.register_directory(image_root)

    staged_by_digest: Dict[str, _StagedImageAsset] = {}
    staged_by_source: Dict[str, _StagedImageAsset] = {}
    for source_key in source_paths:
        source_path = Path(source_key)
        if not source_path.is_file():
            raise RuntimeError(f"image asset is missing: {source_path}")
        try:
            content = source_path.read_bytes()
            size_px = _image_size_pixels(str(source_path))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"image asset is unreadable: {source_path}: {exc}") from exc
        if not content:
            raise RuntimeError(f"image asset is empty: {source_path}")

        digest = hashlib.sha256(content).hexdigest()
        staged = staged_by_digest.get(digest)
        if staged is None:
            if content.startswith(b"\x89PNG\r\n\x1a\n"):
                suffix = ".png"
            elif content.startswith(b"\xff\xd8\xff"):
                suffix = ".jpg"
            else:
                suffix = source_path.suffix.lower()
                if suffix not in {".bmp", ".gif", ".tif", ".tiff"}:
                    suffix = ".img"
            staged_path = image_root / f"{digest}{suffix}"
            atomic_write_bytes(staged_path, content)
            transaction.register_file(staged_path)
            if hashlib.sha256(staged_path.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"staged image asset hash mismatch: {staged_path}")
            if _image_size_pixels(str(staged_path)) != size_px:
                raise RuntimeError(f"staged image asset dimensions changed: {staged_path}")
            staged = _StagedImageAsset(
                source_path=source_path,
                path=staged_path,
                sha256=digest,
                size_px=size_px,
            )
            staged_by_digest[digest] = staged
        staged_by_source[source_key] = staged

    return staged_by_source


def _verify_serialized_image_assets(
    doc: Any,
    expectations: List[_SerializedImageExpectation],
) -> None:
    """Reconcile every normal image placement and owned asset after DXF reopen."""

    if expectations:
        raster_variables = list(doc.objects.query("RASTERVARIABLES"))
        if len(raster_variables) != 1:
            raise RuntimeError("serialized image delivery has invalid raster variables")
        raster_settings = raster_variables[0]
        if (
            int(raster_settings.dxf.frame) != 0
            or int(raster_settings.dxf.quality) != 1
            or int(raster_settings.dxf.units) != 1
        ):
            raise RuntimeError(
                "serialized image delivery changed frame, quality, or millimeter units"
            )

    for expected in expectations:
        image = doc.entitydb.get(expected.image_handle)
        if image is None or not getattr(image, "is_alive", True):
            raise RuntimeError(
                f"serialized image delivery missing IMAGE handle {expected.image_handle}"
            )
        if image.dxftype() != "IMAGE":
            raise RuntimeError(
                f"serialized image delivery handle {expected.image_handle} is not IMAGE"
            )
        if not (int(image.dxf.flags or 0) & 8):
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} disabled transparency"
            )
        if str(image.dxf.image_def_handle or "") != expected.image_def_handle:
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} changed IMAGEDEF ownership"
            )

        image_def = doc.entitydb.get(expected.image_def_handle)
        if image_def is None or not getattr(image_def, "is_alive", True):
            raise RuntimeError(
                f"serialized image delivery missing IMAGEDEF handle {expected.image_def_handle}"
            )
        if image_def.dxftype() != "IMAGEDEF":
            raise RuntimeError(
                f"serialized image delivery handle {expected.image_def_handle} is not IMAGEDEF"
            )

        asset_path = Path(str(image_def.dxf.filename or "")).expanduser().resolve()
        if asset_path != expected.asset_path.resolve() or not asset_path.is_file():
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} references a missing or foreign asset"
            )
        if hashlib.sha256(asset_path.read_bytes()).hexdigest() != expected.asset_sha256:
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} asset hash mismatch"
            )

        actual_insert = tuple(float(value) for value in image.dxf.insert)
        actual_u_vector = tuple(
            float(value) * float(image.dxf.image_size.x)
            for value in image.dxf.u_pixel
        )
        actual_v_vector = tuple(
            float(value) * float(image.dxf.image_size.y)
            for value in image.dxf.v_pixel
        )
        actual_width = math.hypot(*actual_u_vector[:2])
        actual_height = math.hypot(*actual_v_vector[:2])
        actual_pixels = (
            int(round(float(image_def.dxf.image_size.x))),
            int(round(float(image_def.dxf.image_size.y))),
        )
        if not all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(actual_insert, expected.insert, strict=True)
        ):
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} insert changed"
            )
        if not all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(
                actual_u_vector,
                expected.u_vector_in_units,
                strict=True,
            )
        ):
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} U vector orientation or scale changed"
            )
        if not all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(
                actual_v_vector,
                expected.v_vector_in_units,
                strict=True,
            )
        ):
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} V vector orientation or scale changed"
            )
        if not math.isclose(
            actual_width,
            expected.size_in_units[0],
            rel_tol=0.0,
            abs_tol=1e-9,
        ) or not math.isclose(
            actual_height,
            expected.size_in_units[1],
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} size changed"
            )
        if actual_pixels != expected.size_in_pixel:
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} pixel dimensions changed"
            )


def _pixmap_contains_ink(pixmap: Any) -> bool:
    samples = bytes(pixmap.samples)
    channels = int(pixmap.n)
    if not samples or channels <= 0:
        return False
    if bool(pixmap.alpha):
        return any(value > 0 for value in samples[channels - 1 :: channels])
    color_channels = min(3, channels)
    for offset in range(0, len(samples), channels):
        if any(samples[offset + channel] < 250 for channel in range(color_channels)):
            return True
    return False


def _render_source_text_clip(
    source_pdf: Path,
    *,
    page_number: int,
    source_bbox_pdf: Any,
    raster_dpi: int,
) -> Tuple[Any, List[float], List[float]]:
    """Render one exact raw-PDF text bbox through the source page transform."""

    if isinstance(page_number, bool) or int(page_number) <= 0:
        raise ValueError("source page number is invalid")
    if isinstance(raster_dpi, bool) or int(raster_dpi) < 72:
        raise ValueError("terminal raster DPI is invalid")
    bbox = list(source_bbox_pdf or [])
    if len(bbox) != 4:
        raise ValueError("terminal raster source bbox is incomplete")
    sx0, sy0, sx1, sy1 = [float(value) for value in bbox]
    if not all(math.isfinite(value) for value in (sx0, sy0, sx1, sy1)):
        raise ValueError("terminal raster source bbox is non-finite")
    if math.isclose(sx0, sx1) or math.isclose(sy0, sy1):
        raise ValueError("terminal raster source bbox is empty")

    with fitz.open(str(source_pdf)) as source_doc:
        page = source_doc.load_page(int(page_number) - 1)
        rotation_matrix = _page_rotation_transform(
            page.rect,
            getattr(page, "rotation_matrix", None),
        )
        source_corners = [
            _transform_pdf_point(x, y, rotation_matrix)
            for x, y in (
                (sx0, sy0),
                (sx1, sy0),
                (sx1, sy1),
                (sx0, sy1),
            )
        ]
        requested_clip = fitz.Rect(
            min(point[0] for point in source_corners),
            min(point[1] for point in source_corners),
            max(point[0] for point in source_corners),
            max(point[1] for point in source_corners),
        )
        clip = requested_clip & page.rect
        if clip.is_empty or clip.is_infinite:
            raise ValueError("terminal raster clip is outside the source page")
        containment_tolerance = max(
            1e-6,
            max(float(page.rect.width), float(page.rect.height), 1.0) * 1e-7,
        )
        if any(
            not math.isclose(left, right, rel_tol=0.0, abs_tol=containment_tolerance)
            for left, right in zip(
                (
                    requested_clip.x0,
                    requested_clip.y0,
                    requested_clip.x1,
                    requested_clip.y1,
                ),
                (clip.x0, clip.y0, clip.x1, clip.y1),
                strict=True,
            )
        ):
            raise ValueError(
                "terminal raster source bbox is not fully contained by the source page"
            )
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(int(raster_dpi) / 72.0, int(raster_dpi) / 72.0),
            clip=clip,
            alpha=True,
        )
    return (
        pixmap,
        [float(clip.x0), float(clip.y0), float(clip.x1), float(clip.y1)],
        [float(value) for value in rotation_matrix],
    )


def _entitydb_handles(doc: Any) -> set[str]:
    return {str(handle) for handle in doc.entitydb.keys() if handle}


def _entity_is_live(entity: Any) -> bool:
    return entity is not None and bool(getattr(entity, "is_alive", True))


def _dictionary_value_handle(value: Any) -> str:
    if isinstance(value, str):
        return value
    dxf = getattr(value, "dxf", None)
    return str(getattr(dxf, "handle", "") or "")


def _dictionary_bindings(doc: Any) -> Dict[Tuple[str, str], str]:
    bindings: Dict[Tuple[str, str], str] = {}
    for entity in list(doc.objects):
        if not _entity_is_live(entity) or entity.dxftype() != "DICTIONARY":
            continue
        dictionary_handle = str(entity.dxf.handle or "")
        for key, value in list(entity.items()):
            bindings[(dictionary_handle, str(key))] = _dictionary_value_handle(value)
    return bindings


def _dictionary_references_to_handles(doc: Any, handles: set[str]) -> List[str]:
    references: List[str] = []
    if not handles:
        return references
    for entity in list(doc.objects):
        if not _entity_is_live(entity) or entity.dxftype() != "DICTIONARY":
            continue
        dictionary_handle = str(entity.dxf.handle or "")
        for key, value in list(entity.items()):
            value_handle = _dictionary_value_handle(value)
            if value_handle in handles:
                references.append(f"{dictionary_handle}:{key}:{value_handle}")
    return references


def _cleanup_partial_image_attempt(
    doc: Any,
    msp: Any,
    created_handles: set[str],
    dictionary_bindings_before: Dict[Tuple[str, str], str],
) -> Tuple[List[str], bool]:
    """Delete only entities created after this item attempt began."""
    if not created_handles:
        return [], True

    # Remove ownership links first so destroying IMAGEDEF and document-level
    # raster support does not leave a live dictionary entry pointing at a dead
    # object.  Entries resolving to pre-attempt handles are never touched.
    for entity in list(doc.objects):
        if not _entity_is_live(entity) or entity.dxftype() != "DICTIONARY":
            continue
        for key, value in list(entity.items()):
            if _dictionary_value_handle(value) in created_handles:
                try:
                    entity.discard(key)
                except Exception:
                    pass

    # Layout IMAGE deletion also destroys its IMAGEDEF_REACTOR in ezdxf.
    for handle in sorted(created_handles):
        entity = doc.entitydb.get(handle)
        if not _entity_is_live(entity) or entity.dxftype() != "IMAGE":
            continue
        try:
            msp.delete_entity(entity)
        except Exception:
            pass

    object_priority = {
        "IMAGEDEF_REACTOR": 0,
        "IMAGEDEF": 1,
        "RASTERVARIABLES": 2,
        "DICTIONARY": 3,
    }
    remaining_objects = []
    for handle in created_handles:
        entity = doc.entitydb.get(handle)
        if not _entity_is_live(entity) or entity.dxftype() == "IMAGE":
            continue
        remaining_objects.append(entity)
    remaining_objects.sort(
        key=lambda entity: object_priority.get(entity.dxftype(), 4)
    )
    for entity in remaining_objects:
        if not _entity_is_live(entity):
            continue
        try:
            doc.objects.delete_entity(entity)
        except Exception:
            pass

    # A generated IMAGEDEF name can collide with an existing dictionary key.
    # Restore that exact pre-attempt binding after the new definition is gone.
    for (dictionary_handle, key), value_handle in dictionary_bindings_before.items():
        dictionary = doc.entitydb.get(dictionary_handle)
        value = doc.entitydb.get(value_handle)
        if not _entity_is_live(dictionary) or not _entity_is_live(value):
            continue
        current_value = dictionary.get(key)
        if _dictionary_value_handle(current_value) == value_handle:
            continue
        try:
            dictionary[key] = value
        except Exception:
            pass

    surviving_handles = {
        handle
        for handle in created_handles
        if _entity_is_live(doc.entitydb.get(handle))
    }
    dangling_references = _dictionary_references_to_handles(doc, created_handles)
    dictionaries_restored = _dictionary_bindings(doc) == dictionary_bindings_before
    removed_handles = sorted(created_handles - surviving_handles)
    return (
        removed_handles,
        not surviving_handles and not dangling_references and dictionaries_restored,
    )


def _attempt_terminal_text_raster(
    delivery: TextDeliveryResult,
    *,
    extraction: DocumentExtraction,
    page_number: int,
    source_text: Any,
    placed_text: Any,
    msp: Any,
    layer_name: str,
    asset_root: Path,
    raster_dpi: int,
    source_pdf_sha256: str,
    config: Optional[ImportConfig] = None,
) -> Tuple[TextDeliveryResult, Optional[_PendingRasterAsset]]:
    """Attempt a real item crop as requested or after proven structural failure."""
    attempts = list(delivery.attempts)
    for prior in attempts:
        prior.superseded = True
    proof_config = config or ImportConfig.auto()
    physical_ink_proof = _build_physical_glyph_ink_proof(
        source_text,
        proof_config,
    )
    physical_ink_proof_valid = _validate_physical_glyph_ink_proof(
        physical_ink_proof,
        expected_text_item=source_text,
        expected_config=proof_config,
    )
    source_zero_ink_proven = bool(
        physical_ink_proof_valid and physical_ink_proof.get("status") == "empty"
    )
    attempt = TextDeliveryAttempt(
        source_id=delivery.source_id,
        requested_representation=delivery.requested_representation,
        attempted_representation="raster",
        strategy=(
            "sealed_physical_zero_ink_png"
            if source_zero_ink_proven
            else "pymupdf_item_clip"
        ),
    )
    attempts.append(attempt)
    doc = msp.doc
    image = None
    image_def = None
    support_handles: List[str] = []
    entity_handles_before_creation: Optional[set[str]] = None
    dictionary_bindings_before_creation: Dict[Tuple[str, str], str] = {}
    try:
        if not delivery.source_id:
            raise ValueError("terminal raster has no stable source identity")
        source_bbox = getattr(source_text, "source_bbox_pdf", None)
        placed_bbox = getattr(placed_text, "bbox", None)
        if not source_bbox or len(source_bbox) < 4 or not placed_bbox or len(placed_bbox) < 4:
            raise ValueError("terminal raster requires an exact source item bbox")
        sx0, sy0, sx1, sy1 = [float(value) for value in source_bbox[:4]]
        px0, py0, px1, py1 = [float(value) for value in placed_bbox[:4]]
        if not all(
            math.isfinite(value)
            for value in (sx0, sy0, sx1, sy1, px0, py0, px1, py1)
        ):
            raise ValueError(
                "terminal raster bounds must contain only finite coordinates"
            )
        source_width = abs(sx1 - sx0)
        source_height = abs(sy1 - sy0)
        placed_width = abs(px1 - px0)
        placed_height = abs(py1 - py0)
        dimensions = (source_width, source_height, placed_width, placed_height)
        if not all(math.isfinite(value) and value > 0.0 for value in dimensions):
            raise ValueError("terminal raster source item bbox is empty")

        source_clip: Optional[List[float]] = None
        source_rotation: Optional[List[float]] = None
        source_pixels_sampled = False
        visible_ink_verified = False
        zero_ink_verified = False
        dpi = max(72, int(raster_dpi or 300))
        if source_zero_ink_proven:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1, 1), True)
            pixmap.clear_with(0)
            pixmap.set_alpha(bytes([0]))
            png = bytes(pixmap.tobytes("png"))
            zero_ink_verified = not _pixmap_contains_ink(pixmap)
            if not zero_ink_verified:
                raise ValueError("terminal raster zero-ink asset contains visible pixels")
        else:
            pixmap, source_clip, source_rotation = _render_source_text_clip(
                Path(extraction.pdf_path).expanduser().resolve(),
                page_number=int(page_number),
                source_bbox_pdf=(sx0, sy0, sx1, sy1),
                raster_dpi=dpi,
            )
            png = bytes(pixmap.tobytes("png"))
            source_pixels_sampled = True

            visible_ink_verified = _pixmap_contains_ink(pixmap)
            zero_ink_verified = not visible_ink_verified

        if pixmap.width <= 0 or pixmap.height <= 0:
            raise ValueError("terminal raster rendered zero pixels")
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("terminal raster output is not a PNG")

        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", delivery.source_id)
        asset_path = asset_root / f"{safe_id}.png"
        entity_handles_before_creation = _entitydb_handles(doc)
        dictionary_bindings_before_creation = _dictionary_bindings(doc)
        image_def = doc.add_image_def(
            filename=str(asset_path),
            size_in_pixel=(int(pixmap.width), int(pixmap.height)),
            name=f"BCS_TEXT_{safe_id}"[:255],
        )
        image = msp.add_image(
            image_def,
            insert=(min(px0, px1), min(py0, py1)),
            size_in_units=(placed_width, placed_height),
            dxfattribs={"layer": layer_name},
        )
        image.dxf.flags = int(image.dxf.flags or 0) | 8
        image_handle = str(image.dxf.handle or "")
        image_def_handle = str(image_def.dxf.handle or "")
        reactor_handle = str(image.dxf.image_def_reactor_handle or "")
        support_handles = [
            handle for handle in (image_def_handle, reactor_handle) if handle
        ]
        attempt.created_entity_handles = [image_handle] + support_handles
        attempt.entity_handles = [image_handle]
        attempt.support_entity_handles = support_handles

        actual_insert = tuple(image.dxf.insert)[:2]
        actual_width = math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y) * float(
            image.dxf.image_size.x
        )
        actual_height = math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y) * float(
            image.dxf.image_size.y
        )
        insert_ok = all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(
                actual_insert, (min(px0, px1), min(py0, py1)), strict=True
            )
        )
        size_ok = math.isclose(
            actual_width, placed_width, rel_tol=1e-8, abs_tol=1e-9
        ) and math.isclose(
            actual_height, placed_height, rel_tol=1e-8, abs_tol=1e-9
        )
        ink_contract_verified = (
            zero_ink_verified
            if source_zero_ink_proven
            else source_pixels_sampled and visible_ink_verified
        )
        attempt.type_verified = image.dxftype() == "IMAGE"
        attempt.visual_verified = insert_ok and size_ok and ink_contract_verified
        attempt.cleanup_verified = all(
            doc.entitydb.get(handle) is not None
            and getattr(doc.entitydb.get(handle), "is_alive", True)
            for handle in attempt.created_entity_handles
        )
        attempt.evidence = {
            "source_pdf_path": str(Path(extraction.pdf_path).expanduser().resolve()),
            "source_pdf_sha256": source_pdf_sha256,
            "source_page_number": int(page_number),
            "source_id": delivery.source_id,
            "asset_path": str(asset_path),
            "asset_sha256": hashlib.sha256(png).hexdigest(),
            "source_clip_pdf": source_clip,
            "source_bbox_pdf": [sx0, sy0, sx1, sy1],
            "source_to_display_rotation": source_rotation,
            "raster_dpi": dpi,
            "source_render_samples_sha256": (
                hashlib.sha256(bytes(pixmap.samples)).hexdigest()
                if source_pixels_sampled
                else ""
            ),
            "target_bbox_model": [
                min(px0, px1),
                min(py0, py1),
                max(px0, px1),
                max(py0, py1),
            ],
            "pixel_size": [int(pixmap.width), int(pixmap.height)],
            "physical_glyph_ink_proof": physical_ink_proof,
            "physical_glyph_ink_proof_valid": physical_ink_proof_valid,
            "source_zero_ink_physically_proven": source_zero_ink_proven,
            "visible_ink_expected": not source_zero_ink_proven,
            "visible_ink_verified": visible_ink_verified,
            "zero_ink_verified": zero_ink_verified,
            "source_pixels_sampled": source_pixels_sampled,
            "anchor_verified": insert_ok,
            "size_verified": size_ok,
        }
        if not (
            attempt.type_verified
            and attempt.visual_verified
            and attempt.cleanup_verified
        ):
            raise ValueError("terminal raster failed type, visual, or ownership verification")
        attempt.outcome = "verified"
        return (
            TextDeliveryResult(
                source_id=delivery.source_id,
                requested_representation=delivery.requested_representation,
                final_representation="raster",
                verified=True,
                entity_handles=[image_handle],
                support_entity_handles=support_handles,
                attempts=attempts,
            ),
            _PendingRasterAsset(asset_path, png),
        )
    except Exception as exc:
        attempt.reason = f"{type(exc).__name__}: {exc}"
        if entity_handles_before_creation is not None:
            created_handles = (
                _entitydb_handles(doc) - entity_handles_before_creation
            ) | set(attempt.created_entity_handles)
        else:
            created_handles = set(attempt.created_entity_handles)
        attempt.created_entity_handles = sorted(
            handle for handle in created_handles if handle
        )
        (
            attempt.removed_entity_handles,
            attempt.cleanup_verified,
        ) = _cleanup_partial_image_attempt(
            doc,
            msp,
            created_handles,
            dictionary_bindings_before_creation,
        )
        attempt.entity_handles = []
        attempt.support_entity_handles = []
        attempt.outcome = "failed"
        return (
            TextDeliveryResult(
                source_id=delivery.source_id,
                requested_representation=delivery.requested_representation,
                final_representation=None,
                verified=False,
                attempts=attempts,
                failure_reason=attempt.reason,
            ),
            None,
        )


def export_to_dxf(
    extraction: DocumentExtraction,
    output_path: str,
    options: Optional[DxfExportOptions] = None,
) -> DxfExportResult:
    transaction = _AssetTransaction()
    try:
        result = _export_to_dxf_impl(
            extraction,
            output_path,
            options,
            asset_transaction=transaction,
        )
    except Exception:
        transaction.rollback()
        if options is not None and options.provenance_opts is not None:
            options.provenance_opts._result_status = "failed"  # noqa: B010
            options.provenance_opts._delivered_image_count = 0  # noqa: B010
        raise
    transaction.commit()
    return result


def _export_to_dxf_impl(
    extraction: DocumentExtraction,
    output_path: str,
    options: Optional[DxfExportOptions] = None,
    *,
    asset_transaction: _AssetTransaction,
) -> DxfExportResult:
    opts = options or DxfExportOptions()
    output = Path(output_path).expanduser().resolve()
    source_pdf = Path(extraction.pdf_path).expanduser().resolve()
    source_pdf_sha256: Optional[str] = None
    session_token = uuid.uuid4().hex
    asset_parent = output.with_name(f"{output.stem}_assets")
    asset_root = asset_parent / session_token
    pending_raster_assets: List[_PendingRasterAsset] = []
    embedded_font_paths = (
        _stage_embedded_font_assets(extraction, asset_root, asset_transaction)
        if opts.include_text
        else {}
    )
    staged_image_assets = (
        _stage_image_assets(extraction, asset_root, asset_transaction)
        if opts.include_images
        else {}
    )
    dxf_ver = _normalize_dxf_version(opts.dxf_version)
    is_r12 = dxf_ver == "R12"
    reset_text_styles()
    doc = ezdxf.new(dxf_ver)
    doc.units = MM
    doc.header["$INSUNITS"] = 4
    doc.set_raster_variables(frame=0, quality=1, units="mm")
    msp = doc.modelspace()

    entity_count = 0
    image_count = 0
    text_fallbacks: List[Dict[str, Any]] = []
    delivered_text_entity_counts: Dict[str, int] = {}
    text_deliveries: List[Dict[str, Any]] = []
    serialized_text_sources: Dict[str, Tuple[Any, ImportConfig]] = {}
    serialized_page_visual_sources: Dict[str, Dict[str, Any]] = {}
    seen_text_source_ids: set[str] = set()
    seen_text_entity_handles: set[str] = set()
    serialized_image_expectations: List[_SerializedImageExpectation] = []
    if opts.provenance_opts is not None:
        # This transient export state is consumed by write_import_report after
        # the DXF is built, so stale data from a prior export cannot lie.
        opts.provenance_opts._text_mode_fallbacks = []  # noqa: B010
        opts.provenance_opts._delivered_text_entity_counts = {}  # noqa: B010
        opts.provenance_opts._text_representation_deliveries = []  # noqa: B010
        opts.provenance_opts._source_provenance_objects = []  # noqa: B010
        opts.provenance_opts._delivered_image_count = 0  # noqa: B010
        opts.provenance_opts._result_status = "pending_export"  # noqa: B010

    def _sync_text_evidence() -> None:
        if opts.provenance_opts is None:
            return
        opts.provenance_opts._text_mode_fallbacks = [  # noqa: B010
            dict(item) for item in text_fallbacks
        ]
        opts.provenance_opts._delivered_text_entity_counts = dict(  # noqa: B010
            delivered_text_entity_counts
        )
        opts.provenance_opts._text_representation_deliveries = [  # noqa: B010
            dict(item) for item in text_deliveries
        ]
        opts.provenance_opts._export_requested_text_mode = (  # noqa: B010
            _normalized_text_mode(opts.text_mode)
        )
    dash_cache: Dict[str, str] = {}
    image_def_cache: Dict[str, object] = {}

    # Multi-page placement offset.
    _stack_offset_y = 0.0
    arrangement = (opts.page_arrangement or "spread").strip().lower()
    if arrangement not in {"spread", "compact", "touch", "overlay"}:
        arrangement = "spread"
    gap_ratio = max(0.0, float(opts.page_gap_ratio or 0.0))

    # Export extents for host auto-framing (LibreCAD/QCAD/AutoCAD).
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    def _track_xy(x: float, y: float) -> None:
        nonlocal min_x, min_y, max_x, max_y
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y

    for page in extraction.pages:
        # Apply page stacking offset to all coordinates
        dy = _stack_offset_y
        page_w = float(page.page_data.width or 0.0)
        page_h = float(page.page_data.height or 0.0)
        page_image_bindings: List[Dict[str, Any]] = []
        # Seed extents from the page frame so host auto-fit still works even
        # when selected export mode yields no drawable entities on that page.
        _track_xy(0.0, 0.0 + dy)
        _track_xy(page_w, page_h + dy)

        for primitive in page.page_data.primitives:
            stroke_rgb = primitive.stroke_color
            fill_rgb = primitive.fill_color
            layer_rgb = stroke_rgb if stroke_rgb is not None else fill_rgb
            layer = _layer_name(page.page_data.page_number, primitive.layer_name, layer_rgb, opts)
            _ensure_layer(doc, layer, layer_rgb)
            attribs = {"layer": layer}
            fill_attribs = {"layer": layer}
            if is_r12:
                _apply_r12_color(attribs, stroke_rgb)
                _apply_r12_color(fill_attribs, fill_rgb)
            else:
                _apply_color(attribs, stroke_rgb)
                _apply_color(fill_attribs, fill_rgb)
                _apply_lineweight(attribs, primitive.line_width)

            if opts.map_dashes:
                ltype = _linetype_from_dash(doc, primitive.dash_pattern, dash_cache)
                if ltype:
                    attribs["linetype"] = ltype

            # Helper to offset a point by the page stacking offset
            def _ofs(pt, _dy=dy):
                return (pt[0], pt[1] + _dy)

            offset_pts = [_ofs(point) for point in (primitive.points or [])]
            page_background_fill = _is_redundant_white_page_fill(
                primitive,
                page_width=page_w,
                page_height=page_h,
            )
            if (
                fill_rgb is not None
                and not page_background_fill
                and len(offset_pts) >= 3
            ):
                fills = _add_filled_path(
                    msp,
                    offset_pts,
                    fill_rgb,
                    fill_attribs,
                    is_r12=is_r12,
                )
                if not fills:
                    raise RuntimeError(
                        f"filled source primitive {primitive.id} produced no fill entities"
                    )
                entity_count += len(fills)

            # A PDF fill-only path has no stroke.  Do not manufacture an
            # outline in the fill color after its exact fill has been emitted.
            if stroke_rgb is None:
                for px, py in offset_pts:
                    _track_xy(float(px), float(py))
                continue

            if primitive.type == "line" and primitive.points and len(primitive.points) == 2:
                start = _ofs(primitive.points[0])
                end = _ofs(primitive.points[1])
                msp.add_line(start, end, dxfattribs=attribs)
                _track_xy(float(start[0]), float(start[1]))
                _track_xy(float(end[0]), float(end[1]))
                entity_count += 1
            elif primitive.type == "circle" and primitive.center and primitive.radius:
                center = _ofs(primitive.center)
                radius = float(primitive.radius)
                msp.add_circle(center, radius, dxfattribs=attribs)
                _track_xy(float(center[0]) - radius, float(center[1]) - radius)
                _track_xy(float(center[0]) + radius, float(center[1]) + radius)
                entity_count += 1
            elif primitive.type == "arc" and primitive.center and primitive.radius:
                start = float(primitive.start_angle or 0.0)
                end = float(primitive.end_angle or 0.0)
                if math.isclose(start, end, abs_tol=1e-6):
                    end = (end + 359.999) % 360.0
                center = _ofs(primitive.center)
                radius = float(primitive.radius)
                msp.add_arc(center, radius, start, end, dxfattribs=attribs)
                _track_xy(float(center[0]) - radius, float(center[1]) - radius)
                _track_xy(float(center[0]) + radius, float(center[1]) + radius)
                entity_count += 1
            elif primitive.points and len(primitive.points) >= 2:
                if is_r12:
                    msp.add_polyline2d(
                        offset_pts,
                        close=bool(primitive.closed),
                        dxfattribs=attribs,
                    )
                else:
                    msp.add_lwpolyline(
                        offset_pts,
                        format="xy",
                        close=bool(primitive.closed),
                        dxfattribs=attribs,
                    )
                for px, py in offset_pts:
                    _track_xy(float(px), float(py))
                entity_count += 1

        if opts.include_text and opts.text_mode != "none":
            if source_pdf_sha256 is None:
                source_pdf_sha256 = _file_sha256(source_pdf)
            text_cfg = ImportConfig.auto()
            text_cfg.text_mode = opts.text_mode
            text_cfg._embedded_font_asset_paths = dict(embedded_font_paths)  # noqa: B010
            text_cfg._source_pdf_path = str(source_pdf)  # noqa: B010
            text_cfg._source_pdf_sha256 = source_pdf_sha256  # noqa: B010
            for text in page.page_data.text_items:
                layer = _layer_name(page.page_data.page_number, "TEXT", None, opts)
                _ensure_layer(doc, layer, None)
                ti = text
                if dy != 0.0:
                    from dataclasses import replace as _dc_replace
                    ti = _dc_replace(
                        text,
                        insertion=(
                            float(text.insertion[0]),
                            float(text.insertion[1]) + dy,
                        ),
                        bbox=(
                            (
                                float(text.bbox[0]),
                                float(text.bbox[1]) + dy,
                                float(text.bbox[2]),
                                float(text.bbox[3]) + dy,
                            )
                            if text.bbox
                            else None
                        ),
                    )
                delivery = build_text(
                    ti,
                    msp,
                    layer,
                    text_cfg,
                    is_r12=is_r12,
                    target_app="librecad",
                    dxf_version=dxf_ver,
                    return_delivery_result=True,
                )
                if not isinstance(delivery, TextDeliveryResult):
                    raise RuntimeError("text builder returned no delivery evidence")
                if (
                    (not delivery.verified or not delivery.final_representation)
                    and delivery.terminal_fallback_authorized
                ):
                    if source_pdf_sha256 is None:
                        source_pdf_sha256 = _file_sha256(source_pdf)
                    delivery, pending_asset = _attempt_terminal_text_raster(
                        delivery,
                        extraction=extraction,
                        page_number=int(page.page_data.page_number),
                        source_text=text,
                        placed_text=ti,
                        msp=msp,
                        layer_name=layer,
                        asset_root=asset_root,
                        raster_dpi=int(
                            getattr(opts.provenance_opts, "raster_dpi", 300)
                            if opts.provenance_opts is not None
                            else 300
                        ),
                        source_pdf_sha256=source_pdf_sha256,
                        config=text_cfg,
                    )
                    if pending_asset is not None:
                        pending_raster_assets.append(pending_asset)
                if not delivery.verified or not delivery.final_representation:
                    text_deliveries.append(delivery.to_dict())
                    _sync_text_evidence()
                    raise TextRepresentationDeliveryError(
                        (
                            f"{delivery.source_id or 'unknown text item'}: "
                            f"{delivery.failure_reason or 'all representation attempts failed'}"
                        ),
                        delivery,
                    )
                if delivery.source_id in seen_text_source_ids:
                    raise RuntimeError(
                        f"{delivery.source_id}: duplicate stable text source identity"
                    )
                duplicate_handles = seen_text_entity_handles.intersection(
                    delivery.entity_handles
                )
                if duplicate_handles:
                    raise RuntimeError(
                        f"{delivery.source_id}: duplicate delivered DXF handles "
                        f"{sorted(duplicate_handles)}"
                    )
                seen_text_source_ids.add(delivery.source_id)
                seen_text_entity_handles.update(delivery.entity_handles)
                serialized_text_sources[delivery.source_id] = (text, text_cfg)
                text_deliveries.append(delivery.to_dict())

                delivered_kind = delivery.delivered_kind
                created = int(delivery.count)
                _track_xy(float(ti.insertion[0]), float(ti.insertion[1]))
                if ti.bbox:
                    x0, y0, x1, y1 = ti.bbox
                    _track_xy(float(x0), float(y0))
                    _track_xy(float(x1), float(y1))
                entity_count += created
                if delivery.final_representation == "raster":
                    image_count += created
                if created > 0:
                    delivered_bucket = _delivered_text_entity_bucket(delivered_kind)
                    delivered_text_entity_counts[delivered_bucket] = (
                        int(delivered_text_entity_counts.get(delivered_bucket, 0) or 0)
                        + created
                    )
                    if delivery.fallback_used:
                        _append_text_fallback(
                            text_fallbacks,
                            requested=delivery.requested_representation,
                            delivered=str(delivery.final_representation),
                            reason=_fallback_reason_code(delivery),
                            count=1,
                        )
                if created > 0 and opts.provenance_opts is not None:
                    from pdfcadcore.source_provenance import (
                        SourceProvenanceObject,
                        ensure_provenance_bucket,
                    )

                    source_bbox = getattr(ti, "source_bbox_pdf", None)
                    target_bbox = getattr(ti, "bbox", None)
                    span_id = getattr(ti, "id", None)
                    try:
                        span_id = int(span_id)
                    except (TypeError, ValueError):
                        span_id = None
                    bucket = ensure_provenance_bucket(opts.provenance_opts)
                    fallback_reason = (
                        _fallback_reason_code(delivery)
                        if delivery.fallback_used
                        else ""
                    )
                    for handle in delivery.entity_handles:
                        bucket.append(
                            SourceProvenanceObject(
                                object_id=f"{delivery.source_id}:entity:{handle}",
                                page=int(page.page_data.page_number),
                                source_kind="text_span",
                                created_entity_type=str(
                                    doc.entitydb.get(str(handle)).dxftype()
                                ),
                                parent_handle=str(handle),
                                source_bbox_pdf=(
                                    [float(value) for value in source_bbox[:4]]
                                    if source_bbox
                                    else None
                                ),
                                target_bbox_model=(
                                    [float(value) for value in target_bbox[:4]]
                                    if target_bbox
                                    else None
                                ),
                                selected_import_mode=str(
                                    getattr(
                                        opts.provenance_opts, "import_mode", ""
                                    )
                                    or ""
                                ),
                                selected_text_mode=str(opts.text_mode or ""),
                                fallback_reason=fallback_reason,
                                span_id=span_id,
                            )
                        )

        if opts.include_images:
            for placement in page.images:
                source_key = _normalized_image_source_path(str(placement.path))
                staged_asset = staged_image_assets.get(source_key)
                if staged_asset is None:
                    raise RuntimeError(
                        f"image asset was not staged for delivery: {placement.path}"
                    )
                img_path = staged_asset.path

                image_def = image_def_cache.get(str(img_path))
                if image_def is None:
                    image_def = doc.add_image_def(
                        filename=str(img_path),
                        size_in_pixel=staged_asset.size_px,
                        name=f"IMG_{len(image_def_cache) + 1}",
                    )
                    image_def_cache[str(img_path)] = image_def

                layer = _layer_name(page.page_data.page_number, "IMAGES", None, opts)
                _ensure_layer(doc, layer, None)
                insert = (float(placement.x_mm), float(placement.y_mm) + dy, 0.0)
                size_in_units = (
                    float(placement.width_mm),
                    float(placement.height_mm),
                )
                u_vector = tuple(
                    float(value)
                    for value in (
                        placement.u_vector_mm
                        if placement.u_vector_mm is not None
                        else (size_in_units[0], 0.0)
                    )
                ) + (0.0,)
                v_vector = tuple(
                    float(value)
                    for value in (
                        placement.v_vector_mm
                        if placement.v_vector_mm is not None
                        else (0.0, size_in_units[1])
                    )
                ) + (0.0,)
                pixel_width, pixel_height = staged_asset.size_px
                if pixel_width <= 0 or pixel_height <= 0:
                    raise RuntimeError(
                        f"image asset has invalid pixel dimensions: {staged_asset.path}"
                    )
                image = msp.add_image(
                    image_def,
                    insert=insert,
                    size_in_units=size_in_units,
                    dxfattribs={"layer": layer},
                )
                image.dxf.u_pixel = tuple(
                    value / float(pixel_width) for value in u_vector
                )
                image.dxf.v_pixel = tuple(
                    value / float(pixel_height) for value in v_vector
                )
                image.dxf.flags = int(image.dxf.flags or 0) | 8
                image_expectation = _SerializedImageExpectation(
                    image_handle=str(image.dxf.handle or ""),
                    image_def_handle=str(image_def.dxf.handle or ""),
                    asset_path=staged_asset.path,
                    asset_sha256=staged_asset.sha256,
                    insert=insert,
                    size_in_units=size_in_units,
                    size_in_pixel=staged_asset.size_px,
                    u_vector_in_units=u_vector,
                    v_vector_in_units=v_vector,
                )
                serialized_image_expectations.append(image_expectation)
                reactor_handle = str(image.dxf.image_def_reactor_handle or "")
                if not reactor_handle:
                    raise RuntimeError(
                        f"image {image_expectation.image_handle} has no IMAGEDEF reactor"
                    )
                page_image_bindings.append(
                    {
                        "expectation": image_expectation,
                        "reactor_handle": reactor_handle,
                        "source_xref": int(placement.xref),
                    }
                )
                for u_factor, v_factor in (
                    (0.0, 0.0),
                    (1.0, 0.0),
                    (0.0, 1.0),
                    (1.0, 1.0),
                ):
                    _track_xy(
                        insert[0] + u_factor * u_vector[0] + v_factor * v_vector[0],
                        insert[1] + u_factor * u_vector[1] + v_factor * v_vector[1],
                    )
                entity_count += 1
                image_count += 1

        requested_page_text_mode = _normalized_text_mode(opts.text_mode)
        if (
            opts.include_text
            and requested_page_text_mode != "none"
            and not page.page_data.text_items
            and page_image_bindings
        ):
            if source_pdf_sha256 is None:
                source_pdf_sha256 = _file_sha256(source_pdf)
            page_number = int(page.page_data.page_number)
            source_id = f"page_visual:{page_number}"
            zero_text_proof = _source_zero_text_page_proof(source_pdf, page_number)
            if zero_text_proof.get("verified_zero_text") is not True:
                raise RuntimeError(
                    f"{source_id}: normalized text is empty but exact source-zero-text proof failed"
                )
            if source_id in seen_text_source_ids:
                raise RuntimeError(f"{source_id}: duplicate stable page visual identity")

            image_artifacts = [
                _page_visual_image_artifact(
                    binding["expectation"],
                    reactor_handle=str(binding["reactor_handle"]),
                    source_xref=int(binding["source_xref"]),
                )
                for binding in page_image_bindings
            ]
            image_handles = [
                str(artifact["image_handle"]) for artifact in image_artifacts
            ]
            support_handles = [
                str(handle)
                for artifact in image_artifacts
                for handle in (
                    artifact["image_def_handle"],
                    artifact["image_def_reactor_handle"],
                )
            ]
            duplicate_handles = seen_text_entity_handles.intersection(image_handles)
            if duplicate_handles:
                raise RuntimeError(
                    f"{source_id}: duplicate delivered DXF handles {sorted(duplicate_handles)}"
                )
            source_evidence = {
                "source_id": source_id,
                "source_pdf_path": str(source_pdf),
                "source_pdf_sha256": str(source_pdf_sha256),
                "source_page_number": page_number,
                "source_zero_text_proof": zero_text_proof,
            }
            attempts: List[TextDeliveryAttempt] = []
            if requested_page_text_mode != "raster":
                attempts.append(
                    TextDeliveryAttempt(
                        source_id=source_id,
                        requested_representation=requested_page_text_mode,
                        attempted_representation=requested_page_text_mode,
                        strategy="source_zero_text_requested_representation",
                        outcome="impossible",
                        reason=(
                            "the exact source page contains no PDF text object to "
                            f"deliver as {requested_page_text_mode}"
                        ),
                        cleanup_verified=True,
                        evidence={
                            **source_evidence,
                            "no_source_text_item_verified": True,
                        },
                    )
                )
            terminal_evidence = {
                **source_evidence,
                "existing_image_entity_reused": True,
                "duplicate_image_entities_created": False,
                "image_entity_count": len(image_handles),
                "image_entity_handles": image_handles,
                "image_artifacts": image_artifacts,
            }
            attempts.append(
                TextDeliveryAttempt(
                    source_id=source_id,
                    requested_representation=requested_page_text_mode,
                    attempted_representation="raster",
                    strategy="existing_page_image_terminal_raster",
                    outcome="verified",
                    type_verified=True,
                    visual_verified=True,
                    created_entity_handles=[],
                    entity_handles=image_handles,
                    support_entity_handles=support_handles,
                    cleanup_verified=True,
                    evidence=terminal_evidence,
                )
            )
            page_delivery = TextDeliveryResult(
                source_id=source_id,
                requested_representation=requested_page_text_mode,
                final_representation="raster",
                verified=True,
                entity_handles=image_handles,
                support_entity_handles=support_handles,
                attempts=attempts,
            )
            seen_text_source_ids.add(source_id)
            seen_text_entity_handles.update(image_handles)
            serialized_page_visual_sources[source_id] = {
                "page_number": page_number,
                "source_pdf_sha256": str(source_pdf_sha256),
                "source_zero_text_proof": zero_text_proof,
                "image_bindings": page_image_bindings,
            }
            text_deliveries.append(page_delivery.to_dict())
            delivered_text_entity_counts["raster_image"] = int(
                delivered_text_entity_counts.get("raster_image", 0) or 0
            ) + len(image_handles)
            if page_delivery.fallback_used:
                _append_text_fallback(
                    text_fallbacks,
                    requested=requested_page_text_mode,
                    delivered="raster",
                    reason=_fallback_reason_code(page_delivery),
                    count=1,
                )

        # Advance page placement offset for the next page.
        page_step = _page_stack_step(page.page_data.height, arrangement, gap_ratio)
        _stack_offset_y -= page_step

    # Persist extents + initial modelspace viewport so hosts open focused on geometry.
    if min_x <= max_x and min_y <= max_y:
        extmin = (float(min_x), float(min_y), 0.0)
        extmax = (float(max_x), float(max_y), 0.0)
        msp.dxf.extmin = extmin
        msp.dxf.extmax = extmax
        msp.dxf.limmin = (float(min_x), float(min_y))
        msp.dxf.limmax = (float(max_x), float(max_y))
        doc.header["$EXTMIN"] = extmin
        doc.header["$EXTMAX"] = extmax
        doc.header["$LIMMIN"] = (float(min_x), float(min_y))
        doc.header["$LIMMAX"] = (float(max_x), float(max_y))
        center = ((float(min_x) + float(max_x)) * 0.5, (float(min_y) + float(max_y)) * 0.5)
        height = max(1.0, float(max_y) - float(min_y))
        width = max(1.0, float(max_x) - float(min_x))
        doc.set_modelspace_vport(max(height, width) * 1.1, center=center)
        active = doc.viewports.get("*Active")
        if active:
            vp = active[0]
            vp.dxf.center = center
            vp.dxf.height = height * 1.1

    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(f".{output.name}.{session_token}.tmp")
    written_assets: List[Path] = []
    temp_assets: List[Path] = []
    try:
        for asset in pending_raster_assets:
            asset.path.parent.mkdir(parents=True, exist_ok=True)
            temp_asset = asset.path.with_name(f".{asset.path.name}.tmp")
            temp_assets.append(temp_asset)
            temp_asset.write_bytes(asset.content)
            if temp_asset.read_bytes() != asset.content:
                raise OSError(f"raster asset byte verification failed: {asset.path}")
            temp_asset.replace(asset.path)
            temp_assets.remove(temp_asset)
            written_assets.append(asset.path)
            asset_transaction.register_file(asset.path)
            asset_transaction.register_directory(asset.path.parent)
            asset_transaction.register_directory(asset.path.parent.parent)

        doc.saveas(str(temp_output))
        # Re-open the exact candidate before it can replace a prior good DXF.
        candidate = ezdxf.readfile(str(temp_output))
        auditor = candidate.audit()
        if auditor.has_errors:
            raise RuntimeError(
                "serialized DXF candidate failed audit with "
                f"{len(auditor.errors)} error(s)"
            )
        _verify_serialized_text_deliveries(
            candidate,
            text_deliveries,
            expected_source_pdf_path=source_pdf,
            expected_source_pdf_sha256=str(source_pdf_sha256 or ""),
            expected_text_sources=serialized_text_sources,
            expected_page_visual_sources=serialized_page_visual_sources,
        )
        _verify_serialized_image_assets(candidate, serialized_image_expectations)
        temp_output.replace(output)
    except Exception:
        for temp_asset in temp_assets:
            try:
                temp_asset.unlink(missing_ok=True)
            except OSError:
                pass
        for asset_path in written_assets:
            try:
                asset_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            temp_output.unlink(missing_ok=True)
        except OSError:
            pass
        for directory in (asset_root, asset_parent):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise

    if opts.provenance_opts is not None:
        # ImportRun owns the config during CLI export; importer.py reads these
        # actual delivery facts immediately afterward to build import_report.
        opts.provenance_opts._delivered_image_count = int(image_count)  # noqa: B010
        opts.provenance_opts._result_status = "success"  # noqa: B010
        _sync_text_evidence()

    return DxfExportResult(
        output_path=str(output),
        entity_count=entity_count,
        layer_count=len(doc.layers),
        image_count=image_count,
        text_fallbacks=[dict(item) for item in text_fallbacks],
        delivered_text_entity_counts=dict(delivered_text_entity_counts),
        text_deliveries=[dict(item) for item in text_deliveries],
    )


def _layer_name(page_number: int, source_layer: Optional[str], stroke_color,
                opts: DxfExportOptions) -> str:
    parts = []
    if opts.group_by_page:
        parts.append(f"P{page_number:03d}")
    if opts.prefer_source_layers and source_layer:
        parts.append(_sanitize_layer(str(source_layer)))
    elif stroke_color is not None:
        parts.append(_color_key(stroke_color))
    return "_".join(parts) if parts else "PDF_IMPORT"


def _normalize_dxf_version(raw: str) -> str:
    allowed = {"R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"}
    normalized = (raw or "R2018").strip().upper()
    return normalized if normalized in allowed else "R2018"


def _page_stack_step(page_height: float, arrangement: str, gap_ratio: float) -> float:
    h = max(1.0, float(page_height or 0.0))
    if arrangement == "overlay":
        return 0.0
    if arrangement == "touch":
        return h
    if arrangement == "compact":
        return h * (1.0 + max(0.0, gap_ratio))
    return h * 1.2


def _sanitize_layer(name: str) -> str:
    out = [ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name.strip()]
    value = "".join(out).strip("_")
    return value[:120] if value else "Layer"


def _color_key(rgb) -> str:
    r, g, b = (int(max(0, min(255, round(float(c) * 255)))) for c in rgb)
    return f"RGB_{r:03d}_{g:03d}_{b:03d}"


def _rgb_bytes(rgb) -> Tuple[int, int, int]:
    return tuple(
        int(max(0, min(255, round(float(component) * 255))))
        for component in rgb[:3]
    )


def _nearest_r12_aci(rgb) -> int:
    """Return a fixed ACI approximation without color-7 background inversion."""

    target = _rgb_bytes(rgb)
    candidates = list(range(1, 7)) + list(range(8, 256))
    return min(
        candidates,
        key=lambda index: sum(
            (int(left) - int(right)) ** 2
            for left, right in zip(aci2rgb(index), target, strict=True)
        ),
    )


def _apply_r12_color(attribs: dict, rgb) -> None:
    if rgb is not None:
        attribs["color"] = _nearest_r12_aci(rgb)


def _add_filled_path(
    msp,
    points,
    fill_rgb,
    attribs: dict,
    *,
    is_r12: bool,
) -> List[Any]:
    """Emit a real closed PDF fill while leaving its stroke independent."""

    cleaned: List[Tuple[float, float]] = []
    for raw in points:
        point = (float(raw[0]), float(raw[1]))
        if not cleaned or not all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
            for left, right in zip(point, cleaned[-1], strict=True)
        ):
            cleaned.append(point)
    if len(cleaned) >= 2 and all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
        for left, right in zip(cleaned[0], cleaned[-1], strict=True)
    ):
        cleaned.pop()
    if len(cleaned) < 3:
        return []

    if not is_r12:
        hatch = msp.add_hatch(dxfattribs=dict(attribs))
        # LibreCAD's print path may honor HATCH ACI before true-color.  Use a
        # non-inverting ACI approximation as well as exact RGB; color 7 would
        # turn a white PDF page fill black on printed output.
        parent_rgb = _rgb_bytes(fill_rgb)
        if parent_rgb == (255, 255, 255):
            # LibreCAD's print engine inverts exact white drawing entities to
            # black.  254/255 is visually indistinguishable on white paper and
            # bypasses that special color-7/white inversion path.
            parent_rgb = (254, 254, 254)
        hatch.set_solid_fill(
            color=_nearest_r12_aci(fill_rgb),
            rgb=RGB(*parent_rgb),
            style=0,
        )
        hatch.paths.add_polyline_path(cleaned, is_closed=True, flags=1)
        return [hatch]

    path = ezdxf_path.from_vertices(cleaned, close=True)
    solids: List[Any] = []
    for triangle in ezdxf_path.triangulate(
        [path],
        max_sagitta=0.01,
        min_segments=2,
    ):
        vertices = [(float(point.x), float(point.y)) for point in triangle]
        if len(vertices) != 3:
            continue
        p0, p1, p2 = vertices
        area2 = abs(
            (p1[0] - p0[0]) * (p2[1] - p0[1])
            - (p1[1] - p0[1]) * (p2[0] - p0[0])
        )
        if not math.isfinite(area2) or area2 <= 1e-14:
            continue
        solids.append(
            msp.add_solid([p0, p1, p2, p2], dxfattribs=dict(attribs))
        )
    return solids


def _is_redundant_white_page_fill(
    primitive,
    *,
    page_width: float,
    page_height: float,
) -> bool:
    """Use the parent's white paper for an opaque full-page white rectangle.

    LibreCAD deliberately maps white drawing entities to black when printing.
    Emitting a PDF's explicit white page background as HATCH therefore turns
    the entire exported page black.  Omitting only the exact page-sized,
    fill-only white rectangle preserves the same pixels on white paper while
    retaining all smaller white knockout shapes.
    """

    fill = getattr(primitive, "fill_color", None)
    if fill is None or getattr(primitive, "stroke_color", None) is not None:
        return False
    if any(float(component) < 0.995 for component in fill[:3]):
        return False
    bbox = getattr(primitive, "bbox", None)
    if not bbox or len(bbox) < 4:
        return False
    expected = (0.0, 0.0, float(page_width), float(page_height))
    tolerance = max(1e-7, max(float(page_width), float(page_height), 1.0) * 1e-7)
    return all(
        math.isclose(
            float(actual),
            target,
            rel_tol=0.0,
            abs_tol=tolerance,
        )
        for actual, target in zip(bbox[:4], expected, strict=True)
    )


def _ensure_layer(doc: ezdxf.EzDxf, name: str, rgb) -> None:
    if doc.layers.has_entry(name):
        return
    kwargs = {}
    if rgb is not None:
        kwargs["true_color"] = rgb2int(tuple(int(max(0, min(255, round(float(c) * 255)))) for c in rgb))
    doc.layers.new(name=name, dxfattribs=kwargs)


def _apply_color(attribs: dict, rgb) -> None:
    if rgb is None:
        return
    r, g, b = (int(max(0, min(255, round(float(c) * 255)))) for c in rgb)
    # Invert near-white colors to black so geometry is visible on
    # LibreCAD's default white background.  Without this, white-on-white
    # entities are invisible and the user sees a blank/black screen.
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance > 230:
        r, g, b = 0, 0, 0
    attribs["true_color"] = rgb2int((r, g, b))


def _apply_lineweight(attribs: dict, width_pt) -> None:
    if width_pt is None:
        return
    width_mm = float(width_pt) * (25.4 / 72.0)
    lw = int(max(5, min(211, round(width_mm * 100))))  # hundredths of mm
    attribs["lineweight"] = lw


def _linetype_from_dash(doc: ezdxf.EzDxf, dash_pattern, cache: Dict[str, str]) -> Optional[str]:
    if not dash_pattern:
        return None

    values = _normalize_dash(dash_pattern)
    if len(values) < 2:
        return None

    key = ",".join(f"{v:.2f}" for v in values)
    cached = cache.get(key)
    if cached:
        return cached

    if len(values) % 2 == 1:
        values.append(values[-1])

    mm_vals = [max(0.1, v * (25.4 / 72.0)) for v in values]
    pattern = [sum(mm_vals)]
    for idx, val in enumerate(mm_vals):
        pattern.append(val if idx % 2 == 0 else -val)

    name = f"PDF_DASH_{len(cache) + 1}"
    try:
        doc.linetypes.add(name=name, pattern=pattern, description=f"PDF dash {key}")
    except Exception:
        return None

    cache[key] = name
    return name


def _normalize_dash(dash_pattern) -> list[float]:
    if isinstance(dash_pattern, str):
        vals = []
        token = ""
        for ch in dash_pattern:
            if ch.isdigit() or ch in {".", "-"}:
                token += ch
                continue
            if token:
                try:
                    vals.append(abs(float(token)))
                except ValueError:
                    pass
                token = ""
        if token:
            try:
                vals.append(abs(float(token)))
            except ValueError:
                pass
        return [v for v in vals if v > 0.0]

    if isinstance(dash_pattern, (list, tuple)):
        vals = []
        for item in dash_pattern:
            if isinstance(item, (int, float)):
                vals.append(abs(float(item)))
            elif isinstance(item, (list, tuple)):
                for nested in item:
                    if isinstance(nested, (int, float)):
                        vals.append(abs(float(nested)))
        return [v for v in vals if v > 0.0]

    return []


def _image_size_pixels(path: str) -> Tuple[int, int]:
    try:
        pix = fitz.Pixmap(path)
    except Exception as exc:
        raise RuntimeError(f"image asset cannot be decoded: {path}: {exc}") from exc
    width = int(pix.width)
    height = int(pix.height)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"image asset has invalid pixel dimensions: {path}")
    return width, height

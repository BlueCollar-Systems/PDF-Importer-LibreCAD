"""DXF export adapter for LibreCAD workflows."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import traceback
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import uuid
import weakref

import ezdxf
import numpy as np
from ezdxf import path as ezdxf_path
from ezdxf.colors import RGB, aci2rgb, rgb2int
from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS
from ezdxf.lldxf.encoding import decode_dxf_unicode
from ezdxf.math import Vec2, is_point_in_polygon_2d
from ezdxf.math.triangulation import mapbox_earcut_2d
from ezdxf.units import MM

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from ..core.image_paint_order import (
    apply_image_paint_order,
    verify_serialized_image_paint_order,
)

from ..core.document import (
    DocumentExtraction,
    ImagePlacement,
    _classify_pixmap_alpha,
    host_clip_fill_issue,
)

from pdfcadcore.import_config import ImportConfig
from pdfcadcore.fitz_loader import safe_open
from pdfcadcore.primitive_extractor import (
    _page_rotation_transform,
    _transform_pdf_point,
)
from pdfcadcore.primitives import TextCharLayout

from dxf_text_builder import (
    TextDeliveryAttempt,
    TextDeliveryResult,
    _attempt_degraded_text,
    _bbox_tuple,
    _glyph_definition_geometry_fingerprint,
    _glyph_instance_transform_fingerprint,
    _glyph_outer_block_structure_fingerprint,
    _positioned_geometry_fingerprint,
    _resolve_librecad_unicode_lff,
    _nested_outline_tolerance,
    _solid_fill_verified,
    _source_id,
    _write_search_text_companion,
    build_text,
    iter_glyph_outline_entities,
    reset_text_styles,
)
from conversion_control import (
    ActivePageCancelled,
    ImportStopped,
    check_cancel,
    report_progress,
)
from librecad_runtime import local_path_for_io, resolve_librecad_installation


TERMINAL_TILE_PIXELS = 1536
TERMINAL_TILE_BLEED_PIXELS = 4
TERMINAL_MAX_PAGE_PIXELS = 134_217_728
TERMINAL_MAX_PAGE_DIMENSION = 24_576
TERMINAL_MAX_TILES = 256
TERMINAL_MAX_JOB_PIXELS = 268_435_456
TERMINAL_MAX_JOB_TILES = 512
TERMINAL_MAX_JOB_ASSET_BYTES = 805_306_368
TERMINAL_MIN_DPI = 36.0
RECTANGULAR_CROP_MAX_PIXELS = 4_000_000
OPAQUE_ALPHA_NORMALIZE_MAX_PIXELS = 16_000_000

_POSITIONED_TRANSLATION_RECEIPT_APPID = "BCS_POSITIONED_TRANSLATION"
_POSITIONED_TRANSLATION_RECEIPT_SCHEMA = "bcs-positioned-translation-receipt-v1"
_POSITIONED_LAYOUT_PROOF_FIELDS = frozenset(
    {
        "positioned_character_text",
        "positioned_source_glyph_ids",
        "positioned_source_glyph_names",
        "positioned_character_origins",
        "positioned_character_quads",
        "positioned_character_local_bboxes",
        "positioned_character_rotations",
        "positioned_character_count",
        "positioned_layout_bijection_verified",
        "positioned_source_font_glyphs_verified",
        "positioned_source_font_identity_sha256",
        "positioned_layout_sha256",
        "positioned_visible_geometry_fill_only",
        "positioned_contour_entities_omitted",
    }
)
_POSITIONED_PAGE_TRANSLATION_PROOF_FIELDS = frozenset(
    {
        "export_page_translation",
        "positioned_pretranslation_character_origins",
        "positioned_pretranslation_character_quads",
        "positioned_export_translation_verified",
    }
)
_POSITIONED_RECEIPT_PROOF_FIELDS = frozenset(
    {
        "positioned_translation_receipt_schema",
        "positioned_translation_receipt_sha256",
    }
)
_POSITIONED_GEOMETRY_PROOF_FIELDS = frozenset(
    {
        "positioned_geometry_character_solid_counts",
        "positioned_geometry_fingerprint_schema",
        "positioned_geometry_entity_count",
        "positioned_geometry_sha256",
    }
)


_SOURCE_DASH_APPID = "BCS_SOURCE_DASH"


def _add_source_dash_block(doc, layout, primitive, proof, attribs, dy):
    name = f"BCS_DASH_{primitive.page_number}_{primitive.id}"
    if name in doc.blocks:
        raise RuntimeError("duplicate source dash block identity")
    block = doc.blocks.new(name)
    segment_attrs = dict(attribs)
    segment_attrs["linetype"] = "Continuous"
    segment_attrs.setdefault("invisible", 0)
    segments = []
    for start, end in proof.segments_model:
        a, b = (start[0], start[1]+dy, 0.0), (end[0], end[1]+dy, 0.0)
        entity = block.add_line(a, b, dxfattribs=segment_attrs)
        segments.append((str(entity.dxf.handle), a, b))
    parent = layout.add_blockref(name, (0, 0, 0), dxfattribs=segment_attrs)
    if _SOURCE_DASH_APPID not in doc.appids:
        doc.appids.add(_SOURCE_DASH_APPID)
    source = json.dumps({
        "schema": "bcs.source-straight-dashes/1", "source_id": primitive.id,
        "source_seqno": proof.source_seqno, "source_start_pdf": proof.source_start_pdf,
        "source_end_pdf": proof.source_end_pdf, "pattern_pdf": proof.pattern_pdf,
        "phase_pdf": proof.phase_pdf, "visible_source_interval": proof.visible_source_interval,
        "source_line_cap": proof.line_cap,
        "display_limit": "Native LINE cap and lineweight display remain host-dependent.",
    }, sort_keys=True, separators=(",", ":"))
    tags = [(1000, source[index:index+240]) for index in range(0, len(source), 240)]
    parent.set_xdata(_SOURCE_DASH_APPID, tags)
    return {"handle": str(parent.dxf.handle), "name": name, "segments": segments,
            "source_json": source, "attrs": segment_attrs}


def _verify_serialized_source_dash_blocks(doc, expectations):
    for expected in expectations:
        parent = doc.entitydb.get(expected["handle"])
        if (parent is None or parent.dxftype() != "INSERT" or parent.dxf.name != expected["name"]
                or tuple(parent.dxf.insert) != (0, 0, 0) or parent.dxf.rotation != 0
                or (parent.dxf.xscale, parent.dxf.yscale, parent.dxf.zscale) != (1, 1, 1)
                or tuple(parent.dxf.extrusion) != (0, 0, 1)):
            raise RuntimeError("serialized source dash parent transform changed")
        if any(getattr(parent.dxf, key) != value for key, value in expected["attrs"].items()):
            raise RuntimeError("serialized source dash parent style or visibility changed")
        metadata = "".join(tag.value for tag in parent.get_xdata(_SOURCE_DASH_APPID))
        if metadata != expected["source_json"]:
            raise RuntimeError("serialized source dash identity changed")
        lines = list(doc.blocks[expected["name"]])
        if len(lines) != len(expected["segments"]):
            raise RuntimeError("serialized source dash count changed")
        for line, (handle, start, end) in zip(lines, expected["segments"], strict=True):
            if (line.dxftype() != "LINE" or str(line.dxf.handle) != handle
                    or any(not math.isclose(a, b, abs_tol=1e-10, rel_tol=0)
                           for a, b in zip(tuple(line.dxf.start)+tuple(line.dxf.end), start+end, strict=True))
                    or any(getattr(line.dxf, key) != value for key, value in expected["attrs"].items())):
                raise RuntimeError("serialized source dash geometry or style changed")


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
    librecad_executable: Optional[str] = None
    # Hidden, non-certifying companion: the exact source string of every
    # outlined / rastered / dropped span as native TEXT on the frozen layer
    # P###_TEXT_SEARCH, so the drawing is searchable. Outlines stay the truth.
    searchable_text: bool = True


class TextRepresentationDeliveryError(ImportStopped):
    """A text item has no stable source identity, so it cannot even be reported.

    An unverifiable item no longer raises this: it degrades (item raster patch,
    visible degraded TEXT, reported drop) and the sheet still exports.
    """

    def __init__(self, message: str, delivery: TextDeliveryResult):
        super().__init__(message)
        self.delivery = delivery


class _SerializedTextDeliveryMismatches(RuntimeError):
    """Several deliveries failed post-write verification; each keeps its message."""

    def __init__(self, messages: List[str]):
        super().__init__(
            f"{messages[0]} (and {len(messages) - 1} more mismatching text item(s))"
        )
        self.messages = list(messages)


class _SerializedTextItemMismatch(RuntimeError):
    """Post-write verification failed for identifiable text items only."""

    def __init__(self, message: str, forced_text_rungs: Dict[str, Tuple[int, str]]):
        super().__init__(message)
        self.forced_text_rungs = forced_text_rungs


# Owner decision 2026-09-19: one text item whose delivery cannot be verified
# degrades (raster patch -> visible degraded TEXT -> reported drop); it never
# costs the sheet. The builder's failure classification is kept as evidence and
# the item stays verified=False, so certification gates still fail for the sheet.
_TEXT_DEGRADE_POLICY = "item_failure_never_costs_sheet"
_TEXT_DEGRADE_RUNG_RASTER, _TEXT_DEGRADE_RUNG_TEXT, _TEXT_DEGRADE_RUNG_DROP = 0, 1, 2
TEXT_ITEMS_DEGRADED_REPORT_LIMIT = 200


@dataclass
class DxfExportResult:
    output_path: str
    entity_count: int
    layer_count: int
    image_count: int
    text_fallbacks: List[Dict[str, Any]] = field(default_factory=list)
    delivered_text_entity_counts: Dict[str, int] = field(default_factory=dict)
    text_deliveries: List[Dict[str, Any]] = field(default_factory=list)
    final_rect_paints: List[Dict[str, Any]] = field(default_factory=list)
    searchable_text_companions: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _PositionedTranslationAnchor:
    """Immutable, process-local authority captured before DXF serialization."""

    source_id: str
    final_representation: str
    strategy: str
    entity_handles: Tuple[str, ...]
    export_page_translation: Tuple[float, float]
    pretranslation_character_origins: Tuple[Tuple[float, float], ...]
    pretranslation_character_quads: Tuple[
        Tuple[Tuple[float, float], ...], ...
    ]
    positioned_character_origins: Tuple[Tuple[float, float], ...]
    positioned_character_quads: Tuple[Tuple[Tuple[float, float], ...], ...]


_POSITIONED_SESSION_MINT_CAPABILITY = object()


class _PositionedVerificationSession:
    """Opaque, export-local authority over original positioned anchors.

    The persisted evidence and XDATA receipt remain consistency checks.  The
    nonserialized session, its unique capability, and the retained anchor
    objects supply the process-local authority used during the save/reopen
    transaction.  Construction is intentionally unavailable to callers.
    """

    __slots__ = (
        "__weakref__",
        "_anchors",
        "_anchor_capabilities",
        "_anchor_registry",
        "_anchor_views",
        "_mint_capability",
        "_original_session",
        "_retained_session_capability",
        "_session_capability",
    )

    def __init__(
        self,
        anchors: Mapping[str, _PositionedTranslationAnchor],
        *,
        _mint_capability: object,
    ) -> None:
        if _mint_capability is not _POSITIONED_SESSION_MINT_CAPABILITY:
            raise TypeError("positioned verification sessions are export-local")
        copied_anchors = dict(anchors)
        if any(
            not isinstance(source_id, str)
            or type(anchor) is not _PositionedTranslationAnchor
            for source_id, anchor in copied_anchors.items()
        ):
            raise RuntimeError("positioned verification anchor registry changed")
        anchor_capabilities = {
            source_id: object() for source_id in copied_anchors
        }
        anchor_registry = {
            source_id: (anchor, anchor_capabilities[source_id])
            for source_id, anchor in copied_anchors.items()
        }
        anchor_views = {
            source_id: replace(anchor)
            for source_id, anchor in copied_anchors.items()
        }
        session_capability = object()
        object.__setattr__(self, "_anchors", MappingProxyType(copied_anchors))
        object.__setattr__(
            self,
            "_anchor_capabilities",
            MappingProxyType(dict(anchor_capabilities)),
        )
        object.__setattr__(
            self,
            "_anchor_registry",
            MappingProxyType(dict(anchor_registry)),
        )
        object.__setattr__(
            self,
            "_anchor_views",
            MappingProxyType(anchor_views),
        )
        object.__setattr__(self, "_mint_capability", _mint_capability)
        object.__setattr__(self, "_session_capability", session_capability)
        object.__setattr__(
            self,
            "_retained_session_capability",
            session_capability,
        )
        object.__setattr__(self, "_original_session", self)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("positioned verification sessions are immutable")

    def __copy__(self) -> _PositionedVerificationSession:
        copied = object.__new__(type(self))
        for name in self.__slots__:
            if name == "__weakref__":
                continue
            object.__setattr__(copied, name, getattr(self, name))
        return copied

    def __deepcopy__(self, memo: Dict[int, object]) -> _PositionedVerificationSession:
        del memo
        return self.__copy__()

    @property
    def anchors(self) -> Mapping[str, _PositionedTranslationAnchor]:
        """Return read-only diagnostic copies, never authoritative aliases."""

        return self._anchor_views


@dataclass(frozen=True)
class _IssuedPositionedSessionAuthority:
    session_capability: object
    canonical_anchors: Mapping[str, _PositionedTranslationAnchor]
    anchor_registry: Mapping[
        str,
        Tuple[_PositionedTranslationAnchor, object],
    ]


_ISSUED_POSITIONED_SESSIONS: weakref.WeakKeyDictionary[
    _PositionedVerificationSession,
    _IssuedPositionedSessionAuthority,
] = weakref.WeakKeyDictionary()


def _positioned_session_anchor_map(
    session: object,
    *,
    positioned_roster: set[str],
) -> Mapping[str, _PositionedTranslationAnchor]:
    """Authenticate one opaque session and its exact original anchor objects."""

    failure = "serialized text delivery authoritative session changed"
    if type(session) is not _PositionedVerificationSession:
        raise RuntimeError(failure)
    try:
        issued_authority = _ISSUED_POSITIONED_SESSIONS.get(session)
        anchors = session._anchors
        capabilities = session._anchor_capabilities
        registry = session._anchor_registry
        valid_session_identity = bool(
            session._mint_capability is _POSITIONED_SESSION_MINT_CAPABILITY
            and session._original_session is session
            and session._session_capability
            is session._retained_session_capability
        )
        exact_roster = bool(
            set(anchors) == positioned_roster
            and set(capabilities) == positioned_roster
            and set(registry) == positioned_roster
            and issued_authority is not None
            and set(issued_authority.canonical_anchors) == positioned_roster
            and set(issued_authority.anchor_registry) == positioned_roster
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError(failure) from exc
    if not valid_session_identity or not exact_roster:
        raise RuntimeError(failure)
    if issued_authority.session_capability is not session._session_capability:
        raise RuntimeError(failure)
    authenticated_anchors: Dict[str, _PositionedTranslationAnchor] = {}
    for source_id in positioned_roster:
        try:
            anchor = anchors[source_id]
            retained_anchor, retained_capability = registry[source_id]
            issued_anchor, issued_capability = issued_authority.anchor_registry[
                source_id
            ]
            canonical_anchor = issued_authority.canonical_anchors[source_id]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(failure) from exc
        if (
            type(anchor) is not _PositionedTranslationAnchor
            or anchor is not retained_anchor
            or anchor is not issued_anchor
            or anchor != canonical_anchor
            or capabilities[source_id] is not retained_capability
            or retained_capability is not issued_capability
        ):
            raise RuntimeError(failure)
        authenticated_anchors[source_id] = replace(canonical_anchor)
    return MappingProxyType(authenticated_anchors)


def _normalized_text_mode(text_mode: str) -> str:
    mode = str(text_mode or "text").strip().lower()
    if mode == "text3d":
        return "3d_text"
    if mode == "native_text":
        return "text"
    return mode


def _translate_positioned_text_for_page(text: Any, dy: float) -> Any:
    """Clone one text item into its stacked-page model coordinates.

    PDF/source fields remain immutable.  Only model-space insertion, bbox, and the
    complete individually positioned character target geometry receive the page
    translation.  Malformed layout evidence is preserved for the text builder's
    existing fail-closed validator rather than being partially rewritten here.
    """

    offset_y = float(dy)
    raw_layout = getattr(text, "source_char_layout", ())
    source_layout = raw_layout if isinstance(raw_layout, tuple) else ()
    translated_layout = raw_layout
    if bool(getattr(text, "requires_individual_positioning", False)) and source_layout:
        try:
            layout_shape_valid = bool(
                all(isinstance(character, TextCharLayout) for character in source_layout)
                and all(
                    len(tuple(character.target_origin)) == 2
                    for character in source_layout
                )
                and all(
                    len(tuple(character.target_quad)) == 4
                    and all(len(tuple(point)) == 2 for point in character.target_quad)
                    for character in source_layout
                )
            )
            if layout_shape_valid:
                translated_layout = tuple(
                    replace(
                        character,
                        target_origin=(
                            float(character.target_origin[0]),
                            float(character.target_origin[1]) + offset_y,
                        ),
                        target_quad=tuple(
                            (float(point[0]), float(point[1]) + offset_y)
                            for point in character.target_quad
                        ),
                    )
                    for character in source_layout
                )
        except (TypeError, ValueError, OverflowError):
            # Preserve malformed evidence byte-for-byte in spirit: the downstream
            # positioned-layout validator owns the terminal refusal and must never
            # receive an exporter-repaired container or field shape.
            translated_layout = raw_layout

    return replace(
        text,
        insertion=(
            float(text.insertion[0]),
            float(text.insertion[1]) + offset_y,
        ),
        bbox=(
            (
                float(text.bbox[0]),
                float(text.bbox[1]) + offset_y,
                float(text.bbox[2]),
                float(text.bbox[3]) + offset_y,
            )
            if text.bbox
            else None
        ),
        source_char_layout=translated_layout,
    )


def _points_translate_exactly(
    before: Sequence[float],
    after: Sequence[float],
    *,
    dx: float,
    dy: float,
) -> bool:
    try:
        before_xy = tuple(float(value) for value in before)
        after_xy = tuple(float(value) for value in after)
    except (TypeError, ValueError):
        return False
    return bool(
        len(before_xy) == len(after_xy) == 2
        and all(math.isfinite(value) for value in (*before_xy, *after_xy, dx, dy))
        and math.isclose(after_xy[0], before_xy[0] + dx, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(after_xy[1], before_xy[1] + dy, rel_tol=0.0, abs_tol=1e-12)
    )


def _positioned_proof_fields(
    representation: str,
    *,
    include_translation: bool,
    include_receipt: bool,
) -> frozenset[str]:
    if representation not in {"glyphs", "geometry"}:
        raise ValueError(f"unsupported positioned representation: {representation!r}")
    fields = set(_POSITIONED_LAYOUT_PROOF_FIELDS)
    if representation == "geometry":
        fields.update(_POSITIONED_GEOMETRY_PROOF_FIELDS)
    if include_translation:
        fields.update(_POSITIONED_PAGE_TRANSLATION_PROOF_FIELDS)
    if include_receipt:
        fields.update(_POSITIONED_RECEIPT_PROOF_FIELDS)
    return frozenset(fields)


def _positioned_proof_schema_is_complete(
    evidence: Dict[str, Any],
    representation: str,
    *,
    include_translation: bool,
    include_receipt: bool,
) -> bool:
    try:
        required = _positioned_proof_fields(
            representation,
            include_translation=include_translation,
            include_receipt=include_receipt,
        )
    except ValueError:
        return False
    expected_positioned = {
        field for field in required if field.startswith("positioned_")
    }
    actual_positioned = {
        str(field) for field in evidence if str(field).startswith("positioned_")
    }
    if not required.issubset(evidence) or actual_positioned != expected_positioned:
        return False
    try:
        character_count = int(evidence["positioned_character_count"])
        sequence_fields = (
            "positioned_character_text",
            "positioned_source_glyph_ids",
            "positioned_source_glyph_names",
            "positioned_character_origins",
            "positioned_character_quads",
            "positioned_character_local_bboxes",
            "positioned_character_rotations",
        )
        sequence_lengths = [len(evidence[field]) for field in sequence_fields]
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        character_count > 0
        and all(length == character_count for length in sequence_lengths)
        and evidence.get("positioned_layout_bijection_verified") is True
        and evidence.get("positioned_source_font_glyphs_verified") is True
        and evidence.get("positioned_visible_geometry_fill_only") is True
        and evidence.get("positioned_contour_entities_omitted") is True
    )


def _positioned_translation_receipt_digest(
    *,
    evidence: Dict[str, Any],
    source_id: str,
    representation: str,
    strategy: str,
    entity_handles: Sequence[str],
) -> str:
    bound_fields = _positioned_proof_fields(
        representation,
        include_translation=True,
        include_receipt=False,
    )
    payload = {
        "entity_handles": [str(handle) for handle in entity_handles],
        "evidence": {field: evidence[field] for field in sorted(bound_fields)},
        "final_representation": str(representation),
        "schema": _POSITIONED_TRANSLATION_RECEIPT_SCHEMA,
        "source_id": str(source_id),
        "strategy": str(strategy),
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(
        b"BCS_POSITIONED_TRANSLATION_RECEIPT_V1\x00" + canonical
    ).hexdigest()


def _bind_positioned_page_translation(
    delivery: TextDeliveryResult,
    source_text: Any,
    placed_text: Any,
    *,
    dy: float,
    doc: Any,
) -> Optional[_PositionedTranslationAnchor]:
    """Bind page translation evidence to every main entity as exact XDATA."""

    if not bool(getattr(source_text, "requires_individual_positioning", False)):
        return None
    verified_attempts = [
        attempt for attempt in delivery.attempts if attempt.outcome == "verified"
    ]
    if len(verified_attempts) != 1:
        raise RuntimeError(
            f"{delivery.source_id}: positioned page translation has no unique proof"
        )
    evidence = verified_attempts[0].evidence
    if not evidence.get("positioned_character_origins") or not evidence.get(
        "positioned_character_quads"
    ):
        # Some ordinary PDF text carries source character layout for downstream
        # fallbacks but does not use the positioned-fraction renderer.  Its final
        # strategy has no positioned-layout evidence to bind here.
        return None
    before_layout = tuple(getattr(source_text, "source_char_layout", ()) or ())
    after_layout = tuple(getattr(placed_text, "source_char_layout", ()) or ())
    if (
        not before_layout
        or len(before_layout) != len(after_layout)
        or not all(isinstance(value, TextCharLayout) for value in (*before_layout, *after_layout))
    ):
        raise RuntimeError(f"{delivery.source_id}: positioned page translation changed")

    dx = 0.0
    offset_y = float(dy)
    before_origins = [list(map(float, value.target_origin)) for value in before_layout]
    after_origins = [list(map(float, value.target_origin)) for value in after_layout]
    before_quads = [
        [list(map(float, point)) for point in value.target_quad]
        for value in before_layout
    ]
    after_quads = [
        [list(map(float, point)) for point in value.target_quad]
        for value in after_layout
    ]
    emitted_origins = list(evidence.get("positioned_character_origins") or [])
    emitted_quads = list(evidence.get("positioned_character_quads") or [])
    translation_verified = bool(
        len(emitted_origins) == len(after_origins) == len(before_origins)
        and len(emitted_quads) == len(after_quads) == len(before_quads)
        and all(
            _points_translate_exactly(before, after, dx=dx, dy=offset_y)
            for before, after in zip(before_origins, after_origins, strict=True)
        )
        and all(
            len(before_quad) == len(after_quad) == len(emitted_quad) == 4
            and all(
                _points_translate_exactly(before, after, dx=dx, dy=offset_y)
                for before, after in zip(before_quad, after_quad, strict=True)
            )
            for before_quad, after_quad, emitted_quad in zip(
                before_quads,
                after_quads,
                emitted_quads,
                strict=True,
            )
        )
        and emitted_origins == after_origins
        and emitted_quads == after_quads
    )
    evidence.update(
        {
            "export_page_translation": [dx, offset_y],
            "positioned_pretranslation_character_origins": before_origins,
            "positioned_pretranslation_character_quads": before_quads,
            "positioned_export_translation_verified": translation_verified,
        }
    )
    if not translation_verified:
        raise RuntimeError(f"{delivery.source_id}: positioned page translation changed")

    representation = str(delivery.final_representation or "")
    strategy = str(verified_attempts[0].strategy or "")
    if not _positioned_proof_schema_is_complete(
        evidence,
        representation,
        include_translation=True,
        include_receipt=False,
    ):
        raise RuntimeError(f"{delivery.source_id}: positioned proof schema changed")
    handles = [str(handle) for handle in delivery.entity_handles]
    if not handles or len(handles) != len(set(handles)):
        raise RuntimeError(f"{delivery.source_id}: positioned receipt has invalid handles")
    anchor = _PositionedTranslationAnchor(
        source_id=str(delivery.source_id),
        final_representation=representation,
        strategy=strategy,
        entity_handles=tuple(handles),
        export_page_translation=(dx, offset_y),
        pretranslation_character_origins=tuple(
            tuple(map(float, point)) for point in before_origins
        ),
        pretranslation_character_quads=tuple(
            tuple(tuple(map(float, point)) for point in quad)
            for quad in before_quads
        ),
        positioned_character_origins=tuple(
            tuple(map(float, point)) for point in after_origins
        ),
        positioned_character_quads=tuple(
            tuple(tuple(map(float, point)) for point in quad)
            for quad in after_quads
        ),
    )
    try:
        receipt_digest = _positioned_translation_receipt_digest(
            evidence=evidence,
            source_id=str(delivery.source_id),
            representation=representation,
            strategy=strategy,
            entity_handles=handles,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{delivery.source_id}: positioned receipt could not be canonicalized"
        ) from exc
    evidence.update(
        {
            "positioned_translation_receipt_schema": (
                _POSITIONED_TRANSLATION_RECEIPT_SCHEMA
            ),
            "positioned_translation_receipt_sha256": receipt_digest,
        }
    )
    if not doc.appids.has_entry(_POSITIONED_TRANSLATION_RECEIPT_APPID):
        doc.appids.add(_POSITIONED_TRANSLATION_RECEIPT_APPID)
    receipt_tags = [
        (1000, _POSITIONED_TRANSLATION_RECEIPT_SCHEMA),
        (1000, receipt_digest),
    ]
    for handle in handles:
        entity = doc.entitydb.get(handle)
        if entity is None or not getattr(entity, "is_alive", True):
            raise RuntimeError(
                f"{delivery.source_id}: positioned receipt entity is missing"
            )
        entity.set_xdata(_POSITIONED_TRANSLATION_RECEIPT_APPID, receipt_tags)
    return anchor


def _verify_positioned_page_translation_evidence(
    evidence: Dict[str, Any],
    source_id: str,
    *,
    representation: str,
    strategy: str,
    entity_handles: Sequence[str],
) -> str:
    """Validate closed positioned evidence and return its canonical receipt."""

    if not _POSITIONED_PAGE_TRANSLATION_PROOF_FIELDS.issubset(
        evidence
    ) or evidence.get("positioned_export_translation_verified") is not True:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned page translation changed"
        )
    if evidence.get("positioned_visible_geometry_fill_only") is not True:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned geometry contract changed"
        )
    if not _positioned_proof_schema_is_complete(
        evidence,
        representation,
        include_translation=True,
        include_receipt=True,
    ):
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned proof schema changed"
        )
    try:
        translation = tuple(float(value) for value in evidence["export_page_translation"])
        before_origins = list(evidence["positioned_pretranslation_character_origins"])
        before_quads = list(evidence["positioned_pretranslation_character_quads"])
        after_origins = list(evidence["positioned_character_origins"])
        after_quads = list(evidence["positioned_character_quads"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned page translation changed"
        ) from exc
    translation_ok = bool(
        len(translation) == 2
        and len(before_origins) == len(after_origins) > 0
        and len(before_quads) == len(after_quads) == len(before_origins)
        and all(
            _points_translate_exactly(
                before,
                after,
                dx=translation[0],
                dy=translation[1],
            )
            for before, after in zip(before_origins, after_origins, strict=True)
        )
        and all(
            len(before_quad) == len(after_quad) == 4
            and all(
                _points_translate_exactly(
                    before,
                    after,
                    dx=translation[0],
                    dy=translation[1],
                )
                for before, after in zip(before_quad, after_quad, strict=True)
            )
            for before_quad, after_quad in zip(before_quads, after_quads, strict=True)
        )
    )
    if not translation_ok:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned page translation changed"
        )
    try:
        expected_receipt = _positioned_translation_receipt_digest(
            evidence=evidence,
            source_id=source_id,
            representation=representation,
            strategy=strategy,
            entity_handles=entity_handles,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned receipt changed"
        ) from exc
    if (
        evidence.get("positioned_translation_receipt_schema")
        != _POSITIONED_TRANSLATION_RECEIPT_SCHEMA
        or evidence.get("positioned_translation_receipt_sha256") != expected_receipt
    ):
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned receipt changed"
        )
    return expected_receipt


def _verify_positioned_translation_entity_receipts(
    doc: Any,
    entities: Sequence[Any],
    *,
    source_id: str,
    expected_digest: str,
) -> None:
    if not doc.appids.has_entry(_POSITIONED_TRANSLATION_RECEIPT_APPID):
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned receipt changed"
        )
    expected_tags = [
        (1000, _POSITIONED_TRANSLATION_RECEIPT_SCHEMA),
        (1000, expected_digest),
    ]
    for entity in entities:
        try:
            actual_tags = [
                (int(tag.code), str(tag.value))
                for tag in entity.get_xdata(_POSITIONED_TRANSLATION_RECEIPT_APPID)
            ]
        except ezdxf.DXFValueError as exc:
            raise RuntimeError(
                f"serialized text delivery {source_id}: positioned receipt changed"
            ) from exc
        if actual_tags != expected_tags:
            raise RuntimeError(
                f"serialized text delivery {source_id}: positioned receipt changed"
            )


def _verify_positioned_authoritative_anchor(
    anchor: object,
    evidence: Dict[str, Any],
    *,
    source_id: str,
    representation: str,
    strategy: str,
    entity_handles: Sequence[str],
) -> None:
    """Compare mutable delivery evidence with the pre-serialization authority."""

    if type(anchor) is not _PositionedTranslationAnchor:
        raise RuntimeError(
            f"serialized text delivery {source_id}: authoritative anchor changed"
        )
    try:
        evidence_translation = tuple(
            float(value) for value in evidence["export_page_translation"]
        )
        evidence_before_origins = tuple(
            tuple(float(value) for value in point)
            for point in evidence["positioned_pretranslation_character_origins"]
        )
        evidence_before_quads = tuple(
            tuple(tuple(float(value) for value in point) for point in quad)
            for quad in evidence["positioned_pretranslation_character_quads"]
        )
        evidence_after_origins = tuple(
            tuple(float(value) for value in point)
            for point in evidence["positioned_character_origins"]
        )
        evidence_after_quads = tuple(
            tuple(tuple(float(value) for value in point) for point in quad)
            for quad in evidence["positioned_character_quads"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned page translation changed"
        ) from exc
    dx, dy = anchor.export_page_translation
    anchor_translation_valid = bool(
        len(anchor.pretranslation_character_origins)
        == len(anchor.positioned_character_origins)
        > 0
        and len(anchor.pretranslation_character_quads)
        == len(anchor.positioned_character_quads)
        == len(anchor.pretranslation_character_origins)
        and all(
            _points_translate_exactly(before, after, dx=dx, dy=dy)
            for before, after in zip(
                anchor.pretranslation_character_origins,
                anchor.positioned_character_origins,
                strict=True,
            )
        )
        and all(
            len(before_quad) == len(after_quad) == 4
            and all(
                _points_translate_exactly(before, after, dx=dx, dy=dy)
                for before, after in zip(before_quad, after_quad, strict=True)
            )
            for before_quad, after_quad in zip(
                anchor.pretranslation_character_quads,
                anchor.positioned_character_quads,
                strict=True,
            )
        )
    )
    identity_valid = bool(
        anchor.source_id == source_id
        and anchor.final_representation == representation
        and anchor.strategy == strategy
        and anchor.entity_handles == tuple(map(str, entity_handles))
    )
    evidence_valid = bool(
        evidence_translation == anchor.export_page_translation
        and evidence_before_origins == anchor.pretranslation_character_origins
        and evidence_before_quads == anchor.pretranslation_character_quads
        and evidence_after_origins == anchor.positioned_character_origins
        and evidence_after_quads == anchor.positioned_character_quads
    )
    if not anchor_translation_valid or not identity_valid:
        raise RuntimeError(
            f"serialized text delivery {source_id}: authoritative anchor changed"
        )
    if not evidence_valid:
        raise RuntimeError(
            f"serialized text delivery {source_id}: positioned page translation changed"
        )


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
        next(iter(final_modes)) if len(final_modes) == 1 else ("mixed" if final_modes else "none")
    )
    fallback_count = sum(bool(item.get("fallback_used")) for item in items)
    entity_count = sum(len(item.get("entity_handles") or []) for item in items)
    failures = [
        str(item.get("source_id") or "unknown")
        for item in items
        if item.get("verified") is not True or not item.get("final_representation")
    ]
    degraded = degraded_text_items(items)
    return {
        "requested": requested_mode,
        "delivered": delivered,
        "verified": not failures,
        "fallback_used": fallback_count > 0,
        "fallback_item_count": fallback_count,
        "item_count": len(items),
        "entity_count": entity_count,
        "failed_source_ids": failures,
        "degraded_item_count": degraded["total"],
        "degraded_items": degraded["items"],
        "degraded_items_truncated": degraded["truncated"],
        "report_path": str(report_path),
    }


def degraded_text_items(
    deliveries: Sequence[Any],
    *,
    limit: int = TEXT_ITEMS_DEGRADED_REPORT_LIMIT,
) -> Dict[str, Any]:
    """List every degraded or dropped text item, loudly and bounded.

    ``delivered`` is ``raster``, ``text`` (the visible degraded TEXT) or
    ``none`` (dropped). ``total`` counts all of them; ``items`` is capped.
    ``fallbacks`` groups ALL of them by requested/delivered/reason code and
    ``dropped`` counts the items that are not in the drawing at all. An entry
    carries ``no_visible_ink`` only when its raster rung found that the source
    item paints nothing, so no patch was made and nothing visible is missing.
    """

    records = [
        item
        for item in deliveries or []
        if isinstance(item, dict) and item.get("degraded") is True
    ]

    def delivered(item: Dict[str, Any]) -> str:
        if item.get("dropped") is True:
            return "none"
        return str(item.get("final_representation") or "none")

    def no_visible_ink(item: Dict[str, Any]) -> Dict[str, bool]:
        last = (item.get("attempts") or [{}])[-1]
        omitted = (
            isinstance(last, dict)
            and last.get("strategy") == "verified_source_zero_ink_omission"
        )
        return {"no_visible_ink": True} if omitted else {}

    fallbacks: List[Dict[str, Any]] = []
    for item in records:
        _append_text_fallback(
            fallbacks,
            requested=str(item.get("requested_representation") or ""),
            delivered=delivered(item),
            reason=str(item.get("fallback_reason_code") or ""),
            count=1,
        )
    return {
        "items": [
            {
                "source_id": str(item.get("source_id") or ""),
                "page": int(item.get("source_page_number") or 0),
                "text": str(item.get("source_text") or ""),
                "reason": str(item.get("degrade_reason") or ""),
                "reason_code": str(item.get("fallback_reason_code") or ""),
                "proof_class": str(item.get("proof_class") or ""),
                "delivered": delivered(item),
                **no_visible_ink(item),
            }
            for item in records[: max(0, int(limit))]
        ],
        "total": len(records),
        "truncated": len(records) > max(0, int(limit)),
        "dropped": sum(1 for item in records if item.get("dropped") is True),
        "fallbacks": fallbacks,
    }


def searchable_text_companions(
    deliveries: Sequence[Any],
    *,
    enabled: bool,
) -> Dict[str, Any]:
    """Count the hidden search-text companions. They certify nothing visual.

    ``failed`` and ``mismatch`` are warnings; ``not_representable`` is a string
    native TEXT cannot carry literally, so no companion was attempted.
    """

    records = [
        item["search_text"]
        for item in deliveries or []
        if isinstance(item, dict) and isinstance(item.get("search_text"), dict)
    ]
    counts = {
        status: sum(1 for record in records if record.get("status") == status)
        for status in ("written", "not_representable", "failed", "mismatch")
    }
    return {
        "enabled": bool(enabled),
        **counts,
        "layers": sorted(
            {
                str(record.get("layer") or "")
                for record in records
                if record.get("status") == "written"
            }
        ),
    }


SEARCH_TEXT_SEE_IMPORT_REPORT = "See searchable_text_companions in the import report."


def searchable_text_warning_line(
    companions: Mapping[str, Any],
    see: str = SEARCH_TEXT_SEE_IMPORT_REPORT,
) -> str:
    """One warning line when a companion failed or mismatched, else ``''``."""

    lost = int(companions.get("failed") or 0) + int(companions.get("mismatch") or 0)
    if not lost:
        return ""
    return (
        f"Warning: {lost} hidden search-text companion(s) could not be written or "
        f"verified; the drawing itself is unaffected. {see}"
    )


def bounded_traceback(
    exc: BaseException,
    *,
    frames: int = 8,
    max_chars: int = 4000,
    max_message_chars: int = 500,
) -> List[str]:
    """The innermost frames of a failure, bounded: the raise site stays recoverable.

    Each part (one frame, or the exception message) is bounded by itself. The
    message is the LAST part, so a tail cut alone would spend the whole budget on
    a very long message and lose every frame.
    """

    part_limit = max(4, int(max_message_chars))
    text = "".join(
        part if len(part) <= part_limit else f"{part[: part_limit - 3]}...\n"
        for part in traceback.format_exception(
            type(exc), exc, exc.__traceback__, limit=-abs(int(frames))
        )
    )
    return text[-max(0, int(max_chars)):].splitlines()


def _one_line(value: Any, limit: int) -> str:
    """One bounded console line: control characters (ESC, BEL, NUL, BS ...) and
    whitespace runs (newlines included) become one space; long values are cut."""

    text = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char
        for char in str(value if value is not None else "")
    )
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def degraded_text_item_lines(
    items: Sequence[Dict[str, Any]],
    total: int,
    *,
    limit: int = 20,
) -> List[str]:
    """One readable warning line per degraded item, then ``... and N more``.

    Exactly one bounded physical line each: the source text and the reason may
    be long or span lines, and the report keeps them in full.
    """

    outcomes = {
        "raster": "delivered as an unverified raster patch",
        "text": "delivered as visible degraded TEXT",
        "none": "DROPPED from the drawing",
    }
    # ASCII-escaped so a console codepage can never turn the warning into a crash.
    lines = [
        "Warning: text item {source_id} (page {page}, {text!r}) could not be "
        "verified [{proof_class}: {reason}]; {outcome}.".format(
            source_id=_one_line(item.get("source_id"), 80),
            page=item.get("page"),
            text=_one_line(item.get("text"), 80),
            proof_class=_one_line(item.get("proof_class"), 40),
            reason=_one_line(item.get("reason"), 200),
            outcome=(
                # The raster rung made no patch: never call that a delivered patch.
                "the source item has no visible ink, so nothing was drawn"
                if item.get("no_visible_ink") is True
                else outcomes.get(str(item.get("delivered")), "not delivered")
            ),
        )
        .encode("ascii", "backslashreplace")
        .decode("ascii")
        for item in list(items)[: max(0, int(limit))]
    ]
    remaining = int(total) - len(lines)
    if remaining > 0:
        lines.append(f"... and {remaining} more degraded text item(s); see the import report.")
    return lines


def _text_proof_class(delivery: TextDeliveryResult) -> str:
    """Name the builder's own, unchanged failure classification for the report."""

    attempts = list(delivery.attempts)
    strategies = {attempt.strategy for attempt in attempts}
    if "positioned_fraction_layout_validation" in strategies:
        return "invalid_layout"
    # Every rung ending "impossible" is not proof by itself: the builder refuses
    # to call a font failure proven when it may be our runtime's (helper
    # unavailable, proof not bound to the item). Only its own authorization, or
    # its R12 colour proof, makes the item proven impossible.
    if (
        attempts
        and all(attempt.outcome == "impossible" for attempt in attempts)
        and (
            delivery.terminal_fallback_authorized
            or "positioned_fraction_r12_color_validation" in strategies
        )
    ):
        return "proven_impossible"
    return "unproven_failure"


def _fallback_reason_code(
    delivery: TextDeliveryResult,
    degraded_proof_class: str = "",
) -> str:
    # A rescued item must never score like a proven, verified hop.
    if degraded_proof_class == "proven_impossible":
        return "item_degraded_after_proven_impossibility"
    if degraded_proof_class:
        return "item_degraded_after_unproven_failure"
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


def _verification_keep_handles(
    text_deliveries: List[Dict[str, Any]],
    image_expectations: List["_SerializedImageExpectation"],
) -> set[str]:
    """Every entity handle the serialized-delivery verification may address."""

    handles: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("handles") and isinstance(child, (list, tuple)):
                    handles.update(str(item) for item in child if str(item))
                elif key.endswith("handle") and isinstance(child, (str, int)):
                    handles.add(str(child))
                else:
                    collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    for delivery in text_deliveries:
        collect(delivery)
    for expected in image_expectations:
        handles.add(str(expected.image_handle))
        handles.add(str(expected.image_def_handle))
    return handles


def _known_cap_height_ratio(delivery: TextDeliveryResult) -> Optional[float]:
    """The source font's cap-height ratio, when a builder rung resolved it."""

    for attempt in delivery.attempts:
        ratio = attempt.evidence.get("source_cap_height_ratio")
        if isinstance(ratio, (int, float)) and math.isfinite(ratio) and ratio > 0.0:
            return float(ratio)
    return None


def _write_search_text_companions(
    doc: Any,
    msp: Any,
    pending: Sequence[Tuple[Any, ...]],
    *,
    opts: "DxfExportOptions",
    is_r12: bool,
    source_paint_keys: Dict[str, Any],
) -> None:
    """Write one hidden TEXT per settled item whose string is not in the file.

    Owner decision 2026-09-19: LibreCAD output is searchable. The v1.0.81
    guarantee stands -- a substituted LFF font is never certified as delivered
    Text -- so the companion certifies nothing: it lives on the FROZEN,
    non-plotting layer ``P###_TEXT_SEARCH`` and touches no delivery field, count
    or bucket. It never raises; a failure costs that one companion, reported.
    """

    written_per_layer: Dict[str, int] = {}
    for record, text_item, cap_height_ratio, page_number, paint_key in pending:
        content = str(getattr(text_item, "text", "") or "")
        if not content.strip() or record.get("final_representation") in {
            "text", "labels", "3d_text",
        }:
            # Whitespace, or a visible TEXT: the string is already in the file.
            record["search_text"] = {
                "status": "not_needed", "handle": None, "layer": None, "content": content,
            }
            continue
        layer = _layer_name(page_number, "TEXT_SEARCH", None, opts)
        if not layer.endswith("TEXT_SEARCH"):
            layer = f"{layer}_TEXT_SEARCH"  # never freeze a layer that is shared
        try:
            if layer not in written_per_layer:
                if doc.layers.has_entry(layer):
                    raise ValueError(f"layer {layer} already belongs to the drawing")
                _ensure_layer(doc, layer, None)
                entry = doc.layers.get(layer)
                entry.freeze()
                if not is_r12:
                    entry.dxf.plot = 0  # R12 has no plot flag
                written_per_layer[layer] = 0
            search = dict(
                _write_search_text_companion(
                    text_item, msp, layer, is_r12=is_r12, cap_height_ratio=cap_height_ratio
                )
            )
            if search.get("status") == "written":
                # Mandatory: apply_image_paint_order refuses a modelspace entity
                # without a paint key, and that would cost the whole sheet.
                source_paint_keys[str(search["handle"])] = paint_key
                written_per_layer[layer] += 1
        except Exception as exc:  # noqa: BLE001 - a companion never costs the sheet
            search = {
                "status": "failed", "handle": None, "layer": layer, "content": content,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        record["search_text"] = search
    for layer, written in written_per_layer.items():
        if not written:
            try:
                doc.layers.remove(layer)
            except Exception:  # noqa: BLE001 - an empty frozen layer is harmless
                pass


def _verify_serialized_search_text(doc: Any, deliveries: List[Dict[str, Any]]) -> None:
    """Soft post-write check of the hidden companions: never raises, never retries.

    A companion certifies nothing, so one that did not reach the file as written
    becomes ``mismatch`` (a warning) and the item keeps its own verified flag.
    """

    pre_r2007 = str(getattr(doc, "dxfversion", "") or "") < "AC1021"
    for delivery in deliveries:
        search = delivery.get("search_text")
        if not isinstance(search, dict) or search.get("status") != "written":
            continue
        try:
            native = doc.entitydb.get(str(search.get("handle") or ""))
            if native is None or not getattr(native, "is_alive", True):
                raise ValueError("companion TEXT is missing from the written file")
            layer = doc.layers.get(str(search.get("layer") or ""))
            actual = str(native.dxf.text)
            if pre_r2007:
                # cp1252 files carry other characters as \U+XXXX escapes.
                actual = decode_dxf_unicode(actual)
            if (
                native.dxftype() != "TEXT"
                or actual != str(search.get("content") or "")
                or str(native.dxf.layer) != str(search.get("layer") or "")
                or not layer.is_frozen()
            ):
                raise ValueError("companion TEXT content, layer or type changed")
        except Exception as exc:  # noqa: BLE001 - a companion never costs the sheet
            search["status"] = "mismatch"
            search["reason"] = f"{type(exc).__name__}: {exc}"


def _serialized_entity(doc: Any, handle: str, source_id: str) -> Any:
    entity = doc.entitydb.get(str(handle))
    if entity is None or not getattr(entity, "is_alive", True):
        raise RuntimeError(f"serialized text delivery {source_id}: missing live handle {handle}")
    return entity


def _verify_serialized_text_deliveries(
    doc: Any,
    deliveries: List[Dict[str, Any]],
    *,
    trusted_positioned_session: _PositionedVerificationSession,
) -> None:
    """Reconcile accepted evidence against the candidate and opaque authority.

    Positioned translation authority is deliberately process-local and is never
    reconstructed from delivery evidence or DXF XDATA.  A later independent
    process cannot reproduce this identity capability and must fail closed unless
    it receives a separately authenticated (for example, externally signed)
    anchor ledger.  XDATA alone is consistency evidence, not authenticity.
    """

    positioned_roster: set[str] = set()
    for delivery in deliveries:
        source_id = str(delivery.get("source_id") or "")
        verified_attempts = [
            attempt
            for attempt in delivery.get("attempts") or []
            if attempt.get("outcome") == "verified"
        ]
        if len(verified_attempts) != 1:
            continue
        attempt = verified_attempts[0]
        evidence = dict(attempt.get("evidence") or {})
        if (
            str(attempt.get("strategy") or "")
            == "positioned_source_glyph_outlines"
            or "export_page_translation" in evidence
            or any(str(key).startswith("positioned_") for key in evidence)
        ):
            positioned_roster.add(source_id)
    anchor_map = _positioned_session_anchor_map(
        trusted_positioned_session,
        positioned_roster=positioned_roster,
    )

    expected_types = {
        "text": {"TEXT"},
        "labels": {"TEXT", "MTEXT"},
        "glyphs": {"INSERT"},
        "geometry": {"LWPOLYLINE", "POLYLINE", "SOLID"},
        "raster": {"IMAGE"},
        "3d_text": {"TEXT"},
    }
    reopened_lff_resolutions: Dict[str, Any] = {}
    # One verification pass reads an immutable re-opened document, and a block name
    # maps to exactly one definition in it -- so each definition is hashed once per
    # pass and every item that references it is checked against that hash. (Before:
    # 130 definitions were hashed 3,599 times on a 979-item drawing.)
    definition_fingerprints: Dict[str, str] = {}
    source_ids: set[str] = set()
    main_handles: set[str] = set()
    serialized_modelspace = doc.modelspace()
    modelspace_handle_counts: Dict[str, int] = {}
    for modelspace_entity in serialized_modelspace:
        modelspace_handle = str(modelspace_entity.dxf.handle or "")
        modelspace_handle_counts[modelspace_handle] = (
            modelspace_handle_counts.get(modelspace_handle, 0) + 1
        )
    modelspace_record = getattr(serialized_modelspace, "block_record", None)
    expected_modelspace_owner = str(
        getattr(getattr(modelspace_record, "dxf", None), "handle", "") or ""
    )

    def verify_delivery(delivery: Dict[str, Any]) -> None:
        source_id = str(delivery.get("source_id") or "")
        representation = str(delivery.get("final_representation") or "")
        if not source_id or source_id in source_ids:
            raise RuntimeError(
                f"serialized text delivery has invalid or duplicate source id: {source_id!r}"
            )
        source_ids.add(source_id)
        degraded = delivery.get("degraded") is True
        if degraded and delivery.get("dropped") is True:
            # A dropped item is reported, not delivered: it must own nothing.
            attempts = [
                attempt
                for attempt in delivery.get("attempts") or []
                if isinstance(attempt, dict)
            ]
            if (
                representation
                or any(
                    owner.get(key)
                    for owner in (delivery, *attempts)
                    for key in (
                        "entity_handles",
                        "support_entity_handles",
                        "referenced_entity_handles",
                    )
                )
                or any(
                    modelspace_handle_counts.get(str(handle), 0)
                    for attempt in attempts
                    for handle in attempt.get("created_entity_handles") or []
                )
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: dropped item owns live handles"
                )
            return
        if degraded and representation == "text":
            # The visible degraded TEXT certifies nothing visual; what must hold
            # is that the exact source string reached the file where it was put.
            entity_handles = [str(value) for value in delivery.get("entity_handles") or []]
            if len(entity_handles) != 1 or main_handles.intersection(entity_handles):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: missing or duplicate main handles"
                )
            main_handles.update(entity_handles)
            native = _serialized_entity(doc, entity_handles[0], source_id)
            evidence = dict(
                ((delivery.get("attempts") or [{}])[-1] or {}).get("evidence") or {}
            )
            if (
                native.dxftype() != "TEXT"
                or modelspace_handle_counts.get(entity_handles[0], 0) != 1
                or str(native.dxf.text) != str(delivery.get("source_text") or "")
                or str(native.dxf.text) != str(evidence.get("delivered_content") or "")
                or str(native.dxf.layer) != str(evidence.get("layer") or "")
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: degraded text changed"
                )
            return
        if (
            delivery.get("verified") is not True and not degraded
        ) or representation not in expected_types:
            raise RuntimeError(
                f"serialized text delivery {source_id}: unverified final representation"
            )
        entity_handles = [str(value) for value in delivery.get("entity_handles") or []]
        support_handles = [str(value) for value in delivery.get("support_entity_handles") or []]
        referenced_handles = [
            str(value) for value in delivery.get("referenced_entity_handles") or []
        ]
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
        final_evidence = dict(final_attempt.get("evidence") or {})
        final_strategy = str(final_attempt.get("strategy") or "")
        positioned_delivery_evidence = bool(
            final_strategy == "positioned_source_glyph_outlines"
            or "export_page_translation" in final_evidence
            or any(str(key).startswith("positioned_") for key in final_evidence)
        )
        positioned_receipt_digest: Optional[str] = None
        if positioned_delivery_evidence:
            _verify_positioned_authoritative_anchor(
                anchor_map[source_id],
                final_evidence,
                source_id=source_id,
                representation=representation,
                strategy=final_strategy,
                entity_handles=entity_handles,
            )
            positioned_receipt_digest = (
                _verify_positioned_page_translation_evidence(
                    final_evidence,
                    source_id,
                    representation=representation,
                    strategy=final_strategy,
                    entity_handles=entity_handles,
                )
            )
        zero_ink_omitted = bool(
            representation == "raster" and final_evidence.get("zero_ink_omitted") is True
        )
        if zero_ink_omitted:
            if entity_handles or support_handles or referenced_handles:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: zero-ink omission owns entities"
                )
            if final_attempt.get("entity_handles") or final_attempt.get("support_entity_handles"):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: zero-ink attempt owns entities"
                )
            return
        if not entity_handles or main_handles.intersection(entity_handles):
            raise RuntimeError(
                f"serialized text delivery {source_id}: missing or duplicate main handles"
            )
        main_handles.update(entity_handles)
        entities = [_serialized_entity(doc, handle, source_id) for handle in entity_handles]
        if positioned_receipt_digest is not None:
            _verify_positioned_translation_entity_receipts(
                doc,
                entities,
                source_id=source_id,
                expected_digest=positioned_receipt_digest,
            )
        for entity in entities:
            try:
                actual_owner = str(entity.dxf.get("owner", "") or "")
            except Exception:
                actual_owner = ""
            handle = str(entity.dxf.handle or "")
            if (
                modelspace_handle_counts.get(handle, 0) != 1
                or actual_owner != expected_modelspace_owner
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: "
                    "main entity ownership changed"
                )
        actual_types = {entity.dxftype() for entity in entities}
        if not actual_types.issubset(expected_types[representation]):
            raise RuntimeError(
                f"serialized text delivery {source_id}: expected {representation}, "
                f"found {sorted(actual_types)}"
            )
        if representation == "raster":
            if (
                final_evidence.get("host_safe_opaque_image_required") is not True
                or final_evidence.get("host_safe_opaque_image_verified") is not True
            ):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: missing host-safe "
                    "opaque-image evidence"
                )
            for entity in entities:
                image_definition = _serialized_entity(
                    doc,
                    str(entity.dxf.image_def_handle),
                    source_id,
                )
                asset_path = _resolve_serialized_asset_path(
                    doc,
                    str(image_definition.dxf.filename),
                )
                if not asset_path.is_file():
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: raster asset missing"
                    )
                raster_asset = fitz.Pixmap(str(asset_path))
                if bool(raster_asset.alpha):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: raster asset is not "
                        "host-safe opaque RGB"
                    )
        if representation == "3d_text":
            for entity in entities:
                depth = float(getattr(entity.dxf, "thickness", 0.0) or 0.0)
                extrusion = tuple(
                    float(value) for value in getattr(entity.dxf, "extrusion", (0.0, 0.0, 0.0))
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

        if (
            set(map(str, final_attempt.get("entity_handles") or []))
            != set(entity_handles)
            or set(map(str, final_attempt.get("support_entity_handles") or []))
            != set(support_handles)
            or set(map(str, final_attempt.get("referenced_entity_handles") or []))
            != set(referenced_handles)
        ):
            raise RuntimeError(f"serialized text delivery {source_id}: attempt handles disagree")

        positioned_fill_only = bool(
            final_evidence.get("positioned_visible_geometry_fill_only") is True
        )
        if positioned_delivery_evidence and not positioned_fill_only:
            raise RuntimeError(
                f"serialized text delivery {source_id}: "
                "positioned geometry contract changed"
            )
        positioned_r12_aci: Optional[int] = None
        if positioned_fill_only and doc.dxfversion == "AC1009":
            color_encoding = str(
                final_evidence.get("r12_source_color_encoding") or ""
            )
            if color_encoding == "exact_srgb8_aci_match":
                try:
                    source_rgb = tuple(
                        int(value)
                        for value in final_evidence.get("r12_source_color_rgb") or []
                    )
                    positioned_r12_aci = int(
                        final_evidence.get("r12_source_color_aci")
                    )
                    max_channel_error = int(
                        final_evidence.get(
                            "r12_source_color_max_channel_error", -1
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: invalid R12 color evidence"
                    ) from exc
                if (
                    len(source_rgb) != 3
                    or positioned_r12_aci not in range(1, 256)
                    or max_channel_error != 0
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: R12 color mapping changed"
                    )
                palette_rgb = tuple(
                    int(value) for value in aci2rgb(positioned_r12_aci)
                )
                if palette_rgb != source_rgb:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: R12 color mapping changed"
                    )
            elif color_encoding != "source_color_absent":
                raise RuntimeError(
                    f"serialized text delivery {source_id}: missing R12 color contract"
                )

        if representation == "geometry" and positioned_fill_only:
            expected_geometry_digest = str(
                final_evidence.get("positioned_geometry_sha256") or ""
            )
            character_solid_counts = list(
                final_evidence.get("positioned_geometry_character_solid_counts")
                or []
            )
            geometry_ok = bool(
                final_evidence.get("positioned_geometry_fingerprint_schema")
                == "ordered-positioned-character-solids-v1"
                and int(final_evidence.get("positioned_geometry_entity_count") or 0)
                == len(entities)
                and all(entity.dxftype() == "SOLID" for entity in entities)
                and _solid_fill_verified(
                    entities,
                    is_r12=doc.dxfversion == "AC1009",
                )
                and len(expected_geometry_digest) == 64
                and _positioned_geometry_fingerprint(
                    entities,
                    character_solid_counts=character_solid_counts,
                    character_text=list(
                        final_evidence.get("positioned_character_text") or []
                    ),
                    source_glyph_ids=list(
                        final_evidence.get("positioned_source_glyph_ids") or []
                    ),
                )
                == expected_geometry_digest
                and (
                    positioned_r12_aci is None
                    or all(
                        int(entity.dxf.get("color", 256)) == positioned_r12_aci
                        for entity in entities
                    )
                )
            )
            if not geometry_ok:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: positioned geometry changed"
                )

        if representation in {"text", "labels", "3d_text"}:
            if len(entities) != 1 or entities[0].dxftype() not in {"TEXT", "MTEXT"}:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: native text entity mismatch"
                )
            native = entities[0]
            evidence = dict(final_attempt.get("evidence") or {})
            actual_content = str(
                native.dxf.text if native.dxftype() == "TEXT" else native.plain_text()
            )
            expected_content = str(evidence.get("delivered_content") or "")
            expected_insert = tuple(
                float(value) for value in evidence.get("expected_insert") or []
            )
            actual_insert = tuple(float(value) for value in tuple(native.dxf.insert)[:2])
            expected_height = float(evidence.get("expected_height") or 0.0)
            actual_height = float(
                native.dxf.height if native.dxftype() == "TEXT" else native.dxf.char_height
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

            parent_font = str(evidence.get("parent_native_font_candidate") or "")
            if parent_font:
                style = doc.styles.get(str(native.dxf.style or ""))
                if str(style.dxf.font or "").strip().lower() != parent_font.lower():
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: parent font binding changed"
                    )

            if evidence.get("fit_alignment_verified"):
                target_width = float(evidence.get("expected_advance_width") or 0.0)
                if native.dxftype() != "TEXT" or int(native.dxf.halign or 0) != 5:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: FIT alignment changed"
                    )
                align_point = tuple(float(value) for value in tuple(native.dxf.align_point)[:2])
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
                    raise RuntimeError(f"serialized text delivery {source_id}: FIT width changed")

            if (
                evidence.get("target_app") == "librecad"
                and evidence.get("parent_native_font_substitution_accepted") is True
            ):
                required_evidence = (
                    "content_verified",
                    "anchor_verified",
                    "cap_height_invariant_verified",
                    "rotation_verified",
                    "fit_alignment_verified",
                    "librecad_lff_asset_verified",
                    "librecad_lff_coverage_verified",
                    "librecad_parent_installation_verified",
                    "librecad_lff_executable_binding_verified",
                    "librecad_lff_required_glyphs_drawable_verified",
                    "parent_native_font_format_verified",
                    "parent_native_font_asset_coverage_verified",
                    "parent_native_font_style_binding_verified",
                    "parent_native_font_builtin_lff_verified",
                    "parent_native_text_delivery_verified",
                    "native_text_structure_verified",
                )
                missing_evidence = [
                    key for key in required_evidence if evidence.get(key) is not True
                ]
                whitespace_contract = bool(
                    actual_content
                    and not actual_content.strip()
                    and evidence.get("source_content_whitespace_only") is True
                    and evidence.get("parent_native_font_rendering_required") is False
                    and evidence.get("parent_visual_fidelity_verified") is True
                    and evidence.get(
                        "parent_visual_fidelity_limited_by_font_substitution"
                    )
                    is False
                )
                disclosure_ok = bool(
                    evidence.get("parent_native_font_substituted") is True
                    and evidence.get("parent_source_font_equivalence_verified") is False
                    and evidence.get("parent_native_font_renderability_verified") is False
                    and evidence.get("parent_render_verification_required") is True
                    and (
                        whitespace_contract
                        or (
                            evidence.get("parent_visual_fidelity_verified") is False
                            and evidence.get(
                                "parent_visual_fidelity_limited_by_font_substitution"
                            )
                            is True
                        )
                    )
                )
                source_em_height = float(
                    evidence.get("source_font_em_height") or 0.0
                )
                source_cap_height_ratio = float(
                    evidence.get("source_cap_height_ratio") or 0.0
                )
                cap_height_reopen_ok = bool(
                    source_em_height > 0.0
                    and source_cap_height_ratio > 0.0
                    and math.isclose(
                        expected_height,
                        source_em_height * source_cap_height_ratio,
                        rel_tol=1e-9,
                        abs_tol=1e-12,
                    )
                )
                local_diagnostics = dict(
                    evidence.get("local_only_diagnostics") or {}
                )
                # These are handed to _resolve_librecad_unicode_lff, which
                # resolves an installation off the real filesystem, so they must
                # come from the unredacted half only. The previous fallback to
                # evidence[...] substituted a "<user>" path whenever the local
                # half was absent -- an account that exists nowhere, so the
                # reopen check could never pass. Empty is better: the resolver
                # treats it as unspecified and rediscovers normally.
                bound_executable = local_path_for_io(
                    evidence, "librecad_executable_path"
                )
                bound_lff = local_path_for_io(evidence, "librecad_lff_path")
                lff_binding_key = bound_lff or f"<unresolved>:{bound_executable}"
                reopened_lff_resolution = reopened_lff_resolutions.get(
                    lff_binding_key
                )
                if reopened_lff_resolution is None:
                    reopened_lff_resolution = _resolve_librecad_unicode_lff(
                        bound_executable,
                        fresh=True,
                    )
                    reopened_lff_resolutions[lff_binding_key] = (
                        reopened_lff_resolution
                    )
                reopened_lff_evidence = reopened_lff_resolution.evidence(
                    actual_content
                )
                lff_asset_evidence_ok = all(
                    evidence.get(key) == reopened_lff_evidence.get(key)
                    for key in (
                        "librecad_lff_path",
                        "librecad_lff_size_bytes",
                        "librecad_lff_sha256",
                        "librecad_lff_glyph_count",
                        "librecad_lff_drawable_glyph_count",
                        "librecad_lff_coverage_verified",
                        "librecad_lff_missing_codepoints",
                        "librecad_lff_invalid_codepoints",
                        "librecad_lff_required_glyphs_drawable_verified",
                        "librecad_executable_path",
                        "librecad_installation_root",
                        "librecad_parent_installation_verified",
                        "librecad_lff_executable_binding_verified",
                    )
                )
                reopened_local_diagnostics = dict(
                    reopened_lff_evidence.get("local_only_diagnostics") or {}
                )
                local_path_binding_ok = all(
                    local_diagnostics.get(key)
                    == reopened_local_diagnostics.get(key)
                    for key in (
                        "librecad_executable_path",
                        "librecad_installation_root",
                        "librecad_lff_path",
                    )
                )
                attempt_flags_ok = bool(
                    final_attempt.get("delivery_verified") is True
                    and final_attempt.get("visual_verified") is whitespace_contract
                )
                lff_reopen_ok = bool(
                    native.dxftype() == "TEXT"
                    and str(native.dxf.style or "").strip().lower() == "unicode"
                    and str(parent_font).strip().lower() == "unicode"
                    and str(
                        doc.styles.get(str(native.dxf.style or "")).dxf.font or ""
                    ).strip().lower()
                    == "unicode"
                    and evidence.get("parent_native_font_candidate_format") == "lff"
                    and evidence.get("parent_native_font_required_format") == "lff"
                )
                if (
                    missing_evidence
                    or not disclosure_ok
                    or not cap_height_reopen_ok
                    or not lff_asset_evidence_ok
                    or not local_path_binding_ok
                    or not attempt_flags_ok
                    or not lff_reopen_ok
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: LibreCAD native "
                        "text evidence or LFF renderability changed"
                    )
                evidence.update(
                    {
                        "parent_native_text_reopen_verified": True,
                        "parent_native_text_reopen_renderability_verified": False,
                        "parent_native_text_reopen_asset_coverage_verified": True,
                        "serialized_cap_height_invariant_verified": True,
                        "delivery_evidence_verified": True,
                    }
                )
                final_attempt["evidence"] = evidence

        if representation == "glyphs":
            support_set = set(support_handles)
            referenced_set = set(referenced_handles)
            if support_set & referenced_set:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: glyph ownership overlaps"
                )
            for insert in entities:
                if (
                    positioned_r12_aci is not None
                    and int(insert.dxf.get("color", 256)) != positioned_r12_aci
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: outer R12 color changed"
                    )
                try:
                    block = doc.blocks.get(str(insert.dxf.name))
                except Exception as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph block missing"
                    ) from exc
                outer_support = {
                    str(value.dxf.handle or "")
                    for value in (
                        *(() if doc.dxfversion == "AC1009" else (block.block_record,)),
                        block.block,
                        block.endblk,
                        *list(block),
                    )
                    if str(value.dxf.handle or "")
                }
                if final_evidence.get("nested_glyph_definitions") is not True:
                    if outer_support != support_set:
                        raise RuntimeError(
                            f"serialized text delivery {source_id}: glyph support mismatch"
                        )
                    continue

                if _glyph_outer_block_structure_fingerprint(block) != str(
                    final_evidence.get("glyph_outer_block_structure_sha256") or ""
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "outer BLOCK structure changed"
                    )
                outer_children = list(block)
                expected_definition_names = {
                    str(value)
                    for value in final_evidence.get("glyph_definition_names") or []
                    if str(value)
                }
                expected_definition_fingerprints = {
                    str(name): str(digest)
                    for name, digest in dict(
                        final_evidence.get("glyph_definition_geometry_sha256") or {}
                    ).items()
                }
                actual_definition_names = {
                    str(child.dxf.name)
                    for child in outer_children
                    if child.dxftype() == "INSERT"
                }
                expected_instance_count = int(
                    final_evidence.get("glyph_instance_count") or 0
                )
                expected_created_count = int(
                    final_evidence.get("glyph_definition_created_count") or 0
                )
                expected_reused_count = int(
                    final_evidence.get("glyph_definition_reused_count") or 0
                )
                expected_outer_insert = tuple(
                    float(value)
                    for value in final_evidence.get("expected_block_insert") or []
                )
                actual_outer_insert = tuple(
                    float(value) for value in tuple(insert.dxf.insert)[:2]
                )
                outer_transform_ok = bool(
                    len(expected_outer_insert) == 2
                    and all(
                        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                        for left, right in zip(
                            actual_outer_insert,
                            expected_outer_insert,
                            strict=True,
                        )
                    )
                    and math.isclose(
                        float(insert.dxf.xscale or 1.0),
                        1.0,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    and math.isclose(
                        float(insert.dxf.yscale or 1.0),
                        1.0,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    and math.isclose(
                        float(insert.dxf.rotation or 0.0),
                        0.0,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                )
                if _glyph_instance_transform_fingerprint([insert]) != str(
                    final_evidence.get("glyph_outer_insert_sha256") or ""
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "outer INSERT attributes changed"
                    )
                nested_shape_ok = bool(
                    len(entities) == 1
                    and outer_children
                    and outer_transform_ok
                    and all(child.dxftype() == "INSERT" for child in outer_children)
                    and len(outer_children) == expected_instance_count
                    and expected_created_count + expected_reused_count
                    == expected_instance_count
                    and actual_definition_names == expected_definition_names
                    and set(expected_definition_fingerprints)
                    == expected_definition_names
                    and str(insert.dxf.name)
                    == str(final_evidence.get("block_name") or "")
                    and final_evidence.get("block_insert_verified") is True
                    and final_evidence.get("outline_bbox_verified") is True
                    and _glyph_instance_transform_fingerprint(outer_children)
                    == str(
                        final_evidence.get("glyph_instance_transform_sha256") or ""
                    )
                    and (
                        positioned_r12_aci is None
                        or all(
                            int(child.dxf.get("color", 256))
                            == positioned_r12_aci
                            for child in outer_children
                        )
                    )
                )
                if not nested_shape_ok:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: nested glyph evidence changed"
                    )

                owned_definitions: set[str] = set()
                owned_definition_names: set[str] = set()
                referenced_definitions: set[str] = set()
                for definition_name in expected_definition_names:
                    try:
                        definition = doc.blocks.get(definition_name)
                    except Exception as exc:
                        raise RuntimeError(
                            f"serialized text delivery {source_id}: "
                            "glyph definition missing"
                        ) from exc
                    definition_children = list(definition)
                    if (
                        not definition_children
                        or any(
                            child.dxftype()
                            not in {"LWPOLYLINE", "POLYLINE", "SOLID"}
                            for child in definition_children
                        )
                        or not any(
                            child.dxftype() == "SOLID" for child in definition_children
                        )
                        or (
                            positioned_fill_only
                            and (
                                any(
                                    child.dxftype() != "SOLID"
                                    for child in definition_children
                                )
                                or not _solid_fill_verified(
                                    definition_children,
                                    is_r12=doc.dxfversion == "AC1009",
                                )
                                or (
                                    positioned_r12_aci is not None
                                    and any(
                                        int(child.dxf.get("color", 256))
                                        != positioned_r12_aci
                                        for child in definition_children
                                    )
                                )
                            )
                        )
                    ):
                        raise RuntimeError(
                            f"serialized text delivery {source_id}: "
                            "glyph definition geometry changed"
                        )
                    actual_definition_fingerprint = definition_fingerprints.get(
                        definition_name
                    )
                    if actual_definition_fingerprint is None:
                        actual_definition_fingerprint = (
                            _glyph_definition_geometry_fingerprint(definition)
                        )
                        definition_fingerprints[definition_name] = (
                            actual_definition_fingerprint
                        )
                    if (
                        actual_definition_fingerprint
                        != expected_definition_fingerprints[definition_name]
                    ):
                        raise RuntimeError(
                            f"serialized text delivery {source_id}: "
                            "glyph definition geometry changed"
                        )
                    definition_support = {
                        str(value.dxf.handle or "")
                        for value in (
                            *(
                                ()
                                if doc.dxfversion == "AC1009"
                                else (definition.block_record,)
                            ),
                            definition.block,
                            definition.endblk,
                            *definition_children,
                        )
                        if str(value.dxf.handle or "")
                    }
                    if definition_support.issubset(support_set):
                        owned_definitions.update(definition_support)
                        owned_definition_names.add(definition_name)
                    elif definition_support.issubset(referenced_set):
                        referenced_definitions.update(definition_support)
                    else:
                        raise RuntimeError(
                            f"serialized text delivery {source_id}: "
                            "glyph definition ownership mismatch"
                        )

                if len(owned_definition_names) != expected_created_count:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "glyph creation evidence changed"
                    )
                if outer_support | owned_definitions != support_set:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph support mismatch"
                    )
                extra_references = referenced_set - referenced_definitions
                if any(
                    _serialized_entity(doc, handle, source_id).dxftype() != "STYLE"
                    for handle in extra_references
                ):
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "unexpected glyph reference"
                    )

                expected_bbox = tuple(
                    float(value)
                    for value in final_evidence.get("expected_outline_bbox") or []
                )
                recorded_tolerance = tuple(
                    float(value)
                    for value in final_evidence.get(
                        "outline_bbox_tessellation_tolerance"
                    )
                    or []
                )
                computed_tolerance = _nested_outline_tolerance(
                    outer_children,
                    expected_bbox,
                )
                tolerance_evidence_ok = bool(
                    len(expected_bbox) == 4
                    and len(recorded_tolerance) == 2
                    and all(value > 0.0 for value in recorded_tolerance)
                    and all(
                        math.isclose(
                            recorded,
                            computed,
                            rel_tol=1e-12,
                            abs_tol=1e-15,
                        )
                        for recorded, computed in zip(
                            recorded_tolerance,
                            computed_tolerance,
                            strict=True,
                        )
                    )
                )
                if not tolerance_evidence_ok:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "glyph bbox tolerance evidence changed"
                    )
                # Outline-only decomposition: bit-identical to filtering
                # recursive_decompose to LWPOLYLINE/POLYLINE, minus the SOLID fills.
                serialized_outlines = list(iter_glyph_outline_entities(insert))
                # _bbox_tuple == ezdxf bbox.extents (exact vertex bbox on plain
                # LWPOLYLINE outlines, ezdxf otherwise).
                serialized_box = _bbox_tuple(serialized_outlines)
                if serialized_box is None:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "serialized glyph bbox missing"
                    )
                serialized_bbox = (
                    serialized_box[0] - actual_outer_insert[0],
                    serialized_box[1] - actual_outer_insert[1],
                    serialized_box[2] - actual_outer_insert[0],
                    serialized_box[3] - actual_outer_insert[1],
                )
                serialized_bbox_errors = tuple(
                    abs(left - right)
                    for left, right in zip(
                        serialized_bbox,
                        expected_bbox,
                        strict=True,
                    )
                )
                serialized_bbox_ok = bool(
                    serialized_bbox_errors[0] <= computed_tolerance[0]
                    and serialized_bbox_errors[2] <= computed_tolerance[0]
                    and serialized_bbox_errors[1] <= computed_tolerance[1]
                    and serialized_bbox_errors[3] <= computed_tolerance[1]
                )
                if not serialized_bbox_ok:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: "
                        "serialized glyph bbox changed"
                    )

        if representation == "raster":
            evidence = dict(final_attempt.get("evidence") or {})
            asset_path = Path(str(evidence.get("asset_path") or ""))
            expected_sha = str(evidence.get("asset_sha256") or "")
            if not asset_path.is_file() or not expected_sha:
                raise RuntimeError(f"serialized text delivery {source_id}: raster asset missing")
            if hashlib.sha256(asset_path.read_bytes()).hexdigest() != expected_sha:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster asset hash mismatch"
                )
            if len(entities) != 1:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster must own one IMAGE"
                )
            raster = entities[0]
            target_bbox = [float(value) for value in evidence.get("target_bbox_model") or []]
            pixel_size = [int(value) for value in evidence.get("pixel_size") or []]
            if len(target_bbox) != 4 or len(pixel_size) != 2:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster evidence incomplete"
                )
            from librecad_pdf_importer.raster_geometry import raster_pixel_geometry
            expected = raster_pixel_geometry(
                evidence.get("pixel_origin") or [], pixel_size, evidence.get("raster_dpi", 0),
                evidence.get("display_to_model") or [], evidence.get("export_page_offset_y", 0),
            )
            actual_values = (tuple(raster.dxf.insert) + tuple(raster.dxf.u_pixel)
                             + tuple(raster.dxf.v_pixel) + tuple(raster.dxf.image_size))
            expected_values = (*expected["image_insert"], 0.0,
                               *expected["image_u_pixel"], 0.0,
                               *expected["image_v_pixel"], 0.0, *pixel_size, 0.0)
            placement_ok = all(
                math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
                for left, right in zip(actual_values, expected_values, strict=True)
            ) and all(math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9)
                      for a, b in zip(target_bbox, expected["target_bbox_model"], strict=True))
            if not placement_ok:
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster placement changed"
                )
            image_def_handle = str(raster.dxf.image_def_handle or "")
            reactor_handle = str(raster.dxf.image_def_reactor_handle or "")
            exact_support = {handle for handle in (image_def_handle, reactor_handle) if handle}
            if exact_support != set(support_handles):
                raise RuntimeError(
                    f"serialized text delivery {source_id}: raster support mismatch"
                )
            image_def = _serialized_entity(doc, image_def_handle, source_id)
            actual_asset_path = _resolve_serialized_asset_path(
                doc,
                str(image_def.dxf.filename or ""),
            )
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
            if evidence.get("font_asset_id") and evidence.get("font_exact_match") is True:
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

    # One mismatching item must not hide the next: every mismatch confined to
    # one delivery is collected, so ONE forced-degrade re-export covers them
    # all. Structural failures (duplicate source IDs, a dropped item that owns
    # handles) name no retryable delivery and stay fatal at once.
    mismatches: List[RuntimeError] = []
    for delivery in deliveries:
        try:
            verify_delivery(delivery)
        except RuntimeError as exc:
            if _serialized_mismatch_item(str(exc), [delivery]) is None:
                raise
            mismatches.append(exc)
        except Exception as exc:  # noqa: BLE001 - a fault while checking one item is that item's mismatch
            mismatches.append(
                RuntimeError(
                    f"serialized text delivery {delivery.get('source_id')}: "
                    f"{type(exc).__name__}: {exc}"
                )
            )
    if len(mismatches) == 1:
        raise mismatches[0]
    if mismatches:
        raise _SerializedTextDeliveryMismatches([str(exc) for exc in mismatches])


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
    source_size_px: Tuple[int, int]
    crop_box_px: Tuple[int, int, int, int]
    draw_below_editable: bool = False


@dataclass(frozen=True)
class _SerializedImageExpectation:
    image_handle: str
    image_def_handle: str
    asset_path: Path
    asset_sha256: str
    insert: Tuple[float, float]
    u_pixel: Tuple[float, float]
    v_pixel: Tuple[float, float]
    size_in_pixel: Tuple[int, int]


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
    staging_faults: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Stage exact source font programs in this output's unique asset set.

    ``staging_faults`` collects per-asset environment failures so the affected
    items can descend a rung instead of the write escaping and failing the
    whole export.
    """

    from pdfcadcore.atomic_io import atomic_write_bytes

    if staging_faults is None:
        staging_faults = {}

    assets: Dict[str, Any] = {}
    for page in extraction.pages:
        for item in page.page_data.text_items:
            asset = getattr(item, "font_asset", None)
            if asset is None:
                continue
            previous = assets.get(str(asset.asset_id))
            if previous is not None and bytes(previous.usable_bytes) != bytes(asset.usable_bytes):
                raise RuntimeError(f"embedded font asset identity collision: {asset.asset_id}")
            assets[str(asset.asset_id)] = asset

    if not assets:
        return {}
    font_root = asset_root / "fonts"
    try:
        font_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Nothing can be staged. Record one fault per asset so every affected
        # item descends with a reason, instead of an OSError escaping to
        # export_to_dxf, which would roll back and fail the whole document.
        for asset_id in assets:
            _record_font_staging_fault(staging_faults, asset_id, exc)
        return {}
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
        try:
            atomic_write_bytes(path, content)
        except OSError as exc:
            # Environment fault on this one asset: the items that need it will
            # descend a rung; the rest of the document is unaffected. Integrity
            # failures above stay fatal -- they are our bugs, not the machine's.
            _record_font_staging_fault(staging_faults, asset_id, exc)
            continue
        transaction.register_file(path)
        paths[asset_id] = str(path)
    return paths


def _record_font_staging_fault(
    faults: Dict[str, str],
    asset_id: str,
    exc: BaseException,
) -> bool:
    """Record why one exact font could not be staged on this machine.

    The reason is carried through to the per-item resolver, which treats a
    recorded fault as affirmative proof that the exact rung is impossible here
    and descends. Without the record the same absence is indistinguishable from
    a bug: it stays an unproven failure, so the item is degraded as unverified
    and reported instead of being certified.
    """
    key = str(asset_id or "")
    if not key:
        return False
    faults[key] = f"{type(exc).__name__}: {exc}"
    return True


def _restore_embedded_font_asset(
    extraction: DocumentExtraction,
    asset_id: str,
    paths: Dict[str, str],
    transaction: _AssetTransaction,
) -> str:
    """Restore one missing or changed exporter-owned font from source truth."""

    from pdfcadcore.atomic_io import atomic_write_bytes

    requested_id = str(asset_id or "")
    raw_path = str(paths.get(requested_id, "") or "")
    if not requested_id or not raw_path:
        raise RuntimeError(f"embedded font asset is not owned by this export: {requested_id}")

    selected = None
    for page in extraction.pages:
        for item in page.page_data.text_items:
            asset = getattr(item, "font_asset", None)
            if asset is None or str(asset.asset_id) != requested_id:
                continue
            if selected is not None and bytes(selected.usable_bytes) != bytes(
                asset.usable_bytes
            ):
                raise RuntimeError(f"embedded font asset identity collision: {requested_id}")
            selected = asset
    if selected is None:
        raise RuntimeError(f"embedded font source asset is unavailable: {requested_id}")

    content = bytes(selected.usable_bytes)
    digest = hashlib.sha256(content).hexdigest()
    if digest != str(selected.usable_sha256) or requested_id != f"sha256:{digest}":
        raise RuntimeError(f"embedded font source digest mismatch: {requested_id}")
    expected_extension = str(selected.usable_format or "otf").lower().lstrip(".")
    path = Path(raw_path)
    if expected_extension not in {"otf", "ttf"} or path.suffix.lower() != (
        f".{expected_extension}"
    ):
        raise RuntimeError(f"unsupported staged font format: {expected_extension}")

    atomic_write_bytes(path, content)
    transaction.register_file(path)
    transaction.register_directory(path.parent)
    transaction.register_directory(path.parent.parent)
    return str(path)


def _normalized_image_source_path(raw_path: str) -> str:
    return str(Path(raw_path).expanduser().resolve())


def _serialized_asset_filename(asset_path: Path, output_parent: Path) -> str:
    """Return a portable path anchored to the accepted DXF directory."""

    try:
        return asset_path.resolve().relative_to(output_parent.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"owned asset escaped the DXF output directory: {asset_path}") from exc


def _resolve_serialized_asset_path(doc: Any, raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    if not path.is_absolute():
        document_name = str(getattr(doc, "filename", "") or "")
        if not document_name:
            raise RuntimeError("serialized DXF has no path for relative assets")
        document_path = Path(document_name)
        path = document_path.resolve().parent / path
    return path.resolve()


# ---------------------------------------------------------------------------
# Streaming DXF record access.
#
# The post-write verification and the prior-output asset scan used to load the
# whole DXF through ezdxf a second time.  On a 452k-entity sheet that is a 121 MB
# text file and ~24 s of object construction for records the verification never
# looks at.  A DXF text file is a flat sequence of (group code, value) line
# pairs and every record starts with a group-0 tag, so records can be walked
# without building objects.  The verification then reopens a copy that keeps
# every record it inspects and leaves out only bulk geometry it never inspects,
# after that geometry has been syntax-checked here.
# ---------------------------------------------------------------------------

_DXF_HANDLE_VALUE = re.compile(r"^[0-9A-Fa-f]+$")

# Single-record bulk geometry that the serialized-delivery verification never
# addresses by type.  Multi-record entities (POLYLINE/VERTEX/SEQEND) and every
# text, block reference, image, solid and unknown type are always kept.
_REDUCIBLE_BULK_TYPES = frozenset(
    {"LINE", "LWPOLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "HATCH", "POINT"}
)


class _ReducedCopyUnavailable(Exception):
    """The file has a layout the streaming pass does not model; load it fully."""


class _DxfRecordIndex:
    """Line-level index over DXF text: (code, value) pairs and record starts.

    Pair ``i`` is line ``2*i`` (group code) and line ``2*i + 1`` (value).  A
    record starts at every pair whose group code is 0; record ``r`` covers pairs
    ``starts[r]`` up to ``starts[r + 1]``.  Lines keep their trailing CR so
    :meth:`record_text` reproduces the original bytes of a record exactly.
    Group codes are validated for the whole file at once: the distinct code
    strings of even a 120 MB file number a few dozen.
    """

    __slots__ = ("lines", "codes", "values", "starts")

    def __init__(self, text: str) -> None:
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        if len(lines) % 2:
            raise _ReducedCopyUnavailable("odd line count")
        raw_codes = lines[0::2]
        normalized: Dict[str, str] = {}
        for raw in set(raw_codes):
            code = raw.rstrip("\r").strip()
            if not code.lstrip("-").isdigit():
                raise _ReducedCopyUnavailable(f"non-numeric group code {code!r}")
            normalized[raw] = code
        self.lines = lines
        self.codes: List[str] = list(map(normalized.__getitem__, raw_codes))
        self.values: List[str] = lines[1::2]
        self.starts: List[int] = [index for index, code in enumerate(self.codes) if code == "0"]
        if not self.starts or self.starts[0] != 0:
            raise _ReducedCopyUnavailable("file does not open with a group-0 tag")

    def __len__(self) -> int:
        return len(self.starts)

    def record_range(self, record: int) -> Tuple[int, int]:
        start = self.starts[record]
        end = self.starts[record + 1] if record + 1 < len(self.starts) else len(self.codes)
        return start, end

    def record_type(self, record: int) -> str:
        return self.values[self.starts[record]].rstrip("\r").strip()

    def record_values(self, record: int, code: str) -> List[str]:
        """Values of every tag with ``code`` in the record, CR stripped."""

        start, end = self.record_range(record)
        codes = self.codes
        values = self.values
        return [
            values[index].rstrip("\r")
            for index in range(start + 1, end)
            if codes[index] == code
        ]

    def record_text(self, record: int) -> str:
        start, end = self.record_range(record)
        return "\n".join(self.lines[2 * start : 2 * end]) + "\n"

    def write_records(self, records: Sequence[int], destination: Path) -> None:
        destination.write_bytes("".join(self.record_text(record) for record in records).encode("utf-8"))


def _reduced_verification_copy(
    temp_output: Path,
    keep_handles: set[str],
    modelspace_owner_handle: str,
) -> Tuple[Path, int]:
    """Write a reduced copy of the serialized candidate for verification.

    Every record outside the ENTITIES section, every entity whose type is not
    plain bulk geometry, every bulk entity whose handle is delivered or
    referenced, and every bulk entity not owned by the modelspace is copied
    verbatim.  A bulk entity is left out only after its record parsed as
    complete (code, value) pairs with exactly one handle that is unique among
    every entity in the file and an owner equal to the modelspace block record,
    so the verification that follows still runs on the exact serialized bytes of
    everything it inspects.  The redraw order (SORTENTSTABLE) is copied verbatim
    and every entity it names must have been written.  Returns the reduced path
    and the number of entities left out so the caller can prove
    ``kept + left out == entities written``.
    """

    index = _DxfRecordIndex(temp_output.read_bytes().decode("utf-8", errors="strict"))
    keep = {str(handle).upper() for handle in keep_handles if str(handle)}
    owner = str(modelspace_owner_handle).upper()
    codes = index.codes
    values = index.values
    starts = index.starts
    pair_count = len(codes)

    # One pass: section layout, the handle census over every ENTITIES record
    # (bulk or not, so a bulk record sharing a handle with any other entity is
    # refused instead of left out), and the redraw-order references.
    candidates: List[Tuple[int, str, str, bool]] = []  # record, type, handle, owner ok
    current_section: Optional[str] = None
    seen_handles: Dict[str, int] = {}
    sort_references: List[str] = []
    for record in range(len(starts)):
        start = starts[record]
        type_name = values[start].rstrip("\r").strip()
        if type_name == "SECTION":
            names = index.record_values(record, "2")
            current_section = names[0].strip() if names else None
            continue
        if type_name == "ENDSEC":
            current_section = None
            continue
        if type_name == "SORTENTSTABLE":
            # The redraw order lists every modelspace entity when a page carries
            # images.  Nothing in the verification reads it back and ezdxf does
            # not audit it, so its entries do not decide what is kept; they are
            # checked below to resolve to an entity that was written.
            sort_references.extend(value.strip().upper() for value in index.record_values(record, "331"))
            continue
        if current_section != "ENTITIES":
            continue
        end = starts[record + 1] if record + 1 < len(starts) else pair_count
        sub = codes[start + 1 : end]
        handle_count = sub.count("5")
        if type_name not in _REDUCIBLE_BULK_TYPES or handle_count != 1:
            for handle in index.record_values(record, "5"):
                handle = handle.strip().upper()
                seen_handles[handle] = seen_handles.get(handle, 0) + 1
            if type_name in _REDUCIBLE_BULK_TYPES:
                raise RuntimeError(
                    f"serialized DXF candidate {type_name} record has {handle_count} handle tags"
                )
            continue
        handle = values[start + 1 + sub.index("5")].rstrip("\r").strip().upper()
        if not _DXF_HANDLE_VALUE.match(handle):
            raise RuntimeError(
                f"serialized DXF candidate {type_name} record has a malformed handle {handle!r}"
            )
        seen_handles[handle] = seen_handles.get(handle, 0) + 1
        owner_ok = (
            sub.count("330") == 1
            and values[start + 1 + sub.index("330")].rstrip("\r").strip().upper() == owner
        )
        candidates.append((record, type_name, handle, owner_ok))

    missing_sort_targets = [handle for handle in sort_references if handle not in seen_handles]
    if missing_sort_targets:
        raise RuntimeError(
            "serialized DXF candidate redraw order references a missing entity "
            f"{missing_sort_targets[0]}"
        )

    leave_out: set[int] = set()
    for record, type_name, handle, owner_ok in candidates:
        if seen_handles.get(handle, 0) != 1:
            raise RuntimeError(
                f"serialized DXF candidate repeats entity handle {handle} ({type_name})"
            )
        if owner_ok and handle not in keep:
            leave_out.add(record)
    reduced = temp_output.with_name(temp_output.name + ".verify")
    index.write_records(
        [record for record in range(len(starts)) if record not in leave_out], reduced
    )
    return reduced, len(leave_out)


def _reopen_candidate_for_verification(
    temp_output: Path,
    *,
    keep_handles: set[str],
    modelspace_owner_handle: str,
    entities_written: int,
) -> Tuple[Any, Any]:
    """Re-open and audit the serialized candidate without a full parse.

    Returns ``(candidate, auditor)``.  Falls back to a complete ezdxf load and
    audit whenever the reduced copy cannot be produced for a structural reason
    or its audit reports errors, so a surprising file never weakens the check
    and a reduced copy can never refuse what the full file would accept; it
    only slows it.  Corruption found by the streaming pass raises.
    """

    reduced: Optional[Path] = None
    dropped = 0
    try:
        reduced, dropped = _reduced_verification_copy(
            temp_output, keep_handles, modelspace_owner_handle
        )
    except (UnicodeDecodeError, _ReducedCopyUnavailable):
        # A pre-R2007 candidate is cp1252, not UTF-8: one degraded TEXT carrying
        # a degree sign is enough. The complete load below reads its codepage.
        reduced = None
    if reduced is not None:
        try:
            candidate = ezdxf.readfile(str(reduced))
        finally:
            try:
                reduced.unlink(missing_ok=True)
            except OSError:
                pass
        # Relative asset paths resolve against the real candidate, not the copy.
        candidate.filename = str(temp_output)
        kept = len(candidate.modelspace())
        if kept + dropped != entities_written:
            raise RuntimeError(
                "serialized DXF candidate entity count changed: "
                f"wrote {entities_written}, re-read {kept} + {dropped} left out"
            )
        auditor = candidate.audit()
        if not auditor.has_errors:
            return candidate, auditor
    candidate = ezdxf.readfile(str(temp_output))
    return candidate, candidate.audit()


def _scan_asset_reference_paths(output: Path) -> Tuple[List[str], List[str]]:
    """Return (IMAGEDEF filenames, STYLE fonts) from a DXF without loading it."""

    index = _DxfRecordIndex(output.read_bytes().decode("utf-8", errors="strict"))
    image_paths: List[str] = []
    fonts: List[str] = []
    for record in range(len(index)):
        type_name = index.record_type(record)
        if type_name == "IMAGEDEF":
            image_paths.extend(index.record_values(record, "1"))
        elif type_name == "STYLE":
            fonts.extend(font for font in index.record_values(record, "3") if font.strip())
    return image_paths, fonts


class _PriorOutputPathAnchor:
    """Minimal stand-in for a loaded document: only its filename is needed."""

    def __init__(self, filename: Path) -> None:
        self.filename = str(filename)


def _owned_sessions_referenced_by_output(output: Path, asset_parent: Path) -> set[Path]:
    """Find only UUID session directories referenced by the prior accepted DXF."""

    if not output.is_file() or not asset_parent.is_dir():
        return set()
    prior: Any
    try:
        image_paths, fonts = _scan_asset_reference_paths(output)
        raw_paths = list(image_paths) + [font for font in fonts if font]
        prior = _PriorOutputPathAnchor(output)
    except (OSError, RuntimeError, UnicodeDecodeError, _ReducedCopyUnavailable):
        try:
            prior = ezdxf.readfile(str(output))
        except (OSError, ezdxf.DXFError):
            return set()
        raw_paths = [
            str(image_def.dxf.filename or "") for image_def in prior.objects.query("IMAGEDEF")
        ]
        raw_paths.extend(
            str(style.dxf.font or "") for style in prior.styles if str(style.dxf.font or "")
        )
    sessions: set[Path] = set()
    for raw_path in raw_paths:
        try:
            path = _resolve_serialized_asset_path(prior, raw_path)
            relative = path.relative_to(asset_parent.resolve())
        except (RuntimeError, ValueError):
            continue
        if not relative.parts or not re.fullmatch(r"[0-9a-f]{32}", relative.parts[0]):
            continue
        session = (asset_parent / relative.parts[0]).resolve()
        if session.parent == asset_parent.resolve() and session.is_dir():
            sessions.add(session)
    return sessions


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _placement_alpha_profile(
    source_path: Path,
    placements: List[ImagePlacement],
) -> Tuple[Tuple[int, int], str, Tuple[int, int, int, int], bool]:
    """Use extraction-time alpha facts, decoding only legacy/caller-owned assets."""

    known = {
        (
            tuple(placement.pixel_size or ()),
            str(placement.alpha_kind or "unknown"),
            tuple(placement.alpha_bbox_px or ()),
            bool(placement.alpha_present),
        )
        for placement in placements
        if placement.pixel_size
        and placement.alpha_kind != "unknown"
        and placement.alpha_bbox_px is not None
    }
    if len(known) > 1:
        raise RuntimeError(f"image alpha metadata conflicts: {source_path}")
    if known:
        raw_size, alpha_kind, raw_bbox, alpha_present = next(iter(known))
        size_px = (int(raw_size[0]), int(raw_size[1]))
        bbox = tuple(int(value) for value in raw_bbox)
        return size_px, alpha_kind, bbox, alpha_present  # type: ignore[return-value]

    try:
        pixmap = fitz.Pixmap(str(source_path))
        size_px = (int(pixmap.width), int(pixmap.height))
        alpha_kind, bbox = _classify_pixmap_alpha(pixmap)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"image asset is unreadable: {source_path}: {exc}") from exc
    return size_px, alpha_kind, bbox, bool(pixmap.alpha)


def _rectangular_opaque_crop(
    source_path: Path,
    crop_box: Tuple[int, int, int, int],
) -> bytes:
    """Encode only a proven fully opaque rectangular support region."""

    left, top, right, bottom = crop_box
    try:
        source = fitz.Pixmap(str(source_path))
        if source.colorspace is None or int(source.colorspace.n) != 3:
            source = fitz.Pixmap(fitz.csRGB, source)
        channels = int(source.n)
        stride = int(source.stride)
        rows = np.frombuffer(source.samples_mv, dtype=np.uint8).reshape(
            int(source.height),
            stride,
        )
        pixels = rows[:, : int(source.width) * channels].reshape(
            int(source.height),
            int(source.width),
            channels,
        )
        rgb = np.ascontiguousarray(pixels[top:bottom, left:right, :3])
        clipped = fitz.Pixmap(
            fitz.csRGB,
            int(right - left),
            int(bottom - top),
            rgb.tobytes(),
            False,
        )
        prepared = bytes(clipped.tobytes("png"))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"image crop failed: {source_path}: {exc}") from exc
    if not prepared.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"host-safe image crop encoding failed: {source_path}")
    return prepared


def _opaque_rgb_asset(source_path: Path, *, matte_transparency: bool) -> bytes:
    """Strip a safe alpha channel, optionally compositing binary holes on white."""

    try:
        source = fitz.Pixmap(str(source_path))
        if source.colorspace is None or int(source.colorspace.n) != 3:
            source = fitz.Pixmap(fitz.csRGB, source)
        channels = int(source.n)
        rows = np.frombuffer(source.samples_mv, dtype=np.uint8).reshape(
            int(source.height),
            int(source.stride),
        )
        pixels = rows[:, : int(source.width) * channels].reshape(
            int(source.height),
            int(source.width),
            channels,
        )
        rgb = np.array(pixels[:, :, :3], copy=True)
        if bool(source.alpha) and matte_transparency:
            alpha = pixels[:, :, channels - 1].astype(np.uint16)
            rgb = np.minimum(
                rgb.astype(np.uint16) + (255 - alpha)[:, :, np.newaxis],
                255,
            ).astype(np.uint8)
        rgb = np.ascontiguousarray(rgb)
        opaque = fitz.Pixmap(
            fitz.csRGB,
            int(source.width),
            int(source.height),
            rgb.tobytes(),
            False,
        )
        prepared = bytes(opaque.tobytes("png"))
    except (MemoryError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"opaque RGB image normalization failed: {source_path}: {exc}") from exc
    if not prepared.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"opaque RGB image encoding failed: {source_path}")
    return prepared


def _stage_image_assets(
    extraction: DocumentExtraction,
    asset_root: Path,
    transaction: _AssetTransaction,
) -> Tuple[Dict[str, _StagedImageAsset], set[str], set[int]]:
    """Copy every extracted image into this accepted DXF's owned asset set."""

    from pdfcadcore.atomic_io import atomic_write_bytes

    marker_kinds = {
        "inline_image_page_fidelity_required",
        "xobject_image_page_fidelity_required",
    }
    marker_pages = {
        int(placement.page_number)
        for page in extraction.pages
        for placement in page.images
        if str(placement.source_kind) in marker_kinds
    }
    source_paths = sorted(
        {
            _normalized_image_source_path(str(placement.path))
            for page in extraction.pages
            for placement in page.images
            if str(placement.source_kind) not in marker_kinds
        }
    )
    if not source_paths:
        return {}, set(), marker_pages

    image_root = asset_root / "images"
    image_root_ready = False

    staged_by_digest: Dict[str, Path] = {}
    staged_by_source: Dict[str, _StagedImageAsset] = {}
    omitted_sources: set[str] = set()
    compositing_pages: set[int] = set(marker_pages)
    placements_by_source: Dict[str, List[ImagePlacement]] = {}
    profiles_by_source: Dict[
        str,
        Tuple[Tuple[int, int], str, Tuple[int, int, int, int], bool],
    ] = {}
    masked_page_rasters: set[str] = set()
    for page in extraction.pages:
        for placement in page.images:
            if str(placement.source_kind) in marker_kinds:
                continue
            placements_by_source.setdefault(
                _normalized_image_source_path(str(placement.path)), []
            ).append(placement)
    for source_key in source_paths:
        source_path = Path(source_key)
        if not source_path.is_file():
            raise RuntimeError(f"image asset is missing: {source_path}")
        size_px, alpha_kind, crop_box_px, alpha_present = _placement_alpha_profile(
            source_path,
            placements_by_source[source_key],
        )
        profiles_by_source[source_key] = (
            size_px,
            alpha_kind,
            crop_box_px,
            alpha_present,
        )
        masked_page_raster = all(
            placement.source_kind == "page_raster" and bool(placement.masked_text_bboxes_pdf)
            for placement in placements_by_source[source_key]
        )
        if masked_page_raster:
            masked_page_rasters.add(source_key)
        if alpha_kind == "zero":
            omitted_sources.add(source_key)
        elif (
            not masked_page_raster
            and alpha_kind == "rectangular_opaque"
            and (crop_box_px[2] - crop_box_px[0]) * (crop_box_px[3] - crop_box_px[1])
            > RECTANGULAR_CROP_MAX_PIXELS
        ):
            profiles_by_source[source_key] = (
                size_px,
                "compositing_required",
                crop_box_px,
                alpha_present,
            )
            compositing_pages.update(
                int(placement.page_number) for placement in placements_by_source[source_key]
            )
        elif (
            not masked_page_raster
            and alpha_kind == "binary_mask"
            and not all(
                placement.source_kind == "page_raster"
                for placement in placements_by_source[source_key]
            )
        ):
            compositing_pages.update(
                int(placement.page_number) for placement in placements_by_source[source_key]
            )
        elif not masked_page_raster and (
            alpha_kind == "compositing_required"
            or (
                alpha_kind == "opaque"
                and alpha_present
                and size_px[0] * size_px[1] > OPAQUE_ALPHA_NORMALIZE_MAX_PIXELS
            )
        ):
            compositing_pages.update(
                int(placement.page_number) for placement in placements_by_source[source_key]
            )

    for source_key in source_paths:
        if source_key in omitted_sources:
            continue
        placements = placements_by_source[source_key]
        if all(int(placement.page_number) in compositing_pages for placement in placements):
            continue
        if not image_root_ready:
            image_root.mkdir(parents=True, exist_ok=True)
            transaction.register_directory(asset_root.parent)
            transaction.register_directory(asset_root)
            transaction.register_directory(image_root)
            image_root_ready = True
        source_path = Path(source_key)
        size_px, alpha_kind, crop_box_px, alpha_present = profiles_by_source[source_key]
        try:
            content = source_path.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"image asset is unreadable: {source_path}: {exc}") from exc
        if not content:
            raise RuntimeError(f"image asset is empty: {source_path}")
        if source_key in masked_page_rasters:
            prepared = _opaque_rgb_asset(source_path, matte_transparency=True)
            prepared_size_px = size_px
            crop_box_px = (0, 0, size_px[0], size_px[1])
        elif alpha_kind == "rectangular_opaque":
            prepared = _rectangular_opaque_crop(source_path, crop_box_px)
            prepared_size_px = (
                crop_box_px[2] - crop_box_px[0],
                crop_box_px[3] - crop_box_px[1],
            )
        elif alpha_kind == "binary_mask":
            prepared = _opaque_rgb_asset(source_path, matte_transparency=True)
            prepared_size_px = size_px
            crop_box_px = (0, 0, size_px[0], size_px[1])
        elif alpha_kind == "opaque":
            prepared = (
                _opaque_rgb_asset(source_path, matte_transparency=False)
                if alpha_present
                else content
            )
            prepared_size_px = size_px
            crop_box_px = (0, 0, size_px[0], size_px[1])
        else:
            raise RuntimeError(
                f"unsupported image alpha classification {alpha_kind}: {source_path}"
            )
        digest = hashlib.sha256(prepared).hexdigest()
        staged_path = staged_by_digest.get(digest)
        if staged_path is None:
            if prepared.startswith(b"\x89PNG\r\n\x1a\n"):
                suffix = ".png"
            elif prepared.startswith(b"\xff\xd8\xff"):
                suffix = ".jpg"
            else:
                suffix = source_path.suffix.lower()
                if suffix not in {".bmp", ".gif", ".tif", ".tiff"}:
                    suffix = ".img"
            staged_path = image_root / f"{digest}{suffix}"
            atomic_write_bytes(staged_path, prepared)
            transaction.register_file(staged_path)
            if hashlib.sha256(staged_path.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"staged image asset hash mismatch: {staged_path}")
            if _image_size_pixels(str(staged_path)) != prepared_size_px:
                raise RuntimeError(f"staged image asset dimensions changed: {staged_path}")
            staged_by_digest[digest] = staged_path
        staged = _StagedImageAsset(
            source_path=source_path,
            path=staged_path,
            sha256=digest,
            size_px=prepared_size_px,
            source_size_px=size_px,
            crop_box_px=crop_box_px,
            draw_below_editable=bool(
                alpha_kind == "binary_mask" or source_key in masked_page_rasters
            ),
        )
        staged_by_source[source_key] = staged

    return staged_by_source, omitted_sources, compositing_pages


def _render_terminal_page_tiles(
    extraction: DocumentExtraction,
    page_number: int,
    dpi: int,
    asset_root: Path,
    transaction: _AssetTransaction,
) -> Tuple[List[ImagePlacement], Dict[str, _StagedImageAsset], float]:
    """Render an opaque, host-safe page surface in memory-bounded tiles."""

    from pdfcadcore.atomic_io import atomic_write_bytes

    extracted_page = next(
        page for page in extraction.pages if int(page.page_data.page_number) == int(page_number)
    )
    requested_dpi = max(TERMINAL_MIN_DPI, float(dpi or 200))
    image_root = asset_root / "images"
    image_root.mkdir(parents=True, exist_ok=True)
    transaction.register_directory(asset_root.parent)
    transaction.register_directory(asset_root)
    transaction.register_directory(image_root)

    placements: List[ImagePlacement] = []
    staged_assets: Dict[str, _StagedImageAsset] = {}
    staged_by_digest: Dict[str, Path] = {}
    with safe_open(extraction.pdf_path) as document:
        source_page = document[int(page_number) - 1]
        base_width = float(source_page.rect.width)
        base_height = float(source_page.rect.height)
        if base_width <= 0.0 or base_height <= 0.0:
            raise RuntimeError(f"page {page_number} has invalid physical dimensions")
        requested_zoom = requested_dpi / 72.0
        pixel_budget_zoom = math.sqrt(float(TERMINAL_MAX_PAGE_PIXELS) / (base_width * base_height))
        dimension_budget_zoom = min(
            float(TERMINAL_MAX_PAGE_DIMENSION) / base_width,
            float(TERMINAL_MAX_PAGE_DIMENSION) / base_height,
        )
        zoom = min(requested_zoom, pixel_budget_zoom, dimension_budget_zoom)
        effective_dpi = zoom * 72.0
        if effective_dpi + 1e-9 < TERMINAL_MIN_DPI:
            raise RuntimeError(
                f"page {page_number} exceeds the safe fidelity-surface resource "
                f"budget even at {TERMINAL_MIN_DPI:g} DPI"
            )
        matrix = fitz.Matrix(zoom, zoom)
        # One display list per page: Page.get_pixmap rebuilds the page's display
        # list on every call, which on a 500k-path sheet costs ~0.75 s per tile.
        # DisplayList.get_pixmap is the exact same rendering path PyMuPDF uses
        # inside Page.get_pixmap, so the tile pixels are unchanged.
        page_display_list = source_page.get_displaylist()
        rendered_bounds = (source_page.rect * matrix).irect
        full_width = int(rendered_bounds.width)
        full_height = int(rendered_bounds.height)
        if full_width <= 0 or full_height <= 0:
            raise RuntimeError(f"page {page_number} rendered to an empty image")

        tile_limit = max(64, int(TERMINAL_TILE_PIXELS))
        tile_count = math.ceil(full_width / tile_limit) * math.ceil(full_height / tile_limit)
        if tile_count > TERMINAL_MAX_TILES:
            raise RuntimeError(
                f"page {page_number} requires {tile_count} fidelity tiles; safe "
                f"maximum is {TERMINAL_MAX_TILES}"
            )
        for top_px in range(0, full_height, tile_limit):
            bottom_px = min(full_height, top_px + tile_limit)
            for left_px in range(0, full_width, tile_limit):
                right_px = min(full_width, left_px + tile_limit)
                bleed = max(0, int(TERMINAL_TILE_BLEED_PIXELS))
                render_left = max(0, left_px - bleed)
                render_top = max(0, top_px - bleed)
                render_right = min(full_width, right_px + bleed)
                render_bottom = min(full_height, bottom_px + bleed)
                render_clip = fitz.Rect(
                    float(source_page.rect.x0) + float(render_left) / zoom,
                    float(source_page.rect.y0) + float(render_top) / zoom,
                    float(source_page.rect.x0) + float(render_right) / zoom,
                    float(source_page.rect.y0) + float(render_bottom) / zoom,
                )
                rendered = page_display_list.get_pixmap(
                    matrix=matrix,
                    clip=render_clip,
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                rendered_size = (int(rendered.width), int(rendered.height))
                expected_rendered_size = (
                    render_right - render_left,
                    render_bottom - render_top,
                )
                if rendered_size != expected_rendered_size:
                    raise RuntimeError(
                        f"page {page_number} bleed tile dimensions changed: "
                        f"expected {expected_rendered_size}, got {rendered_size}"
                    )
                channels = int(rendered.n)
                rows = np.frombuffer(rendered.samples_mv, dtype=np.uint8).reshape(
                    int(rendered.height),
                    int(rendered.stride),
                )
                pixels = rows[:, : int(rendered.width) * channels].reshape(
                    int(rendered.height),
                    int(rendered.width),
                    channels,
                )
                crop_left = left_px - render_left
                crop_top = top_px - render_top
                tile_rgb = np.ascontiguousarray(
                    pixels[
                        crop_top : crop_top + (bottom_px - top_px),
                        crop_left : crop_left + (right_px - left_px),
                        :3,
                    ]
                )
                pixmap = fitz.Pixmap(
                    fitz.csRGB,
                    int(right_px - left_px),
                    int(bottom_px - top_px),
                    tile_rgb.tobytes(),
                    False,
                )
                tile_size = (int(pixmap.width), int(pixmap.height))
                expected_size = (right_px - left_px, bottom_px - top_px)
                if tile_size != expected_size:
                    raise RuntimeError(
                        f"page {page_number} tile dimensions changed: "
                        f"expected {expected_size}, got {tile_size}"
                    )
                content = bytes(pixmap.tobytes("png"))
                digest = hashlib.sha256(content).hexdigest()
                staged_path = staged_by_digest.get(digest)
                if staged_path is None:
                    staged_path = image_root / f"{digest}.png"
                    atomic_write_bytes(staged_path, content)
                    transaction.register_file(staged_path)
                    if _image_size_pixels(str(staged_path)) != tile_size:
                        raise RuntimeError(f"staged page tile dimensions changed: {staged_path}")
                    staged_by_digest[digest] = staged_path

                source_key = _normalized_image_source_path(str(staged_path))
                staged_assets[source_key] = _StagedImageAsset(
                    source_path=staged_path,
                    path=staged_path,
                    sha256=digest,
                    size_px=tile_size,
                    source_size_px=tile_size,
                    crop_box_px=(0, 0, tile_size[0], tile_size[1]),
                    # This opaque tile is the complete source page, including
                    # vector and text paint. Keep retained editables beneath it
                    # to avoid double-painting; hiding the image layer exposes
                    # those editable entities.
                    draw_below_editable=False,
                )
                page_width = float(extracted_page.page_data.width)
                page_height = float(extracted_page.page_data.height)
                placements.append(
                    ImagePlacement(
                        page_number=int(page_number),
                        x_mm=float(left_px) / float(full_width) * page_width,
                        y_mm=(float(full_height - bottom_px) / float(full_height) * page_height),
                        width_mm=float(tile_size[0]) / float(full_width) * page_width,
                        height_mm=float(tile_size[1]) / float(full_height) * page_height,
                        path=str(staged_path),
                        xref=0,
                        source_kind="page_raster_alpha_fidelity_fallback",
                        source_instance_count=1,
                        source_bbox_pdf=(
                            float(source_page.rect.x0) + float(left_px) / zoom,
                            float(source_page.rect.y0) + float(top_px) / zoom,
                            float(source_page.rect.x0) + float(right_px) / zoom,
                            float(source_page.rect.y0) + float(bottom_px) / zoom,
                        ),
                        source_number=len(placements) + 1,
                        source_digest=digest,
                        pixel_size=tile_size,
                        alpha_kind="opaque",
                        alpha_bbox_px=(0, 0, tile_size[0], tile_size[1]),
                        alpha_present=False,
                    )
                )
    return placements, staged_assets, effective_dpi


def _terminal_job_safe_dpi(
    extraction: DocumentExtraction,
    page_numbers: Sequence[int],
    requested_dpi: float,
) -> float:
    """Choose one DPI whose projected page tiles fit cumulative job budgets."""

    requested = max(TERMINAL_MIN_DPI, float(requested_dpi or 200.0))
    dimensions: List[Tuple[float, float]] = []
    with safe_open(extraction.pdf_path) as document:
        for page_number in page_numbers:
            source_page = document[int(page_number) - 1]
            width = float(source_page.rect.width)
            height = float(source_page.rect.height)
            if width <= 0.0 or height <= 0.0:
                raise RuntimeError(
                    f"page {page_number} has invalid physical dimensions"
                )
            page_budget_zoom = min(
                math.sqrt(float(TERMINAL_MAX_PAGE_PIXELS) / (width * height)),
                float(TERMINAL_MAX_PAGE_DIMENSION) / width,
                float(TERMINAL_MAX_PAGE_DIMENSION) / height,
            )
            if page_budget_zoom * 72.0 + 1e-9 < TERMINAL_MIN_DPI:
                raise RuntimeError(
                    f"page {page_number} exceeds the safe fidelity-surface resource "
                    f"budget even at {TERMINAL_MIN_DPI:g} DPI"
                )
            dimensions.append((width, height))

    tile_limit = max(64, int(TERMINAL_TILE_PIXELS))

    def projected_usage(dpi: float) -> Tuple[int, int]:
        total_pixels = 0
        total_tiles = 0
        requested_zoom = float(dpi) / 72.0
        for width, height in dimensions:
            pixel_budget_zoom = math.sqrt(
                float(TERMINAL_MAX_PAGE_PIXELS) / (width * height)
            )
            dimension_budget_zoom = min(
                float(TERMINAL_MAX_PAGE_DIMENSION) / width,
                float(TERMINAL_MAX_PAGE_DIMENSION) / height,
            )
            zoom = min(requested_zoom, pixel_budget_zoom, dimension_budget_zoom)
            bounds = (
                fitz.Rect(0.0, 0.0, width, height) * fitz.Matrix(zoom, zoom)
            ).irect
            pixel_width = int(bounds.width)
            pixel_height = int(bounds.height)
            total_pixels += pixel_width * pixel_height
            total_tiles += math.ceil(pixel_width / tile_limit) * math.ceil(
                pixel_height / tile_limit
            )
        return total_pixels, total_tiles

    def fits(dpi: float) -> bool:
        pixels, tiles = projected_usage(dpi)
        return (
            pixels <= TERMINAL_MAX_JOB_PIXELS
            and tiles <= TERMINAL_MAX_JOB_TILES
        )

    if not fits(TERMINAL_MIN_DPI):
        raise RuntimeError(
            "document fidelity-surface resource budget exceeded even at "
            f"{TERMINAL_MIN_DPI:g} DPI; import fewer pages per job"
        )
    if fits(requested):
        return requested

    low = float(TERMINAL_MIN_DPI)
    high = requested
    for _ in range(48):
        midpoint = (low + high) * 0.5
        if fits(midpoint):
            low = midpoint
        else:
            high = midpoint
    return low


def _image_geometry(
    placement: ImagePlacement,
    staged_asset: _StagedImageAsset,
    page_offset_y: float,
) -> Tuple[
    Tuple[float, float],
    Tuple[float, float],
    Tuple[float, float],
    Tuple[float, float],
]:
    """Return insert, per-pixel U/V vectors, and total axis lengths."""

    source_width_px, source_height_px = staged_asset.source_size_px
    crop_left, crop_top, crop_right, crop_bottom = staged_asset.crop_box_px
    if placement.affine_model is not None:
        insert_x, insert_y, u_x, u_y, v_x, v_y = (float(value) for value in placement.affine_model)
        insert = (
            insert_x
            + u_x * (float(crop_left) / float(source_width_px))
            + v_x * (1.0 - float(crop_bottom) / float(source_height_px)),
            insert_y
            + page_offset_y
            + u_y * (float(crop_left) / float(source_width_px))
            + v_y * (1.0 - float(crop_bottom) / float(source_height_px)),
        )
        u_pixel = (u_x / float(source_width_px), u_y / float(source_width_px))
        v_pixel = (v_x / float(source_height_px), v_y / float(source_height_px))
    else:
        unit_width_per_pixel = float(placement.width_mm) / float(source_width_px)
        unit_height_per_pixel = float(placement.height_mm) / float(source_height_px)
        insert = (
            float(placement.x_mm) + crop_left * unit_width_per_pixel,
            float(placement.y_mm)
            + page_offset_y
            + (source_height_px - crop_bottom) * unit_height_per_pixel,
        )
        u_pixel = (unit_width_per_pixel, 0.0)
        v_pixel = (0.0, unit_height_per_pixel)
    size_in_units = (
        math.hypot(*u_pixel) * (crop_right - crop_left),
        math.hypot(*v_pixel) * (crop_bottom - crop_top),
    )
    return insert, u_pixel, v_pixel, size_in_units


def _verify_serialized_image_assets(
    doc: Any,
    expectations: List[_SerializedImageExpectation],
) -> None:
    """Reconcile every normal image placement and owned asset after DXF reopen."""

    verified_asset_digests: Dict[Path, str] = {}
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

        asset_path = _resolve_serialized_asset_path(
            doc,
            str(image_def.dxf.filename or ""),
        )
        if asset_path != expected.asset_path.resolve() or not asset_path.is_file():
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} references a missing or foreign asset"
            )
        actual_asset_sha256 = verified_asset_digests.get(asset_path)
        if actual_asset_sha256 is None:
            actual_asset_sha256 = _file_sha256(asset_path)
            verified_asset_digests[asset_path] = actual_asset_sha256
        if actual_asset_sha256 != expected.asset_sha256:
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} asset hash mismatch"
            )

        actual_insert = tuple(image.dxf.insert)[:2]
        actual_u_pixel = tuple(float(value) for value in tuple(image.dxf.u_pixel)[:2])
        actual_v_pixel = tuple(float(value) for value in tuple(image.dxf.v_pixel)[:2])
        actual_pixels = (
            int(round(float(image_def.dxf.image_size.x))),
            int(round(float(image_def.dxf.image_size.y))),
        )
        if not all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(actual_insert, expected.insert, strict=True)
        ):
            raise RuntimeError(f"serialized image delivery {expected.image_handle} insert changed")
        if not all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
            for left, right in zip(
                actual_u_pixel + actual_v_pixel,
                expected.u_pixel + expected.v_pixel,
                strict=True,
            )
        ):
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} orientation changed"
            )
        if actual_pixels != expected.size_in_pixel:
            raise RuntimeError(
                f"serialized image delivery {expected.image_handle} pixel dimensions changed"
            )


def _pixmap_contains_ink(pixmap: Any) -> bool:
    channels = int(pixmap.n)
    width = int(pixmap.width)
    height = int(pixmap.height)
    if width <= 0 or height <= 0 or channels <= 0:
        return False
    stride = int(getattr(pixmap, "stride", width * channels))
    raw_samples = getattr(pixmap, "samples_mv", None)
    if raw_samples is None:
        raw_samples = pixmap.samples
    rows = np.frombuffer(raw_samples, dtype=np.uint8).reshape(height, stride)
    pixels = rows[:, : width * channels].reshape(height, width, channels)
    sample_channels = pixels[:, :, : min(3, channels)]
    for start in range(0, height, 256):
        block = sample_channels[start : min(height, start + 256)]
        if bool(pixmap.alpha):
            alpha = pixels[
                start : min(height, start + 256),
                :,
                channels - 1,
            ]
            # PyMuPDF exposes premultiplied color channels for alpha pixmaps.
            # Alpha coverage alone is not visible ink: an opaque white page
            # background has alpha 255 but is still visually blank. Composite
            # the premultiplied samples onto white before applying the same
            # visibility threshold used for opaque renders.
            composited = np.minimum(
                block.astype(np.uint16)
                + (255 - alpha.astype(np.uint16))[:, :, np.newaxis],
                255,
            )
            if np.any(composited < 250):
                return True
        elif np.any(block < 250):
            return True
    return False


class _RasterRenderSession:
    """Own source documents and page display lists for one DXF export."""

    def __init__(self) -> None:
        self._source_key: Optional[Tuple[str, str]] = None
        self._page_key: Optional[Tuple[str, str, int]] = None
        self._document: Any = None
        self._page: Any = None
        self._display_list: Any = None

    def __enter__(self) -> "_RasterRenderSession":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        """Release every PyMuPDF object owned by this export session."""

        document = self._document
        self._source_key = None
        self._page_key = None
        self._display_list = None
        self._page = None
        self._document = None
        if document is not None:
            document.close()

    def page(
        self,
        source_pdf: Path,
        source_pdf_sha256: str,
        page_number: int,
    ) -> Tuple[Any, Any]:
        """Return an isolated, export-scoped page display list."""

        resolved_source = str(Path(source_pdf).expanduser().resolve())
        source_digest = str(source_pdf_sha256).strip()
        requested_page = int(page_number)
        if not source_digest:
            raise ValueError("raster render session requires a source digest")
        if requested_page < 1:
            raise ValueError("raster render session page number must be positive")
        source_key = (resolved_source, source_digest)
        page_key = (
            resolved_source,
            source_digest,
            requested_page,
        )
        if self._source_key != source_key:
            self.close()
            document = fitz.open(resolved_source)
            self._source_key = source_key
            self._document = document
        if self._page_key != page_key:
            self._page_key = None
            self._display_list = None
            self._page = None
            try:
                page = self._document.load_page(requested_page - 1)
                display_list = page.get_displaylist()
            except Exception:
                if self._source_key == source_key and self._page_key is None:
                    # Keep a valid source document reusable after an invalid page,
                    # while never retaining a partial page/display-list pair.
                    self._display_list = None
                    self._page = None
                raise
            self._page_key = page_key
            self._page = page
            self._display_list = display_list
        return self._page, self._display_list


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
    raster_session: _RasterRenderSession,
    display_to_model: Optional[Tuple[float, ...]] = None,
    page_offset_y: float = 0.0,
) -> Tuple[TextDeliveryResult, Optional[_PendingRasterAsset]]:
    """Attempt a real item crop as requested or after proven structural failure."""
    attempts = list(delivery.attempts)
    for prior in attempts:
        prior.superseded = True
    attempt = TextDeliveryAttempt(
        source_id=delivery.source_id,
        requested_representation=delivery.requested_representation,
        attempted_representation="raster",
        strategy="pymupdf_opaque_source_item_clip",
    )
    attempts.append(attempt)
    doc = msp.doc
    image = None
    image_def = None
    support_handles: List[str] = []
    try:
        if not delivery.source_id:
            raise ValueError("terminal raster has no stable source identity")
        whitespace_only = not str(getattr(source_text, "text", "") or "").strip()
        requested_raster = _normalized_text_mode(delivery.requested_representation) == "raster"
        if whitespace_only and not requested_raster:
            raise ValueError(
                "terminal raster cannot certify a whitespace-only source item "
                "from unrelated page ink"
            )
        source_bbox = getattr(source_text, "source_bbox_pdf", None)
        if not source_bbox or len(source_bbox) != 4:
            raise ValueError("terminal raster requires an exact source item bbox")
        if display_to_model is None:
            raise ValueError("terminal raster has no bound source page-to-model transform")
        sx0, sy0, sx1, sy1 = [float(value) for value in source_bbox]
        if min(abs(sx1-sx0), abs(sy1-sy0)) <= 0:
            raise ValueError("terminal raster source item bbox is empty")

        page, page_display_list = raster_session.page(
            Path(extraction.pdf_path),
            source_pdf_sha256,
            page_number,
        )
        rotation_matrix = _page_rotation_transform(
            page.rect,
            getattr(page, "rotation_matrix", None),
        )
        from librecad_pdf_importer.raster_geometry import source_raster_bounds
        coverage_bbox = source_raster_bounds(source_text)
        cx0, cy0, cx1, cy1 = coverage_bbox
        coverage_corners = [_transform_pdf_point(x, y, rotation_matrix)
            for x, y in ((cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1))]
        requested_clip = fitz.Rect(min(p[0] for p in coverage_corners),
                                  min(p[1] for p in coverage_corners),
                                  max(p[0] for p in coverage_corners),
                                  max(p[1] for p in coverage_corners))
        clip = requested_clip & page.rect
        if clip.is_empty or clip.is_infinite:
            raise ValueError("terminal raster clip is outside the source page")
        containment_tolerance = max(
            1e-6,
            max(float(page.rect.width), float(page.rect.height), 1.0) * 1e-7,
        )
        source_bbox_clipped = any(
            not math.isclose(
                left,
                right,
                rel_tol=0.0,
                abs_tol=containment_tolerance,
            )
            for left, right in zip(
                (requested_clip.x0, requested_clip.y0, requested_clip.x1, requested_clip.y1),
                (clip.x0, clip.y0, clip.x1, clip.y1),
                strict=True,
            )
        )
        # The source clip selects pixels only. Their physical placement comes
        # from the actual device lattice below, never a text/glyph bbox.
        dpi = max(72, int(raster_dpi or 300))
        zero_ink_confirmation_dpi: Optional[int] = None
        if whitespace_only:
            device_rect = (clip * fitz.Matrix(dpi / 72.0, dpi / 72.0)).irect
            pixel_width, pixel_height = device_rect.width, device_rect.height
            pixmap = fitz.Pixmap(
                fitz.csRGB,
                device_rect,
                True,
            )
            pixmap.clear_with(0)
            pixmap.set_alpha(bytes(pixel_width * pixel_height))
            attempt.strategy = "verified_zero_ink_transparent_item"
        else:
            pixmap = page_display_list.get_pixmap(
                matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0),
                clip=clip,
                colorspace=fitz.csRGB,
                alpha=False,
            )
            if not _pixmap_contains_ink(pixmap):
                # A non-empty text record can legitimately paint no page
                # pixels (render mode 3, clipping paths, optional content,
                # an empty glyph program, or white paint). Confirm at a second,
                # higher resolution before preserving it as transparent output,
                # whether Raster was requested directly or reached as the
                # terminal fallback for another requested representation.
                # Bound the confirmation to protect older hardware.
                max_confirmation_pixels = 8_000_000
                area_points = max(float(clip.width) * float(clip.height), 1e-12)
                dpi_cap = int(math.floor(72.0 * math.sqrt(max_confirmation_pixels / area_points)))
                zero_ink_confirmation_dpi = min(dpi * 2, 1200, dpi_cap)
                if zero_ink_confirmation_dpi <= dpi:
                    raise ValueError(
                        "terminal raster zero-ink confirmation exceeds safe pixel budget"
                    )
                confirmation = page_display_list.get_pixmap(
                    matrix=fitz.Matrix(
                        zero_ink_confirmation_dpi / 72.0,
                        zero_ink_confirmation_dpi / 72.0,
                    ),
                    clip=clip,
                    alpha=True,
                )
                if _pixmap_contains_ink(confirmation):
                    pixmap = page_display_list.get_pixmap(
                        matrix=fitz.Matrix(
                            zero_ink_confirmation_dpi / 72.0,
                            zero_ink_confirmation_dpi / 72.0,
                        ),
                        clip=clip,
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )
                    if not _pixmap_contains_ink(pixmap):
                        raise ValueError(
                            "terminal raster higher-resolution opaque render contains no visible source ink"
                        )
                    dpi = zero_ink_confirmation_dpi
                    attempt.strategy = "pymupdf_opaque_source_item_clip_confirmed_at_higher_resolution"
                else:
                    attempt.strategy = "verified_source_zero_ink_transparent_item"
        if pixmap.width <= 0 or pixmap.height <= 0:
            raise ValueError("terminal raster rendered zero pixels")
        from librecad_pdf_importer.raster_geometry import raster_pixel_geometry
        pixel_geometry = raster_pixel_geometry(
            (pixmap.x, pixmap.y), (pixmap.width, pixmap.height), dpi,
            display_to_model, page_offset_y,
        )
        target_x0, target_y0, target_x1, target_y1 = pixel_geometry["target_bbox_model"]
        image_insert = pixel_geometry["image_insert"]
        image_u = pixel_geometry["image_u_pixel"]
        image_v = pixel_geometry["image_v_pixel"]
        visible_placed_width = math.hypot(*image_u) * pixmap.width
        visible_placed_height = math.hypot(*image_v) * pixmap.height
        png = bytes(pixmap.tobytes("png"))
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("terminal raster output is not a PNG")
        contains_ink = _pixmap_contains_ink(pixmap)
        if whitespace_only and contains_ink:
            raise ValueError("requested whitespace raster contains unrelated visible ink")
        verified_source_zero_ink = bool(
            not whitespace_only
            and not contains_ink
            and zero_ink_confirmation_dpi is not None
        )
        if not whitespace_only and not contains_ink and not verified_source_zero_ink:
            raise ValueError("terminal raster crop contains no visible source ink")

        if whitespace_only or verified_source_zero_ink:
            attempt.strategy = (
                "verified_whitespace_zero_ink_omission"
                if whitespace_only
                else "verified_source_zero_ink_omission"
            )
            attempt.type_verified = True
            attempt.visual_verified = True
            attempt.cleanup_verified = True
            attempt.evidence = {
                "source_pdf_path": str(Path(extraction.pdf_path).expanduser().resolve()),
                "source_pdf_sha256": source_pdf_sha256,
                "source_page_number": int(page_number),
                "source_id": delivery.source_id,
                "source_clip_pdf": [
                    float(clip.x0),
                    float(clip.y0),
                    float(clip.x1),
                    float(clip.y1),
                ],
                "source_bbox_pdf": [sx0, sy0, sx1, sy1],
                "source_raster_coverage_bbox_pdf": list(coverage_bbox),
                "source_bbox_clipped_to_page": bool(source_bbox_clipped),
                "source_to_display_rotation": [float(value) for value in rotation_matrix],
                "target_bbox_model": [target_x0, target_y0, target_x1, target_y1],
                **pixel_geometry,
                "source_pixel_lattice_verified": True,
                "pixel_size": [int(pixmap.width), int(pixmap.height)],
                "raster_dpi": dpi,
                "zero_ink_confirmation_dpi": zero_ink_confirmation_dpi,
                "visible_ink_expected": False,
                "visible_ink_verified": False,
                "zero_ink_verified": True,
                "zero_ink_omitted": True,
                "host_safe_opaque_image_required": False,
                "anchor_verified": True,
                "size_verified": True,
            }
            attempt.delivery_verified = True
            attempt.outcome = "verified"
            return (
                TextDeliveryResult(
                    source_id=delivery.source_id,
                    requested_representation=delivery.requested_representation,
                    final_representation="raster",
                    verified=True,
                    entity_handles=[],
                    support_entity_handles=[],
                    attempts=attempts,
                ),
                None,
            )

        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", delivery.source_id)
        asset_path = asset_root / f"{safe_id}.png"
        image_def = doc.add_image_def(
            filename=_serialized_asset_filename(asset_path, asset_root.parent.parent),
            size_in_pixel=(int(pixmap.width), int(pixmap.height)),
            name=f"BCS_TEXT_{safe_id}"[:255],
        )
        image = msp.add_image(
            image_def,
            insert=image_insert,
            size_in_units=(visible_placed_width, visible_placed_height),
            dxfattribs={"layer": layer_name},
        )
        image.dxf.u_pixel = (*image_u, 0.0)
        image.dxf.v_pixel = (*image_v, 0.0)
        image.dxf.flags = int(image.dxf.flags or 0) | 8
        image_handle = str(image.dxf.handle or "")
        image_def_handle = str(image_def.dxf.handle or "")
        reactor_handle = str(image.dxf.image_def_reactor_handle or "")
        support_handles = [handle for handle in (image_def_handle, reactor_handle) if handle]
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
            for left, right in zip(actual_insert, image_insert, strict=True)
        )
        size_ok = math.isclose(
            actual_width, visible_placed_width, rel_tol=1e-8, abs_tol=1e-9
        ) and math.isclose(actual_height, visible_placed_height, rel_tol=1e-8, abs_tol=1e-9)
        attempt.type_verified = image.dxftype() == "IMAGE"
        visible_ink_expected = not (whitespace_only or verified_source_zero_ink)
        content_ok = not contains_ink if not visible_ink_expected else contains_ink
        axes_ok = all(math.isclose(a, b, rel_tol=0.0, abs_tol=1e-12)
                      for a, b in zip(tuple(image.dxf.u_pixel) + tuple(image.dxf.v_pixel),
                                      (*image_u, 0.0, *image_v, 0.0), strict=True))
        attempt.visual_verified = insert_ok and size_ok and axes_ok and content_ok
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
            "source_clip_pdf": [
                float(clip.x0),
                float(clip.y0),
                float(clip.x1),
                float(clip.y1),
            ],
            "source_bbox_pdf": [sx0, sy0, sx1, sy1],
                "source_raster_coverage_bbox_pdf": list(coverage_bbox),
            "source_bbox_clipped_to_page": bool(source_bbox_clipped),
            "source_to_display_rotation": [float(value) for value in rotation_matrix],
            "target_bbox_model": [
                target_x0,
                target_y0,
                target_x1,
                target_y1,
            ],
            **pixel_geometry,
            "source_pixel_lattice_verified": True,
            "pixel_size": [int(pixmap.width), int(pixmap.height)],
            "raster_dpi": dpi,
            "zero_ink_confirmation_dpi": zero_ink_confirmation_dpi,
            "visible_ink_expected": visible_ink_expected,
            "visible_ink_verified": bool(contains_ink),
            "zero_ink_verified": bool(not visible_ink_expected and not contains_ink),
            "zero_ink_omitted": False,
            "host_safe_opaque_image_required": True,
            "host_safe_opaque_image_verified": not bool(pixmap.alpha),
            "anchor_verified": insert_ok,
            "size_verified": size_ok,
        }
        if not (attempt.type_verified and attempt.visual_verified and attempt.cleanup_verified):
            raise ValueError("terminal raster failed type, visual, or ownership verification")
        attempt.delivery_verified = True
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
        if image is not None:
            handle = str(image.dxf.handle or "")
            try:
                msp.delete_entity(image)
                attempt.removed_entity_handles.append(handle)
            except Exception:
                pass
        if image_def is not None:
            handles = [str(image_def.dxf.handle or "")] + support_handles[1:]
            try:
                doc.objects.delete_entity(image_def)
                attempt.removed_entity_handles.extend(
                    handle
                    for handle in handles
                    if handle and handle not in attempt.removed_entity_handles
                )
            except Exception:
                pass
        attempt.entity_handles = []
        attempt.support_entity_handles = []
        attempt.outcome = "failed"
        attempt.cleanup_verified = all(
            doc.entitydb.get(handle) is None
            or not getattr(doc.entitydb.get(handle), "is_alive", True)
            for handle in attempt.created_entity_handles
        )
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


def _failed_text_item_attempt(
    delivery: TextDeliveryResult,
    attempted_representation: str,
    strategy: str,
    reason: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> TextDeliveryResult:
    """Record one failed, entity-free attempt and keep the item unverified."""

    attempts = list(delivery.attempts)
    attempts.append(
        TextDeliveryAttempt(
            source_id=delivery.source_id,
            requested_representation=delivery.requested_representation,
            attempted_representation=attempted_representation,
            strategy=strategy,
            outcome="failed",
            reason=reason,
            cleanup_verified=True,
            evidence=dict(evidence or {}),
        )
    )
    return TextDeliveryResult(
        source_id=delivery.source_id,
        requested_representation=delivery.requested_representation,
        final_representation=None,
        verified=False,
        attempts=attempts,
        failure_reason=reason,
    )


def _build_text_item(
    text_item: Any,
    msp: Any,
    layer_name: str,
    config: Any,
    *,
    forced_reason: Optional[str] = None,
    **builder_options: Any,
) -> TextDeliveryResult:
    """Run the text builder for one item without ever raising for that item.

    A builder crash is an unproven failure of this item, and a forced re-export
    (the item failed post-write verification) skips the builder; either way the
    caller receives one failed attempt and degrades the item.
    """

    evidence: Dict[str, Any] = {}
    if forced_reason is None:
        item_entity_start = len(msp.entity_space.entities)
        try:
            return build_text(text_item, msp, layer_name, config, **builder_options)
        except Exception as exc:  # noqa: BLE001 - one item never costs the sheet
            for stray in list(msp.entity_space.entities[item_entity_start:]):
                msp.delete_entity(stray)
            strategy, reason = "text_builder_exception", f"{type(exc).__name__}: {exc}"
            # This may be OUR bug: keep where it was raised, not only what it said.
            evidence = {
                "exception_type": type(exc).__name__,
                "traceback_tail": bounded_traceback(exc),
            }
    else:
        strategy, reason = "serialized_delivery_verification", forced_reason
    requested = _normalized_text_mode(getattr(config, "text_mode", "text"))
    return _failed_text_item_attempt(
        TextDeliveryResult(
            source_id=_source_id(text_item),
            requested_representation=requested,
            final_representation=None,
            verified=False,
        ),
        requested,
        strategy,
        reason,
        evidence,
    )


def _item_raster_proof_complete(
    delivery: TextDeliveryResult,
    *,
    source_pdf_sha256: Optional[str],
    page_number: int,
) -> bool:
    """A kept item IMAGE must carry the exact opaque pixel-lattice proof."""

    if not delivery.entity_handles:
        return True
    evidence = delivery.attempts[-1].evidence
    return bool(
        evidence.get("source_pixel_lattice_verified") is True
        and evidence.get("host_safe_opaque_image_verified") is True
        and evidence.get("source_pdf_sha256") == source_pdf_sha256
        and evidence.get("source_page_number") == page_number
    )


def _discard_item_raster(msp: Any, delivery: TextDeliveryResult) -> TextDeliveryResult:
    """Remove an item IMAGE that lacks its proof so the next rung can run."""

    doc = msp.doc
    attempt = delivery.attempts[-1]
    for handle in [*delivery.entity_handles, *delivery.support_entity_handles]:
        entity = doc.entitydb.get(str(handle))
        if entity is None or not getattr(entity, "is_alive", True):
            continue
        try:
            if str(handle) in delivery.entity_handles:
                msp.delete_entity(entity)
            else:
                doc.objects.delete_entity(entity)
        except Exception:
            continue
    attempt.removed_entity_handles = [
        handle
        for handle in attempt.created_entity_handles
        if doc.entitydb.get(handle) is None
        or not getattr(doc.entitydb.get(handle), "is_alive", True)
    ]
    attempt.entity_handles = []
    attempt.support_entity_handles = []
    attempt.delivery_verified = False
    attempt.outcome = "failed"
    attempt.reason = "ValueError: item raster has no exact opaque pixel-lattice proof"
    attempt.cleanup_verified = set(attempt.removed_entity_handles) == set(
        attempt.created_entity_handles
    )
    return TextDeliveryResult(
        source_id=delivery.source_id,
        requested_representation=delivery.requested_representation,
        final_representation=None,
        verified=False,
        attempts=list(delivery.attempts),
        failure_reason=attempt.reason,
    )


def _serialized_mismatch_item(
    message: str,
    deliveries: List[Dict[str, Any]],
) -> Optional[Tuple[str, int]]:
    """Name the one delivery a post-write failure is confined to, and its next rung.

    Structural failures (duplicate source IDs, session authority) name no single
    delivery and stay fatal.
    """

    matches = [
        item
        for item in deliveries
        if str(item.get("source_id") or "")
        and message.startswith(f"serialized text delivery {item.get('source_id')}: ")
    ]
    if len(matches) != 1:
        return None
    failed = matches[0]
    if failed.get("dropped") is True:
        return None
    if failed.get("degraded") is True and failed.get("final_representation") == "text":
        next_rung = _TEXT_DEGRADE_RUNG_DROP
    elif failed.get("final_representation") == "raster":
        next_rung = _TEXT_DEGRADE_RUNG_TEXT
    else:
        next_rung = _TEXT_DEGRADE_RUNG_RASTER
    return str(failed.get("source_id")), next_rung


def _serialized_mismatch_rungs(
    exc: RuntimeError,
    deliveries: List[Dict[str, Any]],
) -> Optional[Dict[str, Tuple[int, str]]]:
    """Every mismatching delivery's forced rung, or None when any one is structural."""

    forced: Dict[str, Tuple[int, str]] = {}
    for message in getattr(exc, "messages", None) or [str(exc)]:
        named = _serialized_mismatch_item(message, deliveries)
        if named is None:
            return None
        forced[named[0]] = (named[1], message)
    return forced


def export_to_dxf(
    extraction: DocumentExtraction,
    output_path: str,
    options: Optional[DxfExportOptions] = None,
) -> DxfExportResult:
    try:
        return _export_to_dxf_once(extraction, output_path, options)
    except _SerializedTextItemMismatch as exc:
        # Identifiable items failed their post-write check. Re-export ONCE with
        # all of them forced down the degrade ladder instead of losing the sheet.
        forced_text_rungs = exc.forced_text_rungs
    try:
        return _export_to_dxf_once(extraction, output_path, options, forced_text_rungs)
    except _SerializedTextItemMismatch as exc:
        raise ImportStopped(
            f"{exc} (still failing after one forced-degrade re-export; no DXF was written)"
        ) from exc


def _export_to_dxf_once(
    extraction: DocumentExtraction,
    output_path: str,
    options: Optional[DxfExportOptions] = None,
    forced_text_rungs: Optional[Mapping[str, Tuple[int, str]]] = None,
) -> DxfExportResult:
    transaction = _AssetTransaction()
    with _RasterRenderSession() as raster_session:
        try:
            result = _export_to_dxf_impl(
                extraction,
                output_path,
                options,
                asset_transaction=transaction,
                raster_session=raster_session,
                forced_text_rungs=forced_text_rungs,
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
    raster_session: _RasterRenderSession,
    forced_text_rungs: Optional[Mapping[str, Tuple[int, str]]] = None,
) -> DxfExportResult:
    opts = options or DxfExportOptions()
    forced_text_rungs = forced_text_rungs or {}
    installation = resolve_librecad_installation(opts.librecad_executable)
    librecad_contract_executable = (
        installation.executable_path
        if installation is not None
        else str(opts.librecad_executable or "")
    )
    output = Path(output_path).expanduser().resolve()
    source_pdf = Path(extraction.pdf_path).expanduser().resolve()
    source_pdf_sha256: Optional[str] = None
    session_token = uuid.uuid4().hex
    asset_parent = output.with_name(f"{output.stem}_assets")
    asset_root = asset_parent / session_token
    prior_owned_sessions = _owned_sessions_referenced_by_output(output, asset_parent)
    pending_raster_assets: List[_PendingRasterAsset] = []
    embedded_font_staging_faults: Dict[str, str] = {}
    embedded_font_paths = (
        _stage_embedded_font_assets(
            extraction,
            asset_root,
            asset_transaction,
            embedded_font_staging_faults,
        )
        if opts.include_text
        else {}
    )
    staged_image_assets, omitted_image_sources, compositing_pages = (
        _stage_image_assets(extraction, asset_root, asset_transaction)
        if opts.include_images
        else ({}, set(), set())
    )
    terminal_page_tiles: Dict[int, List[ImagePlacement]] = {}
    terminal_job_pixels = 0
    terminal_job_tiles = 0
    terminal_job_asset_paths: set[Path] = set()
    if compositing_pages:
        requested_raster_dpi = int(
            getattr(opts.provenance_opts, "raster_dpi", 200)
            if opts.provenance_opts is not None
            else 200
        )
        ordered_compositing_pages = sorted(compositing_pages)
        raster_dpi = _terminal_job_safe_dpi(
            extraction,
            ordered_compositing_pages,
            requested_raster_dpi,
        )
        for page_number in ordered_compositing_pages:
            tiles, tile_assets, effective_dpi = _render_terminal_page_tiles(
                extraction,
                page_number,
                raster_dpi,
                asset_root,
                asset_transaction,
            )
            terminal_job_tiles += len(tiles)
            terminal_job_pixels += sum(
                int(placement.pixel_size[0]) * int(placement.pixel_size[1])
                for placement in tiles
                if placement.pixel_size is not None
            )
            terminal_job_asset_paths.update(asset.path.resolve() for asset in tile_assets.values())
            terminal_job_asset_bytes = sum(
                path.stat().st_size for path in terminal_job_asset_paths
            )
            if (
                terminal_job_pixels > TERMINAL_MAX_JOB_PIXELS
                or terminal_job_tiles > TERMINAL_MAX_JOB_TILES
                or terminal_job_asset_bytes > TERMINAL_MAX_JOB_ASSET_BYTES
            ):
                raise RuntimeError(
                    "document fidelity-surface resource budget exceeded; import "
                    "fewer pages per job"
                )
            terminal_page_tiles[page_number] = tiles
            staged_image_assets.update(tile_assets)
            extracted_page = next(
                page for page in extraction.pages if int(page.page_data.page_number) == page_number
            )
            prior_reason = str(extracted_page.resolved_reason or "").strip()
            fallback_reason = (
                "compositing-required transparency delivered as a host-safe "
                "opaque page fidelity surface"
            )
            if effective_dpi + 1e-9 < float(requested_raster_dpi):
                fallback_reason += (
                    f" at resource-bounded {effective_dpi:.1f} DPI "
                    f"(requested {requested_raster_dpi} DPI)"
                )
            extracted_page.resolved_mode = "hybrid"
            if not forced_text_rungs:  # the forced re-export's first pass already said it
                extracted_page.resolved_reason = (
                    f"{prior_reason}; {fallback_reason}" if prior_reason else fallback_reason
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
    positioned_translation_anchors: Dict[str, _PositionedTranslationAnchor] = {}
    seen_text_source_ids: set[str] = set()
    seen_text_entity_handles: set[str] = set()
    search_text_enabled = bool(
        opts.searchable_text and opts.include_text and opts.text_mode != "none"
    )
    # (delivery record, placed item, known cap-height ratio, page number, paint key)
    pending_search_text: List[Tuple[Any, ...]] = []
    serialized_image_expectations: List[_SerializedImageExpectation] = []
    background_image_handles: List[str] = []
    foreground_image_handles: List[str] = []
    if opts.provenance_opts is not None:
        # This transient export state is consumed by write_import_report after
        # the DXF is built, so stale data from a prior export cannot lie.
        opts.provenance_opts._text_mode_fallbacks = []  # noqa: B010
        opts.provenance_opts._delivered_text_entity_counts = {}  # noqa: B010
        opts.provenance_opts._text_representation_deliveries = []  # noqa: B010
        opts.provenance_opts._searchable_text_companions = {}  # noqa: B010
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
        opts.provenance_opts._searchable_text_companions = (  # noqa: B010
            searchable_text_companions(text_deliveries, enabled=search_text_enabled)
        )
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

    cancel_requested = getattr(opts.provenance_opts, "_cancel_requested", None)
    progress_callback = getattr(opts.provenance_opts, "_progress_callback", None)
    source_dash_expectations = []
    final_paint_records = []
    final_paint_expectations = []
    final_paint_stroke_handles = set()
    source_paint_keys = {}
    has_source_image_order = False
    for page_position, page in enumerate(extraction.pages, start=1):
        check_cancel(cancel_requested, f"before exporting page {page.page_data.page_number}")
        report_progress(
            progress_callback,
            f"Building source page {page.page_data.page_number} "
            f"({page_position}/{len(extraction.pages)})",
        )
        # Apply page stacking offset to all coordinates
        dy = _stack_offset_y
        page_w = float(page.page_data.width or 0.0)
        page_h = float(page.page_data.height or 0.0)
        # Seed extents from the page frame so host auto-fit still works even
        # when selected export mode yields no drawable entities on that page.
        _track_xy(0.0, 0.0 + dy)
        _track_xy(page_w, page_h + dy)

        page_entity_start = len(msp.entity_space.entities)
        paint_order = getattr(page, "image_paint_order", None)
        if not opts.include_images:
            paint_order = None
        if int(page.page_data.page_number) in compositing_pages:
            paint_order = None  # Existing exact page-fidelity surface contract.
        has_source_image_order = has_source_image_order or paint_order is not None
        final_paints = [] if is_r12 or int(page.page_data.page_number) in compositing_pages else page.final_rect_paints
        final_by_id = {row["primitive_id"]: row for row in final_paints}
        if len(final_by_id) != len(final_paints):
            raise RuntimeError("Final paint source identity is not unique")
        final_entities = {}
        page_raster_handles = []
        primitive_entity_start = page_entity_start
        previous_primitive_key = None
        previous_primitive_id = None

        def record_primitive_entities(start, key, primitive_id, _order=paint_order,
                                      _page=page_position, _final=final_by_id, _entities=final_entities):
            if primitive_id in _final:
                _entities[primitive_id] = list(msp.entity_space.entities[start:])
            if _order is not None and key is not None:
                for entity in msp.entity_space.entities[start:]:
                    source_paint_keys[str(entity.dxf.handle)] = (_page, key)

        clip_fill_groups = {}
        for primitive in page.page_data.primitives:
            group_id = getattr(primitive, "clip_fill_group_id", None)
            if group_id:
                clip_fill_groups.setdefault(group_id, []).append(primitive)
        emitted_clip_fills = set()
        clip_fill_rows = None  # source rows by group id, built on the first failed fill
        page.clip_fill_build_drops = []  # this export's own; an earlier export's are stale
        for primitive_index, primitive in enumerate(page.page_data.primitives, start=1):
            record_primitive_entities(primitive_entity_start, previous_primitive_key, previous_primitive_id)
            primitive_entity_start = len(msp.entity_space.entities)
            previous_primitive_id = primitive.id
            previous_primitive_key = (
                paint_order.primitive_keys[primitive.id] if paint_order is not None else None
            )
            if primitive_index % 64 == 0:
                check_cancel(cancel_requested, "active page vector build")
                report_progress(
                    progress_callback,
                    f"Building source page {page.page_data.page_number}: "
                    f"vectors {primitive_index}/{len(page.page_data.primitives)}",
                )
            stroke_rgb = primitive.stroke_color
            fill_rgb = primitive.fill_color
            final_paint = final_by_id.get(primitive.id)
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

            source_dash = getattr(page, "source_line_dashes", {}).get(primitive.id)
            if opts.map_dashes and source_dash is not None:
                expected = _add_source_dash_block(doc, msp, primitive, source_dash, attribs, dy)
                source_dash_expectations.append(expected)
                for point in primitive.points:
                    _track_xy(float(point[0]), float(point[1])+dy)
                entity_count += 1
                continue
            if opts.map_dashes:
                ltype = _linetype_from_dash(doc, primitive.dash_pattern, dash_cache)
                if ltype:
                    attribs["linetype"] = ltype
                    ltscale = _linetype_scale_for_dash(primitive.dash_pattern)
                    if ltscale is not None and not is_r12:
                        attribs["ltscale"] = ltscale

            # Helper to offset a point by the page stacking offset
            def _ofs(pt, _dy=dy):
                return (pt[0], pt[1] + _dy)

            offset_pts = [_ofs(point) for point in (primitive.points or [])]
            clip_group_id = getattr(primitive, "clip_fill_group_id", None)
            if clip_group_id:
                if clip_group_id in emitted_clip_fills:
                    continue
                emitted_clip_fills.add(clip_group_id)
                members = clip_fill_groups[clip_group_id]
                even_odd = bool(getattr(primitive, "clip_fill_even_odd", False))
                # One clipped fill that cannot be built is left out and reported;
                # it never costs the page or the document.
                try:
                    if any(
                        member.fill_color != fill_rgb
                        or member.stroke_color is not None
                        or bool(getattr(member, "clip_fill_even_odd", False)) != even_odd
                        for member in members
                    ):
                        raise RuntimeError(f"clipped fill {clip_group_id} has inconsistent paint metadata")
                    if paint_order is not None and any(
                        paint_order.primitive_keys[member.id] != previous_primitive_key
                        for member in members
                    ):
                        raise RuntimeError(f"clipped fill {clip_group_id} crosses an image paint boundary")
                    contours = [[_ofs(point) for point in member.points] for member in members]
                    fills = _add_compound_filled_paths(
                        msp, contours, fill_rgb, fill_attribs,
                        is_r12=is_r12, even_odd=even_odd,
                    )
                except ActivePageCancelled:
                    raise
                except Exception as exc:
                    # Nothing of the failed fill stays behind in the drawing.
                    stale = msp.entity_space.entities[primitive_entity_start:]
                    del msp.entity_space.entities[primitive_entity_start:]
                    for entity in stale:
                        doc.entitydb.delete_entity(entity)
                    if clip_fill_rows is None:
                        clip_fill_rows = {
                            row.get("bcs_clip_fill_group_id"): row
                            for row in getattr(page.page_data, "_source_drawings", None) or ()
                            if row.get("bcs_compound_clip_fill")
                        }
                    page.clip_fill_build_drops.append(host_clip_fill_issue(
                        page.page_data.page_number, clip_fill_rows.get(clip_group_id), exc,
                        seqno=primitive.source_draw_order,
                    ))
                    continue
                entity_count += len(fills)
                for contour in contours:
                    for px, py in contour:
                        _track_xy(float(px), float(py))
                continue
            if final_paint is not None:
                from .final_rect_paint import bind_metadata, image_style_snapshot, render_uniform_source_paint
                png, renderer_proof = render_uniform_source_paint(
                    final_paint["fill_rgb"], final_paint["fill_opacity"])
                x0, y0, x1, y1 = map(float, final_paint["model_bounds"])
                if not all(math.isfinite(v) for v in (x0, y0, x1, y1)) or x1 <= x0 or y1 <= y0:
                    raise RuntimeError("Final source paint bounds are invalid")
                safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(primitive.id))
                asset_path = asset_root / f"final_paint_{page.page_data.page_number}_{safe_id}.png"
                image_def = doc.add_image_def(
                    filename=_serialized_asset_filename(asset_path, asset_root.parent.parent),
                    size_in_pixel=(16, 16))
                image = msp.add_image(image_def, insert=(x0, y0+dy),
                                      size_in_units=(x1-x0, y1-y0), dxfattribs={"layer": layer})
                image.dxf.flags = int(image.dxf.flags or 0) | 8
                if source_pdf_sha256 is None:
                    source_pdf_sha256 = _file_sha256(source_pdf)
                record = {"schema": "bcs.final-source-rectangle-paint/1",
                          **final_paint, "source_pdf_sha256": source_pdf_sha256,
                          "source_page_number": int(page.page_data.page_number),
                          "export_page_offset_y": dy, "image_handle": str(image.dxf.handle),
                          "asset_path": str(asset_path), "asset_sha256": hashlib.sha256(png).hexdigest(),
                          "renderer_proof": renderer_proof,
                          "representation": "non-text native IMAGE alpha paint; source stroke retained"}
                metadata = bind_metadata(image, record)
                final_paint_records.append(record)
                final_paint_expectations.append({"image_handle": str(image.dxf.handle),
                                                "metadata_json": metadata, "strokes": [],
                                                "image_style": image_style_snapshot(image),
                                                "primitive_id": primitive.id})
                pending_raster_assets.append(_PendingRasterAsset(asset_path, png))
                serialized_image_expectations.append(_SerializedImageExpectation(
                    image_handle=str(image.dxf.handle), image_def_handle=str(image_def.dxf.handle),
                    asset_path=asset_path, asset_sha256=record["asset_sha256"],
                    insert=(x0, y0+dy), u_pixel=((x1-x0)/16, 0), v_pixel=(0, (y1-y0)/16),
                    size_in_pixel=(16, 16)))
                image_count += 1
                entity_count += 1
                fill_rgb = None  # The qualified fill is represented by the IMAGE above.

            page_background_fill = _is_redundant_white_page_fill(
                primitive,
                page_width=page_w,
                page_height=page_h,
            )
            if (
                fill_rgb is not None
                and not page_background_fill
                and _filled_path_has_visible_area(offset_pts)
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

        record_primitive_entities(primitive_entity_start, previous_primitive_key, previous_primitive_id)

        if opts.include_text and opts.text_mode != "none":
            text_cfg = ImportConfig.auto()
            text_cfg.text_mode = opts.text_mode
            text_cfg._embedded_font_asset_paths = dict(embedded_font_paths)  # noqa: B010
            # Per-asset environment faults, so an item whose exact font could
            # not be written descends with a reason instead of aborting.
            text_cfg._embedded_font_staging_faults = dict(  # noqa: B010
                embedded_font_staging_faults
            )
            text_cfg._restore_embedded_font_asset = (  # noqa: B010
                lambda asset_id: _restore_embedded_font_asset(
                    extraction,
                    asset_id,
                    embedded_font_paths,
                    asset_transaction,
                )
            )
            for text_index, text in enumerate(page.page_data.text_items, start=1):
                check_cancel(cancel_requested, "active page text build")
                if text_index == 1 or text_index % 16 == 0:
                    report_progress(
                        progress_callback,
                        f"Building source page {page.page_data.page_number}: "
                        f"text {text_index}/{len(page.page_data.text_items)}",
                    )
                layer = _layer_name(page.page_data.page_number, "TEXT", None, opts)
                _ensure_layer(doc, layer, None)
                ti = text
                if dy != 0.0:
                    ti = _translate_positioned_text_for_page(text, dy)
                forced_rung = forced_text_rungs.get(_source_id(ti))
                delivery = _build_text_item(
                    ti,
                    msp,
                    layer,
                    text_cfg,
                    is_r12=is_r12,
                    target_app="librecad",
                    librecad_executable=librecad_contract_executable,
                    dxf_version=dxf_ver,
                    return_delivery_result=True,
                    forced_reason=forced_rung[1] if forced_rung else None,
                )
                if not isinstance(delivery, TextDeliveryResult):
                    raise RuntimeError("text builder returned no delivery evidence")
                # The builder's classification is kept as evidence; only its
                # consequence changed. One unverified item degrades down the ladder
                # (item raster -> visible degraded TEXT -> reported drop) and the
                # sheet still exports. Only the old authorized, proven hop to a
                # verified item raster is still certified.
                unverified = not delivery.verified or not delivery.final_representation
                if unverified and not delivery.source_id:
                    text_deliveries.append(delivery.to_dict())
                    _sync_text_evidence()
                    raise TextRepresentationDeliveryError(
                        f"unknown text item: {delivery.failure_reason}",
                        delivery,
                    )
                degrade: Optional[Dict[str, Any]] = None
                certified_hop = bool(delivery.terminal_fallback_authorized)
                raster_requested = certified_hop and not delivery.attempts
                degrade_rung = forced_rung[0] if forced_rung else _TEXT_DEGRADE_RUNG_RASTER
                if unverified:
                    degrade = {
                        "degraded": True,
                        "dropped": False,
                        "degrade_policy": _TEXT_DEGRADE_POLICY,
                        "proof_class": _text_proof_class(delivery),
                        "degrade_reason": delivery.failure_reason
                        or "all representation attempts failed",
                        "source_text": str(getattr(text, "text", "") or ""),
                        "source_page_number": int(page.page_data.page_number),
                    }
                    # On the record itself: the report's fallback block may be
                    # describing the sheet's verified fallbacks instead.
                    degrade["fallback_reason_code"] = _fallback_reason_code(
                        delivery, degrade["proof_class"]
                    )
                    if degrade_rung == _TEXT_DEGRADE_RUNG_RASTER and source_pdf_sha256 is None:
                        try:
                            source_pdf_sha256 = _file_sha256(source_pdf)
                        except OSError as exc:
                            delivery = _failed_text_item_attempt(
                                delivery,
                                "raster",
                                "pymupdf_opaque_source_item_clip",
                                f"{type(exc).__name__}: {exc}",
                            )
                if (
                    unverified
                    and degrade_rung == _TEXT_DEGRADE_RUNG_RASTER
                    and source_pdf_sha256 is not None
                ):
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
                        raster_session=raster_session,
                        display_to_model=page.display_to_model,
                        page_offset_y=dy,
                    )
                    if delivery.verified and not _item_raster_proof_complete(
                        delivery,
                        source_pdf_sha256=source_pdf_sha256,
                        page_number=page.page_data.page_number,
                    ):
                        # Missing raster proof costs this rung, not the sheet.
                        delivery, pending_asset = _discard_item_raster(msp, delivery), None
                    if pending_asset is not None:
                        pending_raster_assets.append(pending_asset)
                if delivery.verified and delivery.final_representation and certified_hop:
                    degrade = None
                if not delivery.verified or not delivery.final_representation:
                    if raster_requested and delivery.failure_reason:
                        # Requested Raster has no builder failure: the render failed.
                        degrade["degrade_reason"] = delivery.failure_reason
                    if degrade_rung <= _TEXT_DEGRADE_RUNG_TEXT:
                        degraded_layer = _layer_name(
                            page.page_data.page_number, "TEXT_DEGRADED", None, opts
                        )
                        new_layer = not doc.layers.has_entry(degraded_layer)
                        _ensure_layer(doc, degraded_layer, None)
                        delivery = _attempt_degraded_text(
                            delivery, ti, msp, degraded_layer, is_r12=is_r12
                        )
                        if new_layer and not delivery.final_representation:
                            doc.layers.remove(degraded_layer)
                    degrade["dropped"] = not delivery.final_representation
                positioned_anchor = None if degrade else _bind_positioned_page_translation(
                    delivery,
                    text,
                    ti,
                    dy=dy,
                    doc=doc,
                )
                if delivery.source_id in seen_text_source_ids:
                    raise ImportStopped(
                        f"{delivery.source_id}: duplicate stable text source identity"
                    )
                duplicate_handles = seen_text_entity_handles.intersection(delivery.entity_handles)
                if duplicate_handles:
                    raise ImportStopped(
                        f"{delivery.source_id}: duplicate delivered DXF handles "
                        f"{sorted(duplicate_handles)}"
                    )
                seen_text_source_ids.add(delivery.source_id)
                seen_text_entity_handles.update(delivery.entity_handles)
                if positioned_anchor is not None:
                    if delivery.source_id in positioned_translation_anchors:
                        raise ImportStopped(
                            f"{delivery.source_id}: duplicate positioned anchor"
                        )
                    positioned_translation_anchors[delivery.source_id] = positioned_anchor
                text_deliveries.append(delivery.to_dict())
                if degrade is not None:
                    # Loud by construction: never verified, always a fallback.
                    text_deliveries[-1].update(degrade, verified=False, fallback_used=True)

                if paint_order is not None:
                    # Verified item raster pixels already contain the final PDF
                    # appearance at that footprint, including later paints.
                    paint_key = (
                        len(paint_order.image_seqnos) * 2 + 2
                        if delivery.final_representation == "raster"
                        else paint_order.text_keys[text.id]
                    )
                    for handle in delivery.entity_handles:
                        source_paint_keys[str(handle)] = (page_position, paint_key)
                if search_text_enabled:
                    # The delivery is settled. Its hidden companion is written
                    # after every page, so no certified handle moves and no
                    # builder rung ever meets the companion's style or layer.
                    pending_search_text.append(
                        (
                            text_deliveries[-1],
                            ti,
                            _known_cap_height_ratio(delivery),
                            int(page.page_data.page_number),
                            (page_position, paint_key if paint_order is not None else 0),
                        )
                    )
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
                    # The exact opaque pixel-lattice proof was required above,
                    # where a crop without it cost that rung instead of the sheet.
                    page_raster_handles.extend(delivery.entity_handles)
                degraded_proof_class = str(degrade["proof_class"]) if degrade else ""
                if created > 0:
                    delivered_bucket = _delivered_text_entity_bucket(delivered_kind)
                    delivered_text_entity_counts[delivered_bucket] = (
                        int(delivered_text_entity_counts.get(delivered_bucket, 0) or 0) + created
                    )
                # A dropped item created nothing, and is a fallback all the same.
                if (created > 0 and delivery.fallback_used) or degrade is not None:
                    _append_text_fallback(
                        text_fallbacks,
                        requested=delivery.requested_representation,
                        delivered=str(delivery.final_representation or "none"),
                        reason=_fallback_reason_code(delivery, degraded_proof_class),
                        count=1,
                    )
                if created > 0 and opts.provenance_opts is not None:
                    from pdfcadcore.source_provenance import (
                        SourceProvenanceObject,
                        ensure_provenance_bucket,
                    )

                    source_bbox = getattr(ti, "source_bbox_pdf", None)
                    target_bbox = getattr(ti, "bbox", None)
                    if delivery.final_representation == "raster":
                        target_bbox = delivery.attempts[-1].evidence.get("target_bbox_model")
                    span_id = getattr(ti, "id", None)
                    try:
                        span_id = int(span_id)
                    except (TypeError, ValueError):
                        span_id = None
                    bucket = ensure_provenance_bucket(opts.provenance_opts)
                    fallback_reason = (
                        _fallback_reason_code(delivery, degraded_proof_class)
                        if delivery.fallback_used or degrade is not None
                        else ""
                    )
                    for handle in delivery.entity_handles:
                        bucket.append(
                            SourceProvenanceObject(
                                object_id=f"{delivery.source_id}:entity:{handle}",
                                page=int(page.page_data.page_number),
                                source_kind="text_span",
                                created_entity_type=str(doc.entitydb.get(str(handle)).dxftype()),
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
                                    getattr(opts.provenance_opts, "import_mode", "") or ""
                                ),
                                selected_text_mode=str(opts.text_mode or ""),
                                fallback_reason=fallback_reason,
                                span_id=span_id,
                            )
                        )

        if opts.include_images:
            page_number = int(page.page_data.page_number)
            image_placements = terminal_page_tiles.get(page_number, page.images)
            for image_index, placement in enumerate(image_placements, start=1):
                check_cancel(cancel_requested, "active page image build")
                if image_index == 1 or image_index % 16 == 0:
                    report_progress(
                        progress_callback,
                        f"Building source page {page.page_data.page_number}: "
                        f"images {image_index}/{len(image_placements)}",
                    )
                source_key = _normalized_image_source_path(str(placement.path))
                if source_key in omitted_image_sources:
                    continue
                staged_asset = staged_image_assets.get(source_key)
                if staged_asset is None:
                    raise RuntimeError(
                        f"image asset was not staged for delivery: {placement.path}"
                    )
                img_path = staged_asset.path

                image_def = image_def_cache.get(str(img_path))
                if image_def is None:
                    image_def = doc.add_image_def(
                        filename=_serialized_asset_filename(img_path, output.parent),
                        size_in_pixel=staged_asset.size_px,
                        name=f"IMG_{len(image_def_cache) + 1}",
                    )
                    image_def_cache[str(img_path)] = image_def

                layer = _layer_name(page.page_data.page_number, "IMAGES", None, opts)
                _ensure_layer(doc, layer, None)
                insert, u_pixel, v_pixel, size_in_units = _image_geometry(
                    placement,
                    staged_asset,
                    dy,
                )
                image = msp.add_image(
                    image_def,
                    insert=insert,
                    size_in_units=size_in_units,
                    dxfattribs={"layer": layer},
                )
                image.dxf.u_pixel = (u_pixel[0], u_pixel[1], 0.0)
                image.dxf.v_pixel = (v_pixel[0], v_pixel[1], 0.0)
                image.dxf.flags = int(image.dxf.flags or 0) | 8
                if paint_order is not None:
                    source_paint_keys[str(image.dxf.handle)] = (
                        page_position, paint_order.image_keys[image_index - 1],
                    )
                if staged_asset.draw_below_editable:
                    background_image_handles.append(str(image.dxf.handle or ""))
                elif placement.source_kind == "page_raster_alpha_fidelity_fallback":
                    foreground_image_handles.append(str(image.dxf.handle or ""))
                serialized_image_expectations.append(
                    _SerializedImageExpectation(
                        image_handle=str(image.dxf.handle or ""),
                        image_def_handle=str(image_def.dxf.handle or ""),
                        asset_path=staged_asset.path,
                        asset_sha256=staged_asset.sha256,
                        insert=insert,
                        u_pixel=u_pixel,
                        v_pixel=v_pixel,
                        size_in_pixel=staged_asset.size_px,
                    )
                )
                if opts.provenance_opts is not None:
                    from pdfcadcore.source_provenance import (
                        SourceProvenanceObject,
                        ensure_provenance_bucket,
                    )

                    source_kind = str(
                        getattr(placement, "source_kind", "xobject_image") or "xobject_image"
                    )
                    source_count = max(
                        1,
                        int(getattr(placement, "source_instance_count", 1) or 1),
                    )
                    source_number = getattr(placement, "source_number", None)
                    source_bbox = getattr(placement, "source_bbox_pdf", None)
                    crop_width = staged_asset.crop_box_px[2] - staged_asset.crop_box_px[0]
                    crop_height = staged_asset.crop_box_px[3] - staged_asset.crop_box_px[1]
                    image_corners = [
                        insert,
                        (
                            insert[0] + u_pixel[0] * crop_width,
                            insert[1] + u_pixel[1] * crop_width,
                        ),
                        (
                            insert[0] + v_pixel[0] * crop_height,
                            insert[1] + v_pixel[1] * crop_height,
                        ),
                        (
                            insert[0] + u_pixel[0] * crop_width + v_pixel[0] * crop_height,
                            insert[1] + u_pixel[1] * crop_width + v_pixel[1] * crop_height,
                        ),
                    ]
                    image_min_x = min(point[0] for point in image_corners)
                    image_min_y = min(point[1] for point in image_corners)
                    image_max_x = max(point[0] for point in image_corners)
                    image_max_y = max(point[1] for point in image_corners)
                    ensure_provenance_bucket(opts.provenance_opts).append(
                        SourceProvenanceObject(
                            object_id=(
                                f"{source_kind}:{page.page_data.page_number}:"
                                f"{source_number if source_number is not None else source_count}:"
                                f"entity:{image.dxf.handle}"
                            ),
                            page=int(page.page_data.page_number),
                            source_kind=source_kind,
                            created_entity_type="IMAGE",
                            parent_handle=str(image.dxf.handle or ""),
                            source_bbox_pdf=(
                                [float(value) for value in source_bbox[:4]]
                                if source_bbox
                                else None
                            ),
                            target_bbox_model=[
                                float(image_min_x),
                                float(image_min_y),
                                float(image_max_x),
                                float(image_max_y),
                            ],
                            selected_import_mode=str(
                                getattr(opts.provenance_opts, "import_mode", "") or ""
                            ),
                            scale_factor=float(
                                getattr(opts.provenance_opts, "scale_factor", 1.0) or 1.0
                            ),
                        )
                    )
                crop_width = staged_asset.crop_box_px[2] - staged_asset.crop_box_px[0]
                crop_height = staged_asset.crop_box_px[3] - staged_asset.crop_box_px[1]
                for u_factor, v_factor in (
                    (0, 0),
                    (crop_width, 0),
                    (0, crop_height),
                    (crop_width, crop_height),
                ):
                    _track_xy(
                        float(insert[0] + u_pixel[0] * u_factor + v_pixel[0] * v_factor),
                        float(insert[1] + u_pixel[1] * u_factor + v_pixel[1] * v_factor),
                    )
                entity_count += 1
                image_count += 1

        # Advance page placement offset for the next page.
        page_step = _page_stack_step(page.page_data.height, arrangement, gap_ratio)
        if paint_order is None:
            for entity in msp.entity_space.entities[page_entity_start:]:
                source_paint_keys[str(entity.dxf.handle)] = (page_position, 0)
        if final_paints:
            from .final_rect_paint import stroke_snapshot
            if set(final_entities) != set(final_by_id):
                raise RuntimeError("Final source paints were not completely delivered")
            max_key = max(key[1] for key in source_paint_keys.values() if key[0] == page_position)
            for index, paint in enumerate(final_paints, 1):
                entities = final_entities[paint["primitive_id"]]
                if [entity.dxftype() for entity in entities] != ["IMAGE", "LWPOLYLINE"]:
                    raise RuntimeError("Final source paint has unexpected native entities")
                expected = next(e for e in final_paint_expectations
                                if e["image_handle"] == str(entities[0].dxf.handle))
                expected["strokes"] = [stroke_snapshot(entities[1])]
                final_paint_stroke_handles.add(str(entities[1].dxf.handle))
                for entity in entities:
                    source_paint_keys[str(entity.dxf.handle)] = (page_position, max_key+index)
            # These opaque crops are already the final PDF pixel stack. The
            # exact page-pixel placement proof above prevents double tinting.
            for handle in page_raster_handles:
                source_paint_keys[str(handle)] = (page_position, max_key+len(final_paints)+1)
            has_source_image_order = True
        _stack_offset_y -= page_step

    _write_search_text_companions(
        doc, msp, pending_search_text, opts=opts, is_r12=is_r12,
        source_paint_keys=source_paint_keys,
    )

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

    if has_source_image_order:
        background_set = set(background_image_handles)
        foreground_set = set(foreground_image_handles)
        # Non-bound pages retain their pre-existing alpha/composite ordering.
        for handle in background_set:
            page_key, _key = source_paint_keys[handle]
            source_paint_keys[handle] = (page_key, -1)
        for handle in foreground_set:
            page_key, _key = source_paint_keys[handle]
            source_paint_keys[handle] = (page_key, float("inf"))
        apply_image_paint_order(msp, source_paint_keys)
    elif background_image_handles or foreground_image_handles:
        background_set = set(background_image_handles)
        foreground_set = set(foreground_image_handles)
        explicitly_ordered = background_set | foreground_set
        ordered_entities = [
            entity for entity in msp if str(entity.dxf.handle or "") in background_set
        ]
        ordered_entities.extend(
            entity
            for entity in msp
            if str(entity.dxf.handle or "") not in explicitly_ordered
        )
        ordered_entities.extend(
            entity for entity in msp if str(entity.dxf.handle or "") in foreground_set
        )
        msp.set_redraw_order(
            [
                (str(entity.dxf.handle), f"{index:X}")
                for index, entity in enumerate(ordered_entities, start=1)
            ]
        )

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

        trusted_positioned_session = _PositionedVerificationSession(
            positioned_translation_anchors,
            _mint_capability=_POSITIONED_SESSION_MINT_CAPABILITY,
        )
        _ISSUED_POSITIONED_SESSIONS[trusted_positioned_session] = (
            _IssuedPositionedSessionAuthority(
                session_capability=(
                    trusted_positioned_session._session_capability
                ),
                canonical_anchors=MappingProxyType(
                    {
                        source_id: replace(anchor)
                        for source_id, anchor in positioned_translation_anchors.items()
                    }
                ),
                anchor_registry=MappingProxyType(
                    {
                        source_id: (
                            anchor,
                            trusted_positioned_session._anchor_capabilities[
                                source_id
                            ],
                        )
                        for source_id, anchor in positioned_translation_anchors.items()
                    }
                ),
            )
        )
        entities_written = len(msp)
        doc.saveas(str(temp_output))
        if has_source_image_order:
            verify_serialized_image_paint_order(
                temp_output, [str(entity.dxf.handle) for entity in msp],
            )
        # Re-open the exact candidate before it can replace a prior good DXF.
        # Every record the verification inspects is re-read from the written
        # bytes; bulk geometry it never inspects is syntax-checked in a
        # streaming pass instead of being rebuilt as ezdxf objects.
        candidate, auditor = _reopen_candidate_for_verification(
            temp_output,
            keep_handles=_verification_keep_handles(
                text_deliveries, serialized_image_expectations
            ) | final_paint_stroke_handles,
            modelspace_owner_handle=str(msp.block_record.dxf.handle),
            entities_written=entities_written,
        )
        if auditor.has_errors:
            raise RuntimeError(
                f"serialized DXF candidate failed audit with {len(auditor.errors)} error(s)"
            )
        try:
            _verify_serialized_text_deliveries(
                candidate,
                text_deliveries,
                trusted_positioned_session=trusted_positioned_session,
            )
        except RuntimeError as exc:
            mismatch_rungs = _serialized_mismatch_rungs(exc, text_deliveries)
            if mismatch_rungs is None:
                # Structural: no single item can take the blame, so the sheet stops.
                raise ImportStopped(str(exc)) from exc
            raise _SerializedTextItemMismatch(str(exc), mismatch_rungs) from exc
        _verify_serialized_search_text(candidate, text_deliveries)
        _verify_serialized_image_assets(candidate, serialized_image_expectations)
        _verify_serialized_source_dash_blocks(candidate, source_dash_expectations)
        from .final_rect_paint import verify_metadata_and_strokes
        verify_metadata_and_strokes(candidate, final_paint_expectations)
        temp_output.replace(output)
    except Exception:
        _sync_text_evidence()  # the failure report names every item's evidence
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
        opts.provenance_opts._final_rect_paint_deliveries = final_paint_records  # noqa: B010
        opts.provenance_opts._result_status = "success"  # noqa: B010
        _sync_text_evidence()

    for prior_session in sorted(prior_owned_sessions):
        if prior_session == asset_root.resolve():
            continue
        try:
            if prior_session.parent == asset_parent.resolve() and re.fullmatch(
                r"[0-9a-f]{32}", prior_session.name
            ):
                shutil.rmtree(prior_session)
        except OSError:
            # A locked prior asset must never invalidate the newly accepted DXF.
            pass

    return DxfExportResult(
        output_path=str(output),
        entity_count=entity_count,
        layer_count=len(doc.layers),
        image_count=image_count,
        text_fallbacks=[dict(item) for item in text_fallbacks],
        delivered_text_entity_counts=dict(delivered_text_entity_counts),
        text_deliveries=[dict(item) for item in text_deliveries],
        final_rect_paints=[dict(item) for item in final_paint_records],
        searchable_text_companions=searchable_text_companions(
            text_deliveries, enabled=search_text_enabled
        ),
    )


def _layer_name(
    page_number: int, source_layer: Optional[str], stroke_color, opts: DxfExportOptions
) -> str:
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
    return tuple(int(max(0, min(255, round(float(component) * 255)))) for component in rgb[:3])


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


def _filled_path_has_visible_area(points) -> bool:
    """Return whether a PDF fill spans any finite two-dimensional area.

    PDF permits fill operators on open, repeated, or collinear paths; closing
    those paths still paints no pixels.  R12 represents fills as triangulated
    SOLIDs, so a verified zero-area path legitimately yields no entities.
    Non-finite coordinates are not certified as empty and retain the strict
    exporter failure path.
    """

    coordinates: List[Tuple[float, float]] = []
    for raw in points:
        point = (float(raw[0]), float(raw[1]))
        if not all(math.isfinite(value) for value in point):
            return True
        if not coordinates or point != coordinates[-1]:
            coordinates.append(point)
    if len(coordinates) >= 2 and coordinates[0] == coordinates[-1]:
        coordinates.pop()
    if len(coordinates) < 3:
        return False

    origin_x, origin_y = coordinates[0]
    anchor_x, anchor_y = max(
        coordinates[1:],
        key=lambda point: max(
            abs(point[0] - origin_x), abs(point[1] - origin_y)
        ),
    )
    anchor_dx = anchor_x - origin_x
    anchor_dy = anchor_y - origin_y
    if anchor_dx == 0.0 and anchor_dy == 0.0:
        return False
    spans_area = any(
        anchor_dx * (point_y - origin_y) - anchor_dy * (point_x - origin_x)
        != 0.0
        for point_x, point_y in coordinates[1:]
    )
    if not spans_area:
        return False

    # A path may trace a non-collinear loop and then retrace every edge in the
    # opposite direction.  Its winding (and even/odd parity) is zero everywhere,
    # so the PDF fill still paints nothing even though its bounding box has area.
    directed_edges: Dict[
        Tuple[Tuple[float, float], Tuple[float, float]], int
    ] = {}
    for index, start in enumerate(coordinates):
        end = coordinates[(index + 1) % len(coordinates)]
        if start == end:
            continue
        edge = (start, end)
        directed_edges[edge] = directed_edges.get(edge, 0) + 1
    if directed_edges and all(
        count == directed_edges.get((end, start), 0)
        for (start, end), count in directed_edges.items()
    ):
        return False
    return True


def _compound_clip_regions(contours):
    """Nest disjoint clip rings by actual containment, never by bbox centres.

    A logo's diagonal mark and adjacent letters can have overlapping bounding
    boxes while their painted regions are disjoint. Bounding-box nesting would
    incorrectly remove a whole letter as a counter.
    """
    rings = []
    for contour in contours:
        points = [Vec2(point) for point in contour]
        if points[0] == points[-1]:
            points.pop()
        area = abs(sum(a.x*b.y-b.x*a.y for a,b in zip(points, points[1:]+points[:1], strict=True))) / 2
        if area == 0:
            raise RuntimeError("clipping contour needs a self-intersection-aware tessellator")
        rings.append((points, area))
    parents = []
    for index, (points, area) in enumerate(rings):
        containing = []
        for other, (boundary, outer_area) in enumerate(rings):
            if index == other or outer_area <= area:
                continue
            relations = [is_point_in_polygon_2d(point, boundary) for point in points]
            if all(relation >= 0 for relation in relations) and any(relation > 0 for relation in relations):
                containing.append(other)
        parents.append(min(containing, key=lambda candidate:rings[candidate][1]) if containing else None)
    depths = []
    for index in range(len(rings)):
        depth = 0; parent = parents[index]
        while parent is not None:
            depth += 1; parent = parents[parent]
        depths.append(depth)
    return [
        (points, [rings[child][0] for child,parent in enumerate(parents) if parent == index])
        for index,(points,_area) in enumerate(rings) if depths[index] % 2 == 0
    ]


def _add_compound_filled_paths(
    msp, contours, fill_rgb, attribs: dict, *, is_r12: bool, even_odd: bool,
) -> List[Any]:
    """Keep every counter in a PDF clipping mask in one native compound fill."""
    visible = [points for points in contours if _filled_path_has_visible_area(points)]
    if not visible:
        return []
    if len(visible) > 1 and not even_odd:
        raise RuntimeError(
            "multi-contour nonzero clipping fill requires a winding-aware intersection; "
            "refusing to replace it with an inaccurate even-odd fill"
        )
    # LibreCAD's native HATCH renderer creates spurious connectors between
    # these separate mask contours. Native SOLID triangles preserve both the
    # visible regions and empty counters in every supported DXF version.
    attribs = dict(attribs)
    if not is_r12:
        parent_rgb = _rgb_bytes(fill_rgb)
        if parent_rgb == (255, 255, 255):
            parent_rgb = (254, 254, 254)
        attribs["true_color"] = rgb2int(parent_rgb)
        attribs["color"] = _nearest_r12_aci(fill_rgb)
    solids = []
    for exterior, holes in _compound_clip_regions(visible):
        for triangle in mapbox_earcut_2d(exterior, holes):
            vertices = [(float(point.x), float(point.y)) for point in triangle]
            if len(vertices) != 3:
                continue
            p0, p1, p2 = vertices
            area2 = abs((p1[0]-p0[0])*(p2[1]-p0[1])-(p1[1]-p0[1])*(p2[0]-p0[0]))
            if math.isfinite(area2) and area2 > 1e-14:
                solids.append(msp.add_solid([p0, p1, p2, p2], dxfattribs=dict(attribs)))
    if not solids:
        raise RuntimeError("clipped source fill produced no native fill entities")
    return solids


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
        area2 = abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]))
        if not math.isfinite(area2) or area2 <= 1e-14:
            continue
        solids.append(msp.add_solid([p0, p1, p2, p2], dxfattribs=dict(attribs)))
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
        kwargs["true_color"] = rgb2int(
            tuple(int(max(0, min(255, round(float(c) * 255)))) for c in rgb)
        )
    doc.layers.new(name=name, dxfattribs=kwargs)


def _apply_color(attribs: dict, rgb) -> None:
    if rgb is None:
        return
    r, g, b = (int(max(0, min(255, round(float(c) * 255)))) for c in rgb)
    # Invert (near-)white to black so white-on-white geometry is visible on
    # LibreCAD's default white background. Only genuinely white ink qualifies
    # (every channel >= 250): a luminance threshold used to turn pale tints --
    # light-grey lines, pale-yellow highlights, and every translucent colour that
    # pdfcadcore now composites against the page (a 5 % black wash is 242 grey) --
    # into solid black, which is not what the PDF viewer shows.
    if _is_near_white(r, g, b):
        r, g, b = 0, 0, 0
    attribs["true_color"] = rgb2int((r, g, b))


def _is_near_white(r: int, g: int, b: int) -> bool:
    return min(r, g, b) >= 250


def _apply_lineweight(attribs: dict, width_mm) -> None:
    """`Primitive.line_width` is already millimetres in model units (pdfcadcore
    primitive_extractor multiplies the PDF stroke width by MM_PER_PT * scale). This
    used to convert pt->mm a second time, making every LibreCAD lineweight 2.83x too
    thin (0.84 pt border drawn as 0.13 mm instead of 0.30 mm) -- found by the visual
    oracle on 1011: page border, title underlines and heavy plate outlines lighter
    than the PDF."""
    if width_mm is None:
        return
    try:
        width_mm = float(width_mm)
    except (TypeError, ValueError):
        return
    if not math.isfinite(width_mm):
        return
    # Arbitrary integers are not supported DXF weights. ezdxf rounds an invalid
    # value upward: a 0.0998mm source became 10 and then 13 (30% too thick).
    # Choose the nearest supported positive weight before serialization.
    target = max(5.0, min(211.0, width_mm * 100.0))
    attribs["lineweight"] = min(
        (weight for weight in VALID_DXF_LINEWEIGHTS if weight > 0),
        key=lambda weight: (abs(weight - target), weight),
    )


# LibreCAD does not interpret LTYPE table definitions: it recognizes a fixed set of
# linetype NAMES (DASHED, DASHDOT, CENTER, DOT, DIVIDE, BORDER and their TINY/2/X2
# length variants) and draws anything else -- including a perfectly valid custom
# "PDF_DASH_n" definition -- as a continuous line. The visual oracle showed every
# dashed centerline and hidden line on 1011 rendered solid in LibreCAD. So the
# exported entity gets the LibreCAD name whose family and dash length are closest
# to the PDF dash array; the exact PDF pattern is preserved in the LTYPE description
# and in `ltscale` for consumers that honour it.
_LIBRECAD_VARIANT_DASH_MM = (("TINY", 3.175), ("2", 6.35), ("", 12.7), ("X2", 25.4))
_DOT_MAX_MM = 0.75


def _librecad_linetype_for_dash(mm_vals: List[float]) -> Tuple[str, str, float]:
    """Return (LibreCAD linetype name, family, variant dash length mm) for a PDF dash
    array already converted to millimetres [dash, gap, dash, gap, ...]."""
    dashes = [v for i, v in enumerate(mm_vals) if i % 2 == 0]
    longest = max(dashes) if dashes else 0.0
    dots = [d for d in dashes if d <= _DOT_MAX_MM]
    long_dashes = [d for d in dashes if d > _DOT_MAX_MM]
    if not long_dashes:
        family = "DOT"
    elif len(dashes) == 1 or all(abs(d - longest) <= 0.35 * longest for d in dashes):
        family = "DASHED"
    elif len(dashes) == 2:
        family = "DASHDOT" if dots else "CENTER"
    elif len(dashes) >= 3:
        # dash-dot-dot -> DIVIDE; dash-dash-dot -> BORDER; anything else -> CENTER
        if len(dots) >= 2 and len(long_dashes) == 1:
            family = "DIVIDE"
        elif len(long_dashes) >= 2 and len(dots) >= 1:
            family = "BORDER"
        else:
            family = "CENTER"
    else:
        family = "DASHED"
    reference = longest if family != "DOT" else (max(dashes + [g for i, g in enumerate(mm_vals) if i % 2 == 1]) if mm_vals else 1.0)
    variant, variant_len = min(_LIBRECAD_VARIANT_DASH_MM, key=lambda item: abs(item[1] - reference))
    return f"{family}{variant}", family, variant_len


def _librecad_reference_pattern(family: str, variant_len: float) -> List[float]:
    """An LTYPE definition matching the LibreCAD look, for consumers that read the table."""
    d = variant_len
    g = d * 0.5
    dot = min(0.5, d * 0.1)
    if family == "DASHED":
        seq = [d, -g]
    elif family == "DOT":
        seq = [dot, -g]
    elif family == "DASHDOT":
        seq = [d, -g, dot, -g]
    elif family == "CENTER":
        seq = [d * 2, -g, d * 0.5, -g]
    elif family == "DIVIDE":
        seq = [d, -g, dot, -g, dot, -g]
    else:  # BORDER
        seq = [d, -g, d, -g, dot, -g]
    return [sum(abs(v) for v in seq)] + seq


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
    name, family, variant_len = _librecad_linetype_for_dash(mm_vals)
    if name not in doc.linetypes:
        try:
            doc.linetypes.add(
                name=name,
                pattern=_librecad_reference_pattern(family, variant_len),
                description=f"LibreCAD {family} ({variant_len:g} mm) for PDF dash {key} pt",
            )
        except Exception:
            return None

    cache[key] = name
    return name


def _linetype_scale_for_dash(dash_pattern) -> Optional[float]:
    """Entity ltscale so table-honouring consumers reproduce the PDF dash length."""
    values = _normalize_dash(dash_pattern) if dash_pattern else []
    if len(values) < 2:
        return None
    mm_vals = [max(0.1, v * (25.4 / 72.0)) for v in values]
    _name, _family, variant_len = _librecad_linetype_for_dash(mm_vals)
    dashes = [v for i, v in enumerate(mm_vals) if i % 2 == 0]
    longest = max(dashes) if dashes else variant_len
    scale = longest / variant_len if variant_len > 0 else 1.0
    return round(min(max(scale, 0.05), 20.0), 4)


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

# -*- coding: utf-8 -*-
# dxf_text_builder.py -- NormalizedText -> verified DXF representations
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""Build requested text representations without silently changing their type.

    LibreCAD delivery is item-scoped and fail-closed. Because DXF exposes no
    native Label entity, Labels record item-scoped impossibility before the
    closest editable Text fallback; a report-only TEXT/MTEXT alias is rejected.
    3D Text first attempts ``TEXT`` with non-zero thickness and +Z extrusion but
    is not accepted until parent renderability also verifies. Glyphs are grouped
    ``INSERT`` block references and Geometry is raw
    modelspace outline edges. Temporary or rejected TEXT entities are
    attempt-owned and removed before another rung can be certified. Every result
    carries the real DXF handles and complete attempt history, so reports never
    infer delivery from the requested mode string.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf import path as ezdxf_path
from ezdxf.addons import text2path
from ezdxf.fonts import fonts as ezdxf_fonts
from ezdxf.fonts.font_face import FontFace
from ezdxf.math import Matrix44
from ezdxf.tools.text_size import text_size

from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText


_MTEXT_THRESHOLD = 120
_created_styles: Dict[str, str] = {}
_style_counter = 0


class _RepresentationImpossible(ValueError):
    """The exact source item cannot be created in this representation."""


@dataclass
class TextDeliveryAttempt:
    """Evidence for one item-scoped representation strategy."""

    source_id: str
    requested_representation: str
    attempted_representation: str
    strategy: str
    outcome: str = "failed"
    reason: str = ""
    type_verified: bool = False
    visual_verified: bool = False
    created_entity_handles: List[str] = field(default_factory=list)
    removed_entity_handles: List[str] = field(default_factory=list)
    entity_handles: List[str] = field(default_factory=list)
    support_entity_handles: List[str] = field(default_factory=list)
    referenced_entity_handles: List[str] = field(default_factory=list)
    owned_block_names: List[str] = field(default_factory=list)
    cleanup_verified: bool = False
    superseded: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TextDeliveryResult:
    """Final verified delivery plus every same-type retry and fallback."""

    source_id: str
    requested_representation: str
    final_representation: Optional[str]
    verified: bool
    entity_handles: List[str] = field(default_factory=list)
    support_entity_handles: List[str] = field(default_factory=list)
    referenced_entity_handles: List[str] = field(default_factory=list)
    attempts: List[TextDeliveryAttempt] = field(default_factory=list)
    terminal_fallback_authorized: bool = False
    failure_reason: str = ""

    @property
    def fallback_used(self) -> bool:
        return bool(
            self.final_representation
            and self.final_representation != self.requested_representation
        )

    @property
    def delivered_kind(self) -> str:
        return {
            "text": "dxf_native_text",
            "labels": "dxf_text",
            "3d_text": "native_3d_text",
            "glyphs": "glyph_block_reference",
            "geometry": "raw_geometry_edges",
            "raster": "raster_image",
        }.get(str(self.final_representation or ""), "none")

    @property
    def count(self) -> int:
        return len(self.entity_handles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "requested_representation": self.requested_representation,
            "final_representation": self.final_representation,
            "verified": bool(self.verified),
            "fallback_used": self.fallback_used,
            "entity_handles": list(self.entity_handles),
            "support_entity_handles": list(self.support_entity_handles),
            "referenced_entity_handles": list(self.referenced_entity_handles),
            "terminal_fallback_authorized": bool(self.terminal_fallback_authorized),
            "failure_reason": self.failure_reason,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }


@dataclass
class _OutlineCharacterGroup:
    """Pre-entity source ownership for one individually positioned character."""

    index: int
    text: str
    glyph_id: Optional[int]
    target_origin: Tuple[float, float]
    target_quad: Tuple[Tuple[float, float], ...]
    advance_width: float
    glyph_height: float
    rotation_degrees: float
    visible_ink_expected: bool
    expected_bbox: Optional[Tuple[float, float, float, float]]
    expected_path_geometry: Tuple["_PathGeometryExpectation", ...] = ()
    expected_fill_geometry: Tuple[Tuple[Tuple[float, float], ...], ...] = ()
    flattening_error: float = 0.0
    geometry_tolerance: float = 0.0
    outlines: List[Any] = field(default_factory=list)
    fills: List[Any] = field(default_factory=list)


@dataclass(frozen=True)
class _PathGeometryExpectation:
    """Immutable source-font path topology captured before entity creation."""

    start: Tuple[float, float]
    commands: Tuple[Tuple[str, Tuple[Tuple[float, float], ...]], ...]
    flattened_vertices: Tuple[Tuple[float, float], ...]
    is_closed: bool


@dataclass(frozen=True)
class _OutlineExpectation:
    """Independent source/path truth captured before DXF entity construction."""

    path_bbox: Tuple[float, float, float, float]
    source_envelope: Tuple[Tuple[float, float], ...]
    source_envelope_source: str
    path_geometry: Tuple[_PathGeometryExpectation, ...]
    fill_geometry: Tuple[Tuple[Tuple[float, float], ...], ...]
    flattening_error: float
    geometry_tolerance: float
    source_geometry_verified: bool
    character_groups: Tuple[_OutlineCharacterGroup, ...] = ()


@dataclass(frozen=True)
class _ValidatedCharacterLayout:
    index: int
    text: str
    glyph_id: Optional[int]
    target_origin: Tuple[float, float]
    target_quad: Tuple[Tuple[float, float], ...]
    advance_width: float
    glyph_height: float
    rotation_degrees: float
    visible_ink_expected: bool
    source_to_target_linear: Tuple[float, float, float, float]


@dataclass(frozen=True)
class _ExactFontResolution:
    source_name: str
    family: str = ""
    style: str = ""
    filename: str = ""
    exact: bool = False
    reason: str = ""
    resolution_source: str = "installed_exact_font"
    asset_id: str = ""
    asset_sha256: str = ""
    source_xref: Optional[int] = None
    source_cap_height_ratio: Optional[float] = None
    source_sha256: str = ""
    source_origin: str = ""
    source_page_number: Optional[int] = None
    asset_span_font_name: str = ""
    usable_format: str = ""
    pdf_font_failure_reason: str = ""
    installed_font_failure_reason: str = ""
    proof_category: str = ""
    item_impossibility_proven: bool = False

    def evidence(self) -> Dict[str, Any]:
        return {
            "source_font_name": self.source_name,
            "resolved_font_family": self.family or None,
            "resolved_font_style": self.style or None,
            "resolved_font_filename": self.filename or None,
            "font_exact_match": bool(self.exact),
            "font_resolution_reason": self.reason,
            "font_resolution_source": self.resolution_source,
            "font_asset_id": self.asset_id or None,
            "font_asset_sha256": self.asset_sha256 or None,
            "font_source_xref": self.source_xref,
            "source_cap_height_ratio": self.source_cap_height_ratio,
            "font_source_sha256": self.source_sha256 or None,
            "font_source_origin": self.source_origin or None,
            "font_source_page_number": self.source_page_number,
            "font_asset_span_font_name": self.asset_span_font_name or None,
            "font_usable_format": self.usable_format or None,
            "pdf_font_failure_reason": self.pdf_font_failure_reason or None,
            "installed_font_failure_reason": (
                self.installed_font_failure_reason or None
            ),
            "font_item_impossibility_proven": bool(
                self.item_impossibility_proven
            ),
            "font_failure_proof_category": self.proof_category or None,
        }


def _font_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _resolve_exact_font(font_name: str) -> _ExactFontResolution:
    """Resolve only a source-equivalent installed font; never substitute.

    PyMuPDF commonly reports PostScript names (for example ``Arial-BoldMT``)
    rather than Windows family names.  We normalize those exact aliases and
    ask ezdxf's system font cache for the matching family/style.  A generic
    fallback face is explicitly rejected.
    """
    source = str(font_name or "").strip()
    if not source:
        return _ExactFontResolution(source_name=source, reason="source font name missing")
    base = re.sub(r"^[A-Z]{6}\+", "", source)
    lower = base.lower()
    bold = "bold" in lower
    italic = "italic" in lower or "oblique" in lower
    style = "Bold Italic" if bold and italic else ("Bold" if bold else ("Italic" if italic else "Regular"))
    family_part = re.sub(
        r"[-_ ]?(bolditalic|boldoblique|bold|italic|oblique|regular|roman|medium)(mt)?$",
        "",
        base,
        flags=re.IGNORECASE,
    )
    family_part = re.sub(r"PSMT$", "", family_part, flags=re.IGNORECASE)
    family_part = re.sub(r"MT$", "", family_part, flags=re.IGNORECASE)
    aliases = {
        "arial": "Arial",
        "arialnarrow": "Arial Narrow",
        "timesnewroman": "Times New Roman",
        "timesnewromanps": "Times New Roman",
        "couriernew": "Courier New",
        "couriernewps": "Courier New",
        "wingdings": "Wingdings",
        "webdings": "Webdings",
        "symbol": "Symbol",
    }
    token = _font_token(family_part)
    family = aliases.get(token)
    if family is None:
        family = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", family_part)
        family = re.sub(r"[-_]+", " ", family).strip()
    if not family:
        return _ExactFontResolution(
            source_name=source,
            style=style,
            reason="source font family could not be normalized",
        )
    face = ezdxf_fonts.find_best_match(
        family=family,
        style=style,
        weight=700 if bold else 400,
        italic=italic,
    )
    if face is None:
        return _ExactFontResolution(
            source_name=source,
            family=family,
            style=style,
            reason="no exact installed source-font family/style match",
        )
    family_ok = _font_token(face.family) == _font_token(family)
    weight_ok = int(face.weight or 400) >= 600 if bold else int(face.weight or 400) < 600
    italic_ok = bool("italic" in str(face.style or "").lower() or "oblique" in str(face.style or "").lower()) == italic
    filename = str(face.filename or "")
    exact = bool(family_ok and weight_ok and italic_ok and filename)
    return _ExactFontResolution(
        source_name=source,
        family=str(face.family or family),
        style=str(face.style or style),
        filename=filename if exact else "",
        exact=exact,
        reason=("exact installed source-font match" if exact else "font cache match was not source-equivalent"),
    )


def _resolve_item_font(
    text_item: NormalizedText,
    config: ImportConfig,
) -> _ExactFontResolution:
    """Prefer the exact embedded program attached to this source span."""

    source_name = str(getattr(text_item, "font_name", "") or "")
    asset = getattr(text_item, "font_asset", None)
    if asset is not None:
        try:
            cap_height_ratio = _embedded_ezdxf_cap_height_ratio(
                bytes(asset.usable_bytes)
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            return _ExactFontResolution(
                source_name=source_name,
                family=str(asset.base_font_name or source_name),
                exact=False,
                reason=f"embedded font has no certifiable DXF cap-height scale: {exc}",
                resolution_source="embedded_pdf_font",
                asset_id=str(asset.asset_id),
                asset_sha256=str(asset.usable_sha256),
                source_xref=int(asset.source_xref),
            )
        paths = dict(getattr(config, "_embedded_font_asset_paths", {}) or {})
        filename = str(paths.get(str(asset.asset_id), "") or "")
        path = Path(filename) if filename else None
        base = {
            "source_name": source_name,
            "family": str(asset.base_font_name or source_name),
            "filename": filename,
            "resolution_source": str(
                getattr(asset, "source_origin", "embedded_pdf_font")
                or "embedded_pdf_font"
            ),
            "asset_id": str(asset.asset_id),
            "asset_sha256": str(asset.usable_sha256),
            "source_xref": int(asset.source_xref),
            "source_cap_height_ratio": cap_height_ratio,
            "source_sha256": str(getattr(asset, "source_sha256", "") or ""),
            "source_origin": str(
                getattr(asset, "source_origin", "embedded_pdf_font")
                or "embedded_pdf_font"
            ),
            "source_page_number": int(getattr(asset, "page_number", 0) or 0),
            "asset_span_font_name": str(
                getattr(asset, "span_font_name", source_name) or source_name
            ),
            "usable_format": str(getattr(asset, "usable_format", "") or ""),
        }
        if path is None or not path.is_file():
            return _ExactFontResolution(
                **base,
                exact=False,
                reason="exact embedded font was not staged for this export",
            )
        try:
            content = path.read_bytes()
        except OSError as exc:
            return _ExactFontResolution(
                **base,
                exact=False,
                reason=f"exact embedded font asset could not be read: {exc}",
            )
        digest = hashlib.sha256(content).hexdigest()
        if digest != str(asset.usable_sha256) or content != bytes(asset.usable_bytes):
            return _ExactFontResolution(
                **base,
                exact=False,
                reason="staged embedded font bytes do not match the source asset",
            )
        return _ExactFontResolution(
            **base,
            exact=True,
            reason="exact embedded source-font program",
        )

    failure = getattr(text_item, "font_failure", None)
    if failure is not None:
        detail = str(getattr(failure, "detail", "") or "")
        failure_code = str(
            getattr(failure, "reason", "") or "embedded_font_unavailable"
        )
        proof_category = str(getattr(failure, "proof_category", "") or "")
        installed = _resolve_exact_font(source_name)
        installed_may_prove_equivalence = proof_category in {
            "",
            "source_font_absent_for_item",
        }
        if installed.exact and installed_may_prove_equivalence:
            return installed
        reason = failure_code
        if detail:
            reason = f"{reason}: {detail}"
        source_program_absence_proven = proof_category in {
            "source_font_absent_for_item",
            "source_font_ambiguous_for_item",
            "source_specific_impossibility",
            "runtime_inventory_unavailable_for_item",
            "runtime_source_document_unavailable_for_item",
            "runtime_source_font_extraction_unavailable_for_item",
            "source_inventory_invalid_for_page",
        }
        item_impossibility_proven = bool(
            source_name
            and source_program_absence_proven
            and (not installed.exact or not installed_may_prove_equivalence)
        )
        combined_reason = (
            f"source PDF exact font unavailable ({reason}); "
            f"installed exact font unavailable ({installed.reason})"
        )
        return _ExactFontResolution(
            source_name=source_name,
            family=installed.family,
            style=installed.style,
            exact=False,
            reason=combined_reason,
            resolution_source="source_pdf_and_installed_exact_font",
            source_xref=getattr(failure, "source_xref", None),
            pdf_font_failure_reason=reason,
            installed_font_failure_reason=installed.reason,
            item_impossibility_proven=item_impossibility_proven,
            proof_category=proof_category,
        )
    return _resolve_exact_font(source_name)


def _require_exact_item_font(
    text_item: NormalizedText,
    config: ImportConfig,
    attempt: TextDeliveryAttempt,
) -> _ExactFontResolution:
    resolution = _resolve_item_font(text_item, config)
    attempt.evidence.update(resolution.evidence())
    source_authoritative = _source_font_program_is_authoritative(resolution)
    attempt.evidence["source_font_program_authoritative"] = source_authoritative
    if resolution.exact and source_authoritative:
        return resolution
    if resolution.exact:
        raise _RepresentationImpossible(
            "the resolved font program is not source-authoritative for exact outline delivery"
        )
    if resolution.item_impossibility_proven:
        raise _RepresentationImpossible(resolution.reason)
    raise ValueError(resolution.reason)


_SOURCE_AUTHORITATIVE_FONT_ORIGINS = frozenset(
    {
        "embedded_pdf_font",
        "pdf_base14_renderer_font",
        "test_fixture",
    }
)


def _source_font_program_is_authoritative(resolution: _ExactFontResolution) -> bool:
    origin = str(
        resolution.source_origin or resolution.resolution_source or ""
    ).strip().lower()
    return bool(
        resolution.exact and origin in _SOURCE_AUTHORITATIVE_FONT_ORIGINS
    )


def _embedded_ezdxf_cap_height_ratio(font_bytes: bytes) -> float:
    """Reproduce ezdxf's A/x measurement in native PDF em units."""

    from fontTools.pens.boundsPen import ControlBoundsPen
    from fontTools.ttLib import TTFont

    font = TTFont(BytesIO(font_bytes), lazy=False, recalcTimestamp=False)
    units_per_em = float(font["head"].unitsPerEm)
    if not math.isfinite(units_per_em) or units_per_em <= 0.0:
        raise ValueError("font unitsPerEm is invalid")
    cmap = font.getBestCmap()
    if cmap is None:
        raise ValueError("font has no Unicode character map")
    glyph_set = font.getGlyphSet()

    def control_bounds(character: str) -> Tuple[float, float, float, float]:
        glyph_name = cmap.get(ord(character), ".notdef")
        if glyph_name not in glyph_set:
            glyph_name = ".notdef"
        pen = ControlBoundsPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
        if pen.bounds is None:
            raise ValueError(f"font metric glyph {character!r} has no bounds")
        return tuple(float(value) for value in pen.bounds)

    x_bounds = control_bounds("x")
    cap_bounds = control_bounds("A")
    cap_height = cap_bounds[3] - x_bounds[1]
    font.close()
    ratio = cap_height / units_per_em
    if not math.isfinite(ratio) or ratio <= 0.0:
        raise ValueError("font cap-height ratio is invalid")
    return ratio


def _delivery_cap_height(
    source_em_height: float,
    resolution: _ExactFontResolution,
) -> Tuple[float, float]:
    ratio = (
        float(resolution.source_cap_height_ratio)
        if resolution.source_cap_height_ratio is not None
        else 1.0
    )
    height = source_em_height * ratio
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("resolved DXF cap height is invalid")
    return height, ratio


def _ensure_text_style(
    doc: ezdxf.document.Drawing,
    resolution: _ExactFontResolution,
    *,
    style_font: Optional[str] = None,
    preferred_style_name: Optional[str] = None,
) -> Tuple[str, str, bool]:
    """Return style name, actual handle, and whether this call created it."""
    global _style_counter  # noqa: PLW0603

    selected_font = str(style_font or resolution.filename or "").strip()
    if not selected_font:
        raise ValueError("exact source font is unavailable")
    if style_font is None and not resolution.exact:
        raise ValueError("exact source font is unavailable")
    cache_key = f"{resolution.source_name}|{selected_font}"
    if cache_key in _created_styles:
        style_name = _created_styles[cache_key]
        if style_name in doc.styles:
            style = doc.styles.get(style_name)
            return style_name, _handle(style), False

    style_name = str(preferred_style_name or "").strip()
    if style_name and style_name in doc.styles:
        style = doc.styles.get(style_name)
        if str(style.dxf.font or "").strip().lower() != selected_font.lower():
            raise ValueError(
                f"existing text style {style_name!r} does not reference {selected_font!r}"
            )
        _created_styles[cache_key] = style_name
        return style_name, _handle(style), False
    if not style_name:
        while True:
            _style_counter += 1
            candidate = f"S{_style_counter}"
            if candidate not in doc.styles:
                style_name = candidate
                break
    style = doc.styles.add(style_name, font=selected_font)
    _created_styles[cache_key] = style_name
    return style_name, _handle(style), True


def _normalized_mode(value: Any) -> str:
    mode = str(value or "text").strip().lower()
    if mode == "label":
        return "labels"
    if mode == "native_text":
        return "text"
    if mode == "text3d":
        return "3d_text"
    if mode == "outlines":
        return "glyphs"
    return mode


def _source_id(text_item: NormalizedText) -> str:
    def exact_integer(value: Any) -> Optional[int]:
        if value is None or isinstance(value, (bool, str, bytes)):
            return None
        try:
            number = float(value)
            integer = int(value)
        except (OverflowError, TypeError, ValueError):
            return None
        if not math.isfinite(number) or number != float(integer):
            return None
        return integer

    page = exact_integer(getattr(text_item, "page_number", None))
    item_id = exact_integer(getattr(text_item, "id", None))
    if page is None or item_id is None:
        return ""
    return f"text_span:{page}:{item_id}"


def _positive_finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _target_advance_width(text_item: NormalizedText) -> Tuple[Optional[float], str]:
    explicit = _positive_finite(getattr(text_item, "advance_width", None))
    if explicit is not None:
        return explicit, "target_quad_model"

    target_quad = getattr(text_item, "target_quad_model", None)
    if target_quad and len(target_quad) >= 2:
        try:
            run_width = math.hypot(
                float(target_quad[1][0]) - float(target_quad[0][0]),
                float(target_quad[1][1]) - float(target_quad[0][1]),
            )
        except (TypeError, ValueError, IndexError):
            run_width = 0.0
        recovered = _positive_finite(run_width)
        if recovered is not None:
            return recovered, "target_quad_model"

    bbox = getattr(text_item, "bbox", None)
    if not bbox or len(bbox) < 4:
        return None, "unavailable"
    try:
        x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        angle = float(getattr(text_item, "rotation", 0.0) or 0.0) % 180.0
    except (TypeError, ValueError):
        return None, "unavailable"
    if math.isclose(angle, 0.0, abs_tol=1e-6) or math.isclose(
        angle, 180.0, abs_tol=1e-6
    ):
        return (_positive_finite(width), "axis_aligned_bbox")
    if math.isclose(angle, 90.0, abs_tol=1e-6):
        return (_positive_finite(height), "axis_aligned_bbox")
    return None, "unavailable_for_diagonal_bbox"


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_strict_finite_number(value: Any) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _finite_point(value: Any) -> Optional[Tuple[float, float]]:
    if value is None:
        return None
    try:
        if len(value) < 2:
            return None
        x = _finite_float(value[0])
        y = _finite_float(value[1])
    except (TypeError, IndexError):
        return None
    if x is None or y is None:
        return None
    return (x, y)


def _finite_quad(value: Any) -> Optional[Tuple[Tuple[float, float], ...]]:
    if value is None:
        return None
    try:
        if len(value) != 4:
            return None
    except TypeError:
        return None
    points = tuple(_finite_point(point) for point in value)
    if any(point is None for point in points):
        return None
    return tuple(point for point in points if point is not None)


def _quad_dimensions(
    quad: Tuple[Tuple[float, float], ...],
) -> Tuple[float, float]:
    return (
        math.hypot(quad[1][0] - quad[0][0], quad[1][1] - quad[0][1]),
        math.hypot(quad[3][0] - quad[0][0], quad[3][1] - quad[0][1]),
    )


def _validated_quad(
    value: Any,
    *,
    field_name: str,
) -> Tuple[Tuple[float, float], ...]:
    quad = _finite_quad(value)
    if quad is None:
        raise _RepresentationImpossible(f"{field_name} is missing or non-finite")
    advance, height = _quad_dimensions(quad)
    if advance <= 0.0 or height <= 0.0:
        raise _RepresentationImpossible(f"{field_name} is degenerate")
    expected_opposite = (
        quad[1][0] + quad[3][0] - quad[0][0],
        quad[1][1] + quad[3][1] - quad[0][1],
    )
    scale = max(1.0, *(abs(value) for point in quad for value in point))
    tolerance = scale * 1e-7
    if math.hypot(
        quad[2][0] - expected_opposite[0],
        quad[2][1] - expected_opposite[1],
    ) > tolerance:
        raise _RepresentationImpossible(f"{field_name} is not an affine text quad")
    return quad


def _outline_source_envelope(
    text_item: NormalizedText,
    *,
    representation: str,
) -> Tuple[Tuple[Tuple[float, float], ...], str]:
    """Derive finite placement truth without consulting generated DXF entities."""

    insertion = _finite_point(getattr(text_item, "insertion", None))
    if insertion is None:
        raise _RepresentationImpossible("source insertion is missing or non-finite")
    raw_quad = getattr(text_item, "target_quad_model", None)
    if raw_quad is not None:
        envelope = _validated_quad(raw_quad, field_name="target_quad_model")
        source = "target_quad_model"
    else:
        advance, advance_source = _target_advance_width(text_item)
        source_height = _positive_finite(getattr(text_item, "glyph_height", None))
        if source_height is None:
            source_height = _positive_finite(getattr(text_item, "font_size", None))
        rotation = _finite_float(getattr(text_item, "rotation", 0.0) or 0.0)
        descent = _finite_float(getattr(text_item, "baseline_descent", 0.0) or 0.0)
        if advance is None or source_height is None or rotation is None or descent is None:
            raise _RepresentationImpossible(
                "source envelope requires finite insertion, rotation, advance, and height"
            )
        angle = math.radians(rotation)
        baseline = (math.cos(angle), math.sin(angle))
        normal = (-baseline[1], baseline[0])
        lower_left = (
            insertion[0] - normal[0] * descent,
            insertion[1] - normal[1] * descent,
        )
        upper_left = (
            lower_left[0] + normal[0] * source_height,
            lower_left[1] + normal[1] * source_height,
        )
        upper_right = (
            upper_left[0] + baseline[0] * advance,
            upper_left[1] + baseline[1] * advance,
        )
        lower_right = (
            lower_left[0] + baseline[0] * advance,
            lower_left[1] + baseline[1] * advance,
        )
        envelope = (upper_left, upper_right, lower_right, lower_left)
        source = f"normalized_{advance_source}_rotation_height"
    if representation == "glyphs":
        envelope = tuple(
            (point[0] - insertion[0], point[1] - insertion[1]) for point in envelope
        )
    return envelope, source


def _path_bbox_tuple(
    paths: Sequence[Any],
    *,
    offset: Tuple[float, float] = (0.0, 0.0),
) -> Optional[Tuple[float, float, float, float]]:
    """Return a precise pre-entity path bound, optionally in final coordinates."""

    box = ezdxf_path.bbox(paths)
    if not box.has_data:
        return None
    values = (
        float(box.extmin.x) + offset[0],
        float(box.extmin.y) + offset[1],
        float(box.extmax.x) + offset[0],
        float(box.extmax.y) + offset[1],
    )
    return values if all(math.isfinite(value) for value in values) else None


def _bbox_union(
    boxes: Sequence[Optional[Tuple[float, float, float, float]]],
) -> Optional[Tuple[float, float, float, float]]:
    finite = [box for box in boxes if box is not None]
    if not finite:
        return None
    return (
        min(box[0] for box in finite),
        min(box[1] for box in finite),
        max(box[2] for box in finite),
        max(box[3] for box in finite),
    )


def _geometry_scale(
    bbox: Optional[Tuple[float, float, float, float]],
) -> float:
    if bbox is None:
        return 1e-9
    return max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]), 1e-9)


def _flattening_error(paths: Sequence[Any]) -> float:
    """Choose curve error from source size, never a fixed drawing-unit floor."""

    bbox = _path_bbox_tuple(paths)
    if bbox is None:
        # There is no geometric scale to preserve for zero-ink input.  Retain
        # ezdxf's established no-geometry triangulation setting; visible source
        # paths always take the source-scaled branch below.
        return 0.01
    scale = _geometry_scale(bbox)
    return min(0.01, max(scale * 1e-4, 1e-9))


def _geometry_comparison_tolerance(
    bbox: Optional[Tuple[float, float, float, float]],
    *,
    flattening_error: float,
) -> float:
    scale = _geometry_scale(bbox)
    coordinate_scale = max((1.0, *(abs(value) for value in bbox or ())))
    return (
        scale * 1e-8
        + max(float(flattening_error), 0.0) * 1e-4
        + coordinate_scale * 1e-12
        + 1e-12
    )


def _point_pair(value: Any) -> Tuple[float, float]:
    return (float(value[0]), float(value[1]))


def _point_triple(value: Any) -> Tuple[float, float, float]:
    return (float(value[0]), float(value[1]), float(value[2]))


def _path_geometry_expectations(
    paths: Sequence[Any],
    *,
    flattening_error: float,
) -> Tuple[_PathGeometryExpectation, ...]:
    expectations: List[_PathGeometryExpectation] = []
    for path in paths:
        commands: List[Tuple[str, Tuple[Tuple[float, float], ...]]] = []
        for command in path.commands():
            points = tuple(
                _point_pair(getattr(command, field_name))
                for field_name in getattr(command, "_fields", ())
            )
            commands.append((type(command).__name__, points))
        expectations.append(
            _PathGeometryExpectation(
                start=_point_pair(path.start),
                commands=tuple(commands),
                flattened_vertices=tuple(
                    _point_pair(point)
                    for point in path.flattening(flattening_error, segments=4)
                ),
                is_closed=bool(path.is_closed),
            )
        )
    return tuple(expectations)


def _points_match(
    expected: Sequence[Tuple[float, float]],
    actual: Sequence[Tuple[float, float]],
    *,
    tolerance: float,
) -> bool:
    return bool(
        len(expected) == len(actual)
        and all(
            math.hypot(left[0] - right[0], left[1] - right[1]) <= tolerance
            for left, right in zip(expected, actual, strict=True)
        )
    )


def _points3_match(
    expected: Sequence[Tuple[float, float, float]],
    actual: Sequence[Tuple[float, float, float]],
    *,
    tolerance: float,
) -> bool:
    return bool(
        len(expected) == len(actual)
        and all(
            math.dist(left, right) <= tolerance
            for left, right in zip(expected, actual, strict=True)
        )
    )


def _path_geometry_matches(
    expected: Sequence[_PathGeometryExpectation],
    actual_paths: Sequence[Any],
    *,
    flattening_error: float,
    tolerance: float,
) -> bool:
    actual = _path_geometry_expectations(
        actual_paths,
        flattening_error=flattening_error,
    )
    if len(expected) != len(actual):
        return False
    for expected_path, actual_path in zip(expected, actual, strict=True):
        if (
            expected_path.is_closed != actual_path.is_closed
            or not _points_match(
                (expected_path.start,),
                (actual_path.start,),
                tolerance=tolerance,
            )
            or len(expected_path.commands) != len(actual_path.commands)
        ):
            return False
        for expected_command, actual_command in zip(
            expected_path.commands,
            actual_path.commands,
            strict=True,
        ):
            if expected_command[0] != actual_command[0] or not _points_match(
                expected_command[1],
                actual_command[1],
                tolerance=tolerance,
            ):
                return False
        if not _points_match(
            expected_path.flattened_vertices,
            actual_path.flattened_vertices,
            tolerance=tolerance,
        ):
            return False
    return True


def _pre_entity_paths_verified(
    expected_paths: Sequence[Any],
    actual_paths: Sequence[Any],
) -> Tuple[
    bool,
    Optional[Tuple[float, float, float, float]],
    Optional[Tuple[float, float, float, float]],
    float,
    float,
]:
    expected_bbox = _path_bbox_tuple(expected_paths)
    actual_bbox = _path_bbox_tuple(actual_paths)
    flattening_error = _flattening_error(expected_paths)
    tolerance = _geometry_comparison_tolerance(
        expected_bbox,
        flattening_error=flattening_error,
    )
    verified = bool(
        _bbox_matches(
            expected_bbox,
            actual_bbox,
            flattening_error=flattening_error,
        )
        and _path_geometry_matches(
            _path_geometry_expectations(
                expected_paths,
                flattening_error=flattening_error,
            ),
            actual_paths,
            flattening_error=flattening_error,
            tolerance=tolerance,
        )
    )
    return (
        verified,
        expected_bbox,
        actual_bbox,
        flattening_error,
        tolerance,
    )


def _outline_entity_vertices(entity: Any) -> Tuple[Tuple[float, float], ...]:
    if entity.dxftype() == "LWPOLYLINE":
        return tuple(
            (float(point[0]), float(point[1]))
            for point in entity.get_points(format="xy")
        )
    if entity.dxftype() == "POLYLINE":
        return tuple(
            (float(vertex.dxf.location.x), float(vertex.dxf.location.y))
            for vertex in entity.vertices
        )
    return ()


def _outline_entities_match(
    expected: Sequence[_PathGeometryExpectation],
    entities: Sequence[Any],
    *,
    tolerance: float,
) -> bool:
    return bool(
        len(expected) == len(entities)
        and all(
            bool(path.is_closed) == bool(getattr(entity, "is_closed", False))
            and _points_match(
                path.flattened_vertices,
                _outline_entity_vertices(entity),
                tolerance=tolerance,
            )
            for path, entity in zip(expected, entities, strict=True)
        )
    )


def _triangulated_geometry(
    paths: Sequence[Any],
    *,
    flattening_error: float,
) -> Tuple[Tuple[Tuple[float, float], ...], ...]:
    triangles: List[Tuple[Tuple[float, float], ...]] = []
    for triangle in ezdxf_path.triangulate(
        paths,
        max_sagitta=flattening_error,
        min_segments=2,
    ):
        points = tuple(_point_pair(point) for point in triangle)
        if len(points) != 3:
            continue
        p0, p1, p2 = points
        area2 = abs(
            (p1[0] - p0[0]) * (p2[1] - p0[1])
            - (p1[1] - p0[1]) * (p2[0] - p0[0])
        )
        if math.isfinite(area2) and area2 > 1e-14:
            triangles.append(points)
    return tuple(triangles)


def _fill_entities_match(
    expected: Sequence[Tuple[Tuple[float, float], ...]],
    fills: Sequence[Any],
    *,
    tolerance: float,
) -> bool:
    actual = tuple(
        tuple(
            _point_triple(getattr(entity.dxf, f"vtx{index}"))
            for index in range(4)
        )
        for entity in fills
        if entity.dxftype() == "SOLID"
    )
    expected_with_four_vertices = tuple(
        tuple((point[0], point[1], 0.0) for point in triangle)
        + ((triangle[-1][0], triangle[-1][1], 0.0),)
        for triangle in expected
        if len(triangle) == 3
    )
    return bool(
        len(actual) == len(fills) == len(expected_with_four_vertices) == len(expected)
        and all(
            _points3_match(left, right, tolerance=tolerance)
            for left, right in zip(expected_with_four_vertices, actual, strict=True)
        )
    )


_OUTLINE_GEOMETRY_EVIDENCE_SCHEMA = "bcs-source-bound-outline-v1"


def _geometry_digest_quantum(tolerance: float) -> float:
    value = float(tolerance)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError("outline geometry tolerance is invalid")
    return max(value, 1e-12)


def _geometry_digest_number(value: Any, *, quantum: float) -> int:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("outline geometry contains a non-finite coordinate")
    return int(round(number / quantum))


def _geometry_digest_point(value: Any, *, quantum: float) -> List[int]:
    return [
        _geometry_digest_number(value[0], quantum=quantum),
        _geometry_digest_number(value[1], quantum=quantum),
    ]


def _geometry_digest_point3(value: Any, *, quantum: float) -> List[int]:
    return [
        _geometry_digest_number(value[0], quantum=quantum),
        _geometry_digest_number(value[1], quantum=quantum),
        _geometry_digest_number(value[2], quantum=quantum),
    ]


def _geometry_digest_scalar(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("outline geometry contains a non-finite scalar")
    if number == 0.0:
        number = 0.0
    return format(number, ".17g")


def _serialized_visual_attributes(entity: Any) -> Dict[str, Any]:
    doc = getattr(entity, "doc", None)
    if doc is None:
        raise ValueError("outline entity is not attached to a DXF document")
    layer_name = str(entity.dxf.get("layer", "0") or "0")
    try:
        layer = doc.layers.get(layer_name)
    except Exception as exc:
        raise ValueError(f"outline entity layer is missing: {layer_name!r}") from exc
    entity_transparency = float(entity.transparency)
    layer_transparency = float(layer.transparency)
    if not all(
        math.isfinite(value) for value in (entity_transparency, layer_transparency)
    ):
        raise ValueError("outline visibility contains non-finite transparency")
    return {
        "layer": layer_name,
        "layer_handle": _handle(layer),
        "layer_on": bool(layer.is_on()),
        "layer_frozen": bool(layer.is_frozen()),
        "layer_transparency": _geometry_digest_scalar(layer_transparency),
        "invisible": entity.dxf.get("invisible", 0),
        "transparency": _geometry_digest_scalar(entity_transparency),
        "color": int(entity.dxf.get("color", 256) or 0),
        "true_color": (
            int(entity.dxf.true_color) if entity.dxf.hasattr("true_color") else None
        ),
        "linetype": str(entity.dxf.get("linetype", "BYLAYER") or "BYLAYER"),
        "lineweight": int(entity.dxf.get("lineweight", -1)),
    }


def _canonical_source_outline_payload(
    expectation: _OutlineExpectation,
) -> Dict[str, Any]:
    """Return immutable source path truth, including curve control topology."""

    quantum = _geometry_digest_quantum(expectation.geometry_tolerance)
    paths = []
    command_count = 0
    control_point_count = 0
    flattened_vertex_count = 0
    for path in expectation.path_geometry:
        commands = []
        for command_name, control_points in path.commands:
            command_count += 1
            control_point_count += len(control_points)
            commands.append(
                [
                    str(command_name),
                    [
                        _geometry_digest_point(point, quantum=quantum)
                        for point in control_points
                    ],
                ]
            )
        flattened_vertex_count += len(path.flattened_vertices)
        paths.append(
            {
                "start": _geometry_digest_point(path.start, quantum=quantum),
                "commands": commands,
                "flattened_vertices": [
                    _geometry_digest_point(point, quantum=quantum)
                    for point in path.flattened_vertices
                ],
                "closed": bool(path.is_closed),
            }
        )
    fills = [
        [
            *[
                _geometry_digest_point(point, quantum=quantum)
                for point in triangle
            ],
            _geometry_digest_point(triangle[-1], quantum=quantum),
        ]
        for triangle in expectation.fill_geometry
    ]
    characters = [
        {
            "index": int(group.index),
            "text": group.text,
            "glyph_id": group.glyph_id,
            "visible_ink_expected": bool(group.visible_ink_expected),
            "path_count": len(group.expected_path_geometry),
            "fill_count": len(group.expected_fill_geometry),
            "advance_width": _geometry_digest_number(
                group.advance_width,
                quantum=quantum,
            ),
            "glyph_height": _geometry_digest_number(
                group.glyph_height,
                quantum=quantum,
            ),
            "rotation_degrees": _geometry_digest_number(
                group.rotation_degrees,
                quantum=quantum,
            ),
            "target_origin": _geometry_digest_point(
                group.target_origin,
                quantum=quantum,
            ),
            "target_quad": [
                _geometry_digest_point(point, quantum=quantum)
                for point in group.target_quad
            ],
        }
        for group in expectation.character_groups
    ]
    return {
        "schema": _OUTLINE_GEOMETRY_EVIDENCE_SCHEMA,
        "quantum": format(quantum, ".17g"),
        "source_geometry_verified": bool(expectation.source_geometry_verified),
        "source_envelope_source": expectation.source_envelope_source,
        "source_envelope": [
            _geometry_digest_point(point, quantum=quantum)
            for point in expectation.source_envelope
        ],
        "path_bbox": [
            _geometry_digest_number(value, quantum=quantum)
            for value in expectation.path_bbox
        ],
        "paths": paths,
        "fills": fills,
        "characters": characters,
        "path_count": len(paths),
        "command_count": command_count,
        "control_point_count": control_point_count,
        "flattened_vertex_count": flattened_vertex_count,
        "fill_count": len(fills),
    }


def _serialized_outline_payload(
    entities: Sequence[Any],
    *,
    tolerance: float,
) -> Dict[str, Any]:
    """Capture ordered persisted contour/fill geometry, including SOLID vtx3."""

    quantum = _geometry_digest_quantum(tolerance)
    serialized: List[Dict[str, Any]] = []
    for entity in entities:
        entity_type = entity.dxftype()
        if entity_type == "LWPOLYLINE":
            elevation = float(entity.dxf.get("elevation", 0.0) or 0.0)
            serialized.append(
                {
                    "kind": "outline",
                    "type": entity_type,
                    "closed": bool(getattr(entity, "is_closed", False)),
                    "vertices": [
                        {
                            "location": _geometry_digest_point3(
                                (point[0], point[1], elevation),
                                quantum=quantum,
                            ),
                            "start_width": _geometry_digest_scalar(point[2]),
                            "end_width": _geometry_digest_scalar(point[3]),
                            "bulge": _geometry_digest_scalar(point[4]),
                        }
                        for point in entity.get_points(format="xyseb")
                    ],
                    "const_width": _geometry_digest_scalar(
                        entity.dxf.get("const_width", 0.0) or 0.0
                    ),
                    "extrusion": _geometry_digest_point3(
                        entity.dxf.get("extrusion", (0.0, 0.0, 1.0)),
                        quantum=quantum,
                    ),
                    "visual": _serialized_visual_attributes(entity),
                }
            )
        elif entity_type == "POLYLINE":
            serialized.append(
                {
                    "kind": "outline",
                    "type": entity_type,
                    "closed": bool(getattr(entity, "is_closed", False)),
                    "flags": int(entity.dxf.get("flags", 0) or 0),
                    "vertices": [
                        {
                            "location": _geometry_digest_point3(
                                vertex.dxf.location,
                                quantum=quantum,
                            ),
                            "start_width": _geometry_digest_scalar(
                                vertex.dxf.get("start_width", 0.0) or 0.0
                            ),
                            "end_width": _geometry_digest_scalar(
                                vertex.dxf.get("end_width", 0.0) or 0.0
                            ),
                            "bulge": _geometry_digest_scalar(
                                vertex.dxf.get("bulge", 0.0) or 0.0
                            ),
                            "flags": int(vertex.dxf.get("flags", 0) or 0),
                        }
                        for vertex in entity.vertices
                    ],
                    "elevation": _geometry_digest_point3(
                        entity.dxf.get("elevation", (0.0, 0.0, 0.0)),
                        quantum=quantum,
                    ),
                    "extrusion": _geometry_digest_point3(
                        entity.dxf.get("extrusion", (0.0, 0.0, 1.0)),
                        quantum=quantum,
                    ),
                    "visual": _serialized_visual_attributes(entity),
                }
            )
        elif entity_type == "SOLID":
            serialized.append(
                {
                    "kind": "fill",
                    "type": entity_type,
                    "vertices": [
                        _geometry_digest_point3(
                            getattr(entity.dxf, f"vtx{index}"),
                            quantum=quantum,
                        )
                        for index in range(4)
                    ],
                    "extrusion": _geometry_digest_point3(
                        entity.dxf.get("extrusion", (0.0, 0.0, 1.0)),
                        quantum=quantum,
                    ),
                    "visual": _serialized_visual_attributes(entity),
                }
            )
        else:
            raise ValueError(f"unsupported serialized outline entity: {entity_type}")
    return {
        "schema": _OUTLINE_GEOMETRY_EVIDENCE_SCHEMA,
        "quantum": format(quantum, ".17g"),
        "entities": serialized,
    }


def _geometry_payload_sha256(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_outline_geometry_evidence(
    attempt: TextDeliveryAttempt,
    expectation: _OutlineExpectation,
    entities: Sequence[Any],
) -> None:
    source_payload = _canonical_source_outline_payload(expectation)
    serialized_payload = _serialized_outline_payload(
        entities,
        tolerance=expectation.geometry_tolerance,
    )
    attempt.evidence.update(
        {
            "outline_geometry_evidence_schema": _OUTLINE_GEOMETRY_EVIDENCE_SCHEMA,
            "canonical_source_outline_geometry_sha256": _geometry_payload_sha256(
                source_payload
            ),
            "canonical_source_outline_path_count": source_payload["path_count"],
            "canonical_source_outline_command_count": source_payload["command_count"],
            "canonical_source_outline_control_point_count": source_payload[
                "control_point_count"
            ],
            "canonical_source_outline_flattened_vertex_count": source_payload[
                "flattened_vertex_count"
            ],
            "canonical_source_solid_fill_count": source_payload["fill_count"],
            "serialized_outline_geometry_sha256": _geometry_payload_sha256(
                serialized_payload
            ),
            "serialized_outline_geometry_entity_count": len(entities),
        }
    )


def verify_serialized_outline_geometry(
    entities: Sequence[Any],
    evidence: Dict[str, Any],
) -> bool:
    """Verify reopened contour/fill bytes against source-bound delivery evidence."""

    if evidence.get("outline_geometry_evidence_schema") != _OUTLINE_GEOMETRY_EVIDENCE_SCHEMA:
        return False
    count_keys = (
        "serialized_outline_geometry_entity_count",
        "canonical_source_outline_path_count",
        "canonical_source_outline_command_count",
        "canonical_source_outline_control_point_count",
        "canonical_source_outline_flattened_vertex_count",
        "canonical_source_solid_fill_count",
    )
    try:
        raw_tolerance = evidence["outline_geometry_tolerance"]
        if isinstance(raw_tolerance, bool) or not isinstance(raw_tolerance, (int, float)):
            return False
        tolerance = float(raw_tolerance)
        counts = []
        for key in count_keys:
            value = evidence[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return False
            counts.append(value)
    except (KeyError, TypeError, ValueError):
        return False
    (
        expected_entity_count,
        expected_path_count,
        expected_command_count,
        expected_control_point_count,
        expected_flattened_vertex_count,
        expected_fill_count,
    ) = counts
    if (
        not math.isfinite(tolerance)
        or tolerance < 0.0
        or expected_entity_count != len(entities)
        or expected_path_count < 1
        or expected_command_count < expected_path_count
        or expected_control_point_count < expected_command_count
        or expected_flattened_vertex_count < expected_path_count
        or expected_fill_count < 1
        or expected_path_count + expected_fill_count != expected_entity_count
        or evidence.get("source_outline_geometry_verified") is not True
        or evidence.get("outline_topology_control_geometry_verified") is not True
        or evidence.get("solid_fill_geometry_verified") is not True
        or evidence.get("owned_outline_visibility_verified") is not True
    ):
        return False
    source_digest = str(evidence.get("canonical_source_outline_geometry_sha256") or "")
    serialized_digest = str(evidence.get("serialized_outline_geometry_sha256") or "")
    if not (
        re.fullmatch(r"[0-9a-f]{64}", source_digest)
        and re.fullmatch(r"[0-9a-f]{64}", serialized_digest)
    ):
        return False
    try:
        actual_payload = _serialized_outline_payload(entities, tolerance=tolerance)
    except (TypeError, ValueError, AttributeError):
        return False
    return _geometry_payload_sha256(actual_payload) == serialized_digest


def _path_geometry_within_envelope(
    geometry: Sequence[_PathGeometryExpectation],
    envelope: Tuple[Tuple[float, float], ...],
    *,
    tolerance: float,
) -> bool:
    """Verify geometry in the authoritative affine coordinate frame.

    A PDF/text quad is an advance/layout frame, not an ink clipping boundary.
    Exact fonts may have negative bearings, overshoots, swashes, or combining
    marks outside that frame.  Rejecting those source-authentic contours would
    silently make faithful Glyphs/Geometry delivery impossible.  The immutable
    independent path expectation and the later topology/control/vertex checks
    establish exact geometry; this check establishes that every expected point
    is finite and expressible relative to the authoritative source frame.
    """

    advance, height = _quad_dimensions(envelope)
    if not all(math.isfinite(value) and value > 0.0 for value in (advance, height)):
        return False
    geometry_seen = False
    for path in geometry:
        # Control points are verified exactly against the independent font
        # contour later.  Use visible flattened vertices here to establish the
        # expected ink in the authoritative affine coordinate frame.
        points = list(path.flattened_vertices)
        for point in points:
            geometry_seen = True
            try:
                horizontal, vertical = _quad_coordinates(point, envelope)
            except _RepresentationImpossible:
                return False
            if not all(math.isfinite(value) for value in (horizontal, vertical)):
                return False
    return geometry_seen and math.isfinite(tolerance) and tolerance >= 0.0


# Exact ranges from Unicode 17's DerivedCoreProperties.txt for the
# Default_Ignorable_Code_Point property:
# https://www.unicode.org/Public/17.0.0/ucd/DerivedCoreProperties.txt
# Python's unicodedata module does not expose derived binary properties, so
# keep the small, deterministic table locally instead of guessing from general
# categories such as Cf or Mn.  The latter would incorrectly suppress visible
# combining marks.
_DEFAULT_IGNORABLE_CODE_POINT_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)

# Exact White_Space ranges from Unicode 17's PropList.txt:
# https://www.unicode.org/Public/17.0.0/ucd/PropList.txt
_WHITE_SPACE_CODE_POINT_RANGES = (
    (0x0009, 0x000D),
    (0x0020, 0x0020),
    (0x0085, 0x0085),
    (0x00A0, 0x00A0),
    (0x1680, 0x1680),
    (0x2000, 0x200A),
    (0x2028, 0x2029),
    (0x202F, 0x202F),
    (0x205F, 0x205F),
    (0x3000, 0x3000),
)


def _is_default_ignorable_code_point(character: str) -> bool:
    code_point = ord(character)
    return any(
        first <= code_point <= last
        for first, last in _DEFAULT_IGNORABLE_CODE_POINT_RANGES
    )


def _is_unicode_white_space(character: str) -> bool:
    code_point = ord(character)
    return any(
        first <= code_point <= last
        for first, last in _WHITE_SPACE_CODE_POINT_RANGES
    )


def _visible_ink_expected(text: str) -> bool:
    return any(
        not _is_unicode_white_space(character)
        and not _is_default_ignorable_code_point(character)
        for character in text
    )


def _quad_coordinates(
    point: Tuple[float, float],
    quad: Tuple[Tuple[float, float], ...],
) -> Tuple[float, float]:
    baseline = (quad[1][0] - quad[0][0], quad[1][1] - quad[0][1])
    vertical = (quad[3][0] - quad[0][0], quad[3][1] - quad[0][1])
    relative = (point[0] - quad[0][0], point[1] - quad[0][1])
    determinant = baseline[0] * vertical[1] - baseline[1] * vertical[0]
    scale = max(1.0, abs(baseline[0]), abs(baseline[1]), abs(vertical[0]), abs(vertical[1]))
    if abs(determinant) <= scale * scale * 1e-12:
        raise _RepresentationImpossible("source character quad is singular")
    return (
        (relative[0] * vertical[1] - relative[1] * vertical[0]) / determinant,
        (baseline[0] * relative[1] - baseline[1] * relative[0]) / determinant,
    )


def _quad_linear_map(
    source_quad: Tuple[Tuple[float, float], ...],
    target_quad: Tuple[Tuple[float, float], ...],
) -> Tuple[float, float, float, float]:
    source_baseline = (
        source_quad[1][0] - source_quad[0][0],
        source_quad[1][1] - source_quad[0][1],
    )
    source_vertical = (
        source_quad[3][0] - source_quad[0][0],
        source_quad[3][1] - source_quad[0][1],
    )
    target_baseline = (
        target_quad[1][0] - target_quad[0][0],
        target_quad[1][1] - target_quad[0][1],
    )
    target_vertical = (
        target_quad[3][0] - target_quad[0][0],
        target_quad[3][1] - target_quad[0][1],
    )
    determinant = (
        source_baseline[0] * source_vertical[1]
        - source_baseline[1] * source_vertical[0]
    )
    scale = max(
        abs(source_baseline[0]),
        abs(source_baseline[1]),
        abs(source_vertical[0]),
        abs(source_vertical[1]),
        1e-9,
    )
    if abs(determinant) <= scale * scale * 1e-12:
        raise _RepresentationImpossible("source character quad is singular")
    return (
        (
            target_baseline[0] * source_vertical[1]
            - target_vertical[0] * source_baseline[1]
        )
        / determinant,
        (
            -target_baseline[0] * source_vertical[0]
            + target_vertical[0] * source_baseline[0]
        )
        / determinant,
        (
            target_baseline[1] * source_vertical[1]
            - target_vertical[1] * source_baseline[1]
        )
        / determinant,
        (
            -target_baseline[1] * source_vertical[0]
            + target_vertical[1] * source_baseline[0]
        )
        / determinant,
    )


def _validate_character_layout(
    text_item: NormalizedText,
) -> Tuple[_ValidatedCharacterLayout, ...]:
    raw_layout = tuple(getattr(text_item, "source_char_layout", ()) or ())
    source_text = str(getattr(text_item, "text", "") or "")
    if not raw_layout:
        raise _RepresentationImpossible(
            "individual positioning was requested without source character layout"
        )
    layout_text = "".join(str(getattr(item, "text", "") or "") for item in raw_layout)
    if layout_text != source_text:
        raise _RepresentationImpossible(
            "source character layout text/order does not match the source item"
        )
    validated: List[_ValidatedCharacterLayout] = []
    for index, item in enumerate(raw_layout):
        character = str(getattr(item, "text", "") or "")
        if len(character) != 1:
            raise _RepresentationImpossible(
                f"source character layout entry {index} must own exactly one "
                "source character"
            )
        source_quad = _validated_quad(
            getattr(item, "source_quad_pdf", None),
            field_name=f"source_char_layout[{index}].source_quad_pdf",
        )
        target_quad = _validated_quad(
            getattr(item, "target_quad", None),
            field_name=f"source_char_layout[{index}].target_quad",
        )
        source_origin = _finite_point(getattr(item, "source_origin_pdf", None))
        target_origin = _finite_point(getattr(item, "target_origin", None))
        source_bbox_value = getattr(item, "source_bbox_pdf", None)
        try:
            source_bbox = tuple(float(value) for value in source_bbox_value)
        except (TypeError, ValueError):
            source_bbox = ()
        if (
            source_origin is None
            or target_origin is None
            or len(source_bbox) != 4
            or not all(math.isfinite(value) for value in source_bbox)
            or source_bbox[0] > source_bbox[2]
            or source_bbox[1] > source_bbox[3]
        ):
            raise _RepresentationImpossible(
                f"source character layout entry {index} has invalid finite bounds/origins"
            )
        advance = _positive_finite(getattr(item, "advance_width", None))
        glyph_height = _positive_finite(getattr(item, "glyph_height", None))
        target_advance, target_height = _quad_dimensions(target_quad)
        if advance is None or glyph_height is None:
            raise _RepresentationImpossible(
                f"source character layout entry {index} has invalid advance or height"
            )
        metric_scale = max(1.0, advance, glyph_height, target_advance, target_height)
        if not (
            math.isclose(advance, target_advance, rel_tol=1e-7, abs_tol=metric_scale * 1e-7)
            and math.isclose(
                glyph_height,
                target_height,
                rel_tol=1e-7,
                abs_tol=metric_scale * 1e-7,
            )
        ):
            raise _RepresentationImpossible(
                f"source character layout entry {index} metrics do not match its target quad"
            )

        horizontal, vertical = _quad_coordinates(source_origin, source_quad)
        mapped_origin = (
            target_quad[0][0]
            + horizontal * (target_quad[1][0] - target_quad[0][0])
            + vertical * (target_quad[3][0] - target_quad[0][0]),
            target_quad[0][1]
            + horizontal * (target_quad[1][1] - target_quad[0][1])
            + vertical * (target_quad[3][1] - target_quad[0][1]),
        )
        origin_scale = max(1.0, *(abs(value) for value in mapped_origin + target_origin))
        if math.hypot(
            mapped_origin[0] - target_origin[0],
            mapped_origin[1] - target_origin[1],
        ) > origin_scale * 1e-7:
            raise _RepresentationImpossible(
                f"source character layout entry {index} target origin is not source-bound"
            )

        glyph_id = getattr(item, "glyph_id", None)
        if glyph_id is not None:
            try:
                integer_glyph_id = int(glyph_id)
            except (TypeError, ValueError):
                raise _RepresentationImpossible(
                    f"source character layout entry {index} has invalid glyph id"
                ) from None
            if integer_glyph_id != glyph_id:
                raise _RepresentationImpossible(
                    f"source character layout entry {index} has non-integral glyph id"
                )
            glyph_id = integer_glyph_id
        rotation_degrees = math.degrees(
            math.atan2(
                target_quad[1][1] - target_quad[0][1],
                target_quad[1][0] - target_quad[0][0],
            )
        )
        validated.append(
            _ValidatedCharacterLayout(
                index=index,
                text=character,
                glyph_id=glyph_id,
                target_origin=target_origin,
                target_quad=target_quad,
                advance_width=advance,
                glyph_height=glyph_height,
                rotation_degrees=rotation_degrees,
                visible_ink_expected=_visible_ink_expected(character),
                source_to_target_linear=_quad_linear_map(source_quad, target_quad),
            )
        )
    reference_linear = validated[0].source_to_target_linear
    linear_scale = max(1.0, *(abs(value) for value in reference_linear))
    linear_tolerance = linear_scale * 1e-7 + 1e-12
    for item in validated[1:]:
        if any(
            not math.isclose(left, right, rel_tol=0.0, abs_tol=linear_tolerance)
            for left, right in zip(
                reference_linear,
                item.source_to_target_linear,
                strict=True,
            )
        ):
            raise _RepresentationImpossible(
                "source character target affine transforms are inconsistent"
            )
    return tuple(validated)


def _validate_item_source_geometry(text_item: NormalizedText) -> None:
    """Reject contradictory source truth before any representation can claim it."""

    raw_quad = getattr(text_item, "target_quad_model", None)
    if raw_quad is not None:
        quad = _validated_quad(raw_quad, field_name="target_quad_model")
        insertion = _finite_point(getattr(text_item, "insertion", None))
        if insertion is None:
            raise _RepresentationImpossible("source insertion is missing or non-finite")
        advance, height = _quad_dimensions(quad)
        tolerance = max(advance, height, 1e-9) * 1e-7 + 1e-12
        horizontal, vertical = _quad_coordinates(insertion, quad)
        if abs(horizontal) > max(tolerance / advance, 1e-8) or not (
            0.0 - max(tolerance / height, 1e-8)
            <= vertical
            <= 1.0 + max(tolerance / height, 1e-8)
        ):
            raise _RepresentationImpossible(
                "source insertion is not bound to target_quad_model"
            )
        explicit_advance = _positive_finite(getattr(text_item, "advance_width", None))
        explicit_height = _positive_finite(getattr(text_item, "glyph_height", None))
        if explicit_advance is not None and not math.isclose(
            explicit_advance,
            advance,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise _RepresentationImpossible(
                "source advance does not match target_quad_model"
            )
        if explicit_height is not None and not math.isclose(
            explicit_height,
            height,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise _RepresentationImpossible(
                "source height does not match target_quad_model"
            )
    if bool(getattr(text_item, "requires_individual_positioning", False)):
        _validate_character_layout(text_item)


def _handle(entity: Any) -> str:
    return str(getattr(getattr(entity, "dxf", None), "handle", "") or "")


def _is_live_handle(doc: ezdxf.document.Drawing, handle: str) -> bool:
    if not handle:
        return False
    entity = doc.entitydb.get(str(handle))
    return bool(entity is not None and getattr(entity, "is_alive", True))


def _delete_entity(layout: Any, entity: Any) -> bool:
    handle = _handle(entity)
    try:
        if getattr(entity, "is_alive", True):
            layout.delete_entity(entity)
    except Exception:
        try:
            entity.destroy()
        except Exception:
            return False
    return bool(handle)


def _delete_block(doc: ezdxf.document.Drawing, name: str) -> bool:
    try:
        doc.blocks.delete_block(name, safe=False)
        return True
    except Exception:
        return False


def _delete_owned_style(
    doc: ezdxf.document.Drawing,
    style_name: str,
    style_handle: str,
    attempt: TextDeliveryAttempt,
) -> None:
    if not style_name or not style_handle:
        return
    try:
        doc.styles.remove(style_name)
    except Exception:
        return
    if style_handle not in attempt.removed_entity_handles:
        attempt.removed_entity_handles.append(style_handle)
    for key, cached_name in list(_created_styles.items()):
        if cached_name == style_name:
            _created_styles.pop(key, None)


def _verify_owned_state(
    doc: ezdxf.document.Drawing,
    attempt: TextDeliveryAttempt,
) -> bool:
    created = {handle for handle in attempt.created_entity_handles if handle}
    removed = {handle for handle in attempt.removed_entity_handles if handle}
    retained = {
        handle
        for handle in attempt.entity_handles + attempt.support_entity_handles
        if handle
    }
    if created != removed | retained or removed & retained:
        return False
    if any(_is_live_handle(doc, handle) for handle in removed):
        return False
    if any(not _is_live_handle(doc, handle) for handle in retained):
        return False
    if any(
        not _is_live_handle(doc, handle)
        for handle in attempt.referenced_entity_handles
        if handle
    ):
        return False
    return True


def _bbox_tuple(entities: Sequence[Any]) -> Optional[Tuple[float, float, float, float]]:
    box = ezdxf_bbox.extents(entities)
    if not box.has_data:
        return None
    return (
        float(box.extmin.x),
        float(box.extmin.y),
        float(box.extmax.x),
        float(box.extmax.y),
    )


def _bbox_matches(
    expected: Optional[Tuple[float, float, float, float]],
    actual: Optional[Tuple[float, float, float, float]],
    *,
    offset: Tuple[float, float] = (0.0, 0.0),
    flattening_error: float = 0.0,
) -> bool:
    if expected is None or actual is None:
        return False
    shifted = (
        expected[0] + offset[0],
        expected[1] + offset[1],
        expected[2] + offset[0],
        expected[3] + offset[1],
    )
    tolerance = _geometry_comparison_tolerance(
        shifted,
        flattening_error=flattening_error,
    )
    # Exact curve extents and their flattened polyline extents may differ by up
    # to the chosen source-scaled sagitta.  This remains far below the old fixed
    # drawing-unit floor and cannot hide a large relative error on a small glyph.
    tolerance = max(tolerance, max(float(flattening_error), 0.0))
    return all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)
        for left, right in zip(shifted, actual, strict=True)
    )


def _base_attributes(
    text_item: NormalizedText,
    *,
    layer_name: str,
    height: float,
    insert: Tuple[float, float],
    is_r12: bool,
    style_name: str,
) -> Dict[str, Any]:
    attribs: Dict[str, Any] = {
        "layer": layer_name,
        "rotation": float(getattr(text_item, "rotation", 0.0) or 0.0),
        "height": height,
        "insert": insert,
    }
    text_color = getattr(text_item, "color", None)
    if text_color is not None and not is_r12:
        from ezdxf.colors import rgb2int

        rgb = tuple(round(float(component) * 255) for component in text_color[:3])
        attribs["true_color"] = rgb2int(rgb)
    attribs["style"] = style_name
    return attribs


def _fit_text_advance(
    entity: Any,
    target_width: Optional[float],
    *,
    parent_fit_alignment: bool = False,
) -> Optional[float]:
    actual_text = str(getattr(entity.dxf, "text", "") or "")
    if entity.dxftype() == "TEXT" and actual_text and not _visible_ink_expected(
        actual_text
    ):
        return 0.0
    if target_width is None or entity.dxftype() != "TEXT":
        return None
    if parent_fit_alignment:
        from ezdxf.enums import TextEntityAlignment

        insert = tuple(float(value) for value in entity.dxf.insert)[:2]
        angle = math.radians(float(entity.dxf.rotation or 0.0))
        endpoint = (
            insert[0] + target_width * math.cos(angle),
            insert[1] + target_width * math.sin(angle),
        )
        entity.set_placement(insert, endpoint, align=TextEntityAlignment.FIT)
        return target_width
    measured = float(text_size(entity).width)
    if not math.isfinite(measured) or measured <= 0.0:
        raise ValueError("DXF text width could not be measured")
    width_factor = target_width / measured
    if not math.isfinite(width_factor) or width_factor <= 0.0:
        raise ValueError("DXF text width factor is invalid")
    entity.dxf.width = width_factor
    return float(text_size(entity).width)


def _verify_label(
    entity: Any,
    text_item: NormalizedText,
    *,
    height: float,
    target_width: Optional[float],
    measured_width: Optional[float],
    width_source: str,
    expected_content: Optional[str] = None,
) -> Tuple[bool, bool, Dict[str, Any]]:
    entity_type = entity.dxftype()
    type_ok = entity_type in {"TEXT", "MTEXT"}
    actual_text = str(
        entity.dxf.text if entity_type == "TEXT" else entity.plain_text()
    )
    if entity_type == "TEXT":
        insert = tuple(entity.dxf.insert)[:2]
        actual_height = float(entity.dxf.height)
        actual_rotation = float(entity.dxf.rotation)
    else:
        insert = tuple(entity.dxf.insert)[:2]
        actual_height = float(entity.dxf.char_height)
        actual_rotation = float(entity.dxf.rotation)

    expected_insert = tuple(float(value) for value in text_item.insertion[:2])
    expected_rotation = float(getattr(text_item, "rotation", 0.0) or 0.0)
    expected_text = str(text_item.text if expected_content is None else expected_content)
    content_ok = actual_text == expected_text
    insert_ok = all(
        math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
        for left, right in zip(insert, expected_insert, strict=True)
    )
    height_ok = math.isclose(actual_height, height, rel_tol=1e-9, abs_tol=1e-12)
    rotation_ok = math.isclose(
        actual_rotation, expected_rotation, rel_tol=0.0, abs_tol=1e-9
    )
    whitespace_zero_ink = bool(
        actual_text and not _visible_ink_expected(actual_text) and measured_width == 0.0
    )
    fit_alignment_verified = False
    if entity_type == "TEXT" and int(entity.dxf.halign or 0) == 5 and target_width:
        align_point = tuple(float(value) for value in entity.dxf.align_point)[:2]
        fit_width = math.hypot(
            align_point[0] - float(insert[0]),
            align_point[1] - float(insert[1]),
        )
        expected_angle = math.radians(expected_rotation)
        expected_endpoint = (
            float(insert[0]) + target_width * math.cos(expected_angle),
            float(insert[1]) + target_width * math.sin(expected_angle),
        )
        fit_alignment_verified = bool(
            math.isclose(fit_width, target_width, rel_tol=1e-9, abs_tol=1e-12)
            and all(
                math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)
                for left, right in zip(
                    align_point,
                    expected_endpoint,
                    strict=True,
                )
            )
        )
    width_ok = whitespace_zero_ink or fit_alignment_verified or bool(
        target_width is not None
        and measured_width is not None
        and math.isclose(
            measured_width,
            target_width,
            rel_tol=1e-6,
            abs_tol=max(1e-9, target_width * 1e-8),
        )
    )
    visual_ok = content_ok and insert_ok and height_ok and rotation_ok and width_ok
    return type_ok, visual_ok, {
        "entity_type": entity_type,
        "content_verified": content_ok,
        "source_content": str(text_item.text),
        "delivered_content": actual_text,
        "content_compatibility_normalized": actual_text != str(text_item.text),
        "anchor_verified": insert_ok,
        "height_verified": height_ok,
        "rotation_verified": rotation_ok,
        "width_verified": width_ok,
        "fit_alignment_verified": fit_alignment_verified,
        "whitespace_zero_ink_verified": whitespace_zero_ink,
        "width_source": width_source,
        "expected_insert": list(expected_insert),
        "actual_insert": list(insert),
        "expected_height": height,
        "actual_height": actual_height,
        "expected_rotation": expected_rotation,
        "actual_rotation": actual_rotation,
        "expected_advance_width": target_width,
        "actual_advance_width": measured_width,
    }


def _verify_parent_native_text_delivery(
    *,
    target_app: str,
    style_font: str,
    parent_font_format: str,
    parent_font_substituted: bool,
    entity: Any,
    style_name: str,
    style_handle: str,
    is_3d_text: bool,
    source_content_whitespace_only: bool,
) -> Tuple[bool, Dict[str, Any], str]:
    """Verify native editable delivery without inventing source-font equivalence.

    DXF accepts TTF/OTF names, but LibreCAD's native text renderer consumes its
    own LFF stroke-font format.  Merely writing a TEXT entity with a TTF/OTF
    style therefore proves the DXF declaration, not the pixels LibreCAD will
    display.  This gate runs only after the item-specific entity was created so
    the failure evidence and cleanup ownership belong to that exact source span.
    """

    parent = str(target_app or "generic").strip().lower()
    candidate_format = str(parent_font_format or "unknown").strip().lower()
    evidence: Dict[str, Any] = {
        "target_app": parent,
        "item_specific_creation_attempted": True,
        "created_entity_handle": _handle(entity),
        "created_style_name": style_name,
        "created_style_handle": style_handle,
        "parent_native_font_candidate": style_font or None,
        "parent_native_font_candidate_format": candidate_format,
        "parent_native_font_substituted": bool(parent_font_substituted),
        "parent_source_font_equivalence_verified": not bool(
            parent_font_substituted
        ),
    }
    if parent != "librecad":
        source_visual_ok = bool(
            source_content_whitespace_only or not bool(parent_font_substituted)
        )
        parent_delivery_ok = source_visual_ok
        evidence.update(
            {
                "parent_native_font_required_format": None,
                "parent_native_font_format_verified": True,
                "parent_native_font_renderability_verified": True,
                "parent_native_text_delivery_verified": parent_delivery_ok,
                "parent_native_3d_display_verified": True,
                "parent_visual_fidelity_verified": source_visual_ok,
                "fallback_authorized_for_this_item": not parent_delivery_ok,
            }
        )
        reason = ""
        if not parent_delivery_ok:
            reason = (
                "the parent font is a substitute and exact source-font visual "
                "equivalence is not verified for this visible item"
            )
        return parent_delivery_ok, evidence, reason

    font_ok = candidate_format == "lff" and bool(str(style_font or "").strip())
    # A whitespace-only PDF span has no font pixels to reproduce.  A native
    # TEXT entity still preserves its exact semantic content and placement, so
    # requiring an LFF renderer for pixels that do not exist would manufacture
    # a false impossibility and can ultimately rasterize unrelated nearby ink.
    font_rendering_required = not source_content_whitespace_only
    font_requirement_ok = bool(font_ok or not font_rendering_required)
    native_3d_ok = not is_3d_text
    source_visual_ok = bool(
        native_3d_ok
        and (
            not font_rendering_required
            or (font_ok and not bool(parent_font_substituted))
        )
    )
    parent_delivery_ok = bool(font_requirement_ok and source_visual_ok)
    evidence.update(
        {
            "parent_native_font_required_format": "lff",
            "parent_native_font_format_verified": font_ok,
            "parent_native_font_renderability_verified": font_ok,
            "parent_native_font_rendering_required": font_rendering_required,
            "source_content_whitespace_only": source_content_whitespace_only,
            "parent_native_3d_display_verified": native_3d_ok,
            "parent_native_text_delivery_verified": parent_delivery_ok,
            "parent_visual_fidelity_verified": source_visual_ok,
            "fallback_authorized_for_this_item": not parent_delivery_ok,
        }
    )
    reasons: List[str] = []
    if not font_requirement_ok:
        reasons.append(
            "the exact source font program is "
            f"{candidate_format}, not a LibreCAD-renderable LFF program"
        )
    elif (
        font_rendering_required
        and font_ok
        and bool(parent_font_substituted)
    ):
        reasons.append(
            "the LibreCAD-renderable LFF candidate is a substitute and cannot "
            "reproduce the embedded source face for this visible item"
        )
    if not native_3d_ok:
        reasons.append(
            "the created TEXT thickness is not verified as visible/editable 3D text "
            "in the LibreCAD parent"
        )
    return parent_delivery_ok, evidence, "; ".join(reasons)


def _attempt_labels(
    text_item: NormalizedText,
    msp: Any,
    layer_name: str,
    *,
    requested: str,
    source_id: str,
    is_r12: bool,
    target_app: str,
    dxf_version: str,
    config: ImportConfig,
    extrusion_depth: Optional[float] = None,
    semantic_representation: str = "labels",
) -> TextDeliveryAttempt:
    is_3d_text = extrusion_depth is not None
    semantic_representation = _normalized_mode(semantic_representation)
    if semantic_representation not in {"text", "labels"}:
        semantic_representation = "labels"
    attempted_representation = (
        "3d_text" if is_3d_text else semantic_representation
    )
    attempt = TextDeliveryAttempt(
        source_id=source_id,
        requested_representation=requested,
        attempted_representation=attempted_representation,
        strategy="native_dxf_text_extrusion" if is_3d_text else "native_dxf_text",
    )
    doc = msp.doc
    entity = None
    style_name = ""
    style_handle = ""
    style_created = False
    try:
        parent = str(target_app or "generic").strip().lower()
        if not is_3d_text and semantic_representation == "labels":
            # DXF has TEXT and MTEXT entities but no native Label entity.  A
            # report-only semantic tag on either text entity would be a peer
            # alias, not delivery of the distinct requested representation.
            # Record the exact item-scoped schema evaluation, create no wrong-
            # type artifact, and let the finite ladder try editable Text next.
            attempt.reason = (
                "_RepresentationImpossible: the DXF export contract exposes "
                "no native Label entity; TEXT/MTEXT aliases are not accepted"
            )
            attempt.evidence.update(
                {
                    "target_app": parent,
                    "parent_export_format": "dxf",
                    "source_item_id": source_id,
                    "item_specific_capability_evaluation": True,
                    "item_specific_creation_attempted": False,
                    "parent_native_label_entity_available": False,
                    "available_parent_text_entity_types": ["TEXT", "MTEXT"],
                    "text_alias_accepted_as_label": False,
                    "fallback_authorized_for_this_item": True,
                }
            )
            attempt.outcome = "impossible"
            attempt.cleanup_verified = True
            return attempt
        if is_3d_text:
            depth = _positive_finite(extrusion_depth)
            if depth is None:
                raise ValueError("3D text extrusion depth is missing or invalid")
        else:
            depth = None
        source_em_height = _positive_finite(getattr(text_item, "font_size", None))
        if source_em_height is None:
            raise _RepresentationImpossible(
                "source nominal text height is missing or invalid for structural delivery"
            )
        insert = tuple(float(value) for value in text_item.insertion[:2])
        font_resolution = _resolve_item_font(text_item, config)
        attempt.evidence.update(font_resolution.evidence())
        if parent == "librecad":
            # LibreCAD's editable native text renderer consumes its bundled LFF
            # fonts. Preserve the requested Text/Labels representation and use
            # the broad Unicode LFF face; a font substitution is not a change
            # of representation. The source advance and height below still
            # drive the exact item transform, while DXF FIT alignment delegates
            # the final horizontal fit to the parent renderer.
            style_font = "unicode"
            parent_font_format = "lff"
            parent_font_substituted = True
            preferred_style_name = "unicode"
        else:
            if not font_resolution.exact:
                if font_resolution.item_impossibility_proven:
                    raise _RepresentationImpossible(font_resolution.reason)
                raise ValueError(font_resolution.reason)
            style_font = font_resolution.filename
            parent_font_format = (
                Path(str(style_font or "")).suffix.lower().lstrip(".") or "unknown"
            )
            parent_font_substituted = not _source_font_program_is_authoritative(
                font_resolution
            )
            preferred_style_name = None
        height, cap_height_ratio = _delivery_cap_height(
            source_em_height, font_resolution
        )
        style_name, style_handle, style_created = _ensure_text_style(
            doc,
            font_resolution,
            style_font=style_font,
            preferred_style_name=preferred_style_name,
        )
        if style_created:
            attempt.created_entity_handles.append(style_handle)
            attempt.support_entity_handles.append(style_handle)
        else:
            attempt.referenced_entity_handles.append(style_handle)
        attribs = _base_attributes(
            text_item,
            layer_name=layer_name,
            height=height,
            insert=insert,
            is_r12=is_r12,
            style_name=style_name,
        )
        force_text = (
            is_3d_text
            or semantic_representation == "text"
            or
            is_r12
            or str(target_app or "").lower() == "librecad"
            or str(dxf_version or "R2010") <= "R2000"
        )
        # Representation fallback must not rewrite source content.  In
        # particular, NFKC maps compatibility characters such as Hangul
        # fillers to different code points even though DXF can preserve the
        # original Unicode string exactly.
        delivered_text = str(text_item.text)
        if len(delivered_text) > _MTEXT_THRESHOLD and not force_text:
            mtext_attribs = dict(attribs)
            mtext_attribs.pop("height", None)
            mtext_attribs.pop("insert", None)
            mtext_attribs["char_height"] = height
            entity = msp.add_mtext(delivered_text, dxfattribs=mtext_attribs)
            entity.set_location(insert, attachment_point=1)
        else:
            entity = msp.add_text(delivered_text, dxfattribs=attribs)

        if is_3d_text:
            if entity.dxftype() != "TEXT":
                raise ValueError("native 3D text requires a DXF TEXT entity")
            entity.dxf.thickness = float(depth)
            entity.dxf.extrusion = (0.0, 0.0, 1.0)

        handle = _handle(entity)
        attempt.created_entity_handles.append(handle)
        target_width, width_source = _target_advance_width(text_item)
        measured_width = _fit_text_advance(
            entity,
            target_width,
            parent_fit_alignment=parent == "librecad",
        )
        type_ok, visual_ok, evidence = _verify_label(
            entity,
            text_item,
            height=height,
            target_width=target_width,
            measured_width=measured_width,
            width_source=width_source,
            expected_content=delivered_text,
        )
        attempt.type_verified = type_ok
        attempt.visual_verified = visual_ok
        attempt.evidence.update(evidence)
        attempt.evidence["semantic_representation"] = attempted_representation
        if semantic_representation == "text" and entity.dxftype() != "TEXT":
            type_ok = False
            attempt.type_verified = False
        if is_3d_text:
            actual_depth = float(entity.dxf.thickness)
            actual_extrusion = tuple(float(value) for value in entity.dxf.extrusion)
            depth_ok = math.isclose(
                actual_depth,
                float(depth),
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
            extrusion_ok = all(
                math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
                for left, right in zip(
                    actual_extrusion,
                    (0.0, 0.0, 1.0),
                    strict=True,
                )
            )
            type_ok = bool(type_ok and entity.dxftype() == "TEXT" and depth_ok)
            visual_ok = bool(visual_ok and extrusion_ok)
            attempt.evidence.update(
                {
                    "target_app": str(target_app or "generic").strip().lower(),
                    "dxf_version": str(dxf_version),
                    "item_specific_creation_attempted": True,
                    "entity_type": entity.dxftype(),
                    "extrusion_depth_mm": float(depth),
                    "actual_extrusion_depth_mm": actual_depth,
                    "extrusion_vector": list(actual_extrusion),
                    "extrusion_depth_verified": depth_ok,
                    "extrusion_vector_verified": extrusion_ok,
                    "flat_text_alias_accepted": False,
                }
            )
        parent_delivery_ok, parent_evidence, parent_reason = (
            _verify_parent_native_text_delivery(
                target_app=target_app,
                style_font=style_font,
                parent_font_format=parent_font_format,
                parent_font_substituted=parent_font_substituted,
                entity=entity,
                style_name=style_name,
                style_handle=style_handle,
                is_3d_text=is_3d_text,
                source_content_whitespace_only=not _visible_ink_expected(
                    str(getattr(text_item, "text", "") or "")
                ),
            )
        )
        attempt.evidence.update(parent_evidence)
        visual_ok = bool(visual_ok and parent_delivery_ok)
        attempt.visual_verified = visual_ok
        attempt.evidence.update(
            {
                "source_font_em_height": source_em_height,
                "source_cap_height_ratio": cap_height_ratio,
            }
        )
        if not parent_delivery_ok:
            raise _RepresentationImpossible(parent_reason)
        if not type_ok or not visual_ok:
            label = "native 3D text" if is_3d_text else "native DXF text"
            raise ValueError(f"{label} failed type or visual verification")

        attempt.entity_handles = [handle]
        attempt.outcome = "verified"
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        if not attempt.cleanup_verified:
            raise ValueError("native DXF text ownership verification failed")
        return attempt
    except Exception as exc:
        attempt.reason = f"{type(exc).__name__}: {exc}"
        if entity is not None:
            handle = _handle(entity)
            if _delete_entity(msp, entity):
                attempt.removed_entity_handles.append(handle)
        if style_created:
            _delete_owned_style(doc, style_name, style_handle, attempt)
        attempt.entity_handles = []
        attempt.support_entity_handles = []
        attempt.outcome = (
            "impossible" if isinstance(exc, _RepresentationImpossible) else "failed"
        )
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        return attempt


def _outline_attributes(attribs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in attribs.items()
        if key in {"layer", "color", "true_color", "lineweight", "linetype"}
    }


def _to_outline_entities(
    paths: Sequence[Any],
    *,
    is_r12: bool,
    attribs: Dict[str, Any],
) -> List[Any]:
    distance = _flattening_error(paths)
    if is_r12:
        entities = list(
            ezdxf_path.to_polylines2d(
                paths,
                distance=distance,
                segments=4,
                dxfattribs=attribs,
            )
        )
    else:
        entities = list(
            ezdxf_path.to_lwpolylines(
                paths,
                distance=distance,
                segments=4,
                dxfattribs=attribs,
            )
        )
    if len(entities) == len(paths):
        for path, entity in zip(paths, entities, strict=True):
            entity.close(bool(path.is_closed))
    return entities


def _to_solid_fill_entities(
    paths: Sequence[Any],
    *,
    is_r12: bool,
    attribs: Dict[str, Any],
) -> List[Any]:
    """Return parent-visible solid fills while preserving outline ownership.

    Use contour-aware triangulation for every DXF version. LibreCAD can
    misrender nested HATCH boundaries inside blocks, while SOLID triangles are
    stable in the parent and are also available in R12.
    """

    from ezdxf.entities import factory

    fills: List[Any] = []
    for triangle in ezdxf_path.triangulate(
        paths,
        max_sagitta=_flattening_error(paths),
        # The sagitta bound is the visual-accuracy oracle. Requiring sixteen
        # segments for every Bézier inflated real drawings by hundreds of MB
        # without improving that bound; two prevents pathological under-sampling
        # while adaptive flattening adds segments wherever curvature requires.
        min_segments=2,
    ):
        points = [(float(point.x), float(point.y)) for point in triangle]
        if len(points) != 3:
            continue
        p0, p1, p2 = points
        area2 = abs(
            (p1[0] - p0[0]) * (p2[1] - p0[1])
            - (p1[1] - p0[1]) * (p2[0] - p0[0])
        )
        # ezdxf's contour triangulator can emit duplicate-point slivers for
        # otherwise valid glyphs. They carry no visible area, so retaining one
        # would make the serialized fill unverifiable without improving the
        # parent render. Keep the valid triangles and discard only the artifact.
        if not math.isfinite(area2) or area2 <= 1e-14:
            continue
        fills.append(
            factory.new(
                "SOLID",
                dxfattribs={
                    **attribs,
                    "vtx0": p0,
                    "vtx1": p1,
                    "vtx2": p2,
                    "vtx3": p2,
                },
            )
        )
    return fills


def _solid_fill_verified(fills: Sequence[Any], *, is_r12: bool) -> bool:
    if not fills:
        return False
    expected_type = "SOLID"
    if any(entity.dxftype() != expected_type for entity in fills):
        return False
    for entity in fills:
        points = tuple(
            _point_triple(getattr(entity.dxf, f"vtx{index}"))
            for index in range(4)
        )
        if not all(math.isfinite(value) for point in points for value in point):
            return False
        p0, p1, p2, p3 = points
        area2 = abs(
            (p1[0] - p0[0]) * (p2[1] - p0[1])
            - (p1[1] - p0[1]) * (p2[0] - p0[0])
        )
        coordinate_scale = max(1.0, *(abs(value) for point in points for value in point))
        if (
            not math.isfinite(area2)
            or area2 <= 1e-14
            or not _points_match(
                ((p2[0], p2[1]),),
                ((p3[0], p3[1]),),
                tolerance=coordinate_scale * 1e-12,
            )
            or not math.isclose(
                p2[2],
                p3[2],
                rel_tol=0.0,
                abs_tol=coordinate_scale * 1e-12,
            )
            or any(
                not math.isclose(
                    point[2],
                    0.0,
                    rel_tol=0.0,
                    abs_tol=coordinate_scale * 1e-12,
                )
                for point in points
            )
        ):
            return False
    return True


def _visible_font_ink_width(font: Any, text: str, *, height: float) -> float:
    """Return finite source-font ink width without using glyph advance.

    Combining marks can own visible contours while intentionally advancing the
    text cursor by zero.  Their ink is still a valid affine scaling basis.
    """

    path = font.text_path_ex(text, cap_height=height).to_path()
    box = ezdxf_path.bbox(list(path.sub_paths()))
    if not box.has_data:
        return 0.0
    width = float(box.extmax.x) - float(box.extmin.x)
    return width if math.isfinite(width) and width > 0.0 else 0.0


def _make_scaled_string_paths(
    text: str,
    face: FontFace,
    *,
    height: float,
    target_advance: Optional[float],
    rotation_degrees: float,
    translation: Tuple[float, float] = (0.0, 0.0),
    source_transform: Optional[Matrix44] = None,
) -> Tuple[List[Any], float, float]:
    """Create source paths with an explicit baseline scale and placement."""

    font = text2path.get_font(face)
    natural_advance = float(font.text_width(text)) * height
    if not math.isfinite(natural_advance) or natural_advance < 0.0:
        raise ValueError("font returned an invalid source advance")
    if target_advance is None:
        width_scale = 1.0
        delivered_advance = natural_advance
    elif natural_advance > 0.0:
        width_scale = target_advance / natural_advance
        delivered_advance = natural_advance * width_scale
    elif _visible_ink_expected(text):
        ink_width = _visible_font_ink_width(font, text, height=height)
        if ink_width <= 0.0:
            raise ValueError("visible zero-advance source character has no font contour")
        width_scale = target_advance / ink_width
        delivered_advance = target_advance
    else:
        width_scale = 1.0
        delivered_advance = 0.0
    if not math.isfinite(width_scale) or width_scale <= 0.0:
        raise ValueError("font baseline scale is invalid")
    transform = source_transform or (
        Matrix44.scale(width_scale, 1.0, 1.0)
        * Matrix44.z_rotate(math.radians(rotation_degrees))
        * Matrix44.translate(translation[0], translation[1], 0.0)
    )
    render_height = 1.0 if source_transform is not None else height
    paths = list(
        text2path.make_paths_from_str(
            text,
            face,
            size=render_height,
            m=transform,
        )
    )
    return paths, delivered_advance, width_scale


def _independent_font_paths(
    text: str,
    face: FontFace,
    *,
    height: float,
    transform: Matrix44,
) -> List[Any]:
    """Read exact font contours without calling the delivery renderer wrapper."""

    font = text2path.get_font(face)
    path = font.text_path_ex(text, cap_height=height).to_path()
    return list(path.transform(transform).sub_paths())


def _authoritative_quad_transform(
    text: str,
    face: FontFace,
    *,
    target_quad: Tuple[Tuple[float, float], ...],
    target_origin: Tuple[float, float],
    target_advance: float,
    target_height: float,
) -> Tuple[Matrix44, float, float]:
    """Map exact source-font contours through the authoritative affine quad."""

    quad = _validated_quad(target_quad, field_name="authoritative target quad")
    quad_advance, quad_height = _quad_dimensions(quad)
    metric_scale = max(quad_advance, quad_height, target_advance, target_height, 1e-9)
    metric_tolerance = metric_scale * 1e-7 + 1e-12
    if not (
        math.isclose(target_advance, quad_advance, rel_tol=0.0, abs_tol=metric_tolerance)
        and math.isclose(target_height, quad_height, rel_tol=0.0, abs_tol=metric_tolerance)
    ):
        raise _RepresentationImpossible(
            "authoritative target metrics do not match the target quad"
        )

    horizontal, vertical = _quad_coordinates(target_origin, quad)
    normalized_tolerance = max(metric_tolerance / quad_advance, 1e-8)
    if abs(horizontal) > normalized_tolerance or not (
        normalized_tolerance < vertical <= 1.0 + normalized_tolerance
    ):
        raise _RepresentationImpossible(
            "source baseline origin is not bound to the authoritative target quad"
        )

    font = text2path.get_font(face)
    natural_advance = float(font.text_width(text))
    if not math.isfinite(natural_advance) or natural_advance < 0.0:
        raise ValueError("font returned an invalid authoritative source advance")
    source_width_basis = natural_advance
    if source_width_basis <= 0.0:
        if _visible_ink_expected(text):
            source_width_basis = _visible_font_ink_width(font, text, height=1.0)
            if source_width_basis <= 0.0:
                raise ValueError("visible zero-advance source text has no font contour")
        else:
            source_width_basis = target_advance

    baseline = (
        quad[1][0] - quad[0][0],
        quad[1][1] - quad[0][1],
    )
    vertical_axis = (
        quad[3][0] - quad[0][0],
        quad[3][1] - quad[0][1],
    )
    transform = Matrix44.ucs(
        ux=(baseline[0] / source_width_basis, baseline[1] / source_width_basis, 0.0),
        uy=(-vertical_axis[0] * vertical, -vertical_axis[1] * vertical, 0.0),
        uz=(0.0, 0.0, 1.0),
        origin=(target_origin[0], target_origin[1], 0.0),
    )
    return transform, target_advance, target_advance / source_width_basis


def _item_authoritative_transform(
    text_item: NormalizedText,
    face: FontFace,
    *,
    representation: str,
) -> Optional[Tuple[Matrix44, float, float]]:
    raw_quad = getattr(text_item, "target_quad_model", None)
    if raw_quad is None:
        return None
    quad = _validated_quad(raw_quad, field_name="target_quad_model")
    insertion = _finite_point(getattr(text_item, "insertion", None))
    if insertion is None:
        raise _RepresentationImpossible("source insertion is missing or non-finite")
    target_advance = _positive_finite(getattr(text_item, "advance_width", None))
    target_height = _positive_finite(getattr(text_item, "glyph_height", None))
    quad_advance, quad_height = _quad_dimensions(quad)
    if target_advance is None:
        target_advance = quad_advance
    if target_height is None:
        target_height = quad_height
    if representation == "glyphs":
        quad = tuple(
            (point[0] - insertion[0], point[1] - insertion[1]) for point in quad
        )
        target_origin = (0.0, 0.0)
    else:
        target_origin = insertion
    return _authoritative_quad_transform(
        str(getattr(text_item, "text", "") or ""),
        face,
        target_quad=quad,
        target_origin=target_origin,
        target_advance=target_advance,
        target_height=target_height,
    )


def _source_bound_string_path_expectation(
    text: str,
    face: FontFace,
    *,
    height: float,
    target_advance: Optional[float],
    rotation_degrees: float,
    translation: Tuple[float, float],
    source_transform: Optional[Matrix44] = None,
    delivered_advance_override: Optional[float] = None,
    width_scale_override: Optional[float] = None,
) -> Tuple[
    List[Any],
    Optional[Tuple[float, float, float, float]],
    float,
    float,
]:
    """Generate an independent source-derived ink bound before actual paths."""

    font = text2path.get_font(face)
    natural_advance = float(font.text_width(text)) * height
    if not math.isfinite(natural_advance) or natural_advance < 0.0:
        raise ValueError("font returned an invalid expected source advance")
    if target_advance is None:
        width_scale = 1.0
        delivered_advance = natural_advance
    elif natural_advance > 0.0:
        width_scale = target_advance / natural_advance
        delivered_advance = natural_advance * width_scale
    elif _visible_ink_expected(text):
        ink_width = _visible_font_ink_width(font, text, height=height)
        if ink_width <= 0.0:
            raise ValueError("visible zero-advance source character has no font contour")
        width_scale = target_advance / ink_width
        delivered_advance = target_advance
    else:
        width_scale = 1.0
        delivered_advance = 0.0
    if not math.isfinite(width_scale) or width_scale <= 0.0:
        raise ValueError("expected font baseline scale is invalid")
    transform = source_transform or (
        Matrix44.scale(width_scale, 1.0, 1.0)
        * Matrix44.z_rotate(math.radians(rotation_degrees))
        * Matrix44.translate(translation[0], translation[1], 0.0)
    )
    render_height = 1.0 if source_transform is not None else height
    expected_paths = _independent_font_paths(
        text,
        face,
        height=render_height,
        transform=transform,
    )
    return (
        expected_paths,
        _path_bbox_tuple(expected_paths),
        delivered_advance_override
        if delivered_advance_override is not None
        else delivered_advance,
        width_scale_override if width_scale_override is not None else width_scale,
    )


def _outline_expectation(
    text_item: NormalizedText,
    *,
    representation: str,
    path_bbox: Optional[Tuple[float, float, float, float]],
    expected_paths: Sequence[Any],
    character_groups: Sequence[_OutlineCharacterGroup] = (),
) -> _OutlineExpectation:
    if path_bbox is None:
        raise _RepresentationImpossible("source paths have no finite visible-ink bounds")
    envelope, envelope_source = _outline_source_envelope(
        text_item,
        representation=representation,
    )
    if character_groups:
        # Each positioned character is flattened through its own authoritative
        # affine and source scale.  Re-flattening the aggregate at the span scale
        # changes vertex and triangulation sampling, so preserve the immutable
        # per-character expectations in the same ownership order as the output.
        flattening_error = max(
            (group.flattening_error for group in character_groups),
            default=0.0,
        )
        geometry_tolerance = max(
            (group.geometry_tolerance for group in character_groups),
            default=0.0,
        )
        path_geometry = tuple(
            path
            for group in character_groups
            for path in group.expected_path_geometry
        )
        fill_geometry = tuple(
            triangle
            for group in character_groups
            for triangle in group.expected_fill_geometry
        )
    else:
        flattening_error = _flattening_error(expected_paths)
        geometry_tolerance = _geometry_comparison_tolerance(
            path_bbox,
            flattening_error=flattening_error,
        )
        path_geometry = _path_geometry_expectations(
            expected_paths,
            flattening_error=flattening_error,
        )
        fill_geometry = _triangulated_geometry(
            expected_paths,
            flattening_error=flattening_error,
        )
    source_geometry_verified = _path_geometry_within_envelope(
        path_geometry,
        envelope,
        tolerance=geometry_tolerance,
    )
    return _OutlineExpectation(
        path_bbox=path_bbox,
        source_envelope=envelope,
        source_envelope_source=envelope_source,
        path_geometry=path_geometry,
        fill_geometry=fill_geometry,
        flattening_error=flattening_error,
        geometry_tolerance=geometry_tolerance,
        source_geometry_verified=source_geometry_verified,
        character_groups=tuple(character_groups),
    )


def _source_identity_sha256(source_id: str) -> str:
    return hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()


def _glyph_block_identity_base(source_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", str(source_id)).strip("_") or "ITEM"
    digest = _source_identity_sha256(source_id)[:16]
    return f"BCS_GLYPH_{slug[:180]}_{digest}"


def _glyph_block_name_binds_source(block_name: str, source_id: str) -> bool:
    base = _glyph_block_identity_base(source_id)
    if block_name == base:
        return True
    if not block_name.startswith(f"{base}_"):
        return False
    suffix = block_name[len(base) + 1 :]
    return bool(suffix.isdigit() and int(suffix) >= 2 and str(int(suffix)) == suffix)


def _block_reference_handles(doc: Any, block_name: str) -> List[str]:
    references: List[str] = []
    expected = str(block_name).casefold()
    for layout in doc.blocks:
        for entity in layout:
            if (
                entity.dxftype() == "INSERT"
                and str(entity.dxf.name or "").casefold() == expected
            ):
                references.append(_handle(entity))
    return references


def _outline_reference_handles(doc: Any, entities: Sequence[Any]) -> List[str]:
    """Return the exact non-owned layer dependency closure actually traversed."""

    handles: List[str] = []
    for entity in entities:
        layer_name = str(entity.dxf.get("layer", "0") or "0")
        try:
            layer = doc.layers.get(layer_name)
        except Exception as exc:
            raise ValueError(f"outline dependency layer is missing: {layer_name!r}") from exc
        handle = _handle(layer)
        if not handle:
            raise ValueError(f"outline dependency layer has no handle: {layer_name!r}")
        if handle not in handles:
            handles.append(handle)
    return handles


def _outline_entities_visible_and_opaque(
    doc: Any,
    entities: Sequence[Any],
    *,
    expected_owner: Optional[str] = None,
) -> bool:
    """Verify direct and inherited visibility for owned outline entities."""

    if not entities:
        return False
    for entity in entities:
        raw_invisible = entity.dxf.get("invisible", 0)
        if (
            isinstance(raw_invisible, bool)
            or not isinstance(raw_invisible, int)
            or raw_invisible != 0
        ):
            return False
        try:
            entity_transparency = float(entity.transparency)
            layer = doc.layers.get(str(entity.dxf.get("layer", "0") or "0"))
            layer_transparency = float(layer.transparency)
        except (TypeError, ValueError, AttributeError, KeyError):
            return False
        if (
            not math.isfinite(entity_transparency)
            or not math.isclose(
                entity_transparency,
                0.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not layer.is_on()
            or layer.is_frozen()
            or not math.isfinite(layer_transparency)
            or not math.isclose(
                layer_transparency,
                0.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or (
                expected_owner is not None
                and str(entity.dxf.owner or "") != str(expected_owner)
            )
        ):
            return False
    return True


def _unique_block_name(doc: ezdxf.document.Drawing, source_id: str) -> str:
    base = _glyph_block_identity_base(source_id)
    candidate = base
    suffix = 1
    while candidate in doc.blocks:
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate


def _block_structure_handles(
    block: Any,
    *,
    include_block_record: bool = True,
) -> List[str]:
    values = [
        getattr(block, "block_record", None),
        getattr(block, "block", None),
        getattr(block, "endblk", None),
    ]
    if not include_block_record:
        values = values[1:]
    return [
        handle
        for handle in (_handle(value) for value in values)
        if handle
    ]


def _verify_outline_character_ownership(
    expectation: _OutlineExpectation,
    outlines: Sequence[Any],
    fills: Sequence[Any],
    *,
    is_r12: bool,
) -> Tuple[bool, List[Dict[str, Any]]]:
    if not expectation.character_groups:
        return True, []
    ownership: List[Dict[str, Any]] = []
    owned_handles: List[str] = []
    for group in expectation.character_groups:
        outline_handles = [_handle(entity) for entity in group.outlines]
        fill_handles = [_handle(entity) for entity in group.fills]
        entity_handles = outline_handles + fill_handles
        owned_handles.extend(entity_handles)
        actual_bbox = _bbox_tuple(group.outlines)
        if group.visible_ink_expected:
            outline_geometry_verified = _outline_entities_match(
                group.expected_path_geometry,
                group.outlines,
                tolerance=group.geometry_tolerance,
            )
            fill_geometry_verified = _fill_entities_match(
                group.expected_fill_geometry,
                group.fills,
                tolerance=group.geometry_tolerance,
            )
            group_verified = bool(
                outline_handles
                and fill_handles
                and all(entity_handles)
                and _solid_fill_verified(group.fills, is_r12=is_r12)
                and _bbox_matches(
                    group.expected_bbox,
                    actual_bbox,
                    flattening_error=group.flattening_error,
                )
                and outline_geometry_verified
                and fill_geometry_verified
            )
            zero_ink_verified = False
        else:
            outline_geometry_verified = not group.expected_path_geometry
            fill_geometry_verified = not group.expected_fill_geometry
            group_verified = bool(
                not group.outlines
                and not group.fills
                and group.expected_bbox is None
                and actual_bbox is None
            )
            zero_ink_verified = group_verified
        ownership.append(
            {
                "index": group.index,
                "text": group.text,
                "glyph_id": group.glyph_id,
                "target_origin": list(group.target_origin),
                "target_quad": [list(point) for point in group.target_quad],
                "advance_width": group.advance_width,
                "glyph_height": group.glyph_height,
                "rotation_degrees": group.rotation_degrees,
                "visible_ink_expected": group.visible_ink_expected,
                "zero_ink_verified": zero_ink_verified,
                "entity_handles": entity_handles,
                "outline_entity_handles": outline_handles,
                "fill_entity_handles": fill_handles,
                "expected_outline_bbox": (
                    list(group.expected_bbox) if group.expected_bbox else None
                ),
                "actual_outline_bbox": list(actual_bbox) if actual_bbox else None,
                "outline_topology_control_geometry_verified": outline_geometry_verified,
                "solid_fill_geometry_verified": fill_geometry_verified,
                "group_verified": group_verified,
            }
        )
    all_child_handles = [_handle(entity) for entity in list(outlines) + list(fills)]
    ownership_is_exact = bool(
        len(owned_handles) == len(set(owned_handles))
        and set(owned_handles) == set(all_child_handles)
        and all(entry["group_verified"] for entry in ownership)
    )
    return ownership_is_exact, ownership


def _commit_outlines(
    attempt: TextDeliveryAttempt,
    outlines: List[Any],
    fills: List[Any],
    msp: Any,
    *,
    representation: str,
    insertion: Tuple[float, float],
    expectation: _OutlineExpectation,
    is_r12: bool,
) -> None:
    doc = msp.doc
    if not outlines:
        raise ValueError("outline strategy returned zero entities")
    fill_verified = _solid_fill_verified(fills, is_r12=is_r12)
    outline_geometry_verified = _outline_entities_match(
        expectation.path_geometry,
        outlines,
        tolerance=expectation.geometry_tolerance,
    )
    fill_geometry_verified = _fill_entities_match(
        expectation.fill_geometry,
        fills,
        tolerance=expectation.geometry_tolerance,
    )
    attempt.evidence.update(
        {
            "solid_fill_entity_type": "SOLID",
            "solid_fill_entity_count": len(fills),
            "solid_fill_verified": fill_verified,
            "source_outline_envelope": [
                list(point) for point in expectation.source_envelope
            ],
            "source_outline_envelope_source": expectation.source_envelope_source,
            "pre_entity_path_expectation": list(expectation.path_bbox),
            "source_outline_geometry_verified": expectation.source_geometry_verified,
            "outline_topology_control_geometry_verified": outline_geometry_verified,
            "solid_fill_geometry_verified": fill_geometry_verified,
            "outline_flattening_error": expectation.flattening_error,
            "outline_geometry_tolerance": expectation.geometry_tolerance,
        }
    )
    if not fill_verified:
        raise ValueError("outline strategy did not create verified solid glyph fill")

    expected_layer_name = str(outlines[0].dxf.layer or "0")
    if not doc.layers.has_entry(expected_layer_name):
        doc.layers.add(expected_layer_name)
    layer_record = doc.layers.get(expected_layer_name)
    layer_handle = _handle(layer_record)

    if representation == "geometry":
        for entity in outlines + fills:
            msp.add_entity(entity)
            attempt.created_entity_handles.append(_handle(entity))
        geometry_entities = [*outlines, *fills]
        attempt.entity_handles = [_handle(entity) for entity in geometry_entities]
        attempt.referenced_entity_handles = _outline_reference_handles(
            doc,
            geometry_entities,
        )
        actual_bbox = _bbox_tuple(outlines)
        modelspace_ownership_verified = all(
            str(entity.dxf.owner or "") == str(msp.layout_key)
            for entity in geometry_entities
        )
        owned_outline_visibility_verified = _outline_entities_visible_and_opaque(
            doc,
            geometry_entities,
            expected_owner=str(msp.layout_key),
        )
        attempt.type_verified = (
            bool(attempt.entity_handles)
            and all(
                entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
                for entity in outlines
            )
            and _solid_fill_verified(fills, is_r12=is_r12)
        )
        ownership_verified, ownership = _verify_outline_character_ownership(
            expectation,
            outlines,
            fills,
            is_r12=is_r12,
        )
        attempt.visual_verified = bool(
            expectation.source_geometry_verified
            and outline_geometry_verified
            and fill_geometry_verified
            and _bbox_matches(
                expectation.path_bbox,
                actual_bbox,
                flattening_error=expectation.flattening_error,
            )
            and ownership_verified
            and modelspace_ownership_verified
            and owned_outline_visibility_verified
        )
        attempt.evidence.update(
            {
                "expected_outline_bbox": list(expectation.path_bbox),
                "actual_outline_bbox": list(actual_bbox) if actual_bbox else None,
                "outline_character_ownership": ownership,
                "outline_character_ownership_verified": ownership_verified,
                "expected_geometry_in_modelspace": True,
                "geometry_modelspace_ownership_verified": (
                    modelspace_ownership_verified
                ),
                "owned_outline_visibility_verified": (
                    owned_outline_visibility_verified
                ),
            }
        )
        _record_outline_geometry_evidence(
            attempt,
            expectation,
            [*outlines, *fills],
        )
        return

    block_name = _unique_block_name(doc, attempt.source_id)
    block = doc.blocks.new(name=block_name)
    attempt.owned_block_names.append(block_name)
    # R12 has no serialized BLOCK_RECORD table. ezdxf creates a transient
    # record in memory and assigns a different synthetic handle after reload,
    # so it cannot be part of durable delivery identity for an R12 artifact.
    block_structure_handles = _block_structure_handles(
        block,
        include_block_record=not is_r12,
    )
    attempt.created_entity_handles.extend(block_structure_handles)
    for entity in outlines + fills:
        block.add_entity(entity)
        attempt.created_entity_handles.append(_handle(entity))
    block_attribs: Dict[str, Any] = {
        "layer": expected_layer_name,
    }
    # LibreCAD resolves a block reference's display color before child entity
    # true-color in several export/render paths.  Carry the exact source color
    # on both the glyph children and their parent INSERT so a blue source glyph
    # cannot reopen or print as black.
    if outlines[0].dxf.hasattr("true_color"):
        block_attribs["true_color"] = int(outlines[0].dxf.true_color)
    if outlines[0].dxf.hasattr("color"):
        block_attribs["color"] = int(outlines[0].dxf.color)
    block_ref = msp.add_blockref(
        block_name,
        insertion,
        dxfattribs=block_attribs,
    )
    attempt.created_entity_handles.append(_handle(block_ref))
    attempt.entity_handles = [_handle(block_ref)]
    attempt.support_entity_handles = block_structure_handles + [
        _handle(entity) for entity in outlines + fills
    ]
    attempt.referenced_entity_handles = _outline_reference_handles(
        doc,
        [block_ref, *list(block)],
    )
    actual_bbox = _bbox_tuple(outlines)
    expected_insert = (float(insertion[0]), float(insertion[1]), 0.0)
    expected_rotation = 0.0
    expected_xscale = 1.0
    expected_yscale = 1.0
    expected_zscale = 1.0
    expected_row_count = 1
    expected_column_count = 1
    expected_row_spacing = 0.0
    expected_column_spacing = 0.0
    expected_extrusion = (0.0, 0.0, 1.0)
    expected_base_point = (0.0, 0.0, 0.0)
    raw_insert = tuple(block_ref.dxf.insert)
    raw_rotation = block_ref.dxf.get("rotation", 0.0)
    raw_xscale = block_ref.dxf.get("xscale", 1.0)
    raw_yscale = block_ref.dxf.get("yscale", 1.0)
    raw_zscale = block_ref.dxf.get("zscale", 1.0)
    raw_row_count = block_ref.dxf.get("row_count", 1)
    raw_column_count = block_ref.dxf.get("column_count", 1)
    raw_row_spacing = block_ref.dxf.get("row_spacing", 0.0)
    raw_column_spacing = block_ref.dxf.get("column_spacing", 0.0)
    raw_extrusion = tuple(block_ref.dxf.get("extrusion", expected_extrusion))
    raw_base_point = tuple(block.block.dxf.base_point)
    raw_scalar_values = (
        raw_rotation,
        raw_xscale,
        raw_yscale,
        raw_zscale,
        raw_row_spacing,
        raw_column_spacing,
    )
    if (
        len(raw_insert) != 3
        or len(raw_extrusion) != 3
        or len(raw_base_point) != 3
        or not all(
            _is_strict_finite_number(value)
            for value in (
                *raw_insert,
                *raw_scalar_values,
                *raw_extrusion,
                *raw_base_point,
            )
        )
        or isinstance(raw_row_count, bool)
        or not isinstance(raw_row_count, int)
        or raw_row_count < 1
        or isinstance(raw_column_count, bool)
        or not isinstance(raw_column_count, int)
        or raw_column_count < 1
    ):
        raise ValueError("glyph INSERT has invalid typed transform state")
    actual_insert = tuple(float(value) for value in raw_insert)
    actual_rotation = float(raw_rotation)
    actual_xscale = float(raw_xscale)
    actual_yscale = float(raw_yscale)
    actual_zscale = float(raw_zscale)
    actual_row_count = raw_row_count
    actual_column_count = raw_column_count
    actual_row_spacing = float(raw_row_spacing)
    actual_column_spacing = float(raw_column_spacing)
    actual_extrusion = tuple(float(value) for value in raw_extrusion)
    actual_base_point = tuple(float(value) for value in raw_base_point)
    insert_verified = all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
        for left, right in zip(actual_insert, expected_insert, strict=True)
    )
    transform_values = (
        *actual_insert,
        actual_rotation,
        actual_xscale,
        actual_yscale,
        actual_zscale,
        actual_row_spacing,
        actual_column_spacing,
        *actual_extrusion,
        *actual_base_point,
    )
    insert_transform_verified = bool(
        len(actual_insert) == 3
        and len(actual_extrusion) == 3
        and len(actual_base_point) == 3
        and all(math.isfinite(value) for value in transform_values)
        and insert_verified
        and math.isclose(
            actual_rotation,
            expected_rotation,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            actual_xscale,
            expected_xscale,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            actual_yscale,
            expected_yscale,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and math.isclose(
            actual_zscale,
            expected_zscale,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and actual_row_count == expected_row_count
        and actual_column_count == expected_column_count
        and (
            expected_row_count <= 1
            or math.isclose(
                actual_row_spacing,
                expected_row_spacing,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        and (
            expected_column_count <= 1
            or math.isclose(
                actual_column_spacing,
                expected_column_spacing,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        )
        and all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
            for left, right in zip(
                actual_extrusion,
                expected_extrusion,
                strict=True,
            )
        )
        and all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
            for left, right in zip(
                actual_base_point,
                expected_base_point,
                strict=True,
            )
        )
    )
    expected_aci = int(block_attribs.get("color", 256))
    raw_actual_aci = block_ref.dxf.get("color", 256)
    expected_true_color = block_attribs.get("true_color")
    actual_true_color = (
        block_ref.dxf.true_color
        if block_ref.dxf.hasattr("true_color")
        else None
    )
    insert_color_verified = bool(
        not isinstance(raw_actual_aci, bool)
        and isinstance(raw_actual_aci, int)
        and raw_actual_aci == expected_aci
        and actual_true_color == expected_true_color
    )
    source_identity_sha256 = _source_identity_sha256(attempt.source_id)
    source_identity_physical_verified = _glyph_block_name_binds_source(
        block_name,
        attempt.source_id,
    )
    actual_layer_name = str(block_ref.dxf.layer or "")
    actual_layer_on = bool(layer_record.is_on())
    actual_layer_frozen = bool(layer_record.is_frozen())
    actual_layer_transparency = float(layer_record.transparency)
    insert_layer_verified = bool(
        actual_layer_name == expected_layer_name
        and actual_layer_on
        and not actual_layer_frozen
        and math.isfinite(actual_layer_transparency)
        and math.isclose(
            actual_layer_transparency,
            0.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
    raw_invisible = block_ref.dxf.get("invisible", 0)
    invisible_state_verified = bool(
        not isinstance(raw_invisible, bool)
        and isinstance(raw_invisible, int)
        and raw_invisible == 0
    )
    actual_transparency = float(block_ref.transparency)
    transparency_verified = bool(
        math.isfinite(actual_transparency)
        and math.isclose(actual_transparency, 0.0, rel_tol=0.0, abs_tol=1e-12)
    )
    modelspace_verified = str(block_ref.dxf.owner or "") == str(msp.layout_key)
    visible_attribute_count = len(block_ref.attribs)
    attached_content_verified = visible_attribute_count == 0
    actual_reference_handles = _block_reference_handles(doc, block_name)
    block_reference_ownership_verified = actual_reference_handles == [
        _handle(block_ref)
    ]
    owned_outline_visibility_verified = _outline_entities_visible_and_opaque(
        doc,
        list(block),
    )
    attempt.type_verified = (
        block_ref.dxftype() == "INSERT"
        and bool(attempt.support_entity_handles)
        and all(
            entity.dxftype() in {"LWPOLYLINE", "POLYLINE", "SOLID"}
            for entity in block
        )
        and _solid_fill_verified(fills, is_r12=is_r12)
    )
    ownership_verified, ownership = _verify_outline_character_ownership(
        expectation,
        outlines,
        fills,
        is_r12=is_r12,
    )
    attempt.visual_verified = bool(
        insert_verified
        and insert_transform_verified
        and insert_color_verified
        and source_identity_physical_verified
        and insert_layer_verified
        and invisible_state_verified
        and transparency_verified
        and modelspace_verified
        and attached_content_verified
        and block_reference_ownership_verified
        and owned_outline_visibility_verified
        and expectation.source_geometry_verified
        and outline_geometry_verified
        and fill_geometry_verified
        and _bbox_matches(
            expectation.path_bbox,
            actual_bbox,
            flattening_error=expectation.flattening_error,
        )
        and ownership_verified
    )
    attempt.evidence.update(
        {
            "block_name": block_name,
            "source_identity_sha256": source_identity_sha256,
            "source_identity_physical_verified": source_identity_physical_verified,
            "nonserializable_support_roles": ["BLOCK_RECORD"] if is_r12 else [],
            "expected_outline_bbox": list(expectation.path_bbox),
            "actual_outline_bbox": list(actual_bbox) if actual_bbox else None,
            "expected_block_insert": list(expected_insert),
            "actual_block_insert": list(actual_insert),
            "block_insert_verified": insert_verified,
            "expected_block_rotation": expected_rotation,
            "actual_block_rotation": actual_rotation,
            "expected_block_xscale": expected_xscale,
            "actual_block_xscale": actual_xscale,
            "expected_block_yscale": expected_yscale,
            "actual_block_yscale": actual_yscale,
            "expected_block_zscale": expected_zscale,
            "actual_block_zscale": actual_zscale,
            "expected_block_row_count": expected_row_count,
            "actual_block_row_count": actual_row_count,
            "expected_block_column_count": expected_column_count,
            "actual_block_column_count": actual_column_count,
            "expected_block_row_spacing": expected_row_spacing,
            "actual_block_row_spacing": actual_row_spacing,
            "expected_block_column_spacing": expected_column_spacing,
            "actual_block_column_spacing": actual_column_spacing,
            "expected_block_extrusion": list(expected_extrusion),
            "actual_block_extrusion": list(actual_extrusion),
            "expected_block_base_point": list(expected_base_point),
            "actual_block_base_point": list(actual_base_point),
            "block_insert_transform_verified": insert_transform_verified,
            "block_insert_color_verified": insert_color_verified,
            "block_insert_aci": expected_aci,
            "block_insert_true_color": expected_true_color,
            "expected_block_layer": expected_layer_name,
            "actual_block_layer": actual_layer_name,
            "expected_block_layer_handle": layer_handle,
            "expected_block_layer_on": True,
            "actual_block_layer_on": actual_layer_on,
            "expected_block_layer_frozen": False,
            "actual_block_layer_frozen": actual_layer_frozen,
            "expected_block_layer_transparency": 0.0,
            "actual_block_layer_transparency": actual_layer_transparency,
            "block_insert_layer_verified": insert_layer_verified,
            "expected_block_invisible": 0,
            "actual_block_invisible": raw_invisible,
            "block_insert_invisible_state_verified": invisible_state_verified,
            "expected_block_transparency": 0.0,
            "actual_block_transparency": actual_transparency,
            "block_insert_transparency_verified": transparency_verified,
            "expected_block_in_modelspace": True,
            "actual_block_in_modelspace": modelspace_verified,
            "block_insert_modelspace_verified": modelspace_verified,
            "expected_visible_attached_attribute_count": 0,
            "actual_visible_attached_attribute_count": visible_attribute_count,
            "block_insert_attached_content_verified": attached_content_verified,
            "expected_block_reference_count": 1,
            "actual_block_reference_handles": actual_reference_handles,
            "block_reference_ownership_verified": block_reference_ownership_verified,
            "owned_outline_visibility_verified": owned_outline_visibility_verified,
            "outline_character_ownership": ownership,
            "outline_character_ownership_verified": ownership_verified,
        }
    )
    _record_outline_geometry_evidence(
        attempt,
        expectation,
        [*outlines, *fills],
    )


def _rollback_outline_attempt(attempt: TextDeliveryAttempt, msp: Any) -> None:
    doc = msp.doc
    # Modelspace entities must be removed before their block definition.
    for handle in list(attempt.entity_handles):
        entity = doc.entitydb.get(handle)
        if entity is not None and getattr(entity, "is_alive", True):
            if _delete_entity(msp, entity):
                attempt.removed_entity_handles.append(handle)
    for block_name in reversed(attempt.owned_block_names):
        block = doc.blocks.get(block_name)
        child_handles = (
            _block_structure_handles(block) + [_handle(entity) for entity in block]
            if block is not None
            else []
        )
        if _delete_block(doc, block_name):
            attempt.removed_entity_handles.extend(
                handle
                for handle in child_handles
                if handle in attempt.created_entity_handles
                and handle not in attempt.removed_entity_handles
            )
    # Raw Geometry edges are final modelspace entities, not support entities.
    for handle in list(attempt.created_entity_handles):
        if handle in attempt.removed_entity_handles:
            continue
        entity = doc.entitydb.get(handle)
        if entity is not None and getattr(entity, "is_alive", True):
            if _delete_entity(msp, entity):
                attempt.removed_entity_handles.append(handle)
    attempt.entity_handles = []
    attempt.support_entity_handles = []


def _attempt_outline_entity(
    text_item: NormalizedText,
    msp: Any,
    layer_name: str,
    *,
    representation: str,
    requested: str,
    source_id: str,
    is_r12: bool,
    config: ImportConfig,
) -> TextDeliveryAttempt:
    attempt = TextDeliveryAttempt(
        source_id=source_id,
        requested_representation=requested,
        attempted_representation=representation,
        strategy="entity_text2path",
    )
    doc = msp.doc
    source = None
    style_name = ""
    style_handle = ""
    style_created = False
    try:
        source_text = str(getattr(text_item, "text", "") or "")
        if source_text and not _visible_ink_expected(source_text):
            attempt.evidence.update(
                {
                    "source_content_whitespace_only": True,
                    "visible_ink_expected": False,
                    "zero_outline_result_verified": True,
                    "item_specific_creation_attempted": True,
                }
            )
            raise _RepresentationImpossible(
                "zero-ink source item has no truthful outline geometry"
            )
        requires_individual = bool(
            getattr(text_item, "requires_individual_positioning", False)
        )
        attempt.evidence["requires_individual_positioning"] = requires_individual
        if requires_individual:
            positioned_layout = _validate_character_layout(text_item)
            attempt.evidence.update(
                {
                    "source_char_layout_verified": True,
                    "source_char_layout_count": len(positioned_layout),
                }
            )
            raise _RepresentationImpossible(
                "entity text2path cannot retain independent source character placement"
            )
        source_em_height = _positive_finite(getattr(text_item, "font_size", None))
        if source_em_height is None:
            raise _RepresentationImpossible(
                "source nominal text height is missing or invalid for outline delivery"
            )
        insertion = tuple(float(value) for value in text_item.insertion[:2])
        source_insert = (0.0, 0.0) if representation == "glyphs" else insertion
        font_resolution = _require_exact_item_font(text_item, config, attempt)
        height, cap_height_ratio = _delivery_cap_height(
            source_em_height, font_resolution
        )
        face = FontFace(filename=font_resolution.filename)
        source_font = text2path.get_font(face)
        source_advance = float(source_font.text_width(source_text)) * height
        if (
            math.isfinite(source_advance)
            and source_advance <= 0.0
            and _visible_ink_expected(source_text)
            and _visible_font_ink_width(source_font, source_text, height=height) > 0.0
        ):
            attempt.evidence.update(
                {
                    "visible_zero_advance_contour": True,
                    "direct_source_path_required": True,
                }
            )
            raise _RepresentationImpossible(
                "DXF TEXT cannot retain a visible zero-advance contour; "
                "direct source-font paths are required"
            )
        style_name, style_handle, style_created = _ensure_text_style(
            doc, font_resolution
        )
        if style_created:
            attempt.created_entity_handles.append(style_handle)
        else:
            attempt.referenced_entity_handles.append(style_handle)
        attribs = _base_attributes(
            text_item,
            layer_name=layer_name,
            height=height,
            insert=source_insert,
            is_r12=is_r12,
            style_name=style_name,
        )
        source = msp.add_text(str(text_item.text), dxfattribs=attribs)
        source_handle = _handle(source)
        attempt.created_entity_handles.append(source_handle)
        target_width, width_source = _target_advance_width(text_item)
        measured_width = _fit_text_advance(source, target_width)
        verification_item = (
            replace(text_item, insertion=source_insert)
            if representation == "glyphs"
            else text_item
        )
        source_type_ok, source_visual_ok, source_evidence = _verify_label(
            source,
            verification_item,
            height=height,
            target_width=target_width,
            measured_width=measured_width,
            width_source=width_source,
        )
        attempt.evidence.update(
            {
                "expected_advance_width": target_width,
                "actual_advance_width": measured_width,
                "width_source": width_source,
                "source_text_type_verified": source_type_ok,
                "source_text_parameters_verified": source_visual_ok,
                "source_text_evidence": source_evidence,
            }
        )
        source_evidence.update(
            {
                "source_font_em_height": source_em_height,
                "source_cap_height_ratio": cap_height_ratio,
            }
        )
        if not source_type_ok or not source_visual_ok:
            raise ValueError(
                "outline source text failed content, anchor, size, rotation, or width verification"
            )
        rotation_degrees = _finite_float(getattr(text_item, "rotation", 0.0) or 0.0)
        if rotation_degrees is None:
            raise _RepresentationImpossible("source rotation is missing or non-finite")
        source_transform = _item_authoritative_transform(
            text_item,
            face,
            representation=representation,
        )
        transform_matrix = source_transform[0] if source_transform else None
        delivered_override = source_transform[1] if source_transform else None
        scale_override = source_transform[2] if source_transform else None
        expected_paths, expected_path_bbox, expected_advance, expected_scale = (
            _source_bound_string_path_expectation(
                str(text_item.text),
                face,
                height=height,
                target_advance=target_width,
                rotation_degrees=rotation_degrees,
                translation=source_insert,
                source_transform=transform_matrix,
                delivered_advance_override=delivered_override,
                width_scale_override=scale_override,
            )
        )
        paths = list(text2path.make_paths_from_entity(source))
        (
            pre_entity_paths_verified,
            independent_path_bbox,
            actual_path_bbox,
            pre_entity_flattening_error,
            pre_entity_geometry_tolerance,
        ) = _pre_entity_paths_verified(expected_paths, paths)
        if expected_path_bbox != independent_path_bbox:
            raise ValueError("independent source path expectation mutated")
        if expected_path_bbox is None or actual_path_bbox is None:
            if str(text_item.text) and not _visible_ink_expected(str(text_item.text)):
                attempt.evidence.update(
                    {
                        "source_content_whitespace_only": True,
                        "visible_ink_expected": False,
                        "zero_outline_result_verified": True,
                        "item_specific_creation_attempted": True,
                    }
                )
                raise _RepresentationImpossible(
                    "zero-ink source item has no outline ink"
                )
            raise ValueError("visible source text produced no finite outline paths")
        if not pre_entity_paths_verified:
            raise ValueError("entity text2path output is not bound to source geometry")
        attempt.evidence.update(
            {
                "source_bound_expected_advance": expected_advance,
                "source_bound_expected_scale": expected_scale,
                "source_bound_expected_path_bbox": list(expected_path_bbox),
                "pre_entity_actual_path_bbox": list(actual_path_bbox),
                "pre_entity_path_topology_control_geometry_verified": True,
                "pre_entity_flattening_error": pre_entity_flattening_error,
                "pre_entity_geometry_tolerance": pre_entity_geometry_tolerance,
            }
        )
        expectation = _outline_expectation(
            text_item,
            representation=representation,
            path_bbox=expected_path_bbox,
            expected_paths=expected_paths,
        )
        if not expectation.source_geometry_verified:
            raise ValueError("source outline paths fall outside the authoritative envelope")
        outlines = _to_outline_entities(
            paths, is_r12=is_r12, attribs=_outline_attributes(attribs)
        )
        fills = _to_solid_fill_entities(
            paths,
            is_r12=is_r12,
            attribs=_outline_attributes(attribs),
        )
        if _delete_entity(msp, source):
            attempt.removed_entity_handles.append(source_handle)
        source = None
        if style_created:
            _delete_owned_style(doc, style_name, style_handle, attempt)
            style_created = False
        _commit_outlines(
            attempt,
            outlines,
            fills,
            msp,
            representation=representation,
            insertion=insertion,
            expectation=expectation,
            is_r12=is_r12,
        )
        if not attempt.type_verified or not attempt.visual_verified:
            raise ValueError("outline delivery failed type or visual verification")
        attempt.outcome = "verified"
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        if not attempt.cleanup_verified:
            raise ValueError("outline ownership verification failed")
        return attempt
    except Exception as exc:
        attempt.reason = f"{type(exc).__name__}: {exc}"
        if source is not None:
            handle = _handle(source)
            if _delete_entity(msp, source):
                attempt.removed_entity_handles.append(handle)
        if style_created:
            _delete_owned_style(doc, style_name, style_handle, attempt)
        _rollback_outline_attempt(attempt, msp)
        attempt.outcome = (
            "impossible" if isinstance(exc, _RepresentationImpossible) else "failed"
        )
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        return attempt


def _attempt_outline_string(
    text_item: NormalizedText,
    msp: Any,
    layer_name: str,
    *,
    representation: str,
    requested: str,
    source_id: str,
    is_r12: bool,
    config: ImportConfig,
) -> TextDeliveryAttempt:
    attempt = TextDeliveryAttempt(
        source_id=source_id,
        requested_representation=requested,
        attempted_representation=representation,
        strategy="string_text2path",
    )
    doc = msp.doc
    try:
        source_text = str(getattr(text_item, "text", "") or "")
        if source_text and not _visible_ink_expected(source_text):
            attempt.evidence.update(
                {
                    "source_content_whitespace_only": True,
                    "visible_ink_expected": False,
                    "zero_outline_result_verified": True,
                    "item_specific_creation_attempted": True,
                }
            )
            raise _RepresentationImpossible(
                "zero-ink source item has no truthful outline geometry"
            )
        requires_individual = bool(
            getattr(text_item, "requires_individual_positioning", False)
        )
        attempt.evidence["requires_individual_positioning"] = requires_individual
        source_em_height = _positive_finite(getattr(text_item, "font_size", None))
        if source_em_height is None:
            raise _RepresentationImpossible(
                "source nominal text height is missing or invalid for outline delivery"
            )
        insertion_point = _finite_point(getattr(text_item, "insertion", None))
        rotation_degrees = _finite_float(
            getattr(text_item, "rotation", 0.0) or 0.0
        )
        if insertion_point is None or rotation_degrees is None:
            raise _RepresentationImpossible(
                "source insertion or rotation is missing or non-finite"
            )
        insertion = insertion_point
        target_width, width_source = _target_advance_width(text_item)
        font_resolution = _require_exact_item_font(text_item, config, attempt)
        height, cap_height_ratio = _delivery_cap_height(
            source_em_height, font_resolution
        )
        face = FontFace(filename=font_resolution.filename)
        attribs = _base_attributes(
            text_item,
            layer_name=layer_name,
            height=height,
            insert=(0.0, 0.0),
            is_r12=is_r12,
            style_name="Standard",
        )
        outline_attribs = _outline_attributes(attribs)
        character_groups: List[_OutlineCharacterGroup] = []
        delivered_advance: Optional[float] = None
        baseline_scale: Optional[float] = None
        if requires_individual:
            positioned_layout = _validate_character_layout(text_item)
            attempt.evidence.update(
                {
                    "source_char_layout_verified": True,
                    "source_char_layout_count": len(positioned_layout),
                }
            )
            outlines: List[Any] = []
            fills: List[Any] = []
            expected_paths: List[Any] = []
            character_metrics: List[Dict[str, Any]] = []
            for character in positioned_layout:
                if representation == "glyphs":
                    target_origin = (
                        character.target_origin[0] - insertion[0],
                        character.target_origin[1] - insertion[1],
                    )
                    target_quad = tuple(
                        (point[0] - insertion[0], point[1] - insertion[1])
                        for point in character.target_quad
                    )
                else:
                    target_origin = character.target_origin
                    target_quad = character.target_quad
                if character.visible_ink_expected:
                    (
                        character_transform,
                        authoritative_character_advance,
                        authoritative_character_scale,
                    ) = _authoritative_quad_transform(
                        character.text,
                        face,
                        target_quad=target_quad,
                        target_origin=target_origin,
                        target_advance=character.advance_width,
                        target_height=character.glyph_height,
                    )
                    (
                        expected_character_paths,
                        expected_character_bbox,
                        expected_character_advance,
                        expected_character_scale,
                    ) = _source_bound_string_path_expectation(
                        character.text,
                        face,
                        height=1.0,
                        target_advance=character.advance_width,
                        rotation_degrees=character.rotation_degrees,
                        translation=target_origin,
                        source_transform=character_transform,
                        delivered_advance_override=authoritative_character_advance,
                        width_scale_override=authoritative_character_scale,
                    )
                    (
                        character_paths,
                        character_advance,
                        character_scale,
                    ) = _make_scaled_string_paths(
                        character.text,
                        face,
                        height=1.0,
                        target_advance=character.advance_width,
                        rotation_degrees=character.rotation_degrees,
                        translation=target_origin,
                        source_transform=character_transform,
                    )
                    (
                        character_paths_verified,
                        independent_character_bbox,
                        character_bbox,
                        character_flattening_error,
                        character_geometry_tolerance,
                    ) = _pre_entity_paths_verified(
                        expected_character_paths,
                        character_paths,
                    )
                    if expected_character_bbox != independent_character_bbox:
                        raise ValueError(
                            f"source character {character.index} expectation mutated"
                        )
                else:
                    # A source space/control/zero-width format character owns
                    # placement and advance but deliberately owns no ink.  Do
                    # not let a font's .notdef glyph invent visible geometry.
                    character_paths = []
                    expected_character_paths = []
                    character_advance = character.advance_width
                    character_scale = None
                    expected_character_bbox = None
                    expected_character_advance = character.advance_width
                    expected_character_scale = None
                    character_bbox = None
                    character_paths_verified = True
                    character_flattening_error = 0.0
                    character_geometry_tolerance = 0.0
                if character.visible_ink_expected and character_bbox is None:
                    raise ValueError(
                        f"visible source character {character.index} produced no outline paths"
                    )
                if not character.visible_ink_expected and character_bbox is not None:
                    raise ValueError(
                        f"zero-ink source character {character.index} produced visible paths"
                    )
                if character.visible_ink_expected and (
                    expected_character_bbox is None
                    or not character_paths_verified
                    or not math.isclose(
                        character_advance,
                        expected_character_advance,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                    or not math.isclose(
                        character_scale,
                        expected_character_scale,
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                ):
                    raise ValueError(
                        f"source character {character.index} path transform is not source-bound"
                    )
                character_outlines = _to_outline_entities(
                    character_paths,
                    is_r12=is_r12,
                    attribs=outline_attribs,
                )
                character_fills = _to_solid_fill_entities(
                    character_paths,
                    is_r12=is_r12,
                    attribs=outline_attribs,
                )
                character_groups.append(
                    _OutlineCharacterGroup(
                        index=character.index,
                        text=character.text,
                        glyph_id=character.glyph_id,
                        target_origin=character.target_origin,
                        target_quad=character.target_quad,
                        advance_width=character.advance_width,
                        glyph_height=character.glyph_height,
                        rotation_degrees=character.rotation_degrees,
                        visible_ink_expected=character.visible_ink_expected,
                        expected_bbox=expected_character_bbox,
                        expected_path_geometry=_path_geometry_expectations(
                            expected_character_paths,
                            flattening_error=character_flattening_error,
                        ),
                        expected_fill_geometry=_triangulated_geometry(
                            expected_character_paths,
                            flattening_error=character_flattening_error,
                        ),
                        flattening_error=character_flattening_error,
                        geometry_tolerance=character_geometry_tolerance,
                        outlines=character_outlines,
                        fills=character_fills,
                    )
                )
                expected_paths.extend(expected_character_paths)
                outlines.extend(character_outlines)
                fills.extend(character_fills)
                character_metrics.append(
                    {
                        "index": character.index,
                        "expected_advance_width": character.advance_width,
                        "delivered_advance_width": character_advance,
                        "baseline_scale": character_scale,
                        "target_height": character.glyph_height,
                        "pre_entity_path_topology_control_geometry_verified": (
                            character_paths_verified
                        ),
                    }
                )
            expected_path_bbox = _bbox_union(
                [group.expected_bbox for group in character_groups]
            )
            if expected_path_bbox is None:
                attempt.evidence.update(
                    {
                        "source_content_whitespace_only": not _visible_ink_expected(
                            str(text_item.text)
                        ),
                        "visible_ink_expected": False,
                        "zero_outline_result_verified": True,
                        "item_specific_creation_attempted": True,
                        "positioned_character_metrics": character_metrics,
                    }
                )
                raise _RepresentationImpossible(
                    "individually positioned source item contains no visible outline ink"
                )
            expectation = _outline_expectation(
                text_item,
                representation=representation,
                path_bbox=expected_path_bbox,
                expected_paths=expected_paths,
                character_groups=character_groups,
            )
            if not expectation.source_geometry_verified:
                raise ValueError(
                    "positioned source paths fall outside the authoritative span envelope"
                )
            attempt.evidence["positioned_character_metrics"] = character_metrics
        else:
            translation = insertion if representation == "geometry" else (0.0, 0.0)
            source_transform = _item_authoritative_transform(
                text_item,
                face,
                representation=representation,
            )
            transform_matrix = source_transform[0] if source_transform else None
            delivered_override = source_transform[1] if source_transform else None
            scale_override = source_transform[2] if source_transform else None
            (
                expected_paths,
                expected_path_bbox,
                expected_delivered_advance,
                expected_baseline_scale,
            ) = _source_bound_string_path_expectation(
                str(text_item.text),
                face,
                height=height,
                target_advance=target_width,
                rotation_degrees=rotation_degrees,
                translation=translation,
                source_transform=transform_matrix,
                delivered_advance_override=delivered_override,
                width_scale_override=scale_override,
            )
            paths, delivered_advance, baseline_scale = _make_scaled_string_paths(
                str(text_item.text),
                face,
                height=1.0 if source_transform else height,
                target_advance=target_width,
                rotation_degrees=rotation_degrees,
                translation=translation,
                source_transform=transform_matrix,
            )
            (
                pre_entity_paths_verified,
                independent_path_bbox,
                actual_path_bbox,
                pre_entity_flattening_error,
                pre_entity_geometry_tolerance,
            ) = _pre_entity_paths_verified(expected_paths, paths)
            if expected_path_bbox != independent_path_bbox:
                raise ValueError("independent source path expectation mutated")
            if expected_path_bbox is None or actual_path_bbox is None:
                if str(text_item.text) and not _visible_ink_expected(
                    str(text_item.text)
                ):
                    attempt.evidence.update(
                        {
                            "source_content_whitespace_only": True,
                            "visible_ink_expected": False,
                            "zero_outline_result_verified": True,
                            "item_specific_creation_attempted": True,
                        }
                    )
                    raise _RepresentationImpossible(
                        "zero-ink source item has no outline ink"
                    )
                raise ValueError("visible source text produced no finite outline paths")
            if (
                not pre_entity_paths_verified
                or not math.isclose(
                    delivered_advance,
                    expected_delivered_advance,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
                or not math.isclose(
                    baseline_scale,
                    expected_baseline_scale,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
            ):
                raise ValueError("string text2path output is not bound to source geometry")
            attempt.evidence.update(
                {
                    "source_bound_expected_path_bbox": list(expected_path_bbox),
                    "pre_entity_actual_path_bbox": list(actual_path_bbox),
                    "pre_entity_path_topology_control_geometry_verified": True,
                    "pre_entity_flattening_error": pre_entity_flattening_error,
                    "pre_entity_geometry_tolerance": pre_entity_geometry_tolerance,
                }
            )
            expectation = _outline_expectation(
                text_item,
                representation=representation,
                path_bbox=expected_path_bbox,
                expected_paths=expected_paths,
            )
            if not expectation.source_geometry_verified:
                raise ValueError(
                    "source outline paths fall outside the authoritative envelope"
                )
            outlines = _to_outline_entities(
                paths,
                is_r12=is_r12,
                attribs=outline_attribs,
            )
            fills = _to_solid_fill_entities(
                paths,
                is_r12=is_r12,
                attribs=outline_attribs,
            )
        attempt.evidence.update(
            {
                "expected_advance_width": target_width,
                "delivered_advance_width": delivered_advance,
                "string_baseline_scale": baseline_scale,
                "width_source": width_source,
                "source_text_type_verified": True,
                "source_text_parameters_verified": True,
                "font_candidate": face.filename,
                "source_font_em_height": source_em_height,
                "source_cap_height_ratio": cap_height_ratio,
                "source_text_evidence": {
                    "entity_type": "SOURCE_BOUND_PATH_LAYOUT",
                    "content_verified": True,
                    "source_content": str(text_item.text),
                    "delivered_content": str(text_item.text),
                    "anchor_verified": True,
                    "height_verified": True,
                    "rotation_verified": True,
                    "width_verified": True,
                    "expected_insert": list(insertion),
                    "actual_insert": list(insertion),
                    "expected_height": height,
                    "actual_height": height,
                    "expected_rotation": rotation_degrees,
                    "actual_rotation": rotation_degrees,
                    "expected_advance_width": target_width,
                    "actual_advance_width": delivered_advance,
                    "source_font_em_height": source_em_height,
                    "source_cap_height_ratio": cap_height_ratio,
                    "source_char_layout_verified": requires_individual,
                },
            }
        )
        _commit_outlines(
            attempt,
            outlines,
            fills,
            msp,
            representation=representation,
            insertion=insertion,
            expectation=expectation,
            is_r12=is_r12,
        )
        if not attempt.type_verified or not attempt.visual_verified:
            raise ValueError("outline delivery failed type or visual verification")
        attempt.outcome = "verified"
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        if not attempt.cleanup_verified:
            raise ValueError("outline ownership verification failed")
        return attempt
    except Exception as exc:
        attempt.reason = f"{type(exc).__name__}: {exc}"
        _rollback_outline_attempt(attempt, msp)
        attempt.outcome = (
            "impossible" if isinstance(exc, _RepresentationImpossible) else "failed"
        )
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        return attempt


def _representation_ladder(requested: str) -> List[str]:
    ladders = {
        "text": ["text", "glyphs", "geometry"],
        "labels": ["labels", "text", "glyphs", "geometry"],
        "glyphs": ["glyphs", "geometry", "text"],
        "geometry": ["geometry", "glyphs", "text"],
        # Native flat Text is the closest semantic degradation after the exact
        # item-specific 3D Text attempt is affirmatively proven impossible.
        "3d_text": ["3d_text", "text", "glyphs", "geometry"],
        # Raster is a direct requested representation. The DXF builder has no
        # source PDF pixels, so the source-bound exporter performs this sole
        # rung and verifies the resulting IMAGE plus its persisted asset.
        "raster": ["raster"],
    }
    return list(ladders.get(requested, []))


def _build_delivery(
    text_item: NormalizedText,
    msp: Any,
    layer_name: str,
    config: ImportConfig,
    *,
    is_r12: bool,
    target_app: str,
    dxf_version: str,
) -> TextDeliveryResult:
    requested = _normalized_mode(getattr(config, "text_mode", "text"))
    source_id = _source_id(text_item)
    if not source_id:
        return TextDeliveryResult(
            source_id="",
            requested_representation=requested,
            final_representation=None,
            verified=False,
            failure_reason="source text item has no stable identity",
        )
    if str(getattr(text_item, "text", "") or "") == "":
        return TextDeliveryResult(
            source_id=source_id,
            requested_representation=requested,
            final_representation=None,
            verified=False,
            failure_reason="source text item is empty",
        )
    ladder = _representation_ladder(requested)
    if not ladder:
        return TextDeliveryResult(
            source_id=source_id,
            requested_representation=requested,
            final_representation=None,
            verified=False,
            failure_reason=f"unsupported requested representation: {requested}",
        )

    attempts: List[TextDeliveryAttempt] = []

    def verified_result(
        representation: str,
        attempt: TextDeliveryAttempt,
    ) -> TextDeliveryResult:
        for prior in attempts[:-1]:
            prior.superseded = True
        return TextDeliveryResult(
            source_id=source_id,
            requested_representation=requested,
            final_representation=representation,
            verified=True,
            entity_handles=list(attempt.entity_handles),
            support_entity_handles=list(attempt.support_entity_handles),
            referenced_entity_handles=list(attempt.referenced_entity_handles),
            attempts=attempts,
        )

    def unverified_result(reason: str, *, terminal: bool = False) -> TextDeliveryResult:
        return TextDeliveryResult(
            source_id=source_id,
            requested_representation=requested,
            final_representation=None,
            verified=False,
            attempts=attempts,
            terminal_fallback_authorized=terminal,
            failure_reason=reason,
        )

    def cleanup_failure(attempt: TextDeliveryAttempt) -> TextDeliveryResult:
        return unverified_result(
            "%s cleanup/ownership verification is incomplete; fallback is forbidden"
            % attempt.attempted_representation
        )

    if ladder == ["raster"]:
        return unverified_result(
            "requested Raster is pending a source-bound item render",
            terminal=True,
        )

    authoritative_source_error: Optional[str] = None
    try:
        _validate_item_source_geometry(text_item)
    except (TypeError, ValueError) as exc:
        authoritative_source_error = f"invalid authoritative source geometry: {exc}"

    for representation in ladder:
        representation_start = len(attempts)
        if authoritative_source_error and representation in {"3d_text", "labels", "text"}:
            # Outline attempts validate and record the item-specific source
            # contradiction themselves.  A semantic/native rung must never
            # erase that failure by certifying concatenated or otherwise less
            # constrained text against invalid authoritative geometry.
            return unverified_result(authoritative_source_error)
        if representation == "3d_text":
            attempt = _attempt_labels(
                text_item,
                msp,
                layer_name,
                requested=requested,
                source_id=source_id,
                is_r12=is_r12,
                target_app=target_app,
                dxf_version=dxf_version,
                config=config,
                extrusion_depth=getattr(config, "model3d_depth_mm", None),
            )
            attempts.append(attempt)
            if attempt.outcome == "verified":
                if not attempt.cleanup_verified:
                    return cleanup_failure(attempt)
                return verified_result("3d_text", attempt)
            if not attempt.cleanup_verified:
                return cleanup_failure(attempt)
            if attempt.outcome != "impossible":
                return unverified_result(
                    attempt.reason
                    or "native extruded TEXT impossibility was not proven"
                )
            continue

        if representation == "labels":
            attempt = _attempt_labels(
                text_item,
                msp,
                layer_name,
                requested=requested,
                source_id=source_id,
                is_r12=is_r12,
                target_app=target_app,
                dxf_version=dxf_version,
                config=config,
                semantic_representation="labels",
            )
            attempts.append(attempt)
            if attempt.outcome == "verified":
                if not attempt.cleanup_verified:
                    return cleanup_failure(attempt)
                return verified_result("labels", attempt)
            if not attempt.cleanup_verified:
                return cleanup_failure(attempt)
            if attempt.outcome != "impossible":
                return unverified_result(
                    attempt.reason or "Labels failed without impossibility proof"
                )
            continue

        if representation == "text":
            attempt = _attempt_labels(
                text_item,
                msp,
                layer_name,
                requested=requested,
                source_id=source_id,
                is_r12=is_r12,
                target_app=target_app,
                dxf_version=dxf_version,
                config=config,
                semantic_representation="text",
            )
            attempts.append(attempt)
            if attempt.outcome == "verified":
                if not attempt.cleanup_verified:
                    return cleanup_failure(attempt)
                return verified_result("text", attempt)
            if not attempt.cleanup_verified:
                return cleanup_failure(attempt)
            if attempt.outcome != "impossible":
                return unverified_result(
                    attempt.reason or "Text failed without impossibility proof"
                )
            continue

        outline_attempt = _attempt_outline_entity(
            text_item,
            msp,
            layer_name,
            representation=representation,
            requested=requested,
            source_id=source_id,
            is_r12=is_r12,
            config=config,
        )
        attempts.append(outline_attempt)
        if outline_attempt.outcome == "verified":
            if not outline_attempt.cleanup_verified:
                return cleanup_failure(outline_attempt)
            return verified_result(representation, outline_attempt)
        if not outline_attempt.cleanup_verified:
            return cleanup_failure(outline_attempt)

        second_attempt = _attempt_outline_string(
            text_item,
            msp,
            layer_name,
            representation=representation,
            requested=requested,
            source_id=source_id,
            is_r12=is_r12,
            config=config,
        )
        attempts.append(second_attempt)
        if second_attempt.outcome == "verified":
            if not second_attempt.cleanup_verified:
                return cleanup_failure(second_attempt)
            return verified_result(representation, second_attempt)
        if not second_attempt.cleanup_verified:
            return cleanup_failure(second_attempt)

        representation_attempts = attempts[representation_start:]
        if not representation_attempts or any(
            attempt.outcome != "impossible" for attempt in representation_attempts
        ):
            reason = "; ".join(
                attempt.reason for attempt in representation_attempts if attempt.reason
            ) or f"{representation} failed without impossibility proof"
            return unverified_result(reason)

    failure_reason = "; ".join(
        attempt.reason for attempt in attempts if attempt.reason
    ) or "all safe representation attempts failed verification"
    return unverified_result(failure_reason, terminal=True)


def build_text(
    text_item: NormalizedText,
    msp: Any,
    layer_name: str,
    config: ImportConfig,
    is_r12: bool = False,
    target_app: str = "generic",
    dxf_version: str = "R2010",
    return_delivered_kind: bool = False,
    return_delivery_result: bool = False,
) -> Union[int, Tuple[str, int], TextDeliveryResult]:
    """Build and verify one requested representation.

    The legacy integer and ``(kind, count)`` return forms remain available.
    New production callers should request :class:`TextDeliveryResult` and
    persist its exact handles and attempt history.
    """
    result = _build_delivery(
        text_item,
        msp,
        layer_name,
        config,
        is_r12=is_r12,
        target_app=target_app,
        dxf_version=dxf_version,
    )
    if return_delivery_result:
        return result
    if return_delivered_kind:
        return result.delivered_kind, result.count
    return result.count


def reset_text_styles() -> None:
    """Clear the cached text-style registry (call between documents)."""
    global _style_counter  # noqa: PLW0603
    _created_styles.clear()
    _style_counter = 0


__all__ = [
    "TextDeliveryAttempt",
    "TextDeliveryResult",
    "build_text",
    "reset_text_styles",
]

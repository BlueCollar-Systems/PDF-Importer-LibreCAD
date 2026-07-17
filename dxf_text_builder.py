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
import math
from pathlib import Path
import re
import unicodedata
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
    if resolution.exact:
        return resolution
    if resolution.item_impossibility_proven:
        raise _RepresentationImpossible(resolution.reason)
    raise ValueError(resolution.reason)


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
    page = int(getattr(text_item, "page_number", 0) or 0)
    item_id = getattr(text_item, "id", None)
    if item_id is None or str(item_id).strip() == "":
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
) -> bool:
    if expected is None or actual is None:
        return False
    shifted = (
        expected[0] + offset[0],
        expected[1] + offset[1],
        expected[2] + offset[0],
        expected[3] + offset[1],
    )
    scale = max(1.0, *(abs(value) for value in shifted + actual))
    tolerance = max(1e-7, scale * 1e-8)
    return all(
        math.isclose(left, right, rel_tol=1e-8, abs_tol=tolerance)
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
        if str(getattr(entity.dxf, "text", "") or "") and not str(
            getattr(entity.dxf, "text", "") or ""
        ).strip():
            return 0.0
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
        actual_text and not actual_text.strip() and measured_width == 0.0
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
        evidence.update(
            {
                "parent_native_font_required_format": None,
                "parent_native_font_format_verified": True,
                "parent_native_font_renderability_verified": True,
                "parent_native_text_delivery_verified": True,
                "parent_native_3d_display_verified": True,
                "parent_visual_fidelity_verified": source_visual_ok,
                "fallback_authorized_for_this_item": False,
            }
        )
        return True, evidence, ""

    font_ok = candidate_format == "lff" and bool(str(style_font or "").strip())
    # A whitespace-only PDF span has no font pixels to reproduce.  A native
    # TEXT entity still preserves its exact semantic content and placement, so
    # requiring an LFF renderer for pixels that do not exist would manufacture
    # a false impossibility and can ultimately rasterize unrelated nearby ink.
    font_rendering_required = not source_content_whitespace_only
    font_requirement_ok = bool(font_ok or not font_rendering_required)
    native_3d_ok = not is_3d_text
    parent_delivery_ok = bool(font_requirement_ok and native_3d_ok)
    source_visual_ok = bool(
        native_3d_ok
        and (
            not font_rendering_required
            or (font_ok and not bool(parent_font_substituted))
        )
    )
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
            source_origin = str(
                font_resolution.source_origin
                or font_resolution.resolution_source
                or ""
            ).strip().lower()
            parent_font_substituted = source_origin != "embedded_pdf_font"
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
        delivered_text = (
            unicodedata.normalize("NFKC", str(text_item.text))
            if parent == "librecad"
            else str(text_item.text)
        )
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
                source_content_whitespace_only=not bool(
                    str(getattr(text_item, "text", "") or "").strip()
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
    if is_r12:
        return list(ezdxf_path.to_polylines2d(paths, dxfattribs=attribs))
    return list(ezdxf_path.to_lwpolylines(paths, dxfattribs=attribs))


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
        max_sagitta=0.01,
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
        p0 = (float(entity.dxf.vtx0.x), float(entity.dxf.vtx0.y))
        p1 = (float(entity.dxf.vtx1.x), float(entity.dxf.vtx1.y))
        p2 = (float(entity.dxf.vtx2.x), float(entity.dxf.vtx2.y))
        area2 = abs(
            (p1[0] - p0[0]) * (p2[1] - p0[1])
            - (p1[1] - p0[1]) * (p2[0] - p0[0])
        )
        if not math.isfinite(area2) or area2 <= 1e-14:
            return False
    return True


def _unique_block_name(doc: ezdxf.document.Drawing, source_id: str) -> str:
    base = "BCS_GLYPH_" + re.sub(r"[^A-Za-z0-9_]+", "_", source_id).strip("_")
    if not base or base == "BCS_GLYPH_":
        base = "BCS_GLYPH_ITEM"
    candidate = base[:240]
    suffix = 1
    while candidate in doc.blocks:
        suffix += 1
        candidate = f"{base[:230]}_{suffix}"
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


def _commit_outlines(
    attempt: TextDeliveryAttempt,
    outlines: List[Any],
    fills: List[Any],
    msp: Any,
    *,
    representation: str,
    insertion: Tuple[float, float],
    expected_bbox: Optional[Tuple[float, float, float, float]],
    is_r12: bool,
) -> None:
    doc = msp.doc
    if not outlines:
        raise ValueError("outline strategy returned zero entities")
    fill_verified = _solid_fill_verified(fills, is_r12=is_r12)
    attempt.evidence.update(
        {
            "solid_fill_entity_type": "SOLID",
            "solid_fill_entity_count": len(fills),
            "solid_fill_verified": fill_verified,
        }
    )
    if not fill_verified:
        raise ValueError("outline strategy did not create verified solid glyph fill")

    if representation == "geometry":
        for entity in outlines + fills:
            msp.add_entity(entity)
            attempt.created_entity_handles.append(_handle(entity))
        attempt.entity_handles = [_handle(entity) for entity in outlines + fills]
        actual_bbox = _bbox_tuple(outlines)
        attempt.type_verified = (
            bool(attempt.entity_handles)
            and all(
                entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
                for entity in outlines
            )
            and _solid_fill_verified(fills, is_r12=is_r12)
        )
        attempt.visual_verified = _bbox_matches(expected_bbox, actual_bbox)
        attempt.evidence.update(
            {
                "expected_outline_bbox": list(expected_bbox) if expected_bbox else None,
                "actual_outline_bbox": list(actual_bbox) if actual_bbox else None,
            }
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
        "layer": str(outlines[0].dxf.layer or "0"),
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
    actual_bbox = _bbox_tuple(outlines)
    actual_insert = tuple(float(value) for value in tuple(block_ref.dxf.insert)[:2])
    insert_verified = all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
        for left, right in zip(actual_insert, insertion, strict=True)
    )
    expected_true_color = block_attribs.get("true_color")
    actual_true_color = (
        block_ref.dxf.true_color
        if block_ref.dxf.hasattr("true_color")
        else None
    )
    insert_color_verified = bool(
        expected_true_color is None
        or (
            actual_true_color is not None
            and int(actual_true_color) == int(expected_true_color)
        )
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
    attempt.visual_verified = bool(
        insert_verified
        and insert_color_verified
        and _bbox_matches(expected_bbox, actual_bbox)
    )
    attempt.evidence.update(
        {
            "block_name": block_name,
            "nonserializable_support_roles": ["BLOCK_RECORD"] if is_r12 else [],
            "expected_outline_bbox": list(expected_bbox) if expected_bbox else None,
            "actual_outline_bbox": list(actual_bbox) if actual_bbox else None,
            "expected_block_insert": list(insertion),
            "actual_block_insert": list(actual_insert),
            "block_insert_verified": insert_verified,
            "block_insert_color_verified": insert_color_verified,
            "block_insert_true_color": expected_true_color,
        }
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
        paths = text2path.make_paths_from_entity(source)
        outlines = _to_outline_entities(
            paths, is_r12=is_r12, attribs=_outline_attributes(attribs)
        )
        fills = _to_solid_fill_entities(
            paths,
            is_r12=is_r12,
            attribs=_outline_attributes(attribs),
        )
        if not outlines and str(text_item.text) and not str(text_item.text).strip():
            attempt.evidence.update(
                {
                    "source_content_whitespace_only": True,
                    "visible_ink_expected": False,
                    "zero_outline_result_verified": True,
                    "item_specific_creation_attempted": True,
                }
            )
            raise _RepresentationImpossible(
                "whitespace-only source item has no outline ink"
            )
        expected_bbox = _bbox_tuple(outlines)
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
            expected_bbox=expected_bbox,
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
        source_em_height = _positive_finite(getattr(text_item, "font_size", None))
        if source_em_height is None:
            raise _RepresentationImpossible(
                "source nominal text height is missing or invalid for outline delivery"
            )
        insertion = tuple(float(value) for value in text_item.insertion[:2])
        rotation = math.radians(float(getattr(text_item, "rotation", 0.0) or 0.0))
        target_width, width_source = _target_advance_width(text_item)
        font_resolution = _require_exact_item_font(text_item, config, attempt)
        height, cap_height_ratio = _delivery_cap_height(
            source_em_height, font_resolution
        )
        face = FontFace(
            filename=font_resolution.filename
        )
        paths = text2path.make_paths_from_str(
            str(text_item.text),
            face,
            size=height,
            length=target_width or 0.0,
            m=Matrix44.z_rotate(rotation),
        )
        attribs = _base_attributes(
            text_item,
            layer_name=layer_name,
            height=height,
            insert=(0.0, 0.0),
            is_r12=is_r12,
            style_name="Standard",
        )
        outlines = _to_outline_entities(
            paths, is_r12=is_r12, attribs=_outline_attributes(attribs)
        )
        fills = _to_solid_fill_entities(
            paths,
            is_r12=is_r12,
            attribs=_outline_attributes(attribs),
        )
        if not outlines and str(text_item.text) and not str(text_item.text).strip():
            attempt.evidence.update(
                {
                    "source_content_whitespace_only": True,
                    "visible_ink_expected": False,
                    "zero_outline_result_verified": True,
                    "item_specific_creation_attempted": True,
                }
            )
            raise _RepresentationImpossible(
                "whitespace-only source item has no outline ink"
            )
        if representation == "geometry":
            for entity in outlines + fills:
                entity.translate(insertion[0], insertion[1], 0.0)
        expected_bbox = _bbox_tuple(outlines)
        attempt.evidence.update(
            {
                "expected_advance_width": target_width,
                "width_source": width_source,
                "font_candidate": face.filename,
                "source_font_em_height": source_em_height,
                "source_cap_height_ratio": cap_height_ratio,
            }
        )
        _commit_outlines(
            attempt,
            outlines,
            fills,
            msp,
            representation=representation,
            insertion=insertion,
            expected_bbox=expected_bbox,
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

    if ladder == ["raster"]:
        return unverified_result(
            "requested Raster is pending a source-bound item render",
            terminal=True,
        )

    for representation in ladder:
        representation_start = len(attempts)
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
                return verified_result("3d_text", attempt)
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
                return verified_result("labels", attempt)
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
                return verified_result("text", attempt)
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
            return verified_result(representation, outline_attempt)

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
            return verified_result(representation, second_attempt)

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

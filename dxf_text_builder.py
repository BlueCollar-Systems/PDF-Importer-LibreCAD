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
import os
from pathlib import Path
import re
import unicodedata
import weakref
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf import path as ezdxf_path
from ezdxf.addons import text2path
from ezdxf.fonts import fonts as ezdxf_fonts
from ezdxf.fonts.font_face import FontFace
from ezdxf.math import Matrix44
from ezdxf.tools.text import plain_text
from ezdxf.tools.text_size import text_size

from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText
from librecad_runtime import redacted_local_path, resolve_librecad_installation


_MTEXT_THRESHOLD = 120
_created_styles: Dict[str, str] = {}
_embedded_cap_height_cache: Dict[str, float] = {}
_staged_font_verification_cache: Dict[Tuple[str, str, int, int], bool] = {}
_glyph_block_cache: weakref.WeakKeyDictionary[
    Any,
    Dict[Tuple[bool, str], str],
] = weakref.WeakKeyDictionary()
_canonical_glyph_path_cache: Dict[
    Tuple[Tuple[str, ...], str],
    Optional[Any],
] = {}
_scaled_glyph_geometry_cache: Dict[
    Tuple[Tuple[str, ...], str, float, bool, Tuple[Tuple[str, str], ...]],
    Tuple[List[Any], str],
] = {}
_source_outline_bbox_cache: Dict[
    Tuple[Any, ...],
    Optional[Tuple[float, float, float, float]],
] = {}
_glyph_definition_fingerprint_cache: weakref.WeakKeyDictionary[
    Any,
    Dict[str, str],
] = weakref.WeakKeyDictionary()
_librecad_lff_cache: Dict[
    Tuple[str, int, int, str],
    "_LibreCadLffResolution",
] = {}
_MAX_LIBRECAD_LFF_BYTES = 16 * 1024 * 1024
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
    delivery_verified: bool = False
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
        for attempt in self.attempts:
            if attempt.outcome == "verified" and not all(
                (
                    attempt.type_verified,
                    attempt.delivery_verified,
                    attempt.visual_verified,
                    attempt.cleanup_verified,
                )
            ):
                raise RuntimeError(
                    "verified attempt is missing terminal proof: "
                    f"{attempt.source_id}/{attempt.attempted_representation}"
                )
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
class _NestedGlyphGeometry:
    """One exact glyph instance backed by a reusable definition block."""

    insertion: Tuple[float, float]
    xscale: float
    yscale: float
    rotation: float
    paths: List[Any]
    attribs: Dict[str, Any]
    fingerprint: str


@dataclass
class _NestedGlyphRun:
    """Reusable definition geometry plus per-span cache-work evidence."""

    geometries: List[_NestedGlyphGeometry]
    canonical_created_count: int = 0
    canonical_reused_count: int = 0


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


@dataclass(frozen=True)
class _LibreCadLffResolution:
    path: str = ""
    size_bytes: int = 0
    sha256: str = ""
    glyph_codepoints: frozenset[int] = frozenset()
    drawable_codepoints: frozenset[int] = frozenset()
    resolution_source: str = ""
    executable_path: str = ""
    executable_resolution_source: str = ""
    installation_root: str = ""
    executable_binding_verified: bool = False
    parent_installation_verified: bool = False
    verified: bool = False
    reason: str = ""

    def evidence(self, content: str) -> Dict[str, Any]:
        required = sorted(
            {ord(character) for character in str(content) if not character.isspace()}
        )
        missing = [value for value in required if value not in self.glyph_codepoints]
        invalid = [
            value
            for value in required
            if value in self.glyph_codepoints
            and value not in self.drawable_codepoints
        ]
        drawable_verified = bool(self.verified and not missing and not invalid)
        local_diagnostics = {
            "classification": "local_sensitive_paths",
            "shareable": False,
            "librecad_executable_path": self.executable_path or None,
            "librecad_installation_root": self.installation_root or None,
            "librecad_lff_path": self.path or None,
        }
        return {
            "librecad_evidence_sensitivity": (
                "shareable_with_classified_local_diagnostics"
            ),
            "local_only_diagnostics": local_diagnostics,
            "librecad_executable_path": redacted_local_path(self.executable_path),
            "librecad_executable_resolution_source": (
                self.executable_resolution_source or None
            ),
            "librecad_installation_root": redacted_local_path(
                self.installation_root
            ),
            "librecad_parent_installation_verified": bool(
                self.parent_installation_verified
            ),
            "librecad_lff_executable_binding_verified": bool(
                self.executable_binding_verified
            ),
            "librecad_lff_path": redacted_local_path(self.path),
            "librecad_lff_size_bytes": int(self.size_bytes),
            "librecad_lff_sha256": self.sha256 or None,
            "librecad_lff_glyph_count": len(self.glyph_codepoints),
            "librecad_lff_drawable_glyph_count": len(self.drawable_codepoints),
            "librecad_lff_resolution_source": self.resolution_source or None,
            "librecad_lff_asset_verified": bool(self.verified),
            "librecad_lff_required_codepoints": [
                f"U+{value:04X}" for value in required
            ],
            "librecad_lff_missing_codepoints": [
                f"U+{value:04X}" for value in missing
            ],
            "librecad_lff_invalid_codepoints": [
                f"U+{value:04X}" for value in invalid
            ],
            "librecad_lff_required_glyphs_drawable_verified": drawable_verified,
            "librecad_lff_coverage_verified": drawable_verified,
            "librecad_lff_resolution_reason": self.reason,
        }


def _parse_librecad_lff(
    path: Path,
    resolution_source: str,
    *,
    executable_path: str,
    executable_resolution_source: str,
    installation_root: str,
    fresh: bool = False,
) -> _LibreCadLffResolution:
    resolved = path.expanduser().resolve()
    base = {
        "path": str(resolved),
        "resolution_source": resolution_source,
        "executable_path": executable_path,
        "executable_resolution_source": executable_resolution_source,
        "installation_root": installation_root,
        "executable_binding_verified": True,
        "parent_installation_verified": True,
    }
    if not resolved.is_file():
        return _LibreCadLffResolution(
            **base,
            reason="LibreCAD unicode.lff asset is absent",
        )
    try:
        with resolved.open("rb") as stream:
            stat_before = os.fstat(stream.fileno())
            if int(stat_before.st_size) > _MAX_LIBRECAD_LFF_BYTES:
                return _LibreCadLffResolution(
                    **base,
                    size_bytes=int(stat_before.st_size),
                    reason=(
                        "LibreCAD unicode.lff exceeds the "
                        f"{_MAX_LIBRECAD_LFF_BYTES}-byte safety limit"
                    ),
                )
            cache_key = (
                str(resolved),
                int(stat_before.st_size),
                int(stat_before.st_mtime_ns),
                executable_path,
            )
            if not fresh:
                cached = _librecad_lff_cache.get(cache_key)
                if cached is not None:
                    return cached
            payload = stream.read(_MAX_LIBRECAD_LFF_BYTES + 1)
            stat_after = os.fstat(stream.fileno())
        path_stat_after = resolved.stat()
        before_signature = (
            int(stat_before.st_dev),
            int(stat_before.st_ino),
            int(stat_before.st_size),
            int(stat_before.st_mtime_ns),
        )
        after_signature = (
            int(stat_after.st_dev),
            int(stat_after.st_ino),
            int(stat_after.st_size),
            int(stat_after.st_mtime_ns),
        )
        path_signature = (
            int(path_stat_after.st_dev),
            int(path_stat_after.st_ino),
            int(path_stat_after.st_size),
            int(path_stat_after.st_mtime_ns),
        )
        if (
            before_signature != after_signature
            or after_signature != path_signature
            or len(payload) != int(stat_after.st_size)
        ):
            return _LibreCadLffResolution(
                **base,
                reason="LibreCAD unicode.lff changed while it was being read",
            )
        cache_key = (
            str(resolved),
            int(stat_after.st_size),
            int(stat_after.st_mtime_ns),
            executable_path,
        )
        content = payload.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return _LibreCadLffResolution(
            **base,
            reason=(
                "LibreCAD unicode.lff asset is unreadable "
                f"({type(exc).__name__})"
            ),
        )
    format_ok = bool(
        re.search(r"(?im)^#\s*Format:\s*LibreCAD\s+Font\s+1\s*$", content)
    )
    glyph_bodies: Dict[int, List[str]] = {}
    current_codepoint: Optional[int] = None
    for raw_line in content.splitlines():
        header = re.match(r"^\[([0-9A-Fa-f]{4,6})\](?:\s.*)?$", raw_line)
        if header:
            current_codepoint = int(header.group(1), 16)
            glyph_bodies.setdefault(current_codepoint, [])
            continue
        if current_codepoint is None:
            continue
        line = raw_line.strip()
        if line and not line.startswith("#"):
            glyph_bodies[current_codepoint].append(line)

    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    vertex = rf"{number}\s*,\s*{number}(?:\s*,\s*A{number})?"
    geometry_pattern = re.compile(
        rf"^{vertex}(?:\s*;\s*{vertex})+$",
        re.IGNORECASE,
    )
    reference_pattern = re.compile(r"^C([0-9A-Fa-f]{4,6})\s*$")
    references: Dict[int, Tuple[int, ...]] = {}
    direct_geometry: set[int] = set()
    invalid_bodies: set[int] = set()
    for codepoint, body in glyph_bodies.items():
        glyph_references = []
        for line in body:
            reference = reference_pattern.match(line)
            if reference:
                glyph_references.append(int(reference.group(1), 16))
            elif geometry_pattern.match(line):
                direct_geometry.add(codepoint)
            else:
                invalid_bodies.add(codepoint)
        references[codepoint] = tuple(glyph_references)

    drawable_cache: Dict[int, bool] = {}

    def glyph_is_drawable(codepoint: int, active: frozenset[int]) -> bool:
        cached = drawable_cache.get(codepoint)
        if cached is not None:
            return cached
        if codepoint in active or codepoint not in glyph_bodies:
            return False
        if codepoint in invalid_bodies:
            drawable_cache[codepoint] = False
            return False
        glyph_references = references.get(codepoint, ())
        has_drawing = codepoint in direct_geometry or bool(glyph_references)
        valid = bool(
            has_drawing
            and all(
                glyph_is_drawable(reference, active | {codepoint})
                for reference in glyph_references
            )
        )
        drawable_cache[codepoint] = valid
        return valid

    codepoints = frozenset(glyph_bodies)
    drawable_codepoints = frozenset(
        codepoint
        for codepoint in codepoints
        if glyph_is_drawable(codepoint, frozenset())
    )
    verified = bool(format_ok and codepoints and drawable_codepoints and payload)
    result = _LibreCadLffResolution(
        **base,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        glyph_codepoints=codepoints,
        drawable_codepoints=drawable_codepoints,
        verified=verified,
        reason=(
            "verified LibreCAD Font 1 unicode.lff asset"
            if verified
            else "file is not a parseable LibreCAD Font 1 asset"
        ),
    )
    _librecad_lff_cache[cache_key] = result
    return result


def _resolve_librecad_unicode_lff(
    executable: Optional[str] = None,
    *,
    fresh: bool = False,
) -> _LibreCadLffResolution:
    installation = resolve_librecad_installation(executable)
    if installation is None:
        return _LibreCadLffResolution(
            reason=(
                "no resolved LibreCAD executable is available to bind the "
                "unicode.lff asset"
            )
        )
    candidates = [
        (Path(path), source) for path, source in installation.unicode_lff_candidates
    ]
    configured = str(os.environ.get("BCS_LIBRECAD_UNICODE_LFF", "") or "").strip()
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        bound_sources = {
            os.path.normcase(str(path.resolve())): source for path, source in candidates
        }
        configured_key = os.path.normcase(str(configured_path))
        if configured_key not in bound_sources:
            return _LibreCadLffResolution(
                path=str(configured_path),
                executable_path=installation.executable_path,
                executable_resolution_source=(
                    installation.executable_resolution_source
                ),
                installation_root=installation.installation_root,
                parent_installation_verified=True,
                reason=(
                    "configured LibreCAD unicode.lff is not bound to the "
                    "resolved LibreCAD executable installation"
                ),
            )
        candidates = [(configured_path, "bound_environment_override")]
    failures: List[str] = []
    for path, source in candidates:
        resolution = _parse_librecad_lff(
            path,
            source,
            executable_path=installation.executable_path,
            executable_resolution_source=(
                installation.executable_resolution_source
            ),
            installation_root=installation.installation_root,
            fresh=fresh,
        )
        if resolution.verified:
            return resolution
        failures.append(
            f"{redacted_local_path(resolution.path)}: {resolution.reason}"
        )
    return _LibreCadLffResolution(
        path=str(candidates[0][0].expanduser().resolve()),
        resolution_source=candidates[0][1],
        executable_path=installation.executable_path,
        executable_resolution_source=installation.executable_resolution_source,
        installation_root=installation.installation_root,
        executable_binding_verified=True,
        parent_installation_verified=True,
        reason="; ".join(failures),
    )


def _librecad_lff_evidence(
    content: str,
    executable: Optional[str] = None,
    *,
    fresh: bool = False,
) -> Dict[str, Any]:
    return _resolve_librecad_unicode_lff(executable, fresh=fresh).evidence(content)


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


def _staged_font_matches_source(
    path: Path,
    expected_sha256: str,
    expected_bytes: bytes,
) -> bool:
    """Verify immutable staged font bytes once per export document."""

    stat = path.stat()
    cache_key = (
        str(path.resolve()),
        str(expected_sha256),
        int(stat.st_size),
        int(stat.st_mtime_ns),
    )
    if cache_key in _staged_font_verification_cache:
        return _staged_font_verification_cache[cache_key]
    content = path.read_bytes()
    matches = bool(
        hashlib.sha256(content).hexdigest() == str(expected_sha256)
        and content == expected_bytes
    )
    _staged_font_verification_cache[cache_key] = matches
    return matches


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
                bytes(asset.usable_bytes),
                cache_key=str(asset.usable_sha256),
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
        restore = getattr(config, "_restore_embedded_font_asset", None)
        if path is not None and not path.is_file() and callable(restore):
            try:
                restored_filename = str(restore(str(asset.asset_id)) or "")
                restored_path = Path(restored_filename) if restored_filename else None
                if (
                    restored_path is None
                    or restored_path.expanduser().resolve() != path.expanduser().resolve()
                ):
                    raise ValueError(
                        "embedded font restager returned a different asset path"
                    )
                path = restored_path
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                return _ExactFontResolution(
                    **base,
                    exact=False,
                    reason=f"exact embedded font asset could not be restaged: {exc}",
                )
        if path is None or not path.is_file():
            return _ExactFontResolution(
                **base,
                exact=False,
                reason="exact embedded font was not staged for this export",
            )
        try:
            staged_font_matches = _staged_font_matches_source(
                path,
                str(asset.usable_sha256),
                bytes(asset.usable_bytes),
            )
        except OSError as exc:
            return _ExactFontResolution(
                **base,
                exact=False,
                reason=f"exact embedded font asset could not be read: {exc}",
            )
        if not staged_font_matches:
            if callable(restore):
                try:
                    restored_filename = str(restore(str(asset.asset_id)) or "")
                    restored_path = Path(restored_filename) if restored_filename else None
                    if (
                        restored_path is None
                        or restored_path.expanduser().resolve()
                        != path.expanduser().resolve()
                    ):
                        raise ValueError(
                            "embedded font restager returned a different asset path"
                        )
                    path = restored_path
                    staged_font_matches = _staged_font_matches_source(
                        path,
                        str(asset.usable_sha256),
                        bytes(asset.usable_bytes),
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    return _ExactFontResolution(
                        **base,
                        exact=False,
                        reason=f"exact embedded font asset could not be restaged: {exc}",
                    )
        if not staged_font_matches:
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


def _embedded_ezdxf_cap_height_ratio(
    font_bytes: bytes,
    *,
    cache_key: str = "",
) -> float:
    """Resolve a certifiable cap-height ratio from a possibly subset font.

    PDF subset programs legitimately omit unused lowercase ``x`` glyphs.
    Prefer the font's explicit OS/2 cap height when present; otherwise derive
    the same baseline-to-cap measurement from available, non-descending Latin
    glyphs.  The hhea ascent is a final font-table metric for symbol/digit-only
    subsets that contain no usable capital outline.
    """

    font_payload = bytes(font_bytes)
    resolved_cache_key = str(cache_key or hashlib.sha256(font_payload).hexdigest())
    cached_ratio = _embedded_cap_height_cache.get(resolved_cache_key)
    if cached_ratio is not None:
        return cached_ratio

    from fontTools.pens.boundsPen import ControlBoundsPen
    from fontTools.ttLib import TTFont

    font = TTFont(BytesIO(font_payload), lazy=False, recalcTimestamp=False)
    try:
        units_per_em = float(font["head"].unitsPerEm)
        if not math.isfinite(units_per_em) or units_per_em <= 0.0:
            raise ValueError("font unitsPerEm is invalid")
        cmap = font.getBestCmap()
        if cmap is None:
            raise ValueError("font has no Unicode character map")
        glyph_set = font.getGlyphSet()

        def control_bounds(
            character: str,
        ) -> Optional[Tuple[float, float, float, float]]:
            glyph_name = cmap.get(ord(character))
            if not glyph_name or glyph_name not in glyph_set:
                return None
            pen = ControlBoundsPen(glyph_set)
            glyph_set[glyph_name].draw(pen)
            if pen.bounds is None:
                return None
            return tuple(float(value) for value in pen.bounds)

        explicit_cap_height = None
        if "OS/2" in font:
            candidate = float(getattr(font["OS/2"], "sCapHeight", 0.0) or 0.0)
            if math.isfinite(candidate) and candidate > 0.0:
                explicit_cap_height = candidate

        if explicit_cap_height is not None:
            cap_height = explicit_cap_height
        else:
            cap_bounds = next(
                (
                    bounds
                    for character in "AHIXMEFLT01"
                    if (bounds := control_bounds(character)) is not None
                ),
                None,
            )
            baseline_bounds = next(
                (
                    bounds
                    for character in "xHIAXMnoe01"
                    if (bounds := control_bounds(character)) is not None
                ),
                None,
            )
            if cap_bounds is not None:
                baseline = (
                    float(baseline_bounds[1])
                    if baseline_bounds is not None
                    else 0.0
                )
                cap_height = float(cap_bounds[3]) - baseline
            elif "hhea" in font:
                cap_height = float(font["hhea"].ascent)
            else:
                raise ValueError(
                    "font has no explicit or outline-derived cap-height metric"
                )
    finally:
        font.close()
    ratio = cap_height / units_per_em
    if not math.isfinite(ratio) or ratio <= 0.0:
        raise ValueError("font cap-height ratio is invalid")
    _embedded_cap_height_cache[resolved_cache_key] = ratio
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
    accept_librecad_font_substitution: bool,
    librecad_lff_asset_verified: bool,
    librecad_lff_coverage_verified: bool,
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
                "fallback_authorized_for_this_item": not source_visual_ok,
            }
        )
        return True, evidence, ""

    try:
        actual_style = entity.doc.styles.get(style_name)
        actual_style_font = str(actual_style.dxf.font or "").strip()
    except Exception:
        actual_style_font = ""
    entity_style_ok = str(entity.dxf.style or "").strip() == style_name
    style_binding_ok = bool(
        entity_style_ok
        and actual_style_font.lower() == str(style_font or "").strip().lower()
    )
    builtin_unicode_lff_ok = bool(
        candidate_format == "lff"
        and str(style_font or "").strip().lower() == "unicode"
        and style_name.strip().lower() == "unicode"
        and style_binding_ok
        and librecad_lff_asset_verified
        and librecad_lff_coverage_verified
    )
    font_ok = builtin_unicode_lff_ok
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
    substitution_accepted = bool(
        accept_librecad_font_substitution
        and parent_font_substituted
        and font_ok
        and native_3d_ok
    )
    evidence.update(
        {
            "parent_native_font_required_format": "lff",
            "parent_native_font_format_verified": font_ok,
            "parent_native_font_renderability_verified": False,
            "parent_native_font_asset_coverage_verified": font_ok,
            "parent_native_font_style_binding_verified": style_binding_ok,
            "parent_native_font_builtin_lff_verified": builtin_unicode_lff_ok,
            "parent_render_verification_required": True,
            "parent_native_font_rendering_required": font_rendering_required,
            "source_content_whitespace_only": source_content_whitespace_only,
            "parent_native_3d_display_verified": native_3d_ok,
            "parent_native_text_delivery_verified": parent_delivery_ok,
            "parent_visual_fidelity_verified": source_visual_ok,
            "parent_visual_fidelity_limited_by_font_substitution": bool(
                parent_font_substituted and not source_visual_ok
            ),
            "parent_native_font_substitution_accepted": substitution_accepted,
            "fallback_authorized_for_this_item": not (
                parent_delivery_ok and (source_visual_ok or substitution_accepted)
            ),
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
    librecad_executable: Optional[str],
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
        delivered_text = (
            unicodedata.normalize("NFKC", str(text_item.text))
            if parent == "librecad"
            else str(text_item.text)
        )
        font_resolution = _resolve_item_font(text_item, config)
        attempt.evidence.update(font_resolution.evidence())
        source_content_whitespace_only = not bool(
            str(getattr(text_item, "text", "") or "").strip()
        )
        # A substituted LFF can preserve editable structure, but it cannot
        # prove the source glyph appearance for visible text.  Only a zero-ink
        # whitespace span can terminate on this native rung; visible content
        # must descend to exact outlines (or the next finite fallback).
        accept_librecad_font_substitution = bool(
            parent == "librecad"
            and requested in {"text", "labels"}
            and not is_3d_text
            and source_content_whitespace_only
        )
        if parent == "librecad":
            lff_evidence = _librecad_lff_evidence(
                delivered_text,
                librecad_executable,
            )
            attempt.evidence.update(lff_evidence)
            if lff_evidence["librecad_lff_asset_verified"] is not True:
                raise _RepresentationImpossible(
                    str(lff_evidence["librecad_lff_resolution_reason"])
                )
            if lff_evidence["librecad_lff_coverage_verified"] is not True:
                unavailable = ", ".join(
                    [
                        *lff_evidence["librecad_lff_missing_codepoints"],
                        *lff_evidence["librecad_lff_invalid_codepoints"],
                    ]
                )
                raise _RepresentationImpossible(
                    "LibreCAD unicode.lff does not provide a drawable glyph "
                    f"body for {unavailable}"
                )
            # LibreCAD's editable native text renderer consumes its bundled LFF
            # fonts. Build this item-scoped candidate with the broad Unicode LFF
            # face, then require source-equivalent visual proof below. Visible
            # substituted glyphs descend to exact outlines; only zero-ink
            # whitespace may terminate on this native rung.
            style_font = "unicode"
            parent_font_format = (
                Path(str(lff_evidence["librecad_lff_path"] or ""))
                .suffix.lower()
                .lstrip(".")
                or "unknown"
            )
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
        height_basis = "source_font_cap_height"
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
        if force_text and plain_text(delivered_text) != delivered_text:
            # DXF TEXT treats a trailing caret as a control and ezdxf removes
            # it. Marker fonts use a lone caret as visible source content, so
            # certify this item as impossible in native TEXT before creating a
            # silently mutated entity; the caller can continue down its finite
            # item-scoped fallback ladder without aborting the page.
            raise _RepresentationImpossible(
                "DXF TEXT cannot carry trailing caret marker control without "
                "mutating source content"
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
                source_content_whitespace_only=source_content_whitespace_only,
                accept_librecad_font_substitution=(
                    accept_librecad_font_substitution
                ),
                librecad_lff_asset_verified=bool(
                    attempt.evidence.get("librecad_lff_asset_verified")
                ),
                librecad_lff_coverage_verified=bool(
                    attempt.evidence.get("librecad_lff_coverage_verified")
                ),
            )
        )
        attempt.evidence.update(parent_evidence)
        if accept_librecad_font_substitution:
            parent_contract_ok = bool(
                parent_delivery_ok
                and parent_evidence.get("parent_native_font_substitution_accepted")
                is True
            )
        else:
            parent_contract_ok = bool(
                parent_delivery_ok
                and parent_evidence.get("parent_visual_fidelity_verified") is True
            )
        delivery_ok = bool(
            visual_ok
            and (parent_contract_ok if parent == "librecad" else parent_delivery_ok)
        )
        attempt.delivery_verified = delivery_ok
        attempt.visual_verified = bool(
            delivery_ok
            if parent != "librecad"
            else (
                delivery_ok
                and parent_evidence.get("parent_visual_fidelity_verified") is True
            )
        )
        cap_height_invariant_ok = math.isclose(
            height,
            source_em_height * cap_height_ratio,
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
        attempt.evidence.update(
            {
                "source_font_em_height": source_em_height,
                "source_cap_height_ratio": cap_height_ratio,
                "native_text_height_basis": height_basis,
                "native_text_structure_verified": delivery_ok,
                "cap_height_invariant_verified": cap_height_invariant_ok,
            }
        )
        if not parent_delivery_ok:
            raise _RepresentationImpossible(parent_reason)
        label = "native 3D text" if is_3d_text else "native DXF text"
        if not type_ok:
            # Wrong entity kind is our defect, not a property of the source
            # item. Keep aborting so it cannot hide behind a silent descent.
            raise ValueError(f"{label} failed type verification")
        if not delivery_ok:
            # The entity was built correctly and still does not reproduce the
            # source. That is affirmative, item-specific proof that this rung
            # cannot carry this item, so the ladder descends rather than
            # killing the whole import -- one ESRIDefaultMarker glyph was
            # discarding 3,034 of 3,035 verified spans. Lower rungs render the
            # glyph as curves or raster, which reproduce it more faithfully
            # than substituted DXF text does.
            raise _RepresentationImpossible(
                f"{label} does not reproduce the source appearance of this item"
            )

        attempt.entity_handles = [handle]
        attempt.outcome = "verified"
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        if not attempt.cleanup_verified:
            raise ValueError("native DXF text ownership verification failed")
        return attempt
    except Exception as exc:
        attempt.delivery_verified = False
        attempt.visual_verified = False
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


def _path_geometry_fingerprint(
    paths: Sequence[Any],
    *,
    is_r12: bool,
    attribs: Dict[str, Any],
) -> str:
    """Return a translation-independent key for one persisted glyph definition."""

    path_records = []
    for glyph_path in paths:
        vertices = tuple(
            (
                round(float(vertex.x), 12),
                round(float(vertex.y), 12),
                round(float(vertex.z), 12),
            )
            for vertex in glyph_path.control_vertices()
        )
        path_records.append((tuple(glyph_path.command_codes()), vertices))
    attribute_record = tuple(
        (str(key), repr(value)) for key, value in sorted(attribs.items())
    )
    payload = repr((bool(is_r12), attribute_record, tuple(path_records))).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _entity_visual_attribute_record(entity: Any) -> Tuple[Any, ...]:
    """Normalize common DXF attributes that can hide or restyle geometry."""

    def value(name: str, default: Any) -> Any:
        try:
            return entity.dxf.get(name, default)
        except Exception:
            return default

    return (
        int(value("paperspace", 0) or 0),
        str(value("layer", "0") or "0"),
        str(value("linetype", "BYLAYER") or "BYLAYER"),
        int(value("color", 256)),
        (
            int(entity.dxf.true_color)
            if entity.dxf.hasattr("true_color")
            else None
        ),
        (
            str(entity.dxf.color_name)
            if entity.dxf.hasattr("color_name")
            else None
        ),
        (
            int(entity.dxf.transparency)
            if entity.dxf.hasattr("transparency")
            else None
        ),
        int(value("invisible", 0) or 0),
        int(value("lineweight", -1)),
        round(float(value("ltscale", 1.0) or 1.0), 12),
        str(value("material_handle", "") or ""),
        str(value("plotstyle_handle", "") or ""),
        int(value("plotstyle_enum", 0) or 0),
        str(value("visualstyle_handle", "") or ""),
        int(value("shadow_mode", 0) or 0),
    )


def _canonical_dxf_fingerprint_value(value: Any) -> Any:
    """Normalize one persisted DXF namespace value for a stable hash."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return ("float", "nan")
        if math.isinf(value):
            return ("float", "+inf" if value > 0.0 else "-inf")
        return round(value, 12)
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    if isinstance(value, dict):
        return tuple(
            (
                str(key),
                _canonical_dxf_fingerprint_value(item),
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (tuple, list)):
        return tuple(_canonical_dxf_fingerprint_value(item) for item in value)
    try:
        return tuple(_canonical_dxf_fingerprint_value(item) for item in value)
    except (TypeError, ValueError):
        return repr(value)


def _existing_dxf_attribute_record(entity: Any) -> Tuple[Any, ...]:
    """Bind every present DXF attribute except unstable identity/ownership tags."""

    try:
        attributes = dict(entity.dxfattribs())
    except Exception:
        return ()
    entity_type = str(entity.dxftype())
    if entity_type in {"LWPOLYLINE", "POLYLINE"}:
        # ezdxf's writer materializes the absent, default-equivalent group 70.
        attributes.setdefault("flags", 0)
    if entity_type == "POLYLINE":
        # The R12 reader likewise materializes the absent zero elevation.
        attributes.setdefault("elevation", (0.0, 0.0, 0.0))
    if entity_type == "INSERT":
        # The writer omits explicitly stored INSERT defaults. Canonicalize only
        # those exact defaults so non-default transforms and arrays stay bound.
        for name, default in (
            ("xscale", 1.0),
            ("yscale", 1.0),
            ("zscale", 1.0),
            ("rotation", 0.0),
            ("row_spacing", 0.0),
            ("column_spacing", 0.0),
        ):
            try:
                current = float(attributes.get(name, default))
            except (TypeError, ValueError):
                continue
            if current == default:
                attributes[name] = default
        for name in ("row_count", "column_count"):
            try:
                current = int(attributes.get(name, 1))
            except (TypeError, ValueError):
                continue
            if current == 1:
                attributes[name] = 1
    return tuple(
        (str(name), _canonical_dxf_fingerprint_value(value))
        for name, value in sorted(attributes.items(), key=lambda pair: str(pair[0]))
        if str(name) not in {"handle", "owner"}
    )


def _glyph_instance_transform_fingerprint(entities: Sequence[Any]) -> str:
    """Bind every delivery-relevant INSERT attribute to durable evidence."""

    records = []
    for entity in entities:
        if entity.dxftype() != "INSERT":
            return ""
        insert = tuple(
            round(float(value), 12) for value in tuple(entity.dxf.insert)[:3]
        )
        records.append(
            (
                str(entity.dxf.name),
                insert,
                round(float(entity.dxf.xscale or 1.0), 12),
                round(float(entity.dxf.yscale or 1.0), 12),
                round(float(entity.dxf.zscale or 1.0), 12),
                round(float(entity.dxf.rotation or 0.0), 12),
                tuple(
                    round(float(value), 12)
                    for value in tuple(
                        entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
                    )
                ),
                int(entity.dxf.get("row_count", 1)),
                int(entity.dxf.get("column_count", 1)),
                round(float(entity.dxf.get("row_spacing", 0.0) or 0.0), 12),
                round(float(entity.dxf.get("column_spacing", 0.0) or 0.0), 12),
                _entity_visual_attribute_record(entity),
                _existing_dxf_attribute_record(entity),
                str(entity.dxf.get("layer", "0") or "0"),
                int(entity.dxf.get("color", 256)),
                (
                    int(entity.dxf.true_color)
                    if entity.dxf.hasattr("true_color")
                    else None
                ),
                (
                    int(entity.dxf.transparency)
                    if entity.dxf.hasattr("transparency")
                    else None
                ),
                str(entity.dxf.get("linetype", "BYLAYER") or "BYLAYER"),
                int(entity.dxf.get("lineweight", -1)),
                tuple(
                    (
                        str(attrib.dxf.get("tag", "") or ""),
                        str(attrib.dxf.get("text", "") or ""),
                        tuple(
                            round(float(value), 12)
                            for value in tuple(attrib.dxf.insert)
                        ),
                        round(float(attrib.dxf.get("height", 0.0) or 0.0), 12),
                        round(float(attrib.dxf.get("rotation", 0.0) or 0.0), 12),
                        str(attrib.dxf.get("style", "Standard") or "Standard"),
                        str(attrib.dxf.get("layer", "0") or "0"),
                        int(attrib.dxf.get("color", 256)),
                        (
                            int(attrib.dxf.true_color)
                            if attrib.dxf.hasattr("true_color")
                            else None
                        ),
                        _existing_dxf_attribute_record(attrib),
                    )
                    for attrib in getattr(entity, "attribs", ())
                ),
            )
        )
    return hashlib.sha256(repr(tuple(records)).encode("utf-8")).hexdigest()


def _rounded_vector(value: Any) -> Tuple[float, ...]:
    return tuple(round(float(component), 12) for component in tuple(value))


def _glyph_block_header_record(block: Any) -> Tuple[Any, ...]:
    """Normalize rendering/reference-relevant BLOCK/BLOCK_RECORD header state."""

    header = block.block
    record = block.block_record

    def header_value(name: str, default: Any) -> Any:
        try:
            return header.dxf.get(name, default)
        except Exception:
            return default

    def record_value(name: str, default: Any) -> Any:
        try:
            return record.dxf.get(name, default)
        except Exception:
            return default

    layout = str(record_value("layout", "") or "")
    normalized_layout = "" if layout in {"", "0"} else layout
    return (
        str(block.name),
        str(header_value("name", "") or ""),
        _rounded_vector(header.dxf.base_point),
        int(header_value("flags", 0) or 0),
        str(header_value("xref_path", "") or ""),
        str(header_value("description", "") or ""),
        str(header_value("layer", "0") or "0"),
        int(header_value("paperspace", 0) or 0),
        str(record_value("name", "") or ""),
        int(record_value("units", 0) or 0),
        int(record_value("explode", 1)),
        int(record_value("scale", 0) or 0),
        normalized_layout,
    )


def _glyph_outer_block_structure_fingerprint(block: Any) -> str:
    """Hash the outer BLOCK header and its ordered nested INSERT structures."""

    children = list(block)
    payload = (
        _glyph_block_header_record(block),
        tuple(entity.dxftype() for entity in children),
        _glyph_instance_transform_fingerprint(children),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def _glyph_definition_geometry_fingerprint(block: Any) -> str:
    """Hash ordered persisted geometry and visual attributes without handles."""

    header_record = _glyph_block_header_record(block)
    records = []
    for entity in block:
        entity_type = entity.dxftype()
        visual_attributes = (
            _entity_visual_attribute_record(entity),
            _existing_dxf_attribute_record(entity),
            str(entity.dxf.get("layer", "0") or "0"),
            int(entity.dxf.get("color", 256)),
            (
                int(entity.dxf.true_color)
                if entity.dxf.hasattr("true_color")
                else None
            ),
            str(entity.dxf.get("linetype", "BYLAYER") or "BYLAYER"),
            int(entity.dxf.get("lineweight", -1)),
            round(float(entity.dxf.get("thickness", 0.0) or 0.0), 12),
            _rounded_vector(
                entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
            ),
        )
        if entity_type == "LWPOLYLINE":
            geometry = (
                int(entity.dxf.get("flags", 0) or 0),
                round(float(entity.dxf.get("elevation", 0.0) or 0.0), 12),
                _rounded_vector(
                    entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
                ),
                tuple(
                    tuple(round(float(value), 12) for value in point)
                    for point in entity.get_points(format="xyseb")
                ),
            )
        elif entity_type == "POLYLINE":
            geometry = (
                int(entity.dxf.get("flags", 0) or 0),
                _rounded_vector(
                    entity.dxf.get("elevation", (0.0, 0.0, 0.0))
                ),
                _rounded_vector(
                    entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
                ),
                tuple(
                    (
                        _rounded_vector(vertex.dxf.location),
                        round(float(vertex.dxf.get("start_width", 0.0) or 0.0), 12),
                        round(float(vertex.dxf.get("end_width", 0.0) or 0.0), 12),
                        round(float(vertex.dxf.get("bulge", 0.0) or 0.0), 12),
                        _existing_dxf_attribute_record(vertex),
                    )
                    for vertex in entity.vertices
                ),
            )
        elif entity_type == "SOLID":
            geometry = tuple(
                _rounded_vector(entity.dxf.get(name, (0.0, 0.0, 0.0)))
                for name in ("vtx0", "vtx1", "vtx2", "vtx3")
            )
        else:
            geometry = ("unsupported",)
        records.append((entity_type, visual_attributes, geometry))
    return hashlib.sha256(
        repr((header_record, tuple(records))).encode("utf-8")
    ).hexdigest()


def _nested_outline_tolerance(
    entities: Sequence[Any],
    expected_bbox: Optional[Sequence[float]],
) -> Tuple[float, float]:
    """Project local definition sagitta onto world X/Y plus roundoff."""

    tolerance_x = 0.0
    tolerance_y = 0.0
    for entity in entities:
        if entity.dxftype() != "INSERT":
            continue
        xscale = abs(float(entity.dxf.xscale or 1.0))
        yscale = abs(float(entity.dxf.yscale or 1.0))
        angle = math.radians(float(entity.dxf.rotation or 0.0))
        cosine = abs(math.cos(angle))
        sine = abs(math.sin(angle))
        tolerance_x = max(
            tolerance_x,
            0.01 * (cosine * xscale + sine * yscale),
        )
        tolerance_y = max(
            tolerance_y,
            0.01 * (sine * xscale + cosine * yscale),
        )
    bbox_values = tuple(float(value) for value in expected_bbox or ())
    magnitude_x = max(
        (abs(bbox_values[index]) for index in (0, 2) if index < len(bbox_values)),
        default=1.0,
    )
    magnitude_y = max(
        (abs(bbox_values[index]) for index in (1, 3) if index < len(bbox_values)),
        default=1.0,
    )
    return (
        tolerance_x + max(1.0, magnitude_x) * 1e-12,
        tolerance_y + max(1.0, magnitude_y) * 1e-12,
    )


def _path_bbox_tuple(
    paths: Sequence[Any],
) -> Optional[Tuple[float, float, float, float]]:
    box = ezdxf_path.bbox(paths, fast=False)
    if not box.has_data:
        return None
    return (
        float(box.extmin.x),
        float(box.extmin.y),
        float(box.extmax.x),
        float(box.extmax.y),
    )


def _exact_font_cache_identity(
    entity: Any,
    resolution: _ExactFontResolution,
) -> Tuple[str, ...]:
    """Identify the exact font program, never only its reported family name."""

    try:
        style = entity.doc.styles.get(str(entity.dxf.style or ""))
        style_font = str(style.dxf.get("font", "") or "")
        style_bigfont = str(style.dxf.get("bigfont", "") or "")
    except Exception:
        style_font = ""
        style_bigfont = ""
    return (
        str(resolution.asset_sha256 or resolution.source_sha256 or "").lower(),
        str(resolution.asset_id or ""),
        str(resolution.filename or "").replace("\\", "/").lower(),
        style_font.replace("\\", "/").lower(),
        style_bigfont.replace("\\", "/").lower(),
        str(resolution.family or "").lower(),
        str(resolution.style or "").lower(),
        str(resolution.resolution_source or "").lower(),
    )


def _source_outline_bbox_key(
    entity: Any,
    font_identity: Tuple[str, ...],
) -> Tuple[Any, ...]:
    """Capture every source TEXT field that can change text2path geometry."""

    return (
        font_identity,
        str(entity.plain_text()),
        str(entity.font_name()),
        float(entity.dxf.height or 0.0),
        float(entity.dxf.get("width", 1.0) or 1.0),
        float(entity.dxf.get("rotation", 0.0) or 0.0),
        float(entity.dxf.get("oblique", 0.0) or 0.0),
        int(entity.dxf.get("halign", 0) or 0),
        int(entity.dxf.get("valign", 0) or 0),
        int(entity.dxf.get("text_generation_flag", 0) or 0),
        tuple(float(value) for value in tuple(entity.dxf.insert)),
        tuple(
            float(value)
            for value in tuple(
                entity.dxf.get("align_point", (0.0, 0.0, 0.0))
            )
        ),
        tuple(
            float(value)
            for value in tuple(entity.dxf.get("extrusion", (0.0, 0.0, 1.0)))
        ),
    )


def _source_outline_bbox(
    entity: Any,
    font_identity: Tuple[str, ...],
) -> Optional[Tuple[float, float, float, float]]:
    cache_key = _source_outline_bbox_key(entity, font_identity)
    if cache_key not in _source_outline_bbox_cache:
        paths = text2path.make_paths_from_entity(entity)
        _source_outline_bbox_cache[cache_key] = _path_bbox_tuple(paths)
    return _source_outline_bbox_cache[cache_key]


def _definition_scale_for_transform(xscale: float, yscale: float) -> float:
    """Keep nested scaling at or below one so tessellation never gets coarser."""

    largest = max(abs(float(xscale)), abs(float(yscale)))
    if not math.isfinite(largest) or largest <= 0.0:
        raise ValueError("glyph transform scale is invalid")
    if largest <= 1.0:
        return 1.0
    return float(2 ** math.ceil(math.log2(largest)))


def _decompose_nested_transform(matrix: Matrix44) -> Tuple[float, float, float]:
    """Return DXF INSERT x/y scales and rotation for an orthogonal 2D matrix."""

    x_axis = matrix.transform_direction((1.0, 0.0, 0.0))
    y_axis = matrix.transform_direction((0.0, 1.0, 0.0))
    xscale = math.hypot(float(x_axis.x), float(x_axis.y))
    yscale = math.hypot(float(y_axis.x), float(y_axis.y))
    if xscale <= 0.0 or yscale <= 0.0:
        raise ValueError("glyph transform has a zero scale")
    dot = float(x_axis.x) * float(y_axis.x) + float(x_axis.y) * float(y_axis.y)
    tolerance = max(1.0, xscale * yscale) * 1e-10
    if not math.isclose(dot, 0.0, rel_tol=0.0, abs_tol=tolerance):
        raise ValueError("glyph transform contains unsupported shear")
    determinant = (
        float(x_axis.x) * float(y_axis.y)
        - float(x_axis.y) * float(y_axis.x)
    )
    if determinant <= 0.0:
        raise ValueError("glyph transform contains unsupported reflection")
    rotation = math.degrees(math.atan2(float(x_axis.y), float(x_axis.x)))
    return xscale, yscale, rotation


def _nested_glyph_geometry_from_entity(
    entity: Any,
    *,
    font_identity: Tuple[str, ...],
    is_r12: bool,
    attribs: Dict[str, Any],
) -> _NestedGlyphRun:
    """Reproduce ezdxf's text path transform as reusable per-glyph INSERTs."""

    content = str(entity.plain_text())
    height = _positive_finite(entity.dxf.height)
    if height is None:
        raise ValueError("glyph source height is invalid")
    face = ezdxf_fonts.get_font_face(entity.font_name())
    font = text2path.get_font(face)
    font_key = font_identity
    run_unit_paths = font.text_glyph_paths(content, 1.0, 1.0)
    canonical_unit_paths: List[Tuple[str, Any]] = []
    canonical_created_count = 0
    canonical_reused_count = 0
    for character in content:
        canonical_key = (font_key, character)
        if canonical_key not in _canonical_glyph_path_cache:
            character_paths = font.text_glyph_paths(character, 1.0, 1.0)
            _canonical_glyph_path_cache[canonical_key] = (
                character_paths[0] if character_paths else None
            )
            canonical_created_count += 1
        else:
            canonical_reused_count += 1
        canonical_path = _canonical_glyph_path_cache[canonical_key]
        if canonical_path is not None:
            canonical_unit_paths.append((character, canonical_path))
    if len(run_unit_paths) != len(canonical_unit_paths):
        raise ValueError("glyph path decomposition lost a visible character")
    if not run_unit_paths:
        return _NestedGlyphRun(
            geometries=[],
            canonical_created_count=canonical_created_count,
            canonical_reused_count=canonical_reused_count,
        )

    sized_path = font.text_path_ex(content, height, 1.0)
    sized_box = ezdxf_path.bbox([sized_path.to_path()], fast=True)
    measurements = font.measurements.scale_from_baseline(height)
    alignment = text2path.alignment_transformation(
        measurements,
        sized_box,
        entity.get_align_enum(),
        entity.fit_length(),
    )
    transform = Matrix44.scale(height, height, 1.0)
    transform *= alignment
    transform *= entity.wcs_transformation_matrix()
    xscale, yscale, rotation = _decompose_nested_transform(transform)
    definition_scale = _definition_scale_for_transform(xscale, yscale)
    nested_xscale = xscale / definition_scale
    nested_yscale = yscale / definition_scale
    attribute_record = tuple(
        (str(key), repr(value)) for key, value in sorted(attribs.items())
    )

    geometries: List[_NestedGlyphGeometry] = []
    for run_path, (character, canonical_path) in zip(
        run_unit_paths,
        canonical_unit_paths,
        strict=True,
    ):
        run_start = run_path.start
        canonical_start = canonical_path.start
        unit_offset = (
            float(run_start.x) - float(canonical_start.x),
            float(run_start.y) - float(canonical_start.y),
            0.0,
        )
        insertion_point = transform.transform(unit_offset)
        scaled_cache_key = (
            font_key,
            character,
            round(definition_scale, 12),
            bool(is_r12),
            attribute_record,
        )
        cached_geometry = _scaled_glyph_geometry_cache.get(scaled_cache_key)
        if cached_geometry is None:
            definition_path = canonical_path.clone()
            definition_path.transform_inplace(
                Matrix44.scale(definition_scale, definition_scale, 1.0)
            )
            paths = list(definition_path.to_path().sub_paths())
            fingerprint = _path_geometry_fingerprint(
                paths,
                is_r12=is_r12,
                attribs=attribs,
            )
            _scaled_glyph_geometry_cache[scaled_cache_key] = (paths, fingerprint)
        else:
            paths, fingerprint = cached_geometry
        geometries.append(
            _NestedGlyphGeometry(
                insertion=(float(insertion_point.x), float(insertion_point.y)),
                xscale=nested_xscale,
                yscale=nested_yscale,
                rotation=rotation,
                paths=paths,
                attribs=dict(attribs),
                fingerprint=fingerprint,
            )
        )
    return _NestedGlyphRun(
        geometries=geometries,
        canonical_created_count=canonical_created_count,
        canonical_reused_count=canonical_reused_count,
    )


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


def _unique_glyph_definition_name(
    doc: ezdxf.document.Drawing,
    fingerprint: str,
) -> str:
    base = f"BCS_GDEF_{fingerprint[:32]}"
    candidate = base
    suffix = 1
    while candidate in doc.blocks:
        suffix += 1
        candidate = f"{base[:245]}_{suffix}"
    return candidate


def _add_nested_glyph_definitions(
    attempt: TextDeliveryAttempt,
    outer_block: Any,
    geometries: Sequence[_NestedGlyphGeometry],
    *,
    is_r12: bool,
    block_attribs: Dict[str, Any],
) -> Tuple[List[Any], int, int, List[str], List[str], Dict[str, str], int, bool]:
    """Populate one span block with references to shared glyph definitions."""

    doc = outer_block.doc
    doc_block_cache = _glyph_block_cache.setdefault(doc, {})
    doc_fingerprint_cache = _glyph_definition_fingerprint_cache.setdefault(doc, {})
    definition_blocks: List[Any] = []
    definition_names: List[str] = []
    definition_fingerprints: Dict[str, str] = {}
    created_count = 0
    reused_count = 0
    support_handles: List[str] = []
    for geometry in geometries:
        cache_key = (bool(is_r12), geometry.fingerprint)
        block_name = doc_block_cache.get(cache_key, "")
        if block_name and block_name not in doc.blocks:
            doc_block_cache.pop(cache_key, None)
            block_name = ""
        if block_name:
            definition = doc.blocks.get(block_name)
            reused_count += 1
            if block_name not in attempt.owned_block_names:
                referenced = _block_structure_handles(
                    definition,
                    include_block_record=not is_r12,
                ) + [_handle(entity) for entity in definition]
                attempt.referenced_entity_handles.extend(
                    handle
                    for handle in referenced
                    if handle and handle not in attempt.referenced_entity_handles
                )
        else:
            block_name = _unique_glyph_definition_name(doc, geometry.fingerprint)
            definition = doc.blocks.new(name=block_name)
            doc_block_cache[cache_key] = block_name
            attempt.owned_block_names.append(block_name)
            definition_support = _block_structure_handles(
                definition,
                include_block_record=not is_r12,
            )
            attempt.created_entity_handles.extend(definition_support)
            outlines = _to_outline_entities(
                geometry.paths,
                is_r12=is_r12,
                attribs=geometry.attribs,
            )
            fills = _to_solid_fill_entities(
                geometry.paths,
                is_r12=is_r12,
                attribs=geometry.attribs,
            )
            if not outlines or not _solid_fill_verified(fills, is_r12=is_r12):
                raise ValueError("shared glyph definition is not visibly complete")
            for entity in outlines + fills:
                definition.add_entity(entity)
                handle = _handle(entity)
                attempt.created_entity_handles.append(handle)
                definition_support.append(handle)
            support_handles.extend(definition_support)
            created_count += 1
        definition_blocks.append(definition)
        definition_names.append(block_name)
        definition_fingerprint = doc_fingerprint_cache.get(block_name)
        if not definition_fingerprint:
            definition_fingerprint = _glyph_definition_geometry_fingerprint(definition)
            doc_fingerprint_cache[block_name] = definition_fingerprint
        definition_fingerprints[block_name] = definition_fingerprint
        nested_attribs = {
            **block_attribs,
            "xscale": geometry.xscale,
            "yscale": geometry.yscale,
            "rotation": geometry.rotation,
        }
        nested_ref = outer_block.add_blockref(
            block_name,
            geometry.insertion,
            dxfattribs=nested_attribs,
        )
        nested_handle = _handle(nested_ref)
        attempt.created_entity_handles.append(nested_handle)
        support_handles.append(nested_handle)
    unique_definitions = {
        name: definition
        for name, definition in zip(definition_names, definition_blocks, strict=True)
    }
    definition_fills = [
        entity
        for definition in unique_definitions.values()
        for entity in definition
        if entity.dxftype() == "SOLID"
    ]
    return (
        definition_blocks,
        created_count,
        reused_count,
        support_handles,
        definition_names,
        definition_fingerprints,
        len(definition_fills),
        _solid_fill_verified(definition_fills, is_r12=is_r12),
    )


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
    glyph_geometries: Optional[Sequence[_NestedGlyphGeometry]] = None,
) -> None:
    doc = msp.doc
    nested_glyphs = bool(glyph_geometries)
    if not outlines and not nested_glyphs:
        raise ValueError("outline strategy returned zero entities")
    fill_verified = (
        True if nested_glyphs else _solid_fill_verified(fills, is_r12=is_r12)
    )
    attempt.evidence.update(
        {
            "solid_fill_entity_type": "SOLID",
            "solid_fill_entity_count": 0 if nested_glyphs else len(fills),
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

    if outlines:
        block_attribs: Dict[str, Any] = {
            "layer": str(outlines[0].dxf.layer or "0"),
        }
        outline_true_color = (
            int(outlines[0].dxf.true_color)
            if outlines[0].dxf.hasattr("true_color")
            else None
        )
        outline_color = (
            int(outlines[0].dxf.color)
            if outlines[0].dxf.hasattr("color")
            else None
        )
    else:
        glyph_attribs = dict(glyph_geometries[0].attribs)  # type: ignore[index]
        block_attribs = {"layer": str(glyph_attribs.get("layer") or "0")}
        outline_true_color = glyph_attribs.get("true_color")
        outline_color = glyph_attribs.get("color")
    # LibreCAD resolves a block reference's display color before child entity
    # true-color in several export/render paths.  Carry the exact source color
    # on both the glyph children and their parent INSERT so a blue source glyph
    # cannot reopen or print as black.
    if outline_true_color is not None:
        block_attribs["true_color"] = int(outline_true_color)
    if outline_color is not None:
        block_attribs["color"] = int(outline_color)
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
    definition_blocks: List[Any] = []
    definition_created_count = 0
    definition_reused_count = 0
    definition_names: List[str] = []
    definition_fingerprints: Dict[str, str] = {}
    nested_support: List[str] = []
    definition_fill_count = 0
    if glyph_geometries:
        (
            definition_blocks,
            definition_created_count,
            definition_reused_count,
            nested_support,
            definition_names,
            definition_fingerprints,
            definition_fill_count,
            fill_verified,
        ) = _add_nested_glyph_definitions(
            attempt,
            block,
            glyph_geometries,
            is_r12=is_r12,
            block_attribs=block_attribs,
        )
        attempt.owned_block_names.remove(block_name)
        attempt.owned_block_names.append(block_name)
        attempt.evidence.update(
            {
                "solid_fill_entity_count": definition_fill_count,
                "solid_fill_verified": fill_verified,
            }
        )
        if not fill_verified:
            raise ValueError("shared glyph definitions lost verified solid fill")
    else:
        for entity in outlines + fills:
            block.add_entity(entity)
            attempt.created_entity_handles.append(_handle(entity))
    block_ref = msp.add_blockref(
        block_name,
        insertion,
        dxfattribs=block_attribs,
    )
    attempt.created_entity_handles.append(_handle(block_ref))
    attempt.entity_handles = [_handle(block_ref)]
    attempt.support_entity_handles = block_structure_handles + nested_support
    if not glyph_geometries:
        attempt.support_entity_handles.extend(
            _handle(entity) for entity in outlines + fills
        )
    if glyph_geometries:
        from ezdxf.disassemble import recursive_decompose

        resolved_outlines = [
            entity
            for entity in recursive_decompose([block_ref])
            if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
        ]
        resolved_bbox = _bbox_tuple(resolved_outlines)
    else:
        resolved_bbox = None
    actual_bbox = (
        (
            resolved_bbox[0] - insertion[0],
            resolved_bbox[1] - insertion[1],
            resolved_bbox[2] - insertion[0],
            resolved_bbox[3] - insertion[1],
        )
        if resolved_bbox is not None
        else _bbox_tuple(outlines)
    )
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
        and (
            all(entity.dxftype() == "INSERT" for entity in block)
            and all(
                entity.dxftype() in {"LWPOLYLINE", "POLYLINE", "SOLID"}
                for definition in definition_blocks
                for entity in definition
            )
            if glyph_geometries
            else all(
                entity.dxftype() in {"LWPOLYLINE", "POLYLINE", "SOLID"}
                for entity in block
            )
        )
        and fill_verified
    )
    bbox_errors = (
        tuple(
            abs(float(left) - float(right))
            for left, right in zip(expected_bbox, actual_bbox, strict=True)
        )
        if expected_bbox is not None and actual_bbox is not None
        else ()
    )
    bbox_error = max(bbox_errors, default=math.inf)
    bbox_tolerance = (
        _nested_outline_tolerance(list(block), expected_bbox)
        if glyph_geometries
        else None
    )
    bbox_verified = (
        bool(
            len(bbox_errors) == 4
            and bbox_errors[0] <= bbox_tolerance[0]
            and bbox_errors[2] <= bbox_tolerance[0]
            and bbox_errors[1] <= bbox_tolerance[1]
            and bbox_errors[3] <= bbox_tolerance[1]
        )
        if bbox_tolerance is not None
        else _bbox_matches(expected_bbox, actual_bbox)
    )
    attempt.visual_verified = bool(
        insert_verified
        and insert_color_verified
        and bbox_verified
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
            "nested_glyph_definitions": bool(glyph_geometries),
            "glyph_instance_count": len(glyph_geometries or []),
            "glyph_definition_created_count": definition_created_count,
            "glyph_definition_reused_count": definition_reused_count,
            "glyph_definition_names": sorted(set(definition_names)),
            "glyph_definition_geometry_sha256": definition_fingerprints,
            "glyph_outer_block_structure_sha256": (
                _glyph_outer_block_structure_fingerprint(block)
                if glyph_geometries
                else None
            ),
            "glyph_outer_insert_sha256": (
                _glyph_instance_transform_fingerprint([block_ref])
                if glyph_geometries
                else None
            ),
            "glyph_instance_transform_sha256": (
                _glyph_instance_transform_fingerprint(list(block))
                if glyph_geometries
                else None
            ),
            "outline_bbox_max_abs_error": bbox_error,
            "outline_bbox_tessellation_tolerance": (
                list(bbox_tolerance) if bbox_tolerance is not None else None
            ),
            "outline_bbox_verified": bbox_verified,
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
    deleted_block_names: set[str] = set()
    for block_name in reversed(attempt.owned_block_names):
        block = doc.blocks.get(block_name)
        child_handles = (
            _block_structure_handles(block) + [_handle(entity) for entity in block]
            if block is not None
            else []
        )
        if _delete_block(doc, block_name):
            deleted_block_names.add(block_name)
            attempt.removed_entity_handles.extend(
                handle
                for handle in child_handles
                if handle in attempt.created_entity_handles
                and handle not in attempt.removed_entity_handles
            )
    doc_block_cache = _glyph_block_cache.get(doc)
    if doc_block_cache is not None:
        for cache_key, block_name in list(doc_block_cache.items()):
            if block_name in deleted_block_names:
                doc_block_cache.pop(cache_key, None)
    doc_fingerprint_cache = _glyph_definition_fingerprint_cache.get(doc)
    if doc_fingerprint_cache is not None:
        for block_name in deleted_block_names:
            doc_fingerprint_cache.pop(block_name, None)
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
        font_cache_identity = _exact_font_cache_identity(source, font_resolution)
        glyph_run = (
            _nested_glyph_geometry_from_entity(
                source,
                font_identity=font_cache_identity,
                is_r12=is_r12,
                attribs=_outline_attributes(attribs),
            )
            if representation == "glyphs"
            else None
        )
        glyph_geometries = glyph_run.geometries if glyph_run else None
        if glyph_run is not None:
            attempt.evidence.update(
                {
                    "canonical_glyph_created_count": (
                        glyph_run.canonical_created_count
                    ),
                    "canonical_glyph_reused_count": (
                        glyph_run.canonical_reused_count
                    ),
                }
            )
            expected_bbox = _source_outline_bbox(source, font_cache_identity)
            outlines: List[Any] = []
            fills: List[Any] = []
        else:
            paths = text2path.make_paths_from_entity(source)
            outlines = _to_outline_entities(
                paths,
                is_r12=is_r12,
                attribs=_outline_attributes(attribs),
            )
            fills = _to_solid_fill_entities(
                paths,
                is_r12=is_r12,
                attribs=_outline_attributes(attribs),
            )
            expected_bbox = _bbox_tuple(outlines)
        if expected_bbox is None and str(text_item.text) and not str(text_item.text).strip():
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
        if expected_bbox is None:
            attempt.evidence.update(
                {
                    "visible_ink_expected": True,
                    "zero_outline_result_verified": False,
                    "item_specific_creation_attempted": True,
                }
            )
            raise ValueError(
                "non-whitespace outline source produced no visible geometry"
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
            expected_bbox=expected_bbox,
            is_r12=is_r12,
            glyph_geometries=glyph_geometries,
        )
        if not attempt.type_verified:
            raise ValueError("outline delivery failed type verification")
        if not attempt.visual_verified:
            # Same split as native text: a correctly built outline that still
            # does not match the source proves this rung cannot carry the
            # item, so descend rather than abort the whole import.
            raise _RepresentationImpossible(
                "outline delivery does not reproduce the source appearance "
                "of this item"
            )
        attempt.delivery_verified = True
        attempt.outcome = "verified"
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        if not attempt.cleanup_verified:
            raise ValueError("outline ownership verification failed")
        return attempt
    except Exception as exc:
        attempt.delivery_verified = False
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
        if not attempt.type_verified:
            raise ValueError("outline delivery failed type verification")
        if not attempt.visual_verified:
            # Same split as native text: a correctly built outline that still
            # does not match the source proves this rung cannot carry the
            # item, so descend rather than abort the whole import.
            raise _RepresentationImpossible(
                "outline delivery does not reproduce the source appearance "
                "of this item"
            )
        attempt.delivery_verified = True
        attempt.outcome = "verified"
        attempt.cleanup_verified = _verify_owned_state(doc, attempt)
        if not attempt.cleanup_verified:
            raise ValueError("outline ownership verification failed")
        return attempt
    except Exception as exc:
        attempt.delivery_verified = False
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
    librecad_executable: Optional[str],
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
                librecad_executable=librecad_executable,
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
                librecad_executable=librecad_executable,
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
                librecad_executable=librecad_executable,
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
    librecad_executable: Optional[str] = None,
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
        librecad_executable=librecad_executable,
        dxf_version=dxf_version,
    )
    if return_delivery_result:
        return result
    if return_delivered_kind:
        return result.delivered_kind, result.count
    return result.count


def reset_text_styles() -> None:
    """Clear per-document text-style and embedded-font caches."""
    global _style_counter  # noqa: PLW0603
    _created_styles.clear()
    _embedded_cap_height_cache.clear()
    _staged_font_verification_cache.clear()
    _glyph_block_cache.clear()
    _canonical_glyph_path_cache.clear()
    _scaled_glyph_geometry_cache.clear()
    _source_outline_bbox_cache.clear()
    _glyph_definition_fingerprint_cache.clear()
    _librecad_lff_cache.clear()
    _style_counter = 0


__all__ = [
    "TextDeliveryAttempt",
    "TextDeliveryResult",
    "build_text",
    "reset_text_styles",
]

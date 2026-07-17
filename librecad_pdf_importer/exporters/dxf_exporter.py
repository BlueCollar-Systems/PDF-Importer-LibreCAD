"""DXF export adapter for LibreCAD workflows."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
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
    build_text,
    reset_text_styles,
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


def _verify_serialized_text_deliveries(
    doc: Any,
    deliveries: List[Dict[str, Any]],
) -> None:
    """Reconcile accepted item evidence against the re-opened DXF candidate."""

    expected_types = {
        "text": {"TEXT"},
        "labels": {"TEXT", "MTEXT"},
        "glyphs": {"INSERT"},
        "geometry": {"LWPOLYLINE", "POLYLINE", "SOLID"},
        "raster": {"IMAGE"},
        "3d_text": {"TEXT"},
    }
    source_ids: set[str] = set()
    main_handles: set[str] = set()
    for delivery in deliveries:
        source_id = str(delivery.get("source_id") or "")
        representation = str(delivery.get("final_representation") or "")
        if not source_id or source_id in source_ids:
            raise RuntimeError(
                f"serialized text delivery has invalid or duplicate source id: {source_id!r}"
            )
        source_ids.add(source_id)
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
        if set(map(str, final_attempt.get("entity_handles") or [])) != set(
            entity_handles
        ) or set(map(str, final_attempt.get("support_entity_handles") or [])) != set(
            support_handles
        ):
            raise RuntimeError(
                f"serialized text delivery {source_id}: attempt handles disagree"
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

        if representation == "glyphs":
            support_set = set(support_handles)
            for insert in entities:
                try:
                    block = doc.blocks.get(str(insert.dxf.name))
                except Exception as exc:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph block missing"
                    ) from exc
                exact_support = {
                    str(value.dxf.handle or "")
                    for value in (
                        *(() if doc.dxfversion == "AC1009" else (block.block_record,)),
                        block.block,
                        block.endblk,
                        *list(block),
                    )
                    if str(value.dxf.handle or "")
                }
                if exact_support != support_set:
                    raise RuntimeError(
                        f"serialized text delivery {source_id}: glyph support mismatch"
                    )

        if representation == "raster":
            evidence = dict(final_attempt.get("evidence") or {})
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
    insert: Tuple[float, float]
    size_in_units: Tuple[float, float]
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

        actual_insert = tuple(image.dxf.insert)[:2]
        actual_width = math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y) * float(
            image.dxf.image_size.x
        )
        actual_height = math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y) * float(
            image.dxf.image_size.y
        )
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
) -> Tuple[TextDeliveryResult, Optional[_PendingRasterAsset]]:
    """Attempt a real item crop as requested or after proven structural failure."""
    attempts = list(delivery.attempts)
    for prior in attempts:
        prior.superseded = True
    attempt = TextDeliveryAttempt(
        source_id=delivery.source_id,
        requested_representation=delivery.requested_representation,
        attempted_representation="raster",
        strategy="pymupdf_item_clip",
    )
    attempts.append(attempt)
    doc = msp.doc
    image = None
    image_def = None
    support_handles: List[str] = []
    try:
        if not delivery.source_id:
            raise ValueError("terminal raster has no stable source identity")
        if not str(getattr(source_text, "text", "") or "").strip():
            raise ValueError(
                "terminal raster cannot certify a whitespace-only source item "
                "from unrelated page ink"
            )
        source_bbox = getattr(source_text, "source_bbox_pdf", None)
        placed_bbox = getattr(placed_text, "bbox", None)
        if not source_bbox or len(source_bbox) < 4 or not placed_bbox or len(placed_bbox) < 4:
            raise ValueError("terminal raster requires an exact source item bbox")
        sx0, sy0, sx1, sy1 = [float(value) for value in source_bbox[:4]]
        px0, py0, px1, py1 = [float(value) for value in placed_bbox[:4]]
        source_width = abs(sx1 - sx0)
        source_height = abs(sy1 - sy0)
        placed_width = abs(px1 - px0)
        placed_height = abs(py1 - py0)
        if min(source_width, source_height, placed_width, placed_height) <= 0.0:
            raise ValueError("terminal raster source item bbox is empty")

        with fitz.open(extraction.pdf_path) as source_doc:
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
            ):
                raise ValueError(
                    "terminal raster source bbox is not fully contained by the source page"
                )
            dpi = max(72, int(raster_dpi or 300))
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0),
                clip=clip,
                alpha=True,
            )
            png = bytes(pixmap.tobytes("png"))

        if pixmap.width <= 0 or pixmap.height <= 0:
            raise ValueError("terminal raster rendered zero pixels")
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("terminal raster output is not a PNG")
        if not _pixmap_contains_ink(pixmap):
            raise ValueError("terminal raster crop contains no visible source ink")

        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", delivery.source_id)
        asset_path = asset_root / f"{safe_id}.png"
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
        attempt.type_verified = image.dxftype() == "IMAGE"
        attempt.visual_verified = insert_ok and size_ok
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
            "source_to_display_rotation": [float(value) for value in rotation_matrix],
            "target_bbox_model": [
                min(px0, px1),
                min(py0, py1),
                max(px0, px1),
                max(py0, py1),
            ],
            "pixel_size": [int(pixmap.width), int(pixmap.height)],
            "visible_ink_verified": True,
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
            text_cfg = ImportConfig.auto()
            text_cfg.text_mode = opts.text_mode
            text_cfg._embedded_font_asset_paths = dict(embedded_font_paths)  # noqa: B010
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
                insert = (float(placement.x_mm), float(placement.y_mm) + dy)
                size_in_units = (
                    float(placement.width_mm),
                    float(placement.height_mm),
                )
                image = msp.add_image(
                    image_def,
                    insert=insert,
                    size_in_units=size_in_units,
                    dxfattribs={"layer": layer},
                )
                image.dxf.flags = int(image.dxf.flags or 0) | 8
                serialized_image_expectations.append(
                    _SerializedImageExpectation(
                        image_handle=str(image.dxf.handle or ""),
                        image_def_handle=str(image_def.dxf.handle or ""),
                        asset_path=staged_asset.path,
                        asset_sha256=staged_asset.sha256,
                        insert=insert,
                        size_in_units=size_in_units,
                        size_in_pixel=staged_asset.size_px,
                    )
                )
                _track_xy(float(placement.x_mm), float(placement.y_mm) + dy)
                _track_xy(float(placement.x_mm + placement.width_mm), float(placement.y_mm + placement.height_mm) + dy)
                entity_count += 1
                image_count += 1

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
        _verify_serialized_text_deliveries(candidate, text_deliveries)
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

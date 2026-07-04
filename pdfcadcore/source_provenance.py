# -*- coding: utf-8 -*-
"""Minimal source provenance sidecar builder (bcs.source_provenance/1.0)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "bcs.source_provenance/1.0"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_import_session_id() -> str:
    return str(uuid.uuid4())


@dataclass
class SourceProvenanceObject:
    object_id: str
    page: int
    source_kind: str
    created_entity_type: str
    parent_handle: str = ""
    ocg_layer: str = ""
    source_bbox_pdf: Optional[List[float]] = None
    target_bbox_model: Optional[List[float]] = None
    selected_import_mode: str = ""
    selected_text_mode: str = ""
    scale_factor: Optional[float] = None
    fallback_reason: str = ""
    span_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if payload.get("span_id") is None:
            payload.pop("span_id", None)
        if not payload.get("parent_handle"):
            payload.pop("parent_handle", None)
        if not payload.get("ocg_layer"):
            payload.pop("ocg_layer", None)
        if not payload.get("selected_import_mode"):
            payload.pop("selected_import_mode", None)
        if not payload.get("selected_text_mode"):
            payload.pop("selected_text_mode", None)
        if payload.get("scale_factor") is None:
            payload.pop("scale_factor", None)
        if not payload.get("fallback_reason"):
            payload.pop("fallback_reason", None)
        if not payload.get("source_bbox_pdf"):
            payload.pop("source_bbox_pdf", None)
        if not payload.get("target_bbox_model"):
            payload.pop("target_bbox_model", None)
        return payload


@dataclass
class SourceProvenanceManifest:
    schema: str = SCHEMA
    import_session_id: str = ""
    importer: Dict[str, str] = field(default_factory=dict)
    source_pdf: Dict[str, Any] = field(default_factory=dict)
    objects: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def write_json(self, output_path: str, indent: int = 2) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=indent, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return str(path)


def ensure_provenance_bucket(opts: Any) -> List[SourceProvenanceObject]:
    bucket = getattr(opts, "_source_provenance_objects", None)
    if bucket is None:
        bucket = []
        setattr(opts, "_source_provenance_objects", bucket)
    return bucket


def ensure_import_session_id(opts: Any) -> str:
    session_id = str(getattr(opts, "_import_session_id", "") or "").strip()
    if not session_id:
        session_id = new_import_session_id()
        setattr(opts, "_import_session_id", session_id)
    return session_id


def _span_bbox_pdf(span: Dict[str, Any]) -> Optional[List[float]]:
    bbox = span.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    origin = span.get("origin")
    if isinstance(origin, (list, tuple)) and len(origin) >= 2:
        x = float(origin[0])
        y = float(origin[1])
        size = float(span.get("size", 0.0) or 0.0)
        width = max(size * max(len(str(span.get("text") or "")), 1) * 0.5, 1.0)
        return [x, y, x + width, y + size]
    return None


def record_text_span_provenance(
    opts: Any,
    *,
    page: int,
    span: Dict[str, Any],
    text: str,
    created_entity_type: str,
    parent_handle: str = "",
    import_mode: str = "",
    text_mode: str = "",
    span_index: Optional[int] = None,
) -> None:
    """Record one created label/text object back to its PDF span."""
    bucket = ensure_provenance_bucket(opts)
    index = span_index if span_index is not None else len(bucket)
    entry = SourceProvenanceObject(
        object_id=f"text_span:{page}:{index}",
        page=int(page),
        source_kind="text_span",
        created_entity_type=str(created_entity_type),
        parent_handle=str(parent_handle or ""),
        source_bbox_pdf=_span_bbox_pdf(span),
        selected_import_mode=str(import_mode or getattr(opts, "import_mode", "") or ""),
        selected_text_mode=str(text_mode or getattr(opts, "text_mode", "") or ""),
        span_id=index,
    )
    bucket.append(entry)


def build_source_provenance(
    *,
    import_session_id: str,
    pdf_path: str,
    objects: List[SourceProvenanceObject],
    host_app: str,
    importer_version: str = "",
    build_stamp: str = "",
    page_count: Optional[int] = None,
) -> SourceProvenanceManifest:
    source_pdf: Dict[str, Any] = {"path": str(pdf_path)}
    if pdf_path and Path(pdf_path).is_file():
        source_pdf["sha256"] = _sha256_file(pdf_path)
    if page_count is not None and page_count > 0:
        source_pdf["page_count"] = int(page_count)

    importer: Dict[str, str] = {"name": str(host_app)}
    if importer_version:
        importer["version"] = str(importer_version)
    if build_stamp:
        importer["build"] = str(build_stamp)

    return SourceProvenanceManifest(
        import_session_id=str(import_session_id),
        importer=importer,
        source_pdf=source_pdf,
        objects=[item.to_dict() for item in objects],
    )


def write_source_provenance_sidecar(
    *,
    output_path: str,
    import_session_id: str,
    pdf_path: str,
    objects: List[SourceProvenanceObject],
    host_app: str,
    importer_version: str = "",
    build_stamp: str = "",
    page_count: Optional[int] = None,
) -> str:
    manifest = build_source_provenance(
        import_session_id=import_session_id,
        pdf_path=pdf_path,
        objects=objects,
        host_app=host_app,
        importer_version=importer_version,
        build_stamp=build_stamp,
        page_count=page_count,
    )
    return manifest.write_json(output_path)


__all__ = [
    "SCHEMA",
    "SourceProvenanceManifest",
    "SourceProvenanceObject",
    "build_source_provenance",
    "ensure_import_session_id",
    "ensure_provenance_bucket",
    "new_import_session_id",
    "record_text_span_provenance",
    "write_source_provenance_sidecar",
]

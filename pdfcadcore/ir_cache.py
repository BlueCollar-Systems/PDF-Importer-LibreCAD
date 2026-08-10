# -*- coding: utf-8 -*-
# ir_cache.py — Persistent intermediate-representation cache for PDF extraction
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""
Cache extracted PageData so repeated imports of the same PDF with the same
options can skip the PDF parsing/arc-fit phase entirely. The cache key is a
SHA-256 digest over the source PDF bytes and the extraction parameters, so
any change in source or options invalidates the entry automatically.

This is a pure speed optimization: the cached IR is bit-identical to what a
fresh extraction would produce, so visual accuracy is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Optional

from .primitives import PageData


DEFAULT_CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", os.environ.get("TMP", "."))) / "BCS" / "pdf_import_ir_cache"


def _cache_root() -> Path:
    root = Path(os.environ.get("BCS_PDF_IR_CACHE_DIR", DEFAULT_CACHE_ROOT))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extraction_params_key(
    page_number: int,
    scale: float,
    flip_y: bool,
    detect_arcs: bool,
    arc_fit_tol_mm: float,
    min_arc_angle_deg: float,
    arc_min_pts: int,
) -> str:
    """Stable hash for extraction parameters."""
    params = {
        "page_number": int(page_number),
        "scale": float(scale),
        "flip_y": bool(flip_y),
        "detect_arcs": bool(detect_arcs),
        "arc_fit_tol_mm": float(arc_fit_tol_mm),
        "min_arc_angle_deg": float(min_arc_angle_deg),
        "arc_min_pts": int(arc_min_pts),
        "schema": "ir-v1",
    }
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_key(pdf_path: str) -> Optional[str]:
    """Hash the source PDF bytes. Returns None only if the file is unreadable."""
    try:
        h = hashlib.sha256()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def cache_key(
    pdf_path: str,
    page_number: int,
    scale: float = 1.0,
    flip_y: bool = True,
    detect_arcs: bool = True,
    arc_fit_tol_mm: float = 0.05,
    min_arc_angle_deg: float = 5.0,
    arc_min_pts: int = 5,
) -> Optional[str]:
    """Return a stable cache key string, or None if the source is unreadable."""
    src = _source_key(pdf_path)
    if src is None:
        return None
    param = _extraction_params_key(
        page_number, scale, flip_y, detect_arcs,
        arc_fit_tol_mm, min_arc_angle_deg, arc_min_pts,
    )
    return f"{src}_{param}"


def cache_path(key: str) -> Path:
    """Map a cache key to a filesystem path (two-level sharded directory)."""
    root = _cache_root()
    return root / key[:2] / key[2:4] / f"{key}.pkl"


def load_ir(key: str) -> Optional[PageData]:
    """Load cached PageData if present, otherwise return None."""
    if not key:
        return None
    path = cache_path(key)
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if isinstance(data, PageData):
            return data
    except (OSError, pickle.PickleError, EOFError, AttributeError):
        pass
    return None


def save_ir(key: str, page_data: PageData) -> None:
    """Persist PageData to the cache."""
    if not key:
        return
    path = cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(page_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def clear_cache() -> int:
    """Remove all cached entries. Returns the number of files removed."""
    root = _cache_root()
    count = 0
    if not root.exists():
        return 0
    for path in root.rglob("*.pkl"):
        try:
            path.unlink()
            count += 1
        except OSError:
            pass
    return count

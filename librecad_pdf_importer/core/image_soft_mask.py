"""Exact alignment of independent, non-interpolated PDF image sample grids."""
from __future__ import annotations

from math import lcm

import numpy as np

try:
    import pymupdf as fitz
except ImportError:
    import fitz


SOFT_MASK_MAX_DIMENSION = 8192
SOFT_MASK_MAX_WORK_BYTES = 64 * 1024 * 1024


def _pdf_value(doc: fitz.Document, xref: int, key: str) -> tuple[str, str]:
    """Resolve an optional scalar, rejecting malformed/cyclic indirect values."""
    kind, value = doc.xref_get_key(xref, key)
    seen: set[int] = set()
    while kind == "xref":
        target = int(value.split()[0])
        if target in seen or len(seen) >= 16:
            raise ValueError(f"cyclic or excessive indirect {key} value")
        seen.add(target)
        value = doc.xref_object(target, compressed=True).strip()
        if value in {"true", "false"}:
            kind = "bool"
        elif value == "null":
            kind = "null"
        elif len(value.split()) == 3 and value.split()[-1] == "R":
            kind = "xref"
        else:
            kind = "other"
    return kind, value


def _interpolate(doc: fitz.Document, xref: int) -> bool:
    kind, value = _pdf_value(doc, xref, "Interpolate")
    if kind == "null":
        return False
    if kind != "bool" or value not in {"true", "false"}:
        raise ValueError("image Interpolate must be a PDF boolean")
    return value == "true"


def _repeat_cells(pix: fitz.Pixmap, width: int, height: int) -> fitz.Pixmap:
    # Pixmap samples have already undergone the PDF Filter/Decode transforms.
    # Replicate complete cells instead of resampling at a different boundary.
    samples = np.frombuffer(pix.samples_mv, dtype=np.uint8)
    rows = samples.reshape(pix.height, pix.stride)[:, :pix.width * pix.n]
    cells = rows.reshape(pix.height, pix.width, pix.n)
    expanded = cells.repeat(height // pix.height, axis=0).repeat(width // pix.width, axis=1)
    return fitz.Pixmap(pix.colorspace, width, height, expanded.tobytes(), False)


def align_image_soft_mask(
    doc: fitz.Document,
    image_xref: int,
    mask_xref: int,
    image: fitz.Pixmap,
    mask: fitz.Pixmap,
) -> tuple[fitz.Pixmap, fitz.Pixmap]:
    """Align unequal grids without moving either image's unit-square cells.

    PDF Reference 1.6, Table 7.11 permits independent dimensions when Matte is
    absent. With Interpolate false, the per-axis least common multiple is the
    smallest grid that preserves every boundary in both original grids. Using
    only the larger size would shift boundaries for coprime dimensions.

    Equal sizes keep the existing composition path. Interpolated unequal grids,
    invalid unequal Matte grids, and excessive exact grids fail explicitly; they
    must not silently become a nearest-neighbour approximation or opaque image.
    """
    if (image.width, image.height) == (mask.width, mask.height):
        return image, mask
    if image.alpha or mask.alpha or mask.n != 1 or mask.colorspace is None:
        raise ValueError("unequal soft-mask grids require opaque color and grayscale mask samples")
    if min(image.width, image.height, mask.width, mask.height) <= 0:
        raise ValueError("image and soft-mask dimensions must be positive")
    if _pdf_value(doc, mask_xref, "Matte")[0] != "null":
        raise ValueError("PDF soft-mask Matte requires matching image dimensions")
    if _interpolate(doc, image_xref) or _interpolate(doc, mask_xref):
        raise ValueError("interpolated unequal image/soft-mask grids require faithful compositing")

    width, height = lcm(image.width, mask.width), lcm(image.height, mask.height)
    # Account conservatively for repeat intermediates, byte copies, pixmaps and
    # subsequent RGBA composition. Check before reading or expanding samples.
    work_bytes = width * height * (8 * (image.n + mask.n) + 16)
    if max(width, height) > SOFT_MASK_MAX_DIMENSION or work_bytes > SOFT_MASK_MAX_WORK_BYTES:
        raise ValueError(
            f"exact image/soft-mask grid {width}x{height} exceeds the bounded extraction budget"
        )
    return _repeat_cells(image, width, height), _repeat_cells(mask, width, height)

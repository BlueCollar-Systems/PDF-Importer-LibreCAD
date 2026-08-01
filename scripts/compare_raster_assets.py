"""Compare delivered raster bytes directly, without a lossy CAD rerender."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import ezdxf
import numpy as np
from PIL import Image


def _rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def compare_images(reference: Path, delivered: Path) -> dict[str, Any]:
    reference = Path(reference).expanduser().resolve()
    delivered = Path(delivered).expanduser().resolve()
    expected = _rgba(reference)
    actual = _rgba(delivered)
    same_shape = expected.shape == actual.shape
    if not same_shape:
        return {
            "reference": str(reference),
            "delivered": str(delivered),
            "reference_size": [int(expected.shape[1]), int(expected.shape[0])],
            "delivered_size": [int(actual.shape[1]), int(actual.shape[0])],
            "pixel_exact": False,
            "mean_absolute_error": None,
            "ink_recall": 0.0,
        }

    difference = np.abs(expected.astype(np.int16) - actual.astype(np.int16))
    expected_ink = (expected[:, :, 3] > 0) & np.any(expected[:, :, :3] < 250, axis=2)
    actual_ink = (actual[:, :, 3] > 0) & np.any(actual[:, :, :3] < 250, axis=2)
    expected_ink_count = int(np.count_nonzero(expected_ink))
    retained_ink_count = int(np.count_nonzero(expected_ink & actual_ink))
    ink_recall = (
        retained_ink_count / expected_ink_count if expected_ink_count else 1.0
    )
    return {
        "reference": str(reference),
        "delivered": str(delivered),
        "reference_size": [int(expected.shape[1]), int(expected.shape[0])],
        "delivered_size": [int(actual.shape[1]), int(actual.shape[0])],
        "pixel_exact": bool(np.array_equal(expected, actual)),
        "mean_absolute_error": float(np.mean(difference)),
        "ink_recall": float(ink_recall),
    }


def resolve_dxf_image_assets(dxf_path: Path) -> list[Path]:
    drawing = Path(dxf_path).expanduser().resolve()
    document = ezdxf.readfile(drawing)
    resolved: list[Path] = []
    for definition in document.objects.query("IMAGEDEF"):
        raw = Path(str(definition.dxf.filename))
        asset = raw.resolve() if raw.is_absolute() else (drawing.parent / raw).resolve()
        if not asset.is_file():
            raise FileNotFoundError(f"DXF image asset is missing: {asset}")
        resolved.append(asset)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a reference image with the exact image asset delivered by "
            "the importer. The CAD file is never rerendered."
        )
    )
    parser.add_argument("reference", type=Path)
    candidate = parser.add_mutually_exclusive_group(required=True)
    candidate.add_argument("--image", type=Path)
    candidate.add_argument("--dxf", type=Path)
    parser.add_argument("--asset-index", type=int, default=0)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    delivered = args.image
    if args.dxf is not None:
        assets = resolve_dxf_image_assets(args.dxf)
        if not assets:
            parser.error("DXF contains no image assets")
        if args.asset_index < 0 or args.asset_index >= len(assets):
            parser.error(f"--asset-index must be between 0 and {len(assets) - 1}")
        delivered = assets[args.asset_index]
    result = compare_images(args.reference, delivered)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["pixel_exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

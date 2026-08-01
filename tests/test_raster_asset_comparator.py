from __future__ import annotations

from pathlib import Path

import ezdxf
from PIL import Image

from scripts.compare_raster_assets import compare_images, resolve_dxf_image_assets


def _png(path: Path, pixels: list[tuple[int, int, int, int]]) -> None:
    image = Image.new("RGBA", (2, 2), (255, 255, 255, 255))
    image.putdata(pixels)
    image.save(path)


def test_direct_asset_comparison_is_pixel_exact_without_cad_rerender(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    delivered = tmp_path / "delivered.png"
    pixels = [
        (255, 255, 255, 255),
        (0, 0, 0, 255),
        (10, 20, 30, 128),
        (255, 255, 255, 0),
    ]
    _png(reference, pixels)
    _png(delivered, pixels)

    result = compare_images(reference, delivered)

    assert result["pixel_exact"] is True
    assert result["mean_absolute_error"] == 0.0
    assert result["ink_recall"] == 1.0


def test_direct_asset_comparison_detects_real_pixel_loss(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    delivered = tmp_path / "delivered.png"
    _png(reference, [(0, 0, 0, 255)] * 4)
    _png(delivered, [(255, 255, 255, 255)] * 4)

    result = compare_images(reference, delivered)

    assert result["pixel_exact"] is False
    assert result["mean_absolute_error"] > 0.0
    assert result["ink_recall"] == 0.0


def test_dxf_asset_resolution_uses_the_dxf_location_not_process_cwd(tmp_path: Path) -> None:
    drawing_dir = tmp_path / "drawing"
    asset_dir = drawing_dir / "assets"
    asset_dir.mkdir(parents=True)
    image_path = asset_dir / "page.png"
    _png(image_path, [(0, 0, 0, 255)] * 4)
    drawing = drawing_dir / "candidate.dxf"
    doc = ezdxf.new("R2010")
    image_def = doc.add_image_def("assets/page.png", size_in_pixel=(2, 2))
    doc.modelspace().add_image(image_def, insert=(0, 0), size_in_units=(2, 2))
    doc.saveas(drawing)

    assert resolve_dxf_image_assets(drawing) == [image_path.resolve()]


def test_comparator_never_uses_matplotlib_rendering() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "compare_raster_assets.py"
    ).read_text(encoding="utf-8")
    assert "matplotlib" not in source.lower()

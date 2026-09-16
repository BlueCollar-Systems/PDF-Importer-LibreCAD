"""Cross-host contract gates for the byte-identical shared PDF core."""

from __future__ import annotations

from dataclasses import fields
import hashlib
import importlib
import json
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]


def _package_name() -> str:
    if (ROOT / "PDFVectorImporter" / "pdfcadcore").is_dir():
        return "PDFVectorImporter.pdfcadcore"
    if (ROOT / "pdf_vector_importer" / "pdfcadcore").is_dir():
        return "pdf_vector_importer.pdfcadcore"
    return "pdfcadcore"


def _core_dir() -> Path:
    if (ROOT / "PDFVectorImporter" / "pdfcadcore").is_dir():
        return ROOT / "PDFVectorImporter" / "pdfcadcore"
    if (ROOT / "pdf_vector_importer" / "pdfcadcore").is_dir():
        return ROOT / "pdf_vector_importer" / "pdfcadcore"
    return ROOT / "pdfcadcore"


def _module(name: str):
    return importlib.import_module(f"{_package_name()}.{name}")


def _sha256(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def test_text_truth_model_preserves_every_cross_host_field() -> None:
    primitives = _module("primitives")

    assert [field.name for field in fields(primitives.TextCharLayout)] == [
        "text",
        "glyph_id",
        "source_origin_pdf",
        "source_bbox_pdf",
        "source_quad_pdf",
        "target_origin",
        "target_quad",
        "advance_width",
        "glyph_height",
    ]
    normalized_fields = {field.name for field in fields(primitives.NormalizedText)}
    assert {
        "source_bbox_pdf",
        "source_quad_pdf",
        "target_quad_model",
        "advance_width",
        "glyph_height",
        "baseline_descent",
        "source_char_layout",
        "requires_individual_positioning",
        "positioned_character",
        "source_glyph_id",
        "font_asset",
        "font_failure",
    } <= normalized_fields
    assert "source_quad" not in normalized_fields
    assert "font_asset_failure" not in normalized_fields


def test_embedded_font_evidence_api_is_complete() -> None:
    embedded = _module("embedded_fonts")

    assert [field.name for field in fields(embedded.EmbeddedFontFailure)] == [
        "page_number",
        "span_font_name",
        "reason",
        "source_xref",
        "error_type",
        "detail",
        "proof_category",
    ]
    asset_fields = {field.name for field in fields(embedded.EmbeddedFontAsset)}
    assert {
        "page_number",
        "span_font_name",
        "base_font_name",
        "source_xref",
        "resource_name",
        "source_font_type",
        "source_encoding",
        "source_format",
        "source_origin",
        "source_bytes",
        "source_sha256",
        "usable_format",
        "usable_bytes",
        "usable_sha256",
        "asset_id",
        "unicode_map_installed",
        "units_per_em",
        "ascender",
        "descender",
        "glyph_advances",
    } <= asset_fields
    for name in (
        "_validate_font_work_bounds",
        "_font_delivery_metrics",
        "_usable_font",
        "_cff_to_otf",
        "_install_pdf_unicode_cmap",
        "_page_unicode_glyph_maps",
        "_base14_renderer_program",
    ):
        assert callable(getattr(embedded, name))
    for name in ("from_page", "for_span", "failure_for_span"):
        assert callable(getattr(embedded.EmbeddedFontCatalog, name))


def test_atomic_publish_and_strict_config_api_are_shared(tmp_path: Path) -> None:
    atomic_io = _module("atomic_io")
    config = _module("import_config")

    target = tmp_path / "nested" / "proof.json"
    result = atomic_io.atomic_write_text(target, '{"verified": true}\n')
    assert result == str(target)
    assert target.read_text(encoding="utf-8") == '{"verified": true}\n'
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []
    assert config.ImportConfig().strict_text_fidelity is True


def test_local_manifest_covers_and_hashes_every_shared_file() -> None:
    manifest = json.loads(
        (ROOT / "pdfcadcore_sync_manifest.json").read_text(encoding="utf-8")
    )
    core = _core_dir()
    expected_names = {path.name for path in core.glob("*.py")}
    expected_names.update({"repo_context_builder_core.py", "pdfcadcore_sync_check.py"})

    assert set(manifest) == expected_names
    for name in sorted(expected_names):
        path = ROOT / name if name in {
            "repo_context_builder_core.py",
            "pdfcadcore_sync_check.py",
        } else core / name
        assert manifest[name] == _sha256(path), name


class _DrawingPage:
    rect = pymupdf.Rect(0.0, 0.0, 200.0, 200.0)
    rotation = 0
    rotation_matrix = pymupdf.Matrix(1.0, 1.0)
    parent = None

    def __init__(self, items: list[tuple[object, ...]]) -> None:
        self._items = list(items)

    def get_drawings(self) -> list[dict[str, object]]:
        return [
            {
                "items": list(self._items),
                "color": (0.0, 0.0, 0.0),
                "width": 1.0,
                "closePath": False,
            }
        ]

    def get_text(self, _mode: str) -> dict[str, list[object]]:
        return {"blocks": []}

    def get_texttrace(self) -> list[object]:
        return []

    def get_fonts(self, *, full: bool = False) -> list[object]:
        del full
        return []


def _extract_drawings(items: list[tuple[object, ...]]):
    extractor = _module("primitive_extractor")
    return extractor.extract_page(
        _DrawingPage(items),
        1,
        flip_y=False,
        detect_arcs=False,
    )


def _point(x: float, y: float) -> pymupdf.Point:
    return pymupdf.Point(x, y)


def test_disconnected_line_items_remain_separate_primitives() -> None:
    page = _extract_drawings(
        [
            ("l", _point(10.0, 10.0), _point(20.0, 10.0)),
            ("l", _point(100.0, 100.0), _point(110.0, 100.0)),
        ]
    )

    mm_per_point = 25.4 / 72.0
    assert [primitive.type for primitive in page.primitives] == ["line", "line"]
    assert [primitive.points for primitive in page.primitives] == [
        [(10.0 * mm_per_point, 10.0 * mm_per_point),
         (20.0 * mm_per_point, 10.0 * mm_per_point)],
        [(100.0 * mm_per_point, 100.0 * mm_per_point),
         (110.0 * mm_per_point, 100.0 * mm_per_point)],
    ]


def test_disconnected_cubic_items_remain_separate_primitives() -> None:
    page = _extract_drawings(
        [
            (
                "c",
                _point(10.0, 10.0),
                _point(13.0, 6.0),
                _point(17.0, 14.0),
                _point(20.0, 10.0),
            ),
            (
                "c",
                _point(100.0, 100.0),
                _point(103.0, 96.0),
                _point(107.0, 104.0),
                _point(110.0, 100.0),
            ),
        ]
    )

    mm_per_point = 25.4 / 72.0
    assert len(page.primitives) == 2
    assert page.primitives[0].points[0] == (10.0 * mm_per_point, 10.0 * mm_per_point)
    assert page.primitives[0].points[-1] == (20.0 * mm_per_point, 10.0 * mm_per_point)
    assert page.primitives[1].points[0] == (100.0 * mm_per_point, 100.0 * mm_per_point)
    assert page.primitives[1].points[-1] == (110.0 * mm_per_point, 100.0 * mm_per_point)


def test_continuous_line_and_cubic_items_share_one_primitive() -> None:
    page = _extract_drawings(
        [
            ("l", _point(10.0, 10.0), _point(20.0, 10.0)),
            (
                "c",
                _point(20.0, 10.0),
                _point(23.0, 6.0),
                _point(27.0, 14.0),
                _point(30.0, 10.0),
            ),
        ]
    )

    assert len(page.primitives) == 1
    assert page.primitives[0].type == "polyline"


def test_implicit_start_cubic_items_continue_from_the_current_endpoint() -> None:
    implicit_items = [
        (
            "c",
            _point(23.0, 6.0),
            _point(27.0, 14.0),
            _point(30.0, 10.0),
        ),
        ("c", 23.0, 6.0, 27.0, 14.0, 30.0, 10.0),
    ]

    for cubic_item in implicit_items:
        page = _extract_drawings(
            [
                ("l", _point(10.0, 10.0), _point(20.0, 10.0)),
                cubic_item,
            ]
        )

        mm_per_point = 25.4 / 72.0
        assert len(page.primitives) == 1
        assert page.primitives[0].type == "polyline"
        assert page.primitives[0].points[0] == (
            10.0 * mm_per_point,
            10.0 * mm_per_point,
        )
        assert page.primitives[0].points[-1] == (
            30.0 * mm_per_point,
            10.0 * mm_per_point,
        )


def test_tuple_point_cubic_keeps_its_explicit_start_and_endpoint() -> None:
    page = _extract_drawings(
        [
            ("l", _point(10.0, 10.0), _point(20.0, 10.0)),
            ("c", (20.0, 10.0), (23.0, 6.0), (27.0, 14.0), (30.0, 10.0)),
        ]
    )

    mm_per_point = 25.4 / 72.0
    assert len(page.primitives) == 1
    assert page.primitives[0].type == "polyline"
    assert page.primitives[0].points[0] == (
        10.0 * mm_per_point,
        10.0 * mm_per_point,
    )
    assert page.primitives[0].points[-1] == (
        30.0 * mm_per_point,
        10.0 * mm_per_point,
    )

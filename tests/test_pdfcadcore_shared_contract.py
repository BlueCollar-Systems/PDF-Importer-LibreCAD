"""Cross-host contract gates for the byte-identical shared PDF core."""

from __future__ import annotations

from dataclasses import fields
import hashlib
import importlib
import json
from pathlib import Path


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

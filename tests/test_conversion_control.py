from __future__ import annotations

from pathlib import Path

import pytest

from conversion_control import ActivePageCancelled, check_cancel, report_progress


def test_cancel_check_raises_dedicated_control_flow_exception() -> None:
    with pytest.raises(ActivePageCancelled, match="active page"):
        check_cancel(lambda: True, "active page")


def test_progress_is_optional_and_preserves_exact_message() -> None:
    messages: list[str] = []
    report_progress(messages.append, "Building page 2: text 64/200")
    report_progress(None, "ignored")
    assert messages == ["Building page 2: text 64/200"]


def test_extractor_and_exporter_contain_bounded_cancel_checkpoints() -> None:
    root = Path(__file__).resolve().parents[1]
    extractor = (root / "librecad_pdf_importer" / "core" / "document.py").read_text(
        encoding="utf-8"
    )
    exporter = (
        root / "librecad_pdf_importer" / "exporters" / "dxf_exporter.py"
    ).read_text(encoding="utf-8")

    assert extractor.count("check_cancel(") >= 3
    assert "for primitive_index, primitive in enumerate(" in exporter
    assert "primitive_index % 64 == 0" in exporter
    assert "for text_index, text in enumerate(" in exporter
    assert 'check_cancel(cancel_requested, "active page text build")' in exporter
    assert "for image_index, placement in enumerate(" in exporter
    assert 'check_cancel(cancel_requested, "active page image build")' in exporter
    assert exporter.count("check_cancel(") >= 4


def test_export_cancel_context_is_initialized_only_in_the_main_export_scope() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (
        root / "librecad_pdf_importer" / "exporters" / "dxf_exporter.py"
    ).read_text(encoding="utf-8")
    font_stage = source.split("def _stage_embedded_font_assets(", 1)[1].split(
        "def _normalized_image_source_path(", 1
    )[0]
    main_export = source.split("def _export_to_dxf_impl(", 1)[1]

    assert "opts.provenance_opts" not in font_stage
    assert main_export.index("cancel_requested = getattr(opts.provenance_opts") < main_export.index(
        "for page_position, page in enumerate(extraction.pages"
    )

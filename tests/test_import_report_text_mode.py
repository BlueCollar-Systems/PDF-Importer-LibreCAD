# -*- coding: utf-8 -*-
"""import_report text_mode parity for LibreCAD host."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfcadcore.import_report import build_import_report


def test_librecad_report_records_text_mode():
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="hybrid",
        import_text=True,
        text_mode="labels",
    )
    extra = report.to_dict()["extra"]
    assert extra["text_mode"] == "labels"
    assert extra["import_text"] is True
    assert extra["diagnostics"]["quality_level"] == "empty"
    assert "text_mode_labels" in extra["diagnostics"]["signals"]


def test_geometry_mode_skips_import_text_flag_still_recorded():
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="vector",
        import_text=False,
        text_mode="geometry",
    )
    extra = report.to_dict()["extra"]
    assert extra["text_mode"] == "geometry"
    assert extra["import_text"] is False


def test_performance_phases_optional():
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        elapsed_ms=1200.0,
        performance_phases={"parse_ms": 400.0, "total_ms": 1200.0},
        helper_timings_ms={"ezdxf_save_ms": 20.0},
        text_source_spans=3,
        text_glyph_estimate=14,
    )
    data = report.to_dict()
    perf = data["performance"]
    assert perf["elapsed_ms"] == 1200.0
    assert perf["phases"]["parse_ms"] == 400.0
    assert perf["phases"]["total_ms"] == 1200.0
    assert perf["helpers_ms"]["ezdxf_save_ms"] == 20.0
    assert data["extra"]["text_source_spans"] == 3
    assert data["extra"]["text_glyph_estimate"] == 14


def test_3d_text_alias_reported_as_host_limit_fallback():
    """TEXTMODE-1 item 10: the 2D alias is a documented host-limit fallback."""
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="vector",
        import_text=True,
        text_mode="3d_text",
        text_fallback={
            "requested": "3d_text",
            "delivered": "labels",
            "reason": "host_2d_no_3d_text",
            "count": 2,
        },
    )
    data = report.to_dict()
    assert data["fallback"]["used"] is True
    text_block = data["fallback"]["text"]
    assert text_block["requested"] == "3d_text"
    assert text_block["delivered"] == "labels"
    assert text_block["reason"] == "host_2d_no_3d_text"
    assert text_block["count"] == 2
    extra = data["extra"]
    # The report keeps the REQUESTED mode; the fallback block tells the truth.
    assert extra["text_mode"] == "3d_text"
    assert "text_mode_fallback" in extra["diagnostics"]["signals"]


def test_matching_delivery_emits_no_fallback_text():
    """TEXTMODE-1: requested == delivered must not synthesize a fallback."""
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="vector",
        import_text=True,
        text_mode="labels",
    )
    data = report.to_dict()
    assert data["fallback"]["used"] is False
    assert data["fallback"].get("text") is None
    assert "text_mode_fallback" not in data["extra"]["diagnostics"]["signals"]


def test_import_report_diagnostics_for_fallback_and_dense_text():
    report = build_import_report(
        host_app="librecad",
        pdf_path="scan.pdf",
        mode="auto",
        primitive_count=0,
        text_count=0,
        layer_count=0,
        warnings=2,
        fallback_used=True,
        fallback_reason="raster_fallback_1_pages",
        import_text=True,
        text_mode="glyphs",
        text_source_spans=14,
        text_glyph_estimate=1200,
    )
    diagnostics = report.to_dict()["extra"]["diagnostics"]
    assert diagnostics["quality_level"] == "empty"
    assert "fallback_used" in diagnostics["signals"]
    assert "warnings_present" in diagnostics["signals"]
    assert "source_text_seen_but_no_text_entities_created" in diagnostics["signals"]
    assert "dense_text_glyph_workload" in diagnostics["signals"]
    assert any("Vector or Hybrid" in action for action in diagnostics["recommended_actions"])

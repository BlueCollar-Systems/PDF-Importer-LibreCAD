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

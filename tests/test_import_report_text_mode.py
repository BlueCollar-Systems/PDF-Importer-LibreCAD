# -*- coding: utf-8 -*-
"""import_report text_mode parity for LibreCAD host."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfcadcore.import_report import (
    build_fallback_transitions,
    build_import_contract_ready,
    build_import_report,
)
from librecad_pdf_importer.importer import _delivery_item_has_persisted_output


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
    assert extra["fallback_transitions"] == []
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


def test_import_contract_ready_ignores_source_spans_when_text_is_disabled():
    report = build_import_report(
        host_app="librecad",
        importer_version="1.0.66",
        pdf_path="drawing.pdf",
        mode="vector",
        pages=1,
        primitive_count=40,
        import_text=False,
        text_mode="none",
        text_source_spans=7,
    )

    ready = report.extra.get("import_contract_ready")
    assert isinstance(ready, dict)
    assert ready["ready"] is True
    assert ready["checks"]["text_delivery"] is True


def test_clean_scale_evaluation_is_explicit_and_contract_ready():
    report = build_import_report(
        host_app="librecad",
        importer_version="1.0.79",
        pdf_path="drawing.pdf",
        mode="vector",
        pages=1,
        primitive_count=40,
        import_text=False,
        text_mode="none",
        extra={
            "resolved_scale": {
                "factor": 24.0,
                "notation": '1/2" = 1\'-0"',
                "source": "titleblock",
                "confidence": 0.98,
                "fallback_reason": "",
            },
            "scale_hints": {
                "title_block_detected": True,
                "dimension_count": 4,
                "alternate_scale_factors": [24.0],
            },
        },
    )

    extra = report.to_dict()["extra"]
    assert extra["scale_crosscheck"] == {
        "level": "ok",
        "reasons": [],
        "messages": [],
    }
    ready = extra["import_contract_ready"]
    assert ready["ready"] is True
    assert ready["checks"]["scale_crosscheck"] is True


def test_malformed_scale_evaluation_remains_fail_closed():
    report = build_import_report(
        host_app="librecad",
        importer_version="1.0.79",
        pdf_path="drawing.pdf",
        mode="vector",
        primitive_count=40,
        import_text=False,
        text_mode="none",
    )
    report.extra["scale_crosscheck"] = None

    ready = build_import_contract_ready(report)

    assert ready["ready"] is False
    assert ready["checks"]["scale_crosscheck"] is False


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


def test_3d_text_item_specific_impossibility_fallback_is_reported_loudly():
    """A distinct fallback records the item-specific representation failure."""
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="vector",
        import_text=True,
        text_mode="3d_text",
        text_fallback={
            "requested": "3d_text",
            "delivered": "labels",
            "reason": "requested_representation_failed_verification",
            "count": 2,
        },
    )
    data = report.to_dict()
    assert data["fallback"]["used"] is True
    text_block = data["fallback"]["text"]
    assert text_block["requested"] == "3d_text"
    assert text_block["delivered"] == "labels"
    assert text_block["reason"] == "requested_representation_failed_verification"
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
    assert not any(
        "Vector or Hybrid" in action
        or "another text mode" in action.lower()
        or "Outlines" in action
        for action in diagnostics["recommended_actions"]
    )
    assert any(
        "requested representation unchanged" in action
        for action in diagnostics["recommended_actions"]
    )


def test_explicit_raster_report_counts_the_delivered_image_instead_of_calling_it_empty():
    report = build_import_report(
        host_app="librecad",
        pdf_path="scan.pdf",
        mode="raster",
        image_count=1,
        import_text=False,
    )
    data = report.to_dict()

    assert data["result"]["images"] == 1
    assert data["extra"]["diagnostics"]["quality_level"] == "raster"
    assert "raster_or_image_content_delivered" in data["extra"]["diagnostics"]["signals"]
    assert "1 raster/image placement" in data["extra"]["human_summary"]
    assert "No editable geometry was created" not in data["extra"]["human_summary"]


def test_failed_delivery_report_cannot_claim_contract_ready_or_imported():
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="vector",
        text_count=1,
        import_text=True,
        text_mode="labels",
        text_source_spans=1,
        extra={
            "result_status": "failed",
            "text_representation_delivery": {
                "verified": False,
                "items": [{"source_id": "text_span:1:1", "verified": False}],
            },
        },
    )
    data = report.to_dict()

    assert data["extra"]["import_contract_ready"]["ready"] is False
    assert data["extra"]["import_contract_ready"]["checks"]["result_succeeded"] is False
    assert data["extra"]["import_contract_ready"]["checks"]["text_delivery"] is False
    assert data["extra"]["human_summary"].startswith("Import failed")
    assert not data["extra"]["human_summary"].startswith("Imported")


def _verified_zero_ink_raster_delivery():
    return {
        "source_id": "text_span:1:355",
        "requested_representation": "raster",
        "final_representation": "raster",
        "verified": True,
        "entity_handles": [],
        "attempts": [
            {
                "attempted_representation": "raster",
                "outcome": "verified",
                "type_verified": True,
                "visual_verified": True,
                "cleanup_verified": True,
                "evidence": {
                    "visible_ink_expected": False,
                    "zero_ink_verified": True,
                    "zero_ink_omitted": True,
                },
            }
        ],
    }


def test_verified_zero_ink_raster_omission_satisfies_the_delivery_gate():
    assert _delivery_item_has_persisted_output(
        _verified_zero_ink_raster_delivery()
    ) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("zero_ink_verified", False),
        ("zero_ink_omitted", False),
        ("visible_ink_expected", True),
    ],
)
def test_unproven_empty_raster_delivery_remains_fail_closed(field, value):
    delivery = deepcopy(_verified_zero_ink_raster_delivery())
    delivery["attempts"][-1]["evidence"][field] = value
    assert _delivery_item_has_persisted_output(delivery) is False


def test_librecad_fallback_transitions_expand_from_representation_delivery():
    report = build_import_report(
        host_app="librecad",
        pdf_path="plan.pdf",
        mode="vector",
        text_count=1,
        import_text=True,
        text_mode="text",
        extra={
            "text_representation_delivery": {
                "verified": True,
                "items": [
                    {
                        "source_id": "text_span:1:12",
                        "requested_representation": "text",
                        "final_representation": "glyphs",
                        "fallback_used": True,
                        "reason": "host_cannot_render_source_ttf_as_native_text",
                        "attempts": [
                            {
                                "outcome": "impossible",
                                "reason": "host_cannot_render_source_ttf_as_native_text",
                                "evidence": {"host_limit": True},
                            }
                        ],
                    }
                ],
            }
        },
    )
    extra = report.to_dict()["extra"]
    assert extra["fallback_transitions"] == [
        {
            "source_span_id": "text_span:1:12",
            "from_mode": "text",
            "to_mode": "glyphs",
            "reason_code": "host_cannot_render_source_ttf_as_native_text",
            "affirmative_impossibility": True,
            "generic_failure": False,
        }
    ]


def test_librecad_keeps_explicit_empty_fallback_transition_ledger():
    assert build_fallback_transitions({"fallback_transitions": []}) == []

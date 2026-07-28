# -*- coding: utf-8 -*-
"""import_report text_mode parity for LibreCAD host."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfcadcore.import_report import build_import_report
from pdfcadcore.text_delivery_report import build_text_representation_delivery


def _delivery_contract_extra(
    source_ids: list[str],
    *,
    requested_type: str = "text",
) -> dict:
    attempts = [
        {
            "source_item_id": source_id,
            "requested_type": requested_type,
            "attempted_type": requested_type,
            "final_type": requested_type,
            "outcome": "verified",
            "cleanup_complete": True,
            "record_verified": True,
            "type_verified": True,
            "visual_verified": True,
            "ownership_verified": True,
            "created_entity_ids": [f"entity:{source_id}"],
            "removed_entity_ids": [],
            "delivery_entity_ids": [f"entity:{source_id}"],
            "support_entity_ids": [],
            "referenced_entity_ids": [],
            "reused_entity_ids": [],
            "evidence": {"host_bound": True},
        }
        for source_id in source_ids
    ]
    required = bool(source_ids)
    return {
        "text_delivery_obligations": {
            "schema": "bcs.text_delivery_obligations/1.0",
            "required": required,
            "requested_type": requested_type,
            "source_item_ids": list(source_ids),
        },
        "text_delivery_attempts": attempts,
        "text_representation_delivery": build_text_representation_delivery(
            attempts,
            requested_type=requested_type,
            required=required,
            expected_source_item_ids=source_ids,
        ),
    }


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


def test_zero_span_unverified_delivery_cannot_claim_contract_ready():
    report = build_import_report(
        host_app="librecad",
        importer_version="1.0.66",
        pdf_path="image-only.pdf",
        mode="vector",
        pages=1,
        image_count=1,
        import_text=True,
        text_mode="text",
        text_source_spans=0,
        extra={
            "text_representation_delivery": {
                "required": False,
                "verified": False,
                "items": [],
            },
        },
    )

    ready = report.extra["import_contract_ready"]
    assert ready["ready"] is False
    assert ready["checks"]["text_delivery"] is False


def test_fabricated_delivery_without_canonical_ledger_is_not_ready():
    report = build_import_report(
        host_app="librecad",
        importer_version="1.0.66",
        pdf_path="drawing.pdf",
        import_text=True,
        text_mode="text",
        text_source_spans=1,
        extra={
            "text_delivery_obligations": {
                "schema": "bcs.text_delivery_obligations/1.0",
                "required": True,
                "requested_type": "text",
                "source_item_ids": ["text_span:1:1"],
            },
            "text_representation_delivery": {
                "verified": True,
                "items": [{"source_item_id": "text_span:1:1", "verified": True}],
            },
        },
    )

    assert report.extra["import_contract_ready"]["ready"] is False
    assert report.extra["import_contract_ready"]["checks"]["text_delivery"] is False


def test_readiness_recomputes_mutated_ledger_and_binds_independent_context():
    for mutation in ("ledger", "requested", "obligation"):
        extra = _delivery_contract_extra(["text_span:1:1"])
        if mutation == "ledger":
            extra["text_delivery_attempts"][0]["outcome"] = "failed"
        elif mutation == "requested":
            extra["text_delivery_obligations"]["requested_type"] = "glyphs"
        else:
            extra["text_delivery_obligations"]["source_item_ids"] = [
                "text_span:1:2"
            ]
        report = build_import_report(
            host_app="librecad",
            importer_version="1.0.66",
            pdf_path="drawing.pdf",
            import_text=True,
            text_mode="text",
            text_source_spans=1,
            extra=extra,
        )

        assert report.extra["import_contract_ready"]["ready"] is False
        assert report.extra["import_contract_ready"]["checks"]["text_delivery"] is False


def test_verified_zero_obligation_contract_is_ready() -> None:
    report = build_import_report(
        host_app="librecad",
        importer_version="1.0.66",
        pdf_path="blank.pdf",
        import_text=True,
        text_mode="text",
        text_source_spans=0,
        extra=_delivery_contract_extra([]),
    )

    assert report.extra["import_contract_ready"]["ready"] is True
    assert report.extra["import_contract_ready"]["checks"]["text_delivery"] is True


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

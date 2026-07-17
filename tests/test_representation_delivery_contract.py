"""Owner-directive locks for LibreCAD requested-representation delivery."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ezdxf
import pytest
from ezdxf.tools.text_size import text_size

from dxf_text_builder import (
    TextDeliveryAttempt,
    TextDeliveryResult,
    _ExactFontResolution,
    _ensure_text_style,
    _normalized_mode,
    _representation_ladder,
    _solid_fill_verified,
    _to_solid_fill_entities,
    build_text,
    reset_text_styles,
)
from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    _verify_serialized_text_deliveries,
    export_to_dxf,
)
from librecad_pdf_importer.importer import ImportRun, run_import, write_import_report
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.embedded_fonts import EmbeddedFontFailure
from pdfcadcore.import_report import build_actual_text_entity_types
from pdfcadcore.primitive_extractor import (
    MM_PER_PT,
    _extract_text,
    _page_rotation_transform,
    _transform_pdf_point,
)
from pdfcadcore.primitives import NormalizedText, PageData
from pdfcadcore.text_scale import (
    calibrate_text_size_to_bbox,
    effective_span_font_size_pt,
    fit_font_size_to_span_bbox,
)


def _item(
    *,
    item_id: int = 17,
    height: float = 0.08,
    width: float = 7.5,
    rotation: float = 33.0,
) -> NormalizedText:
    return NormalizedText(
        id=item_id,
        text="W12X30",
        normalized="W12X30",
        insertion=(12.25, 24.5),
        bbox=(10.0, 20.0, 22.0, 28.0),
        font_size=height,
        rotation=rotation,
        font_name="Arial",
        page_number=3,
        advance_width=width,
    )


def test_generated_text_style_never_claims_a_preexisting_user_style() -> None:
    doc = ezdxf.new("R2010")
    user_style = doc.styles.add("S1", font="user-owned.ttf")
    user_handle = str(user_style.dxf.handle)
    reset_text_styles()

    style_name, style_handle, created = _ensure_text_style(
        doc,
        _ExactFontResolution(
            source_name="EmbeddedSource",
            filename="source-exact.ttf",
            exact=True,
        ),
    )

    assert created is True
    assert style_name != "S1"
    assert style_handle != user_handle
    assert doc.styles.get("S1").dxf.font == "user-owned.ttf"
    assert doc.styles.get(style_name).dxf.font == "source-exact.ttf"


def test_installed_name_match_is_not_reported_as_source_font_equivalence() -> None:
    installed_match = _ExactFontResolution(
        source_name="Arial",
        family="Arial",
        filename="arial.ttf",
        exact=True,
        resolution_source="installed_exact_font",
        reason="exact installed source-font family/style match",
    )
    with patch("dxf_text_builder._resolve_item_font", return_value=installed_match):
        _, _, result = _deliver("text", target_app="generic")

    evidence = result.attempts[0].evidence
    assert evidence["parent_native_text_delivery_verified"] is True
    assert evidence["parent_native_font_substituted"] is True
    assert evidence["parent_source_font_equivalence_verified"] is False
    assert evidence["parent_visual_fidelity_verified"] is False


def _deliver(
    mode: str,
    item: NormalizedText | None = None,
    *,
    target_app: str = "generic",
):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    result = build_text(
        item or _item(),
        msp,
        "TEXT",
        ImportConfig(text_mode=mode),
        target_app=target_app,
        dxf_version="R2010",
        return_delivery_result=True,
    )
    assert isinstance(result, TextDeliveryResult)
    return doc, msp, result


def test_text_is_a_distinct_requested_and_delivered_representation() -> None:
    _, msp, result = _deliver("text")

    assert _normalized_mode("text") == "text"
    assert _representation_ladder("text")[0] == "text"
    assert result.requested_representation == "text"
    assert result.final_representation == "text"
    assert result.fallback_used is False
    assert result.delivered_kind == "dxf_native_text"
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "text"
    ]
    assert [entity.dxftype() for entity in msp] == ["TEXT"]


def test_requested_raster_authorizes_only_the_direct_item_render() -> None:
    _, msp, result = _deliver("raster")

    assert _representation_ladder("raster") == ["raster"]
    assert result.requested_representation == "raster"
    assert result.final_representation is None
    assert result.verified is False
    assert result.terminal_fallback_authorized is True
    assert result.attempts == []
    assert list(msp) == []


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("text", ["text", "glyphs", "geometry"]),
        ("labels", ["labels", "text", "glyphs", "geometry"]),
        ("3d_text", ["3d_text", "text", "glyphs", "geometry"]),
        ("glyphs", ["glyphs", "geometry", "text"]),
        ("geometry", ["geometry", "glyphs", "text"]),
        ("raster", ["raster"]),
    ],
)
def test_fallback_ladders_use_the_nearest_remaining_representation(
    requested,
    expected,
) -> None:
    assert _representation_ladder(requested) == expected


def test_trace_inventory_failure_cannot_be_relabelled_as_exact_native_text() -> None:
    item = __import__("dataclasses").replace(
        _item(),
        font_asset=None,
        font_failure=EmbeddedFontFailure(
            page_number=3,
            span_font_name="Arial",
            reason="page_text_trace_inventory_failed",
            source_xref=41,
            error_type="RuntimeError",
            detail="trace unavailable",
            proof_category="runtime_inventory_unavailable_for_item",
        ),
    )
    _, msp, result = _deliver("text", item)

    assert result.verified is False
    assert result.final_representation is None
    assert result.terminal_fallback_authorized is True
    assert list(msp) == []
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "text",
        "glyphs",
        "glyphs",
        "geometry",
        "geometry",
    ]
    assert all(attempt.outcome == "impossible" for attempt in result.attempts)
    assert all(
        attempt.evidence.get("font_failure_proof_category")
        == "runtime_inventory_unavailable_for_item"
        for attempt in result.attempts
    )


def test_missing_source_text_size_proves_structural_impossibility_without_stalling() -> None:
    item = __import__("dataclasses").replace(_item(), font_size=0.0)
    _, msp, result = _deliver("labels", item)

    assert result.verified is False
    assert result.terminal_fallback_authorized is True
    assert list(msp) == []
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "labels",
        "text",
        "glyphs",
        "glyphs",
        "geometry",
        "geometry",
    ]
    assert all(attempt.outcome == "impossible" for attempt in result.attempts)


def test_librecad_reports_missing_label_entity_then_falls_back_to_text() -> None:
    _, msp, result = _deliver("labels", target_app="librecad")

    assert result.verified is True
    assert result.requested_representation == "labels"
    assert result.final_representation == "text"
    assert result.fallback_used is True
    assert [entity.dxftype() for entity in msp] == ["TEXT"]

    label_attempt, native = result.attempts
    assert label_attempt.attempted_representation == "labels"
    assert label_attempt.outcome == "impossible"
    assert label_attempt.cleanup_verified is True
    assert label_attempt.evidence["item_specific_capability_evaluation"] is True
    assert label_attempt.evidence["parent_native_label_entity_available"] is False
    assert label_attempt.evidence["text_alias_accepted_as_label"] is False
    assert label_attempt.entity_handles == []

    assert native.attempted_representation == "text"
    assert native.outcome == "verified"
    assert native.type_verified is True
    assert native.visual_verified is True
    assert native.cleanup_verified is True
    assert native.evidence["item_specific_creation_attempted"] is True
    assert native.evidence["target_app"] == "librecad"
    assert native.evidence["parent_native_font_required_format"] == "lff"
    assert native.evidence["parent_native_font_candidate_format"] == "lff"
    assert native.evidence["parent_native_font_format_verified"] is True
    assert native.evidence["parent_native_text_delivery_verified"] is True
    assert native.evidence["parent_visual_fidelity_verified"] is False
    assert native.evidence["parent_source_font_equivalence_verified"] is False
    assert native.evidence["fallback_authorized_for_this_item"] is False
    assert native.evidence["parent_native_font_substituted"] is True
    assert native.evidence["parent_native_font_candidate"] == "unicode"
    entity = next(iter(msp))
    style = msp.doc.styles.get(entity.dxf.style)
    assert style.dxf.font == "unicode"


def test_librecad_ladders_do_not_use_labels_as_a_text_alias() -> None:
    assert _representation_ladder("text") == ["text", "glyphs", "geometry"]
    assert _representation_ladder("labels") == [
        "labels",
        "text",
        "glyphs",
        "geometry",
    ]
    assert _representation_ladder("glyphs") == ["glyphs", "geometry", "text"]
    assert _representation_ladder("geometry") == ["geometry", "glyphs", "text"]
    assert _representation_ladder("3d_text") == [
        "3d_text",
        "text",
        "glyphs",
        "geometry",
    ]


def test_librecad_rejects_unverified_native_3d_text_then_preserves_native_text() -> None:
    _, msp, result = _deliver("3d_text", target_app="librecad")

    assert result.verified is True
    assert result.requested_representation == "3d_text"
    assert result.final_representation == "text"
    assert result.fallback_used is True
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "3d_text",
        "text",
    ]
    assert [attempt.outcome for attempt in result.attempts] == [
        "impossible",
        "verified",
    ]
    native_3d = result.attempts[0]
    assert native_3d.evidence["item_specific_creation_attempted"] is True
    assert native_3d.evidence["extrusion_depth_verified"] is True
    assert native_3d.evidence["parent_native_3d_display_verified"] is False
    assert native_3d.evidence["parent_visual_fidelity_verified"] is False
    assert native_3d.cleanup_verified is True
    assert [entity.dxftype() for entity in msp] == ["TEXT"]


@pytest.mark.parametrize("width", [0.75, 7.5, 75.0])
@pytest.mark.parametrize("rotation", [0.0, 33.0, 89.5, 137.0])
def test_label_fallback_to_text_preserves_transform_and_source_advance(
    width: float,
    rotation: float,
) -> None:
    item = _item(width=width, rotation=rotation)
    _, msp, result = _deliver("labels", item)

    assert result.requested_representation == "labels"
    assert result.final_representation == "text"
    assert result.verified is True
    assert result.source_id == "text_span:3:17"
    assert result.fallback_used is True
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "labels",
        "text",
    ]
    assert len(result.entity_handles) == 1

    entity = next(iter(msp))
    assert entity.dxftype() == "TEXT"
    assert entity.dxf.handle == result.entity_handles[0]
    assert entity.dxf.text == item.text
    assert tuple(entity.dxf.insert)[:2] == pytest.approx(item.insertion)
    assert entity.dxf.rotation == pytest.approx(rotation)
    assert entity.dxf.height == pytest.approx(0.08)
    assert text_size(entity).width == pytest.approx(width, rel=1e-6, abs=1e-8)

    final_attempt = result.attempts[-1]
    assert final_attempt.type_verified is True
    assert final_attempt.visual_verified is True
    assert final_attempt.entity_handles == result.entity_handles


def test_labels_preserve_whitespace_only_source_text_as_text() -> None:
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text="   ",
        normalized="",
    )
    _, msp, result = _deliver("labels", item)

    assert result.verified is True
    assert result.final_representation == "text"
    assert result.fallback_used is True
    entity = next(iter(msp))
    assert entity.dxftype() == "TEXT"
    assert entity.dxf.text == "   "
    assert text_size(entity).width == pytest.approx(0.0)
    assert result.attempts[-1].evidence["whitespace_zero_ink_verified"] is True


@pytest.mark.parametrize(
    ("mode", "expected_final", "expected_attempts"),
    [
        ("labels", "text", ["labels", "text"]),
        ("3d_text", "text", ["3d_text", "text"]),
    ],
)
def test_librecad_whitespace_preserves_native_text_without_borrowed_font_pixels(
    mode,
    expected_final,
    expected_attempts,
) -> None:
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text="   ",
        normalized="",
    )
    _, msp, result = _deliver(mode, item, target_app="librecad")

    assert result.verified is True
    assert result.final_representation == expected_final
    assert result.fallback_used is (expected_final != mode)
    assert [attempt.attempted_representation for attempt in result.attempts] == (
        expected_attempts
    )
    final = result.attempts[-1]
    assert final.outcome == "verified"
    assert final.evidence["source_content_whitespace_only"] is True
    assert final.evidence["parent_native_font_rendering_required"] is False
    assert final.evidence["parent_visual_fidelity_verified"] is True
    assert [entity.dxftype() for entity in msp] == ["TEXT"]
    assert next(iter(msp)).dxf.text == "   "


def test_glyphs_are_block_references_and_geometry_is_raw_edges() -> None:
    glyph_doc, glyph_msp, glyph_result = _deliver("glyphs")
    geometry_doc, geometry_msp, geometry_result = _deliver("geometry")

    glyph_entities = list(glyph_msp)
    assert [entity.dxftype() for entity in glyph_entities] == ["INSERT"]
    assert glyph_result.final_representation == "glyphs"
    assert glyph_result.entity_handles == [glyph_entities[0].dxf.handle]
    assert glyph_result.support_entity_handles
    block = glyph_doc.blocks.get(glyph_entities[0].dxf.name)
    block_child_handles = {entity.dxf.handle for entity in block}
    support_handles = set(glyph_result.support_entity_handles)
    assert block_child_handles < support_handles
    structure_handles = support_handles - block_child_handles
    assert len(structure_handles) == 3
    assert {
        glyph_doc.entitydb[handle].dxftype() for handle in structure_handles
    } == {"BLOCK_RECORD", "BLOCK", "ENDBLK"}
    glyph_types = {entity.dxftype() for entity in block}
    assert "SOLID" in glyph_types
    assert glyph_types <= {"LWPOLYLINE", "POLYLINE", "SOLID"}
    assert glyph_result.attempts[-1].evidence["solid_fill_verified"] is True

    geometry_entities = list(geometry_msp)
    assert geometry_result.final_representation == "geometry"
    assert geometry_result.support_entity_handles == []
    assert {entity.dxf.handle for entity in geometry_entities} == set(
        geometry_result.entity_handles
    )
    assert {entity.dxftype() for entity in geometry_entities} <= {
        "LWPOLYLINE",
        "POLYLINE",
        "SOLID",
    }
    assert any(entity.dxftype() == "SOLID" for entity in geometry_entities)
    assert "INSERT" not in {entity.dxftype() for entity in geometry_msp}


def test_glyph_block_reference_carries_source_color_for_librecad_parent() -> None:
    item = __import__("dataclasses").replace(
        _item(),
        color=(0.10980392156862745, 0.3764705882352941, 0.5764705882352941),
    )
    doc, msp, result = _deliver("glyphs", item, target_app="librecad")

    assert result.verified is True
    insert = next(iter(msp))
    assert insert.dxftype() == "INSERT"
    assert insert.dxf.true_color == 0x1C6093
    block = doc.blocks.get(insert.dxf.name)
    assert all(entity.dxf.true_color == 0x1C6093 for entity in block)


def test_r12_glyph_fill_uses_serializable_solid_triangles(tmp_path) -> None:
    doc = ezdxf.new("R12")
    msp = doc.modelspace()
    result = build_text(
        _item(),
        msp,
        "TEXT",
        ImportConfig(text_mode="glyphs"),
        is_r12=True,
        target_app="librecad",
        dxf_version="R12",
        return_delivery_result=True,
    )

    assert isinstance(result, TextDeliveryResult)
    assert result.final_representation == "glyphs"
    block_ref = next(iter(msp))
    block = doc.blocks.get(block_ref.dxf.name)
    block_types = {entity.dxftype() for entity in block}
    assert "SOLID" in block_types
    assert "HATCH" not in block_types
    assert result.attempts[-1].evidence["solid_fill_verified"] is True
    assert result.attempts[-1].evidence["solid_fill_entity_type"] == "SOLID"

    output = tmp_path / "r12-filled-glyph.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    reopened_ref = next(iter(reopened.modelspace()))
    reopened_block = reopened.blocks.get(reopened_ref.dxf.name)
    assert "SOLID" in {entity.dxftype() for entity in reopened_block}


def test_solid_fill_discards_degenerate_triangulator_artifacts() -> None:
    """A single zero-area artifact must not invalidate otherwise valid glyph fill."""

    from ezdxf.math import Vec3

    valid = (Vec3(0, 0), Vec3(2, 0), Vec3(0, 1))
    degenerate = (Vec3(3, 0), Vec3(3, 0), Vec3(3, 1))
    with patch(
        "dxf_text_builder.ezdxf_path.triangulate",
        return_value=[valid, degenerate],
    ) as triangulate:
        fills = _to_solid_fill_entities([], is_r12=False, attribs={})

    assert len(fills) == 1
    assert _solid_fill_verified(fills, is_r12=False) is True
    assert triangulate.call_args.kwargs == {"max_sagitta": 0.01, "min_segments": 2}


def test_3d_text_is_a_verified_extruded_text_entity_not_a_flat_label_fallback() -> None:
    _, msp, result = _deliver("3d_text")

    assert result.requested_representation == "3d_text"
    assert result.final_representation == "3d_text"
    assert result.fallback_used is False
    assert result.verified is True
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "3d_text",
    ]
    attempt = result.attempts[0]
    assert attempt.outcome == "verified"
    assert attempt.source_id == result.source_id
    assert len(attempt.entity_handles) == 1
    assert attempt.cleanup_verified is True
    assert attempt.evidence["target_app"] == "generic"
    assert attempt.evidence["dxf_version"] == "R2010"
    assert attempt.evidence["item_specific_creation_attempted"] is True
    assert attempt.evidence["extrusion_depth_mm"] == pytest.approx(3.175)
    entity = next(iter(msp))
    assert entity.dxftype() == "TEXT"
    assert entity.dxf.thickness == pytest.approx(3.175)
    assert tuple(entity.dxf.extrusion) == pytest.approx((0.0, 0.0, 1.0))


def test_3d_text_does_not_depend_on_a_nonstandard_add_text3d_factory() -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    with patch.object(
        type(msp),
        "add_text3d",
        lambda *_args, **_kwargs: None,
        create=True,
    ):
        result = build_text(
            _item(),
            msp,
            "TEXT",
            ImportConfig(text_mode="3d_text"),
            target_app="generic",
            dxf_version="R2010",
            return_delivery_result=True,
        )

    assert isinstance(result, TextDeliveryResult)
    assert result.verified is True
    assert result.final_representation == "3d_text"
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "3d_text"
    ]
    assert result.attempts[0].outcome == "verified"
    assert len(list(msp)) == 1


def test_failed_outline_strategies_stop_without_cross_type_fallback() -> None:
    with (
        patch(
            "dxf_text_builder.text2path.make_paths_from_entity",
            side_effect=RuntimeError("entity outline unavailable"),
        ),
        patch(
            "dxf_text_builder.text2path.make_paths_from_str",
            side_effect=RuntimeError("string outline unavailable"),
        ),
    ):
        doc, msp, result = _deliver("geometry")

    assert result.final_representation is None
    assert result.fallback_used is False
    assert list(msp) == []
    assert [attempt.strategy for attempt in result.attempts] == [
        "entity_text2path",
        "string_text2path",
    ]
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "geometry",
        "geometry",
    ]
    assert all(attempt.cleanup_verified for attempt in result.attempts)
    assert all(
        set(attempt.removed_entity_handles) == set(attempt.created_entity_handles)
        for attempt in result.attempts
    )
    assert not any(
        entity.dxftype() in {"TEXT", "MTEXT"}
        for block in doc.blocks
        if block.name not in {"*Model_Space", "*Paper_Space"}
        for entity in block
    )


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_whitespace_only_source_falls_back_to_nearest_exact_zero_ink_text(mode) -> None:
    item = _item(width=4.0)
    item.text = "   "
    item.normalized = ""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    result = build_text(
        item,
        msp,
        "TEXT",
        ImportConfig(text_mode=mode),
        target_app="librecad",
        dxf_version="R2010",
        return_delivery_result=True,
    )

    assert isinstance(result, TextDeliveryResult)
    assert result.verified is True
    assert result.final_representation == "text"
    assert result.fallback_used is True
    assert result.terminal_fallback_authorized is False
    outline_attempts = [
        attempt
        for attempt in result.attempts
        if attempt.attempted_representation in {"glyphs", "geometry"}
    ]
    assert outline_attempts
    assert all(attempt.outcome == "impossible" for attempt in outline_attempts)
    assert all(attempt.cleanup_verified for attempt in outline_attempts)
    assert all(
        attempt.evidence["source_content_whitespace_only"] is True
        and attempt.evidence["zero_outline_result_verified"] is True
        and attempt.evidence["item_specific_creation_attempted"] is True
        for attempt in outline_attempts
    )
    assert result.attempts[-1].attempted_representation == "text"
    assert result.attempts[-1].outcome == "verified"
    assert result.attempts[-1].evidence["parent_visual_fidelity_verified"] is True
    assert result.attempts[-1].evidence["source_content_whitespace_only"] is True
    assert result.attempts[-1].evidence["parent_native_font_rendering_required"] is False
    assert [entity.dxftype() for entity in msp] == ["TEXT"]
    assert next(iter(msp)).dxf.text == "   "


def test_outline_cannot_self_certify_when_source_text_parameters_fail() -> None:
    with (
        patch(
            "dxf_text_builder._verify_label",
            return_value=(
                True,
                False,
                {"source_text_parameters_verified": False},
            ),
        ),
        patch(
            "dxf_text_builder.text2path.make_paths_from_str",
            side_effect=RuntimeError("independent outline unavailable"),
        ),
    ):
        _, msp, result = _deliver("geometry")

    assert result.verified is False
    assert result.final_representation is None
    assert list(msp) == []
    assert result.attempts[0].strategy == "entity_text2path"
    assert result.attempts[0].visual_verified is False
    assert result.attempts[0].cleanup_verified is True


def test_unknown_diagonal_advance_cannot_certify_visual_width() -> None:
    item = _item(rotation=33.0)
    item.advance_width = None
    item.target_quad_model = None

    _, msp, result = _deliver("text", item)

    assert result.verified is False
    assert result.final_representation is None
    assert result.attempts[0].evidence["width_source"] == (
        "unavailable_for_diagonal_bbox"
    )
    assert result.attempts[0].evidence["width_verified"] is False
    assert list(msp) == []


def test_unresolved_source_font_cannot_self_certify_as_arial() -> None:
    item = _item()
    item.font_name = "BCS-Definitely-Missing-Weld-Font"

    _, msp, result = _deliver("text", item)

    assert result.verified is False
    assert result.final_representation is None
    assert result.attempts[0].evidence["font_exact_match"] is False
    assert list(msp) == []


def test_actual_entity_report_does_not_infer_delivery_from_requested_mode() -> None:
    actual = build_actual_text_entity_types(
        host_app="librecad",
        text_mode="geometry",
        count=9,
        delivered_counts={},
    )

    assert actual["entity_type"] == "none"
    assert actual["count"] == 0
    assert actual["raw_geometry_edges"] == 0
    assert actual["dxf_text"] == 0


def test_shared_text_scale_preserves_subpoint_source_size_without_floor() -> None:
    assert effective_span_font_size_pt({"size": 0.25}) == pytest.approx(0.25)
    assert calibrate_text_size_to_bbox("A", 0.025, None) == pytest.approx(0.025)
    assert fit_font_size_to_span_bbox("A", 0.025, {}, 1.0) == pytest.approx(
        0.025
    )

    class _Page:
        @staticmethod
        def get_text(_kind):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "dir": (1.0, 0.0),
                                "bbox": (10.0, 9.7, 10.5, 10.1),
                                "spans": [
                                    {
                                        "text": "A",
                                        "size": 0.25,
                                        "font": "Arial",
                                        "origin": (10.0, 10.0),
                                        "bbox": (10.0, 9.7, 10.5, 10.1),
                                        "ascender": 0.8,
                                        "descender": -0.2,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }

    with patch(
        "pdfcadcore.primitive_extractor._merge_stacked_fractions",
        side_effect=AssertionError(
            "production extraction must preserve original positioned source spans"
        ),
    ):
        extracted = _extract_text(_Page(), 100.0, 1, True, 1.0)
        extracted_again = _extract_text(_Page(), 100.0, 1, True, 1.0)
    assert len(extracted) == 1
    assert [item.id for item in extracted] == [1]
    assert [item.id for item in extracted_again] == [1]
    assert extracted[0].font_size == pytest.approx(0.25 * MM_PER_PT)
    assert extracted[0].font_size < 0.1


def _run_for_items(tmp_path, mode: str, items: list[NormalizedText]):
    pdf_path = tmp_path / "source.pdf"
    pdf = __import__("pymupdf").open()
    pdf.new_page(width=120, height=80)
    pdf.save(str(pdf_path))
    pdf.close()
    page = ExtractedPage(
        page_data=PageData(
            page_number=3,
            width=120.0,
            height=80.0,
            text_items=items,
        ),
        profile=SimpleNamespace(titleblock_likely=False),
        resolved_mode="vector",
    )
    config = ImportConfig.vector()
    config.import_text = True
    config.text_mode = mode
    run = ImportRun(
        extraction=DocumentExtraction(
            str(pdf_path), pages=[page], requested_mode="vector"
        ),
        config=config,
    )
    dxf_path = tmp_path / f"{mode}.dxf"
    result = export_to_dxf(
        run.extraction,
        str(dxf_path),
        DxfExportOptions(
            include_images=False,
            text_mode=mode,
            provenance_opts=config,
        ),
    )
    report_path = tmp_path / f"{mode}_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    return result, config, ezdxf.readfile(dxf_path), json.loads(
        report_path.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    ("mode", "delivered_mode", "modelspace_type", "actual_bucket"),
    [
        ("labels", "text", "TEXT", "dxf_text"),
        ("glyphs", "glyphs", "INSERT", "outline_curve_or_mesh"),
        ("geometry", "geometry", "LWPOLYLINE", "raw_geometry_edges"),
    ],
)
def test_exporter_reports_exact_source_and_dxf_handle_sets(
    tmp_path,
    mode: str,
    delivered_mode: str,
    modelspace_type: str,
    actual_bucket: str,
) -> None:
    items = [
        _item(item_id=17, width=7.5, rotation=33.0),
        _item(item_id=18, width=19.0, rotation=89.5),
    ]
    result, config, drawing, report = _run_for_items(tmp_path, mode, items)

    deliveries = result.text_deliveries
    assert deliveries == config._text_representation_deliveries
    assert [entry["source_id"] for entry in deliveries] == [
        "text_span:3:17",
        "text_span:3:18",
    ]
    assert all(entry["requested_representation"] == mode for entry in deliveries)
    assert all(entry["final_representation"] == delivered_mode for entry in deliveries)
    assert all(entry["verified"] is True for entry in deliveries)

    reported_ids = {
        handle for entry in deliveries for handle in entry["entity_handles"]
    }
    actual_entities = [
        entity
        for entity in drawing.modelspace()
        if str(entity.dxf.layer or "") == "P003_TEXT"
    ]
    assert actual_entities
    assert modelspace_type in {entity.dxftype() for entity in actual_entities}
    assert reported_ids == {entity.dxf.handle for entity in actual_entities}

    provenance = list(config._source_provenance_objects)
    assert {entry.parent_handle for entry in provenance} == reported_ids
    assert len({entry.object_id for entry in provenance}) == len(provenance)
    assert all(entry.object_id.startswith("text_span:3:") for entry in provenance)
    expected_provenance_types = (
        {modelspace_type, "SOLID"} if mode == "geometry" else {modelspace_type}
    )
    assert {entry.created_entity_type for entry in provenance} == expected_provenance_types
    assert all(entry.source_bbox_pdf is None for entry in provenance)
    assert all(entry.target_bbox_model is not None for entry in provenance)

    delivery_report = report["extra"]["text_representation_delivery"]
    assert delivery_report["schema"] == "bcs.text_representation_delivery/1.0"
    assert delivery_report["items"] == deliveries
    assert set(delivery_report["source_ids"]) == {
        "text_span:3:17",
        "text_span:3:18",
    }
    assert set(delivery_report["entity_handles"]) == reported_ids
    assert set(delivery_report["support_entity_handles"]) == {
        handle
        for item in deliveries
        for handle in item["support_entity_handles"]
    }
    assert set(delivery_report["referenced_entity_handles"]) == {
        handle
        for item in deliveries
        for handle in item["referenced_entity_handles"]
    }
    actual = report["extra"]["actual_text_entity_types"]
    assert actual["entity_type"] == delivered_mode
    assert actual[actual_bucket] == len(actual_entities)


def test_3d_export_report_records_loud_native_text_fallback(tmp_path) -> None:
    result, _, drawing, report = _run_for_items(tmp_path, "3d_text", [_item()])

    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    assert delivery["requested_representation"] == "3d_text"
    assert delivery["final_representation"] == "text"
    assert delivery["fallback_used"] is True
    entity = next(iter(drawing.modelspace()))
    assert entity.dxftype() == "TEXT"
    assert [attempt["attempted_representation"] for attempt in delivery["attempts"]] == [
        "3d_text",
        "text",
    ]
    actual = report["extra"]["actual_text_entity_types"]
    assert actual["entity_type"] == "text"
    assert actual["native_3d_text"] == 0
    assert actual["dxf_text"] == 1


def test_direct_dxf_builder_records_verified_3d_text_fallback_for_librecad() -> None:
    from dxf_builder import build_dxf

    config = ImportConfig.vector()
    config.import_text = True
    config.text_mode = "3d_text"
    page = PageData(
        page_number=3,
        width=120.0,
        height=80.0,
        text_items=[_item()],
    )

    drawing, _, text_count = build_dxf([page], config, dxf_version="R2010")

    deliveries = list(getattr(config, "_text_representation_deliveries", []) or [])
    assert len(deliveries) == 1
    assert deliveries[0]["verified"] is True
    assert deliveries[0]["requested_representation"] == "3d_text"
    assert deliveries[0]["final_representation"] == "text"
    assert deliveries[0]["fallback_used"] is True
    assert text_count == 1
    assert next(iter(drawing.modelspace())).dxftype() == "TEXT"


def test_noncanonical_engine_mode_fails_closed_instead_of_using_legacy_semantics(
    tmp_path,
) -> None:
    from dxf_import_engine import convert

    pdf_path = tmp_path / "source.pdf"
    pdf = __import__("pymupdf").open()
    pdf.new_page(width=120, height=80)
    pdf.save(str(pdf_path))
    pdf.close()
    config = ImportConfig.vector()
    config.import_mode = "legacy"

    with pytest.raises(ValueError, match="auto, vector, raster, hybrid"):
        convert(str(pdf_path), str(tmp_path / "must_not_publish.dxf"), config=config)

    assert not (tmp_path / "must_not_publish.dxf").exists()


def _real_text_extraction(tmp_path):
    pdf_path = tmp_path / "raster_source.pdf"
    pdf = __import__("pymupdf").open()
    page = pdf.new_page(width=240, height=160)
    page.insert_text((36, 72), "W12X30", fontsize=12)
    pdf.save(str(pdf_path))
    pdf.close()
    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    assert run.extraction.text_count == 1
    return run


def test_explicit_item_raster_is_verified_without_being_reported_as_fallback(
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    output = tmp_path / "requested_item_raster.dxf"

    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_images=False,
            text_mode="raster",
            provenance_opts=run.config,
        ),
    )

    assert output.is_file()
    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    assert delivery["requested_representation"] == "raster"
    assert delivery["final_representation"] == "raster"
    assert delivery["verified"] is True
    assert delivery["fallback_used"] is False
    assert [attempt["attempted_representation"] for attempt in delivery["attempts"]] == [
        "raster"
    ]
    assert result.text_fallbacks == []
    drawing = ezdxf.readfile(output)
    assert [entity.dxftype() for entity in drawing.modelspace()] == ["IMAGE"]
    image = next(iter(drawing.modelspace()))
    original_insert = tuple(image.dxf.insert)
    image.dxf.insert = (original_insert[0] + 1.0, original_insert[1], 0.0)
    with pytest.raises(RuntimeError, match="raster placement changed"):
        _verify_serialized_text_deliveries(drawing, result.text_deliveries)

    report_path = tmp_path / "requested_item_raster_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["fallback"]["used"] is False
    assert "text" not in report["fallback"]
    assert report["extra"]["actual_text_entity_types"]["entity_type"] == "raster"


def test_explicit_raster_and_requested_labels_are_both_retained(tmp_path) -> None:
    pdf_path = tmp_path / "raster_with_requested_text.pdf"
    pdf = __import__("pymupdf").open()
    page = pdf.new_page(width=240, height=160)
    page.insert_text((36, 72), "W12X30", fontsize=12)
    pdf.save(str(pdf_path))
    pdf.close()

    run = run_import(
        str(pdf_path),
        mode="raster",
        overrides={"pages": "1", "import_text": True, "text_mode": "labels"},
    )

    assert run.extraction.requested_mode == "raster"
    assert run.extraction.pages[0].resolved_mode == "hybrid"
    assert run.extraction.text_count == 1
    assert run.extraction.image_count == 1
    assert "requested labels" in run.extraction.pages[0].resolved_reason.lower()
    source_text = run.extraction.pages[0].page_data.text_items[0]
    assert source_text.source_bbox_pdf is not None
    page_raster = __import__("pymupdf").Pixmap(
        run.extraction.pages[0].images[0].path
    )
    assert page_raster.alpha
    x0, y0, x1, y1 = source_text.source_bbox_pdf
    center_x = int(round(((x0 + x1) * 0.5) * page_raster.width / 240.0))
    center_y = int(round(((y0 + y1) * 0.5) * page_raster.height / 160.0))
    assert page_raster.pixel(center_x, center_y)[-1] == 0


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_page_raster_text_mask_uses_the_authoritative_page_rotation(
    tmp_path,
    rotation,
) -> None:
    pdf_path = tmp_path / f"masked-r{rotation}.pdf"
    pdf = __import__("pymupdf").open()
    page = pdf.new_page(width=240, height=160)
    page.insert_text((36, 72), "W12X30", fontsize=12)
    page.set_rotation(rotation)
    pdf.save(str(pdf_path))
    pdf.close()

    run = run_import(
        str(pdf_path),
        mode="raster",
        overrides={"pages": "1", "import_text": True, "text_mode": "labels"},
    )
    source_text = run.extraction.pages[0].page_data.text_items[0]
    raster = __import__("pymupdf").Pixmap(run.extraction.pages[0].images[0].path)
    assert raster.alpha

    with __import__("pymupdf").open(pdf_path) as document:
        page = document[0]
        transform = _page_rotation_transform(page.rect, page.rotation_matrix)
        x0, y0, x1, y1 = source_text.source_bbox_pdf
        center = _transform_pdf_point((x0 + x1) * 0.5, (y0 + y1) * 0.5, transform)
        pixel_x = int(
            round((center[0] - page.rect.x0) * raster.width / page.rect.width)
        )
        pixel_y = int(
            round((center[1] - page.rect.y0) * raster.height / page.rect.height)
        )
    assert raster.pixel(pixel_x, pixel_y)[-1] == 0


def test_run_import_records_but_does_not_publish_pre_export_report(tmp_path) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf = __import__("pymupdf").open()
    pdf.new_page(width=120, height=80)
    pdf.save(str(pdf_path))
    pdf.close()
    report_path = tmp_path / "accepted_import_report.json"
    prior = b'{"accepted": true}\n'
    report_path.write_bytes(prior)

    run = run_import(
        str(pdf_path),
        mode="vector",
        overrides={"pages": "1", "import_report_path": str(report_path)},
    )

    assert run.import_report_path == str(report_path)
    assert report_path.read_bytes() == prior


def test_failed_3d_export_writes_separate_complete_failure_report(tmp_path) -> None:
    from dxf_import_engine import convert

    pdf_path = tmp_path / "source.pdf"
    pdf = __import__("pymupdf").open()
    page = pdf.new_page(width=120, height=80)
    page.insert_text((20, 40), "W12X30", fontsize=10)
    pdf.save(str(pdf_path))
    pdf.close()
    pdf = __import__("pymupdf").open(str(pdf_path))
    font_xref = pdf[0].get_fonts(full=True)[0][0]
    font_object = pdf.xref_object(font_xref)
    pdf.update_object(
        font_xref,
        font_object.replace("/BaseFont/Helvetica", "/BaseFont/DefinitelyMissingFont")
        .replace("/BaseFont /Helvetica", "/BaseFont /DefinitelyMissingFont"),
    )
    pdf.saveIncr()
    pdf.close()

    dxf_path = tmp_path / "accepted.dxf"
    prior_dxf = b"prior accepted DXF\r\n"
    dxf_path.write_bytes(prior_dxf)
    accepted_report = tmp_path / "accepted_import_report.json"
    prior_report = b'{"accepted": true}\n'
    accepted_report.write_bytes(prior_report)
    config = ImportConfig.vector()
    config.import_text = True
    config.text_mode = "3d_text"
    structural_failure = TextDeliveryResult(
        source_id="text_span:1:1",
        requested_representation="3d_text",
        final_representation=None,
        verified=False,
        attempts=[
            TextDeliveryAttempt(
                source_id="text_span:1:1",
                requested_representation="3d_text",
                attempted_representation="3d_text",
                strategy="native_dxf_text_extrusion",
                outcome="impossible",
                reason="parent cannot display editable 3D text",
                cleanup_verified=True,
            )
        ],
        terminal_fallback_authorized=True,
        failure_reason="all structural representations were proven impossible",
    )

    with (
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter.build_text",
            return_value=structural_failure,
        ),
        patch.object(
            __import__("pymupdf").Page,
            "get_pixmap",
            side_effect=RuntimeError("terminal renderer unavailable"),
        ),
    ):
        with pytest.raises(RuntimeError, match="text_span:1:1") as raised:
            convert(str(pdf_path), str(dxf_path), config=config, dxf_version="R2010")

    assert dxf_path.read_bytes() == prior_dxf
    assert accepted_report.read_bytes() == prior_report
    failure_report_path = Path(raised.value.failure_report_path)
    assert failure_report_path.is_file()
    assert failure_report_path != accepted_report
    report = json.loads(failure_report_path.read_text(encoding="utf-8"))
    assert report["extra"]["result_status"] == "failed"
    assert report["extra"]["import_contract_ready"]["ready"] is False
    assert report["extra"]["human_summary"].startswith("Import failed")
    delivery = report["extra"]["text_representation_delivery"]
    assert delivery["verified"] is False
    assert delivery["requested_representation"] == "3d_text"
    assert len(delivery["items"]) == 1
    item = delivery["items"][0]
    assert item["source_id"] == "text_span:1:1"
    assert item["final_representation"] is None
    assert item["verified"] is False
    assert [attempt["attempted_representation"] for attempt in item["attempts"]] == [
        "3d_text",
        "raster",
    ]
    assert all(attempt["outcome"] == "impossible" for attempt in item["attempts"][:-1])
    assert item["attempts"][-1]["outcome"] == "failed"


def test_exporter_reaches_verified_item_raster_terminal_attempt(tmp_path) -> None:
    run = _real_text_extraction(tmp_path)
    failure = TextDeliveryResult(
        source_id=f"text_span:1:{run.extraction.pages[0].page_data.text_items[0].id}",
        requested_representation="labels",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=True,
        failure_reason="all structural representations failed",
    )
    output = tmp_path / "raster_terminal.dxf"
    with patch(
        "librecad_pdf_importer.exporters.dxf_exporter.build_text",
        return_value=failure,
    ):
        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(
                include_images=False,
                text_mode="labels",
                provenance_opts=run.config,
            ),
        )

    assert output.is_file()
    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    assert delivery["final_representation"] == "raster"
    assert delivery["fallback_used"] is True
    assert delivery["verified"] is True
    assert delivery["attempts"][-1]["attempted_representation"] == "raster"
    assert delivery["attempts"][-1]["type_verified"] is True
    assert delivery["attempts"][-1]["visual_verified"] is True
    evidence = delivery["attempts"][-1]["evidence"]
    assert evidence["source_pdf_path"] == str(Path(run.extraction.pdf_path).resolve())
    assert evidence["source_pdf_sha256"] == hashlib.sha256(
        Path(run.extraction.pdf_path).read_bytes()
    ).hexdigest()
    assert evidence["source_page_number"] == 1
    assert evidence["source_id"] == delivery["source_id"]
    asset_path = Path(evidence["asset_path"])
    assert asset_path.is_file()
    assert asset_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    drawing = ezdxf.readfile(output)
    assert {entity.dxftype() for entity in drawing.modelspace()} == {"IMAGE"}
    assert {entity.dxf.handle for entity in drawing.modelspace()} == set(
        delivery["entity_handles"]
    )
    report_path = tmp_path / "raster_terminal_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    actual = report["extra"]["actual_text_entity_types"]
    assert actual["entity_type"] == "raster"
    assert actual["raster_image"] == 1
    assert report["fallback"]["text"]["requested"] == "labels"
    assert report["fallback"]["text"]["delivered"] == "raster"
    assert (
        report["fallback"]["text"]["reason"]
        == "structural_representations_failed_verification"
    )
    assert (
        report["extra"]["text_representation_delivery"]["items"][0]
        == delivery
    )


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("user_unit", [1.0, 2.0])
def test_terminal_raster_uses_exact_raw_source_bbox_through_page_transform(
    tmp_path,
    rotation,
    user_unit,
) -> None:
    pdf_path = tmp_path / f"terminal-raster-r{rotation}-u{user_unit}.pdf"
    pdf = __import__("pymupdf").open()
    page = pdf.new_page(width=200, height=100)
    page.insert_text((30, 50), "W12X30", fontsize=12)
    page.set_cropbox(__import__("pymupdf").Rect(20, 10, 180, 90))
    page.set_rotation(rotation)
    if user_unit != 1.0:
        pdf.xref_set_key(page.xref, "UserUnit", str(user_unit))
    pdf.save(str(pdf_path))
    pdf.close()

    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    source_text = run.extraction.pages[0].page_data.text_items[0]
    assert source_text.source_bbox_pdf is not None
    failure = TextDeliveryResult(
        source_id=f"text_span:1:{source_text.id}",
        requested_representation="labels",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=True,
        failure_reason="all structural representations proven impossible",
    )
    output = tmp_path / f"terminal-raster-r{rotation}-u{user_unit}.dxf"
    with patch(
        "librecad_pdf_importer.exporters.dxf_exporter.build_text",
        return_value=failure,
    ):
        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_images=False, text_mode="labels"),
        )

    attempt = result.text_deliveries[0]["attempts"][-1]
    assert attempt["outcome"] == "verified"
    assert attempt["evidence"]["source_bbox_pdf"] == pytest.approx(
        source_text.source_bbox_pdf
    )
    assert attempt["evidence"]["visible_ink_verified"] is True
    assert Path(attempt["evidence"]["asset_path"]).is_file()


def test_exporter_fails_loudly_when_terminal_raster_cannot_be_verified(
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    source_id = (
        f"text_span:1:{run.extraction.pages[0].page_data.text_items[0].id}"
    )
    failure = TextDeliveryResult(
        source_id=source_id,
        requested_representation="labels",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=True,
        failure_reason="all structural representations failed",
    )
    output = tmp_path / "must_not_publish.dxf"
    prior_output = b"prior accepted DXF must remain byte-for-byte unchanged\r\n"
    output.write_bytes(prior_output)
    with (
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter.build_text",
            return_value=failure,
        ),
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter.fitz.open",
            side_effect=RuntimeError("terminal renderer unavailable"),
        ),
    ):
        with pytest.raises(RuntimeError, match=source_id):
            export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_images=False, text_mode="labels"),
            )
    assert output.read_bytes() == prior_output
    assert not list(tmp_path.rglob("*.png"))


def test_terminal_raster_cannot_borrow_neighboring_ink_for_whitespace(tmp_path) -> None:
    run = _real_text_extraction(tmp_path)
    original = run.extraction.pages[0].page_data.text_items[0]
    whitespace = __import__("dataclasses").replace(
        original,
        text="   ",
        normalized="",
    )
    run.extraction.pages[0].page_data.text_items = [whitespace]
    source_id = f"text_span:1:{whitespace.id}"
    failure = TextDeliveryResult(
        source_id=source_id,
        requested_representation="labels",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=True,
        failure_reason="all structural representations proven impossible",
    )
    output = tmp_path / "whitespace_must_not_be_rasterized.dxf"

    with patch(
        "librecad_pdf_importer.exporters.dxf_exporter.build_text",
        return_value=failure,
    ):
        with pytest.raises(RuntimeError, match="whitespace-only"):
            export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_images=False, text_mode="labels"),
            )

    assert not output.exists()
    assert not list(tmp_path.rglob("*.png"))


def test_unproven_structural_failure_cannot_start_terminal_raster(
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    source_id = (
        f"text_span:1:{run.extraction.pages[0].page_data.text_items[0].id}"
    )
    failure = TextDeliveryResult(
        source_id=source_id,
        requested_representation="labels",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=False,
        failure_reason="requested representation failed without impossibility proof",
    )
    output = tmp_path / "unproven_failure.dxf"
    prior_output = b"prior accepted DXF must survive unproven fallback\r\n"
    output.write_bytes(prior_output)
    with (
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter.build_text",
            return_value=failure,
        ),
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter.fitz.open",
            side_effect=AssertionError("terminal Raster must not be attempted"),
        ),
    ):
        with pytest.raises(RuntimeError, match="without impossibility proof"):
            export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_images=False, text_mode="labels"),
            )

    assert output.read_bytes() == prior_output


def test_duplicate_source_identity_aborts_without_replacing_prior_output(
    tmp_path,
) -> None:
    pdf_path = tmp_path / "duplicate_source.pdf"
    pdf = __import__("pymupdf").open()
    pdf.new_page(width=120, height=80)
    pdf.save(str(pdf_path))
    pdf.close()
    page = ExtractedPage(
        page_data=PageData(
            page_number=3,
            width=120.0,
            height=80.0,
            text_items=[_item(item_id=17), _item(item_id=17, width=19.0)],
        ),
        profile=SimpleNamespace(titleblock_likely=False),
        resolved_mode="vector",
    )
    extraction = DocumentExtraction(
        str(pdf_path), pages=[page], requested_mode="vector"
    )
    output = tmp_path / "duplicate_source.dxf"
    prior_output = b"prior accepted DXF must survive duplicate identity\r\n"
    output.write_bytes(prior_output)

    with pytest.raises(RuntimeError, match="duplicate stable text source identity"):
        export_to_dxf(
            extraction,
            str(output),
            DxfExportOptions(include_images=False, text_mode="labels"),
        )

    assert output.read_bytes() == prior_output


def test_serialized_candidate_must_reconcile_delivery_handles_before_publish(
    tmp_path,
) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf = __import__("pymupdf").open()
    pdf.new_page(width=120, height=80)
    pdf.save(str(pdf_path))
    pdf.close()
    extraction = DocumentExtraction(
        str(pdf_path),
        pages=[
            ExtractedPage(
                page_data=PageData(
                    page_number=3,
                    width=120.0,
                    height=80.0,
                    text_items=[_item()],
                ),
                profile=SimpleNamespace(titleblock_likely=False),
                resolved_mode="vector",
            )
        ],
        requested_mode="vector",
    )
    output = tmp_path / "accepted.dxf"
    prior_output = b"prior accepted DXF must remain unchanged\r\n"
    output.write_bytes(prior_output)

    with patch(
        "librecad_pdf_importer.exporters.dxf_exporter.ezdxf.readfile",
        return_value=ezdxf.new("R2010"),
    ):
        with pytest.raises(RuntimeError, match="serialized text delivery"):
            export_to_dxf(
                extraction,
                str(output),
                DxfExportOptions(
                    include_images=False,
                    text_mode="labels",
                    dxf_version="R2010",
                ),
            )

    assert output.read_bytes() == prior_output


def test_serialized_native_text_fit_width_cannot_change_after_verification(
    tmp_path,
) -> None:
    result, _, drawing, _ = _run_for_items(tmp_path, "labels", [_item()])
    native = next(iter(drawing.modelspace()))
    assert native.dxftype() == "TEXT"
    assert int(native.dxf.halign) == 5
    native.dxf.align_point = (
        float(native.dxf.align_point.x) + 1.0,
        float(native.dxf.align_point.y),
        0.0,
    )

    with pytest.raises(RuntimeError, match="FIT width changed"):
        _verify_serialized_text_deliveries(drawing, result.text_deliveries)


def test_terminal_raster_rejects_partially_clipped_source_bbox(tmp_path) -> None:
    run = _real_text_extraction(tmp_path)
    item = run.extraction.pages[0].page_data.text_items[0]
    assert item.source_bbox_pdf is not None
    run.extraction.pages[0].page_data.text_items[0] = __import__(
        "dataclasses"
    ).replace(
        item,
        source_bbox_pdf=(
            -5.0,
            item.source_bbox_pdf[1],
            item.source_bbox_pdf[2],
            item.source_bbox_pdf[3],
        ),
    )
    source_id = f"text_span:1:{item.id}"
    failure = TextDeliveryResult(
        source_id=source_id,
        requested_representation="labels",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=True,
        failure_reason="all structural representations proven impossible",
    )
    output = tmp_path / "accepted.dxf"
    prior_output = b"prior accepted DXF\r\n"
    output.write_bytes(prior_output)

    with patch(
        "librecad_pdf_importer.exporters.dxf_exporter.build_text",
        return_value=failure,
    ):
        with pytest.raises(RuntimeError, match="not fully contained"):
            export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(include_images=False, text_mode="labels"),
            )

    assert output.read_bytes() == prior_output


@pytest.mark.parametrize("mode", ["text", "labels", "3d_text", "glyphs", "geometry"])
def test_real_embedded_chart_fonts_drive_the_requested_dxf_representation(
    tmp_path,
    mode: str,
) -> None:
    chart = Path(
        r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\Welding-Symbol-Chart.pdf"
    )
    run = run_import(
        str(chart),
        mode="vector",
        overrides={"pages": "1", "import_text": True, "text_mode": mode},
    )
    page = run.extraction.pages[0]
    by_font = {}
    for item in page.page_data.text_items:
        by_font.setdefault(item.font_name, item)
    assert set(by_font) == {
        "Siwa-Regular",
        "Siwa-Bold",
        "ArialMT",
        "MyriadPro-Regular",
    }
    page.page_data.text_items = list(by_font.values())
    page.page_data.primitives = []
    page.images = []
    output = tmp_path / f"embedded_{mode}.dxf"

    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_images=False,
            text_mode=mode,
            dxf_version="R2010",
            provenance_opts=run.config,
        ),
    )

    assert output.is_file()
    assert len(result.text_deliveries) == 4
    expected_final = "text" if mode in {"labels", "3d_text"} else mode
    assert all(
        item["final_representation"] == expected_final
        for item in result.text_deliveries
    )
    assert all(
        item["fallback_used"] is (expected_final != mode)
        for item in result.text_deliveries
    )
    asset_paths = set()
    asset_ids = set()
    for item in result.text_deliveries:
        attempt = [
            value for value in item["attempts"] if value["outcome"] == "verified"
        ][0]
        evidence = attempt["evidence"]
        assert evidence["font_resolution_source"] == "embedded_pdf_font"
        assert evidence["font_exact_match"] is True
        visual_evidence = (
            evidence
            if expected_final in {"text", "labels", "3d_text"}
            else evidence["source_text_evidence"]
        )
        assert visual_evidence["source_font_em_height"] > 0.0
        assert visual_evidence["source_cap_height_ratio"] > 0.0
        assert visual_evidence["expected_height"] == pytest.approx(
            visual_evidence["source_font_em_height"]
            * visual_evidence["source_cap_height_ratio"]
        )
        assert visual_evidence["actual_height"] == pytest.approx(
            visual_evidence["expected_height"]
        )
        asset_path = Path(evidence["resolved_font_filename"])
        assert asset_path.is_file()
        assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == evidence[
            "font_asset_sha256"
        ]
        asset_paths.add(asset_path)
        asset_ids.add(evidence["font_asset_id"])
    assert len(asset_paths) == 4
    assert len(asset_ids) == 4
    assert all(output.with_name(f"{output.stem}_assets") in path.parents for path in asset_paths)

    drawing = ezdxf.readfile(output)
    if mode in {"text", "labels", "3d_text"}:
        assert {entity.dxftype() for entity in drawing.modelspace()} == {"TEXT"}
        assert {
            drawing.styles.get(entity.dxf.style).dxf.font
            for entity in drawing.modelspace()
        } == {"unicode"}
        verified_evidence = [
            next(
                attempt["evidence"]
                for attempt in item["attempts"]
                if attempt["outcome"] == "verified"
            )
            for item in result.text_deliveries
        ]
        assert all(
            evidence["parent_native_text_delivery_verified"] is True
            for evidence in verified_evidence
        )
        assert all(
            evidence["parent_visual_fidelity_verified"] is False
            for evidence in verified_evidence
        )
        if mode == "labels":
            assert all(
                item["attempts"][0]["evidence"][
                    "parent_native_label_entity_available"
                ]
                is False
                for item in result.text_deliveries
            )
        if mode == "3d_text":
            assert all(
                item["attempts"][0]["evidence"][
                    "parent_native_text_delivery_verified"
                ]
                is False
                for item in result.text_deliveries
            )
    assert not list(tmp_path.rglob("*.tmp"))


def test_real_welding_chart_requested_item_raster_is_source_bound(tmp_path) -> None:
    chart = Path(
        r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\Welding-Symbol-Chart.pdf"
    )
    run = run_import(
        str(chart),
        mode="vector",
        overrides={"pages": "1", "import_text": True, "text_mode": "raster"},
    )
    page = run.extraction.pages[0]
    source_item = next(item for item in page.page_data.text_items if item.text.strip())
    page.page_data.text_items = [source_item]
    page.page_data.primitives = []
    page.images = []
    output = tmp_path / "welding-requested-item-raster.dxf"

    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_images=False,
            text_mode="raster",
            dxf_version="R2010",
            provenance_opts=run.config,
        ),
    )

    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    assert delivery["requested_representation"] == "raster"
    assert delivery["final_representation"] == "raster"
    assert delivery["fallback_used"] is False
    evidence = delivery["attempts"][-1]["evidence"]
    assert evidence["source_pdf_sha256"] == hashlib.sha256(chart.read_bytes()).hexdigest()
    assert evidence["source_page_number"] == 1
    assert evidence["source_id"] == delivery["source_id"]
    assert evidence["visible_ink_verified"] is True
    drawing = ezdxf.readfile(output)
    assert [entity.dxftype() for entity in drawing.modelspace()] == ["IMAGE"]
    run.close()
    assert Path(evidence["asset_path"]).is_file()


def test_real_image_only_chart_explicit_page_raster_survives_source_cleanup(tmp_path) -> None:
    chart = Path(r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\AWSWeldSymbolchart.pdf")
    run = run_import(
        str(chart),
        mode="raster",
        overrides={"pages": "1", "import_text": False},
    )
    page = run.extraction.pages[0]
    assert page.resolved_mode == "raster"
    assert page.raster_fallback_failed is False
    assert page.page_data.primitives == []
    assert page.page_data.text_items == []
    assert len(page.images) == 1
    source_asset = Path(page.images[0].path)
    source_sha = hashlib.sha256(source_asset.read_bytes()).hexdigest()
    output = tmp_path / "aws-explicit-page-raster.dxf"

    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_text=False,
            include_images=True,
            dxf_version="R2010",
            provenance_opts=run.config,
        ),
    )

    assert result.image_count == 1
    drawing = ezdxf.readfile(output)
    images = list(drawing.modelspace().query("IMAGE"))
    assert len(images) == 1
    image = images[0]
    image_def = drawing.entitydb.get(str(image.dxf.image_def_handle))
    staged_asset = Path(str(image_def.dxf.filename)).resolve()
    assert hashlib.sha256(staged_asset.read_bytes()).hexdigest() == source_sha
    actual_width = math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y) * float(
        image.dxf.image_size.x
    )
    actual_height = math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y) * float(
        image.dxf.image_size.y
    )
    with __import__("pymupdf").open(str(chart)) as source_pdf:
        source_rect = source_pdf[0].rect
    assert actual_width == pytest.approx(float(source_rect.width) * 25.4 / 72.0)
    assert actual_height == pytest.approx(float(source_rect.height) * 25.4 / 72.0)
    report_path = tmp_path / "aws-explicit-page-raster_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["result"]["images"] == 1
    assert report["extra"]["result_status"] == "success"
    assert report["extra"]["diagnostics"]["quality_level"] == "raster"
    assert "1 raster/image placement" in report["extra"]["human_summary"]
    run.close()
    assert not source_asset.exists()
    assert staged_asset.is_file()

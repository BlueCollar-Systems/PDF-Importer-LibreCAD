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
import dxf_text_builder
from ezdxf.tools.text_size import text_size
from fontTools.ttLib import TTFont

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
    TextRepresentationDeliveryError,
    _attempt_terminal_text_raster,
    _render_source_text_clip,
    _verify_serialized_text_deliveries,
    export_to_dxf,
)
from librecad_pdf_importer.importer import ImportRun, run_import, write_import_report
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.embedded_fonts import EmbeddedFontFailure
from pdfcadcore.fitz_loader import import_fitz
from pdfcadcore.import_report import build_actual_text_entity_types
from pdfcadcore.primitive_extractor import (
    MM_PER_PT,
    _extract_text,
    _page_rotation_transform,
    _transform_pdf_point,
)
from pdfcadcore.primitives import NormalizedText, PageData, TextCharLayout
from pdfcadcore.text_scale import (
    calibrate_text_size_to_bbox,
    effective_span_font_size_pt,
    fit_font_size_to_span_bbox,
)


fitz = import_fitz()


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
        font_name="BCS Deterministic Test",
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


def test_installed_name_match_cannot_be_verified_with_false_visual_fidelity() -> None:
    installed_match = _ExactFontResolution(
        source_name="Arial",
        family="Arial",
        filename="arial.ttf",
        exact=True,
        resolution_source="installed_exact_font",
        reason="exact installed source-font family/style match",
    )
    with patch("dxf_text_builder._resolve_item_font", return_value=installed_match):
        _, msp, result = _deliver("text", target_app="generic")

    native = result.attempts[0]
    evidence = native.evidence
    assert native.outcome == "impossible"
    assert native.cleanup_verified is True
    assert evidence["parent_native_text_delivery_verified"] is False
    assert evidence["parent_native_font_substituted"] is True
    assert evidence["parent_source_font_equivalence_verified"] is False
    assert evidence["parent_visual_fidelity_verified"] is False
    assert evidence["fallback_authorized_for_this_item"] is True
    assert not any(
        attempt.outcome == "verified"
        for attempt in result.attempts
    )
    assert result.verified is False
    assert result.final_representation is None
    assert list(msp) == []


def test_authenticated_base14_renderer_font_is_source_authoritative(
    deterministic_exact_font,
) -> None:
    base14 = _ExactFontResolution(
        source_name="Helvetica",
        family="Helvetica",
        style="Regular",
        filename=str(deterministic_exact_font),
        exact=True,
        source_cap_height_ratio=0.7,
        source_origin="pdf_base14_renderer_font",
        resolution_source="pdf_base14_renderer_font",
        reason="authenticated PDF Base14 renderer program",
    )
    with patch("dxf_text_builder._resolve_item_font", return_value=base14):
        _, msp, result = _deliver("text", target_app="generic")

    assert result.verified is True
    assert result.final_representation == "text"
    assert [entity.dxftype() for entity in msp] == ["TEXT"]
    evidence = result.attempts[0].evidence
    assert evidence["parent_native_font_substituted"] is False
    assert evidence["parent_source_font_equivalence_verified"] is True
    assert evidence["parent_visual_fidelity_verified"] is True


def test_impossible_attempt_with_incomplete_cleanup_cannot_advance() -> None:
    dirty = TextDeliveryAttempt(
        source_id="text_span:3:17",
        requested_representation="labels",
        attempted_representation="labels",
        strategy="native_dxf_text",
        outcome="impossible",
        reason="item-specific representation impossibility",
        created_entity_handles=["AA"],
        removed_entity_handles=[],
        cleanup_verified=False,
    )
    with patch("dxf_text_builder._attempt_labels", return_value=dirty) as attempt_labels:
        _, msp, result = _deliver("labels", target_app="librecad")

    assert result.verified is False
    assert result.final_representation is None
    assert result.terminal_fallback_authorized is False
    assert "cleanup" in result.failure_reason.lower()
    assert attempt_labels.call_count == 1
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "labels"
    ]
    assert list(msp) == []


def _deliver(
    mode: str,
    item: NormalizedText | None = None,
    *,
    target_app: str = "generic",
    config: ImportConfig | None = None,
):
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    result = build_text(
        item or _item(),
        msp,
        "TEXT",
        config or ImportConfig(text_mode=mode),
        target_app=target_app,
        dxf_version="R2010",
        return_delivery_result=True,
    )
    assert isinstance(result, TextDeliveryResult)
    return doc, msp, result


def _positioned_repeated_item() -> NormalizedText:
    first_quad = ((10.0, 22.0), (13.0, 22.0), (13.0, 18.0), (10.0, 18.0))
    second_quad = ((18.0, 30.0), (18.0, 33.0), (22.0, 33.0), (22.0, 30.0))
    return NormalizedText(
        id=91,
        text="AA",
        normalized="AA",
        insertion=(10.0, 20.0),
        bbox=(10.0, 18.0, 22.0, 33.0),
        font_size=4.0,
        rotation=0.0,
        font_name="BCS Deterministic Test",
        page_number=3,
        target_quad_model=((10.0, 33.0), (22.0, 33.0), (22.0, 18.0), (10.0, 18.0)),
        advance_width=12.0,
        glyph_height=15.0,
        source_char_layout=(
            TextCharLayout(
                text="A",
                glyph_id=65,
                source_origin_pdf=(1.0, 2.0),
                source_bbox_pdf=(1.0, 0.0, 4.0, 4.0),
                source_quad_pdf=((1.0, 4.0), (4.0, 4.0), (4.0, 0.0), (1.0, 0.0)),
                target_origin=(10.0, 20.0),
                target_quad=first_quad,
                advance_width=3.0,
                glyph_height=4.0,
            ),
            TextCharLayout(
                text="A",
                glyph_id=65,
                source_origin_pdf=(8.0, 9.0),
                source_bbox_pdf=(6.0, 9.0, 10.0, 12.0),
                source_quad_pdf=((6.0, 9.0), (6.0, 12.0), (10.0, 12.0), (10.0, 9.0)),
                target_origin=(20.0, 30.0),
                target_quad=second_quad,
                advance_width=3.0,
                glyph_height=4.0,
            ),
        ),
        requires_individual_positioning=True,
    )


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize(
    "corruption",
    [
        ezdxf.math.Matrix44.translate(9.0, -4.0, 0.0),
        ezdxf.math.Matrix44.z_rotate(math.radians(37.0)),
        ezdxf.math.Matrix44.scale(1.8, 0.6, 1.0),
    ],
    ids=["translated", "rotated", "scaled"],
)
def test_outline_verification_rejects_post_construction_affine_corruption(
    mode,
    corruption,
) -> None:
    original = dxf_text_builder._to_outline_entities

    def corrupt_after_construction(paths, *, is_r12, attribs):
        entities = original(paths, is_r12=is_r12, attribs=attribs)
        for entity in entities:
            entity.transform(corruption)
        return entities

    with patch(
        "dxf_text_builder._to_outline_entities",
        side_effect=corrupt_after_construction,
    ):
        _, msp, result = _deliver(mode)

    assert result.verified is False
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)
    assert all(attempt.outcome == "failed" for attempt in result.attempts)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_outline_verification_rejects_source_to_path_affine_corruption(mode) -> None:
    """Pre-entity paths must remain bound to source placement, not themselves."""

    original = dxf_text_builder._source_bound_string_path_expectation

    def corrupt_source_to_path(*args, **kwargs):
        paths, expected_bbox, advance, scale = original(*args, **kwargs)
        corruption = ezdxf.math.Matrix44.translate(47.0, -31.0, 0.0)
        corrupted = [path.transform(corruption) for path in paths]
        return corrupted, expected_bbox, advance, scale

    with (
        patch(
            "dxf_text_builder.text2path.make_paths_from_entity",
            side_effect=RuntimeError("force the source-layout string route"),
        ),
        patch(
            "dxf_text_builder._source_bound_string_path_expectation",
            side_effect=corrupt_source_to_path,
        ),
    ):
        _, msp, result = _deliver(mode)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_outline_verification_rejects_corrupted_underlying_string_renderer(
    mode,
) -> None:
    """Renderer output cannot also be the oracle that certifies that output."""

    original = dxf_text_builder.text2path.make_paths_from_str
    corruption = ezdxf.math.Matrix44.translate(47.0, -31.0, 0.0)

    def corrupt_renderer_output(*args, **kwargs):
        paths = list(original(*args, **kwargs))
        return [path.transform(corruption) for path in paths]

    with (
        patch(
            "dxf_text_builder.text2path.make_paths_from_entity",
            side_effect=RuntimeError("force the source-layout string route"),
        ),
        patch(
            "dxf_text_builder.text2path.make_paths_from_str",
            side_effect=corrupt_renderer_output,
        ),
    ):
        _, msp, result = _deliver(mode)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_outline_verification_enforces_authoritative_target_quad(mode) -> None:
    item = _item(rotation=0.0)
    item.target_quad_model = (
        (112.25, 24.58),
        (119.75, 24.58),
        (119.75, 24.50),
        (112.25, 24.50),
    )

    _, msp, result = _deliver(mode, item)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_outline_verification_rejects_bbox_preserving_shape_corruption(mode) -> None:
    """Matching extents cannot certify the outline's interior source geometry."""

    original_outlines = dxf_text_builder._to_outline_entities
    original_fills = dxf_text_builder._to_solid_fill_entities
    reflection = {}

    def reflect_outlines(paths, *, is_r12, attribs):
        entities = original_outlines(paths, is_r12=is_r12, attribs=attribs)
        bbox = dxf_text_builder._bbox_tuple(entities)
        assert bbox is not None
        center_x = (bbox[0] + bbox[2]) / 2.0
        transform = (
            ezdxf.math.Matrix44.translate(-center_x, 0.0, 0.0)
            * ezdxf.math.Matrix44.scale(-1.0, 1.0, 1.0)
            * ezdxf.math.Matrix44.translate(center_x, 0.0, 0.0)
        )
        reflection["transform"] = transform
        for entity in entities:
            entity.transform(transform)
        return entities

    def reflect_fills(paths, *, is_r12, attribs):
        entities = original_fills(paths, is_r12=is_r12, attribs=attribs)
        transform = reflection["transform"]
        for entity in entities:
            entity.transform(transform)
        return entities

    with (
        patch(
            "dxf_text_builder._to_outline_entities",
            side_effect=reflect_outlines,
        ),
        patch(
            "dxf_text_builder._to_solid_fill_entities",
            side_effect=reflect_fills,
        ),
    ):
        _, msp, result = _deliver(mode)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_outline_verification_rejects_corrupted_hatch_boundary(mode) -> None:
    """A compact HATCH hole/external boundary is part of its visible fill."""

    original = dxf_text_builder._to_solid_fill_entities

    def corrupt_fill_boundary(paths, *, is_r12, attribs):
        entities = original(paths, is_r12=is_r12, attribs=attribs)
        fill = entities[0]
        boundary = fill.paths[0]
        point = boundary.vertices[0]
        boundary.vertices[0] = (point[0] + 47.0, point[1] - 31.0, point[2])
        return entities

    with patch(
        "dxf_text_builder._to_solid_fill_entities",
        side_effect=corrupt_fill_boundary,
    ):
        _, msp, result = _deliver(mode)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


def test_outline_verification_rejects_large_relative_error_below_flattening_floor() -> None:
    """A fixed curve tolerance cannot hide an 11.9% shift of straight glyphs."""

    original_outlines = dxf_text_builder._to_outline_entities
    original_fills = dxf_text_builder._to_solid_fill_entities
    corruption = ezdxf.math.Matrix44.translate(0.0095, 0.0, 0.0)

    def shift_outlines(paths, *, is_r12, attribs):
        entities = original_outlines(paths, is_r12=is_r12, attribs=attribs)
        for entity in entities:
            entity.transform(corruption)
        return entities

    def shift_fills(paths, *, is_r12, attribs):
        entities = original_fills(paths, is_r12=is_r12, attribs=attribs)
        for entity in entities:
            entity.transform(corruption)
        return entities

    with (
        patch(
            "dxf_text_builder._to_outline_entities",
            side_effect=shift_outlines,
        ),
        patch(
            "dxf_text_builder._to_solid_fill_entities",
            side_effect=shift_fills,
        ),
    ):
        _, msp, result = _deliver("geometry", _item(height=0.08))

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


@pytest.mark.parametrize("requested", ["glyphs", "labels"])
def test_positioned_repeated_characters_keep_source_order_origin_and_rotation(
    requested,
) -> None:
    item = _positioned_repeated_item()
    with patch(
        "dxf_text_builder.text2path.make_paths_from_entity",
        side_effect=RuntimeError("force the source-layout string route"),
    ):
        _, _, result = _deliver(requested, item, target_app="librecad")

    assert result.verified is True
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    assert final.attempted_representation == "glyphs"
    assert final.evidence["requires_individual_positioning"] is True
    assert final.evidence["source_char_layout_verified"] is True
    ownership = final.evidence["outline_character_ownership"]
    assert [entry["index"] for entry in ownership] == [0, 1]
    assert [entry["text"] for entry in ownership] == ["A", "A"]
    assert [entry["glyph_id"] for entry in ownership] == [65, 65]
    assert [entry["target_origin"] for entry in ownership] == [
        [10.0, 20.0],
        [20.0, 30.0],
    ]
    assert [entry["rotation_degrees"] for entry in ownership] == pytest.approx(
        [0.0, 90.0]
    )
    assert all(entry["entity_handles"] for entry in ownership)


def test_positioned_layout_never_concatenates_visible_source_characters() -> None:
    calls = []
    original = dxf_text_builder.text2path.make_paths_from_str

    def record_source_text(text, *args, **kwargs):
        calls.append(text)
        return original(text, *args, **kwargs)

    with (
        patch(
            "dxf_text_builder.text2path.make_paths_from_entity",
            side_effect=RuntimeError("force the source-layout string route"),
        ),
        patch(
            "dxf_text_builder.text2path.make_paths_from_str",
            side_effect=record_source_text,
        ),
    ):
        _, _, result = _deliver("glyphs", _positioned_repeated_item())

    assert result.verified is True
    assert calls == []
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    assert [
        row["selection_source"]
        for row in final.evidence["physical_glyph_ink_proof"]["glyphs"]
    ] == ["source_char_layout_glyph_id", "source_char_layout_glyph_id"]


def test_positioned_layout_rejects_one_entry_that_concatenates_source_characters() -> None:
    """One ownership row cannot silently stand in for two positioned characters."""

    item = _positioned_repeated_item()
    combined_quad = tuple(item.target_quad_model)
    combined = TextCharLayout(
        text="AA",
        glyph_id=None,
        source_origin_pdf=(10.0, 20.0),
        source_bbox_pdf=(10.0, 18.0, 22.0, 33.0),
        source_quad_pdf=combined_quad,
        target_origin=(10.0, 20.0),
        target_quad=combined_quad,
        advance_width=12.0,
        glyph_height=15.0,
    )
    item = __import__("dataclasses").replace(
        item,
        source_char_layout=(combined,),
    )
    calls = []
    original = dxf_text_builder.text2path.make_paths_from_str

    def record_source_text(text, *args, **kwargs):
        calls.append(text)
        return original(text, *args, **kwargs)

    with patch(
        "dxf_text_builder.text2path.make_paths_from_str",
        side_effect=record_source_text,
    ):
        _, msp, result = _deliver("glyphs", item)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert "AA" not in calls


def test_positioned_layout_uses_contoured_source_glyph_bound_to_unicode_space() -> None:
    item = _positioned_repeated_item()
    space = __import__("dataclasses").replace(
        item.source_char_layout[1],
        text=" ",
        glyph_id=32,
    )
    item = __import__("dataclasses").replace(
        item,
        text="A ",
        normalized="A",
        source_char_layout=(item.source_char_layout[0], space),
    )
    calls = []
    original = dxf_text_builder.text2path.make_paths_from_str

    def record_source_text(text, *args, **kwargs):
        calls.append(text)
        return original(text, *args, **kwargs)

    with patch(
        "dxf_text_builder.text2path.make_paths_from_str",
        side_effect=record_source_text,
    ):
        _, _, result = _deliver("glyphs", item)

    assert result.verified is True
    assert calls == []
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    ownership = final.evidence["outline_character_ownership"]
    assert ownership[0]["entity_handles"]
    assert ownership[0]["visible_ink_expected"] is True
    assert ownership[1]["entity_handles"]
    assert ownership[1]["visible_ink_expected"] is True
    assert ownership[1]["zero_ink_verified"] is False
    proof = final.evidence["physical_glyph_ink_proof"]
    assert proof["glyphs"][1]["glyph_id"] == 32
    assert proof["glyphs"][1]["status"] == "visible"


def test_positioned_layout_records_physically_empty_source_glyph_without_artifacts() -> None:
    item = _positioned_repeated_item()
    space = __import__("dataclasses").replace(
        item.source_char_layout[1],
        text=" ",
        glyph_id=1,
    )
    item = __import__("dataclasses").replace(
        item,
        text="A ",
        normalized="A",
        source_char_layout=(item.source_char_layout[0], space),
    )

    _, _, result = _deliver("glyphs", item)

    assert result.verified is True
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    ownership = final.evidence["outline_character_ownership"]
    assert ownership[0]["entity_handles"]
    assert ownership[0]["visible_ink_expected"] is True
    assert ownership[1]["entity_handles"] == []
    assert ownership[1]["visible_ink_expected"] is False
    assert ownership[1]["zero_ink_verified"] is True
    proof = final.evidence["physical_glyph_ink_proof"]
    assert proof["glyphs"][1]["glyph_id"] == 1
    assert proof["glyphs"][1]["status"] == "empty"


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_positioned_layout_enforces_each_character_target_height(mode) -> None:
    item = _positioned_repeated_item()
    taller = __import__("dataclasses").replace(
        item.source_char_layout[1],
        target_origin=(22.0, 30.0),
        target_quad=((18.0, 30.0), (18.0, 33.0), (26.0, 33.0), (26.0, 30.0)),
        glyph_height=8.0,
    )
    item = __import__("dataclasses").replace(
        item,
        bbox=(10.0, 18.0, 26.0, 33.0),
        source_char_layout=(item.source_char_layout[0], taller),
    )

    _, msp, result = _deliver(mode, item)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert list(msp) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)


def test_fractional_source_page_cannot_be_truncated_into_an_existing_identity() -> None:
    item = _item()
    item.page_number = 3.75

    _, msp, result = _deliver("geometry", item)

    assert result.verified is False, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation is None
    assert result.source_id == ""
    assert list(msp) == []


def test_positioned_layout_rejects_mismatched_source_truth_before_path_creation() -> None:
    item = _positioned_repeated_item()
    mismatched = __import__("dataclasses").replace(
        item.source_char_layout[1],
        text="B",
        glyph_id=66,
    )
    item = __import__("dataclasses").replace(
        item,
        source_char_layout=(item.source_char_layout[0], mismatched),
    )

    with patch("dxf_text_builder.text2path.make_paths_from_str") as make_paths:
        _, msp, result = _deliver("glyphs", item, target_app="librecad")

    assert result.verified is False
    assert result.final_representation is None
    assert list(msp) == []
    make_paths.assert_not_called()
    outline_attempts = [
        attempt
        for attempt in result.attempts
        if attempt.attempted_representation in {"glyphs", "geometry"}
    ]
    assert outline_attempts
    assert all(attempt.outcome == "impossible" for attempt in outline_attempts)
    assert all(attempt.cleanup_verified for attempt in outline_attempts)


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


def test_librecad_visible_label_uses_exact_glyphs_after_native_text_impossibility() -> None:
    _, msp, result = _deliver("labels", target_app="librecad")

    assert result.verified is True
    assert result.requested_representation == "labels"
    assert result.final_representation == "glyphs"
    assert result.fallback_used is True
    assert [entity.dxftype() for entity in msp] == ["INSERT"]

    label_attempt, native, glyphs = result.attempts
    assert label_attempt.attempted_representation == "labels"
    assert label_attempt.outcome == "impossible"
    assert label_attempt.cleanup_verified is True
    assert label_attempt.evidence["item_specific_capability_evaluation"] is True
    assert label_attempt.evidence["parent_native_label_entity_available"] is False
    assert label_attempt.evidence["text_alias_accepted_as_label"] is False
    assert label_attempt.entity_handles == []

    assert native.attempted_representation == "text"
    assert native.outcome == "impossible"
    assert native.type_verified is True
    assert native.visual_verified is False
    assert native.cleanup_verified is True
    assert native.evidence["item_specific_creation_attempted"] is True
    assert native.evidence["target_app"] == "librecad"
    assert native.evidence["parent_native_font_required_format"] == "lff"
    assert native.evidence["parent_native_font_candidate_format"] == "lff"
    assert native.evidence["parent_native_font_format_verified"] is True
    assert native.evidence["parent_native_text_delivery_verified"] is False
    assert native.evidence["parent_visual_fidelity_verified"] is False
    assert native.evidence["parent_source_font_equivalence_verified"] is False
    assert native.evidence["fallback_authorized_for_this_item"] is True
    assert native.evidence["parent_native_font_substituted"] is True
    assert native.evidence["parent_native_font_candidate"] == "unicode"
    assert set(native.removed_entity_handles) == set(native.created_entity_handles)
    assert not any(entity.dxftype() == "TEXT" for entity in msp)
    assert glyphs.attempted_representation == "glyphs"
    assert glyphs.outcome == "verified"
    assert glyphs.type_verified is True
    assert glyphs.visual_verified is True
    assert glyphs.evidence["font_resolution_source"] == "test_fixture"
    assert glyphs.evidence["font_exact_match"] is True


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


def test_librecad_rejects_unverified_native_3d_and_flat_text_then_uses_glyphs() -> None:
    _, msp, result = _deliver("3d_text", target_app="librecad")

    assert result.verified is True
    assert result.requested_representation == "3d_text"
    assert result.final_representation == "glyphs"
    assert result.fallback_used is True
    assert [attempt.attempted_representation for attempt in result.attempts] == [
        "3d_text",
        "text",
        "glyphs",
    ]
    assert [attempt.outcome for attempt in result.attempts] == [
        "impossible",
        "impossible",
        "verified",
    ]
    native_3d = result.attempts[0]
    assert native_3d.evidence["item_specific_creation_attempted"] is True
    assert native_3d.evidence["extrusion_depth_verified"] is True
    assert native_3d.evidence["parent_native_3d_display_verified"] is False
    assert native_3d.evidence["parent_visual_fidelity_verified"] is False
    assert native_3d.cleanup_verified is True
    native_text = result.attempts[1]
    assert native_text.evidence["parent_native_text_delivery_verified"] is False
    assert native_text.evidence["parent_visual_fidelity_verified"] is False
    assert native_text.evidence["fallback_authorized_for_this_item"] is True
    assert native_text.cleanup_verified is True
    assert set(native_text.removed_entity_handles) == set(
        native_text.created_entity_handles
    )
    assert [entity.dxftype() for entity in msp] == ["INSERT"]


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
        text=" ",
        normalized="",
        source_glyph_id=1,
    )
    _, msp, result = _deliver("labels", item)

    assert result.verified is True
    assert result.final_representation == "text"
    assert result.fallback_used is True
    entity = next(iter(msp))
    assert entity.dxftype() == "TEXT"
    assert entity.dxf.text == " "
    assert text_size(entity).width == pytest.approx(0.0)
    assert result.attempts[-1].evidence["physical_zero_ink_verified"] is True
    assert result.attempts[-1].evidence["source_zero_ink_physically_proven"] is True


def test_librecad_empty_source_glyph_does_not_waive_visible_parent_lff() -> None:
    """A source-empty glyph cannot make a visible unicode.lff glyph disappear."""

    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text="A",
        normalized="A",
        source_glyph_id=1,
    )

    _, msp, result = _deliver("text", item, target_app="librecad")

    assert result.verified is False
    assert result.final_representation is None
    assert result.terminal_fallback_authorized is True
    assert list(msp) == []
    native = next(
        attempt
        for attempt in result.attempts
        if attempt.attempted_representation == "text"
    )
    assert native.outcome == "impossible"
    assert native.cleanup_verified is True
    assert native.evidence["source_zero_ink_physically_proven"] is True
    assert native.evidence["parent_delivered_lff_zero_ink_proven"] is False
    assert native.evidence["parent_native_lff_ink_proof_valid"] is True
    assert native.evidence["parent_native_lff_ink_proof"]["status"] == "visible"
    assert native.evidence["fallback_authorized_for_this_item"] is True


def test_serialized_verifier_rejects_text_entity_relabelled_as_native_label(
    tmp_path,
) -> None:
    """DXF TEXT cannot become a native Label through report-only relabelling."""

    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text=" ",
        normalized="",
        source_glyph_id=1,
    )
    doc, _msp, result = _deliver("labels", item)
    assert result.final_representation == "text"
    output = tmp_path / "forged-label-alias.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    forged = result.to_dict()
    forged["final_representation"] = "labels"

    with pytest.raises(RuntimeError, match="native Label|Label.*unsupported"):
        _verify_serialized_text_deliveries(reopened, [forged])


def test_librecad_space_bound_to_visible_source_glyph_uses_exact_glyph_geometry(
    deterministic_exact_font,
    tmp_path,
) -> None:
    font = TTFont(str(deterministic_exact_font), lazy=False, recalcTimestamp=False)
    try:
        glyph_id = font.getGlyphOrder().index(font.getBestCmap()[ord("A")])
    finally:
        font.close()
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text=" ",
        normalized="",
        source_glyph_id=glyph_id,
    )

    doc, msp, result = _deliver("text", item, target_app="librecad")

    assert result.verified is True
    assert result.final_representation == "glyphs"
    assert result.fallback_used is True
    native = result.attempts[0]
    assert native.attempted_representation == "text"
    assert native.outcome == "impossible"
    assert native.evidence["source_zero_ink_physically_proven"] is False
    assert native.evidence["parent_native_lff_ink_proof"]["status"] == "empty"
    assert native.evidence["parent_delivered_lff_zero_ink_proven"] is True
    assert native.evidence["parent_visual_fidelity_verified"] is False
    assert [entity.dxftype() for entity in msp] == ["INSERT"]

    output = tmp_path / "space-bound-to-visible-source-glyph.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_parent_lff_proof_rejects_missing_exact_asset() -> None:
    config = ImportConfig(text_mode="text")
    config._librecad_lff_font_paths = {  # noqa: SLF001
        "unicode": r"C:\definitely-missing-bcs-review\unicode.lff"
    }
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text=" ",
        normalized="",
        source_glyph_id=1,
    )

    _, msp, result = _deliver(
        "text",
        item,
        target_app="librecad",
        config=config,
    )

    assert result.verified is False
    assert result.terminal_fallback_authorized is True
    assert list(msp) == []
    native = result.attempts[0]
    assert native.outcome == "impossible"
    assert native.evidence["parent_native_lff_ink_proof_valid"] is False
    assert native.evidence["parent_native_lff_ink_proof"]["status"] == "unproven"
    assert "unavailable" in native.evidence["parent_native_lff_ink_proof"]["reason"]


def test_serialized_native_zero_ink_revalidates_exact_parent_lff_asset(
    deterministic_exact_font,
    monkeypatch,
    tmp_path,
) -> None:
    source_lff = deterministic_exact_font.parent / "librecad-fonts" / "unicode.lff"
    delivered_lff = tmp_path / "unicode.lff"
    delivered_lff.write_bytes(source_lff.read_bytes())
    monkeypatch.setenv("LIBRECAD_FONT_DIR", str(tmp_path))
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text=" ",
        normalized="",
        source_glyph_id=1,
    )
    doc, _, result = _deliver("text", item, target_app="librecad")
    output = tmp_path / "native-zero-ink.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    _verify_serialized_text_deliveries(reopened, [result.to_dict()])

    delivered_lff.write_bytes(delivered_lff.read_bytes() + b"\n# tampered\n")
    with pytest.raises(RuntimeError, match="zero-ink proof"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_native_zero_ink_rejects_rewritten_parent_lff_evidence(
    deterministic_exact_font,
    tmp_path,
) -> None:
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text=" ",
        normalized="",
        source_glyph_id=1,
    )
    doc, _, result = _deliver("text", item, target_app="librecad")
    output = tmp_path / "native-zero-ink-rewritten-proof.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    delivery = result.to_dict()
    final = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )
    proof = final["evidence"]["parent_native_lff_ink_proof"]
    alternate_dir = tmp_path / "not-the-parent-font-directory"
    alternate_dir.mkdir()
    alternate_asset = alternate_dir / "unicode.lff"
    alternate_asset.write_bytes(
        (deterministic_exact_font.parent / "librecad-fonts" / "unicode.lff").read_bytes()
    )
    proof["font_asset_path"] = str(alternate_asset)
    proof.pop("proof_sha256")
    proof["proof_sha256"] = dxf_text_builder._canonical_sha256(proof)  # noqa: SLF001

    with pytest.raises(RuntimeError, match="zero-ink proof"):
        _verify_serialized_text_deliveries(reopened, [delivery])


def test_parent_lff_asset_is_parsed_once_per_exact_content(
    deterministic_exact_font,
    monkeypatch,
    tmp_path,
) -> None:
    source_lff = deterministic_exact_font.parent / "librecad-fonts" / "unicode.lff"
    font_dir = tmp_path / "large-parent-font"
    font_dir.mkdir()
    (font_dir / "unicode.lff").write_bytes(source_lff.read_bytes())
    monkeypatch.setenv("LIBRECAD_FONT_DIR", str(font_dir))
    item = __import__("dataclasses").replace(
        _item(width=2.5, rotation=17.0),
        text=" ",
        normalized="",
        source_glyph_id=1,
    )
    from ezdxf.fonts import lff

    with patch("ezdxf.fonts.lff.loads", wraps=lff.loads) as load_lff:
        first = _deliver("text", item, target_app="librecad")[2]
        second = _deliver("text", item, target_app="librecad")[2]

    assert first.verified is True
    assert second.verified is True
    assert load_lff.call_count == 1


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
        text=" ",
        normalized="",
        source_glyph_id=1,
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
    assert final.evidence["source_zero_ink_physically_proven"] is True
    assert final.evidence["parent_native_font_rendering_required"] is False
    assert final.evidence["parent_visual_fidelity_verified"] is True
    assert [entity.dxftype() for entity in msp] == ["TEXT"]
    assert next(iter(msp)).dxf.text == " "


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
    assert "HATCH" in glyph_types
    assert glyph_types <= {"LWPOLYLINE", "POLYLINE", "HATCH"}
    assert glyph_result.attempts[-1].evidence["solid_fill_verified"] is True
    assert glyph_result.attempts[-1].evidence["solid_fill_entity_type"] == "HATCH"

    geometry_entities = list(geometry_msp)
    assert geometry_result.final_representation == "geometry"
    assert geometry_result.support_entity_handles == []
    assert {entity.dxf.handle for entity in geometry_entities} == set(
        geometry_result.entity_handles
    )
    assert {entity.dxftype() for entity in geometry_entities} <= {
        "LWPOLYLINE",
        "POLYLINE",
        "HATCH",
    }
    assert any(entity.dxftype() == "HATCH" for entity in geometry_entities)
    assert "INSERT" not in {entity.dxftype() for entity in geometry_msp}


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_serialized_outline_verifier_rejects_reopened_contour_corruption(
    tmp_path,
    mode,
) -> None:
    """Persisted handles and entity types cannot certify changed source ink."""

    doc, _, result = _deliver(mode)
    output = tmp_path / f"{mode}-corrupted-after-reopen.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    if mode == "glyphs":
        insert = next(iter(reopened.modelspace()))
        entities = list(reopened.blocks.get(insert.dxf.name))
    else:
        entities = list(reopened.modelspace())
    outline = next(
        entity
        for entity in entities
        if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
    )
    if outline.dxftype() == "LWPOLYLINE":
        points = list(outline.get_points(format="xyseb"))
        points[0] = (points[0][0] + 47.0, *points[0][1:])
        outline.set_points(points, format="xyseb")
    else:
        vertex = next(iter(outline.vertices))
        location = vertex.dxf.location
        vertex.dxf.location = (location.x + 47.0, location.y, location.z)

    with pytest.raises(RuntimeError, match="geometry|contour|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("rotation", 47.0), ("xscale", 2.0), ("yscale", 0.5)],
)
def test_serialized_glyph_verifier_rejects_reopened_parent_transform_corruption(
    tmp_path,
    attribute,
    value,
) -> None:
    """Persisted block contours cannot certify a transformed parent INSERT."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-corrupted-parent-{attribute}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    insert = next(iter(reopened.modelspace()))
    setattr(insert.dxf, attribute, value)

    with pytest.raises(RuntimeError, match="transform|geometry|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("row_count", 2),
        ("column_count", 2),
        ("extrusion", (0.0, 1.0, 0.0)),
    ],
)
def test_serialized_glyph_verifier_rejects_reopened_array_or_ocs_corruption(
    tmp_path,
    attribute,
    value,
) -> None:
    """A reopened INSERT cannot duplicate or reorient verified glyph ink."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-corrupted-{attribute}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    insert = next(iter(reopened.modelspace()))
    setattr(insert.dxf, attribute, value)

    with pytest.raises(RuntimeError, match="transform|geometry|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("zscale", 2.0),
        ("insert", (12.25, 24.5, 47.0)),
    ],
)
def test_serialized_glyph_verifier_rejects_adjacent_insert_state_corruption(
    tmp_path,
    attribute,
    value,
) -> None:
    """Every persisted INSERT field that can reposition glyph ink is bound."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-corrupted-adjacent-{attribute}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    insert = next(iter(reopened.modelspace()))
    setattr(insert.dxf, attribute, value)

    with pytest.raises(RuntimeError, match="transform|geometry|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize("attribute", ["row_spacing", "column_spacing"])
def test_serialized_glyph_verifier_ignores_visually_inoperative_spacing(
    tmp_path,
    attribute,
) -> None:
    """Spacing is not a roadblock when its corresponding array count is one."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-inoperative-{attribute}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    insert = next(iter(reopened.modelspace()))
    assert int(insert.dxf.get("row_count", 1)) == 1
    assert int(insert.dxf.get("column_count", 1)) == 1
    setattr(insert.dxf, attribute, 47.0)

    _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize(
    ("count_attribute", "spacing_attribute"),
    [
        ("row_count", "row_spacing"),
        ("column_count", "column_spacing"),
    ],
)
def test_serialized_glyph_verifier_binds_spacing_when_array_count_is_operative(
    tmp_path,
    count_attribute,
    spacing_attribute,
) -> None:
    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-operative-{spacing_attribute}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    delivery = result.to_dict()
    verified_attempt = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )
    evidence = verified_attempt["evidence"]

    insert = next(iter(reopened.modelspace()))
    setattr(insert.dxf, count_attribute, 2)
    setattr(insert.dxf, spacing_attribute, 47.0)
    evidence[f"expected_block_{count_attribute}"] = 2

    with pytest.raises(RuntimeError, match="transform|geometry|outline"):
        _verify_serialized_text_deliveries(reopened, [delivery])


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("row_count", 1.5),
        ("column_count", True),
        ("xscale", True),
        ("zscale", "1.0"),
        ("row_spacing", "0.0"),
        ("extrusion", (False, 0.0, 1.0)),
    ],
)
def test_serialized_glyph_verifier_rejects_untyped_raw_insert_state(
    tmp_path,
    attribute,
    value,
) -> None:
    """Raw malformed DXF values cannot be normalized into trusted state."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-corrupted-raw-{attribute}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    insert = next(iter(reopened.modelspace()))
    insert.dxf.unprotected_set(attribute, value)

    with pytest.raises(RuntimeError, match="transform|geometry|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_created_glyph_evidence_binds_the_complete_insert_transform() -> None:
    _, _, result = _deliver("glyphs")
    evidence = result.attempts[-1].evidence

    assert evidence["expected_block_insert"] == pytest.approx([12.25, 24.5, 0.0])
    assert evidence["expected_block_rotation"] == pytest.approx(0.0)
    assert evidence["expected_block_xscale"] == pytest.approx(1.0)
    assert evidence["expected_block_yscale"] == pytest.approx(1.0)
    assert evidence["expected_block_zscale"] == pytest.approx(1.0)
    assert evidence["expected_block_row_count"] == 1
    assert evidence["expected_block_column_count"] == 1
    assert evidence["expected_block_row_spacing"] == pytest.approx(0.0)
    assert evidence["expected_block_column_spacing"] == pytest.approx(0.0)
    assert evidence["expected_block_extrusion"] == pytest.approx([0.0, 0.0, 1.0])
    assert evidence["block_insert_transform_verified"] is True


def test_serialized_glyph_verifier_rejects_reopened_block_base_point_corruption(
    tmp_path,
) -> None:
    """A changed BLOCK base point moves every glyph despite intact children."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-corrupted-block-base-point.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    insert = next(iter(reopened.modelspace()))
    block = reopened.blocks.get(insert.dxf.name)
    block.block.dxf.base_point = (123.0, -47.0, 0.0)

    with pytest.raises(RuntimeError, match="transform|geometry|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_hidden_parent_layer(
    tmp_path,
) -> None:
    """Moving the INSERT onto an off layer must not retain visual acceptance."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-hidden-parent-layer.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    hidden = reopened.layers.add("BCS_HIDDEN_REVIEW_LAYER")
    hidden.off()
    next(iter(reopened.modelspace())).dxf.layer = hidden.dxf.name

    with pytest.raises(RuntimeError, match="visual|layer|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_a_different_visible_parent_layer(
    tmp_path,
) -> None:
    """Layer identity is exact even when both table entries remain visible."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-different-visible-parent-layer.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    visible = reopened.layers.add("BCS_VISIBLE_REVIEW_LAYER")
    next(iter(reopened.modelspace())).dxf.layer = visible.dxf.name

    with pytest.raises(RuntimeError, match="visual|layer|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_expected_layer_turned_off(
    tmp_path,
) -> None:
    """Layer-table visibility is part of the persisted visual state."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-expected-layer-off.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    layer_name = str(insert.dxf.layer)
    if layer_name not in reopened.layers:
        reopened.layers.add(layer_name)
    reopened.layers.get(layer_name).off()

    with pytest.raises(RuntimeError, match="visual|layer|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_expected_layer_frozen(
    tmp_path,
) -> None:
    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-expected-layer-frozen.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    layer_name = str(insert.dxf.layer)
    if layer_name not in reopened.layers:
        reopened.layers.add(layer_name)
    reopened.layers.get(layer_name).freeze()

    with pytest.raises(RuntimeError, match="visual|layer|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_expected_layer_transparency(
    tmp_path,
) -> None:
    """Inherited layer opacity is part of the persisted parent visual state."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-expected-layer-transparent.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    layer = reopened.layers.get(str(insert.dxf.layer))
    layer.transparency = 1.0

    with pytest.raises(RuntimeError, match="visual|layer|transparent|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_invisible_parent_insert(
    tmp_path,
) -> None:
    """The entity-level invisible flag cannot preserve visual acceptance."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-invisible-parent-insert.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    next(iter(reopened.modelspace())).dxf.invisible = 1

    with pytest.raises(RuntimeError, match="visual|visible|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_transparent_parent_insert(
    tmp_path,
) -> None:
    """A fully transparent parent is not visually equivalent delivery."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-transparent-parent-insert.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    next(iter(reopened.modelspace())).transparency = 1.0

    with pytest.raises(RuntimeError, match="visual|transparent|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_partially_transparent_parent_insert(
    tmp_path,
) -> None:
    """Persisted opacity is exact, not merely nonzero."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-partially-transparent-parent-insert.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    next(iter(reopened.modelspace())).transparency = 0.5

    with pytest.raises(RuntimeError, match="visual|transparent|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize("color_kind", ["aci", "true_color"])
def test_serialized_glyph_verifier_rejects_added_parent_color(
    tmp_path,
    color_kind,
) -> None:
    """An uncolored parent cannot gain a display color after acceptance."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-added-parent-{color_kind}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    if color_kind == "aci":
        insert.dxf.color = 1
    else:
        insert.dxf.true_color = 0xFF0000

    with pytest.raises(RuntimeError, match="visual|color|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize("state", ["invisible", "transparent"])
def test_serialized_glyph_verifier_rejects_hidden_block_child(
    tmp_path,
    state,
) -> None:
    """Intact contour coordinates cannot certify hidden owned glyph ink."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / f"glyphs-hidden-block-child-{state}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    child = next(iter(reopened.blocks.get(str(insert.dxf.name))))
    if state == "invisible":
        child.dxf.invisible = 1
    else:
        child.transparency = 1.0

    with pytest.raises(RuntimeError, match="visual|visible|transparent|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


@pytest.mark.parametrize("state", ["invisible", "transparent"])
def test_serialized_geometry_verifier_rejects_hidden_owned_entity(
    tmp_path,
    state,
) -> None:
    """Raw Geometry must remain visibly delivered after save/reopen."""

    doc, _, result = _deliver("geometry")
    output = tmp_path / f"geometry-hidden-owned-entity-{state}.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    entity = next(iter(reopened.modelspace()))
    if state == "invisible":
        entity.dxf.invisible = 1
    else:
        entity.transparency = 1.0

    with pytest.raises(RuntimeError, match="visual|visible|transparent|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_geometry_verifier_requires_owned_entities_in_modelspace(
    tmp_path,
) -> None:
    """Live handles in paper space are not delivered model geometry."""

    doc, _, result = _deliver("geometry")
    output = tmp_path / "geometry-moved-to-paperspace.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    for entity in list(reopened.modelspace()):
        reopened.modelspace().move_to_layout(entity, reopened.layout())
    assert list(reopened.modelspace()) == []

    with pytest.raises(RuntimeError, match="model|space|ownership|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_requires_the_parent_in_modelspace(
    tmp_path,
) -> None:
    """A live INSERT in paper space is not delivered model geometry."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-moved-to-paperspace.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    reopened.modelspace().move_to_layout(insert, reopened.layout())
    assert list(reopened.modelspace()) == []

    with pytest.raises(RuntimeError, match="model|space|ownership|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_allows_a_nonrendering_attached_attribute(
    tmp_path,
) -> None:
    """Nonrendering metadata does not become a future visual roadblock."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-hidden-attached-attrib.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    attribute = insert.add_attrib(
        "BCS_REVIEW_METADATA",
        "HIDDEN METADATA",
        insert=insert.dxf.insert,
        dxfattribs={"height": 2.5},
    )
    attribute.dxf.invisible = 1

    _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_visible_attached_attribute(
    tmp_path,
) -> None:
    """Unexpected ATTRIB text attached to the INSERT changes rendered content."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-visible-attached-attrib.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    insert.add_attrib(
        "BCS_REVIEW_INTRUDER",
        "VISIBLE INTRUDER",
        insert=insert.dxf.insert,
        dxfattribs={"height": 2.5},
    )
    assert len(insert.attribs) == 1

    with pytest.raises(RuntimeError, match="content|attribute|support|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_attribute_with_invalid_invisibility(
    tmp_path,
) -> None:
    """Only the defined invisible state can prove attached text nonrendering."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-invalid-invisible-attached-attrib.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    attribute = insert.add_attrib(
        "BCS_REVIEW_INTRUDER",
        "UNCERTAIN INTRUDER",
        insert=insert.dxf.insert,
        dxfattribs={"height": 2.5},
    )
    attribute.dxf.invisible = 2

    with pytest.raises(RuntimeError, match="content|attribute|support|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_attribute_on_an_undefined_layer(
    tmp_path,
) -> None:
    """A missing layer table entry is not proof that attached text is hidden."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-undefined-layer-attached-attrib.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    attribute = insert.add_attrib(
        "BCS_REVIEW_INTRUDER",
        "UNCERTAIN INTRUDER",
        insert=insert.dxf.insert,
        dxfattribs={"height": 2.5},
    )
    attribute.dxf.layer = "BCS_UNDEFINED_REVIEW_LAYER"
    assert not reopened.layers.has_entry(attribute.dxf.layer)

    with pytest.raises(RuntimeError, match="content|attribute|support|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_an_unowned_duplicate_reference(
    tmp_path,
) -> None:
    """A second reference to the owned glyph block duplicates visible content."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-unowned-duplicate-reference.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    insert = next(iter(reopened.modelspace()))
    duplicate = insert.copy()
    duplicate.dxf.insert = (99.0, 99.0, 0.0)
    reopened.modelspace().add_entity(duplicate)
    assert len(list(reopened.modelspace().query("INSERT"))) == 2

    with pytest.raises(RuntimeError, match="duplicate|ownership|reference|outline"):
        _verify_serialized_text_deliveries(reopened, [result.to_dict()])


def test_serialized_glyph_verifier_rejects_jointly_invented_referenced_handle(
    tmp_path,
) -> None:
    """Attempt/delivery agreement cannot invent a second physical dependency."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-invented-referenced-handle.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    delivery = result.to_dict()
    verified_attempt = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )
    invented = str(verified_attempt["support_entity_handles"][-1])
    delivery["referenced_entity_handles"].append(invented)
    verified_attempt["referenced_entity_handles"].append(invented)

    with pytest.raises(RuntimeError, match="reference|handle|layer|support"):
        _verify_serialized_text_deliveries(reopened, [delivery])


def test_serialized_delivery_binds_verified_attempt_to_the_same_source_id(
    tmp_path,
) -> None:
    """A delivery cannot borrow valid attempt evidence from another source item."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-mismatched-attempt-source.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    delivery = result.to_dict()
    delivery["source_id"] = "text_span:3:999"

    with pytest.raises(RuntimeError, match="source|attempt"):
        _verify_serialized_text_deliveries(reopened, [delivery])


def test_serialized_glyph_identity_cannot_be_rewritten_with_its_attempt(
    tmp_path,
) -> None:
    """The physical block name must remain bound to the exact source identity."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-rewritten-source-identity.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    delivery = result.to_dict()
    delivery["source_id"] = "text_span:3:999"
    for attempt in delivery["attempts"]:
        attempt["source_id"] = "text_span:3:999"

    with pytest.raises(RuntimeError, match="source|identity|block"):
        _verify_serialized_text_deliveries(reopened, [delivery])


def test_serialized_glyph_identity_remains_physical_if_all_report_ids_are_rewritten(
    tmp_path,
) -> None:
    """Rewriting every report-side identity field cannot rewrite the DXF block."""

    doc, _, result = _deliver("glyphs")
    output = tmp_path / "glyphs-fully-rewritten-report-identity.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    delivery = result.to_dict()
    rewritten = "text_span:3:999"
    delivery["source_id"] = rewritten
    for attempt in delivery["attempts"]:
        attempt["source_id"] = rewritten
        attempt["evidence"]["source_identity_sha256"] = hashlib.sha256(
            rewritten.encode("utf-8")
        ).hexdigest()

    with pytest.raises(RuntimeError, match="source|identity|block"):
        _verify_serialized_text_deliveries(reopened, [delivery])


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


def _nested_rectangle_paths():
    """One external contour plus one hole, independent of a host font."""

    from ezdxf.path import Path as DxfPath

    outer = DxfPath((0.0, 0.0))
    outer.line_to((10.0, 0.0))
    outer.line_to((10.0, 10.0))
    outer.line_to((0.0, 10.0))
    outer.close()
    hole = DxfPath((3.0, 3.0))
    hole.line_to((7.0, 3.0))
    hole.line_to((7.0, 7.0))
    hole.line_to((3.0, 7.0))
    hole.close()
    return [outer, hole]


def test_modern_glyph_fill_uses_one_compact_hatch_with_a_hole(tmp_path) -> None:
    """Modern DXF must not amplify one nested glyph into SOLID triangles."""

    fills = _to_solid_fill_entities(
        _nested_rectangle_paths(),
        is_r12=False,
        attribs={"layer": "TEXT"},
    )

    assert len(fills) == 1
    hatch = fills[0]
    assert hatch.dxftype() == "HATCH"
    assert hatch.dxf.solid_fill == 1
    assert hatch.dxf.pattern_name == "SOLID"
    assert len(hatch.paths) == 2
    assert hatch.paths[0].path_type_flags & 1
    assert not (hatch.paths[1].path_type_flags & 1)

    doc = ezdxf.new("R2010")
    block = doc.blocks.new("NESTED_GLYPH")
    block.add_entity(hatch)
    doc.modelspace().add_blockref("NESTED_GLYPH", (0.0, 0.0))
    output = tmp_path / "modern-nested-hatch-in-block.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)
    reopened_ref = next(iter(reopened.modelspace()))
    reopened_hatches = [
        entity
        for entity in reopened.blocks.get(reopened_ref.dxf.name)
        if entity.dxftype() == "HATCH"
    ]
    assert len(reopened_hatches) == 1
    assert len(reopened_hatches[0].paths) == 2


def test_modern_fill_entity_count_is_bounded_by_source_contours() -> None:
    """Proof/report growth must follow contours, never triangulation density."""

    paths = _nested_rectangle_paths()
    fills = _to_solid_fill_entities(paths, is_r12=False, attribs={})

    assert 0 < len(fills) <= len(paths)
    assert {entity.dxftype() for entity in fills} == {"HATCH"}


@pytest.mark.parametrize(
    ("dxf_version", "is_r12"),
    [("R12", True), ("R2010", False)],
)
@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_outline_modes_survive_direct_save_reopen_verification(
    tmp_path,
    dxf_version,
    is_r12,
    mode,
) -> None:
    doc = ezdxf.new(dxf_version)
    msp = doc.modelspace()
    result = build_text(
        _item(),
        msp,
        "TEXT",
        ImportConfig(text_mode=mode),
        is_r12=is_r12,
        target_app="librecad",
        dxf_version=dxf_version,
        return_delivery_result=True,
    )

    assert isinstance(result, TextDeliveryResult)
    assert result.verified is True
    assert result.final_representation == mode
    output = tmp_path / f"{dxf_version}-{mode}-direct-reopen.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    _verify_serialized_text_deliveries(reopened, [result.to_dict()])
    expected_types = {"INSERT"} if mode == "glyphs" else {
        "POLYLINE" if is_r12 else "LWPOLYLINE",
        "SOLID" if is_r12 else "HATCH",
    }
    assert {entity.dxftype() for entity in reopened.modelspace()} == expected_types


def test_solid_fill_discards_degenerate_triangulator_artifacts() -> None:
    """A single zero-area artifact must not invalidate otherwise valid glyph fill."""

    from ezdxf.math import Vec3

    valid = (Vec3(0, 0), Vec3(2, 0), Vec3(0, 1))
    degenerate = (Vec3(3, 0), Vec3(3, 0), Vec3(3, 1))
    with patch(
        "dxf_text_builder.ezdxf_path.triangulate",
        return_value=[valid, degenerate],
    ) as triangulate:
        fills = _to_solid_fill_entities([], is_r12=True, attribs={})

    assert len(fills) == 1
    assert _solid_fill_verified(fills, is_r12=True) is True
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
    item.text = " "
    item.normalized = ""
    item.source_glyph_id = 1
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
        attempt.evidence["source_zero_ink_physically_proven"] is True
        and attempt.evidence["zero_outline_result_verified"] is True
        and attempt.evidence["item_specific_creation_attempted"] is True
        for attempt in outline_attempts
    )
    assert result.attempts[-1].attempted_representation == "text"
    assert result.attempts[-1].outcome == "verified"
    assert result.attempts[-1].evidence["parent_visual_fidelity_verified"] is True
    assert result.attempts[-1].evidence["source_zero_ink_physically_proven"] is True
    assert result.attempts[-1].evidence["parent_native_font_rendering_required"] is False
    assert [entity.dxftype() for entity in msp] == ["TEXT"]
    assert next(iter(msp)).dxf.text == " "


@pytest.mark.parametrize(
    "content",
    [
        "\u200b",  # ZERO WIDTH SPACE
        "\u00ad",  # SOFT HYPHEN
        "\u034f",  # COMBINING GRAPHEME JOINER
        "\ufe0f",  # VARIATION SELECTOR-16
    ],
)
def test_default_ignorable_codepoint_does_not_self_certify_zero_ink(content) -> None:
    item = _item(width=4.0)
    item.text = content
    item.normalized = ""

    proof = dxf_text_builder._build_physical_glyph_ink_proof(
        item,
        ImportConfig.auto(),
    )

    assert dxf_text_builder._validate_physical_glyph_ink_proof(proof) is True
    assert proof["status"] == "unproven"
    assert dxf_text_builder._visible_ink_expected(content) is True


@pytest.mark.parametrize(
    "content",
    [
        "\u0301",  # COMBINING ACUTE ACCENT has visible ink.
        "\u05b0",  # HEBREW POINT SHEVA has visible ink.
        "A\u034f",  # Visible base plus a default-ignorable joiner.
        "\u0301\u200b",  # Visible combining ink plus ZERO WIDTH SPACE.
    ],
)
def test_default_ignorable_detection_preserves_real_combining_ink(content) -> None:
    assert dxf_text_builder._visible_ink_expected(content) is True


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_visible_zero_advance_combining_contour_is_delivered(mode) -> None:
    """Visible contours do not become impossible merely because advance is zero."""

    item = _item(width=2.0)
    item.text = "\u0301"
    item.normalized = "\u0301"

    _, msp, result = _deliver(mode, item, target_app="librecad")

    assert result.verified is True, [attempt.to_dict() for attempt in result.attempts]
    assert result.final_representation == mode
    assert list(msp)


@pytest.mark.parametrize(
    "content",
    [
        "\x00",  # NULL is a control, but not Unicode Default_Ignorable_Code_Point.
        "\x07",  # BELL is a control, but not Unicode Default_Ignorable_Code_Point.
        "\x1b",  # ESCAPE is a control, but not Unicode Default_Ignorable_Code_Point.
    ],
)
def test_non_default_ignorable_controls_do_not_self_certify_as_zero_ink(
    content,
) -> None:
    """Unicode categories never self-certify zero ink; physical glyph proof does."""

    assert dxf_text_builder._visible_ink_expected(content) is True


def test_unicode_white_space_membership_is_not_zero_ink_authority() -> None:
    white_space = [
        *range(0x0009, 0x000E),
        0x0020,
        0x0085,
        0x00A0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
    ]

    assert all(
        dxf_text_builder._visible_ink_expected(chr(code_point)) is True
        for code_point in white_space
    )


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
                                        "font": "BCS Deterministic Test",
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

    extracted = _extract_text(_Page(), 100.0, 1, True, 1.0)
    extracted_again = _extract_text(_Page(), 100.0, 1, True, 1.0)
    assert len(extracted) == 1
    assert [item.id for item in extracted] == [1]
    assert [item.id for item in extracted_again] == [1]
    assert extracted[0].font_size == pytest.approx(0.25 * MM_PER_PT)
    assert extracted[0].font_size < 0.1


def test_extraction_merges_stacked_fractions_into_semantic_value() -> None:
    """Extraction owns the semantic merge: a stacked '716' + '/' IS 7/16.

    RB-16 cross-host golden family (stacked-fraction-extract, T1-11). A
    prior revision of this file locked the opposite ("production must NOT
    merge") — that lock was wrong (worker-log Ruling 1, 2026-07-17): on
    fabrication drawings the stacked spans ARE the dimension value, and
    representation modes govern HOW a delivered value renders, never WHAT
    the value is. Ids stay page-local source order after the merge.
    """

    class _Page:
        @staticmethod
        def get_text(_kind):
            def _span(text, origin, bbox):
                return {
                    "text": text,
                    "size": 2.0,
                    "font": "BCS Deterministic Test",
                    "origin": origin,
                    "bbox": bbox,
                    "ascender": 0.8,
                    "descender": -0.2,
                }

            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "dir": (1.0, 0.0),
                                "bbox": (10.0, 48.0, 14.0, 51.0),
                                "spans": [
                                    _span(
                                        "716",
                                        (10.0, 50.0),
                                        (10.0, 48.0, 14.0, 51.0),
                                    )
                                ],
                            },
                            {
                                "dir": (1.0, 0.0),
                                "bbox": (10.2, 50.5, 12.5, 53.5),
                                "spans": [
                                    _span(
                                        "/",
                                        (10.5, 52.0),
                                        (10.2, 50.5, 12.5, 53.5),
                                    )
                                ],
                            },
                        ],
                    }
                ]
            }

    extracted = _extract_text(_Page(), 100.0, 1, True, 1.0)
    extracted_again = _extract_text(_Page(), 100.0, 1, True, 1.0)

    assert [item.text for item in extracted] == ["7/16"]
    # Identity is page-local source order, deterministic across runs and
    # independent of the merger's global id counter.
    assert [item.id for item in extracted] == [1]
    assert [item.id for item in extracted_again] == [1]
    merged = extracted[0]
    # The merged value positions as a whole string (per-character source
    # layout no longer maps 1:1 onto the semantic text) and carries union
    # source/target fidelity geometry from its constituent spans.
    assert merged.requires_individual_positioning is False
    assert merged.source_char_layout == ()
    assert merged.source_bbox_pdf is not None
    assert merged.target_quad_model is not None


def test_render_stage_must_not_alter_delivered_text_representation(tmp_path) -> None:
    """The render stage delivers extraction's text values verbatim.

    Counterpart lock to the extraction-merge test above: the semantic
    stacked-fraction merge happens at extraction and ONLY there. The render
    stage must not merge ('13' + '16' never becomes '13/16'), split
    ('7/16' stays one entity), or otherwise relabel delivered content.
    """

    def _text(item_id: int, text: str, insertion) -> NormalizedText:
        return NormalizedText(
            id=item_id,
            text=text,
            normalized=text,
            insertion=insertion,
            bbox=(
                insertion[0] - 0.5,
                insertion[1] - 0.5,
                insertion[0] + 2.0,
                insertion[1] + 0.5,
            ),
            font_size=0.9,
            font_name="BCS Deterministic Test",
            page_number=3,
        )

    items = [
        _text(1, "7/16", (10.0, 20.0)),
        _text(2, "13", (30.0, 20.3)),
        _text(3, "16", (30.0, 19.7)),
    ]
    result, _config, drawing, _report = _run_for_items(tmp_path, "labels", items)

    # Labels are not a native DXF entity and must not be certified by relabeling
    # TEXT.  Check the source-bound evidence on each verified closest fallback
    # instead of requiring a representation that the parent cannot deliver.
    delivered_texts = []
    for delivery in result.text_deliveries:
        verified = [
            attempt
            for attempt in delivery["attempts"]
            if attempt["outcome"] == "verified"
        ]
        assert len(verified) == 1
        source_text = verified[0]["evidence"]["source_text_evidence"]
        assert source_text["content_verified"] is True
        assert source_text["source_content"] == source_text["delivered_content"]
        delivered_texts.append(source_text["delivered_content"])
    assert sorted(delivered_texts) == ["13", "16", "7/16"]
    assert [entry["source_id"] for entry in result.text_deliveries] == [
        "text_span:3:1",
        "text_span:3:2",
        "text_span:3:3",
    ]


def _run_for_items(tmp_path, mode: str, items: list[NormalizedText]):
    pdf_path = tmp_path / "source.pdf"
    pdf = fitz.open()
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
        ("labels", "glyphs", "INSERT", "outline_curve_or_mesh"),
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
        {modelspace_type, "HATCH"} if mode == "geometry" else {modelspace_type}
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
    assert delivery["final_representation"] == "glyphs"
    assert delivery["fallback_used"] is True
    entity = next(iter(drawing.modelspace()))
    assert entity.dxftype() == "INSERT"
    assert [attempt["attempted_representation"] for attempt in delivery["attempts"]] == [
        "3d_text",
        "text",
        "glyphs",
    ]
    actual = report["extra"]["actual_text_entity_types"]
    assert actual["entity_type"] == "glyphs"
    assert actual["native_3d_text"] == 0
    assert actual["dxf_text"] == 0
    assert actual["outline_curve_or_mesh"] == 1


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
    assert deliveries[0]["final_representation"] == "glyphs"
    assert deliveries[0]["fallback_used"] is True
    assert text_count == 1
    assert next(iter(drawing.modelspace())).dxftype() == "INSERT"


def test_noncanonical_engine_mode_fails_closed_instead_of_using_legacy_semantics(
    tmp_path,
) -> None:
    from dxf_import_engine import convert

    pdf_path = tmp_path / "source.pdf"
    pdf = fitz.open()
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
    pdf = fitz.open()
    page = pdf.new_page(width=240, height=160)
    page.insert_text((36, 72), "W12X30", fontsize=12)
    pdf.save(str(pdf_path))
    pdf.close()
    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    assert run.extraction.text_count == 1
    return run


def test_visible_unicode_bound_to_empty_source_glyph_reaches_transparent_raster(
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    original = run.extraction.pages[0].page_data.text_items[0]
    source_empty = __import__("dataclasses").replace(
        original,
        text="A",
        normalized="A",
        font_name="BCS Deterministic Test",
        source_char_layout=(),
        requires_individual_positioning=False,
        positioned_character=False,
        source_glyph_id=1,
        font_asset=None,
        font_failure=None,
    )
    run.extraction.pages[0].page_data.text_items = [source_empty]
    output = tmp_path / "source-empty-parent-visible.dxf"

    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_images=False,
            text_mode="text",
            provenance_opts=run.config,
        ),
    )

    assert output.is_file()
    assert result.text_fallbacks == [
        {
            "requested": "text",
            "delivered": "raster",
            "reason": "structural_representations_failed_verification",
            "count": 1,
        }
    ]
    delivery = result.text_deliveries[0]
    assert delivery["requested_representation"] == "text"
    assert delivery["final_representation"] == "raster"
    assert delivery["fallback_used"] is True
    assert delivery["verified"] is True
    structural = [
        attempt
        for attempt in delivery["attempts"]
        if attempt["attempted_representation"] != "raster"
    ]
    assert structural
    assert all(attempt["outcome"] == "impossible" for attempt in structural)
    assert all(attempt["cleanup_verified"] is True for attempt in structural)
    native = structural[0]
    assert native["attempted_representation"] == "text"
    assert native["evidence"]["source_zero_ink_physically_proven"] is True
    assert native["evidence"]["parent_native_lff_ink_proof"]["status"] == "visible"
    raster = delivery["attempts"][-1]
    assert raster["attempted_representation"] == "raster"
    assert raster["strategy"] == "sealed_physical_zero_ink_png"
    assert raster["evidence"]["source_zero_ink_physically_proven"] is True
    assert raster["evidence"]["source_pixels_sampled"] is False
    asset = Path(raster["evidence"]["asset_path"])
    pixmap = fitz.Pixmap(str(asset))
    assert (pixmap.width, pixmap.height) == (1, 1)
    assert bool(pixmap.alpha) is True
    assert pixmap.pixel(0, 0)[-1] == 0

    drawing = ezdxf.readfile(output)
    assert [entity.dxftype() for entity in drawing.modelspace()] == ["IMAGE"]
    _verify_serialized_text_deliveries(drawing, result.text_deliveries)
    run.close()


def test_missing_source_glyph_identity_reaches_source_sampled_terminal_raster(
    deterministic_exact_font,
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    original = run.extraction.pages[0].page_data.text_items[0]
    missing_identity = __import__("dataclasses").replace(
        original,
        source_char_layout=(),
        requires_individual_positioning=False,
        positioned_character=False,
        source_glyph_id=None,
        font_asset=None,
        font_failure=None,
    )
    run.extraction.pages[0].page_data.text_items = [missing_identity]
    resolution = _ExactFontResolution(
        source_name="BCS missing-identity fixture",
        family="BCS missing-identity fixture",
        style="Regular",
        filename=str(deterministic_exact_font),
        exact=True,
        reason="exact font bytes without an installed PDF cmap",
        resolution_source="test_fixture",
        source_origin="test_fixture",
        unicode_map_installed=False,
    )
    output = tmp_path / "missing-glyph-identity-terminal-raster.dxf"

    with patch("dxf_text_builder._resolve_item_font", return_value=resolution):
        result = export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(
                include_images=False,
                text_mode="geometry",
                provenance_opts=run.config,
            ),
        )

    delivery = result.text_deliveries[0]
    assert delivery["requested_representation"] == "geometry"
    assert delivery["final_representation"] == "raster"
    assert delivery["fallback_used"] is True
    collapsed_attempts = []
    for attempt in delivery["attempts"]:
        attempted = attempt["attempted_representation"]
        if not collapsed_attempts or collapsed_attempts[-1] != attempted:
            collapsed_attempts.append(attempted)
    assert collapsed_attempts == _representation_ladder("geometry") + ["raster"]
    structural = delivery["attempts"][:-1]
    assert all(attempt["outcome"] == "impossible" for attempt in structural)
    assert all(attempt["cleanup_verified"] is True for attempt in structural)
    raster = delivery["attempts"][-1]
    assert raster["strategy"] == "pymupdf_item_clip"
    assert raster["outcome"] == "verified"
    assert raster["evidence"]["source_pixels_sampled"] is True
    assert Path(raster["evidence"]["asset_path"]).is_file()
    run.close()


def test_unproven_zero_ink_cannot_certify_a_blank_sampled_raster_clip(
    tmp_path,
) -> None:
    """Sampling a clip is not visual proof when it contains no source ink."""

    run = _real_text_extraction(tmp_path)
    original = run.extraction.pages[0].page_data.text_items[0]
    blank_clip_item = __import__("dataclasses").replace(
        original,
        source_bbox_pdf=(180.0, 120.0, 220.0, 150.0),
        source_char_layout=(),
        requires_individual_positioning=False,
        positioned_character=False,
        source_glyph_id=None,
        font_asset=None,
        font_failure=None,
    )
    run.extraction.pages[0].page_data.text_items = [blank_clip_item]
    output = tmp_path / "blank-source-clip-must-fail.dxf"

    with pytest.raises(TextRepresentationDeliveryError):
        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(
                include_images=False,
                text_mode="raster",
                provenance_opts=run.config,
            ),
        )

    assert not output.exists()
    run.close()


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


def test_serialized_raster_rejects_jointly_rewritten_png_and_hash(tmp_path) -> None:
    run = _real_text_extraction(tmp_path)
    output = tmp_path / "jointly-rewritten-raster.dxf"
    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_images=False,
            text_mode="raster",
            provenance_opts=run.config,
        ),
    )
    drawing = ezdxf.readfile(output)
    delivery = json.loads(json.dumps(result.text_deliveries[0]))
    attempt = delivery["attempts"][-1]
    evidence = attempt["evidence"]
    assert evidence["source_pixels_sampled"] is True
    asset = Path(evidence["asset_path"])
    original = fitz.Pixmap(str(asset))
    wrong = fitz.Pixmap(
        fitz.csRGB,
        fitz.IRect(0, 0, original.width, original.height),
        True,
    )
    wrong.clear_with(255)
    wrong_png = bytes(wrong.tobytes("png"))
    assert hashlib.sha256(wrong_png).hexdigest() != evidence["asset_sha256"]
    asset.write_bytes(wrong_png)
    evidence["asset_sha256"] = hashlib.sha256(wrong_png).hexdigest()

    with pytest.raises(RuntimeError, match="source-derived raster mismatch"):
        _verify_serialized_text_deliveries(drawing, [delivery])
    run.close()


def test_serialized_raster_rejects_fresh_pixels_from_a_different_page(
    tmp_path,
) -> None:
    pdf_path = tmp_path / "two-page-raster-source.pdf"
    pdf = fitz.open()
    first = pdf.new_page(width=240, height=160)
    first.insert_text((36, 72), "W12X30", fontsize=12)
    second = pdf.new_page(width=240, height=160)
    second.insert_text((36, 72), "IIIIII", fontsize=12)
    pdf.save(str(pdf_path))
    pdf.close()
    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    assert run.extraction.text_count == 1
    output = tmp_path / "page-rebound-raster.dxf"
    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_images=False,
            text_mode="raster",
            provenance_opts=run.config,
        ),
    )
    drawing = ezdxf.readfile(output)
    delivery = json.loads(json.dumps(result.text_deliveries[0]))
    evidence = delivery["attempts"][-1]["evidence"]
    asset = Path(evidence["asset_path"])
    original_sha = evidence["asset_sha256"]
    fresh, fresh_clip, fresh_rotation = _render_source_text_clip(
        pdf_path,
        page_number=2,
        source_bbox_pdf=evidence["source_bbox_pdf"],
        raster_dpi=evidence["raster_dpi"],
    )
    replacement_png = bytes(fresh.tobytes("png"))
    replacement_sha = hashlib.sha256(replacement_png).hexdigest()
    assert replacement_sha != original_sha
    asset.write_bytes(replacement_png)
    evidence["source_page_number"] = 2
    evidence["source_clip_pdf"] = fresh_clip
    evidence["source_to_display_rotation"] = fresh_rotation
    evidence["source_render_samples_sha256"] = hashlib.sha256(
        bytes(fresh.samples)
    ).hexdigest()
    evidence["asset_sha256"] = replacement_sha

    with pytest.raises(RuntimeError, match="selected source page"):
        _verify_serialized_text_deliveries(
            drawing,
            [delivery],
            expected_source_pdf_path=pdf_path,
            expected_source_pdf_sha256=hashlib.sha256(
                pdf_path.read_bytes()
            ).hexdigest(),
        )
    run.close()


def test_explicit_raster_and_requested_labels_are_both_retained(tmp_path) -> None:
    pdf_path = tmp_path / "raster_with_requested_text.pdf"
    pdf = fitz.open()
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
    page_raster = fitz.Pixmap(
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
    pdf = fitz.open()
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
    raster = fitz.Pixmap(run.extraction.pages[0].images[0].path)
    assert raster.alpha

    with fitz.open(pdf_path) as document:
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
    pdf = fitz.open()
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
    pdf = fitz.open()
    page = pdf.new_page(width=120, height=80)
    page.insert_text((20, 40), "W12X30", fontsize=10)
    pdf.save(str(pdf_path))
    pdf.close()
    pdf = fitz.open(str(pdf_path))
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
            fitz.Page,
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
    pdf = fitz.open()
    page = pdf.new_page(width=200, height=100)
    page.insert_text((30, 50), "W12X30", fontsize=12)
    page.set_cropbox(fitz.Rect(20, 10, 180, 90))
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


def test_requested_raster_samples_source_when_whitespace_lacks_physical_glyph_proof(
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    original = run.extraction.pages[0].page_data.text_items[0]
    whitespace = __import__("dataclasses").replace(
        original,
        text="   ",
        normalized="",
        source_char_layout=(),
        requires_individual_positioning=False,
        positioned_character=False,
        source_glyph_id=None,
        font_asset=None,
    )
    run.extraction.pages[0].page_data.text_items = [whitespace]
    source_id = f"text_span:1:{whitespace.id}"
    output = tmp_path / "whitespace_zero_ink_raster.dxf"

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
    assert result.entity_count == 1
    assert result.image_count == 1
    assert result.delivered_text_entity_counts == {"raster_image": 1}
    assert result.text_fallbacks == []
    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    assert delivery["source_id"] == source_id
    assert delivery["requested_representation"] == "raster"
    assert delivery["final_representation"] == "raster"
    assert delivery["verified"] is True
    assert delivery["fallback_used"] is False
    assert len(delivery["entity_handles"]) == 1
    assert len(delivery["support_entity_handles"]) == 2
    assert len(delivery["attempts"]) == 1
    attempt = delivery["attempts"][0]
    assert attempt["attempted_representation"] == "raster"
    assert attempt["strategy"] == "pymupdf_item_clip"
    assert attempt["outcome"] == "verified"
    assert attempt["type_verified"] is True
    assert attempt["visual_verified"] is True
    assert attempt["cleanup_verified"] is True
    evidence = attempt["evidence"]
    assert evidence["source_id"] == source_id
    assert evidence["source_pdf_sha256"] == hashlib.sha256(
        Path(run.extraction.pdf_path).read_bytes()
    ).hexdigest()
    assert evidence["source_bbox_pdf"] == pytest.approx(whitespace.source_bbox_pdf)
    assert evidence["target_bbox_model"] == pytest.approx(whitespace.bbox)
    assert evidence["source_zero_ink_physically_proven"] is False
    assert evidence["visible_ink_expected"] is True
    assert evidence["source_pixels_sampled"] is True
    assert evidence["source_clip_pdf"] is not None
    assert evidence["pixel_size"][0] > 1
    assert evidence["pixel_size"][1] > 1
    assert evidence["anchor_verified"] is True
    assert evidence["size_verified"] is True

    asset_path = Path(evidence["asset_path"])
    assert asset_path.is_file()
    asset_content = asset_path.read_bytes()
    assert asset_content.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(asset_content).hexdigest() == evidence["asset_sha256"]
    sampled = fitz.Pixmap(str(asset_path))
    assert (sampled.width, sampled.height) == tuple(evidence["pixel_size"])

    drawing = ezdxf.readfile(output)
    images = list(drawing.modelspace())
    assert [entity.dxftype() for entity in images] == ["IMAGE"]
    image = images[0]
    assert str(image.dxf.handle) == delivery["entity_handles"][0]
    assert int(image.dxf.flags or 0) & 8
    x0, y0, x1, y1 = evidence["target_bbox_model"]
    actual_size = (
        math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y)
        * float(image.dxf.image_size.x),
        math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y)
        * float(image.dxf.image_size.y),
    )
    assert tuple(image.dxf.insert)[:2] == pytest.approx((x0, y0))
    assert actual_size == pytest.approx((x1 - x0, y1 - y0))
    assert all(
        drawing.entitydb.get(handle) is not None
        for handle in delivery["support_entity_handles"]
    )
    _verify_serialized_text_deliveries(drawing, result.text_deliveries)

    report_path = tmp_path / "whitespace_zero_ink_import_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    actual = report["extra"]["actual_text_entity_types"]
    assert actual["entity_type"] == "raster"
    assert actual["raster_image"] == 1
    delivery_report = report["extra"]["text_representation_delivery"]
    assert delivery_report["requested_representation"] == "raster"
    assert delivery_report["verified"] is True
    assert delivery_report["source_ids"] == [source_id]
    assert delivery_report["entity_handles"] == delivery["entity_handles"]
    assert delivery_report["support_entity_handles"] == delivery["support_entity_handles"]
    run.close()
    assert asset_path.is_file()
    assert not list(tmp_path.rglob("*.tmp"))


def test_terminal_raster_cleans_partial_image_creation_without_touching_prior_state(
    tmp_path,
) -> None:
    run = _real_text_extraction(tmp_path)
    source = run.extraction.pages[0].page_data.text_items[0]
    whitespace = __import__("dataclasses").replace(
        source,
        text="   ",
        normalized="",
    )
    source_id = f"text_span:1:{whitespace.id}"
    delivery = TextDeliveryResult(
        source_id=source_id,
        requested_representation="raster",
        final_representation=None,
        verified=False,
        terminal_fallback_authorized=True,
    )
    doc = ezdxf.new("R2010")
    doc.layers.add("TEXT")
    msp = doc.modelspace()
    prior_definition = doc.add_image_def(
        filename=str(tmp_path / "prior.png"),
        size_in_pixel=(1, 1),
        name=f"BCS_TEXT_{source_id.replace(':', '_')}",
    )
    prior_image = msp.add_image(
        prior_definition,
        insert=(1.0, 2.0),
        size_in_units=(3.0, 4.0),
        dxfattribs={"layer": "TEXT"},
    )
    prior_handles = {
        str(handle)
        for handle, entity in doc.entitydb.items()
        if handle and entity is not None and getattr(entity, "is_alive", True)
    }
    prior_support = {
        str(prior_definition.dxf.handle),
        str(prior_image.dxf.image_def_reactor_handle),
    }
    image_dict = doc.rootdict.get("ACAD_IMAGE_DICT")
    prior_image_dict = {
        key: str(entity.dxf.handle) for key, entity in image_dict.items()
    }

    layout_type = type(msp)
    original_add_image = layout_type.add_image
    injected_handles = []

    def create_then_raise(self, image_def, *args, **kwargs):
        image = original_add_image(self, image_def, *args, **kwargs)
        injected_handles.extend(
            [
                str(image_def.dxf.handle),
                str(image.dxf.handle),
                str(image.dxf.image_def_reactor_handle),
            ]
        )
        raise RuntimeError("injected post-create failure")

    with patch.object(layout_type, "add_image", new=create_then_raise):
        failed, pending = _attempt_terminal_text_raster(
            delivery,
            extraction=run.extraction,
            page_number=1,
            source_text=whitespace,
            placed_text=whitespace,
            msp=msp,
            layer_name="TEXT",
            asset_root=tmp_path / "partial_image_assets",
            raster_dpi=300,
            source_pdf_sha256=hashlib.sha256(
                Path(run.extraction.pdf_path).read_bytes()
            ).hexdigest(),
        )

    attempt = failed.attempts[-1]
    live_handles = {
        str(handle)
        for handle, entity in doc.entitydb.items()
        if handle and entity is not None and getattr(entity, "is_alive", True)
    }
    assert failed.verified is False
    assert pending is None
    assert attempt.outcome == "failed"
    assert attempt.reason == "RuntimeError: injected post-create failure"
    assert attempt.cleanup_verified is True
    assert set(attempt.created_entity_handles) == set(injected_handles)
    assert set(attempt.removed_entity_handles) == set(injected_handles)
    assert live_handles == prior_handles
    assert {entity.dxftype() for entity in msp} == {"IMAGE"}
    assert str(next(iter(msp)).dxf.handle) == str(prior_image.dxf.handle)
    assert all(
        doc.entitydb.get(handle) is not None
        and getattr(doc.entitydb.get(handle), "is_alive", True)
        for handle in prior_support
    )
    assert {
        key: str(entity.dxf.handle) for key, entity in image_dict.items()
    } == prior_image_dict
    run.close()


@pytest.mark.parametrize("bbox_kind", ["source", "target"])
@pytest.mark.parametrize(
    "bad_coordinate",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive_infinity", "negative_infinity"],
)
def test_terminal_raster_rejects_non_finite_source_and_target_bounds(
    tmp_path,
    bbox_kind,
    bad_coordinate,
) -> None:
    run = _real_text_extraction(tmp_path)
    source = run.extraction.pages[0].page_data.text_items[0]
    whitespace = __import__("dataclasses").replace(
        source,
        text="   ",
        normalized="",
    )
    if bbox_kind == "source":
        source_bbox = list(whitespace.source_bbox_pdf)
        source_bbox[2] = bad_coordinate
        whitespace = __import__("dataclasses").replace(
            whitespace,
            source_bbox_pdf=tuple(source_bbox),
        )
    else:
        target_bbox = list(whitespace.bbox)
        target_bbox[2] = bad_coordinate
        whitespace = __import__("dataclasses").replace(
            whitespace,
            bbox=tuple(target_bbox),
        )
    run.extraction.pages[0].page_data.text_items = [whitespace]
    output = tmp_path / f"non_finite_{bbox_kind}.dxf"
    prior = b"prior accepted DXF must survive invalid bounds\r\n"
    output.write_bytes(prior)

    with pytest.raises(
        TextRepresentationDeliveryError,
        match="terminal raster bounds must contain only finite coordinates",
    ):
        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_images=False, text_mode="raster"),
        )

    assert output.read_bytes() == prior
    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("*.tmp"))
    run.close()


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
    pdf = fitz.open()
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
    pdf = fitz.open()
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


def test_serialized_librecad_fallback_contains_no_superseded_native_text(
    tmp_path,
) -> None:
    result, _, drawing, _ = _run_for_items(tmp_path, "labels", [_item()])
    delivery = result.text_deliveries[0]
    assert delivery["final_representation"] == "glyphs"
    assert {entity.dxftype() for entity in drawing.modelspace()} == {"INSERT"}
    native_attempt = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["attempted_representation"] == "text"
    )
    assert native_attempt["outcome"] == "impossible"
    assert native_attempt["cleanup_verified"] is True
    assert set(native_attempt["removed_entity_handles"]) == set(
        native_attempt["created_entity_handles"]
    )
    _verify_serialized_text_deliveries(drawing, result.text_deliveries)


def test_serialized_native_text_fit_width_cannot_change_after_verification(
    tmp_path,
) -> None:
    parent_evidence = {
        "parent_native_text_delivery_verified": True,
        "parent_visual_fidelity_verified": True,
        "fallback_authorized_for_this_item": False,
    }
    with patch(
        "dxf_text_builder._verify_parent_native_text_delivery",
        return_value=(True, parent_evidence, ""),
    ):
        doc, _, result = _deliver("text", target_app="librecad")
    output = tmp_path / "generic_native_text.dxf"
    doc.saveas(output)
    drawing = ezdxf.readfile(output)
    native = next(iter(drawing.modelspace()))
    assert native.dxftype() == "TEXT"
    assert int(native.dxf.halign) == 5
    native.dxf.align_point = (
        float(native.dxf.align_point.x) + 1.0,
        float(native.dxf.align_point.y),
        0.0,
    )

    with pytest.raises(RuntimeError, match="FIT width changed"):
        _verify_serialized_text_deliveries(drawing, [result.to_dict()])


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
    welding_symbol_chart,
) -> None:
    chart = welding_symbol_chart
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
    expected_final = "geometry" if mode == "geometry" else "glyphs"
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
        assert {entity.dxftype() for entity in drawing.modelspace()} == {"INSERT"}
        for item in result.text_deliveries:
            assert item["requested_representation"] == mode
            structural_attempts = []
            for attempt in item["attempts"]:
                attempted = attempt["attempted_representation"]
                if not structural_attempts or structural_attempts[-1] != attempted:
                    structural_attempts.append(attempted)
            ladder = _representation_ladder(mode)
            assert structural_attempts == ladder[: len(structural_attempts)]
            native_attempts = [
                attempt
                for attempt in item["attempts"]
                if "parent_visual_fidelity_verified" in attempt["evidence"]
            ]
            assert native_attempts
            assert all(attempt["outcome"] == "impossible" for attempt in native_attempts)
            assert all(attempt["cleanup_verified"] is True for attempt in native_attempts)
            assert all(
                attempt["evidence"]["parent_native_text_delivery_verified"] is False
                and attempt["evidence"]["parent_visual_fidelity_verified"] is False
                and attempt["evidence"]["fallback_authorized_for_this_item"] is True
                for attempt in native_attempts
            )
            assert all(
                set(attempt["removed_entity_handles"])
                == set(attempt["created_entity_handles"])
                for attempt in native_attempts
            )
            final_attempt = next(
                attempt
                for attempt in item["attempts"]
                if attempt["outcome"] == "verified"
            )
            assert final_attempt["attempted_representation"] == "glyphs"
            assert final_attempt["evidence"]["font_resolution_source"] == (
                "embedded_pdf_font"
            )
            assert final_attempt["evidence"]["source_text_parameters_verified"] is True
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


def test_real_welding_chart_all_requested_raster_spans_are_source_bound(
    tmp_path,
    welding_symbol_chart,
) -> None:
    chart = welding_symbol_chart
    run = run_import(
        str(chart),
        mode="vector",
        overrides={"pages": "1", "import_text": True, "text_mode": "raster"},
    )
    page = run.extraction.pages[0]
    source_items = list(page.page_data.text_items)
    assert len(source_items) == 372
    whitespace_ids = {int(item.id) for item in source_items if not item.text.strip()}
    assert whitespace_ids == {166, 311, 314}
    page.page_data.primitives = []
    page.images = []
    output = tmp_path / "welding-all-requested-item-raster.dxf"

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

    assert output.is_file()
    assert result.entity_count == 372
    assert result.image_count == 372
    assert result.delivered_text_entity_counts == {"raster_image": 372}
    assert result.text_fallbacks == []
    assert len(result.text_deliveries) == 372
    expected_source_ids = {f"text_span:1:{item.id}" for item in source_items}
    assert {"text_span:1:166", "text_span:1:311", "text_span:1:314"}.issubset(
        expected_source_ids
    )
    deliveries_by_source = {
        delivery["source_id"]: delivery for delivery in result.text_deliveries
    }
    assert set(deliveries_by_source) == expected_source_ids

    drawing = ezdxf.readfile(output)
    images = list(drawing.modelspace())
    assert len(images) == 372
    assert {entity.dxftype() for entity in images} == {"IMAGE"}
    assert {str(entity.dxf.handle) for entity in images} == {
        delivery["entity_handles"][0] for delivery in result.text_deliveries
    }
    source_sha = hashlib.sha256(chart.read_bytes()).hexdigest()
    asset_paths = set()
    zero_ink_asset_paths = set()
    for item in source_items:
        source_id = f"text_span:1:{item.id}"
        delivery = deliveries_by_source[source_id]
        assert delivery["requested_representation"] == "raster"
        assert delivery["final_representation"] == "raster"
        assert delivery["verified"] is True
        assert delivery["fallback_used"] is False
        assert len(delivery["entity_handles"]) == 1
        assert len(delivery["support_entity_handles"]) == 2
        assert len(delivery["attempts"]) == 1
        attempt = delivery["attempts"][0]
        assert attempt["attempted_representation"] == "raster"
        assert attempt["outcome"] == "verified"
        assert attempt["cleanup_verified"] is True
        evidence = attempt["evidence"]
        assert evidence["source_pdf_sha256"] == source_sha
        assert evidence["source_page_number"] == 1
        assert evidence["source_id"] == source_id
        assert evidence["source_bbox_pdf"] == pytest.approx(item.source_bbox_pdf)
        x0, y0, x1, y1 = [float(value) for value in item.bbox]
        assert evidence["target_bbox_model"] == pytest.approx(
            [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        )
        asset_path = Path(evidence["asset_path"])
        assert asset_path.is_file()
        assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == evidence[
            "asset_sha256"
        ]
        asset_paths.add(asset_path)
        if int(item.id) in whitespace_ids:
            assert attempt["strategy"] == "sealed_physical_zero_ink_png"
            assert evidence["source_zero_ink_physically_proven"] is True
            assert evidence["physical_glyph_ink_proof_valid"] is True
            assert evidence["physical_glyph_ink_proof"]["status"] == "empty"
            assert evidence["visible_ink_expected"] is False
            assert evidence["zero_ink_verified"] is True
            assert evidence["source_pixels_sampled"] is False
            assert evidence["pixel_size"] == [1, 1]
            transparent = fitz.Pixmap(str(asset_path))
            assert (transparent.width, transparent.height) == (1, 1)
            assert bool(transparent.alpha) is True
            assert transparent.pixel(0, 0)[-1] == 0
            zero_ink_asset_paths.add(asset_path)
        else:
            assert attempt["strategy"] == "pymupdf_item_clip"
            assert evidence["visible_ink_verified"] is True
            assert len(evidence["source_clip_pdf"]) == 4

    assert len(asset_paths) == 372
    assert len(zero_ink_asset_paths) == 3
    _verify_serialized_text_deliveries(drawing, result.text_deliveries)

    report_path = tmp_path / "welding-all-requested-item-raster-report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    actual = report["extra"]["actual_text_entity_types"]
    assert actual["entity_type"] == "raster"
    assert actual["raster_image"] == 372
    delivery_report = report["extra"]["text_representation_delivery"]
    assert delivery_report["requested_representation"] == "raster"
    assert delivery_report["verified"] is True
    assert len(delivery_report["source_ids"]) == 372
    assert len(delivery_report["entity_handles"]) == 372
    assert len(delivery_report["support_entity_handles"]) == 744
    assert len(delivery_report["items"]) == 372
    run.close()
    assert all(path.is_file() for path in asset_paths)
    assert not list(tmp_path.rglob("*.tmp"))


def test_real_image_only_chart_explicit_page_raster_survives_source_cleanup(
    tmp_path,
    aws_weld_symbol_chart,
) -> None:
    chart = aws_weld_symbol_chart
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
    with fitz.open(str(chart)) as source_pdf:
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


@pytest.mark.parametrize(
    ("requested_mode", "expected_fallback", "expected_attempt_count"),
    [
        ("text", True, 2),
        ("labels", True, 2),
        ("glyphs", True, 2),
        ("3d_text", True, 2),
        ("geometry", True, 2),
        ("raster", False, 1),
    ],
)
def test_real_image_only_chart_binds_existing_page_image_as_verified_text_terminal(
    tmp_path,
    aws_weld_symbol_chart,
    requested_mode,
    expected_fallback,
    expected_attempt_count,
) -> None:
    chart = aws_weld_symbol_chart
    source_pdf_sha = hashlib.sha256(chart.read_bytes()).hexdigest()
    run = run_import(
        str(chart),
        mode="vector",
        overrides={"pages": "1", "text_mode": requested_mode},
    )
    output = tmp_path / f"aws-page-terminal-{requested_mode}.dxf"
    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(
            include_text=True,
            include_images=True,
            text_mode=requested_mode,
            dxf_version="R2010",
            provenance_opts=run.config,
        ),
    )

    drawing = ezdxf.readfile(output)
    images = list(drawing.modelspace().query("IMAGE"))
    assert len(images) == 1
    assert result.image_count == 1
    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    assert delivery["source_id"] == "page_visual:1"
    assert delivery["requested_representation"] == requested_mode
    assert delivery["final_representation"] == "raster"
    assert delivery["verified"] is True
    assert delivery["fallback_used"] is expected_fallback
    assert delivery["entity_handles"] == [str(images[0].dxf.handle)]
    assert len(delivery["attempts"]) == expected_attempt_count
    assert sum(
        attempt["outcome"] == "verified" for attempt in delivery["attempts"]
    ) == 1
    terminal = delivery["attempts"][-1]
    assert terminal["attempted_representation"] == "raster"
    assert terminal["strategy"] == "existing_page_image_terminal_raster"
    assert terminal["outcome"] == "verified"
    evidence = terminal["evidence"]
    assert evidence["source_pdf_sha256"] == source_pdf_sha
    assert evidence["source_page_number"] == 1
    assert evidence["source_zero_text_proof"]["verified_zero_text"] is True
    assert evidence["source_zero_text_proof"]["plain_text_length"] == 0
    assert evidence["source_zero_text_proof"]["word_count"] == 0
    assert evidence["existing_image_entity_reused"] is True
    assert evidence["duplicate_image_entities_created"] is False
    assert evidence["image_entity_handles"] == [str(images[0].dxf.handle)]

    report_path = tmp_path / f"aws-page-terminal-{requested_mode}_report.json"
    write_import_report(run, str(report_path), elapsed_ms=1.0)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    reported = report["extra"]["text_representation_delivery"]
    assert reported["verified"] is True
    assert reported["source_ids"] == ["page_visual:1"]
    assert len(reported["items"]) == 1
    assert report["extra"]["import_contract_ready"]["ready"] is True
    assert (
        report["extra"]["import_contract_ready"]["checks"]["text_delivery"]
        is True
    )


def test_image_only_page_terminal_rejects_source_zero_text_proof_tamper(
    tmp_path,
    aws_weld_symbol_chart,
) -> None:
    from librecad_pdf_importer.exporters import dxf_exporter as exporter_module

    run = run_import(
        str(aws_weld_symbol_chart),
        mode="vector",
        overrides={"pages": "1", "text_mode": "text"},
    )
    original_proof = exporter_module._source_zero_text_page_proof
    proof_call_count = 0

    def proof_then_tamper(*args, **kwargs):
        nonlocal proof_call_count
        proof_call_count += 1
        proof = dict(original_proof(*args, **kwargs))
        if proof_call_count >= 2:
            proof["plain_text_length"] = 1
        return proof

    with (
        patch.object(
            exporter_module,
            "_source_zero_text_page_proof",
            side_effect=proof_then_tamper,
        ),
        pytest.raises(RuntimeError, match="source-zero-text proof changed"),
    ):
        export_to_dxf(
            run.extraction,
            str(tmp_path / "aws-zero-text-proof-tamper.dxf"),
            DxfExportOptions(
                include_text=True,
                include_images=True,
                text_mode="text",
                dxf_version="R2010",
                provenance_opts=run.config,
            ),
        )


def test_image_only_page_terminal_rejects_duplicate_existing_image_artifact(
    tmp_path,
    aws_weld_symbol_chart,
) -> None:
    run = run_import(
        str(aws_weld_symbol_chart),
        mode="vector",
        overrides={"pages": "1", "text_mode": "text"},
    )
    real_readfile = ezdxf.readfile

    def reopen_with_duplicate_image(path):
        drawing = real_readfile(path)
        image = list(drawing.modelspace().query("IMAGE"))[0]
        drawing.modelspace().add_entity(image.copy())
        return drawing

    with (
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter.ezdxf.readfile",
            side_effect=reopen_with_duplicate_image,
        ),
        pytest.raises(RuntimeError, match="duplicate or altered page IMAGE"),
    ):
        export_to_dxf(
            run.extraction,
            str(tmp_path / "aws-duplicate-page-image.dxf"),
            DxfExportOptions(
                include_text=True,
                include_images=True,
                text_mode="text",
                dxf_version="R2010",
                provenance_opts=run.config,
            ),
        )

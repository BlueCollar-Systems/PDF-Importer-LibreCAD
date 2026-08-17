"""Persisted DXF locks for individually positioned stacked fractions."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import inspect
import math
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

import dxf_text_builder as text_builder
import ezdxf
from ezdxf.colors import aci2rgb, rgb2int
from fontTools.ttLib import TTFont
import pytest

from dxf_text_builder import (
    _ExactFontResolution,
    _bbox_tuple,
    _positioned_font_identity,
    _solid_fill_verified,
    TextDeliveryAttempt,
    TextDeliveryResult,
    build_text,
    iter_glyph_outline_entities,
    reset_text_styles,
)
from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    TextRepresentationDeliveryError,
    _PositionedTranslationAnchor,
    _positioned_session_anchor_map,
    _positioned_translation_receipt_digest,
    _verify_serialized_text_deliveries,
    export_to_dxf,
)
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText, PageData, TextCharLayout


_TEXT = "13/16"
_GLYPH_IDS = (18, 20, 16, 18, 23)
_COLOR = (0.2, 0.4, 0.8)
_TRUE_COLOR = rgb2int(tuple(round(component * 255) for component in _COLOR))
_POSITIONED_TRANSLATION_APPID = "BCS_POSITIONED_TRANSLATION"
_POSITIONED_LAYOUT_PROOF_FIELDS = (
    "positioned_character_text",
    "positioned_source_glyph_ids",
    "positioned_source_glyph_names",
    "positioned_character_origins",
    "positioned_character_quads",
    "positioned_character_local_bboxes",
    "positioned_character_rotations",
    "positioned_character_count",
    "positioned_layout_bijection_verified",
    "positioned_source_font_glyphs_verified",
    "positioned_source_font_identity_sha256",
    "positioned_layout_sha256",
    "positioned_visible_geometry_fill_only",
    "positioned_contour_entities_omitted",
)
_POSITIONED_PAGE_TRANSLATION_PROOF_FIELDS = (
    "export_page_translation",
    "positioned_pretranslation_character_origins",
    "positioned_pretranslation_character_quads",
    "positioned_export_translation_verified",
)
_POSITIONED_RECEIPT_PROOF_FIELDS = (
    "positioned_translation_receipt_schema",
    "positioned_translation_receipt_sha256",
)
_POSITIONED_GEOMETRY_PROOF_FIELDS = (
    "positioned_geometry_character_solid_counts",
    "positioned_geometry_fingerprint_schema",
    "positioned_geometry_entity_count",
    "positioned_geometry_sha256",
)


def _world_point(
    point: tuple[float, float],
    *,
    scale: float,
    rotation: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    angle = math.radians(rotation)
    x = point[0] * scale
    y = point[1] * scale
    return (
        origin[0] + x * math.cos(angle) - y * math.sin(angle),
        origin[1] + x * math.sin(angle) + y * math.cos(angle),
    )


def _layout_char(
    text: str,
    glyph_id: int,
    local_origin: tuple[float, float],
    *,
    scale: float,
    rotation: float,
    origin: tuple[float, float],
) -> TextCharLayout:
    local_quad = (
        (local_origin[0], local_origin[1] + 0.4),
        (local_origin[0] + 0.5, local_origin[1] + 0.4),
        (local_origin[0] + 0.5, local_origin[1] - 0.4),
        (local_origin[0], local_origin[1] - 0.4),
    )
    target_quad = tuple(
        _world_point(point, scale=scale, rotation=rotation, origin=origin)
        for point in local_quad
    )
    target_origin = _world_point(
        local_origin,
        scale=scale,
        rotation=rotation,
        origin=origin,
    )
    source_quad = tuple((x + 300.0, 700.0 - y) for x, y in target_quad)
    source_origin = (target_origin[0] + 300.0, 700.0 - target_origin[1])
    source_x = [point[0] for point in source_quad]
    source_y = [point[1] for point in source_quad]
    return TextCharLayout(
        text=text,
        glyph_id=glyph_id,
        source_origin_pdf=source_origin,
        source_bbox_pdf=(min(source_x), min(source_y), max(source_x), max(source_y)),
        source_quad_pdf=source_quad,
        target_origin=target_origin,
        target_quad=target_quad,
        advance_width=0.5 * scale,
        glyph_height=0.8 * scale,
    )


def _positioned_fraction(
    encoding: str,
    *,
    scale: float = 1.0,
    rotation: float = 0.0,
    origin: tuple[float, float] = (100.0, 200.0),
    color: tuple[float, float, float] = _COLOR,
) -> NormalizedText:
    if encoding == "vertical":
        local_origins = (
            (-0.275, 1.2),
            (0.275, 1.2),
            (0.0, 0.0),
            (-0.275, -1.2),
            (0.275, -1.2),
        )
    elif encoding == "horizontal":
        local_origins = (
            (-2.3, 0.0),
            (-1.75, 0.0),
            (0.0, 0.0),
            (1.2, 0.0),
            (1.75, 0.0),
        )
    else:  # pragma: no cover - helper guard
        raise ValueError(encoding)
    layout = tuple(
        _layout_char(
            character,
            glyph_id,
            local_origin,
            scale=scale,
            rotation=rotation,
            origin=origin,
        )
        for character, glyph_id, local_origin in zip(
            _TEXT,
            _GLYPH_IDS,
            local_origins,
            strict=True,
        )
    )
    target_points = [point for character in layout for point in character.target_quad]
    source_points = [point for character in layout for point in character.source_quad_pdf]
    target_x = [point[0] for point in target_points]
    target_y = [point[1] for point in target_points]
    source_x = [point[0] for point in source_points]
    source_y = [point[1] for point in source_points]
    slash_origin = layout[2].target_origin
    return NormalizedText(
        id=17,
        text=_TEXT,
        normalized=_TEXT,
        insertion=slash_origin,
        bbox=(min(target_x), min(target_y), max(target_x), max(target_y)),
        font_size=scale,
        rotation=rotation,
        font_name="BCS Deterministic Test",
        color=color,
        page_number=3,
        generic_tags=["dimension"],
        domain_tags=[{"source": "synthetic-positioned-fraction"}],
        source_bbox_pdf=(min(source_x), min(source_y), max(source_x), max(source_y)),
        source_quad_pdf=None,
        target_quad_model=None,
        advance_width=0.0,
        glyph_height=0.0,
        baseline_descent=0.0,
        source_char_layout=layout,
        requires_individual_positioning=True,
    )


def _save_reopen(
    tmp_path: Path,
    item: NormalizedText,
    mode: str,
    *,
    dxf_version: str = "R2010",
) -> tuple[object, object, object]:
    output = tmp_path / f"positioned-fraction-{mode}-{dxf_version}.dxf"
    exported, trusted_authority = _export_with_captured_anchors(
        DocumentExtraction(
            pdf_path=str(tmp_path / "must-not-be-read.pdf"),
            pages=[
                ExtractedPage(
                    page_data=PageData(
                        page_number=int(item.page_number),
                        width=300.0,
                        height=100.0,
                        text_items=[item],
                    ),
                    profile=SimpleNamespace(),
                )
            ],
        ),
        output,
        DxfExportOptions(
            include_images=False,
            attach_metadata=False,
            text_mode=mode,
            dxf_version=dxf_version,
            page_arrangement="overlay",
        ),
    )
    delivery = copy.deepcopy(exported.text_deliveries[0])
    result = TextDeliveryResult(
        source_id=str(delivery["source_id"]),
        requested_representation=str(delivery["requested_representation"]),
        final_representation=delivery["final_representation"],
        verified=bool(delivery["verified"]),
        entity_handles=list(delivery["entity_handles"]),
        support_entity_handles=list(delivery["support_entity_handles"]),
        referenced_entity_handles=list(delivery["referenced_entity_handles"]),
        attempts=[TextDeliveryAttempt(**attempt) for attempt in delivery["attempts"]],
        terminal_fallback_authorized=bool(
            delivery["terminal_fallback_authorized"]
        ),
        failure_reason=str(delivery["failure_reason"]),
    )
    return ezdxf.readfile(output), result, trusted_authority


def _rotation_from_quad(quad: tuple[tuple[float, float], ...]) -> float:
    dx = quad[1][0] - quad[0][0]
    dy = quad[1][1] - quad[0][1]
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _local_quad_bbox(character: TextCharLayout) -> tuple[float, float, float, float]:
    angle = math.radians(_rotation_from_quad(character.target_quad))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    values = []
    for x, y in character.target_quad:
        dx = x - character.target_origin[0]
        dy = y - character.target_origin[1]
        values.append((dx * cosine + dy * sine, -dx * sine + dy * cosine))
    return (
        min(value[0] for value in values),
        min(value[1] for value in values),
        max(value[0] for value in values),
        max(value[1] for value in values),
    )


@pytest.mark.parametrize(
    ("mode", "encoding", "scale", "rotation"),
    [
        ("text", "vertical", 1.0, 0.0),
        ("labels", "horizontal", 1.0, 0.0),
        ("glyphs", "vertical", 10.0, -90.0),
        ("3d_text", "horizontal", 2.75, 37.0),
    ],
)
def test_positioned_fraction_persists_one_ordered_fill_only_glyph_delivery(
    tmp_path: Path,
    mode: str,
    encoding: str,
    scale: float,
    rotation: float,
) -> None:
    item = _positioned_fraction(encoding, scale=scale, rotation=rotation)

    reopened, result, _trusted_anchors = _save_reopen(tmp_path, item, mode)

    assert result.verified is True
    assert result.final_representation == "glyphs"
    assert result.source_id == "text_span:3:17"
    assert len(result.entity_handles) == len(set(result.entity_handles)) == 1
    assert len([attempt for attempt in result.attempts if attempt.outcome == "verified"]) == 1
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    assert final.evidence["positioned_character_text"] == list(_TEXT)
    assert final.evidence["positioned_source_glyph_ids"] == list(_GLYPH_IDS)
    assert final.evidence["positioned_character_count"] == len(_TEXT)
    assert final.evidence["positioned_layout_bijection_verified"] is True
    assert final.evidence["positioned_source_font_glyphs_verified"] is True
    assert final.evidence["positioned_visible_geometry_fill_only"] is True
    assert final.evidence["positioned_contour_entities_omitted"] is True
    assert final.evidence["font_exact_match"] is True

    outer = next(iter(reopened.modelspace()))
    assert outer.dxftype() == "INSERT"
    assert tuple(outer.dxf.insert)[:2] == pytest.approx(item.insertion)
    assert outer.dxf.true_color == _TRUE_COLOR
    outer_block = reopened.blocks.get(outer.dxf.name)
    nested = list(outer_block)
    assert len(nested) == len(item.source_char_layout)
    assert all(child.dxftype() == "INSERT" for child in nested)
    assert len({str(child.dxf.handle) for child in nested}) == len(nested)

    for character, child in zip(item.source_char_layout, nested, strict=True):
        expected_insert = (
            character.target_origin[0] - item.insertion[0],
            character.target_origin[1] - item.insertion[1],
        )
        assert tuple(child.dxf.insert)[:2] == pytest.approx(expected_insert, abs=1e-9)
        assert float(child.dxf.rotation) % 360.0 == pytest.approx(
            _rotation_from_quad(character.target_quad),
            abs=1e-9,
        )
        assert child.dxf.xscale == pytest.approx(1.0)
        assert child.dxf.yscale == pytest.approx(1.0)
        assert child.dxf.true_color == _TRUE_COLOR

        definition = reopened.blocks.get(child.dxf.name)
        outline_entities = [
            entity
            for entity in definition
            if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
        ]
        visible_entities = [
            entity
            for entity in definition
            if int(entity.dxf.get("invisible", 0) or 0) == 0
        ]
        assert outline_entities == []
        assert visible_entities
        assert {entity.dxftype() for entity in visible_entities} == {"SOLID"}
        assert all(entity.dxf.true_color == _TRUE_COLOR for entity in definition)
        assert _bbox_tuple(visible_entities) == pytest.approx(
            _local_quad_bbox(character),
            abs=max(1e-7, scale * 1e-6),
        )

    slash = nested[2]
    assert tuple(slash.dxf.insert)[:2] == pytest.approx((0.0, 0.0), abs=1e-9)
    assert float(slash.dxf.rotation) % 360.0 == pytest.approx(rotation % 360.0)
    all_outlines = list(iter_glyph_outline_entities(outer))
    assert all_outlines
    assert _bbox_tuple(all_outlines) is not None


def test_positioned_fraction_geometry_is_persisted_as_fill_only_raw_geometry(
    tmp_path: Path,
) -> None:
    item = _positioned_fraction("vertical", scale=3.25, rotation=23.0)

    reopened, result, _trusted_anchors = _save_reopen(tmp_path, item, "geometry")

    assert result.verified is True
    assert result.final_representation == "geometry"
    assert result.source_id == "text_span:3:17"
    assert len(result.entity_handles) == len(set(result.entity_handles))
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    assert final.evidence["positioned_character_text"] == list(_TEXT)
    assert final.evidence["positioned_source_glyph_ids"] == list(_GLYPH_IDS)
    assert final.evidence["positioned_visible_geometry_fill_only"] is True
    assert final.evidence["positioned_contour_entities_omitted"] is True
    entities = list(reopened.modelspace())
    character_solid_counts = final.evidence[
        "positioned_geometry_character_solid_counts"
    ]
    assert len(character_solid_counts) == len(_TEXT)
    assert all(count > 0 for count in character_solid_counts)
    assert sum(character_solid_counts) == len(result.entity_handles)
    assert final.evidence["positioned_geometry_fingerprint_schema"] == (
        "ordered-positioned-character-solids-v1"
    )
    assert final.evidence["positioned_geometry_entity_count"] == len(
        result.entity_handles
    )
    assert final.evidence["positioned_geometry_sha256"] == (
        text_builder._positioned_geometry_fingerprint(
            entities,
            character_solid_counts=character_solid_counts,
            character_text=final.evidence["positioned_character_text"],
            source_glyph_ids=final.evidence["positioned_source_glyph_ids"],
        )
    )
    outlines = [
        entity for entity in entities if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
    ]
    visible = [
        entity for entity in entities if int(entity.dxf.get("invisible", 0) or 0) == 0
    ]
    assert outlines == []
    assert visible
    assert {entity.dxftype() for entity in visible} == {"SOLID"}
    assert all(entity.dxf.true_color == _TRUE_COLOR for entity in entities)
    assert _bbox_tuple(entities) == pytest.approx(
        final.evidence["expected_outline_bbox"],
        abs=1e-7,
    )


def _two_page_positioned_fraction_extraction(
    source: Path,
    item: NormalizedText,
) -> DocumentExtraction:
    return DocumentExtraction(
        pdf_path=str(source),
        pages=[
            ExtractedPage(
                page_data=PageData(page_number=1, width=300.0, height=100.0),
                profile=SimpleNamespace(),
            ),
            ExtractedPage(
                page_data=PageData(
                    page_number=2,
                    width=300.0,
                    height=100.0,
                    text_items=[item],
                ),
                profile=SimpleNamespace(),
            ),
        ],
    )


def _derived_untrusted_anchor(delivery: dict[str, object]) -> SimpleNamespace:
    verified = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )
    evidence = verified["evidence"]
    return SimpleNamespace(
        source_id=str(delivery["source_id"]),
        final_representation=str(delivery["final_representation"]),
        strategy=str(verified["strategy"]),
        entity_handles=tuple(map(str, delivery["entity_handles"])),
        export_page_translation=tuple(evidence["export_page_translation"]),
        pretranslation_character_origins=tuple(
            tuple(point)
            for point in evidence["positioned_pretranslation_character_origins"]
        ),
        pretranslation_character_quads=tuple(
            tuple(tuple(point) for point in quad)
            for quad in evidence["positioned_pretranslation_character_quads"]
        ),
        positioned_character_origins=tuple(
            tuple(point) for point in evidence["positioned_character_origins"]
        ),
        positioned_character_quads=tuple(
            tuple(tuple(point) for point in quad)
            for quad in evidence["positioned_character_quads"]
        ),
    )


def _derived_exact_anchor(delivery: dict[str, object]) -> _PositionedTranslationAnchor:
    derived = _derived_untrusted_anchor(delivery)
    return _PositionedTranslationAnchor(**vars(derived))


def _anchor_with(anchor: object, **changes: object) -> object:
    try:
        return replace(anchor, **changes)
    except TypeError:
        values = dict(vars(anchor))
        values.update(changes)
        return SimpleNamespace(**values)


def _authority_with_anchor_map(
    authority: object,
    anchors: dict[str, object],
) -> object:
    if not hasattr(authority, "anchors"):
        return MappingProxyType(dict(anchors))
    forged = object.__new__(type(authority))
    for name in authority.__slots__:
        if name == "__weakref__":
            continue
        object.__setattr__(forged, name, getattr(authority, name))
    capabilities = {source_id: object() for source_id in anchors}
    object.__setattr__(forged, "_anchors", MappingProxyType(dict(anchors)))
    object.__setattr__(
        forged,
        "_anchor_capabilities",
        MappingProxyType(dict(capabilities)),
    )
    object.__setattr__(
        forged,
        "_anchor_registry",
        MappingProxyType(
            {
                source_id: (anchor, capabilities[source_id])
                for source_id, anchor in anchors.items()
            }
        ),
    )
    object.__setattr__(forged, "_original_session", forged)
    return forged


def _authority_anchor_map(authority: object) -> MappingProxyType:
    anchors = getattr(authority, "anchors", authority)
    return MappingProxyType(dict(anchors))


def _verify_with_trusted_anchors(
    doc: object,
    deliveries: list[dict[str, object]],
    trusted_authority: object,
) -> None:
    parameters = inspect.signature(_verify_serialized_text_deliveries).parameters
    if "trusted_positioned_session" in parameters:
        _verify_serialized_text_deliveries(
            doc,
            deliveries,
            trusted_positioned_session=trusted_authority,
        )
        return
    if "trusted_positioned_anchors" in parameters:
        _verify_serialized_text_deliveries(
            doc,
            deliveries,
            trusted_positioned_anchors=trusted_authority,
        )
        return
    _verify_serialized_text_deliveries(doc, deliveries)


def _export_with_captured_anchors(
    extraction: DocumentExtraction,
    output: Path,
    options: DxfExportOptions,
) -> tuple[object, object]:
    captured_authorities: list[object] = []

    def capture_real_verification(
        doc: object,
        deliveries: list[dict[str, object]],
        **kwargs: object,
    ) -> None:
        authority = kwargs.get(
            "trusted_positioned_session",
            kwargs.get("trusted_positioned_anchors"),
        )
        if authority is not None:
            captured_authorities.append(authority)
        _verify_with_trusted_anchors(doc, deliveries, authority)

    with patch(
        "librecad_pdf_importer.exporters.dxf_exporter."
        "_verify_serialized_text_deliveries",
        side_effect=capture_real_verification,
    ):
        result = export_to_dxf(extraction, str(output), options)
    return (
        result,
        captured_authorities[-1]
        if captured_authorities
        else MappingProxyType({}),
    )


def _export_positioned_proof_fixture(
    tmp_path: Path,
    *,
    mode: str,
    dxf_version: str,
    actual_dy: float,
) -> tuple[Path, object, dict[str, object], object]:
    """Create one real, persisted positioned delivery without opening a PDF."""

    if actual_dy not in {0.0, -120.0}:  # pragma: no cover - helper guard
        raise ValueError(actual_dy)
    source_color = (
        tuple(component / 255.0 for component in aci2rgb(5))
        if dxf_version == "R12"
        else _COLOR
    )
    page_number = 2 if actual_dy else 1
    item = replace(
        _positioned_fraction(
            "vertical",
            scale=2.75,
            rotation=37.0,
            origin=(100.0, 50.0),
            color=source_color,
        ),
        page_number=page_number,
    )
    source = tmp_path / "must-not-be-read.pdf"
    if actual_dy:
        extraction = _two_page_positioned_fraction_extraction(source, item)
    else:
        extraction = DocumentExtraction(
            pdf_path=str(source),
            pages=[
                ExtractedPage(
                    page_data=PageData(
                        page_number=1,
                        width=300.0,
                        height=100.0,
                        text_items=[item],
                    ),
                    profile=SimpleNamespace(),
                )
            ],
    )
    offset_label = "negative-120" if actual_dy else "zero"
    output = tmp_path / f"positioned-proof-{mode}-{dxf_version}-{offset_label}.dxf"
    result, captured_anchors = _export_with_captured_anchors(
        extraction,
        output,
        DxfExportOptions(
            include_images=False,
            attach_metadata=False,
            text_mode=mode,
            dxf_version=dxf_version,
            page_arrangement="spread",
            page_gap_ratio=0.02,
        ),
    )
    assert len(result.text_deliveries) == 1
    delivery = copy.deepcopy(result.text_deliveries[0])
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    assert evidence["export_page_translation"] == [0.0, actual_dy]
    trusted_anchors = (
        captured_anchors
        if captured_anchors
        else MappingProxyType(
            {str(delivery["source_id"]): _derived_untrusted_anchor(delivery)}
        )
    )
    return output, ezdxf.readfile(output), delivery, trusted_anchors


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
def test_reopen_rejects_coherently_falsified_negative_page_translation(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode=mode,
        dxf_version=dxf_version,
        actual_dy=-120.0,
    )
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    evidence["export_page_translation"] = [0.0, 0.0]
    evidence["positioned_pretranslation_character_origins"] = copy.deepcopy(
        evidence["positioned_character_origins"]
    )
    evidence["positioned_pretranslation_character_quads"] = copy.deepcopy(
        evidence["positioned_character_quads"]
    )
    evidence["positioned_export_translation_verified"] = True

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
def test_reopen_rejects_zero_page_translation_falsified_as_positive(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode=mode,
        dxf_version=dxf_version,
        actual_dy=0.0,
    )
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    false_dy = 73.0
    evidence["export_page_translation"] = [0.0, false_dy]
    evidence["positioned_pretranslation_character_origins"] = [
        [float(point[0]), float(point[1]) - false_dy]
        for point in evidence["positioned_character_origins"]
    ]
    evidence["positioned_pretranslation_character_quads"] = [
        [
            [float(point[0]), float(point[1]) - false_dy]
            for point in quad
        ]
        for quad in evidence["positioned_character_quads"]
    ]
    evidence["positioned_export_translation_verified"] = True

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


_MANDATORY_POSITIONED_PROOF_CASES = [
    pytest.param(mode, field, id=f"{mode}-{field}")
    for mode in ("glyphs", "geometry")
    for field in (
        _POSITIONED_LAYOUT_PROOF_FIELDS
        + _POSITIONED_PAGE_TRANSLATION_PROOF_FIELDS
        + _POSITIONED_RECEIPT_PROOF_FIELDS
        + (_POSITIONED_GEOMETRY_PROOF_FIELDS if mode == "geometry" else ())
    )
]


@pytest.mark.parametrize(("mode", "missing_field"), _MANDATORY_POSITIONED_PROOF_CASES)
def test_reopen_rejects_deletion_of_each_mandatory_positioned_proof_field(
    tmp_path: Path,
    mode: str,
    missing_field: str,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode=mode,
        dxf_version="R2010",
        actual_dy=0.0,
    )
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    evidence.pop(missing_field, None)

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
def test_positioned_translation_receipt_roundtrips_on_every_main_entity(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
) -> None:
    _output, reopened, delivery, _trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode=mode,
        dxf_version=dxf_version,
        actual_dy=-120.0,
    )
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    expected_receipt = [
        (1000, evidence["positioned_translation_receipt_schema"]),
        (1000, evidence["positioned_translation_receipt_sha256"]),
    ]

    assert reopened.appids.has_entry(_POSITIONED_TRANSLATION_APPID)
    for handle in delivery["entity_handles"]:
        entity = reopened.entitydb.get(handle)
        assert entity is not None
        actual_receipt = [
            (int(tag.code), str(tag.value))
            for tag in entity.get_xdata(_POSITIONED_TRANSLATION_APPID)
        ]
        assert actual_receipt == expected_receipt


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
@pytest.mark.parametrize("tamper", ["remove", "schema", "digest"])
def test_reopen_rejects_removed_or_mutated_positioned_translation_receipt(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
    tamper: str,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode=mode,
        dxf_version=dxf_version,
        actual_dy=-120.0,
    )
    first_entity = reopened.entitydb.get(delivery["entity_handles"][0])
    assert first_entity is not None
    if tamper == "remove":
        first_entity.discard_xdata(_POSITIONED_TRANSLATION_APPID)
    else:
        if not reopened.appids.has_entry(_POSITIONED_TRANSLATION_APPID):
            reopened.appids.add(_POSITIONED_TRANSLATION_APPID)
        evidence = next(
            attempt
            for attempt in delivery["attempts"]
            if attempt["outcome"] == "verified"
        )["evidence"]
        schema = str(
            evidence.get("positioned_translation_receipt_schema")
            or "positioned-translation-receipt-v1"
        )
        digest = str(
            evidence.get("positioned_translation_receipt_sha256") or "1" * 64
        )
        first_entity.set_xdata(
            _POSITIONED_TRANSLATION_APPID,
            [
                (1000, "mutated-schema" if tamper == "schema" else schema),
                (1000, "0" * 64 if tamper == "digest" else digest),
            ],
        )
    tampered_output = tmp_path / f"tampered-{mode}-{dxf_version}-{tamper}.dxf"
    reopened.saveas(tampered_output)
    persisted_tamper = ezdxf.readfile(tampered_output)

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            persisted_tamper,
            [delivery],
            trusted_anchors,
        )


def _coherently_rebind_claimed_translation(
    reopened: object,
    delivery: dict[str, object],
    *,
    claimed_dy: float,
) -> None:
    verified = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )
    evidence = verified["evidence"]
    evidence["export_page_translation"] = [0.0, claimed_dy]
    evidence["positioned_pretranslation_character_origins"] = [
        [float(point[0]), float(point[1]) - claimed_dy]
        for point in evidence["positioned_character_origins"]
    ]
    evidence["positioned_pretranslation_character_quads"] = [
        [
            [float(point[0]), float(point[1]) - claimed_dy]
            for point in quad
        ]
        for quad in evidence["positioned_character_quads"]
    ]
    evidence["positioned_export_translation_verified"] = True
    rebound_digest = _positioned_translation_receipt_digest(
        evidence=evidence,
        source_id=str(delivery["source_id"]),
        representation=str(delivery["final_representation"]),
        strategy=str(verified["strategy"]),
        entity_handles=list(map(str, delivery["entity_handles"])),
    )
    evidence["positioned_translation_receipt_sha256"] = rebound_digest
    rebound_tags = [
        (1000, evidence["positioned_translation_receipt_schema"]),
        (1000, rebound_digest),
    ]
    for handle in delivery["entity_handles"]:
        entity = reopened.entitydb.get(str(handle))
        assert entity is not None
        entity.set_xdata(_POSITIONED_TRANSLATION_APPID, rebound_tags)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
@pytest.mark.parametrize(
    ("actual_dy", "claimed_dy"),
    [
        pytest.param(-120.0, 0.0, id="negative-120-as-zero"),
        pytest.param(0.0, 73.0, id="zero-as-positive-73"),
    ],
)
def test_reopen_rejects_coordinated_evidence_and_all_xdata_translation_rebind(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
    actual_dy: float,
    claimed_dy: float,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode=mode,
        dxf_version=dxf_version,
        actual_dy=actual_dy,
    )
    preserved_anchor = _authority_anchor_map(trusted_anchors)[
        str(delivery["source_id"])
    ]
    _coherently_rebind_claimed_translation(
        reopened,
        delivery,
        claimed_dy=claimed_dy,
    )
    tampered_output = (
        tmp_path
        / f"coordinated-{mode}-{dxf_version}-{actual_dy}-{claimed_dy}.dxf"
    )
    reopened.saveas(tampered_output)
    persisted_tamper = ezdxf.readfile(tampered_output)

    assert (
        _authority_anchor_map(trusted_anchors)[str(delivery["source_id"])]
        is preserved_anchor
    )
    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            persisted_tamper,
            [delivery],
            trusted_anchors,
        )


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
@pytest.mark.parametrize(
    ("actual_dy", "claimed_dy"),
    [
        pytest.param(-120.0, 0.0, id="negative-120-as-zero"),
        pytest.param(0.0, 73.0, id="zero-as-positive-73"),
    ],
)
def test_reopen_rejects_exact_class_anchor_forged_from_coherent_tamper(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
    actual_dy: float,
    claimed_dy: float,
) -> None:
    _output, reopened, delivery, trusted_authority = (
        _export_positioned_proof_fixture(
            tmp_path,
            mode=mode,
            dxf_version=dxf_version,
            actual_dy=actual_dy,
        )
    )
    _coherently_rebind_claimed_translation(
        reopened,
        delivery,
        claimed_dy=claimed_dy,
    )
    tampered_output = (
        tmp_path
        / f"exact-class-forgery-{mode}-{dxf_version}-{actual_dy}-{claimed_dy}.dxf"
    )
    reopened.saveas(tampered_output)
    persisted_tamper = ezdxf.readfile(tampered_output)
    source_id = str(delivery["source_id"])
    forged_anchor = _derived_exact_anchor(delivery)
    forged_authority = _authority_with_anchor_map(
        trusted_authority,
        {source_id: forged_anchor},
    )

    assert type(forged_anchor) is _PositionedTranslationAnchor
    assert forged_anchor is not _authority_anchor_map(trusted_authority)[source_id]
    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            persisted_tamper,
            [delivery],
            forged_authority,
        )


@pytest.mark.parametrize(
    "attack",
    ["shallow-copy", "deep-copy", "dataclasses-replace"],
)
def test_positioned_verification_rejects_copied_authority_or_anchor(
    tmp_path: Path,
    attack: str,
) -> None:
    _output, reopened, delivery, trusted_authority = (
        _export_positioned_proof_fixture(
            tmp_path,
            mode="glyphs",
            dxf_version="R2010",
            actual_dy=-120.0,
        )
    )
    source_id = str(delivery["source_id"])
    original_anchor = _authority_anchor_map(trusted_authority)[source_id]
    if attack == "shallow-copy":
        forged_authority = (
            copy.copy(trusted_authority)
            if hasattr(trusted_authority, "anchors")
            else MappingProxyType(dict(_authority_anchor_map(trusted_authority)))
        )
    elif attack == "deep-copy":
        copied_anchors = copy.deepcopy(dict(_authority_anchor_map(trusted_authority)))
        forged_authority = _authority_with_anchor_map(
            trusted_authority,
            copied_anchors,
        )
    else:
        replaced_anchor = replace(original_anchor)
        assert replaced_anchor is not original_anchor
        forged_authority = _authority_with_anchor_map(
            trusted_authority,
            {source_id: replaced_anchor},
        )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            reopened,
            [delivery],
            forged_authority,
        )


def test_positioned_verification_rejects_forged_session_or_map(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, trusted_authority = (
        _export_positioned_proof_fixture(
            tmp_path,
            mode="geometry",
            dxf_version="R2010",
            actual_dy=-120.0,
        )
    )
    anchors = dict(_authority_anchor_map(trusted_authority))
    if hasattr(trusted_authority, "anchors"):
        exact_class_forgery = _authority_with_anchor_map(
            trusted_authority,
            anchors,
        )
        with pytest.raises(RuntimeError):
            _verify_with_trusted_anchors(
                reopened,
                [delivery],
                exact_class_forgery,
            )
        with pytest.raises((TypeError, RuntimeError)):
            forged_session = type(trusted_authority)(anchors)
            _verify_with_trusted_anchors(reopened, [delivery], forged_session)
        return

    forged_map = MappingProxyType(anchors)
    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], forged_map)


def test_positioned_session_anchor_registry_is_alias_safe_and_read_only(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, trusted_authority = (
        _export_positioned_proof_fixture(
            tmp_path,
            mode="glyphs",
            dxf_version="R2010",
            actual_dy=-120.0,
        )
    )
    assert hasattr(trusted_authority, "anchors")
    source_id = str(delivery["source_id"])
    original_anchor = trusted_authority.anchors[source_id]
    detached_alias = dict(trusted_authority.anchors)
    detached_alias[source_id] = replace(original_anchor)

    assert trusted_authority.anchors[source_id] is original_anchor
    with pytest.raises(TypeError):
        trusted_authority.anchors[source_id] = detached_alias[source_id]
    _verify_with_trusted_anchors(reopened, [delivery], trusted_authority)


def test_authenticated_anchor_map_is_a_detached_canonical_snapshot(
    tmp_path: Path,
) -> None:
    _output, _reopened, delivery, trusted_authority = (
        _export_positioned_proof_fixture(
            tmp_path,
            mode="glyphs",
            dxf_version="R2010",
            actual_dy=-120.0,
        )
    )
    source_id = str(delivery["source_id"])
    original_anchor = trusted_authority._anchors[source_id]
    authenticated = _positioned_session_anchor_map(
        trusted_authority,
        positioned_roster={source_id},
    )
    snapshot_anchor = authenticated[source_id]
    expected_translation = snapshot_anchor.export_page_translation

    assert authenticated is not trusted_authority._anchors
    assert snapshot_anchor is not original_anchor
    assert snapshot_anchor == original_anchor
    with pytest.raises(TypeError):
        authenticated[source_id] = original_anchor

    object.__setattr__(
        original_anchor,
        "export_page_translation",
        (expected_translation[0], expected_translation[1] + 73.0),
    )
    assert snapshot_anchor.export_page_translation == expected_translation
    assert snapshot_anchor != original_anchor


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("dxf_version", ["R12", "R2010"])
@pytest.mark.parametrize(
    ("actual_dy", "claimed_dy"),
    [
        pytest.param(-120.0, 0.0, id="negative-120-as-zero"),
        pytest.param(0.0, 73.0, id="zero-as-positive-73"),
    ],
)
def test_reopen_rejects_in_place_mutation_of_original_session_anchor_alias(
    tmp_path: Path,
    mode: str,
    dxf_version: str,
    actual_dy: float,
    claimed_dy: float,
) -> None:
    _output, reopened, delivery, trusted_authority = (
        _export_positioned_proof_fixture(
            tmp_path,
            mode=mode,
            dxf_version=dxf_version,
            actual_dy=actual_dy,
        )
    )
    source_id = str(delivery["source_id"])
    exposed_anchor = trusted_authority.anchors[source_id]
    _coherently_rebind_claimed_translation(
        reopened,
        delivery,
        claimed_dy=claimed_dy,
    )
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    object.__setattr__(
        exposed_anchor,
        "export_page_translation",
        tuple(evidence["export_page_translation"]),
    )
    object.__setattr__(
        exposed_anchor,
        "pretranslation_character_origins",
        tuple(
            tuple(point)
            for point in evidence["positioned_pretranslation_character_origins"]
        ),
    )
    object.__setattr__(
        exposed_anchor,
        "pretranslation_character_quads",
        tuple(
            tuple(tuple(point) for point in quad)
            for quad in evidence["positioned_pretranslation_character_quads"]
        ),
    )
    tampered_output = (
        tmp_path
        / f"original-alias-{mode}-{dxf_version}-{actual_dy}-{claimed_dy}.dxf"
    )
    reopened.saveas(tampered_output)

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            ezdxf.readfile(tampered_output),
            [delivery],
            trusted_authority,
        )


def test_positioned_verification_rejects_missing_authoritative_anchor(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, _trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=-120.0,
    )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            reopened,
            [delivery],
            _authority_with_anchor_map(_trusted_anchors, {}),
        )


def test_positioned_verification_rejects_extra_authoritative_anchor(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=-120.0,
    )
    source_id = str(delivery["source_id"])
    anchor = _authority_anchor_map(trusted_anchors)[source_id]
    anchors_with_extra = _authority_with_anchor_map(
        trusted_anchors,
        {source_id: anchor, "text_span:999:999": anchor},
    )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], anchors_with_extra)


def test_positioned_verification_rejects_anchor_rebound_from_another_source(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, _trusted_anchors = _export_positioned_proof_fixture(
        tmp_path / "original",
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=-120.0,
    )
    (
        _other_output,
        _other_reopened,
        other_delivery,
        other_anchors,
    ) = _export_positioned_proof_fixture(
        tmp_path / "other",
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=0.0,
    )
    rebound = _authority_with_anchor_map(
        _trusted_anchors,
        {
            str(delivery["source_id"]): _authority_anchor_map(other_anchors)[
                str(other_delivery["source_id"])
            ]
        },
    )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], rebound)


@pytest.mark.parametrize(
    "anchor_field",
    ["source_id", "entity_handles", "final_representation", "entity_order"],
)
def test_positioned_verification_rejects_authoritative_anchor_identity_swap(
    tmp_path: Path,
    anchor_field: str,
) -> None:
    _output, reopened, delivery, trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode="geometry",
        dxf_version="R2010",
        actual_dy=-120.0,
    )
    source_id = str(delivery["source_id"])
    anchor = _authority_anchor_map(trusted_anchors)[source_id]
    original_handles = tuple(anchor.entity_handles)
    assert len(original_handles) > 1
    if anchor_field == "source_id":
        changed_anchor = _anchor_with(anchor, source_id="text_span:777:777")
    elif anchor_field == "entity_handles":
        changed_anchor = _anchor_with(
            anchor,
            entity_handles=("FFFF", *original_handles[1:]),
        )
    elif anchor_field == "final_representation":
        changed_anchor = _anchor_with(anchor, final_representation="glyphs")
    else:
        changed_anchor = _anchor_with(
            anchor,
            entity_handles=tuple(reversed(original_handles)),
        )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            reopened,
            [delivery],
            _authority_with_anchor_map(
                trusted_anchors,
                {source_id: changed_anchor},
            ),
        )


def test_positioned_verification_rejects_evidence_derived_public_anchor(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, _trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=-120.0,
    )
    source_id = str(delivery["source_id"])
    evidence_derived = MappingProxyType(
        {source_id: _derived_untrusted_anchor(delivery)}
    )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], evidence_derived)


def test_independent_process_positioned_verification_without_anchor_fails_closed(
    tmp_path: Path,
) -> None:
    _output, reopened, delivery, _trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=-120.0,
    )

    with pytest.raises(TypeError):
        _verify_serialized_text_deliveries(reopened, [delivery])


def test_explicit_null_positioned_anchor_map_fails_closed(tmp_path: Path) -> None:
    _output, reopened, delivery, _trusted_anchors = _export_positioned_proof_fixture(
        tmp_path,
        mode="glyphs",
        dxf_version="R2010",
        actual_dy=-120.0,
    )

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], None)


def test_nonpositioned_delivery_requires_exact_empty_authoritative_anchor_map(
    tmp_path: Path,
) -> None:
    _empty_result, trusted_authority = _export_with_captured_anchors(
        DocumentExtraction(
            pdf_path=str(tmp_path / "must-not-be-read.pdf"),
            pages=[
                ExtractedPage(
                    page_data=PageData(page_number=1, width=20.0, height=10.0),
                    profile=SimpleNamespace(),
                )
            ],
        ),
        tmp_path / "empty-production-session.dxf",
        DxfExportOptions(
            include_images=False,
            include_text=False,
            attach_metadata=False,
            dxf_version="R2010",
        ),
    )
    assert hasattr(trusted_authority, "anchors")
    assert dict(trusted_authority.anchors) == {}
    doc = ezdxf.new("R2010")
    entity = doc.modelspace().add_text(
        "W12X30",
        dxfattribs={"height": 2.0, "rotation": 0.0},
    )
    entity.dxf.insert = (12.25, 24.5)
    handle = str(entity.dxf.handle)
    delivery = {
        "source_id": "text_span:1:451",
        "final_representation": "text",
        "verified": True,
        "entity_handles": [handle],
        "support_entity_handles": [],
        "referenced_entity_handles": [],
        "attempts": [
            {
                "outcome": "verified",
                "entity_handles": [handle],
                "support_entity_handles": [],
                "referenced_entity_handles": [],
                "evidence": {
                    "delivered_content": "W12X30",
                    "expected_insert": [12.25, 24.5],
                    "expected_height": 2.0,
                    "expected_rotation": 0.0,
                    "font_exact_match": False,
                    "resolved_font_filename": None,
                },
            }
        ],
    }
    output = tmp_path / "ordinary-native-text.dxf"
    doc.saveas(output)
    reopened = ezdxf.readfile(output)

    _verify_with_trusted_anchors(
        reopened,
        [delivery],
        trusted_authority,
    )
    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(
            reopened,
            [delivery],
            _authority_with_anchor_map(
                trusted_authority,
                {"text_span:999:999": SimpleNamespace()},
            ),
        )


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_multi_page_stack_translates_positioned_fraction_layout_and_reopen_evidence(
    tmp_path: Path,
    mode: str,
) -> None:
    item = replace(
        _positioned_fraction(
            "vertical",
            scale=2.75,
            rotation=37.0,
            origin=(100.0, 50.0),
        ),
        page_number=2,
    )
    original = copy.deepcopy(item)
    output = tmp_path / f"two-page-positioned-{mode}.dxf"

    result, trusted_anchors = _export_with_captured_anchors(
        _two_page_positioned_fraction_extraction(
            tmp_path / "must-not-be-read.pdf",
            item,
        ),
        output,
        DxfExportOptions(
            include_images=False,
            attach_metadata=False,
            text_mode=mode,
            dxf_version="R2010",
            page_arrangement="spread",
            page_gap_ratio=0.02,
        ),
    )

    assert item == original
    assert len(result.text_deliveries) == 1
    delivery = result.text_deliveries[0]
    verified = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )
    evidence = verified["evidence"]
    expected_dy = -120.0
    assert evidence["export_page_translation"] == [0.0, expected_dy]
    assert evidence["positioned_export_translation_verified"] is True
    assert evidence["positioned_pretranslation_character_origins"] == [
        list(character.target_origin) for character in original.source_char_layout
    ]
    assert evidence["positioned_pretranslation_character_quads"] == [
        [list(point) for point in character.target_quad]
        for character in original.source_char_layout
    ]
    for before, after in zip(
        evidence["positioned_pretranslation_character_origins"],
        evidence["positioned_character_origins"],
        strict=True,
    ):
        assert after == pytest.approx((before[0], before[1] + expected_dy), abs=1e-9)
    for before_quad, after_quad in zip(
        evidence["positioned_pretranslation_character_quads"],
        evidence["positioned_character_quads"],
        strict=True,
    ):
        for before_point, after_point in zip(before_quad, after_quad, strict=True):
            assert after_point == pytest.approx(
                (before_point[0], before_point[1] + expected_dy),
                abs=1e-9,
            )

    reopened = ezdxf.readfile(output)
    _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)
    if mode == "glyphs":
        outer = next(iter(reopened.modelspace()))
        assert tuple(outer.dxf.insert)[:2] == pytest.approx(
            (original.insertion[0], original.insertion[1] + expected_dy),
            abs=1e-9,
        )
    else:
        serialized_bbox = _bbox_tuple(list(reopened.modelspace()))
        assert serialized_bbox == pytest.approx(
            evidence["expected_outline_bbox"],
            abs=1e-7,
        )


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_multi_page_stack_does_not_repair_malformed_layout_container(
    tmp_path: Path,
    mode: str,
) -> None:
    item = replace(
        _positioned_fraction("vertical", origin=(100.0, 50.0)),
        page_number=2,
    )
    malformed_layout = list(item.source_char_layout)
    item.source_char_layout = malformed_layout
    output = tmp_path / f"two-page-malformed-layout-{mode}.dxf"

    with pytest.raises(TextRepresentationDeliveryError) as raised:
        export_to_dxf(
            _two_page_positioned_fraction_extraction(
                tmp_path / "must-not-be-read.pdf",
                item,
            ),
            str(output),
            DxfExportOptions(
                include_images=False,
                attach_metadata=False,
                text_mode=mode,
                dxf_version="R2010",
                page_arrangement="spread",
                page_gap_ratio=0.02,
            ),
        )

    assert item.source_char_layout is malformed_layout
    assert raised.value.delivery.terminal_fallback_authorized is False
    assert not output.exists()
    assert not output.with_name(f"{output.stem}_assets").exists()


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_reopen_rejects_stale_unshifted_positioned_layout_evidence(
    tmp_path: Path,
    mode: str,
) -> None:
    item = replace(
        _positioned_fraction("vertical", origin=(100.0, 50.0)),
        page_number=2,
    )
    output = tmp_path / "two-page-positioned-stale-evidence.dxf"
    result, trusted_anchors = _export_with_captured_anchors(
        _two_page_positioned_fraction_extraction(
            tmp_path / "must-not-be-read.pdf",
            item,
        ),
        output,
        DxfExportOptions(
            include_images=False,
            attach_metadata=False,
            text_mode=mode,
            dxf_version="R2010",
            page_arrangement="spread",
            page_gap_ratio=0.02,
        ),
    )
    delivery = copy.deepcopy(result.text_deliveries[0])
    evidence = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )["evidence"]
    evidence["positioned_character_origins"] = copy.deepcopy(
        evidence["positioned_pretranslation_character_origins"]
    )
    evidence["positioned_character_quads"] = copy.deepcopy(
        evidence["positioned_pretranslation_character_quads"]
    )

    with pytest.raises(RuntimeError, match="positioned page translation changed"):
        _verify_with_trusted_anchors(
            ezdxf.readfile(output),
            [delivery],
            trusted_anchors,
        )


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_reopen_requires_complete_translation_proof_for_zero_offset(
    tmp_path: Path,
    mode: str,
) -> None:
    reopened, result, trusted_anchors = _save_reopen(
        tmp_path,
        _positioned_fraction("vertical"),
        mode,
    )
    delivery = copy.deepcopy(result.to_dict())
    evidence = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )["evidence"]
    for field in (
        "export_page_translation",
        "positioned_pretranslation_character_origins",
        "positioned_pretranslation_character_quads",
        "positioned_export_translation_verified",
    ):
        evidence.pop(field)

    with pytest.raises(RuntimeError, match="positioned page translation changed"):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_reopen_cannot_delete_positioned_coordinates_and_translation_proof(
    tmp_path: Path,
    mode: str,
) -> None:
    reopened, result, trusted_anchors = _save_reopen(
        tmp_path,
        _positioned_fraction("vertical"),
        mode,
    )
    delivery = copy.deepcopy(result.to_dict())
    evidence = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )["evidence"]
    for field in (
        "positioned_character_origins",
        "positioned_character_quads",
        "export_page_translation",
        "positioned_pretranslation_character_origins",
        "positioned_pretranslation_character_quads",
        "positioned_export_translation_verified",
    ):
        evidence.pop(field)
    assert evidence["positioned_layout_bijection_verified"] is True
    assert evidence["positioned_layout_sha256"]

    with pytest.raises(RuntimeError, match="positioned page translation changed"):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


def test_reopen_cannot_delete_fill_contract_to_bypass_shifted_geometry(
    tmp_path: Path,
) -> None:
    item = replace(
        _positioned_fraction("vertical", origin=(100.0, 50.0)),
        page_number=2,
    )
    output = tmp_path / "positioned-fill-contract-bypass.dxf"
    result, trusted_anchors = _export_with_captured_anchors(
        _two_page_positioned_fraction_extraction(
            tmp_path / "must-not-be-read.pdf",
            item,
        ),
        output,
        DxfExportOptions(
            include_images=False,
            attach_metadata=False,
            text_mode="geometry",
            dxf_version="R2010",
            page_arrangement="spread",
            page_gap_ratio=0.02,
        ),
    )
    delivery = copy.deepcopy(result.text_deliveries[0])
    evidence = next(
        attempt
        for attempt in delivery["attempts"]
        if attempt["outcome"] == "verified"
    )["evidence"]
    evidence.pop("positioned_visible_geometry_fill_only")
    assert evidence["export_page_translation"] == [0.0, -120.0]
    assert evidence["positioned_geometry_sha256"]

    reopened = ezdxf.readfile(output)
    solids = [
        entity for entity in reopened.modelspace() if entity.dxftype() == "SOLID"
    ]
    assert solids
    for entity in solids:
        for attribute in ("vtx0", "vtx1", "vtx2", "vtx3"):
            point = entity.dxf.get(attribute)
            entity.dxf.set(attribute, (float(point.x), float(point.y) + 102.0))

    with pytest.raises(RuntimeError, match="positioned geometry contract changed"):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_multi_page_stack_preserves_malformed_target_origin_for_terminal_refusal(
    tmp_path: Path,
    mode: str,
) -> None:
    item = replace(
        _positioned_fraction("vertical", origin=(100.0, 50.0)),
        page_number=2,
    )
    layout = item.source_char_layout
    malformed_character = replace(layout[0], target_origin=None)
    item.source_char_layout = (malformed_character, *layout[1:])
    original_layout = item.source_char_layout
    output = tmp_path / f"two-page-malformed-target-origin-{mode}.dxf"

    with pytest.raises(TextRepresentationDeliveryError) as raised:
        export_to_dxf(
            _two_page_positioned_fraction_extraction(
                tmp_path / "must-not-be-read.pdf",
                item,
            ),
            str(output),
            DxfExportOptions(
                include_images=False,
                attach_metadata=False,
                text_mode=mode,
                dxf_version="R2010",
                page_arrangement="spread",
                page_gap_ratio=0.02,
            ),
        )

    assert item.source_char_layout is original_layout
    assert raised.value.delivery.terminal_fallback_authorized is False
    assert not output.exists()
    assert not output.with_name(f"{output.stem}_assets").exists()


def test_positioned_delivery_does_not_invent_bbox_quad_equality() -> None:
    item = _positioned_fraction("vertical", scale=1.25, rotation=31.0)
    assert item.bbox is not None
    assert item.source_bbox_pdf is not None
    item.bbox = (
        item.bbox[0] - 0.2,
        item.bbox[1] - 0.1,
        item.bbox[2] + 0.3,
        item.bbox[3] + 0.4,
    )
    item.source_bbox_pdf = (
        item.source_bbox_pdf[0] - 0.4,
        item.source_bbox_pdf[1] - 0.3,
        item.source_bbox_pdf[2] + 0.2,
        item.source_bbox_pdf[3] + 0.1,
    )
    doc = ezdxf.new("R2010")

    result = build_text(
        item,
        doc.modelspace(),
        "TEXT",
        ImportConfig(text_mode="glyphs"),
        target_app="librecad",
        dxf_version="R2010",
        return_delivery_result=True,
    )

    assert result.verified is True
    assert result.final_representation == "glyphs"
    assert result.attempts[-1].evidence["positioned_layout_bijection_verified"] is True


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_positioned_fraction_fill_only_contract_survives_r12_reopen(
    tmp_path: Path,
    mode: str,
) -> None:
    source_aci = 5
    source_rgb = tuple(int(component) for component in aci2rgb(source_aci))
    item = _positioned_fraction(
        "vertical",
        scale=1.5,
        rotation=17.0,
        color=tuple(component / 255.0 for component in source_rgb),
    )

    reopened, result, _trusted_anchors = _save_reopen(
        tmp_path,
        item,
        mode,
        dxf_version="R12",
    )

    assert result.verified is True
    assert result.final_representation == mode
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    assert final.evidence["r12_source_color_encoding"] == "exact_srgb8_aci_match"
    assert final.evidence["r12_source_color_rgb"] == list(source_rgb)
    assert final.evidence["r12_source_color_aci"] == source_aci
    assert final.evidence["r12_source_color_max_channel_error"] == 0
    if mode == "glyphs":
        outer = next(iter(reopened.modelspace()))
        assert outer.dxf.color == source_aci
        outer_block = reopened.blocks.get(outer.dxf.name)
        nested = list(outer_block)
        assert nested
        assert all(entity.dxf.color == source_aci for entity in nested)
        entities = [
            entity
            for nested_insert in nested
            for entity in reopened.blocks.get(nested_insert.dxf.name)
        ]
    else:
        entities = list(reopened.modelspace())
    outlines = [
        entity for entity in entities if entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}
    ]
    visible = [
        entity for entity in entities if int(entity.dxf.get("invisible", 0) or 0) == 0
    ]
    assert outlines == []
    assert visible
    assert {entity.dxftype() for entity in visible} == {"SOLID"}
    assert all(entity.dxf.color == source_aci for entity in entities)


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_r12_positioned_fraction_refuses_nonrepresentable_source_rgb_without_artifacts(
    mode: str,
) -> None:
    assert tuple(round(component * 255) for component in _COLOR) not in {
        tuple(int(component) for component in aci2rgb(index))
        for index in range(1, 256)
    }
    item = _positioned_fraction("vertical", color=_COLOR)
    doc = ezdxf.new("R12")

    result = build_text(
        item,
        doc.modelspace(),
        "TEXT",
        ImportConfig(text_mode=mode),
        is_r12=True,
        target_app="librecad",
        dxf_version="R12",
        return_delivery_result=True,
    )

    assert result.verified is False
    assert result.final_representation is None
    assert result.terminal_fallback_authorized is False
    assert list(doc.modelspace()) == []
    assert result.attempts
    assert result.attempts[0].strategy == "positioned_fraction_r12_color_validation"
    assert result.attempts[0].evidence == {
        "fallback_authorized_for_this_item": False,
        "item_specific_creation_attempted": False,
        "positioned_layout_bijection_verified": True,
        "r12_source_color_encoding": "unrepresentable_srgb8",
        "r12_source_color_rgb": [51, 102, 204],
    }


def test_r12_positioned_fraction_rejects_invalid_serialized_aci_evidence(
    tmp_path: Path,
) -> None:
    source_rgb = tuple(int(component) for component in aci2rgb(5))
    item = _positioned_fraction(
        "vertical",
        color=tuple(component / 255.0 for component in source_rgb),
    )
    reopened, result, trusted_anchors = _save_reopen(
        tmp_path,
        item,
        "glyphs",
        dxf_version="R12",
    )
    delivery = copy.deepcopy(result.to_dict())
    verified = next(
        attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
    )
    verified["evidence"]["r12_source_color_aci"] = 999

    with pytest.raises(RuntimeError, match="R12 color mapping changed"):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


@pytest.mark.parametrize(
    "fault",
    [
        "zero_layout",
        "partial_layout",
        "unexpected_layout_object",
        "layout_text_mismatch",
        "missing_slash",
        "reused_character_occurrence",
        "invalid_quad",
        "wrong_glyph_program",
        "mixed_font_binding",
    ],
)
def test_invalid_positioned_fraction_refuses_terminally_without_artifacts(
    fault: str,
) -> None:
    item = _positioned_fraction("vertical")
    layout = list(item.source_char_layout)
    if fault == "zero_layout":
        item.source_char_layout = ()
    elif fault == "partial_layout":
        item.source_char_layout = tuple(layout[:-1])
    elif fault == "unexpected_layout_object":
        item.source_char_layout = (*layout[:-1], SimpleNamespace(text="6"))
    elif fault == "layout_text_mismatch":
        item.source_char_layout = (replace(layout[0], text="9"), *layout[1:])
    elif fault == "missing_slash":
        item.source_char_layout = (*layout[:2], replace(layout[2], text="1"), *layout[3:])
    elif fault == "reused_character_occurrence":
        item.source_char_layout = (layout[0], layout[0], *layout[2:])
    elif fault == "invalid_quad":
        bad_quad = ((math.nan, 0.0), *layout[0].target_quad[1:])
        item.source_char_layout = (replace(layout[0], target_quad=bad_quad), *layout[1:])
    elif fault == "wrong_glyph_program":
        item.source_char_layout = (replace(layout[0], glyph_id=9999), *layout[1:])
    elif fault == "mixed_font_binding":
        item.font_asset = object()
        item.font_failure = object()

    reset_text_styles()
    doc = ezdxf.new("R2010")
    result = build_text(
        item,
        doc.modelspace(),
        "TEXT",
        ImportConfig(text_mode="text"),
        target_app="librecad",
        dxf_version="R2010",
        return_delivery_result=True,
    )

    assert result.verified is False
    assert result.final_representation is None
    assert result.terminal_fallback_authorized is False
    assert list(doc.modelspace()) == []
    assert all(attempt.cleanup_verified is True for attempt in result.attempts)
    assert all(
        attempt.evidence.get("fallback_authorized_for_this_item") is False
        for attempt in result.attempts
    )
    assert "raster" not in [attempt.attempted_representation for attempt in result.attempts]
    assert result.attempts[0].evidence["fallback_authorized_for_this_item"] is False


def test_invalid_positioned_fraction_export_never_reads_pdf_or_attempts_raster(
    tmp_path: Path,
) -> None:
    item = _positioned_fraction("vertical")
    item.source_char_layout = item.source_char_layout[:-1]
    extraction = DocumentExtraction(
        pdf_path=str(tmp_path / "must-not-be-read.pdf"),
        pages=[
            ExtractedPage(
                page_data=PageData(
                    page_number=3,
                    width=300.0,
                    height=200.0,
                    text_items=[item],
                ),
                profile=SimpleNamespace(),
            )
        ],
    )
    output = tmp_path / "existing-native-output.dxf"
    prior = b"prior native artifact\n"
    output.write_bytes(prior)

    def unchanged_delivery(delivery, **_kwargs):
        return delivery, None

    with (
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter._file_sha256",
            return_value="0" * 64,
        ) as hash_pdf,
        patch(
            "librecad_pdf_importer.exporters.dxf_exporter._attempt_terminal_text_raster",
            side_effect=unchanged_delivery,
        ) as raster_fallback,
        pytest.raises(TextRepresentationDeliveryError) as raised,
    ):
        export_to_dxf(
            extraction,
            str(output),
            DxfExportOptions(include_images=False, text_mode="text"),
        )

    assert output.read_bytes() == prior
    assert raised.value.delivery.terminal_fallback_authorized is False
    assert hash_pdf.call_count == 0
    assert raster_fallback.call_count == 0
    assert not output.with_name(f"{output.stem}_assets").exists()


def _resolution(
    filename: Path,
    *,
    digest: str,
    asset_id: str,
) -> _ExactFontResolution:
    return _ExactFontResolution(
        source_name="BCS Deterministic Test",
        family="BCS Deterministic Test",
        style="Regular",
        filename=str(filename),
        exact=True,
        reason="stable positioned-font identity regression",
        resolution_source="embedded_pdf_font",
        asset_id=asset_id,
        asset_sha256=digest,
        source_sha256=digest,
    )


def _positioned_definition_names(
    resolution: _ExactFontResolution,
) -> tuple[str, ...]:
    reset_text_styles()
    doc = ezdxf.new("R2010")
    with patch("dxf_text_builder._resolve_item_font", return_value=resolution):
        result = build_text(
            _positioned_fraction("vertical"),
            doc.modelspace(),
            "TEXT",
            ImportConfig(text_mode="glyphs"),
            target_app="librecad",
            dxf_version="R2010",
            return_delivery_result=True,
        )
    assert result.verified is True
    final = next(attempt for attempt in result.attempts if attempt.outcome == "verified")
    names = tuple(final.evidence["glyph_definition_names"])
    assert names and all(name.startswith("BCS_GDEF_") for name in names)
    return names


def test_positioned_font_identity_and_definition_names_ignore_staging_path_when_hashed(
    tmp_path: Path,
    deterministic_exact_font: Path,
) -> None:
    font_bytes = deterministic_exact_font.read_bytes()
    first_path = tmp_path / "stage-a" / "asset-a.ttf"
    second_path = tmp_path / "stage-b" / "asset-b.ttf"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_bytes(font_bytes)
    second_path.write_bytes(font_bytes)
    digest = hashlib.sha256(font_bytes).hexdigest()
    first = _resolution(first_path, digest=digest, asset_id="staged-a")
    second = _resolution(second_path, digest=digest, asset_id="staged-b")

    assert _positioned_font_identity(first) == _positioned_font_identity(second)
    assert str(first_path).lower() not in repr(_positioned_font_identity(first)).lower()
    assert str(second_path).lower() not in repr(_positioned_font_identity(second)).lower()
    assert _positioned_definition_names(first) == _positioned_definition_names(second)


def test_positioned_font_identity_and_definition_names_distinguish_font_bytes(
    tmp_path: Path,
    deterministic_exact_font: Path,
) -> None:
    first_path = tmp_path / "original-font.ttf"
    second_path = tmp_path / "changed-font.ttf"
    first_path.write_bytes(deterministic_exact_font.read_bytes())
    second_path.write_bytes(deterministic_exact_font.read_bytes())
    changed_font = TTFont(second_path, recalcTimestamp=False)
    changed_font["head"].fontRevision += 0.125
    changed_font.save(second_path, reorderTables=False)
    changed_font.close()
    first_digest = hashlib.sha256(first_path.read_bytes()).hexdigest()
    second_digest = hashlib.sha256(second_path.read_bytes()).hexdigest()
    assert first_digest != second_digest
    first = _resolution(first_path, digest=first_digest, asset_id="original")
    second = _resolution(second_path, digest=second_digest, asset_id="changed")

    assert _positioned_font_identity(first) != _positioned_font_identity(second)
    assert _positioned_definition_names(first) != _positioned_definition_names(second)


@pytest.mark.parametrize(
    "mutation",
    ["color", "vertices", "order", "character_counts", "remove", "add", "type"],
)
def test_positioned_geometry_serialized_fingerprint_rejects_tampering(
    tmp_path: Path,
    mutation: str,
) -> None:
    item = _positioned_fraction("vertical", scale=2.0, rotation=19.0)
    reopened, result, trusted_anchors = _save_reopen(tmp_path, item, "geometry")
    delivery = copy.deepcopy(result.to_dict())
    modelspace = reopened.modelspace()
    entities = [reopened.entitydb.get(handle) for handle in delivery["entity_handles"]]
    assert all(entity is not None for entity in entities)

    if mutation == "color":
        entities[0].dxf.true_color = rgb2int((12, 34, 56))
    elif mutation == "vertices":
        point = entities[0].dxf.vtx0
        entities[0].dxf.vtx0 = (float(point.x) + 0.25, float(point.y), float(point.z))
    elif mutation == "order":
        delivery["entity_handles"].reverse()
        verified = next(
            attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
        )
        verified["entity_handles"].reverse()
    elif mutation == "character_counts":
        verified = next(
            attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
        )
        counts = verified["evidence"][
            "positioned_geometry_character_solid_counts"
        ]
        assert counts[0] > 1
        counts[0] -= 1
        counts[1] += 1
    elif mutation == "remove":
        modelspace.delete_entity(entities[0])
    elif mutation == "add":
        extra = modelspace.add_solid(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 1.0)],
            dxfattribs={"true_color": _TRUE_COLOR},
        )
        delivery["entity_handles"].append(str(extra.dxf.handle))
        verified = next(
            attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
        )
        verified["entity_handles"].append(str(extra.dxf.handle))
    else:
        extra = modelspace.add_line((0.0, 0.0), (1.0, 1.0))
        delivery["entity_handles"].append(str(extra.dxf.handle))
        verified = next(
            attempt for attempt in delivery["attempts"] if attempt["outcome"] == "verified"
        )
        verified["entity_handles"].append(str(extra.dxf.handle))

    with pytest.raises(RuntimeError):
        _verify_with_trusted_anchors(reopened, [delivery], trusted_anchors)


@pytest.mark.parametrize("visibility", [(1,), (0, 1)])
def test_solid_fill_verification_rejects_invisible_only_or_mixed_visibility(
    visibility: tuple[int, ...],
) -> None:
    doc = ezdxf.new("R2010")
    fills = [
        doc.modelspace().add_solid(
            [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 1.0)],
            dxfattribs={"invisible": invisible},
        )
        for invisible in visibility
    ]

    assert _solid_fill_verified(fills, is_r12=False) is False


def test_solid_only_bbox_fallback_rejects_mixed_visibility_definition() -> None:
    doc = ezdxf.new("R2010")
    definition = doc.blocks.new("MIXED_VISIBILITY_SOLIDS")
    for invisible, x in ((0, 0.0), (1, 2.0)):
        definition.add_solid(
            [(x, 0.0), (x + 1.0, 0.0), (x, 1.0), (x, 1.0)],
            dxfattribs={"invisible": invisible},
        )
    insert = doc.modelspace().add_blockref(definition.name, (0.0, 0.0))

    assert list(iter_glyph_outline_entities(insert)) == []


def test_non_fraction_text_delivery_behavior_remains_native_and_unpositioned() -> None:
    item = NormalizedText(
        id=91,
        text="W12X30",
        normalized="W12X30",
        insertion=(12.25, 24.5),
        bbox=(10.0, 20.0, 22.0, 28.0),
        font_size=2.0,
        rotation=0.0,
        font_name="BCS Deterministic Test",
        page_number=3,
        advance_width=7.5,
    )
    doc = ezdxf.new("R2010")

    result = build_text(
        item,
        doc.modelspace(),
        "TEXT",
        ImportConfig(text_mode="text"),
        target_app="generic",
        dxf_version="R2010",
        return_delivery_result=True,
    )

    assert result.verified is True
    assert result.final_representation == "text"
    assert [entity.dxftype() for entity in doc.modelspace()] == ["TEXT"]


def test_ordinary_mixed_glyph_definition_never_uses_solid_bbox_fallback() -> None:
    item = NormalizedText(
        id=92,
        text="W12X30",
        normalized="W12X30",
        insertion=(12.25, 24.5),
        bbox=(10.0, 20.0, 22.0, 28.0),
        font_size=2.0,
        rotation=0.0,
        font_name="BCS Deterministic Test",
        page_number=3,
        advance_width=7.5,
    )
    doc = ezdxf.new("R2010")

    result = build_text(
        item,
        doc.modelspace(),
        "TEXT",
        ImportConfig(text_mode="glyphs"),
        target_app="generic",
        dxf_version="R2010",
        return_delivery_result=True,
    )

    assert result.verified is True
    outer = next(iter(doc.modelspace()))
    outer_block = doc.blocks.get(outer.dxf.name)
    definitions = [doc.blocks.get(nested.dxf.name) for nested in outer_block]
    assert all(
        {entity.dxftype() for entity in definition}
        >= {"LWPOLYLINE", "SOLID"}
        for definition in definitions
    )
    bbox_entities = list(iter_glyph_outline_entities(outer))
    assert bbox_entities
    assert {entity.dxftype() for entity in bbox_entities} == {"LWPOLYLINE"}

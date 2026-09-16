from __future__ import annotations

from dataclasses import replace
import hashlib
import math

import pytest

from pdfcadcore.embedded_fonts import EmbeddedFontAsset, EmbeddedFontFailure
from pdfcadcore.primitive_extractor import _merge_stacked_fractions
from pdfcadcore.primitives import NormalizedText, TextCharLayout


def _point(
    local: tuple[float, float],
    *,
    scale: float,
    rotation: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    angle = math.radians(rotation)
    x = local[0] * scale
    y = local[1] * scale
    return (
        origin[0] + x * math.cos(angle) - y * math.sin(angle),
        origin[1] + x * math.sin(angle) + y * math.cos(angle),
    )


def _char_layout(
    text: str,
    glyph_id: int | None,
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
        _point(value, scale=scale, rotation=rotation, origin=origin)
        for value in local_quad
    )
    target_origin = _point(
        local_origin,
        scale=scale,
        rotation=rotation,
        origin=origin,
    )
    source_quad = tuple((x + 300.0, 700.0 - y) for x, y in target_quad)
    source_origin = (target_origin[0] + 300.0, 700.0 - target_origin[1])
    source_x = [value[0] for value in source_quad]
    source_y = [value[1] for value in source_quad]
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


def _item(
    item_id: int,
    text: str,
    local_origins: tuple[tuple[float, float], ...],
    *,
    scale: float = 1.0,
    rotation: float = 0.0,
    origin: tuple[float, float] = (100.0, 200.0),
    glyph_ids: tuple[int | None, ...] | None = None,
    char_texts: tuple[str, ...] | None = None,
    font_size: float | None = None,
) -> NormalizedText:
    chars = char_texts if char_texts is not None else tuple(text)
    ids = glyph_ids if glyph_ids is not None else tuple(range(item_id * 10, item_id * 10 + len(chars)))
    assert len(chars) == len(local_origins) == len(ids)
    layout = tuple(
        _char_layout(
            char,
            glyph_id,
            local_origin,
            scale=scale,
            rotation=rotation,
            origin=origin,
        )
        for char, glyph_id, local_origin in zip(chars, ids, local_origins, strict=True)
    )
    target_points = [point for char in layout for point in char.target_quad]
    source_points = [point for char in layout for point in char.source_quad_pdf]
    target_x = [point[0] for point in target_points]
    target_y = [point[1] for point in target_points]
    source_x = [point[0] for point in source_points]
    source_y = [point[1] for point in source_points]
    insertion = _point(
        local_origins[0],
        scale=scale,
        rotation=rotation,
        origin=origin,
    )
    bbox = (min(target_x), min(target_y), max(target_x), max(target_y))
    source_bbox = (min(source_x), min(source_y), max(source_x), max(source_y))
    return NormalizedText(
        id=item_id,
        text=text,
        normalized=text,
        insertion=insertion,
        bbox=bbox,
        font_size=float(scale if font_size is None else font_size),
        rotation=rotation,
        font_name="EmbeddedFraction",
        color=(0.1, 0.2, 0.3),
        page_number=1,
        generic_tags=["dimension"],
        domain_tags=[{"source": "synthetic-fraction"}],
        source_bbox_pdf=source_bbox,
        source_quad_pdf=(
            (source_bbox[0], source_bbox[1]),
            (source_bbox[2], source_bbox[1]),
            (source_bbox[2], source_bbox[3]),
            (source_bbox[0], source_bbox[3]),
        ),
        target_quad_model=(
            (bbox[0], bbox[3]),
            (bbox[2], bbox[3]),
            (bbox[2], bbox[1]),
            (bbox[0], bbox[1]),
        ),
        advance_width=max(target_x) - min(target_x),
        glyph_height=max(target_y) - min(target_y),
        baseline_descent=0.2 * scale,
        source_char_layout=layout,
        requires_individual_positioning=True,
    )


def _separate_fraction(
    encoding: str,
    *,
    scale: float = 1.0,
    rotation: float = 0.0,
    numerator: str = "13",
    denominator: str = "16",
) -> tuple[NormalizedText, NormalizedText, NormalizedText]:
    if encoding == "vertical":
        numerator_origins = tuple((index * 0.55 - 0.275, 1.2) for index in range(len(numerator)))
        denominator_origins = tuple((index * 0.55 - 0.275, -1.2) for index in range(len(denominator)))
    elif encoding == "horizontal":
        numerator_origins = tuple(
            (-1.2 - 0.55 * (len(numerator) - index), 0.0)
            for index in range(len(numerator))
        )
        denominator_origins = tuple((1.2 + index * 0.55, 0.0) for index in range(len(denominator)))
    else:  # pragma: no cover - test helper guard
        raise ValueError(encoding)
    numerator_item = _item(
        1,
        numerator,
        numerator_origins,
        scale=scale,
        rotation=rotation,
    )
    slash_item = _item(2, "/", ((0.0, 0.0),), scale=scale, rotation=rotation)
    denominator_item = _item(
        3,
        denominator,
        denominator_origins,
        scale=scale,
        rotation=rotation,
    )
    return numerator_item, slash_item, denominator_item


def _concatenated_fraction(
    *,
    scale: float = 1.0,
    rotation: float = 0.0,
    numerator: str = "13",
    denominator: str = "16",
) -> tuple[NormalizedText, NormalizedText]:
    numerator_origins = tuple((index * 0.55 - 0.275, 1.2) for index in range(len(numerator)))
    denominator_origins = tuple((index * 0.55 - 0.275, -1.2) for index in range(len(denominator)))
    digits = _item(
        1,
        numerator + denominator,
        numerator_origins + denominator_origins,
        scale=scale,
        rotation=rotation,
    )
    slash = _item(2, "/", ((0.0, 0.0),), scale=scale, rotation=rotation)
    return digits, slash


def _assert_refused(items: list[NormalizedText]) -> None:
    snapshots = [repr(vars(item)) for item in items]

    result = _merge_stacked_fractions(items)

    assert result is items
    assert len(result) == len(items)
    assert all(actual is original for actual, original in zip(result, items, strict=True))
    assert [repr(vars(item)) for item in result] == snapshots


def _font_asset(identity: str) -> EmbeddedFontAsset:
    source_bytes = f"source-{identity}".encode("ascii")
    usable_bytes = f"usable-{identity}".encode("ascii")
    return EmbeddedFontAsset(
        page_number=1,
        span_font_name="EmbeddedFraction",
        base_font_name="EmbeddedFraction",
        source_xref=71,
        resource_name="/F7",
        source_font_type="Type0",
        source_encoding="Identity-H",
        source_format="otf",
        source_origin="embedded_pdf_font",
        source_bytes=source_bytes,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        usable_format="otf",
        usable_bytes=usable_bytes,
        usable_sha256=hashlib.sha256(usable_bytes).hexdigest(),
        asset_id=f"fraction-font-{identity}",
        unicode_map_installed=True,
        units_per_em=1000,
        ascender=800,
        descender=-200,
        glyph_advances=(500, 500, 500),
    )


def _font_failure(reason: str) -> EmbeddedFontFailure:
    return EmbeddedFontFailure(
        page_number=1,
        span_font_name="EmbeddedFraction",
        reason=reason,
        source_xref=71,
        error_type="ExactFontSourceImpossible",
        detail=f"proof-{reason}",
        proof_category="source_impossible",
    )


def _fraction_items(encoding: str) -> list[NormalizedText]:
    if encoding == "separate":
        numerator, slash, denominator = _separate_fraction("vertical")
        return [denominator, slash, numerator]
    digits, slash = _concatenated_fraction()
    return [slash, digits]


@pytest.mark.parametrize("encoding", ["separate", "concatenated"])
@pytest.mark.parametrize(
    "mixed_binding",
    ["font_name", "font_asset", "font_failure", "color"],
)
def test_mixed_item_rendering_binding_refuses_without_touching_inputs(
    encoding: str,
    mixed_binding: str,
) -> None:
    items = _fraction_items(encoding)
    changed = items[-1]
    if mixed_binding == "font_name":
        changed.font_name = "DifferentFractionFont"
    elif mixed_binding == "font_asset":
        for item in items:
            item.font_asset = replace(_font_asset("shared"))
        changed.font_asset = _font_asset("different")
    elif mixed_binding == "font_failure":
        for item in items:
            item.font_failure = replace(_font_failure("shared"))
        changed.font_failure = _font_failure("different")
    elif mixed_binding == "color":
        changed.color = (0.9, 0.1, 0.2)

    _assert_refused(items)


@pytest.mark.parametrize("encoding", ["separate", "concatenated"])
@pytest.mark.parametrize("evidence", ["font_asset", "font_failure"])
def test_distinct_objects_with_same_rendering_evidence_remain_mergeable(
    encoding: str,
    evidence: str,
) -> None:
    items = _fraction_items(encoding)
    if evidence == "font_asset":
        for item in items:
            item.font_asset = replace(_font_asset("shared"))
    else:
        for item in items:
            item.font_failure = replace(_font_failure("shared"))

    result = _merge_stacked_fractions(items)

    assert len(result) == 1
    assert result[0].text == "13/16"
    assert "".join(char.text for char in result[0].source_char_layout) == "13/16"


@pytest.mark.parametrize(
    "fault",
    [
        "zero_layout",
        "partial_layout",
        "unexpected_layout_object",
        "layout_text_mismatch",
        "missing_slash_layout",
        "two_layout_slashes",
        "reused_character_occurrence",
    ],
)
def test_incomplete_or_non_bijective_layout_refuses_without_touching_inputs(fault: str) -> None:
    numerator, slash, denominator = _separate_fraction("vertical")
    items = [numerator, slash, denominator]
    if fault == "zero_layout":
        for item in items:
            item.source_char_layout = ()
            item.requires_individual_positioning = False
    elif fault == "partial_layout":
        numerator.source_char_layout = numerator.source_char_layout[:1]
    elif fault == "unexpected_layout_object":
        numerator.source_char_layout = (object(),)  # type: ignore[assignment]
    elif fault == "layout_text_mismatch":
        denominator.source_char_layout = (
            denominator.source_char_layout[0],
            replace(denominator.source_char_layout[1], text="8"),
        )
    elif fault == "missing_slash_layout":
        slash.source_char_layout = ()
    elif fault == "two_layout_slashes":
        slash.source_char_layout = slash.source_char_layout * 2
    elif fault == "reused_character_occurrence":
        numerator.source_char_layout = (
            numerator.source_char_layout[0],
            numerator.source_char_layout[0],
        )

    _assert_refused(items)


@pytest.mark.parametrize(
    ("encoding", "scale", "rotation"),
    [
        ("vertical", 1.0, 0.0),
        ("vertical", 10.0, 0.0),
        ("vertical", 1.0, -90.0),
        ("vertical", 3.25, 37.0),
        ("horizontal", 1.0, 0.0),
        ("horizontal", 10.0, 0.0),
        ("horizontal", 1.0, -90.0),
        ("horizontal", 2.5, 123.0),
    ],
)
def test_separate_fraction_recognition_is_font_relative_and_rotation_invariant(
    encoding: str,
    scale: float,
    rotation: float,
) -> None:
    numerator, slash, denominator = _separate_fraction(
        encoding,
        scale=scale,
        rotation=rotation,
    )

    result = _merge_stacked_fractions([denominator, slash, numerator])

    assert len(result) == 1
    merged = result[0]
    assert merged.text == "13/16"
    assert tuple(char.text for char in merged.source_char_layout) == ("1", "3", "/", "1", "6")
    assert merged.source_char_layout == (
        numerator.source_char_layout + slash.source_char_layout + denominator.source_char_layout
    )
    assert merged.requires_individual_positioning is True


@pytest.mark.parametrize(("scale", "rotation"), [(1.0, 0.0), (10.0, -90.0), (2.75, 41.0)])
def test_concatenated_multi_character_fraction_preserves_semantic_layout(
    scale: float,
    rotation: float,
) -> None:
    digits, slash = _concatenated_fraction(scale=scale, rotation=rotation)

    result = _merge_stacked_fractions([slash, digits])

    assert len(result) == 1
    assert result[0].text == "13/16"
    assert tuple(char.text for char in result[0].source_char_layout) == ("1", "3", "/", "1", "6")
    assert result[0].source_char_layout == (
        digits.source_char_layout[:2]
        + slash.source_char_layout
        + digits.source_char_layout[2:]
    )


def test_rotation_incompatible_slash_refuses_false_merge() -> None:
    numerator, slash, denominator = _separate_fraction("vertical")
    slash.rotation = 90.0
    items = [numerator, slash, denominator]

    _assert_refused(items)


def test_non_equivalent_duplicate_concatenated_candidates_refuse() -> None:
    digits, slash = _concatenated_fraction()
    conflicting_layout = (
        replace(digits.source_char_layout[0], glyph_id=9999),
        *digits.source_char_layout[1:],
    )
    conflicting = replace(digits, id=4, source_char_layout=conflicting_layout)
    items = [digits, conflicting, slash]

    _assert_refused(items)


def test_equivalent_duplicate_concatenated_overlays_are_consumed_once() -> None:
    digits, slash = _concatenated_fraction()
    equivalent = replace(
        digits,
        id=4,
        source_char_layout=tuple(replace(char) for char in digits.source_char_layout),
    )

    result = _merge_stacked_fractions([digits, equivalent, slash])

    assert len(result) == 1
    assert result[0].text == "13/16"
    assert len(result[0].source_char_layout) == 5
    assert tuple(char.glyph_id for char in result[0].source_char_layout) == (10, 11, 20, 12, 13)


def test_repeated_glyph_program_id_on_distinct_characters_is_valid() -> None:
    digits, slash = _concatenated_fraction(numerator="11")
    digits.source_char_layout = (
        replace(digits.source_char_layout[0], glyph_id=111),
        replace(digits.source_char_layout[1], glyph_id=111),
        *digits.source_char_layout[2:],
    )

    result = _merge_stacked_fractions([digits, slash])

    assert len(result) == 1
    assert result[0].text == "11/16"
    assert result[0].source_char_layout[0] is not result[0].source_char_layout[1]
    assert tuple(char.glyph_id for char in result[0].source_char_layout[:2]) == (111, 111)


def test_multiple_non_equivalent_valid_pairs_are_ambiguous_and_refuse() -> None:
    numerator, slash, denominator = _separate_fraction("vertical")
    alternative = _item(4, "32", ((-0.275, -1.1), (0.275, -1.1)))
    items = [numerator, slash, denominator, alternative]

    _assert_refused(items)


def test_two_non_equivalent_slashes_competing_for_same_digits_refuse() -> None:
    numerator, slash, denominator = _separate_fraction("vertical")
    other_slash = replace(
        slash,
        id=5,
        color=(0.9, 0.1, 0.1),
        source_char_layout=(replace(slash.source_char_layout[0], glyph_id=505),),
    )
    items = [numerator, slash, other_slash, denominator]

    _assert_refused(items)


def test_refusal_preserves_rich_objects_in_original_source_order() -> None:
    numerator, slash, denominator = _separate_fraction("vertical")
    slash.rotation = 180.0
    numerator.positioned_character = True
    numerator.source_glyph_id = 313
    numerator.generic_tags.append("keep-me")
    numerator.domain_tags.append({"nested": [1, 2, 3]})
    items = [denominator, numerator, slash]

    _assert_refused(items)


def test_missing_slash_item_preserves_inputs() -> None:
    numerator, _slash, denominator = _separate_fraction("vertical")
    items = [denominator, numerator]

    _assert_refused(items)


def test_merged_item_keeps_only_observed_anchor_and_exact_character_truth() -> None:
    numerator, slash, denominator = _separate_fraction("vertical", scale=2.0, rotation=28.0)
    slash.font_size = 2.75
    for item in (numerator, slash, denominator):
        item.font_name = "ObservedSlashFont"
        item.color = (0.7, 0.6, 0.5)
        item.source_quad_pdf = None
        item.target_quad_model = None
        item.advance_width = 0.0
        item.glyph_height = 0.0
        item.baseline_descent = 0.0

    result = _merge_stacked_fractions([numerator, slash, denominator])

    assert len(result) == 1
    merged = result[0]
    assert merged.insertion == slash.insertion
    assert merged.font_size == 2.75
    assert merged.rotation == 28.0
    assert merged.font_name == "ObservedSlashFont"
    assert merged.color == (0.7, 0.6, 0.5)
    assert merged.source_quad_pdf is None
    assert merged.target_quad_model is None
    assert merged.advance_width == 0.0
    assert merged.glyph_height == 0.0
    assert merged.baseline_descent == 0.0
    assert merged.requires_individual_positioning is True
    assert tuple(char.text for char in merged.source_char_layout) == ("1", "3", "/", "1", "6")


def test_nearby_non_equivalent_semantic_fraction_is_not_deduplicated() -> None:
    numerator, slash, denominator = _separate_fraction("vertical")
    existing_layout = (
        numerator.source_char_layout
        + slash.source_char_layout
        + denominator.source_char_layout
    )
    existing = replace(
        slash,
        id=99,
        text="13/16",
        normalized="13/16",
        color=(1.0, 0.0, 0.0),
        bbox=(99.0, 198.0, 102.0, 202.0),
        source_char_layout=existing_layout,
    )

    result = _merge_stacked_fractions([existing, numerator, slash, denominator])

    assert len(result) == 2
    assert result[0] is existing
    assert [item.text for item in result] == ["13/16", "13/16"]

#!/usr/bin/env python3
"""Regression: a both-sides weld symbol is TWO stacked fractions, not one.

Geometry is the pdfcadcore extraction of "1011 (1 OF 2) - Rev 0.pdf" page 1,
weld symbol at PDF pt (953.9, 937.8): '316' [949.5,927.5,966.8,941.5] + '/'
above the reference line and '316' [949.5,940.5,966.8,954.6] + '/' below it
(14 such stacked-over-stacked pairs on that sheet, 96 across the local
corpus).  Before this fix ``_merge_stacked_fractions`` Pattern A let the first
slash swallow both '316' spans (nearest_distance + _FRAC_Y_SPREAD_MM window)
and ``_dedupe_fraction_overlays`` then deleted the second, now bare, slash
(5.0/5.5 mm centre tolerance), so one '3/16' survived per symbol.
"""
from __future__ import annotations

from dataclasses import replace
import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

MOD_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MOD_ROOT))

import pdfcadcore.primitive_extractor as primitive_extractor  # noqa: E402
from pdfcadcore.primitive_extractor import (  # noqa: E402
    _extract_text,
    _merge_stacked_fractions,
)
from pdfcadcore.primitives import NormalizedText, TextCharLayout  # noqa: E402


def _world_point(
    point: tuple[float, float],
    *,
    anchor: tuple[float, float],
    rotation: float,
) -> tuple[float, float]:
    angle = math.radians(rotation)
    return (
        anchor[0] + point[0] * math.cos(angle) - point[1] * math.sin(angle),
        anchor[1] + point[0] * math.sin(angle) + point[1] * math.cos(angle),
    )


def _producer_shaped_layout(
    text: str,
    *,
    slash_anchor: tuple[float, float],
    rotation: float,
) -> tuple[TextCharLayout, ...]:
    """Complete finite rawdict-style character evidence for one source span."""
    if text == "316":
        local_origins = ((-0.3, 1.05), (-0.65, -1.05), (0.15, -1.05))
    elif text == "/":
        local_origins = ((0.0, 0.0),)
    else:  # pragma: no cover - fixture guard
        raise ValueError(text)

    result = []
    for char, local_origin in zip(text, local_origins, strict=True):
        local_quad = (
            (local_origin[0] - 0.25, local_origin[1] + 0.4),
            (local_origin[0] + 0.25, local_origin[1] + 0.4),
            (local_origin[0] + 0.25, local_origin[1] - 0.4),
            (local_origin[0] - 0.25, local_origin[1] - 0.4),
        )
        target_quad = tuple(
            _world_point(point, anchor=slash_anchor, rotation=rotation)
            for point in local_quad
        )
        target_origin = _world_point(
            local_origin,
            anchor=slash_anchor,
            rotation=rotation,
        )
        xs = [point[0] for point in target_quad]
        ys = [point[1] for point in target_quad]
        result.append(
            TextCharLayout(
                text=char,
                glyph_id=ord(char),
                source_origin_pdf=target_origin,
                source_bbox_pdf=(min(xs), min(ys), max(xs), max(ys)),
                source_quad_pdf=target_quad,
                target_origin=target_origin,
                target_quad=target_quad,
                advance_width=0.5,
                glyph_height=0.8,
            )
        )
    return tuple(result)


def _clone_observed_item(item: NormalizedText, *, item_id: int) -> NormalizedText:
    return replace(
        item,
        id=item_id,
        source_char_layout=tuple(replace(char) for char in item.source_char_layout),
    )


def _both_sides_1011_items(rotate90: bool = False) -> list[NormalizedText]:
    # (text, insertion, bbox, font_size, owning slash) -- model mm, 1011 p1.
    # The character layout mirrors what the real rawdict extraction path stores.
    raw = [
        (
            "316",
            (334.95, 279.05),
            (334.95, 276.86, 341.06, 281.81),
            3.55,
            (336.51, 278.16),
        ),
        (
            "/",
            (336.51, 278.16),
            (336.51, 277.22, 337.69, 281.45),
            4.23,
            (336.51, 278.16),
        ),
        (
            "316",
            (334.95, 274.44),
            (334.95, 272.25, 341.06, 277.20),
            3.55,
            (336.51, 273.51),
        ),
        (
            "/",
            (336.51, 273.51),
            (336.51, 272.56, 337.69, 276.79),
            4.23,
            (336.51, 273.51),
        ),
    ]
    items = []
    for idx, (text, ins, box, size, slash_anchor) in enumerate(raw, start=1):
        rot = 0.0
        if rotate90:  # (x, y) -> (-y, x): a vertical dimension string
            ins = (-ins[1], ins[0])
            box = (-box[3], box[0], -box[1], box[2])
            slash_anchor = (-slash_anchor[1], slash_anchor[0])
            rot = 90.0
        items.append(
            NormalizedText(
                id=idx, text=text, normalized=text, insertion=ins,
                bbox=box, font_size=size, rotation=rot, page_number=1,
                source_char_layout=_producer_shaped_layout(
                    text,
                    slash_anchor=slash_anchor,
                    rotation=rot,
                ),
                requires_individual_positioning=True,
            )
        )
    return items


def _assert_identity_and_order_preserved(items: list[NormalizedText]) -> None:
    snapshots = [repr(vars(item)) for item in items]

    result = _merge_stacked_fractions(items)

    assert result is items
    assert len(result) == len(items)
    assert all(actual is expected for actual, expected in zip(result, items, strict=True))
    assert [repr(vars(item)) for item in result] == snapshots


@pytest.mark.parametrize("fault", ["layout_free", "partial_layout", "ambiguous"])
def test_unproven_1011_weld_fraction_refuses_without_reordering_or_rewriting(
    fault: str,
) -> None:
    items = _both_sides_1011_items()[:2]
    if fault == "layout_free":
        for item in items:
            item.source_char_layout = ()
            item.requires_individual_positioning = False
    elif fault == "partial_layout":
        items[0].source_char_layout = items[0].source_char_layout[:-1]
    else:
        competing = _clone_observed_item(items[0], item_id=9)
        competing.text = "516"
        competing.normalized = "516"
        competing.source_char_layout = tuple(
            replace(char, text=replacement)
            for char, replacement in zip(
                competing.source_char_layout,
                competing.text,
                strict=True,
            )
        )
        items.insert(1, competing)

    _assert_identity_and_order_preserved(items)


def test_rawdict_extraction_builds_complete_layout_before_fraction_merger() -> None:
    class _Page:
        requested_kinds: list[str] = []

        @classmethod
        def get_text(cls, kind: str):
            cls.requested_kinds.append(kind)

            def span(text: str, origins: tuple[tuple[float, float], ...]) -> dict:
                chars = []
                for char, (x, y) in zip(text, origins, strict=True):
                    quad = (
                        (x - 0.25, y + 0.4),
                        (x + 0.25, y + 0.4),
                        (x + 0.25, y - 0.4),
                        (x - 0.25, y - 0.4),
                    )
                    chars.append(
                        {
                            "c": char,
                            "origin": (x, y),
                            "bbox": (x - 0.25, y - 0.4, x + 0.25, y + 0.4),
                            "quad": quad,
                        }
                    )
                return {
                    "chars": chars,
                    "font": "RawdictProducerFont",
                    "size": 10.0,
                    "origin": origins[0],
                    "bbox": (
                        min(x for x, _y in origins) - 0.25,
                        min(y for _x, y in origins) - 0.4,
                        max(x for x, _y in origins) + 0.25,
                        max(y for _x, y in origins) + 0.4,
                    ),
                }

            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "dir": (1.0, 0.0),
                                "spans": [
                                    span("316", ((9.7, 11.05), (9.35, 8.95), (10.15, 8.95)))
                                ],
                            },
                            {
                                "dir": (1.0, 0.0),
                                "spans": [span("/", ((10.0, 10.0),))],
                            },
                        ],
                    }
                ]
            }

        @staticmethod
        def get_texttrace():
            return []

    observed: list[NormalizedText] = []

    def observe_before_merge(items: list[NormalizedText]) -> list[NormalizedText]:
        observed.extend(items)
        return items

    with patch.object(
        primitive_extractor,
        "_merge_stacked_fractions",
        side_effect=observe_before_merge,
    ):
        extracted = _extract_text(
            _Page(),
            100.0,
            1,
            False,
            1.0,
            to_model=lambda x, y: (float(x), float(y)),
        )

    assert _Page.requested_kinds == ["rawdict"]
    assert extracted == observed
    assert [item.text for item in observed] == ["316", "/"]
    for item in observed:
        layout = item.source_char_layout
        assert isinstance(layout, tuple)
        assert len(layout) == len(item.text)
        assert len({id(char) for char in layout}) == len(layout)
        assert all(isinstance(char, TextCharLayout) for char in layout)
        assert "".join(char.text for char in layout) == item.text
        assert item.requires_individual_positioning is True
        for char in layout:
            scalars = (
                *char.source_origin_pdf,
                *char.source_bbox_pdf,
                *(value for point in char.source_quad_pdf for value in point),
                *char.target_origin,
                *(value for point in char.target_quad for value in point),
                char.advance_width,
                char.glyph_height,
            )
            assert all(math.isfinite(float(value)) for value in scalars)
            assert char.advance_width > 0.0
            assert char.glyph_height > 0.0


def test_both_sides_weld_symbol_keeps_both_stacked_fractions() -> None:
    merged = _merge_stacked_fractions(_both_sides_1011_items())
    assert [item.text for item in merged] == ["3/16", "3/16"]
    top, bottom = sorted(merged, key=lambda it: -it.insertion[1])
    # Each fraction sits at its own slash; its bbox does not span the other half.
    assert top.insertion == (336.51, 278.16)
    assert bottom.insertion == (336.51, 273.51)
    assert top.bbox[1] >= 276.8 and bottom.bbox[3] <= 277.3
    # Both retain the same observed slash anchor size.
    assert abs(top.font_size - bottom.font_size) < 1e-6


def test_both_sides_weld_symbol_rotated_90_keeps_both() -> None:
    merged = _merge_stacked_fractions(_both_sides_1011_items(rotate90=True))
    assert [item.text for item in merged] == ["3/16", "3/16"]


def test_coincident_overlay_stack_still_merges_once() -> None:
    # A printer that draws the SAME stack twice at the SAME place is an overlay;
    # that (and only that) still collapses to one fraction.
    a = _both_sides_1011_items()[:2]
    b = [
        _clone_observed_item(a[0], item_id=3),
        _clone_observed_item(a[1], item_id=4),
    ]
    assert [item.text for item in _merge_stacked_fractions(a + b)] == ["3/16"]


def test_leftover_slash_inside_its_own_fraction_is_dropped_but_not_a_neighbour() -> None:
    top = _both_sides_1011_items()[:2]
    dup_slash = _clone_observed_item(top[1], item_id=9)
    far_slash = _clone_observed_item(_both_sides_1011_items()[3], item_id=10)
    merged = _merge_stacked_fractions(top + [dup_slash, far_slash])
    assert [item.text for item in merged] == ["3/16", "/"]

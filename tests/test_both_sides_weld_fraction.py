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

import sys
from pathlib import Path

MOD_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MOD_ROOT))

from pdfcadcore.primitive_extractor import _merge_stacked_fractions  # noqa: E402
from pdfcadcore.primitives import NormalizedText  # noqa: E402


def _both_sides_1011_items(rotate90: bool = False) -> list[NormalizedText]:
    # (text, insertion, bbox, font_size) -- model mm, 1011 p1 as extracted
    raw = [
        ("316", (334.95, 279.05), (334.95, 276.86, 341.06, 281.81), 3.55),
        ("/", (336.51, 278.16), (336.51, 277.22, 337.69, 281.45), 4.23),
        ("316", (334.95, 274.44), (334.95, 272.25, 341.06, 277.20), 3.55),
        ("/", (336.51, 273.51), (336.51, 272.56, 337.69, 276.79), 4.23),
    ]
    items = []
    for idx, (text, ins, box, size) in enumerate(raw, start=1):
        rot = 0.0
        if rotate90:  # (x, y) -> (-y, x): a vertical dimension string
            ins = (-ins[1], ins[0])
            box = (-box[3], box[0], -box[1], box[2])
            rot = 90.0
        items.append(
            NormalizedText(
                id=idx, text=text, normalized=text, insertion=ins,
                bbox=box, font_size=size, rotation=rot, page_number=1,
            )
        )
    return items


def test_both_sides_weld_symbol_keeps_both_stacked_fractions() -> None:
    merged = _merge_stacked_fractions(_both_sides_1011_items())
    assert [item.text for item in merged] == ["3/16", "3/16"]
    top, bottom = sorted(merged, key=lambda it: -it.insertion[1])
    # Each fraction sits at its own slash; its bbox does not span the other half.
    assert top.insertion == (336.51, 278.16)
    assert bottom.insertion == (336.51, 273.51)
    assert top.bbox[1] >= 276.8 and bottom.bbox[3] <= 277.3
    # Both carry the same reduced stacked footprint (owner item: 0.6x scale).
    assert abs(top.font_size - bottom.font_size) < 1e-6


def test_both_sides_weld_symbol_rotated_90_keeps_both() -> None:
    merged = _merge_stacked_fractions(_both_sides_1011_items(rotate90=True))
    assert [item.text for item in merged] == ["3/16", "3/16"]


def test_coincident_overlay_stack_still_merges_once() -> None:
    # A printer that draws the SAME stack twice at the SAME place is an overlay;
    # that (and only that) still collapses to one fraction.
    a = _both_sides_1011_items()[:2]
    b = [
        NormalizedText(
            id=3, text="316", normalized="316", insertion=(334.98, 279.07),
            bbox=(334.98, 276.88, 341.09, 281.83), font_size=3.55, page_number=1,
        ),
        NormalizedText(
            id=4, text="/", normalized="/", insertion=(336.53, 278.18),
            bbox=(336.53, 277.24, 337.71, 281.47), font_size=4.23, page_number=1,
        ),
    ]
    assert [item.text for item in _merge_stacked_fractions(a + b)] == ["3/16"]


def test_leftover_slash_inside_its_own_fraction_is_dropped_but_not_a_neighbour() -> None:
    top = _both_sides_1011_items()[:2]
    dup_slash = NormalizedText(
        id=9, text="/", normalized="/", insertion=(336.53, 278.18),
        bbox=(336.53, 277.24, 337.71, 281.47), font_size=4.23, page_number=1,
    )
    far_slash = NormalizedText(
        id=10, text="/", normalized="/", insertion=(336.51, 273.51),
        bbox=(336.51, 272.56, 337.69, 276.79), font_size=4.23, page_number=1,
    )
    merged = _merge_stacked_fractions(top + [dup_slash, far_slash])
    assert [item.text for item in merged] == ["3/16", "/"]

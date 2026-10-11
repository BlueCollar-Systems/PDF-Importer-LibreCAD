"""The one rule for PDF ink that LibreCAD must draw in its foreground colour.

LibreCAD swaps a pen to the foreground colour only when the pen is exactly
black (or equal to the background).  Its stock drawing background is black, so
"rich black" ink -- Distiller writes 35/31/32, other producers write other
dark neutral greys -- is drawn as that colour and is close to invisible.

Dark, neutral ink is therefore delivered exactly as a source colour of exact
black is: same colour value, same layer name.  A dark ink that carries a hue
(for example the dark blue 1F3863) keeps its colour.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

# Every channel at or below this 8-bit value ...
NEAR_BLACK_MAX_CHANNEL = 64
# ... and the channels no further apart than this: dark and neutral.
NEAR_BLACK_MAX_SPREAD = 16

INK_RULE_NEAR_BLACK = "near_black_neutral_delivered_as_black"

_BLACK = (0.0, 0.0, 0.0)


def rule_identity() -> dict:
    """What decides the delivered colour; part of a resume session's identity."""

    return {
        "rule": INK_RULE_NEAR_BLACK,
        "max_channel": NEAR_BLACK_MAX_CHANNEL,
        "max_spread": NEAR_BLACK_MAX_SPREAD,
    }


def rgb8(rgb: Sequence[float]) -> Tuple[int, int, int]:
    """Unit-interval RGB as clamped 8-bit channels (the exporter's rounding)."""

    r, g, b = (int(max(0, min(255, round(float(c) * 255)))) for c in rgb[:3])
    return r, g, b


def is_near_black_neutral(r: int, g: int, b: int) -> bool:
    """True for dark, neutral 8-bit ink; exact black included."""

    return (
        max(r, g, b) <= NEAR_BLACK_MAX_CHANNEL
        and max(r, g, b) - min(r, g, b) <= NEAR_BLACK_MAX_SPREAD
    )


def delivered_rgb8(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """The 8-bit colour an entity is written with for this 8-bit source ink."""

    if is_near_black_neutral(r, g, b):
        return 0, 0, 0
    return r, g, b


def is_remapped_near_black(rgb: Optional[Sequence[float]]) -> bool:
    """True when ``delivered_ink`` changes this unit-interval source colour."""

    if rgb is None:
        return False
    channels = rgb8(rgb)
    return channels != (0, 0, 0) and is_near_black_neutral(*channels)


def delivered_ink(rgb: Optional[Sequence[float]]):
    """The unit-interval colour to write for a unit-interval source colour.

    Near-black neutral ink becomes exact black; every other colour (and
    ``None``) is returned as the same object, so nothing else changes.
    """

    if is_remapped_near_black(rgb):
        return _BLACK
    return rgb

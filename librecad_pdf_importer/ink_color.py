"""Keep adaptive foreground ink separate from fixed source fill paint.

LibreCAD swaps a pen to the foreground colour only when the pen is exactly
black (or equal to the background).  Its stock drawing background is black, so
"rich black" ink -- Distiller writes 35/31/32, other producers write other
dark neutral greys -- is drawn as that colour and is close to invisible.

Ordinary dark-neutral lines and text use that foreground behavior. Filled
regions retain their source RGB so a dark panel does not become white and
erase white lettering. Exact black/white paint uses a reported one-channel-step
host approximation to avoid LibreCAD's model and print inversion.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

# Every channel at or below this 8-bit value ...
NEAR_BLACK_MAX_CHANNEL = 64
# ... and the channels no further apart than this: dark and neutral.
NEAR_BLACK_MAX_SPREAD = 16

INK_RULE_NEAR_BLACK = "near_black_neutral_delivered_as_black"
PAINT_RULE_FIXED_BLACK_WHITE = "source_paint_noninverting_black_white"

_BLACK = (0.0, 0.0, 0.0)


def rule_identity() -> dict:
    """What decides the delivered colour; part of a resume session's identity."""

    return {
        "rule": INK_RULE_NEAR_BLACK,
        "max_channel": NEAR_BLACK_MAX_CHANNEL,
        "max_spread": NEAR_BLACK_MAX_SPREAD,
        "fill_rule": "preserve_source_srgb8",
        "paint_encoding_rule": PAINT_RULE_FIXED_BLACK_WHITE,
        "fixed_black_rgb": [1, 1, 1],
        "fixed_white_rgb": [254, 254, 254],
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


def source_paint_rgb8(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """Source fill paint, avoiding LibreCAD's exact black/white inversion.

    Dark panels are paint, not adaptive foreground pens. Preserve every other
    source sRGB8 value; exact black/white need a one-channel-step approximation
    so the host does not swap them with its drawing or printing foreground.
    """
    if (r, g, b) == (0, 0, 0):
        return 1, 1, 1
    if (r, g, b) == (255, 255, 255):
        return 254, 254, 254
    return r, g, b


def text_ink_rgb8(r: int, g: int, b: int) -> Tuple[int, int, int]:
    """Keep ordinary dark text adaptive; white text remains light paint."""
    if (r, g, b) == (255, 255, 255):
        return 254, 254, 254
    return delivered_rgb8(r, g, b)


def is_remapped_near_black(rgb: Optional[Sequence[float]]) -> bool:
    """True when ``delivered_ink`` changes this unit-interval source colour."""

    if rgb is None:
        return False
    channels = rgb8(rgb)
    return channels != (0, 0, 0) and is_near_black_neutral(*channels)


def delivered_ink(rgb: Optional[Sequence[float]]):
    """The unit-interval colour to write for a unit-interval source colour.

    Near-black neutral ink becomes adaptive black; exact-white ink uses the
    non-inverting host approximation. Other colours and ``None`` are unchanged.
    """

    if rgb is not None and rgb8(rgb) == (255, 255, 255):
        return (254 / 255.0,) * 3
    if is_remapped_near_black(rgb):
        return _BLACK
    return rgb

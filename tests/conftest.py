"""Portable, deterministic fixtures shared by the LibreCAD test suite."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import pytest


DETERMINISTIC_FONT_NAME = "BCS Deterministic Test"


def _draw_box(*, top: int, right: int = 550, notch: int = 0) -> object:
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((right, 0))
    pen.lineTo((right, top))
    pen.lineTo((50 + notch, top))
    if notch:
        pen.lineTo((50, top - notch))
    else:
        pen.lineTo((50, top))
    pen.closePath()
    return pen.glyph()


def _build_deterministic_test_font(path: Path) -> None:
    glyph_order = [".notdef", "space"]
    cmap = {32: "space"}
    for codepoint in range(33, 127):
        glyph_name = f"uni{codepoint:04X}"
        glyph_order.append(glyph_name)
        cmap[codepoint] = glyph_name

    glyphs = {".notdef": _draw_box(top=700), "space": TTGlyphPen(None).glyph()}
    for codepoint, glyph_name in cmap.items():
        if glyph_name != "space":
            glyphs[glyph_name] = _draw_box(
                top=500 if codepoint == ord("x") else 700,
                right=430 + (codepoint % 10) * 11,
                notch=18 + (codepoint % 7) * 4,
            )

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(cmap)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (600, 50) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
        sxHeight=500,
        sCapHeight=700,
    )
    builder.setupNameTable(
        {
            "familyName": DETERMINISTIC_FONT_NAME,
            "styleName": "Regular",
            "uniqueFontIdentifier": "BCS-Deterministic-Test-Regular-1.0",
            "fullName": f"{DETERMINISTIC_FONT_NAME} Regular",
            "psName": "BCSDeterministicTest-Regular",
            "version": "Version 1.0",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.font.recalcTimestamp = False
    builder.font["head"].created = 2_082_844_800
    builder.font["head"].modified = 2_082_844_800
    builder.save(str(path))


@pytest.fixture(scope="session", autouse=True)
def deterministic_exact_font(tmp_path_factory):
    """Resolve synthetic delivery items without relying on host fonts."""

    font_path = tmp_path_factory.mktemp("bcs_test_font") / "bcs-test-regular.ttf"
    _build_deterministic_test_font(font_path)

    from dxf_text_builder import _ExactFontResolution, _resolve_exact_font

    original_resolver = _resolve_exact_font

    def resolve(font_name: str):
        if str(font_name) == DETERMINISTIC_FONT_NAME:
            return _ExactFontResolution(
                source_name=DETERMINISTIC_FONT_NAME,
                family=DETERMINISTIC_FONT_NAME,
                style="Regular",
                filename=str(font_path),
                exact=True,
                reason="repository-controlled deterministic test font",
                resolution_source="test_fixture",
            )
        return original_resolver(font_name)

    with patch("dxf_text_builder._resolve_exact_font", side_effect=resolve):
        yield font_path


def _supplied_pdf(filename: str) -> Path:
    roots = []
    for variable in ("BCS_PDF_TEST_FILES", "BCS_CORPUS_ROOT"):
        configured = str(os.environ.get(variable, "") or "").strip()
        if configured:
            roots.append(Path(configured).expanduser())
    roots.append(Path.home() / "Desktop" / "PDFTest Files")

    for root in roots:
        for candidate in (root / filename, root / "fixtures" / filename, root / "pdfs" / filename):
            if candidate.is_file():
                return candidate.resolve()

    pytest.skip(
        f"supplied PDF fixture {filename!r} is unavailable; set BCS_PDF_TEST_FILES",
    )


@pytest.fixture
def welding_symbol_chart() -> Path:
    return _supplied_pdf("Welding-Symbol-Chart.pdf")


@pytest.fixture
def aws_weld_symbol_chart() -> Path:
    return _supplied_pdf("AWSWeldSymbolchart.pdf")

"""The glyph outlines must come from the exact source-font program, not ezdxf's fallback.

Found by the LibreCAD visual oracle on `1011 (1 OF 2) - Rev 0.pdf` (2026-08-16): the
title "CLASSIC STEEL" is a light serif (embedded RomanT subset) in every PDF viewer and
a bold sans in LibreCAD's own render of the import. The delivery evidence said
`font_exact_match=True`, `resolved_font_filename=<extracted asset .ttf>` -- and the
outlines were Arial Unicode MS. Root cause: ezdxf resolves fonts *by file name* against
its cache of scanned system folders; the absolute path of an extracted asset is unknown
to it and `fonts.get_font_face(path)` silently returns the fallback face. Every text2path
call in this module went through that lookup, so every embedded-font glyph delivery
rendered the fallback font while all evidence and verification stayed self-consistent.

These tests pin: (1) the engine-name resolver registers the asset folder and returns a
name the engine really loads, refusing (item-scoped) when it cannot; (2) a real glyph
delivery of the deterministic test font -- whose glyphs are boxes -- produces box
outlines, not the fallback font's curves; (3) the fallback face is genuinely different,
so (2) is not vacuous.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import ezdxf
import pytest
from ezdxf.addons import text2path
from ezdxf.disassemble import recursive_decompose
from ezdxf.fonts import fonts as ezdxf_fonts

import dxf_text_builder as dxf_text_builder_module
from dxf_text_builder import (
    TextDeliveryResult,
    _RepresentationImpossible,
    _outline_engine_font_name,
    build_text,
)
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText


def _item(text: str = "W12X30") -> NormalizedText:
    return NormalizedText(
        id=17,
        text=text,
        normalized=text,
        insertion=(12.25, 24.5),
        bbox=(10.0, 20.0, 22.0, 28.0),
        font_size=0.08,
        rotation=0.0,
        font_name="BCS Deterministic Test",
        page_number=3,
        advance_width=7.5,
    )


def test_engine_name_registers_the_asset_folder_and_resolves_to_the_same_file(
    deterministic_exact_font: Path,
) -> None:
    name = _outline_engine_font_name(str(deterministic_exact_font))
    assert name == deterministic_exact_font.name
    face = ezdxf_fonts.get_font_face(name)
    assert face.filename.lower() == name.lower()
    assert face.family == "BCS Deterministic Test"
    font = text2path.get_font(face)
    assert Path(font.name).name.lower() == name.lower()


def test_engine_name_keeps_installed_font_basenames() -> None:
    fallback = ezdxf_fonts.font_manager.fallback_font_name()
    assert _outline_engine_font_name(fallback).lower() == fallback.lower()


def test_engine_name_refuses_when_the_engine_would_substitute(
    deterministic_exact_font: Path,
) -> None:
    # Missing file: nothing to register.
    with pytest.raises(_RepresentationImpossible, match="missing"):
        _outline_engine_font_name(str(deterministic_exact_font.with_name("nope.ttf")))
    # Present but the engine still resolves it to another face: refuse, do not draw.
    fallback_face = ezdxf_fonts.get_font_face(ezdxf_fonts.font_manager.fallback_font_name())
    with patch.object(
        ezdxf_fonts.font_manager, "get_font_face", return_value=fallback_face
    ):
        with pytest.raises(_RepresentationImpossible, match="substitution"):
            _outline_engine_font_name(str(deterministic_exact_font))
    with patch.object(ezdxf_fonts.font_manager, "has_font", return_value=False):
        with pytest.raises(_RepresentationImpossible, match="cannot load"):
            _outline_engine_font_name(str(deterministic_exact_font))


def _glyph_outline_point_counts(doc, msp) -> list[int]:
    counts = []
    for insert in (e for e in msp if e.dxftype() == "INSERT"):
        for outline in recursive_decompose([insert]):
            if outline.dxftype() == "LWPOLYLINE":
                counts.append(len(outline.get_points(format="xy")))
    return counts


def test_glyph_delivery_draws_the_exact_font_not_the_fallback(deterministic_exact_font: Path) -> None:
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    result = build_text(
        _item(),
        msp,
        "TEXT",
        ImportConfig(text_mode="glyphs"),
        target_app="generic",
        dxf_version="R2010",
        return_delivery_result=True,
    )
    assert isinstance(result, TextDeliveryResult)
    assert result.final_representation == "glyphs"
    counts = _glyph_outline_point_counts(doc, msp)
    assert counts, "delivery produced no glyph outlines"
    # The deterministic test font draws every glyph as a 4- or 5-vertex box (see
    # conftest._draw_box); a curved fallback face needs dozens of vertices per glyph.
    assert max(counts) <= 6, (
        f"glyph outlines have up to {max(counts)} vertices -- these are not the box "
        "glyphs of the exact test font; the outline engine substituted another font"
    )
    evidence = [a for a in result.attempts if a.outcome == "verified"][0].evidence
    assert evidence.get("outline_engine_font_verified") is True
    assert evidence.get("outline_engine_font_name", "").lower() == deterministic_exact_font.name.lower()


def test_negative_control_fallback_font_is_not_box_shaped() -> None:
    fallback = ezdxf_fonts.get_font_face(ezdxf_fonts.font_manager.fallback_font_name())
    paths = text2path.make_paths_from_str("W12X30", fallback, size=1.0)
    verts = [len(list(p.flattening(0.01))) for p in paths]
    assert verts and max(verts) > 6, "the fallback face must be distinguishable from box glyphs"


def test_source_text_style_font_is_the_engine_name(deterministic_exact_font: Path) -> None:
    """The temporary source TEXT that seeds text2path must carry the engine name so
    every ezdxf lookup (make_paths_from_entity, text_size) resolves the exact program."""
    doc = ezdxf.new("R2010")
    from dxf_text_builder import _ensure_text_style, _resolve_exact_font

    resolution = _resolve_exact_font("BCS Deterministic Test")
    assert resolution.exact
    style_name, _handle, _created = _ensure_text_style(doc, resolution)
    style = doc.styles.get(style_name)
    assert str(style.dxf.font).lower() == deterministic_exact_font.name.lower()

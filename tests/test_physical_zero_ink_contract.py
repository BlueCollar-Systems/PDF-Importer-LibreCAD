"""Physical source-glyph authority for zero-ink delivery decisions."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from unittest.mock import patch

from fontTools.ttLib import TTFont
import ezdxf
import pytest

from dxf_text_builder import (
    _ExactFontResolution,
    _build_physical_glyph_ink_proof,
    _make_paths_from_source_glyph_id,
    _validate_physical_glyph_ink_proof,
    _visible_ink_expected,
    build_text,
)
from pdfcadcore.embedded_fonts import EmbeddedFontAsset
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText


ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")


def _item(character: str, *, glyph_id: int | None) -> NormalizedText:
    return NormalizedText(
        id=701,
        text=character,
        normalized=character,
        insertion=(4.0, 8.0),
        bbox=(4.0, 6.0, 10.0, 10.0),
        font_size=4.0,
        rotation=0.0,
        font_name="Arial",
        page_number=1,
        source_bbox_pdf=(10.0, 20.0, 30.0, 40.0),
        advance_width=6.0,
        glyph_height=4.0,
        source_glyph_id=glyph_id,
    )


def _arial_resolution() -> _ExactFontResolution:
    if not ARIAL.is_file():
        pytest.skip("Windows Arial fixture is unavailable")
    return _ExactFontResolution(
        source_name="Arial",
        family="Arial",
        style="Regular",
        filename=str(ARIAL),
        exact=True,
        reason="host Arial test fixture",
        resolution_source="test_fixture",
        source_origin="test_fixture",
    )


def _glyph_id(character: str) -> int:
    font = TTFont(str(ARIAL), lazy=False, recalcTimestamp=False)
    try:
        name = font.getBestCmap()[ord(character)]
        return font.getGlyphOrder().index(name)
    finally:
        font.close()


def _arial_asset() -> EmbeddedFontAsset:
    content = ARIAL.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    return EmbeddedFontAsset(
        page_number=1,
        span_font_name="Arial",
        base_font_name="Arial",
        source_xref=17,
        resource_name="F1",
        source_font_type="TrueType",
        source_encoding="Identity-H",
        source_format="ttf",
        source_origin="embedded_pdf_font",
        source_bytes=content,
        source_sha256=digest,
        usable_format="ttf",
        usable_bytes=content,
        usable_sha256=digest,
        asset_id="arial-exact",
        unicode_map_installed=True,
    )


@pytest.mark.parametrize("character", ["\u00ad", "\u034f"])
def test_arial_default_ignorable_with_physical_contour_is_visible(character) -> None:
    """Unicode properties cannot erase a contour in the exact source glyph."""

    item = _item(character, glyph_id=_glyph_id(character))
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        proof = _build_physical_glyph_ink_proof(item, ImportConfig.auto())

    assert _validate_physical_glyph_ink_proof(proof) is True
    assert proof["status"] == "visible"
    assert proof["glyphs"][0]["selection_source"] == "source_glyph_id"
    assert proof["glyphs"][0]["bounds"] is not None
    assert proof["glyphs"][0]["contour_count"] > 0


def test_contoured_source_glyph_bound_to_unicode_space_is_visible() -> None:
    """The PDF glyph ID outranks the character's Unicode whitespace property."""

    item = _item(" ", glyph_id=_glyph_id("A"))
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        proof = _build_physical_glyph_ink_proof(item, ImportConfig.auto())

    assert _validate_physical_glyph_ink_proof(proof) is True
    assert proof["status"] == "visible"
    assert proof["glyphs"][0]["glyph_id"] == _glyph_id("A")
    assert proof["glyphs"][0]["contour_count"] > 0


def test_exact_source_glyph_id_generates_its_contour_not_unicode_space() -> None:
    paths = _make_paths_from_source_glyph_id(
        str(ARIAL),
        _glyph_id("A"),
        cap_height=1.0,
    )

    assert paths
    assert any(list(path.flattening(0.01)) for path in paths)


def test_missing_glyph_identity_is_unproven_never_zero_ink() -> None:
    item = _item(" ", glyph_id=None)
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        proof = _build_physical_glyph_ink_proof(item, ImportConfig.auto())

    assert _validate_physical_glyph_ink_proof(proof) is True
    assert proof["status"] == "unproven"
    assert proof["glyphs"][0]["status"] == "unproven"
    assert proof["glyphs"][0]["glyph_id"] is None


def test_outline_does_not_use_uninstalled_unicode_cmap_as_glyph_authority() -> None:
    item = _item("A", glyph_id=None)
    doc = ezdxf.new("R2010")
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        result = build_text(
            item,
            doc.modelspace(),
            "TEXT",
            ImportConfig(text_mode="geometry"),
            target_app="librecad",
            dxf_version="R2010",
            return_delivery_result=True,
        )

    assert result.verified is False
    assert result.final_representation is None
    assert list(doc.modelspace()) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)
    assert any(
        "glyph identity or contour evidence is incomplete" in attempt.reason
        for attempt in result.attempts
    )


def test_boolean_glyph_identity_is_rejected_as_unproven() -> None:
    item = _item(" ", glyph_id=True)
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        proof = _build_physical_glyph_ink_proof(item, ImportConfig.auto())

    assert _validate_physical_glyph_ink_proof(proof) is True
    assert proof["status"] == "unproven"
    assert proof["glyphs"][0]["glyph_id"] is None


@pytest.mark.parametrize("character", [" ", "\u00ad", "\u034f", "\u200b"])
def test_unicode_property_alone_never_certifies_zero_ink(character) -> None:
    """This hint must remain conservative when physical glyph evidence is absent."""

    assert _visible_ink_expected(character) is True


def test_installed_pdf_unicode_cmap_can_prove_empty_glyph(
    tmp_path,
) -> None:
    asset = _arial_asset()
    staged = tmp_path / "arial-exact.ttf"
    staged.write_bytes(asset.usable_bytes)
    config = ImportConfig.auto()
    config._embedded_font_asset_paths = {asset.asset_id: str(staged)}
    item = replace(_item(" ", glyph_id=None), font_asset=asset)

    proof = _build_physical_glyph_ink_proof(item, config)

    assert _validate_physical_glyph_ink_proof(proof) is True
    assert proof["status"] == "empty"
    assert proof["glyphs"][0]["selection_source"] == "installed_pdf_unicode_cmap"
    assert proof["glyphs"][0]["bounds"] is None
    assert proof["glyphs"][0]["contour_count"] == 0


def test_tampered_staged_font_bytes_cannot_prove_empty_glyph(tmp_path) -> None:
    asset = _arial_asset()
    staged = tmp_path / "arial-tampered.ttf"
    staged.write_bytes(asset.usable_bytes + b"tampered")
    config = ImportConfig.auto()
    config._embedded_font_asset_paths = {asset.asset_id: str(staged)}
    item = replace(_item(" ", glyph_id=None), font_asset=asset)

    proof = _build_physical_glyph_ink_proof(item, config)

    assert proof["status"] == "unproven"
    assert proof["status"] != "empty"


def test_zero_ink_proof_tampering_is_rejected() -> None:
    item = _item(" ", glyph_id=_glyph_id(" "))
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        proof = _build_physical_glyph_ink_proof(item, ImportConfig.auto())

    assert proof["status"] == "empty"
    assert _validate_physical_glyph_ink_proof(proof) is True
    proof["glyphs"][0]["glyph_id"] = _glyph_id("A")
    assert _validate_physical_glyph_ink_proof(proof) is False

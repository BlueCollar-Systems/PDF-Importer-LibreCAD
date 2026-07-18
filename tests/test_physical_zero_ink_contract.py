"""Physical source-glyph authority for zero-ink delivery decisions."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
from pathlib import Path
from unittest.mock import patch

import dxf_text_builder
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
from pdfcadcore.primitives import NormalizedText, TextCharLayout


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


def _reseal(proof: dict) -> dict:
    proof.pop("proof_sha256", None)
    proof["proof_sha256"] = dxf_text_builder._canonical_sha256(proof)  # noqa: SLF001
    return proof


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


def test_unavailable_font_preserves_exact_source_glyph_identity_as_unproven() -> None:
    item = _item("A", glyph_id=_glyph_id("A"))
    resolution = _ExactFontResolution(
        source_name="DefinitelyMissingFont",
        family="Definitely Missing Font",
        style="Regular",
        filename="",
        exact=False,
        reason="exact source font is unavailable",
        resolution_source="source_pdf_and_installed_exact_font",
        proof_category="source_specific_impossibility",
        item_impossibility_proven=True,
    )
    config = ImportConfig.auto()
    proof = _build_physical_glyph_ink_proof(
        item,
        config,
        resolution=resolution,
    )

    assert proof["status"] == "unproven"
    assert proof["glyphs"][0]["glyph_id"] == _glyph_id("A")
    assert proof["glyphs"][0]["selection_source"] == "source_glyph_id"
    assert proof["glyphs"][0]["status"] == "unproven"
    assert _validate_physical_glyph_ink_proof(
        proof,
        expected_text_item=item,
        expected_config=config,
        expected_resolution=resolution,
    ) is True


@pytest.mark.parametrize(
    "mode",
    ["text", "labels", "3d_text", "glyphs", "geometry"],
)
def test_missing_glyph_identity_exhausts_finite_ladder_without_stalling(
    mode,
) -> None:
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
            ImportConfig(text_mode=mode),
            target_app="librecad",
            dxf_version="R2010",
            return_delivery_result=True,
        )

    assert result.verified is False
    assert result.final_representation is None
    assert result.requested_representation == mode
    assert result.terminal_fallback_authorized is True
    assert list(doc.modelspace()) == []
    assert all(attempt.cleanup_verified for attempt in result.attempts)
    assert all(attempt.outcome == "impossible" for attempt in result.attempts)
    assert all(
        "glyph identity or contour evidence is incomplete" in attempt.reason
        for attempt in result.attempts
        if attempt.attempted_representation in {"glyphs", "geometry"}
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


def test_resealed_bool_glyph_id_is_rejected_without_integer_coercion() -> None:
    item = _item(" ", glyph_id=1)
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=_arial_resolution(),
    ):
        proof = _build_physical_glyph_ink_proof(item, ImportConfig.auto())

    assert proof["status"] == "empty"
    assert proof["glyphs"][0]["glyph_id"] == 1
    proof["glyphs"][0]["glyph_id"] = True
    _reseal(proof)
    assert _validate_physical_glyph_ink_proof(proof) is False


def test_conflicting_source_glyph_aliases_are_unproven() -> None:
    resolution = _arial_resolution()
    item = replace(
        _item("A", glyph_id=_glyph_id("B")),
        source_char_layout=(
            TextCharLayout(
                text="A",
                glyph_id=_glyph_id("A"),
                source_origin_pdf=(10.0, 40.0),
                source_bbox_pdf=(10.0, 20.0, 30.0, 40.0),
                source_quad_pdf=(
                    (10.0, 20.0),
                    (30.0, 20.0),
                    (30.0, 40.0),
                    (10.0, 40.0),
                ),
                target_origin=(4.0, 8.0),
                target_quad=(
                    (4.0, 6.0),
                    (10.0, 6.0),
                    (10.0, 10.0),
                    (4.0, 10.0),
                ),
                advance_width=6.0,
                glyph_height=4.0,
            ),
        ),
    )
    config = ImportConfig.auto()
    with patch("dxf_text_builder._resolve_item_font", return_value=resolution):
        proof = _build_physical_glyph_ink_proof(item, config)

    assert proof["status"] == "unproven"
    assert proof["glyphs"][0]["glyph_id"] is None
    assert proof["glyphs"][0]["selection_source"] == "missing"
    assert _validate_physical_glyph_ink_proof(
        proof,
        expected_text_item=item,
        expected_config=config,
        expected_resolution=resolution,
    ) is True


@pytest.mark.parametrize("mutation", ["selection_source", "source_text"])
def test_resealed_alternate_glyph_source_is_rejected(mutation) -> None:
    item = _item("A", glyph_id=_glyph_id("A"))
    config = ImportConfig.auto()
    resolution = _arial_resolution()
    with patch(
        "dxf_text_builder._resolve_item_font",
        return_value=resolution,
    ):
        proof = _build_physical_glyph_ink_proof(item, config)

    if mutation == "selection_source":
        proof["glyphs"][0]["selection_source"] = "invented"
    else:
        proof["glyphs"][0]["character_codepoint"] = ord("B")
        proof["source_text_sha256"] = hashlib.sha256(b"B").hexdigest()
    _reseal(proof)
    assert _validate_physical_glyph_ink_proof(
        proof,
        expected_text_item=item,
        expected_config=config,
        expected_resolution=resolution,
    ) is False


def test_physical_proof_binds_expected_pdf_page_item_font_and_glyph(
    tmp_path,
) -> None:
    source_pdf = tmp_path / "selected-source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n% exact source identity fixture\n")
    source_sha = hashlib.sha256(source_pdf.read_bytes()).hexdigest()
    config = ImportConfig.auto()
    config._source_pdf_path = str(source_pdf.resolve())
    config._source_pdf_sha256 = source_sha
    resolution = _arial_resolution()
    item = _item("A", glyph_id=_glyph_id("A"))
    with patch("dxf_text_builder._resolve_item_font", return_value=resolution):
        proof = _build_physical_glyph_ink_proof(item, config)
        assert _validate_physical_glyph_ink_proof(
            proof,
            expected_text_item=item,
            expected_config=config,
            expected_resolution=resolution,
        ) is True

        mutations = []
        for field_name, value in (
            ("source_pdf_sha256", "0" * 64),
            ("source_page_number", 2),
            ("source_item_id", 999),
            ("source_id", "text_span:2:999"),
            ("font_program_path", str(tmp_path / "alternate-arial.ttf")),
            ("font_asset_id", "alternate-font-asset"),
        ):
            candidate = copy.deepcopy(proof)
            candidate[field_name] = value
            mutations.append(_reseal(candidate))
        alternate_text = copy.deepcopy(proof)
        alternate_text["source_text_sha256"] = hashlib.sha256(b"B").hexdigest()
        alternate_text["glyphs"][0]["character_codepoint"] = ord("B")
        mutations.append(_reseal(alternate_text))
        alternate_glyph = copy.deepcopy(proof)
        alternate_glyph["glyphs"][0]["selection_source"] = "invented"
        mutations.append(_reseal(alternate_glyph))

        assert all(
            not _validate_physical_glyph_ink_proof(
                candidate,
                expected_text_item=item,
                expected_config=config,
                expected_resolution=resolution,
            )
            for candidate in mutations
        )

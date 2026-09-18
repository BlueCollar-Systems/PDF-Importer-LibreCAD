"""E2-like empty source fonts and rounded fraction quads, without private PDFs."""

from dataclasses import replace
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ezdxf
import pytest

import dxf_text_builder as builder
from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.exporters import dxf_exporter as exporter
from librecad_pdf_importer.importer import run_import
from pdfcadcore.embedded_fonts import EmbeddedFontFailure
from pdfcadcore.fitz_loader import import_fitz
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import PageData
from test_positioned_fraction_dxf_delivery import _positioned_fraction
from test_representation_delivery_contract import _item


_RUNTIME_CATEGORIES = (
    "runtime_inventory_unavailable_for_item",
    "runtime_source_document_unavailable_for_item",
    "runtime_source_font_extraction_unavailable_for_item",
    "source_inventory_invalid_for_page",
    "runtime_capability_unavailable_for_item",
    "source_font_ambiguous_for_item",
)
_MODES = ("text", "labels", "glyphs", "geometry", "3d_text")


def _empty_program_item(*, positioned=True):
    item = _positioned_fraction("vertical") if positioned else _item()
    return replace(
        item, font_name="Arial", font_asset=None,
        font_failure=EmbeddedFontFailure(
            page_number=item.page_number, span_font_name="Arial", source_xref=61,
            reason="embedded_font_asset_build_failed",
            error_type="ExactFontSourceImpossible",
            detail="embedded font stream is empty",
            proof_category="source_specific_impossibility",
        ),
    )


def _deliver(item, mode="glyphs", config=None):
    builder.reset_text_styles()
    doc = ezdxf.new("R2010")
    with patch.object(builder, "_resolve_exact_font", return_value=builder._ExactFontResolution(
        source_name="Arial", family="Arial", exact=False, reason="no exact match",
    )):
        result = builder.build_text(
            item, doc.modelspace(), "TEXT", config or ImportConfig(text_mode=mode),
            target_app="librecad", dxf_version="R2010", return_delivery_result=True,
        )
    assert list(doc.modelspace()) == []
    return result


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("positioned", [False, True])
def test_observed_empty_program_authorizes_source_bound_raster(mode, positioned):
    item = _empty_program_item(positioned=positioned)
    result = _deliver(item, mode)
    assert not result.verified
    assert result.terminal_fallback_authorized
    assert all(attempt.outcome == "impossible" for attempt in result.attempts)
    assert any(attempt.evidence.get("font_source_xref") == 61 for attempt in result.attempts)


@pytest.mark.parametrize("category", _RUNTIME_CATEGORIES)
@pytest.mark.parametrize("positioned", [False, True])
@pytest.mark.parametrize("mode", _MODES)
def test_runtime_and_invalid_inventory_never_authorize_raster(category, positioned, mode):
    item = _empty_program_item(positioned=positioned)
    item.font_failure = replace(
        item.font_failure, reason="font_inventory_unavailable", error_type="RuntimeError",
        detail="injected runtime failure", proof_category=category,
    )
    result = _deliver(item, mode)
    assert not result.terminal_fallback_authorized
    assert any(attempt.outcome == "failed" for attempt in result.attempts)
    assert all(attempt.attempted_representation != "raster" for attempt in result.attempts)


@pytest.mark.parametrize("changes", [
    {"page_number": 1}, {"span_font_name": "OtherFont"},
    {"error_type": "RuntimeError"}, {"source_xref": None},
    {"source_xref": 0}, {"source_xref": True},
    {"detail": "font helper unavailable"}, {"reason": "page_font_inventory_failed"},
])
def test_fraction_empty_program_proof_is_specific_and_bound(changes):
    item = _empty_program_item()
    item.font_failure = replace(item.font_failure, **changes)
    assert not builder._positioned_empty_font_program_proven(item)
    assert not _deliver(item).terminal_fallback_authorized


@pytest.mark.parametrize("positioned", [False, True])
def test_runtime_error_cannot_claim_source_specific_impossibility(positioned):
    item = _empty_program_item(positioned=positioned)
    item.font_failure = replace(item.font_failure, error_type="RuntimeError")
    result = _deliver(item)
    assert not result.terminal_fallback_authorized
    assert any(attempt.outcome == "failed" for attempt in result.attempts)


@pytest.mark.parametrize("positioned", [False, True])
@pytest.mark.parametrize("restaging", [False, True])
def test_staging_error_is_diagnostic_not_impossibility(tmp_path, positioned, restaging):
    item = _empty_program_item(positioned=positioned)
    item.font_failure = None
    asset_id = "sha256:" + "a" * 64
    item.font_asset = SimpleNamespace(
        asset_id=asset_id, usable_bytes=b"source", usable_sha256="a" * 64,
        base_font_name="Arial", source_xref=61,
    )
    config = ImportConfig(text_mode="glyphs")
    config._embedded_font_staging_faults = {asset_id: "output disk unavailable"}
    if restaging:
        config._embedded_font_asset_paths = {asset_id: str(tmp_path / "missing.ttf")}

        def fail_restore(_asset_id):
            raise OSError("asset restore unavailable")

        config._restore_embedded_font_asset = fail_restore
    with patch.object(builder, "_embedded_ezdxf_cap_height_ratio", return_value=0.7):
        resolution = builder._resolve_item_font(item, config)
        result = _deliver(item, config=config)
    assert resolution.proof_category == "environment_write_fault"
    assert not resolution.item_impossibility_proven
    assert not result.terminal_fallback_authorized
    assert any(attempt.outcome == "failed" for attempt in result.attempts)


@pytest.mark.parametrize("positioned", [False, True])
def test_runtime_failure_export_preserves_prior_output_without_raster(tmp_path, positioned):
    item = _empty_program_item(positioned=positioned)
    item.font_failure = replace(
        item.font_failure, error_type="RuntimeError", detail="trace unavailable",
        proof_category="runtime_inventory_unavailable_for_item",
    )
    extraction = DocumentExtraction(
        pdf_path=str(tmp_path / "must-not-be-read.pdf"),
        pages=[ExtractedPage(page_data=PageData(
            page_number=3, width=300.0, height=200.0, text_items=[item],
        ), profile=SimpleNamespace())],
    )
    output = tmp_path / "prior.dxf"
    output.write_bytes(b"prior output")
    assets = tmp_path / "prior_assets"
    assets.mkdir()
    asset = assets / "prior.png"
    asset.write_bytes(b"prior asset")
    with (
        patch.object(exporter, "_file_sha256", side_effect=AssertionError("no source read")),
        patch.object(exporter, "_attempt_terminal_text_raster", side_effect=AssertionError("no Raster")),
        pytest.raises(exporter.TextRepresentationDeliveryError),
    ):
        exporter.export_to_dxf(extraction, str(output), exporter.DxfExportOptions(
            include_images=False, text_mode="glyphs",
        ))
    assert output.read_bytes() == b"prior output"
    assert asset.read_bytes() == b"prior asset"


@pytest.mark.parametrize("scale", [0.001, 1.0, 1000.0])
@pytest.mark.parametrize("width, height, dy", [
    (1.5297515869140739, 3.073217444106774, 1.516125394118717e-6),
    (0.9145436604818, 3.6879399256683882, 1.32603668e-5),
])
def test_e2_quad_rounding_is_accepted_at_every_scale(scale, width, height, dy):
    # Real E2 character frames include at most 0.000831 degree edge noise.
    raw = ((0., 0.), (width, dy), (width, dy - height), (0., -height))
    quad = tuple((x * scale, y * scale) for x, y in raw)
    measured_width, measured_height, rotation = builder._quad_frame(quad)
    assert measured_width == pytest.approx(width * scale)
    assert measured_height == pytest.approx(height * scale)
    assert 0 < rotation < 0.000831
    item = _positioned_fraction("vertical", scale=scale, origin=(0., 0.))
    char = replace(item.source_char_layout[0], target_quad=quad,
                   advance_width=measured_width, glyph_height=measured_height)
    item.source_char_layout = (char, *item.source_char_layout[1:])
    assert builder._positioned_fraction_layout(item) is not None


@pytest.mark.parametrize("scale", [0.001, 1.0, 1000.0])
@pytest.mark.parametrize("shear", [1e-4, 0.2, 0.5])
def test_real_shear_is_rejected_at_every_scale(scale, shear):
    quad = tuple((x * scale, y * scale) for x, y in
                 ((0., 0.), (1., 0.), (1. + shear, -1.), (shear, -1.)))
    with pytest.raises(builder._RepresentationImpossible, match="shear"):
        builder._quad_frame(quad)


def test_incompatible_character_rotation_still_rejected():
    item = _positioned_fraction("vertical", rotation=0.01)
    item.rotation = 0.0
    with pytest.raises(builder._RepresentationImpossible, match="orientation"):
        builder._positioned_fraction_layout(item)


def test_real_empty_arial_program_fraction_exports_and_reopens(tmp_path):
    fitz = import_fitz()
    pdf = fitz.open()
    page = pdf.new_page(width=200, height=120)
    page.insert_text((60, 50), "13", fontsize=8)
    page.insert_text((60, 62), "16", fontsize=8)
    page.insert_text((59, 58), "/", fontsize=10)
    font_xref = page.get_fonts(full=True)[0][0]
    pdf.xref_set_key(font_xref, "BaseFont", "/Arial")
    pdf.xref_set_key(font_xref, "Subtype", "/TrueType")
    source = tmp_path / "empty-arial-fraction.pdf"
    pdf.save(source)
    pdf.close()
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    fraction = next(item for item in run.extraction.pages[0].page_data.text_items
                    if item.text == "13/16")
    assert builder._positioned_empty_font_program_proven(fraction)
    output = tmp_path / "empty-arial-fraction.dxf"
    result = exporter.export_to_dxf(run.extraction, str(output), exporter.DxfExportOptions(
        include_images=False, text_mode="glyphs", dxf_version="R2010",
    ))
    reopened = ezdxf.readfile(output)
    images = list(reopened.modelspace().query("IMAGE"))
    assert len(images) == 1
    assert not list(reopened.modelspace().query("TEXT MTEXT INSERT"))
    image = images[0]
    assert math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y) > 0
    assert math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y) > 0
    assert result.image_count == 1
    delivery = result.text_deliveries[0]
    assert delivery["verified"] is True
    assert delivery["final_representation"] == "raster"
    evidence = delivery["attempts"][-1]["evidence"]
    assert evidence["source_pdf_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert evidence["source_bbox_pdf"] == pytest.approx(fraction.source_bbox_pdf)
    assert evidence["anchor_verified"] and evidence["size_verified"]
    asset = Path(evidence["asset_path"])
    assert asset.is_file()
    assert (output.parent / image.image_def.dxf.filename).resolve() == asset.resolve()
    assert evidence["asset_sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()
    with fitz.open(source) as source_pdf:
        page = source_pdf[0]
        dpi = evidence["raster_dpi"]
        expected_png = page.get_pixmap(
            matrix=fitz.Matrix(dpi / 72., dpi / 72.),
            clip=fitz.Rect(fraction.source_bbox_pdf) & page.rect,
            colorspace=fitz.csRGB, alpha=False,
        ).tobytes("png")
    assert asset.read_bytes() == expected_png

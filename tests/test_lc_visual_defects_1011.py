"""Defects the LibreCAD visual oracle found on `1011 (1 OF 2) - Rev 0.pdf` (2026-08-16).

The oracle renders the import with LibreCAD's own dxf2png and compares it side by side
with the PDF page. Three import defects surfaced that no report field showed:

1. 34 small bolt/weld circles the PDF draws as two half-polylines (left half top->bottom,
   right half top->bottom) came out as two identical LEFT-half ARCs -- a "C" instead of a
   circle. `_promote_arcs` emitted (first, last) regardless of traversal direction, but a
   DXF ARC always sweeps counter-clockwise, so a clockwise polyline became its complement.
2. The historical 0.6-width stacked-fraction rewrite was retired: exact observed union
   geometry is retained, and an invalid positioned fraction cannot read the source PDF or
   descend to Raster. Ordinary requested-Raster items still retain square pixels.
3. Custom PDF_DASH linetypes render continuous in LibreCAD (tracked separately).
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from librecad_pdf_importer.core import document as document_module
from pdfcadcore.primitives import PageData, Primitive


def _half_circle_points(cx, cy, r, start_deg, end_deg, n=16):
    return [
        (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        for a in [start_deg + (end_deg - start_deg) * i / n for i in range(n + 1)]
    ]


def _arc_covers(prim, angle_deg, tol=1.0):
    """True if the CCW sweep start->end of the promoted arc contains angle_deg."""
    start, end = prim.start_angle, prim.end_angle
    a = angle_deg % 360.0
    sweep = (end - start) % 360.0
    off = (a - start) % 360.0
    return off <= sweep + tol


@pytest.mark.parametrize("clockwise", [False, True])
def test_promote_arcs_respects_traversal_direction(clockwise: bool) -> None:
    # Right half of a circle: from top (90 deg) down to bottom (-90 deg) is a CLOCKWISE
    # traversal; from bottom up to top is counter-clockwise. Both describe the same
    # right-half arc and must both come out covering 0 deg (the rightmost point).
    if clockwise:
        pts = _half_circle_points(10.0, 10.0, 2.0, 90.0, -90.0)
    else:
        pts = _half_circle_points(10.0, 10.0, 2.0, -90.0, 90.0)
    prim = Primitive(id=1, type="polyline", points=pts, closed=False)
    page = PageData(page_number=1, width=100.0, height=100.0, primitives=[prim], text_items=[])
    document_module._promote_arcs(page, arc_fit_tol_mm=0.05, min_arc_span_deg=5.0)
    assert prim.type == "arc"
    assert _arc_covers(prim, 0.0), (
        f"right-half arc {prim.start_angle:.1f}->{prim.end_angle:.1f} does not cover 0 deg "
        f"(clockwise={clockwise}); this is the 'C instead of a circle' defect"
    )
    assert not _arc_covers(prim, 180.0)


def test_two_half_polylines_of_one_circle_cover_the_whole_circle() -> None:
    # Exactly the PDF's construction: left half top->bottom (CCW through 180) and right
    # half top->bottom (CW through 0). Before the fix both became the left half.
    left = Primitive(id=1, type="polyline", points=_half_circle_points(5.0, 5.0, 1.5, 90.0, 270.0), closed=False)
    right = Primitive(id=2, type="polyline", points=_half_circle_points(5.0, 5.0, 1.5, 90.0, -90.0), closed=False)
    page = PageData(page_number=1, width=100.0, height=100.0, primitives=[left, right], text_items=[])
    document_module._promote_arcs(page, arc_fit_tol_mm=0.05, min_arc_span_deg=5.0)
    assert left.type == "arc" and right.type == "arc"
    for angle in range(0, 360, 15):
        assert _arc_covers(left, angle) or _arc_covers(right, angle), f"{angle} deg uncovered"


# ---------------------------------------------------------------------------
# 3. Dashed linetypes: LibreCAD only recognizes its own linetype NAMES.
# ---------------------------------------------------------------------------
import ezdxf  # noqa: E402

from librecad_pdf_importer.exporters import dxf_exporter as dxf_exporter_module  # noqa: E402

LIBRECAD_LINETYPE_NAMES = {
    f"{family}{variant}"
    for family in ("DASHED", "DASHDOT", "CENTER", "DOT", "DIVIDE", "BORDER")
    for variant in ("", "TINY", "2", "X2")
}


@pytest.mark.parametrize(
    ("dash_pt", "expected_family"),
    [
        ("[6 6] 0", "DASHED"),        # 1011 hidden lines: 2.12 mm dash / gap
        ("[12 6] 0", "DASHED"),
        ("[18 6 1 6] 0", "DASHDOT"),  # long-gap-dot-gap
        ("[18 4 6 4] 0", "CENTER"),   # long-short
        ("[1 3] 0", "DOT"),
        ("[18 4 1 4 1 4] 0", "DIVIDE"),
        ("[12 4 12 4 1 4] 0", "BORDER"),
    ],
)
def test_pdf_dashes_map_to_librecad_recognized_names(dash_pt: str, expected_family: str) -> None:
    doc = ezdxf.new("R2010")
    cache: dict = {}
    name = dxf_exporter_module._linetype_from_dash(doc, dash_pt, cache)
    assert name in LIBRECAD_LINETYPE_NAMES, name
    assert name.startswith(expected_family)
    assert not name.startswith("PDF_DASH"), "custom names render CONTINUOUS in LibreCAD"
    assert name in doc.linetypes
    assert "PDF dash" in str(doc.linetypes.get(name).dxf.description)


def test_dash_variant_tracks_pdf_dash_length() -> None:
    doc = ezdxf.new("R2010")
    short = dxf_exporter_module._linetype_from_dash(doc, "[6 6] 0", {})      # 2.1 mm -> TINY
    medium = dxf_exporter_module._linetype_from_dash(doc, "[18 9] 0", {})    # 6.35 mm -> 2
    long_ = dxf_exporter_module._linetype_from_dash(doc, "[36 18] 0", {})    # 12.7 mm -> base
    huge = dxf_exporter_module._linetype_from_dash(doc, "[72 36] 0", {})     # 25.4 mm -> X2
    assert (short, medium, long_, huge) == ("DASHEDTINY", "DASHED2", "DASHED", "DASHEDX2")
    assert dxf_exporter_module._linetype_scale_for_dash("[36 18] 0") == pytest.approx(1.0, abs=0.01)


def test_same_pdf_dash_reuses_one_linetype_and_distinct_dashes_do_not_collide() -> None:
    doc = ezdxf.new("R2010")
    cache: dict = {}
    a = dxf_exporter_module._linetype_from_dash(doc, "[6 6] 0", cache)
    b = dxf_exporter_module._linetype_from_dash(doc, "[6 6] 0", cache)
    c = dxf_exporter_module._linetype_from_dash(doc, "[18 6 1 6] 0", cache)
    assert a == b and a != c
    assert len(cache) == 2


# ---------------------------------------------------------------------------
# 4. Lineweights were converted pt->mm twice (pdfcadcore already delivers mm).
# ---------------------------------------------------------------------------
from pdfcadcore.primitive_extractor import MM_PER_PT  # noqa: E402


@pytest.mark.parametrize("width_pt", [0.24, 0.60, 0.84, 1.32])
def test_lineweight_treats_primitive_line_width_as_millimetres(width_pt: float) -> None:
    width_mm = width_pt * MM_PER_PT          # what pdfcadcore stores on Primitive.line_width
    attribs: dict = {}
    dxf_exporter_module._apply_lineweight(attribs, width_mm)
    expected = int(max(5, min(211, round(width_mm * 100))))
    assert attribs["lineweight"] == expected
    # The old double conversion produced width_mm * MM_PER_PT -> 2.83x too thin.
    wrong = int(max(5, min(211, round(width_mm * MM_PER_PT * 100))))
    assert attribs["lineweight"] != wrong or expected == 5


def test_lineweight_ignores_missing_or_non_finite_widths() -> None:
    for bad in (None, float("nan"), "x"):
        attribs: dict = {}
        dxf_exporter_module._apply_lineweight(attribs, bad)
        assert "lineweight" not in attribs


# ---------------------------------------------------------------------------
# 2. Exact stacked-fraction truth does not use the retired 0.6-width rewrite.
#    Invalid positioned evidence fails atomically; ordinary Raster remains square-pixel.
# ---------------------------------------------------------------------------
from librecad_pdf_importer.exporters.dxf_exporter import (  # noqa: E402
    DxfExportOptions,
    TextRepresentationDeliveryError,
    export_to_dxf,
)
from librecad_pdf_importer.importer import run_import  # noqa: E402
from pdfcadcore.fitz_loader import import_fitz  # noqa: E402
from pdfcadcore import primitive_extractor as primitive_extractor_module  # noqa: E402

fitz = import_fitz()


def _footprint_aspect(image):
    w = math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y) * float(image.dxf.image_size.x)
    h = math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y) * float(image.dxf.image_size.y)
    return w / h


def _write_stacked_fraction_pdf(pdf_path, *, include_plate: bool = True) -> None:
    pdf = fitz.open()
    page = pdf.new_page(width=200, height=120)
    # A stacked fraction the way CAD PDFs draw it: numerator over denominator,
    # plus a separately positioned slash span.
    page.insert_text((60, 50), "13", fontsize=8)
    page.insert_text((60, 62), "16", fontsize=8)
    page.insert_text((59, 58), "/", fontsize=10)
    if include_plate:
        page.insert_text((100, 90), "PLATE", fontsize=10)
    pdf.save(str(pdf_path))
    pdf.close()


def test_stacked_fraction_merge_preserves_full_observed_union(tmp_path) -> None:
    pdf_path = tmp_path / "stacked-fraction-exact-union.pdf"
    _write_stacked_fraction_pdf(pdf_path)

    with patch.object(
        primitive_extractor_module,
        "_merge_stacked_fractions",
        side_effect=lambda items: items,
    ):
        unmerged_run = run_import(
            str(pdf_path),
            mode="vector",
            overrides={"pages": "1"},
        )
    merged_run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})

    observed_parts = [
        item
        for item in unmerged_run.extraction.pages[0].page_data.text_items
        if item.text in {"13", "16", "/"}
    ]
    assert [item.text for item in observed_parts] == ["13", "16", "/"]
    assert all(item.bbox is not None for item in observed_parts)
    expected_union = (
        min(item.bbox[0] for item in observed_parts),
        min(item.bbox[1] for item in observed_parts),
        max(item.bbox[2] for item in observed_parts),
        max(item.bbox[3] for item in observed_parts),
    )
    merged = next(
        item
        for item in merged_run.extraction.pages[0].page_data.text_items
        if item.text == "13/16"
    )

    assert merged.bbox == pytest.approx(expected_union, abs=1e-9)
    assert merged.requires_individual_positioning is True
    assert "".join(char.text for char in merged.source_char_layout) == "13/16"


@pytest.mark.parametrize("fault", ["unsupported_shear", "partial_layout"])
def test_invalid_positioned_fraction_refuses_without_pdf_or_raster_work(
    tmp_path,
    fault: str,
) -> None:
    pdf_path = tmp_path / f"stacked-fraction-{fault}.pdf"
    _write_stacked_fraction_pdf(pdf_path, include_plate=False)
    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    fraction = next(
        item
        for item in run.extraction.pages[0].page_data.text_items
        if item.text == "13/16"
    )
    if fault == "partial_layout":
        fraction.source_char_layout = fraction.source_char_layout[:-1]

    output = tmp_path / f"prior-{fault}.dxf"
    prior = b"prior native artifact\n"
    output.write_bytes(prior)
    asset_root = output.with_name(f"{output.stem}_assets")

    with (
        patch.object(
            dxf_exporter_module,
            "_file_sha256",
            side_effect=AssertionError("source PDF hash must not be read"),
        ) as source_hash,
        patch.object(
            dxf_exporter_module,
            "_attempt_terminal_text_raster",
            side_effect=AssertionError("terminal Raster must not be attempted"),
        ) as raster_attempt,
        patch.object(
            dxf_exporter_module,
            "_rectangular_opaque_crop",
            side_effect=AssertionError("source crop must not be attempted"),
        ) as source_crop,
        pytest.raises(TextRepresentationDeliveryError) as raised,
    ):
        export_to_dxf(
            run.extraction,
            str(output),
            DxfExportOptions(include_images=False, text_mode="raster"),
        )

    assert output.read_bytes() == prior
    assert not asset_root.exists()
    assert raised.value.delivery.verified is False
    assert raised.value.delivery.final_representation is None
    assert raised.value.delivery.terminal_fallback_authorized is False
    assert all(attempt.cleanup_verified is True for attempt in raised.value.delivery.attempts)
    assert source_hash.call_count == 0
    assert raster_attempt.call_count == 0
    assert source_crop.call_count == 0


def test_non_fraction_requested_raster_keeps_source_clip_aspect(tmp_path) -> None:
    pdf_path = tmp_path / "ordinary-raster-text.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=200, height=120)
    page.insert_text((60, 60), "PLATE", fontsize=10)
    pdf.save(str(pdf_path))
    pdf.close()
    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    output = tmp_path / "ordinary-raster-text.dxf"
    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(include_images=False, text_mode="raster"),
    )

    assert result.text_deliveries
    doc = ezdxf.readfile(str(output))
    images = list(doc.modelspace().query("IMAGE"))
    assert images
    for delivery, image in zip(result.text_deliveries, images, strict=True):
        ev = delivery["attempts"][-1]["evidence"]
        u = math.hypot(image.dxf.u_pixel.x, image.dxf.u_pixel.y)
        v = math.hypot(image.dxf.v_pixel.x, image.dxf.v_pixel.y)
        assert u == pytest.approx(v, rel=0.03), (delivery["source_id"], u, v)
        assert _footprint_aspect(image) == pytest.approx(ev["source_clip_aspect"], rel=0.03)

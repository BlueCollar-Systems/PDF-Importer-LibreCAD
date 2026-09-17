"""The positioned-fraction route must only engage for the merger's semantic fraction.

Regression for v1.0.92–v1.0.95: every ordinary text span whose text merely looks like a
fraction ("3/8" on a dimension string) carries a character layout from rawdict
extraction, so pdfcadcore marks it ``requires_individual_positioning``.  The route then
treated it as a merged stacked fraction and refused the whole page with
"positioned fraction contains invented aggregate placement metrics" because the span
legitimately has a source quad and an aggregate advance.  Shop drawings with plain
fraction labels stopped converting in every text mode.
"""

from __future__ import annotations

import fitz
import pytest

from dxf_text_builder import (
    _RepresentationImpossible,
    _positioned_fraction_layout,
    _quad_frame,
)
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import
from pdfcadcore.primitives import NormalizedText, TextCharLayout


def _layout(text: str) -> tuple[TextCharLayout, ...]:
    chars = []
    for index, character in enumerate(text):
        x0 = float(index)
        quad = ((x0, 0.0), (x0 + 1.0, 0.0), (x0 + 1.0, 1.0), (x0, 1.0))
        chars.append(
            TextCharLayout(
                text=character,
                glyph_id=index,
                source_origin_pdf=(x0, 0.0),
                source_bbox_pdf=(x0, 0.0, x0 + 1.0, 1.0),
                source_quad_pdf=quad,
                target_origin=(x0, 0.0),
                target_quad=quad,
                advance_width=1.0,
                glyph_height=1.0,
            )
        )
    return tuple(chars)


def _ordinary_span(text: str) -> NormalizedText:
    """Exactly what extract_page yields for a plain fraction label on a drawing."""
    quad = ((10.0, 20.0), (17.8, 20.0), (17.8, 25.5), (10.0, 25.5))
    return NormalizedText(
        id=1,
        text=text,
        normalized=text,
        insertion=(10.0, 20.0),
        bbox=(10.0, 20.0, 17.8, 25.5),
        font_size=5.5,
        page_number=1,
        source_bbox_pdf=(100.0, 600.0, 107.8, 605.5),
        source_quad_pdf=quad,
        target_quad_model=quad,
        advance_width=7.83,
        glyph_height=5.49,
        source_char_layout=_layout(text),
        requires_individual_positioning=True,
    )


def _merger_fraction(**overrides) -> NormalizedText:
    """The merger's semantic stacked fraction: no quads, zero aggregate metrics."""
    fields = dict(
        id=2,
        text="13/16",
        normalized="13/16",
        insertion=(0.0, 0.0),
        bbox=(0.0, 0.0, 5.0, 3.0),
        font_size=3.0,
        page_number=1,
        source_bbox_pdf=(0.0, 0.0, 5.0, 3.0),
        source_quad_pdf=None,
        target_quad_model=None,
        advance_width=0.0,
        glyph_height=0.0,
        source_char_layout=_layout("13/16"),
        requires_individual_positioning=True,
    )
    fields.update(overrides)
    return NormalizedText(**fields)


@pytest.mark.parametrize("text", ["3/8", "1/2", "13/16", "1/4"])
def test_ordinary_fraction_shaped_span_stays_on_the_regular_ladder(text: str) -> None:
    assert _positioned_fraction_layout(_ordinary_span(text)) is None


@pytest.mark.parametrize("fault", [{"advance_width": 2.5}, {"glyph_height": 1.0}])
def test_merger_fraction_with_invented_aggregate_metrics_still_fails_closed(fault: dict) -> None:
    with pytest.raises(_RepresentationImpossible):
        _positioned_fraction_layout(_merger_fraction(**fault))


@pytest.mark.parametrize("text_mode", ["text", "glyphs", "geometry"])
def test_plain_fraction_label_page_converts_in_every_text_mode(tmp_path, text_mode: str) -> None:
    pdf_path = tmp_path / "plain-fraction-label.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=200)
    page.draw_line((20, 100), (280, 100))
    page.insert_text((120, 90), "3/8", fontsize=10)
    page.insert_text((60, 150), "PLATE", fontsize=10)
    pdf.save(str(pdf_path))
    pdf.close()

    run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
    labels = [item for item in run.extraction.pages[0].page_data.text_items if item.text == "3/8"]
    assert labels, "the plain fraction label must be extracted as its own text item"
    assert all(item.requires_individual_positioning for item in labels)

    output = tmp_path / f"plain-fraction-{text_mode}.dxf"
    result = export_to_dxf(
        run.extraction,
        str(output),
        DxfExportOptions(include_images=False, text_mode=text_mode),
    )
    assert output.exists() and output.stat().st_size > 0
    assert result is not None


def test_quad_frame_accepts_pdf_float_noise() -> None:
    # E2 markup 1/4 numerator: ~5e-6 mm dot product on a 3 mm glyph.
    quad = (
        (0.0, 0.0),
        (1.5297515869140739, 1.516125394118717e-06),
        (1.5297515869140739, 1.516125394118717e-06 - 3.073217444106774),
        (0.0, -3.073217444106774),
    )
    width, height, rotation = _quad_frame(quad)
    assert width == pytest.approx(1.5297515869140739, rel=1e-9)
    assert height == pytest.approx(3.073217444106774, rel=1e-9)
    assert abs(rotation) < 0.001


def test_quad_frame_rotation_noise_matches_zero_item_rotation() -> None:
    width, height, rotation = _quad_frame(
        (
            (0.0, 0.0),
            (1.5297515869140739, 1.516125394118717e-06),
            (1.5297515869140739, 1.516125394118717e-06 - 3.073217444106774),
            (0.0, -3.073217444106774),
        )
    )
    rotation_delta = (rotation - 0.0 + 180.0) % 360.0 - 180.0
    assert abs(rotation_delta) < 0.05


def test_quad_frame_rejects_visible_italic_shear() -> None:
    shear = 0.5
    quad = (
        (shear, 0.0),
        (1.0 + shear, 0.0),
        (1.0, -3.0),
        (0.0, -3.0),
    )
    with pytest.raises(_RepresentationImpossible, match="unsupported shear"):
        _quad_frame(quad)

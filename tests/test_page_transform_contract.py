from __future__ import annotations

import math
from pathlib import Path

import pytest

fitz = pytest.importorskip("pymupdf")

from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.importer import apply_uniform_scale
from pdfcadcore.primitive_extractor import MM_PER_PT, _extract_text, extract_page


_CROP = fitz.Rect(20.0, 10.0, 180.0, 90.0)
_RAW_PAGE_WIDTH = 160.0
_RAW_PAGE_HEIGHT = 80.0


def _write_transform_repro(
    path: Path,
    *,
    rotation: int = 0,
    user_unit: float = 1.0,
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200.0, height=100.0)
    page.draw_line((30.0, 20.0), (80.0, 40.0), color=(1.0, 0.0, 0.0))
    page.insert_text((30.0, 50.0), "  A B  ", fontsize=10.0)
    page.insert_text((30.0, 70.0), "   ", fontsize=10.0)
    page.set_cropbox(_CROP)
    page.set_rotation(rotation)
    if user_unit != 1.0:
        doc.xref_set_key(page.xref, "UserUnit", str(user_unit))
    doc.save(path)
    doc.close()


def _display_point(
    point: tuple[float, float],
    rotation: int,
    user_unit: float = 1.0,
) -> tuple[float, float]:
    x = point[0] * user_unit
    y = point[1] * user_unit
    width = _RAW_PAGE_WIDTH * user_unit
    height = _RAW_PAGE_HEIGHT * user_unit
    if rotation == 0:
        return x, y
    if rotation == 90:
        return height - y, x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return y, width - x
    raise AssertionError(f"unexpected test rotation: {rotation}")


def _model_point(
    point: tuple[float, float],
    rotation: int,
    user_unit: float = 1.0,
) -> tuple[float, float]:
    x, y = _display_point(point, rotation, user_unit)
    display_height = (
        _RAW_PAGE_WIDTH if rotation in {90, 270} else _RAW_PAGE_HEIGHT
    ) * user_unit
    return x * MM_PER_PT, (display_height - y) * MM_PER_PT


def _first_span(page):
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text") == "  A B  ":
                    return line, span
    raise AssertionError("expected source span was not emitted by PyMuPDF")


@pytest.mark.parametrize(
    ("rotation", "expected_size", "expected_text_rotation"),
    [
        (0, (160.0, 80.0), 0.0),
        (90, (80.0, 160.0), -90.0),
        (180, (160.0, 80.0), 180.0),
        (270, (80.0, 160.0), 90.0),
    ],
)
@pytest.mark.parametrize("user_unit", [1.0, 2.0])
def test_cropbox_and_rotate_transform_page_geometry_text_and_quad_once(
    tmp_path: Path,
    rotation: int,
    expected_size: tuple[float, float],
    expected_text_rotation: float,
    user_unit: float,
) -> None:
    pdf_path = tmp_path / f"crop-userunit{user_unit}-rotate-{rotation}.pdf"
    _write_transform_repro(
        pdf_path,
        rotation=rotation,
        user_unit=user_unit,
    )

    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        page_data = extract_page(
            page,
            page_num=1,
            scale=1.0,
            flip_y=True,
            detect_arcs=False,
        )
        line, span = _first_span(page)
        raw_quad = fitz.recover_span_quad(line["dir"], span)
    finally:
        doc.close()

    assert (page_data.width, page_data.height) == pytest.approx(
        tuple(value * user_unit * MM_PER_PT for value in expected_size)
    )
    assert len(page_data.primitives) == 1
    assert page_data.primitives[0].points == pytest.approx(
        [
            _model_point((10.0, 10.0), rotation, user_unit),
            _model_point((60.0, 30.0), rotation, user_unit),
        ]
    )

    # Leading/trailing spaces and a whitespace-only positioned run are source
    # content. Empty spans, if a PDF engine emits one, must not become "None".
    assert [item.text for item in page_data.text_items] == ["  A B  ", "   "]
    assert [item.id for item in page_data.text_items] == [1, 2]
    text = page_data.text_items[0]
    assert text.insertion == pytest.approx(
        _model_point((10.0, 40.0), rotation, user_unit)
    )
    rotation_delta = (text.rotation - expected_text_rotation + 180.0) % 360.0 - 180.0
    assert rotation_delta == pytest.approx(0.0)

    raw_points = [raw_quad.ul, raw_quad.ur, raw_quad.lr, raw_quad.ll]
    # PyMuPDF coordinates are already crop-local. Convert them back to the
    # unit=1 raw crop space before applying the independent expected mapping.
    expected_quad = [
        _model_point(
            (float(point.x) / user_unit, float(point.y) / user_unit),
            rotation,
            user_unit,
        )
        for point in raw_points
    ]
    assert text.target_quad_model == pytest.approx(expected_quad)
    assert text.advance_width == pytest.approx(
        math.dist(expected_quad[0], expected_quad[1])
    )


def test_userunit_scales_crop_space_before_single_page_rotation(tmp_path: Path) -> None:
    pdf_path = tmp_path / "crop-userunit2-rotate90.pdf"
    _write_transform_repro(pdf_path, rotation=90, user_unit=2.0)

    doc = fitz.open(pdf_path)
    try:
        page_data = extract_page(
            doc[0],
            page_num=1,
            scale=1.0,
            flip_y=True,
            detect_arcs=False,
        )
    finally:
        doc.close()

    assert (page_data.width, page_data.height) == pytest.approx(
        (160.0 * MM_PER_PT, 320.0 * MM_PER_PT)
    )
    assert page_data.primitives[0].points == pytest.approx(
        [
            _model_point((10.0, 10.0), 90, 2.0),
            _model_point((60.0, 30.0), 90, 2.0),
        ]
    )
    text = page_data.text_items[0]
    assert text.insertion == pytest.approx(_model_point((10.0, 40.0), 90, 2.0))
    assert text.font_size == pytest.approx(20.0 * MM_PER_PT)
    assert text.advance_width is not None
    assert text.advance_width == pytest.approx(2.0 * 27.24 * MM_PER_PT, rel=2e-4)


@pytest.mark.parametrize("factor", [0.1, 10.0])
def test_uniform_scale_scales_text_advance_and_every_target_quad_point(
    tmp_path: Path,
    factor: float,
) -> None:
    pdf_path = tmp_path / f"scale-source-evidence-{factor}.pdf"
    _write_transform_repro(pdf_path, rotation=270)

    doc = fitz.open(pdf_path)
    try:
        page_data = extract_page(
            doc[0],
            page_num=1,
            scale=1.0,
            flip_y=True,
            detect_arcs=False,
        )
    finally:
        doc.close()

    text = page_data.text_items[0]
    assert text.advance_width is not None
    assert text.target_quad_model is not None
    original_advance = text.advance_width
    original_quad = tuple(text.target_quad_model)
    extraction = DocumentExtraction(
        pdf_path=str(pdf_path),
        pages=[ExtractedPage(page_data=page_data, profile=None)],
    )

    apply_uniform_scale(extraction, factor)

    assert text.advance_width == pytest.approx(original_advance * factor)
    assert text.target_quad_model == pytest.approx(
        [(x * factor, y * factor) for x, y in original_quad]
    )


def test_empty_or_none_span_content_is_ignored_without_stringification() -> None:
    class EmptySpanPage:
        @staticmethod
        def get_text(_kind):
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "dir": (1.0, 0.0),
                                "spans": [
                                    {"text": None},
                                    {"text": ""},
                                ],
                            }
                        ],
                    }
                ]
            }

    assert _extract_text(EmptySpanPage(), 100.0, 1, True, 1.0) == []

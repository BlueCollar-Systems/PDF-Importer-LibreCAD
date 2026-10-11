"""The delivered drawing's extents and first view are its sheets.

A content stream may paint past the page box without a clip. That ink stays in
the DXF, but it never enlarges ``$EXTMIN/$EXTMAX``, ``$LIMMIN/$LIMMAX`` or the
``*Active`` viewport: those are the union of the placed page frames, both in a
page checkpoint and in the assembled file the operator opens.

Every fixture is synthetic and generated here.
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox
import pytest

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

import dxf_import_engine
from dxf_import_engine import _assemble_checkpoints
from librecad_pdf_importer.dxf_framing import frame_modelspace, sheet_bounds
from librecad_pdf_importer.exporters.dxf_exporter import export_to_dxf
from librecad_pdf_importer.importer import run_import
from pdfcadcore.import_config import ImportConfig

MM = 25.4 / 72.0
LETTER = (612.0, 792.0)
TABLOID_LANDSCAPE = (1224.0, 792.0)
LETTER_FRAME = (0.0, 0.0, LETTER[0] * MM, LETTER[1] * MM)

# PDF user-space strokes (y down in PyMuPDF's page space), none of them clipped.
DIAGONAL = ((-760.0, 300.0), (1500.0, 500.0))          # far past both side edges
HORIZONTAL = ((-200.0, 600.0), (900.0, 600.0))         # axis-aligned, both sides
VERTICAL = ((306.0, -150.0), (306.0, 1200.0))          # axis-aligned, top and bottom
SLIGHT = ((500.0, 400.0), (660.0, 380.0))              # 17 mm past the right edge
INSIDE = ((72.0, 72.0), (540.0, 720.0))


def _write_pdf(path: Path, pages) -> Path:
    """``pages`` is a list of ``((width, height), [stroke, ...])`` in points."""
    with fitz.open() as document:
        for (width, height), strokes in pages:
            page = document.new_page(width=width, height=height)
            shape = page.new_shape()
            for start, end in strokes:
                shape.draw_line(fitz.Point(*start), fitz.Point(*end))
            shape.finish(color=(0, 0, 0), width=1)
            shape.commit()
        document.save(path)
    return path


def _convert(tmp_path: Path, pages, name: str = "sheets"):
    """The importer window's flow: one checkpoint per page, then the assembly."""
    source = _write_pdf(tmp_path / f"{name}.pdf", pages)
    output = tmp_path / f"{name}.dxf"
    config = ImportConfig.auto()
    config.import_text = False
    config.raster_fallback = False
    dxf_import_engine.convert(str(source), str(output), config=config, resumable=True)
    checkpoints = [
        tmp_path / f"{name}_resume" / f"page_{number:04d}.dxf"
        for number in range(1, len(pages) + 1)
    ]
    assert all(checkpoint.is_file() for checkpoint in checkpoints)
    return ezdxf.readfile(output), [ezdxf.readfile(path) for path in checkpoints]


def _header_bounds(doc):
    extmin, extmax = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    return (extmin[0], extmin[1], extmax[0], extmax[1])


def _visible_bounds(entities):
    box = ezdxf_bbox.extents(entities, fast=False)
    assert box.has_data
    return (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)


def _page_entities(doc, page_number: int):
    prefix = f"page_{page_number:04d}$0$"
    return [
        entity for entity in doc.modelspace()
        if str(entity.dxf.layer).startswith(prefix)
        and not str(entity.dxf.layer).endswith("TEXT_SEARCH")
    ]


def _union(first, second):
    return (min(first[0], second[0]), min(first[1], second[1]),
            max(first[2], second[2]), max(first[3], second[3]))


def assert_sheets_are_the_drawing(doc, sheets) -> None:
    """Header extents, limits and LibreCAD's opening view are exactly ``sheets``."""
    x0, y0, x1, y1 = sheets
    assert tuple(doc.header["$EXTMIN"]) == pytest.approx((x0, y0, 0.0), abs=1e-6)
    assert tuple(doc.header["$EXTMAX"]) == pytest.approx((x1, y1, 0.0), abs=1e-6)
    assert tuple(doc.header["$LIMMIN"])[:2] == pytest.approx((x0, y0), abs=1e-6)
    assert tuple(doc.header["$LIMMAX"])[:2] == pytest.approx((x1, y1), abs=1e-6)
    active = doc.viewports.get("*Active")
    assert len(active) == 1
    view = active[0].dxf
    assert tuple(view.direction) == (0, 0, 1)
    assert tuple(view.target) == (0, 0, 0)
    assert view.view_twist == 0
    assert view.view_mode == 0
    # LibreCAD 2.2 shows, at the saved aspect, the world rectangle whose
    # upper-right corner is twice the saved centre (RS_FilterDXFRW::addVport).
    view_width, view_height = view.height * view.aspect_ratio, view.height
    right, top = 2 * view.center[0], 2 * view.center[1]
    left, bottom = right - view_width, top - view_height
    assert left <= x0 and x1 <= right and bottom <= y0 and y1 <= top
    assert ((left + right) / 2, (bottom + top) / 2) == pytest.approx(
        ((x0 + x1) / 2, (y0 + y1) / 2), abs=1e-6)
    fill = max((x1 - x0) / view_width, (y1 - y0) / view_height)
    assert fill == pytest.approx(1 / 1.1, abs=5e-4)  # 0.909: the sheet plus its margin


# --- the rule itself ------------------------------------------------------

def test_known_sheets_frame_the_drawing_whatever_the_geometry_does():
    sheet = (0.0, 0.0, 215.9, 279.4)
    assert sheet_bounds(sheet, (-268.1, 0.0, 529.2, 279.4)) == sheet
    # No threshold: a small overhang and ink smaller than the sheet alike.
    assert sheet_bounds(sheet, (0.0, 0.0, 216.0, 279.4)) == sheet
    assert sheet_bounds(sheet, (50.0, 50.0, 60.0, 60.0)) == sheet
    assert sheet_bounds(sheet, None) == sheet


@pytest.mark.parametrize("sheets", [
    None,
    (0.0, 0.0, 0.0, 279.4),                      # zero width
    (0.0, 0.0, 215.9, 0.0),                      # zero height
    (float("inf"), float("inf"), float("-inf"), float("-inf")),   # never tracked
    (1e20, 1e20, -1e20, -1e20),                  # DXF's unset sentinel
    (0.0, 0.0, float("nan"), 279.4),
])
def test_without_a_page_frame_the_geometry_frames_the_drawing(sheets):
    geometry = (-5.0, -6.0, 70.0, 80.0)
    assert sheet_bounds(sheets, geometry) == geometry


# --- one page -------------------------------------------------------------

@pytest.mark.parametrize("strokes", [
    [DIAGONAL],
    [HORIZONTAL],
    [VERTICAL],
    [SLIGHT],
    [DIAGONAL, HORIZONTAL, VERTICAL, INSIDE],
], ids=["diagonal", "horizontal", "vertical", "slight-overhang", "all"])
def test_page_checkpoint_extents_are_the_page_frame(tmp_path: Path, strokes):
    source = _write_pdf(tmp_path / "page.pdf", [(LETTER, strokes)])
    run = run_import(str(source), mode="vector", overrides={"import_text": False})
    output = tmp_path / "page.dxf"
    export_to_dxf(run.extraction, str(output))
    assert_sheets_are_the_drawing(ezdxf.readfile(output), LETTER_FRAME)


@pytest.mark.parametrize("strokes", [
    [DIAGONAL],
    [SLIGHT],
    [DIAGONAL, HORIZONTAL, VERTICAL, INSIDE],
], ids=["diagonal", "slight-overhang", "all"])
def test_delivered_single_page_is_framed_by_its_sheet(tmp_path: Path, strokes):
    delivered, checkpoints = _convert(tmp_path, [(LETTER, strokes)])
    assert_sheets_are_the_drawing(checkpoints[0], LETTER_FRAME)
    assert_sheets_are_the_drawing(delivered, LETTER_FRAME)
    # The ink is still delivered at full length; only the framing ignores it.
    ink = _visible_bounds(_page_entities(delivered, 1))
    assert ink[2] > LETTER_FRAME[2] + 10.0
    if DIAGONAL in strokes:
        assert ink[0] == pytest.approx(DIAGONAL[0][0] * MM, abs=0.5)
        assert ink[2] == pytest.approx(DIAGONAL[1][0] * MM, abs=0.5)


# --- several pages --------------------------------------------------------

def _placed_sheets(delivered, checkpoints):
    """Where each page frame landed, from how far its own entities moved."""
    placed = []
    for number, checkpoint in enumerate(checkpoints, start=1):
        frame = _header_bounds(checkpoint)
        before = _visible_bounds(
            entity for entity in checkpoint.modelspace()
            if not str(entity.dxf.layer).endswith("TEXT_SEARCH")
        )
        after = _visible_bounds(_page_entities(delivered, number))
        assert after[0] == pytest.approx(before[0], abs=1e-6)  # left edges aligned
        offset = after[1] - before[1]
        placed.append((frame[0], frame[1] + offset, frame[2], frame[3] + offset))
    return placed


def test_two_pages_with_off_sheet_ink_are_framed_by_both_sheets(tmp_path: Path):
    delivered, checkpoints = _convert(tmp_path, [
        (LETTER, [DIAGONAL, VERTICAL, INSIDE]),
        (LETTER, [HORIZONTAL, VERTICAL, INSIDE]),
    ])
    for checkpoint in checkpoints:
        assert_sheets_are_the_drawing(checkpoint, LETTER_FRAME)
    first, second = _placed_sheets(delivered, checkpoints)
    assert first == pytest.approx(LETTER_FRAME, abs=1e-6)
    assert second[3] < first[1]                      # stacked downward, no overlap
    assert_sheets_are_the_drawing(delivered, _union(first, second))
    # Off-sheet ink is kept, and never lands on the neighbouring sheet.
    first_ink = _visible_bounds(_page_entities(delivered, 1))
    second_ink = _visible_bounds(_page_entities(delivered, 2))
    assert first_ink[0] < -200.0 and first_ink[1] < first[1] - 100.0
    assert second_ink[3] > second[3] + 40.0
    assert first_ink[1] > second_ink[3]
    extents = _header_bounds(delivered)
    assert extents[0] == pytest.approx(0.0, abs=1e-6)
    assert extents[2] == pytest.approx(LETTER_FRAME[2], abs=1e-6)


def test_mixed_page_sizes_are_framed_by_the_union_of_their_sheets(tmp_path: Path):
    delivered, checkpoints = _convert(tmp_path, [
        (TABLOID_LANDSCAPE, [INSIDE, ((-300.0, 100.0), (1500.0, 700.0))]),
        (LETTER, [INSIDE, DIAGONAL]),
        (LETTER, [INSIDE]),
    ])
    wide = (0.0, 0.0, TABLOID_LANDSCAPE[0] * MM, TABLOID_LANDSCAPE[1] * MM)
    assert_sheets_are_the_drawing(checkpoints[0], wide)
    assert_sheets_are_the_drawing(checkpoints[1], LETTER_FRAME)
    assert_sheets_are_the_drawing(checkpoints[2], LETTER_FRAME)
    placed = _placed_sheets(delivered, checkpoints)
    assert placed[0] == pytest.approx(wide, abs=1e-6)
    for upper, lower in zip(placed, placed[1:], strict=False):
        assert lower[3] < upper[1]
    sheets = placed[0]
    for sheet in placed[1:]:
        sheets = _union(sheets, sheet)
    assert sheets[0] == pytest.approx(0.0, abs=1e-6)
    assert sheets[2] == pytest.approx(wide[2], abs=1e-6)
    assert_sheets_are_the_drawing(delivered, sheets)


def test_pages_without_off_sheet_ink_keep_the_regular_stack(tmp_path: Path):
    delivered, checkpoints = _convert(tmp_path, [(LETTER, [INSIDE]), (LETTER, [INSIDE])])
    first, second = _placed_sheets(delivered, checkpoints)
    height = LETTER_FRAME[3]
    assert first == pytest.approx(LETTER_FRAME, abs=1e-6)
    # Gap of 20% of the page height between the sheets, as before.
    assert second == pytest.approx(
        (0.0, -1.2 * height, LETTER_FRAME[2], -0.2 * height), abs=1e-6)
    assert_sheets_are_the_drawing(delivered, (0.0, -1.2 * height, LETTER_FRAME[2], height))


# --- assembly of checkpoints, with and without a saved sheet ---------------

def _hand_checkpoint(path: Path, line, sheet=None) -> Path:
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line(line[0], line[1])
    if sheet is not None:
        frame_modelspace(doc, sheet)
    doc.saveas(path)
    return path


def test_assembly_frames_a_saved_sheet_and_ignores_ink_beyond_it(tmp_path: Path):
    sheet = (0.0, 0.0, 200.0, 100.0)
    first = _hand_checkpoint(tmp_path / "page_0001.dxf", ((-500, 50), (900, 60)), sheet)
    second = _hand_checkpoint(tmp_path / "page_0002.dxf", ((20, -80), (30, 400)), sheet)
    output = tmp_path / "batch.dxf"
    _assemble_checkpoints([first, second], str(output))
    doc = ezdxf.readfile(output)
    # Page 2 occupies y -80..400; its top is put 20% of page 1's height below
    # page 1, so its sheet sits at y -420..-320.
    assert_sheets_are_the_drawing(doc, (0.0, -420.0, 200.0, 100.0))
    lines = list(doc.modelspace().query("LINE"))
    assert [line.dxf.start.x for line in lines] == pytest.approx([-500.0, 20.0])
    assert lines[1].dxf.end.y == pytest.approx(-20.0)


def test_assembly_without_a_saved_sheet_is_framed_by_its_entities(tmp_path: Path):
    first = _hand_checkpoint(tmp_path / "page_0001.dxf", ((-500, 50), (900, 60)))
    output = tmp_path / "batch.dxf"
    _assemble_checkpoints([first], str(output))
    assert _header_bounds(ezdxf.readfile(output)) == pytest.approx(
        (-500.0, 50.0, 900.0, 60.0))


def test_assembly_with_a_zero_area_saved_frame_is_framed_by_its_entities(tmp_path: Path):
    first = _hand_checkpoint(
        tmp_path / "page_0001.dxf", ((-500, 50), (900, 60)), (0.0, 0.0, 0.0, 100.0))
    output = tmp_path / "batch.dxf"
    _assemble_checkpoints([first], str(output))
    assert _header_bounds(ezdxf.readfile(output)) == pytest.approx(
        (-500.0, 0.0, 900.0, 100.0))


def test_the_sheet_rule_is_the_only_framing_decision_in_the_exporter():
    """No second threshold (the former 1.5x clamp) decides the framed bounds."""
    root = Path(__file__).resolve().parents[1]
    exporter = (root / "librecad_pdf_importer" / "exporters" / "dxf_exporter.py").read_text(
        encoding="utf-8")
    engine = (root / "dxf_import_engine.py").read_text(encoding="utf-8")
    for source in (exporter, engine):
        assert source.count("frame_modelspace(") == 1
        assert "sheet_bounds(" in source
    assert "1.5 * frame_w" not in exporter and "1.5 * frame_h" not in exporter

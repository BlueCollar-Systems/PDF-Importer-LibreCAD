"""Whole drawing view and non-overlapping mixed-sheet resume contracts."""
from pathlib import Path

import ezdxf
from ezdxf import bbox
import pymupdf as fitz
import pytest

from dxf_import_engine import _assemble_checkpoints
from librecad_pdf_importer.exporters.dxf_exporter import export_to_dxf
from librecad_pdf_importer.importer import run_import


def assert_framed(doc, bounds):
    x0, y0, x1, y1 = bounds
    assert tuple(doc.header["$EXTMIN"]) == pytest.approx((x0, y0, 0))
    assert tuple(doc.header["$EXTMAX"]) == pytest.approx((x1, y1, 0))
    active = doc.viewports.get("*Active")[0]
    cx, cy = tuple(active.dxf.center)[:2]
    # Reproduce LibreCAD's actual importer, including integer pixel offsets.
    # Standard DXF center assertions previously passed while the native
    # opening view showed only one note from a three-sheet batch.
    for width, height in ((1024, 658), (600, 900), (1800, 600)):
        factor = min(width / (active.dxf.height * active.dxf.aspect_ratio),
                     height / active.dxf.height)
        ox, oy = int(width - 2 * cx * factor), int(height - 2 * cy * factor)
        left, right = -ox / factor, (width - ox) / factor
        bottom, top = -oy / factor, (height - oy) / factor
        assert left <= x0 < x1 <= right
        assert bottom <= y0 < y1 <= top
    assert (2 * cx - active.dxf.height * active.dxf.aspect_ratio / 2,
            2 * cy - active.dxf.height / 2) == pytest.approx(
                ((x0 + x1) / 2, (y0 + y1) / 2))
    assert active.dxf.height <= max(y1 - y0, (x1 - x0) / active.dxf.aspect_ratio) * 1.101
    assert tuple(active.dxf.direction) == (0, 0, 1)
    assert tuple(active.dxf.target) == (0, 0, 0)
    assert active.dxf.view_twist == 0
    assert active.dxf.view_mode == 0


def checkpoint(path, bounds, hidden=False):
    doc = ezdxf.new("R2010")
    x0, y0, x1, y1 = bounds
    doc.modelspace().add_line((x0, y0), (x1, y1))
    if hidden:
        layer = doc.layers.new("P001_TEXT_SEARCH")
        layer.freeze()
        doc.modelspace().add_text("FICTIONAL SEARCH", dxfattribs={
            "insert": (80000, -90000), "height": 10, "layer": layer.dxf.name})
    doc.saveas(path)
    return path


def test_wide_vector_sheet_opens_with_its_entire_width_in_view(tmp_path: Path):
    pdf = tmp_path / "wide.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=900, height=100)
        page.draw_line((5, 5), (895, 95))
        doc.save(pdf)
    run = run_import(str(pdf), mode="vector", overrides={"import_text": False})
    output = tmp_path / "wide.dxf"
    export_to_dxf(run.extraction, str(output))
    doc = ezdxf.readfile(output)
    assert_framed(doc, (0, 0, 900 * 25.4 / 72, 100 * 25.4 / 72))


def test_resume_output_reconstructs_a_tight_whole_batch_view(tmp_path: Path):
    first = checkpoint(tmp_path / "first.dxf", (1000, 2000, 1300, 2100))
    second = checkpoint(tmp_path / "second.dxf", (1000, 2000, 1300, 2100))
    output = tmp_path / "batch.dxf"
    _assemble_checkpoints([first, second], str(output))
    doc = ezdxf.readfile(output)
    assert_framed(doc, (1000, 1880, 1300, 2100))


def test_mixed_page_heights_have_a_gap_instead_of_overlapping(tmp_path: Path):
    first = checkpoint(tmp_path / "short.dxf", (0, 0, 200, 100))
    second = checkpoint(tmp_path / "tall.dxf", (0, 0, 100, 300))
    output = tmp_path / "mixed.dxf"
    _assemble_checkpoints([first, second], str(output))
    doc = ezdxf.readfile(output)
    lines = list(doc.modelspace().query("LINE"))
    assert len(lines) == 2
    first_box, second_box = (bbox.extents([line]) for line in lines)
    assert second_box.extmax.y == pytest.approx(first_box.extmin.y - 20)
    assert second_box.extmax.y - second_box.extmin.y == pytest.approx(300)
    assert_framed(doc, (0, -320, 200, 100))


def test_hidden_search_text_never_inflates_batch_framing(tmp_path: Path):
    first = checkpoint(tmp_path / "hidden.dxf", (10, 20, 210, 120), hidden=True)
    output = tmp_path / "visible.dxf"
    _assemble_checkpoints([first], str(output))
    doc = ezdxf.readfile(output)
    assert len(list(doc.modelspace().query("TEXT"))) == 1
    assert_framed(doc, (10, 20, 210, 120))

"""The importer window's path delivers near-black ink as black and frames by the sheet.

``gui.py`` converts through ``dxf_import_engine.convert(..., resumable=True)``:
one checkpoint per page, then the assembly the operator opens. Both fixes must
hold on that path, not only on the one-shot command-line path:

* Dark neutral ink (#231f20, #191919) on lines, fills and lettering comes out
  as exact black, which LibreCAD draws in its foreground colour on its default
  black canvas. A mid grey (#808080) keeps its colour.
* A stroke painted far past the paper edge stays in the drawing at full
  length, but the file's extents and opening view are the sheet.

Every fixture is synthetic and generated here (fictional job D042, mark EX101).
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezdxf_bbox
import pymupdf
import pytest

import dxf_import_engine
from pdfcadcore.import_config import ImportConfig

MM = 25.4 / 72.0
LETTER_W, LETTER_H = 612.0, 792.0

# (label, 8-bit source ink, expected delivered colour); one row per ink.
INKS = (
    ("rich_black_231f20", (0x23, 0x1F, 0x20), 0x000000),
    ("dark_grey_191919", (0x19, 0x19, 0x19), 0x000000),
    ("black_000000", (0x00, 0x00, 0x00), 0x000000),
    ("mid_grey_808080", (0x80, 0x80, 0x80), 0x808080),
)
ROW_PITCH = 120.0
FIRST_ROW_Y = 120.0


def _row_y(index: int) -> float:
    return FIRST_ROW_Y + index * ROW_PITCH


def _gui_path_convert(source: Path, output: Path, *, import_text: bool = True) -> dict:
    """Exactly how the importer window calls the engine (gui.py worker)."""

    config = ImportConfig.auto()
    config.import_text = import_text
    return dxf_import_engine.convert(
        input_path=str(source),
        output_path=str(output),
        config=config,
        dxf_version="R2010",
        progress_callback=None,
        resumable=True,
        cancel_requested=lambda: False,
        restart_on_resume_mismatch=True,
        librecad_executable="",
    )


def _write_ink_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=LETTER_W, height=LETTER_H)
    for index, (_label, rgb8, _expected) in enumerate(INKS):
        y = _row_y(index)
        ink = tuple(channel / 255.0 for channel in rgb8)
        page.draw_line((72, y), (300, y), color=ink, width=1.0)
        page.draw_rect(pymupdf.Rect(330, y - 14, 380, y + 14), color=None, fill=ink)
        page.insert_text((410, y + 4), "EX101", fontname="helv", fontsize=12, color=ink)
    page.insert_text(
        (72, 740), "D042", fontname="helv", fontsize=10, color=(0, 0, 0)
    )
    document.save(str(path))
    document.close()
    return path


def _own_colour(entity):
    if entity.dxf.hasattr("true_color"):
        return int(entity.dxf.true_color)
    aci = int(entity.dxf.get("color", 256))
    return {0: "BYBLOCK", 256: "BYLAYER"}.get(aci, f"aci{aci}")


def _layer_colour(doc, layer_name):
    layer = doc.layers.get(layer_name)
    if layer.dxf.hasattr("true_color"):
        return int(layer.dxf.true_color)
    return f"layer-aci{layer.color}"


def _resolved_leaves(doc, entities, inherited=None, inherited_layer="0"):
    """Yield ``(leaf, effective colour)`` with nested INSERT/BYBLOCK resolved.

    ``INSERT.virtual_entities`` places each child in world coordinates, so the
    leaves can be told apart by where they sit on the sheet.
    """

    for entity in entities:
        layer = entity.dxf.layer if entity.dxf.layer != "0" else inherited_layer
        colour = _own_colour(entity)
        if colour == "BYBLOCK":
            colour = inherited
        elif colour == "BYLAYER":
            colour = _layer_colour(doc, layer)
        if entity.dxftype() == "INSERT":
            yield from _resolved_leaves(
                doc, entity.virtual_entities(), colour, layer
            )
        else:
            yield entity, colour


def test_gui_path_delivers_near_black_ink_as_exact_black(tmp_path):
    source = _write_ink_pdf(tmp_path / "ink_rows.pdf")
    output = tmp_path / "ink_rows.dxf"
    stats = _gui_path_convert(source, output)
    assert output.is_file()

    doc = ezdxf.readfile(output)
    row_centres_mm = [(LETTER_H - _row_y(i)) * MM for i in range(len(INKS))]
    half_band_mm = ROW_PITCH * MM / 2.0

    seen = defaultdict(lambda: defaultdict(set))
    for leaf, colour in _resolved_leaves(doc, doc.modelspace()):
        box = ezdxf_bbox.extents([leaf], fast=False)
        if not box.has_data:
            continue
        centre_y = box.center.y
        for index, row_y in enumerate(row_centres_mm):
            if abs(centre_y - row_y) <= half_band_mm:
                seen[index][leaf.dxftype()].add(colour)
                break

    for index, (label, _rgb8, expected) in enumerate(INKS):
        kinds = seen[index]
        assert kinds, f"nothing delivered on the {label} row"
        colours = set().union(*kinds.values())
        assert colours == {expected}, (
            f"{label}: delivered colours {sorted(map(str, colours))}, "
            f"expected #{expected:06x}"
        )
        # The line, the fill and the lettering all came through on this row.
        assert {"LWPOLYLINE", "LINE", "POLYLINE"} & set(kinds), (label, dict(kinds))
        assert {"HATCH", "SOLID"} & set(kinds), (label, dict(kinds))

    # The swap is recorded in the page's import report so it can be explained.
    summary = json.loads(
        Path(stats["import_report_path"]).read_text(encoding="utf-8")
    )
    deliveries = []
    for page_report in summary["page_reports"]:
        report = json.loads(Path(page_report).read_text(encoding="utf-8"))
        deliveries.extend((report.get("extra") or {}).get("ink_color_delivery") or ())
    assert deliveries, "the near-black swap is not recorded in the import report"
    sources = {tuple(row["source_rgb"]) for row in deliveries}
    assert (0x23, 0x1F, 0x20) in sources
    assert (0x19, 0x19, 0x19) in sources
    assert all(row["delivered_rgb"] == [0, 0, 0] for row in deliveries)


def test_gui_path_frames_by_the_sheet_when_a_stroke_runs_off_it(tmp_path):
    source = tmp_path / "diagonal_far.pdf"
    document = pymupdf.open()
    page = document.new_page(width=LETTER_W, height=LETTER_H)
    page.draw_rect(pymupdf.Rect(36, 36, 576, 756), color=(0, 0, 0), width=1)
    # Out to three times the page width (1836 pt = 647.7 mm), no clip.
    page.draw_line((300, 300), (3 * LETTER_W, 420), color=(0, 0, 0), width=0.5)
    page.insert_text((72, 740), "D042 EX101", fontname="helv", fontsize=10)
    document.save(str(source))
    document.close()

    output = tmp_path / "diagonal_far.dxf"
    _gui_path_convert(source, output)
    doc = ezdxf.readfile(output)

    sheet_w, sheet_h = LETTER_W * MM, LETTER_H * MM
    extmin, extmax = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    assert extmin[0] == pytest.approx(0.0, abs=0.05)
    assert extmin[1] == pytest.approx(0.0, abs=0.05)
    assert extmax[0] == pytest.approx(sheet_w, abs=0.05)   # 215.9, not 647.7
    assert extmax[1] == pytest.approx(sheet_h, abs=0.05)

    active = doc.viewports.get("*Active")
    assert active, "no *Active viewport"
    assert active[0].dxf.height == pytest.approx(sheet_h * 1.1, abs=0.1)  # 307.3

    # The off-sheet ink is kept at full length; only the framing ignores it.
    visible = [
        entity
        for entity in doc.modelspace()
        if not doc.layers.get(entity.dxf.layer).is_frozen()
    ]
    drawn = ezdxf_bbox.extents(visible, fast=False)
    assert drawn.has_data
    assert drawn.extmax.x == pytest.approx(3 * LETTER_W * MM, abs=1.0)  # 647.7

"""Original PDF paint stays distinct from adaptive CAD foreground ink."""
from pathlib import Path

import ezdxf
from ezdxf.colors import int2rgb
from ezdxf.disassemble import recursive_decompose
import pymupdf
import pytest

from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import
from librecad_pdf_importer.ink_color import PAINT_RULE_FIXED_BLACK_WHITE


def _rgb(entity):
    value = entity.dxf.get("true_color")
    return None if value is None else tuple(int2rgb(value))


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
def test_source_dark_panels_white_masks_and_letters_survive_serialization(tmp_path, deterministic_exact_font, mode):
    source = tmp_path / "source-panels.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=300, height=240)
        # Different dark paints rule out a fixture-specific RGB31 exception.
        for index, rgb in enumerate([(31, 31, 31), (35, 31, 32), (0, 0, 0)]):
            y = 20 + index * 65
            page.draw_rect((20, y, 280, y + 50), color=None, fill=tuple(c / 255 for c in rgb))
            page.insert_text((35, y + 30), "WHITE A", fontsize=15,
                             fontname="BCFixture", fontfile=str(deterministic_exact_font), color=(1, 1, 1))
        # A smaller white mask is real paint, unlike a redundant full-page background.
        page.draw_rect((200, 30, 240, 50), color=None, fill=(1, 1, 1))
        page.insert_text((20, 230), "BLACK A", fontsize=15,
                         fontname="BCFixture", fontfile=str(deterministic_exact_font), color=(0, 0, 0))
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={"text_mode": mode})
    output = tmp_path / "panels.dxf"
    result = export_to_dxf(run.extraction, str(output),
                           DxfExportOptions(text_mode=mode, provenance_opts=run.config))
    doc = ezdxf.readfile(output)
    assert not doc.audit().errors
    assert all(not doc.layers.get(e.dxf.layer).is_off() for e in doc.modelspace())
    fills = [e for e in doc.modelspace() if e.dxftype() == "HATCH"]
    assert sorted(_rgb(e) for e in fills) == [(1, 1, 1), (31, 31, 31), (35, 31, 32), (254, 254, 254)]
    text = [e for e in doc.modelspace() if e.dxf.layer == "P001_TEXT"]
    leaves = list(recursive_decompose(text))
    colors = {_rgb(e) for e in leaves}
    assert (254, 254, 254) in colors and (0, 0, 0) in colors
    assert (255, 255, 255) not in colors
    assert all(row["verified"] and row["final_representation"] == mode for row in result.text_deliveries)
    encoding = [row for row in result.ink_color_deliveries if row["rule"] == PAINT_RULE_FIXED_BLACK_WHITE]
    assert sum(row["text_items"] for row in encoding) == 3
    assert sum(row["fills"] for row in encoding) == 2
    assert all(row["max_channel_error"] == 1 for row in encoding)
    # Preserve source paint data; a host delivery encoding must never rewrite it.
    assert {(tuple(p.fill_color) if p.fill_color is not None else None)
            for p in run.extraction.pages[0].page_data.primitives} >= {(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)}


@pytest.mark.parametrize("case,expected_fills", [("first-white-rectangle", 0),
                                                ("late-white-rectangle", 1),
                                                ("gray254-rectangle", 1),
                                                ("white-triangle", 1)])
def test_only_a_proven_first_white_rectangle_is_redundant_paper(tmp_path, case, expected_fills):
    source = tmp_path / (case + ".pdf")
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        if case == "late-white-rectangle":
            page.draw_line((10, 50), (90, 50), color=(1, 0, 0))
        rgb = (254 / 255,) * 3 if case == "gray254-rectangle" else (1, 1, 1)
        if case == "white-triangle":
            page.draw_polyline([(0, 0), (100, 0), (0, 100)], color=None, fill=rgb, closePath=True)
        else:
            page.draw_rect(page.rect, color=None, fill=rgb)
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={"import_text": False})
    output = tmp_path / (case + ".dxf")
    export_to_dxf(run.extraction, str(output), DxfExportOptions(include_text=False, include_images=False))
    doc = ezdxf.readfile(output)
    fills = list(doc.modelspace().query("HATCH"))
    assert len(fills) == expected_fills
    assert all(_rgb(fill) == (254, 254, 254) for fill in fills)
    assert all(not doc.layers.get(fill.dxf.layer).is_off() for fill in fills)

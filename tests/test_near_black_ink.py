"""Near-black foreground ink is adaptive; source fill paints are independent.

LibreCAD swaps a pen to its foreground colour only when the pen is exactly
black. Distiller's "rich black" (35/31/32) written as that true colour is close
to invisible on LibreCAD's black drawing background, so dark neutral ink --
every channel <= 64 and the channels no further apart than 16 -- is written as
exact black on ordinary lines/text. Source fill paints keep their colors and
exact black/white paint has a reported one-step non-inverting host encoding.

Every fixture is synthetic and generated here.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import ezdxf
from ezdxf.colors import int2rgb
from ezdxf.disassemble import recursive_decompose
import pytest

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

import dxf_import_engine
import dxf_text_builder
from librecad_pdf_importer import ink_color
from librecad_pdf_importer.exporters import dxf_exporter
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import, write_import_report
from pdfcadcore.import_config import ImportConfig

RICH_BLACK = (35, 31, 32)       # 231F20
DARK_BLUE = (31, 56, 99)        # 1F3863
RED = (255, 0, 0)
BLACK = (0, 0, 0)


def _unit(rgb8):
    return tuple(channel / 255.0 for channel in rgb8)


def _true_color(rgb8):
    attribs = {}
    dxf_exporter._apply_color(attribs, _unit(rgb8))
    return tuple(int2rgb(attribs["true_color"]))


# ---------------------------------------------------------------- the rule ----

@pytest.mark.parametrize("source", [
    BLACK,
    RICH_BLACK,
    (64, 64, 64),        # darkest channel limit
    (64, 48, 48),        # widest neutral spread
    (16, 0, 0),
    (0, 0, 16),
    (48, 64, 56),
    (1, 1, 1),
])
def test_dark_neutral_ink_is_written_as_exact_black(source):
    assert _true_color(source) == BLACK
    assert ink_color.delivered_rgb8(*source) == BLACK


@pytest.mark.parametrize("source", [
    (65, 65, 65),        # one step lighter than the limit
    (65, 64, 64),
    (64, 47, 47),        # one step wider than the neutral spread
    (17, 0, 0),
    (0, 0, 17),
    DARK_BLUE,
    (60, 0, 0),          # dark red
    (0, 64, 0),          # dark green
    (96, 96, 96),
    (128, 128, 128),
    RED,
    (242, 242, 242),     # pale wash keeps its colour (near-white rule is separate)
])
def test_other_ink_keeps_its_colour(source):
    assert _true_color(source) == source
    assert ink_color.delivered_rgb8(*source) == source


def test_white_is_noninverting_paint_and_near_white_stays_source_colored():
    assert _true_color((255, 255, 255)) == (254, 254, 254)
    assert _true_color((250, 250, 250)) == (250, 250, 250)
    assert _true_color((249, 249, 249)) == (249, 249, 249)


def test_delivered_ink_leaves_every_other_colour_object_alone():
    red, black, blue = _unit(RED), (0.0, 0.0, 0.0), _unit(DARK_BLUE)
    assert ink_color.delivered_ink(None) is None
    assert ink_color.delivered_ink(red) is red
    assert ink_color.delivered_ink(black) is black
    assert ink_color.delivered_ink(blue) is blue
    assert ink_color.delivered_ink(_unit(RICH_BLACK)) == (0.0, 0.0, 0.0)
    assert ink_color.delivered_ink(list(_unit(RICH_BLACK))) == (0.0, 0.0, 0.0)
    assert ink_color.is_remapped_near_black(_unit(RICH_BLACK)) is True
    assert ink_color.is_remapped_near_black(black) is False
    assert ink_color.is_remapped_near_black(None) is False


def test_native_text_attributes_follow_the_same_rule():
    def true_color(rgb8):
        item = SimpleNamespace(color=_unit(rgb8), rotation=0.0)
        attribs = dxf_text_builder._base_attributes(
            item, layer_name="TEXT", height=2.0, insert=(0.0, 0.0),
            is_r12=False, style_name="Standard",
        )
        return tuple(int2rgb(attribs["true_color"]))

    assert true_color(RICH_BLACK) == BLACK
    assert true_color(BLACK) == BLACK
    assert true_color((64, 48, 48)) == BLACK
    assert true_color((65, 65, 65)) == (65, 65, 65)
    assert true_color(DARK_BLUE) == DARK_BLUE
    assert true_color(RED) == RED
    assert true_color((255, 255, 255)) == (254, 254, 254)


def test_r12_positioned_colour_contract_binds_near_black_as_black():
    def contract(rgb8):
        item = SimpleNamespace(color=_unit(rgb8), rotation=0.0)
        return dxf_text_builder._positioned_r12_color_contract(item)

    black_attribs, black_evidence = contract(BLACK)
    attribs, evidence = contract(RICH_BLACK)
    assert attribs == black_attribs
    assert evidence == {
        **black_evidence,
        "r12_ink_rule": ink_color.INK_RULE_NEAR_BLACK,
        "r12_observed_source_color_rgb": list(RICH_BLACK),
    }
    assert "r12_ink_rule" not in black_evidence
    with pytest.raises(dxf_text_builder._R12ColorImpossible):
        contract(DARK_BLUE)


# --------------------------------------------------------- a whole page ----

def _write_page(path: Path, font: Path, ink) -> Path:
    """Strokes, a fill and outline text in ``ink``; dark-blue text; red markup."""
    with fitz.open() as document:
        page = document.new_page(width=300, height=200)
        shape = page.new_shape()
        shape.draw_line(fitz.Point(20, 20), fitz.Point(280, 20))
        shape.draw_line(fitz.Point(20, 30), fitz.Point(280, 60))
        shape.finish(color=_unit(ink), width=1)
        shape.draw_rect(fitz.Rect(20, 80, 80, 120))
        shape.finish(color=None, fill=_unit(ink))
        shape.draw_line(fitz.Point(20, 150), fitz.Point(280, 170))
        shape.finish(color=_unit(RED), width=1)
        shape.commit()
        page.insert_text((100, 110), "AH", fontsize=20, fontname="BCFixture",
                         fontfile=str(font), color=_unit(ink))
        page.insert_text((180, 110), "HA", fontsize=20, fontname="BCFixture",
                         fontfile=str(font), color=_unit(DARK_BLUE))
        document.save(path)
    return path


def _export(tmp_path: Path, font: Path, ink, name: str, dxf_version: str = "R2010"):
    source = _write_page(tmp_path / f"{name}.pdf", font, ink)
    run = run_import(str(source), mode="vector", overrides={"text_mode": "glyphs"})
    output = tmp_path / f"{name}-{dxf_version}.dxf"
    result = export_to_dxf(
        run.extraction, str(output),
        DxfExportOptions(text_mode="glyphs", dxf_version=dxf_version, provenance_opts=run.config),
    )
    return ezdxf.readfile(output), result, run, output


def _rgb(entity):
    value = entity.dxf.get("true_color")
    return None if value is None else tuple(int2rgb(value))


def _signature(doc):
    """Everything that decides how the page is drawn, without handles or names."""
    layers = sorted(
        (layer.dxf.name, layer.dxf.color, layer.dxf.get("true_color"),
         layer.is_off(), layer.is_frozen())
        for layer in doc.layers
    )
    entities = [
        (entity.dxftype(), entity.dxf.layer, entity.dxf.get("color"), entity.dxf.get("true_color"))
        for entity in doc.modelspace()
    ]
    leaves = [
        (entity.dxftype(), entity.dxf.get("color"), entity.dxf.get("true_color"))
        for entity in recursive_decompose(doc.modelspace())
    ]
    return layers, entities, leaves


def test_rich_black_page_is_delivered_as_black_and_colours_stay(tmp_path, deterministic_exact_font):
    doc, result, _run, _output = _export(tmp_path, deterministic_exact_font, RICH_BLACK, "rich")
    assert all(row["verified"] and row["final_representation"] == "glyphs"
               for row in result.text_deliveries)

    layer_names = {layer.dxf.name for layer in doc.layers}
    assert "P001_RGB_000_000_000" in layer_names
    assert "P001_RGB_035_031_032" in layer_names
    assert "P001_RGB_255_000_000" in layer_names
    assert doc.layers.get("P001_RGB_000_000_000").dxf.true_color == 0

    black_layer = [e for e in doc.modelspace() if e.dxf.layer == "P001_RGB_000_000_000"]
    assert sorted(e.dxftype() for e in black_layer) == ["LINE", "LWPOLYLINE"]
    assert all(_rgb(e) == BLACK for e in black_layer)
    hatch = next(e for e in doc.modelspace() if e.dxftype() == "HATCH")
    assert _rgb(hatch) == RICH_BLACK
    assert hatch.dxf.color == dxf_exporter._nearest_r12_aci(_unit(RICH_BLACK))

    red = [e for e in doc.modelspace() if e.dxf.layer == "P001_RGB_255_000_000"]
    assert len(red) == 1 and _rgb(red[0]) == RED

    inserts = [e for e in doc.modelspace() if e.dxftype() == "INSERT"]
    assert sorted(_rgb(e) for e in inserts) == [BLACK, DARK_BLUE]
    companions = [e for e in doc.modelspace() if e.dxf.layer == "P001_TEXT_SEARCH"]
    assert sorted(_rgb(e) for e in companions) == [BLACK, DARK_BLUE]

    visible = [
        e for e in doc.modelspace()
        if not doc.layers.get(e.dxf.layer).is_frozen() and not doc.layers.get(e.dxf.layer).is_off()
    ]
    colours = {_rgb(e) for e in recursive_decompose(visible)}
    assert colours == {BLACK, RICH_BLACK, DARK_BLUE, RED}


@pytest.mark.parametrize("dxf_version", ["R2010", "R12"])
def test_rich_black_line_and_text_equal_black_but_fills_keep_source(tmp_path, deterministic_exact_font, dxf_version):
    rich, rich_result, _run, _out = _export(
        tmp_path, deterministic_exact_font, RICH_BLACK, "rich", dxf_version)
    black, black_result, _run, _out = _export(
        tmp_path, deterministic_exact_font, BLACK, "black", dxf_version)

    def ink_colors(doc):
        return [(_rgb(e), e.dxf.get("color")) for e in doc.modelspace()
                if e.dxftype() in {"LINE", "LWPOLYLINE", "POLYLINE", "INSERT", "TEXT"}]
    assert ink_colors(rich) == ink_colors(black)
    assert rich_result.entity_count == black_result.entity_count
    if dxf_version == "R12":
        assert black_result.ink_color_deliveries == []
    else:
        assert black_result.ink_color_deliveries[0]["delivered_rgb"] == [1, 1, 1]
    assert len(rich_result.ink_color_deliveries) == 1


def test_report_names_the_replaced_source_colour(tmp_path, deterministic_exact_font):
    _doc, result, run, output = _export(tmp_path, deterministic_exact_font, RICH_BLACK, "rich")
    expected = [{
        "rule": ink_color.INK_RULE_NEAR_BLACK,
        "source_page_number": 1,
        "source_rgb": list(RICH_BLACK),
        "delivered_rgb": [0, 0, 0],
        "strokes": 2,
        "fills": 0,
        "text_items": 1,
    }]
    assert result.ink_color_deliveries == expected

    report_path = write_import_report(run, str(output.with_name("rich_import_report.json")))
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["extra"]["ink_color_delivery"] == expected


def test_report_names_exact_black_fill_host_encoding(tmp_path, deterministic_exact_font):
    _doc, result, run, output = _export(tmp_path, deterministic_exact_font, BLACK, "black")
    expected = [{"rule": ink_color.PAINT_RULE_FIXED_BLACK_WHITE,
                 "source_page_number": 1, "source_rgb": [0, 0, 0],
                 "delivered_rgb": [1, 1, 1], "max_channel_error": 1,
                 "strokes": 0, "fills": 1, "text_items": 0}]
    assert result.ink_color_deliveries == expected
    report_path = write_import_report(run, str(output.with_name("black_import_report.json")))
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert report["extra"]["ink_color_delivery"] == expected


def test_resume_identity_covers_the_ink_rule(monkeypatch):
    """A page checkpoint written under another ink rule is never resumed."""
    config = ImportConfig.auto()
    first, payload = dxf_import_engine._resume_options_identity(config, "R2010")
    assert payload["ink_color_rule"] == ink_color.rule_identity()
    monkeypatch.setattr(ink_color, "NEAR_BLACK_MAX_CHANNEL", 32)
    second, _payload = dxf_import_engine._resume_options_identity(config, "R2010")
    assert second != first

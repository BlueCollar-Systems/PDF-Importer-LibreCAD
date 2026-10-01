"""Valid subsets with empty reference letters retain exact em-sized outlines."""
from io import BytesIO

import ezdxf
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
import pymupdf as fitz
import pytest

import dxf_text_builder as builder
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import

SCALE = 25.4 / 72.0


@pytest.mark.parametrize("mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("frame", ["isotropic", "sheared", "rotated"])
@pytest.mark.parametrize("text", ["BB", "B B"])
def test_missing_reference_letters_keep_original_outline_and_affine(tmp_path, deterministic_exact_font, mode, frame, text):
    font = TTFont(deterministic_exact_font)
    for char in "Axp":
        name = font.getBestCmap()[ord(char)]
        font["glyf"][name] = TTGlyphPen(None).glyph()
        font["hmtx"].metrics[name] = (0, 0)
    payload = BytesIO()
    font.save(payload)
    font.close()
    source, output = tmp_path / "subset.pdf", tmp_path / "subset.dxf"
    matrix = {"isotropic": (12, 0, 0, 12), "sheared": (12, 0, 4, 20),
              "rotated": (0, 12, -20, 4)}[frame]
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=150)
        page.insert_font(fontname="Source", fontbuffer=payload.getvalue())
        page.insert_text((30, 100), text, fontname="Source", fontsize=1)
        xref = page.get_contents()[0]
        stream = pdf.xref_stream(xref)
        assert b"1 0 0 1 30 50 Tm" in stream
        pdf.update_stream(xref, stream.replace(b"1 0 0 1 30 50 Tm",
                         (" ".join(map(str, matrix)) + " 30 50 Tm").encode()))
        pdf.save(source)
    run = run_import(str(source), mode="vector", overrides={"pages": "1", "text_mode": mode})
    item = run.extraction.pages[0].page_data.text_items[0]
    assert item.text == text and item.font_failure is None
    result = export_to_dxf(run.extraction, str(output), DxfExportOptions(include_images=False, text_mode=mode))
    delivery = result.text_deliveries[0]
    assert delivery["verified"] is True
    assert delivery["final_representation"] == mode
    assert delivery["attempts"][-1]["evidence"]["outline_engine_coordinate_basis"] == "original_design_units_per_em"
    drawing = ezdxf.readfile(output)
    assert not list(drawing.modelspace().query("IMAGE"))
    visible = [e for e in drawing.modelspace() if not e.dxf.layer.endswith("TEXT_SEARCH")]
    font = TTFont(BytesIO(item.font_asset.usable_bytes))
    glyph_set, cmap, em = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
    bounds = []
    for char in item.source_char_layout:
        ox, oy = char.target_origin
        a, b, c, d = (value * SCALE / em for value in matrix)
        pen = BoundsPen(glyph_set)
        glyph_set[cmap[ord(char.text)]].draw(TransformPen(pen, (a, b, c, d, ox, oy)))
        if pen.bounds is not None:
            bounds.append(pen.bounds)
    font.close()
    expected = (min(b[0] for b in bounds), min(b[1] for b in bounds),
                max(b[2] for b in bounds), max(b[3] for b in bounds))
    assert builder._bbox_tuple(visible) == pytest.approx(expected, abs=2e-5)

"""Raw staggered fractions retain source glyph em frames, not aggregate box fits."""
from dataclasses import replace
from io import BytesIO
import math

import ezdxf
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
import pymupdf as fitz
import pytest

import dxf_text_builder as builder
from librecad_pdf_importer.exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from librecad_pdf_importer.importer import run_import
from pdfcadcore.primitive_extractor import extract_page

SCALE = 25.4 / 72.0


def _visible(drawing) -> list:
    """Modelspace without the hidden search-text companions (frozen P###_TEXT_SEARCH)."""
    return [
        entity
        for entity in drawing.modelspace()
        if not entity.dxf.layer.endswith("TEXT_SEARCH")
    ]


def make_fraction(path, shear=0.0, rotated=False):
    doc = fitz.open()
    page = doc.new_page(width=200, height=150)
    page.insert_text((30, 100), "13/16", fontname="helv", fontsize=1)
    chunks = ["BT /helv 1 Tf"]
    for text, x, y in [("13", 30, 50), ("/", 43.344, 46), ("16", 46.68, 42)]:
        matrix = (0, 12, -20, shear, 180-y, x) if rotated else (12, 0, shear, 20, x, y)
        chunks.append(" ".join(map(str, matrix)) + " Tm (" + text + ") Tj")
    chunks.append("ET")
    doc.update_stream(page.get_contents()[0], " ".join(chunks).encode("ascii"))
    doc.save(path)
    doc.close()


def extracted(path):
    with fitz.open(path) as doc:
        items = extract_page(doc[0], 1).text_items
    return next(item for item in items if item.text == "13/16")


@pytest.mark.parametrize("shear", [0.0, 4.0, -3.0])
def test_original_pdf_metrics_recover_true_axes_and_baselines(tmp_path, shear):
    source = tmp_path / "staggered.pdf"
    make_fraction(source, shear)
    item = extracted(source)
    layout = builder._source_affine_layout(item)
    assert len(layout) == 5
    assert builder._raw_layout_has_multiple_baselines(layout)
    for char in layout:
        x, y = builder._source_character_affine_axes(char)
        assert x == pytest.approx((12*SCALE, 0.0), abs=2e-6)
        assert y == pytest.approx((shear*SCALE, 20*SCALE), abs=2e-6)
        assert char.source_font_size_pdf == pytest.approx(math.sqrt(240), abs=2e-6)
        assert char.source_writing_mode == 0
    assert layout[2].target_origin[1]-layout[0].target_origin[1] == pytest.approx(-4*SCALE)
    assert layout[3].target_origin[1]-layout[0].target_origin[1] == pytest.approx(-8*SCALE)


@pytest.mark.parametrize("mutation", [
    {"source_font_ascender": None}, {"source_font_descender": float("nan")},
    {"source_font_size_pdf": 0.0}, {"source_writing_mode": 1},
    {"source_font_ascender": 2.0}, {"source_origin_pdf": (0.0, 0.0)},
])
def test_missing_or_unbound_metrics_are_runtime_failure_not_impossibility(tmp_path, mutation):
    source = tmp_path / "staggered.pdf"
    make_fraction(source)
    char = extracted(source).source_char_layout[0]
    with pytest.raises(ValueError) as error:
        builder._source_character_affine_axes(replace(char, **mutation))
    assert not isinstance(error.value, builder._RepresentationImpossible)


def test_declared_advance_does_not_stretch_glyph_ink(tmp_path):
    source = tmp_path / "staggered.pdf"
    make_fraction(source, 4.0)
    char = extracted(source).source_char_layout[0]
    def widened(quad):
        ul, ur, lr, ll = quad
        return (ul, tuple(ul[i]+1.8*(ur[i]-ul[i]) for i in range(2)),
                tuple(ll[i]+1.8*(lr[i]-ll[i]) for i in range(2)), ll)
    altered = replace(char, source_quad_pdf=widened(char.source_quad_pdf),
                      target_quad=widened(char.target_quad), advance_width=char.advance_width*1.8)
    before = builder._source_character_affine_axes(char)
    after = builder._source_character_affine_axes(altered)
    assert after[0] == pytest.approx(before[0], abs=1e-10)
    assert after[1] == pytest.approx(before[1], abs=1e-10)


@pytest.mark.parametrize("text_mode", ["glyphs", "geometry"])
@pytest.mark.parametrize("rotated", [False, True])
def test_persisted_raw_fraction_has_source_positions_and_unstretched_ink(tmp_path, text_mode, rotated):
    source = tmp_path / "staggered.pdf"
    make_fraction(source, rotated=rotated)
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    item = next(t for t in run.extraction.pages[0].page_data.text_items if t.text == "13/16")
    output = tmp_path / "staggered.dxf"
    export_to_dxf(run.extraction, str(output), DxfExportOptions(include_images=False, text_mode=text_mode))
    doc = ezdxf.readfile(output)
    if text_mode == "glyphs":
        outer = list(doc.modelspace().query("INSERT"))
        assert len(outer) == 1
        inner = list(doc.blocks[outer[0].dxf.name].query("INSERT"))
        assert len(inner) == 5
        for insert, char in zip(inner, item.source_char_layout, strict=True):
            actual = outer[0].matrix44().transform(insert.dxf.insert)
            assert tuple(actual)[:2] == pytest.approx(char.target_origin, abs=1e-8)
    # This expected ink comes from original font outlines and the public PDF's
    # explicit 12x20 text matrix, independently of the builder's source axes.
    font = TTFont(BytesIO(item.font_asset.usable_bytes))
    glyphset = font.getGlyphSet()
    cmap = font.getBestCmap()
    em = font["head"].unitsPerEm
    expected_points = []
    for char in item.source_char_layout:
        pen = BoundsPen(glyphset)
        glyphset[cmap[ord(char.text)]].draw(pen)
        x0, y0, x1, y1 = pen.bounds
        ox, oy = char.target_origin
        for gx, gy in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            dx, dy = gx/em*12*SCALE, gy/em*20*SCALE
            expected_points.append((ox-dy, oy+dx) if rotated else (ox+dx, oy+dy))
    font.close()
    expected = (min(p[0] for p in expected_points), min(p[1] for p in expected_points),
                max(p[0] for p in expected_points), max(p[1] for p in expected_points))
    actual = builder._bbox_tuple(_visible(doc))
    assert actual == pytest.approx(expected, abs=0.015)


def test_raw_span_rejects_character_size_mismatch_and_incomplete_inventory(tmp_path):
    source = tmp_path / "staggered.pdf"
    make_fraction(source)
    item = extracted(source)
    with pytest.raises(ValueError, match="raw span"):
        builder._source_affine_layout(replace(item, source_char_layout=(
            replace(item.source_char_layout[0], source_font_size_pdf=1.0),
            *item.source_char_layout[1:],
        )))
    with pytest.raises(ValueError, match="inventory"):
        builder._source_affine_layout(replace(item, source_char_layout=item.source_char_layout[:-1]))


@pytest.mark.parametrize("text", ["x1", "A B"])
@pytest.mark.parametrize("text_mode", ["glyphs", "geometry"])
def test_ordinary_anisotropic_string_preserves_full_source_glyph_em(tmp_path, text, text_mode):
    source = tmp_path / "ordinary.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=200, height=150)
    page.insert_text((30, 100), text, fontsize=1, fontname="helv")
    pdf.update_stream(page.get_contents()[0], f"BT /helv 1 Tf 12 0 0 20 30 50 Tm ({text}) Tj ET".encode())
    pdf.save(source)
    pdf.close()
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    item = next(t for t in run.extraction.pages[0].page_data.text_items if t.text == text)
    output = tmp_path / "ordinary.dxf"
    export_to_dxf(run.extraction, str(output), DxfExportOptions(include_images=False, text_mode=text_mode))
    doc = ezdxf.readfile(output)
    font = TTFont(BytesIO(item.font_asset.usable_bytes))
    glyphset, cmap, em = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
    points = []
    for char in item.source_char_layout:
        pen = BoundsPen(glyphset)
        glyphset[cmap[ord(char.text)]].draw(pen)
        if pen.bounds is None:
            assert char.text.isspace()
            continue
        x0, y0, x1, y1 = pen.bounds
        ox, oy = char.target_origin
        points += [(ox+x0/em*12*SCALE, oy+y0/em*20*SCALE),
                   (ox+x1/em*12*SCALE, oy+y1/em*20*SCALE)]
    expected = (min(p[0] for p in points), min(p[1] for p in points),
                max(p[0] for p in points), max(p[1] for p in points))
    assert builder._bbox_tuple(_visible(doc)) == pytest.approx(expected, abs=.015)
    font.close()


def test_unavailable_optional_metric_api_preserves_actual_source_quads(tmp_path, monkeypatch):
    from pdfcadcore.primitive_extractor import _raw_text_with_source_quads

    source = tmp_path / "metrics-unavailable.pdf"
    make_fraction(source, shear=4.0)
    with fitz.open(source) as doc:
        before = _raw_text_with_source_quads(doc[0])
        def unavailable(_font):
            raise AttributeError("older wrapper has no original-font metric getter")
        monkeypatch.setattr(fitz.mupdf, "ll_fz_font_ascender", unavailable)
        after = _raw_text_with_source_quads(doc[0])
    def chars(raw):
        return [c for b in raw["blocks"] if b["type"] == 0
                for line in b["lines"] for span in line["spans"] for c in span["chars"]]
    original, retained = chars(before), chars(after)
    assert len(original) == len(retained) == 5
    for a, b in zip(original, retained, strict=True):
        assert b["c"] == a["c"] and b["origin"] == a["origin"]
        assert b["quad"] == a["quad"]
        assert all(key not in b for key in (
            "source_font_size_pdf", "source_font_ascender",
            "source_font_descender", "source_writing_mode",
        ))


@pytest.mark.parametrize("text_mode", ["glyphs", "geometry"])
def test_synthetic_source_space_retains_missing_id_and_exact_zero_ink(tmp_path, text_mode):
    source = tmp_path / "synthetic-space.pdf"
    pdf = fitz.open()
    page = pdf.new_page(width=200, height=150)
    page.insert_text((30, 100), "AB", fontsize=1, fontname="helv")
    pdf.update_stream(page.get_contents()[0], b"BT /helv 1 Tf 12 0 0 20 30 50 Tm (A) Tj 12 0 0 20 42 50 Tm (B) Tj ET")
    pdf.save(source)
    pdf.close()
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    item = next(t for t in run.extraction.pages[0].page_data.text_items if t.text == "A B")
    assert item.source_char_layout[1].glyph_id is None
    output = tmp_path / "synthetic-space.dxf"
    result = export_to_dxf(run.extraction, str(output), DxfExportOptions(include_images=False, text_mode=text_mode))
    delivered = result.text_deliveries[0]
    assert delivered["final_representation"] == text_mode
    evidence = delivered["attempts"][-1]["evidence"]
    assert evidence["positioned_character_text"] == ["A", " ", "B"]
    assert evidence["positioned_source_glyph_ids"][1] is None
    assert evidence["positioned_character_local_bboxes"][1] == [0.0]*4
    assert ezdxf.readfile(output).modelspace()
    assert result is not None


def test_missing_space_glyph_id_requires_exact_font_zero_ink(tmp_path):
    source = tmp_path / "fraction.pdf"
    make_fraction(source)
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    item = next(t for t in run.extraction.pages[0].page_data.text_items if t.text == "13/16")
    font = TTFont(BytesIO(item.font_asset.usable_bytes))
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap[32] = font.getBestCmap()[ord("A")]
    path = tmp_path / "visible-space.ttf"
    font.save(path)
    font.close()
    char = replace(item.source_char_layout[0], text=" ", glyph_id=None)
    resolution = builder._ExactFontResolution(source_name="fixture", filename=str(path), exact=True)
    with pytest.raises(builder._RepresentationImpossible, match="visible exact-font ink"):
        builder._positioned_source_glyph_names([char], resolution)


@pytest.mark.parametrize("page_height", [500.0, 2000.0])
@pytest.mark.parametrize("scale", [0.25, 1.0, 10.0])
def test_page_flip_preserves_original_coordinate_roundoff_budget(page_height, scale):
    pdf = fitz.open()
    page = pdf.new_page(width=100, height=page_height)
    page.insert_text((2, page_height-2.37), "A", fontsize=9, fontname="helv")
    item = extract_page(page, 1, scale=scale).text_items[0]
    char = item.source_char_layout[0]
    before = (char.source_quad_pdf, char.target_quad, char.target_origin)
    builder._source_affine_layout(item)
    assert (char.source_quad_pdf, char.target_quad, char.target_origin) == before
    with pytest.raises(ValueError, match="baseline"):
        builder._source_character_affine_axes(replace(
            char, target_origin=(char.target_origin[0], char.target_origin[1]+0.01*scale)))
    pdf.close()


@pytest.mark.parametrize("failure", ["no_filename", "missing_asset", "invalid_asset", "glyph_inventory_error"])
def test_unavailable_exact_font_inspection_is_runtime_not_source_impossibility(tmp_path, monkeypatch, failure):
    source = tmp_path / "font-runtime.pdf"
    make_fraction(source)
    char = extracted(source).source_char_layout[0]
    font_path = tmp_path / "unavailable.ttf"
    if failure == "invalid_asset":
        font_path.write_bytes(b"invalid font fixture")
    if failure == "glyph_inventory_error":
        class FontInventory:
            def getBestCmap(self): return {ord(char.text): "one"}
            def getGlyphID(self, name): raise OSError("temporary font inventory read failure")
            def close(self): pass
        monkeypatch.setattr("fontTools.ttLib.TTFont", lambda *a, **k: FontInventory())
    resolution = builder._ExactFontResolution(
        source_name="fixture", filename="" if failure == "no_filename" else str(font_path), exact=True)
    with pytest.raises(ValueError) as error:
        builder._positioned_source_glyph_names([char], resolution)
    assert not isinstance(error.value, builder._RepresentationImpossible)


@pytest.mark.parametrize("visible_space, engine_path_count", [(True, 0), (True, 2), (False, 2)])
def test_valid_id_space_cannot_hide_visible_or_multiple_engine_paths(tmp_path, monkeypatch, visible_space, engine_path_count):
    from types import SimpleNamespace

    source = tmp_path / "space-ink.pdf"
    make_fraction(source)
    run = run_import(str(source), mode="vector", overrides={"pages": "1"})
    item = next(t for t in run.extraction.pages[0].page_data.text_items if t.text == "13/16")
    font = TTFont(BytesIO(item.font_asset.usable_bytes))
    name = font.getBestCmap()[ord("A") if visible_space else 32]
    for table in font["cmap"].tables:
        if table.isUnicode(): table.cmap[32] = name
    glyph_id = font.getGlyphID(name)
    font_path = tmp_path / "space-program.ttf"
    font.save(font_path)
    font.close()
    char = replace(item.source_char_layout[0], text=" ", glyph_id=glyph_id)
    resolution = builder._ExactFontResolution(source_name="fixture", filename=str(font_path), exact=True)
    empty = set()
    assert builder._positioned_source_glyph_names([char], resolution, empty_glyph_names=empty) == [name]
    assert (name in empty) is (not visible_space)
    monkeypatch.setattr(builder, "_canonical_glyph_path_cache", {})
    engine_name = builder._outline_engine_font_name(str(font_path))
    monkeypatch.setattr(builder.ezdxf_fonts, "get_font_face", lambda _name: SimpleNamespace(filename=engine_name))
    monkeypatch.setattr(builder.text2path, "get_font", lambda _face: SimpleNamespace(
        text_glyph_paths=lambda *args: [object() for _ in range(engine_path_count)]))
    with pytest.raises(ValueError) as error:
        builder._positioned_fraction_glyph_run(item, [char], resolution, is_r12=False, attribs={})
    assert not isinstance(error.value, builder._RepresentationImpossible)
    assert "multiple paths" in str(error.value) if engine_path_count > 1 else "visible exact-font space" in str(error.value)

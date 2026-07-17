from __future__ import annotations

from collections import Counter
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from fontTools.ttLib import TTFont
from fontTools.cffLib import CFFFontSet

from pdfcadcore import embedded_fonts
from pdfcadcore.embedded_fonts import (
    EmbeddedFontCatalog,
    ExactFontSourceImpossible,
    _cff_to_otf,
    _install_pdf_unicode_cmap,
    _usable_font,
)
from pdfcadcore.primitive_extractor import extract_page


WELDING_SYMBOL_CHART = Path(
    r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\Welding-Symbol-Chart.pdf"
)


def _load_font(data: bytes) -> TTFont:
    font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
    # Force all referenced table payloads to be decoded while the in-memory
    # stream is alive. A table-directory-only file is not a usable font asset.
    for tag in font.reader.keys():
        font[tag].compile(font)
    return font


def test_real_chart_maps_each_span_font_to_its_exact_distinct_embedded_asset():
    assert WELDING_SYMBOL_CHART.is_file(), "required supplied regression fixture is missing"

    with pymupdf.open(WELDING_SYMBOL_CHART) as document:
        page_data = extract_page(document[0], page_num=0, detect_arcs=False)

    counts = Counter(item.font_name for item in page_data.text_items)
    assert counts == {
        "Siwa-Regular": 283,
        "Siwa-Bold": 84,
        "ArialMT": 1,
        "MyriadPro-Regular": 4,
    }

    by_name = {}
    for item in page_data.text_items:
        asset = item.font_asset
        assert asset is not None, f"{item.font_name} silently lost its embedded font asset"
        assert asset.span_font_name == item.font_name
        assert asset.base_font_name == item.font_name
        assert asset.page_number == item.page_number
        assert asset.source_xref > 0
        assert asset.source_bytes
        assert asset.usable_bytes
        assert asset.source_sha256
        assert asset.usable_sha256
        assert asset.asset_id == f"sha256:{asset.usable_sha256}"
        assert not hasattr(asset, "path"), "source extraction must not persist embedded fonts"
        assert item.source_bbox_pdf is not None
        assert item.bbox is not None
        assert tuple(item.source_bbox_pdf) != tuple(item.bbox)
        by_name.setdefault(item.font_name, asset)
        assert by_name[item.font_name] is asset

    assert set(by_name) == {
        "Siwa-Regular",
        "Siwa-Bold",
        "ArialMT",
        "MyriadPro-Regular",
    }
    assert {asset.source_xref for asset in by_name.values()} == {5, 6, 7, 8}
    assert len({asset.asset_id for asset in by_name.values()}) == 4
    assert {asset.usable_format for asset in by_name.values()} == {"otf", "ttf"}

    for asset in by_name.values():
        font = _load_font(asset.usable_bytes)
        assert font.getGlyphOrder()


def test_raw_cff_conversion_is_deterministic_and_loadable_without_disk_sidecars():
    with pymupdf.open(WELDING_SYMBOL_CHART) as document:
        first = EmbeddedFontCatalog.from_page(document[0], page_number=0)
        second = EmbeddedFontCatalog.from_page(document[0], page_number=0)

    for font_name in ("Siwa-Regular", "Siwa-Bold", "MyriadPro-Regular"):
        asset_a = first.for_span(font_name)
        asset_b = second.for_span(font_name)
        assert asset_a is not None
        assert asset_b is not None
        assert asset_a.source_format == "cff"
        assert asset_a.usable_format == "otf"
        assert asset_a.usable_bytes == asset_b.usable_bytes
        assert asset_a.usable_sha256 == asset_b.usable_sha256
        assert asset_a.asset_id == asset_b.asset_id
        font = _load_font(asset_a.usable_bytes)
        assert font.getGlyphOrder()
        assert font["head"].created == 2_082_844_800
        assert font["head"].modified == 2_082_844_800
        source_cff = CFFFontSet()
        source_cff.decompile(BytesIO(asset_a.source_bytes), None, isCFF2=False)
        assert list(font["CFF "].cff.topDictIndex[0].FontMatrix) == list(
            source_cff.topDictIndex[0].FontMatrix
        )


def test_unknown_span_font_stays_unresolved_instead_of_substituting_another_asset():
    with pymupdf.open(WELDING_SYMBOL_CHART) as document:
        catalog = EmbeddedFontCatalog.from_page(document[0], page_number=0)

    assert catalog.for_span("Definitely-Not-In-The-PDF") is None
    assert catalog.for_span("Arial") is None


def test_unexpected_embedded_font_programming_error_is_not_swallowed():
    class FontDecodeBomb(Exception):
        pass

    class Document:
        @staticmethod
        def extract_font(xref):
            assert xref == 41
            raise FontDecodeBomb("fixture decoder failure")

    class Page:
        parent = Document()

        @staticmethod
        def get_texttrace():
            return [{"font": "BrokenExact", "chars": [(65, 1, None, None)]}]

        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            return [(41, "cff", "Type1", "ABCDEF+BrokenExact", "F1", "Custom", 0)]

    with pytest.raises(FontDecodeBomb, match="fixture decoder failure"):
        EmbeddedFontCatalog.from_page(Page(), page_number=7)


def test_text_trace_failure_rejects_even_a_font_with_an_existing_cmap():
    with pymupdf.open(WELDING_SYMBOL_CHART) as document:
        arial_bytes = bytes(document.extract_font(7)[3])

    class Document:
        @staticmethod
        def extract_font(xref):
            assert xref == 41
            return ("ABCDEF+ArialMT", "ttf", "TrueType", arial_bytes)

    class Page:
        parent = Document()

        @staticmethod
        def get_texttrace():
            raise RuntimeError("trace inventory unavailable")

        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            return [(41, "ttf", "TrueType", "ABCDEF+ArialMT", "F1", "Custom", 0)]

    catalog = EmbeddedFontCatalog.from_page(Page(), page_number=7)

    assert catalog.for_span("ArialMT") is None
    failure = catalog.failure_for_span("ArialMT")
    assert failure.reason == "page_text_trace_inventory_failed"
    assert failure.error_type == "RuntimeError"
    assert failure.proof_category == "runtime_inventory_unavailable_for_item"


def test_embedded_font_source_size_and_glyph_work_are_bounded(monkeypatch):
    monkeypatch.setattr(embedded_fonts, "MAX_EMBEDDED_FONT_BYTES", 4)
    with pytest.raises(ExactFontSourceImpossible, match="byte limit"):
        _usable_font(b"12345", "ttf", "TooLarge", {})

    monkeypatch.setattr(embedded_fonts, "MAX_EMBEDDED_FONT_BYTES", 100)
    monkeypatch.setattr(embedded_fonts, "MAX_EMBEDDED_FONT_GLYPHS", 1)
    with pytest.raises(ExactFontSourceImpossible, match="glyph limit"):
        embedded_fonts._validate_font_work_bounds(b"font", glyph_count=2)


@pytest.mark.parametrize("failure", [ValueError("bad source"), KeyError("bad key")])
def test_cff_parser_data_failures_become_structured_source_impossibility(failure):
    with patch(
        "fontTools.cffLib.CFFFontSet.decompile",
        side_effect=failure,
    ):
        with pytest.raises(ExactFontSourceImpossible, match="raw CFF parse failed"):
            _cff_to_otf(b"broken cff", "Broken")


def test_cff_parser_memory_failure_is_not_swallowed():
    with patch(
        "fontTools.cffLib.CFFFontSet.decompile",
        side_effect=MemoryError("budget exhausted"),
    ):
        with pytest.raises(MemoryError, match="budget exhausted"):
            _cff_to_otf(b"broken cff", "Broken")


def test_cmap_parser_data_failure_is_structured_but_memory_failure_propagates():
    with patch("fontTools.ttLib.TTFont", side_effect=ValueError("broken sfnt")):
        with pytest.raises(ExactFontSourceImpossible, match="cmap repair failed"):
            _install_pdf_unicode_cmap(b"broken sfnt", {65: 1})
    with patch("fontTools.ttLib.TTFont", side_effect=MemoryError("budget exhausted")):
        with pytest.raises(MemoryError, match="budget exhausted"):
            _install_pdf_unicode_cmap(b"broken sfnt", {65: 1})


def test_page_font_inventory_failure_is_bound_to_each_span_and_never_becomes_absence():
    class InventoryFailure(RuntimeError):
        pass

    class Page:
        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            raise InventoryFailure("transient parent inventory failure")

    catalog = EmbeddedFontCatalog.from_page(Page(), page_number=9)

    failure = catalog.failure_for_span("Exact-Font-Name")
    assert failure.page_number == 9
    assert failure.span_font_name == "Exact-Font-Name"
    assert failure.reason == "page_font_inventory_failed"
    assert failure.error_type == "InventoryFailure"
    assert "transient parent inventory failure" in failure.detail
    assert failure.proof_category == "runtime_inventory_unavailable_for_item"


def test_multiple_different_embedded_programs_with_same_name_remain_ambiguous():
    with pymupdf.open(WELDING_SYMBOL_CHART) as document:
        arial_bytes = document.extract_font(7)[3]
        siwa_asset = EmbeddedFontCatalog.from_page(document[0], page_number=0).for_span(
            "Siwa-Regular"
        )
        assert siwa_asset is not None
        siwa_bytes = siwa_asset.usable_bytes

    programs = {
        1: ("ttf", arial_bytes),
        2: ("otf", siwa_bytes),
        3: ("ttf", arial_bytes),
    }

    class Document:
        @staticmethod
        def extract_font(xref):
            extension, data = programs[xref]
            return ("ABCDEF+SameExactName", extension, "Test", data)

    class Page:
        parent = Document()

        @staticmethod
        def get_texttrace():
            return [{"font": "SameExactName", "chars": [(65, 1, None, None)]}]

        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            return [
                (xref, extension, "Test", "ABCDEF+SameExactName", f"F{xref}", "", 0)
                for xref, (extension, _data) in programs.items()
            ]

    catalog = EmbeddedFontCatalog.from_page(Page(), page_number=4)

    assert catalog.for_span("SameExactName") is None
    assert catalog.failure_for_span("SameExactName").reason == (
        "ambiguous_exact_embedded_font_match"
    )


def test_normalized_text_keeps_raw_source_whitespace_and_exact_font_identity():
    class Rect:
        width = 100.0
        height = 100.0
        x0 = 0.0
        y0 = 0.0

    class Page:
        rect = Rect()
        rotation_matrix = None

        def get_drawings(self):
            return []

        def get_fonts(self, *, full=False):
            assert full is True
            return []

        def get_text(self, kind):
            assert kind == "dict"
            return {
                "blocks": [
                    {
                        "type": 0,
                        "lines": [
                            {
                                "dir": (1.0, 0.0),
                                "bbox": (10.0, 10.0, 60.0, 20.0),
                                "spans": [
                                    {
                                        "text": "  KEEP BOTH SIDES  ",
                                        "font": "Missing-Exact-Font",
                                        "size": 10.0,
                                        "origin": (10.0, 20.0),
                                        "bbox": (10.0, 10.0, 60.0, 20.0),
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }

    page_data = extract_page(Page(), page_num=3, detect_arcs=False)

    assert len(page_data.text_items) == 1
    item = page_data.text_items[0]
    assert item.text == "  KEEP BOTH SIDES  "
    assert item.font_name == "Missing-Exact-Font"
    assert item.font_asset is None


def test_usable_fonts_preserve_the_pdf_unicode_to_glyph_mapping():
    with pymupdf.open(WELDING_SYMBOL_CHART) as document:
        catalog = EmbeddedFontCatalog.from_page(document[0], page_number=1)
        traces = document[0].get_texttrace()

    checked = 0
    for trace in traces:
        font_name = str(trace.get("font") or "")
        asset = catalog.for_span(font_name)
        if asset is None:
            continue
        font = _load_font(asset.usable_bytes)
        cmap = font.getBestCmap()
        assert cmap is not None, f"{font_name} would force a fallback font"
        glyph_order = font.getGlyphOrder()
        for codepoint, glyph_id, _origin, _bbox in trace.get("chars") or ():
            assert 0 <= glyph_id < len(glyph_order)
            assert cmap.get(codepoint) == glyph_order[glyph_id]
            checked += 1
    assert checked > 0


def test_pdf_base14_text_uses_the_local_pdf_renderer_font_without_substitution(
    tmp_path,
):
    pdf_path = tmp_path / "base14.pdf"
    document = pymupdf.open()
    page = document.new_page(width=120, height=80)
    page.insert_text((20, 40), "W12X30", fontsize=10)
    document.save(pdf_path)
    document.close()

    with pymupdf.open(pdf_path) as document:
        page_data = extract_page(document[0], page_num=1, detect_arcs=False)

    assert len(page_data.text_items) == 1
    item = page_data.text_items[0]
    assert item.font_name == "Helvetica"
    assert item.font_failure is None
    assert item.font_asset is not None
    assert item.font_asset.source_origin == "pdf_base14_renderer_font"
    assert item.font_asset.source_format == "cff"
    assert item.font_asset.usable_format == "otf"
    font = _load_font(item.font_asset.usable_bytes)
    assert font.getBestCmap()

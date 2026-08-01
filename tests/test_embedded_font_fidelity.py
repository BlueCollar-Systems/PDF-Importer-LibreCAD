from __future__ import annotations

from collections import Counter
from io import BytesIO
from unittest.mock import patch

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf  # type: ignore[no-redef]
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
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


def _load_font(data: bytes) -> TTFont:
    font = TTFont(BytesIO(data), lazy=False, recalcTimestamp=False)
    # Force all referenced table payloads to be decoded while the in-memory
    # stream is alive. A table-directory-only file is not a usable font asset.
    for tag in font.reader.keys():
        font[tag].compile(font)
    return font


def test_shared_catalog_type3_without_xref_is_item_scoped_impossibility():
    class Document:
        @staticmethod
        def extract_font(_xref):
            raise AssertionError("Type3 without an xref must not be extracted")

    class Page:
        parent = Document()

        @staticmethod
        def get_texttrace():
            return []

        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            return [(None, "", "Type3", "", "Type3Resource")]

    catalog = EmbeddedFontCatalog.from_page(Page(), page_number=32)
    failure = catalog.failure_for_span("Type3Resource")

    assert catalog.assets == ()
    assert len(catalog.failures) == 1
    assert failure.span_font_name == "Type3Resource"
    assert failure.reason == "embedded_type3_font_program_unavailable"
    assert failure.source_xref is None
    assert failure.error_type == "ExactFontSourceImpossible"
    assert failure.detail == "PDF Type3 resource has no extractable font program"
    assert failure.proof_category == "source_specific_impossibility"
    assert catalog.failure_for_span("OtherFont").reason == "no_exact_embedded_font_match"


def test_shared_catalog_non_type3_without_xref_remains_terminal_page_failure():
    class Document:
        @staticmethod
        def extract_font(_xref):
            raise AssertionError("an invalid inventory row must stop extraction")

    class Page:
        parent = Document()

        @staticmethod
        def get_texttrace():
            return []

        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            return [(None, "", "Type1", "Siwa-Regular", "F1", "")]

    catalog = EmbeddedFontCatalog.from_page(Page(), page_number=33)

    assert catalog.assets == ()
    assert len(catalog.failures) == 1
    page_failure = catalog.failures[0]
    assert page_failure.span_font_name == ""
    assert page_failure.reason == "invalid_page_font_record"
    assert page_failure.proof_category == "source_inventory_invalid_for_page"
    assert catalog.failure_for_span("Siwa-Regular").reason == "invalid_page_font_record"


def test_cmap_repair_adds_host_safe_names_to_anonymous_subset_font():
    """Repaired PDF subset fonts must be loadable by native host font APIs."""
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "A"])
    pen = TTGlyphPen(None)
    empty_glyph = pen.glyph()
    builder.setupGlyf({".notdef": empty_glyph, "A": empty_glyph})
    builder.setupHorizontalMetrics({".notdef": (500, 0), "A": (600, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupCharacterMap({65: "A"})
    builder.setupOS2()
    builder.setupNameTable(
        {
            "familyName": "Disposable fixture",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Disposable fixture Regular",
            "fullName": "Disposable fixture Regular",
            "psName": "DisposableFixture-Regular",
        }
    )
    builder.setupPost()
    builder.setupMaxp()
    del builder.font["cmap"]
    del builder.font["name"]
    source = BytesIO()
    builder.font.save(source, reorderTables=False)

    usable_format, usable_bytes, cmap_installed = _usable_font(
        source.getvalue(),
        "ttf",
        "OCR Exact / Anonymous",
        {65: 1},
    )

    assert usable_format == "ttf"
    assert cmap_installed is True
    font = TTFont(BytesIO(usable_bytes), lazy=False)
    try:
        assert font.getBestCmap() == {65: "A"}
        names = {
            int(record.nameID): record.toUnicode()
            for record in font["name"].names
            if int(record.nameID) in {1, 2, 3, 4, 5, 6}
        }
        assert names[1] == "OCR Exact / Anonymous"
        assert names[2] == "Regular"
        assert names[4] == "OCR Exact / Anonymous"
        assert names[6] == "OCR-Exact-Anonymous"
    finally:
        font.close()


def test_exact_inventory_name_outranks_weaker_internal_family_aliases(
    monkeypatch,
):
    class Document:
        @staticmethod
        def extract_font(xref):
            names = {
                1: "ABCDEF+Arial",
                2: "ArialMT",
                3: "Arial-BoldMT",
            }
            return names[xref], "ttf", "Type0", f"font-{xref}".encode("ascii")

    class Page:
        parent = Document()

        @staticmethod
        def get_texttrace():
            return []

        @staticmethod
        def get_fonts(*, full=False):
            assert full is True
            return [
                (1, "ttf", "Type0", "ABCDEF+Arial", "F0", "Identity-H"),
                (2, "ttf", "Type0", "ArialMT", "F1", "Identity-H"),
                (3, "ttf", "Type0", "Arial-BoldMT", "F2", "Identity-H"),
            ]

    monkeypatch.setattr(
        embedded_fonts,
        "_page_unicode_glyph_maps",
        lambda _page: ({"Arial": {65: 1}}, set(), None),
    )
    monkeypatch.setattr(
        embedded_fonts,
        "_font_program_name_aliases",
        lambda _data, _format: {"Arial"},
    )
    monkeypatch.setattr(
        embedded_fonts,
        "_usable_font",
        lambda source, source_format, _name, _mapping: (
            source_format,
            source,
            True,
        ),
    )
    monkeypatch.setattr(
        embedded_fonts,
        "_font_delivery_metrics",
        lambda _data: (1000, 800, -200, (500, 500)),
    )

    catalog = EmbeddedFontCatalog.from_page(Page(), page_number=30)
    asset = catalog.for_span("Arial")

    assert asset is not None
    assert asset.source_xref == 1
    assert asset.base_font_name == "Arial"


def test_cmap_repair_classifies_fonttools_assertion_as_malformed_source(
    monkeypatch,
):
    monkeypatch.setattr(
        embedded_fonts,
        "_install_pdf_unicode_cmap_unchecked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(
                "corrupt cmap table format 4 (data length: 74, header length: 80)"
            )
        ),
    )

    with pytest.raises(
        ExactFontSourceImpossible,
        match="corrupt cmap table format 4",
    ):
        _install_pdf_unicode_cmap(
            b"malformed-font",
            {65: 1},
            "MalformedFont",
        )


def test_real_chart_maps_each_span_font_to_its_exact_distinct_embedded_asset(
    welding_symbol_chart,
):
    with pymupdf.open(welding_symbol_chart) as document:
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


def test_raw_cff_conversion_is_deterministic_and_loadable_without_disk_sidecars(
    welding_symbol_chart,
):
    with pymupdf.open(welding_symbol_chart) as document:
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


def test_unknown_span_font_stays_unresolved_instead_of_substituting_another_asset(
    welding_symbol_chart,
):
    with pymupdf.open(welding_symbol_chart) as document:
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


def test_text_trace_failure_rejects_even_a_font_with_an_existing_cmap(
    welding_symbol_chart,
):
    with pymupdf.open(welding_symbol_chart) as document:
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


def test_multiple_different_embedded_programs_with_same_name_remain_ambiguous(
    welding_symbol_chart,
):
    with pymupdf.open(welding_symbol_chart) as document:
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


def test_usable_fonts_preserve_the_pdf_unicode_to_glyph_mapping(welding_symbol_chart):
    with pymupdf.open(welding_symbol_chart) as document:
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


def test_generated_pdf_matches_a_truetype_postscript_span_to_its_embedded_font(
    deterministic_exact_font,
    tmp_path,
):
    pdf_path = tmp_path / "deterministic-embedded-ttf.pdf"
    document = pymupdf.open()
    page = document.new_page(width=240, height=120)
    page.insert_font(fontname="BCSTest", fontfile=str(deterministic_exact_font))
    page.insert_text(
        (24, 60),
        "AB x!",
        fontsize=14,
        fontname="BCSTest",
    )
    document.save(pdf_path)
    document.close()

    with pymupdf.open(pdf_path) as document:
        page_data = extract_page(document[0], page_num=0, detect_arcs=False)

    assert len(page_data.text_items) == 1
    item = page_data.text_items[0]
    assert item.font_name == "BCSDeterministicTest-Regular"
    assert item.font_failure is None
    assert item.font_asset is not None
    assert item.font_asset.span_font_name == item.font_name
    assert item.font_asset.base_font_name == "BCS Deterministic Test Regular"
    assert item.font_asset.source_origin == "embedded_pdf_font"
    assert item.font_asset.source_format == "ttf"
    font = _load_font(item.font_asset.usable_bytes)
    cmap = font.getBestCmap()
    glyphs = font["glyf"]
    assert cmap[ord("A")] != cmap[ord("B")]
    assert tuple(glyphs[cmap[ord("A")]].getCoordinates(glyphs)[0]) != tuple(
        glyphs[cmap[ord("B")]].getCoordinates(glyphs)[0]
    )

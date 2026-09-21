"""Glyph-code recovery: synthetic fonts and a synthetic page, no PDF needed.

Every font here is built in the test from fictional shapes, and every string is
fictional sample content (D042, MXT-100, SAMPLE, job 1000-01). The page is a
duck type that answers the three questions the module asks a PyMuPDF page:
which glyphs were drawn, which of them MuPDF could not turn into characters,
and which PDF font object they came from.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "PDFVectorImporter", ROOT / "pdf_vector_importer", ROOT):
    if (candidate / "pdfcadcore").is_dir():
        sys.path.insert(0, str(candidate))
        break
from pdfcadcore import glyph_code_recovery as gcr

FONT_TOOLS = pytest.importorskip("fontTools")
UNKNOWN = gcr.UNKNOWN_CHARACTER

# One distinct closed outline per character. Nothing here is a real typeface:
# the point is that two different characters never share a contour list.
SHAPES = {
    " ": None,
    "D": [(0, 0), (500, 0), (500, 700), (0, 700)],
    "0": [(20, 0), (480, 0), (480, 700), (20, 700)],
    "4": [(0, 0), (460, 0), (460, 660), (0, 660)],
    "2": [(40, 0), (520, 0), (520, 640), (40, 640)],
    "M": [(0, 0), (600, 0), (600, 720), (300, 400), (0, 720)],
    "S": [(10, 10), (590, 10), (590, 690), (300, 380), (10, 690)],
    "X": [(0, 0), (540, 0), (540, 680), (270, 340), (0, 680)],
    "-": [(0, 300), (400, 300), (400, 360), (0, 360)],
    "1": [(200, 0), (300, 0), (300, 700), (200, 700)],
}
ADVANCES = {
    " ": 278, "D": 600, "0": 520, "4": 500, "2": 560,
    "M": 700, "S": 640, "X": 620, "-": 440, "1": 380,
}


def _glyph(points):
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    pen = TTGlyphPen(None)
    if points:
        pen.moveTo(points[0])
        for point in points[1:]:
            pen.lineTo(point)
        pen.closePath()
    return pen.glyph()


def _composite(components, glyph_names):
    """A glyph built from references to other glyphs, the way an accent is."""
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    pen = TTGlyphPen({name: None for name in glyph_names})
    for component_name, dx, dy in components:
        pen.addComponent(component_name, (1, 0, 0, 1, dx, dy))
    return pen.glyph()


def _build_font(path, order, shape_for, *, cmap=None, family="Sample Gothic",
                style="Regular", post_names=False, upem=1000, warp=None,
                composites=None):
    """Write one TrueType face. ``order`` is the glyph order, index by index."""
    from fontTools.fontBuilder import FontBuilder

    names = [".notdef"] + list(order)
    builder = FontBuilder(upem, isTTF=True)
    builder.setupGlyphOrder(names)
    glyphs = {".notdef": _glyph([(0, 0), (100, 0), (100, 100), (0, 100)])}
    metrics = {".notdef": (500, 0)}
    for name in order:
        character = shape_for(name)
        points = SHAPES[character]
        parts = (composites or {}).get(name)
        if parts:
            glyphs[name] = _composite(parts, names)
        else:
            glyphs[name] = _glyph(warp(points) if (warp and points) else points)
        metrics[name] = (ADVANCES[character], 0)
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    if cmap is not None:
        builder.setupCharacterMap(cmap)
    builder.setupNameTable({
        "familyName": family,
        "styleName": style,
        "uniqueFontIdentifier": "%s %s sample" % (family, style),
        "fullName": "%s %s" % (family, style),
        "psName": "%s-%s" % (family.replace(" ", ""), style.replace(" ", "")),
        "version": "1.000",
    })
    # A subset with no cmap is exactly the defect; state the ranges so the
    # builder does not insist on one.
    builder.setupOS2(ulUnicodeRange1=1, xAvgCharWidth=500)
    builder.setupPost(keepGlyphNames=bool(post_names))
    builder.save(str(path))
    return path.read_bytes()


def reference_face(directory, *, family="Sample Gothic", style="Regular",
                   characters=" D042MSX-1", distort=False, name="sample.ttf",
                   composite_index=None):
    """A reference face with a real cmap, the way an installed font has one.

    ``distort`` gives every glyph a different outline while keeping the name
    and the advances: a face of the right family that is not the right face,
    which is how a bold reference behaves against a regular subset.
    """
    order = ["ref%02d" % index for index in range(len(characters))]
    mapping = {}
    for index, character in enumerate(characters):
        mapping[ord(character)] = order[index]

    def shape_for(glyph_name):
        return characters[order.index(glyph_name)]

    composites = None
    if composite_index is not None:
        composites = {order[composite_index]: [(order[0], 0, 0), (order[1], 60, 210)]}
    _build_font(directory / name, order, shape_for, cmap=mapping,
                family=family, style=style, composites=composites,
                warp=(lambda points: [(x + 13, y + 7) for x, y in points])
                if distort else None)
    return directory / name


# ── the subset program the PDF embeds ──


def subset_program(path, layout, *, cmap=None, post_names=False, names=None,
                   composite_index=None):
    """``layout`` maps glyph index -> character. Index 0 is .notdef."""
    highest = max(layout)
    order = []
    characters = {}
    for index in range(1, highest + 1):
        name = (names or {}).get(index, "g%05d" % index)
        order.append(name)
        characters[name] = layout.get(index, " ")
    composites = None
    if composite_index is not None:
        composites = {
            order[composite_index - 1]: [(order[0], 0, 0), (order[1], 60, 210)]
        }
    return _build_font(path, order, lambda name: characters[name],
                       cmap=cmap, post_names=post_names, composites=composites)


# ── the page and document duck types ──


class FakeDocument:
    def __init__(self, keys, program, *, extract_error=None):
        self._keys = keys
        self._program = program
        self._extract_error = extract_error

    def xref_get_key(self, xref, key):
        entry = self._keys.get(int(xref), {})
        if key not in entry:
            return ("null", "null")
        return entry[key]

    def xref_object(self, xref, compressed=True):
        return self._keys.get(int(xref), {}).get("__object__", "<<>>")

    def extract_font(self, xref):
        if self._extract_error is not None:
            raise self._extract_error
        return ("ABCDEF+SampleGothic", "ttf", "Type0", self._program)


class FakePage:
    def __init__(self, document, fonts, traces, number=0):
        self.parent = document
        self._fonts = fonts
        self._traces = traces
        self.number = number

    def get_fonts(self, full=True):
        return self._fonts

    def get_texttrace(self):
        return self._traces


def trace_span(font, entries):
    """``entries`` is a list of (unicode, glyph id); origins are handed out."""
    chars = []
    for index, (codepoint, glyph_id) in enumerate(entries):
        origin = (10.0 + index * 7.0, 100.0)
        chars.append((codepoint, glyph_id, origin, (origin[0], 90.0, origin[0] + 7.0, 104.0)))
    return {"font": font, "chars": chars}


def raw_span(font, entries, *, text=None, bbox=(10.0, 90.0, 200.0, 104.0)):
    """A RAWDICT span whose per-character origins match ``trace_span``."""
    chars = []
    for index, (codepoint, _glyph_id) in enumerate(entries):
        chars.append({
            "c": chr(codepoint if codepoint != UNKNOWN else entries[index][1]),
            "origin": (10.0 + index * 7.0, 100.0),
            "bbox": (10.0 + index * 7.0, 90.0, 17.0 + index * 7.0, 104.0),
        })
    span = {"font": font, "bbox": list(bbox), "size": 10.0, "chars": chars}
    if text is not None:
        span["text"] = text
    return span


def tdict_of(*spans):
    return {"blocks": [{"type": 0, "lines": [{"dir": (1.0, 0.0), "spans": list(spans)}]}]}


def span_text(tdict):
    out = []
    for block in tdict["blocks"]:
        for line in block["lines"]:
            for span in line["spans"]:
                chars = span.get("chars") or ()
                out.append("".join(c["c"] for c in chars) if chars
                           else str(span.get("text", "")))
    return out


TYPE0_KEYS = {
    7: {
        "Subtype": ("name", "/Type0"),
        "Encoding": ("name", "/Identity-H"),
        "DescendantFonts": ("array", "[8 0 R]"),
    },
    8: {
        "Subtype": ("name", "/CIDFontType2"),
        "CIDToGIDMap": ("name", "/Identity"),
        "DW": ("int", "1000"),
    },
}


def type0_keys(widths):
    keys = {7: dict(TYPE0_KEYS[7]), 8: dict(TYPE0_KEYS[8])}
    keys[8]["W"] = ("array", "[" + " ".join(
        "%d[%d]" % (glyph_id, width) for glyph_id, width in sorted(widths.items())
    ) + "]")
    return keys


FONT_RECORDS = [(7, "ttf", "Type0", "ABCDEF+SampleGothic", "F1", "Identity-H")]


@pytest.fixture(autouse=True)
def _isolated_reference_fonts(monkeypatch):
    monkeypatch.delenv("BCS_GLYPH_REFERENCE_FONTS", raising=False)
    gcr.clear_reference_font_cache()
    yield
    gcr.clear_reference_font_cache()


def build_case(tmp_path, monkeypatch, layout, drawn, *, reference=True,
               widths=None, cmap=None, post_names=False, reference_kwargs=None,
               extract_error=None, font_keys=None, font_records=None,
               glyph_names=None):
    """One page drawing ``drawn`` (a list of glyph ids) from one subset."""
    program = subset_program(tmp_path / "subset.ttf", layout, cmap=cmap,
                             post_names=post_names, names=glyph_names)
    reference_dir = tmp_path / "reference"
    reference_dir.mkdir(exist_ok=True)
    if reference:
        reference_face(reference_dir, **(reference_kwargs or {}))
    monkeypatch.setenv("BCS_GLYPH_REFERENCE_FONTS",
                       str(reference_dir) if reference else "none")
    gcr.clear_reference_font_cache()
    if widths is None:
        widths = {glyph_id: ADVANCES[layout[glyph_id]] for glyph_id in layout}
    keys = font_keys if font_keys is not None else type0_keys(widths)
    document = FakeDocument(keys, program, extract_error=extract_error)
    entries = [(UNKNOWN, glyph_id) for glyph_id in drawn]
    page = FakePage(
        document,
        font_records if font_records is not None else FONT_RECORDS,
        [trace_span("SampleGothic", entries)],
    )
    return document, page, entries


# ── the defect itself ──


def test_recovers_a_span_whose_subset_order_is_not_source_order(tmp_path, monkeypatch):
    # Glyph 1 is "2" and glyph 4 is "0": index order is not character order, so
    # anything that matched glyph id to position would answer "D2xx".
    layout = {1: "2", 2: "D", 3: " ", 4: "0", 5: "4"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [2, 4, 5, 1])
    tdict = tdict_of(raw_span("SampleGothic", entries))
    assert span_text(tdict) == ["\x02\x04\x05\x01"]

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D042"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["recovered"] == 1
    assert block["unproven"] == 0
    assert block["glyphs_recovered"] == 4
    assert block["spans_by_route"] == {"outline_identity": 1}


def test_printable_ascii_raw_codes_are_recovered_not_left_looking_right(tmp_path, monkeypatch):
    # The dangerous case: glyph ids 0x30 and 0x36 arrive as the characters "0"
    # and "6". A control-character check sees nothing wrong with "06".
    layout = {0x30: "M", 0x36: "S", 0x10: "-", 0x16: "1"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [0x30, 0x36, 0x10, 0x16])
    tdict = tdict_of(raw_span("SampleGothic", entries))
    raw = span_text(tdict)[0]
    assert raw == "06\x10\x16"
    assert raw[:2].isprintable() and raw[:2].isascii()

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["MS-1"]


def test_one_unproven_character_leaves_the_whole_span_raw(tmp_path, monkeypatch):
    # "X" is not in the reference face, so that one character is unproven and
    # the span must stay byte for byte as it arrived - never "D04?".
    layout = {1: "D", 2: "0", 3: "4", 4: "X"}
    document, page, entries = build_case(
        tmp_path, monkeypatch, layout,
        [1, 2, 3, 4], reference_kwargs={"characters": " D042MS-1"},
    )
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["recovered"] == 0
    assert block["unproven"] == 1
    assert block["items"][0]["raw_codes"] == [1, 2, 3, 4]
    assert block["items"][0]["font_name"] == "SampleGothic"


def test_a_wrong_reference_face_proves_nothing(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(
        tmp_path, monkeypatch, layout, [1, 2, 3, 4],
        reference_kwargs={"distort": True},
    )
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["recovered"] == 0 and block["unproven"] == 1


def test_no_reference_face_recovers_nothing_and_says_so(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], reference=False)
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["by_reason"] == {"no_reference_face_available": 1}
    assert block["items"][0]["looked_for_face"] == "samplegothic"


def test_a_disagreeing_declared_advance_proves_nothing(tmp_path, monkeypatch):
    # The outline matches, but this PDF says the glyph is 999/1000 em wide.
    layout = {1: "D", 2: "0"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2],
                                         widths={1: 999, 2: 999})
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    assert gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))["unproven"] == 1


# ── route order ──


def test_the_embedded_cmap_is_used_before_any_outline(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    cmap = {ord("D"): "g00001", ord("0"): "g00002", ord("4"): "g00003", ord("2"): "g00004"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], cmap=cmap)
    tdict = tdict_of(raw_span("SampleGothic", entries))

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D042"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["spans_by_route"] == {"embedded_cmap": 1}
    assert block["glyphs_by_route"] == {"embedded_cmap": 4}


def test_a_cmap_into_the_private_use_area_is_refused(tmp_path, monkeypatch):
    # A Wingdings-style cmap "proves" U+F0xx, which is a picture, not a
    # character. The outline route answers instead, and says so.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    cmap = {0xF041: "g00001", 0xF042: "g00002", 0xF043: "g00003", 0xF044: "g00004"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], cmap=cmap)
    tdict = tdict_of(raw_span("SampleGothic", entries))

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D042"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["spans_by_route"] == {"outline_identity": 1}


def test_a_real_post_table_proves_characters_when_the_advances_agree(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    names = {1: "uni0044", 2: "uni0030", 3: "uni0034", 4: "uni0032"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], post_names=True,
                                         glyph_names=names)
    tdict = tdict_of(raw_span("SampleGothic", entries))

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D042"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["spans_by_route"] == {"post_glyph_name": 1}


def test_post_names_that_contradict_the_drawn_outlines_prove_nothing(tmp_path, monkeypatch):
    # A subsetter that reorders glyf without rewriting post leaves names for
    # glyphs the file no longer draws. The names read as perfectly plausible
    # characters, so only the outline can catch them - and where the two
    # disagree, nothing is proven.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    names = {1: "uni0053", 2: "uni0031", 3: "uni0058", 4: "uni004D"}   # S 1 X M
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], post_names=True,
                                         glyph_names=names)
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["recovered"] == 0
    assert block["by_reason"] == {"glyph_outline_not_proven": 1}


def test_a_cmap_that_contradicts_the_drawn_outlines_proves_nothing(tmp_path, monkeypatch):
    # Same rule for the font's own cmap: a declaration is not a drawing.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    lying = {ord("S"): "g00001", ord("1"): "g00002", ord("X"): "g00003", ord("M"): "g00004"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], cmap=lying)
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    assert gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))["recovered"] == 0


def test_a_font_name_proves_nothing_with_no_reference_face_to_corroborate_it(tmp_path, monkeypatch):
    # With no reference face there is no advance to check the name against and
    # no outline table to contradict it, so a name alone never substitutes.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    names = {1: "uni0044", 2: "uni0030", 3: "uni0034", 4: "uni0032"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], post_names=True,
                                         reference=False, glyph_names=names)
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["by_reason"] == {"no_reference_face_available": 1}


def test_synthesised_glyph_names_never_prove_anything(tmp_path, monkeypatch):
    # The subset below has post format 3.0, so fontTools invents "g00001"
    # style names from the index. They are fabricated from the very index
    # being decoded; with no reference face nothing may be recovered.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout,
                                         [1, 2, 3, 4], reference=False)
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before


# ── scope ──


def test_a_winansi_font_with_no_tounicode_is_untouched(tmp_path, monkeypatch):
    # ~1,380 corpus fonts look like this and extract correctly today: WinAnsi
    # IS an encoding. Nothing here may reach them.
    layout = {1: "D", 2: "0"}
    keys = {7: {
        "Subtype": ("name", "/TrueType"),
        "Encoding": ("name", "/WinAnsiEncoding"),
        "FirstChar": ("int", "32"),
    }}
    program = subset_program(tmp_path / "subset.ttf", layout)
    document = FakeDocument(keys, program)
    entries = [(ord("D"), 1), (ord("0"), 2)]
    page = FakePage(document, [(7, "ttf", "TrueType", "SampleGothic", "F1", "WinAnsiEncoding")],
                    [trace_span("SampleGothic", entries)])
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    assert gcr.glyph_code_issues(document) == []


def test_a_type3_font_is_out_of_scope_and_never_outline_matched(tmp_path, monkeypatch):
    # Type3 glyphs are content-stream procedures: no glyf, no outline to hash.
    # The trigger is Type0 only, so nothing here is ever substituted - but
    # MuPDF has already said these characters are unmapped, so they are still
    # counted rather than passing as clean.
    layout = {1: "D", 2: "0"}
    keys = {7: {"Subtype": ("name", "/Type3")}}
    program = subset_program(tmp_path / "subset.ttf", layout)

    class RefusingDocument(FakeDocument):
        def extract_font(self, xref):
            raise AssertionError("a Type3 font has no font program to extract")

    document = RefusingDocument(keys, program)
    entries = [(UNKNOWN, 141), (UNKNOWN, 142)]
    page = FakePage(document, [(7, "", "Type3", "", "Type3 (7 0 R)", "")],
                    [trace_span("Type3 (7 0 R)", entries)])
    tdict = tdict_of(raw_span("Type3 (7 0 R)", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["recovered"] == 0
    assert block["by_reason"] == {"font_is_not_type0": 1}
    assert block["items"][0]["raw_codes"] == [141, 142]


def test_a_font_that_declares_tounicode_is_left_to_the_pdf(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0"}
    keys = type0_keys({1: 600, 2: 520})
    keys[7]["ToUnicode"] = ("xref", "9 0 R")
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2],
                                         font_keys=keys)
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["recovered"] == 0
    assert block["by_reason"] == {"font_declares_to_unicode": 1}


def test_a_page_with_no_composite_or_type3_font_is_never_even_traced(tmp_path, monkeypatch):
    # The cheap gate: a simple font always carries a real text encoding, so a
    # page of nothing but TrueType fonts costs no second text extraction.
    layout = {1: "D", 2: "0"}
    program = subset_program(tmp_path / "subset.ttf", layout)
    document = FakeDocument({7: {"Subtype": ("name", "/TrueType")}}, program)
    entries = [(ord("D"), 1), (ord("0"), 2)]

    class CountingPage(FakePage):
        traces_taken = 0

        def get_texttrace(self):
            CountingPage.traces_taken += 1
            return self._traces

    page = CountingPage(document, [(7, "ttf", "TrueType", "SampleGothic", "F1", "WinAnsi")],
                        [trace_span("SampleGothic", entries)])

    gcr.recover_glyph_codes_in_place(page, tdict_of(raw_span("SampleGothic", entries)))

    assert CountingPage.traces_taken == 0
    assert gcr.page_delivers_glyph_codes(page) is False


def test_characters_mupdf_resolved_are_never_second_guessed_nor_called_tounicode(
        tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, _entries = build_case(tmp_path, monkeypatch, layout, [1, 2])
    # One character MuPDF resolved itself (a partial map), one it did not.
    entries = [(ord("Z"), 1), (UNKNOWN, 2)]
    page._traces = [trace_span("SampleGothic", entries)]
    tdict = tdict_of(raw_span("SampleGothic", entries))
    assert span_text(tdict) == ["Z\x02"]

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["Z0"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    # An in-scope font has no /ToUnicode by construction, so no count in this
    # block may read as one. The character MuPDF had is counted apart.
    assert "pdf_to_unicode" not in block["glyphs_by_route"]
    assert block["glyphs_by_route"] == {"outline_identity": 1}
    assert block["characters_left_as_delivered"] == {"mupdf_resolved": 1}


# ── how the result is delivered and reported ──


def test_a_plain_text_dictionary_is_never_bound_by_guessing_glyph_ids(tmp_path, monkeypatch):
    # page.get_text("dict") carries no per-character origins. Reading the
    # delivered code as a glyph index is how a character no glyph drew becomes
    # a letter, so it is refused and reported as this run's limitation.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, _entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])
    span = {"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
            "size": 10.0, "text": "\x01\x02\x03\x04"}
    tdict = tdict_of(span)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span["text"] == "\x01\x02\x03\x04"
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["by_reason"] == {"span_has_no_character_origins": 1}
    assert block["unproven_from_run_limitation"] == 1


def test_a_layout_space_in_a_plain_dictionary_never_becomes_a_character(
        tmp_path, monkeypatch):
    # MuPDF's layout inserts a space between two runs on one baseline. No
    # glyph drew it. Reading its code point as a glyph index picks whichever
    # character that subset draws at glyph 32 - legible, plausible and wrong.
    layout = {1: "D", 2: "0", 3: "4", 4: "2", 32: "M"}
    document, page, _entries = build_case(tmp_path, monkeypatch, layout,
                                          [1, 2, 3, 4, 32])
    span = {"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
            "size": 10.0, "text": "\x01\x02 \x03\x04"}
    tdict = tdict_of(span)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span["text"] == "\x01\x02 \x03\x04"
    assert "M" not in span["text"]


def test_the_recovered_text_is_copied_onto_a_plain_dictionary_span_for_span(
        tmp_path, monkeypatch):
    # The host route: recover the per-character dictionary, copy the result
    # across. A span that does not line up is left alone and counted.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])
    raw = tdict_of(raw_span("SampleGothic", entries))
    gcr.recover_glyph_codes_in_place(page, raw)
    assert span_text(raw) == ["D042"]

    plain = tdict_of({"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
                      "size": 10.0, "text": "\x01\x02\x03\x04"})
    assert gcr.copy_recovered_text(raw, plain) == (1, 0)
    assert span_text(plain) == ["D042"]

    misaligned = tdict_of({"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
                           "size": 10.0, "text": "\x01\x02\x03"})
    assert gcr.copy_recovered_text(raw, misaligned) == (0, 1)
    assert span_text(misaligned) == ["\x01\x02\x03"]

    other_place = tdict_of({"font": "SampleGothic", "bbox": [99.0, 90.0, 200.0, 104.0],
                            "size": 10.0, "text": "\x01\x02\x03\x04"})
    assert gcr.copy_recovered_text(raw, other_place) == (0, 1)


def test_running_twice_recovers_once_and_counts_once(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])

    for _ in range(2):
        tdict = tdict_of(raw_span("SampleGothic", entries))
        gcr.recover_glyph_codes_in_place(page, tdict)
        assert span_text(tdict) == ["D042"]

    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["spans_examined"] == 1
    assert block["recovered"] == 1


def test_an_unreadable_font_program_is_reported_and_never_raises(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2],
                                         extract_error=RuntimeError("EX404"))
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["by_reason"] == {"embedded_font_program_unavailable": 1}
    assert "EX404" in block["items"][0]["detail"]


def test_a_page_that_cannot_be_traced_changes_nothing(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2])

    def refuse():
        raise RuntimeError("no trace")

    page.get_texttrace = refuse
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before


def test_the_report_block_names_the_route_and_warns_only_for_unproven(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "X"}
    document, page, _entries = build_case(
        tmp_path, monkeypatch, layout, [1, 2, 3, 4],
        reference_kwargs={"characters": " D042MS-1"},
    )
    proven = [(UNKNOWN, 1), (UNKNOWN, 2)]
    unproven = [(UNKNOWN, 4), (UNKNOWN, 3)]
    page._traces = [{"font": "SampleGothic",
                     "chars": trace_span("SampleGothic", proven)["chars"]},
                    {"font": "SampleGothic",
                     "chars": [(code, glyph, (400.0 + index * 7.0, 200.0),
                                (400.0, 190.0, 407.0, 204.0))
                               for index, (code, glyph) in enumerate(unproven)]}]
    first = raw_span("SampleGothic", proven)
    second = {
        "font": "SampleGothic", "bbox": [400.0, 190.0, 460.0, 204.0], "size": 10.0,
        "chars": [{"c": chr(glyph), "origin": (400.0 + index * 7.0, 200.0),
                   "bbox": (400.0, 190.0, 407.0, 204.0)}
                  for index, (_code, glyph) in enumerate(unproven)],
    }
    tdict = tdict_of(first, second)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D0", "\x04\x03"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["spans_examined"] == 2
    assert block["recovered"] == 1 and block["unproven"] == 1
    assert gcr.glyph_code_warning_count(block) == 1
    # Unproven spans sort first so the item cap never hides one.
    assert block["items"][0]["status"] == "unproven"
    assert block["pages"] == [1]
    line = gcr.summarize_glyph_code_issues(gcr.glyph_code_issues(document))
    assert "outline_identity" in line and "raw glyph codes" in line


def test_the_shared_extractor_hands_hosts_the_recovered_text(tmp_path, monkeypatch):
    # The hook in _extract_text is what makes every host, every downstream
    # classifier and the fraction merger see the characters instead of the
    # codes. Without it this span reaches them as "\x01\x02\x03\x04".
    from pdfcadcore import primitive_extractor

    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])
    span = raw_span("SampleGothic", entries)
    span["origin"] = (10.0, 100.0)
    span["ascender"] = 0.9
    span["descender"] = -0.2
    span["color"] = 0
    tdict = tdict_of(span)
    page.get_text = lambda kind="dict": tdict

    items = primitive_extractor._extract_text(
        page, 200.0, 1, True, 1.0, page_w=300.0, to_model=lambda x, y: (x, y)
    )

    assert [item.text for item in items] == ["D042"]
    assert gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))["recovered"] == 1


def test_issues_can_be_read_back_for_one_page(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2])
    tdict = tdict_of(raw_span("SampleGothic", entries))
    gcr.recover_glyph_codes_in_place(page, tdict)

    assert len(gcr.glyph_code_issues(page)) == 1
    assert len(gcr.glyph_code_issues(document)) == 1
    other = FakePage(document, FONT_RECORDS, [], number=4)
    assert gcr.glyph_code_issues(other) == []


def test_reference_directories_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("BCS_GLYPH_REFERENCE_FONTS", "none")
    gcr.clear_reference_font_cache()
    assert gcr.reference_font_directories() == ()


def test_reference_directories_honour_an_explicit_list(tmp_path, monkeypatch):
    monkeypatch.setenv("BCS_GLYPH_REFERENCE_FONTS",
                       str(tmp_path) + os.pathsep + str(tmp_path / "missing"))
    gcr.clear_reference_font_cache()
    assert str(tmp_path) in gcr.reference_font_directories()


# ── one span, one record, whichever dictionary examined it ──


def test_two_dictionaries_of_one_page_report_one_row_per_span(tmp_path, monkeypatch):
    # A host may hand this module its own dictionary and the one a cross-check
    # compares against. They describe the same spans, so the report must not
    # claim to have examined the page twice, nor list one span under two
    # opposite verdicts, nor warn about a span that was recovered. The space
    # below is MuPDF's layout, not a glyph: the two dictionaries account for it
    # differently, which is exactly what used to make it two rows.
    layout = {1: "D", 2: "0", 3: "4", 4: "2", 32: "M"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])

    rich_span = raw_span("SampleGothic", entries)
    rich_span["chars"].insert(2, {"c": " ", "origin": (300.0, 100.0),
                                  "bbox": (300.0, 90.0, 307.0, 104.0)})
    rich = tdict_of(rich_span)
    gcr.recover_glyph_codes_in_place(page, rich)
    assert span_text(rich) == ["D0 42"]

    plain = tdict_of({"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
                      "size": 10.0, "text": "\x01\x02 \x03\x04"})
    gcr.recover_glyph_codes_in_place(page, plain)

    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["spans_examined"] == 1
    assert (block["recovered"], block["unproven"]) == (1, 0)
    assert gcr.glyph_code_warning_count(block) == 0
    assert block["characters_left_as_delivered"] == {"layout_space": 1}


def test_running_twice_over_a_plain_dictionary_changes_nothing(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, _entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])
    span = {"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
            "size": 10.0, "text": "\x01\x02\x03\x04"}
    tdict = tdict_of(span)

    for _ in range(3):
        gcr.recover_glyph_codes_in_place(page, tdict)

    assert span["text"] == "\x01\x02\x03\x04"
    assert gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))["spans_examined"] == 1


# ── what a report may and may not claim ──


def test_a_run_limitation_is_never_reported_as_the_document_failing(tmp_path, monkeypatch):
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, _entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3, 4])
    tdict = tdict_of({"font": "SampleGothic", "bbox": [10.0, 90.0, 200.0, 104.0],
                      "size": 10.0, "text": "\x01\x02\x03\x04"})

    gcr.recover_glyph_codes_in_place(page, tdict)

    line = gcr.summarize_glyph_code_issues(gcr.glyph_code_issues(document))
    assert "a limitation of this import, not of the sheet" in line
    assert "no usable Unicode map" not in line


def test_two_subsets_of_one_family_are_reported_not_passed_over(tmp_path, monkeypatch):
    # Both fonts strip to the same base name, so neither resolves to one xref.
    # Nothing may be proven - and the sheet must not publish a clean report.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(
        tmp_path, monkeypatch, layout, [1, 2, 3, 4],
        font_records=[(7, "ttf", "Type0", "AAAAAA+SampleGothic", "F1", "Identity-H"),
                      (9, "ttf", "Type0", "AAAAAB+SampleGothic", "F2", "Identity-H")],
    )
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["by_reason"] == {"font_name_ambiguous_on_page": 1}
    assert block["unproven_from_run_limitation"] == 1


def test_a_font_the_page_does_not_name_is_reported_not_passed_over(tmp_path, monkeypatch):
    # The page's font dictionaries do not name the font that drew this text,
    # so there is nothing to read the subset out of. Saying so is a statement
    # about this run, not about what the document declares.
    layout = {1: "D", 2: "0", 3: "4", 4: "2"}
    document, page, entries = build_case(
        tmp_path, monkeypatch, layout, [1, 2, 3, 4],
        font_records=[(7, "ttf", "Type0", "AAAAAA+OtherFace", "F1", "Identity-H")],
    )
    tdict = tdict_of(raw_span("SampleGothic", entries))
    before = span_text(tdict)

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == before
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["by_reason"] == {"font_not_found_on_page": 1}
    assert block["unproven_from_run_limitation"] == 1


def test_a_blank_glyph_is_named_a_convention_and_not_outline_identity(tmp_path, monkeypatch):
    # Every empty outline hashes alike in every face, so the only thing behind
    # this character is its advance. The report says which it was.
    layout = {1: "D", 2: " ", 3: "0"}
    document, page, entries = build_case(tmp_path, monkeypatch, layout, [1, 2, 3])
    tdict = tdict_of(raw_span("SampleGothic", entries))

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D 0"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["glyphs_by_route"] == {"blank_glyph_advance": 1, "outline_identity": 2}
    assert block["spans_by_route"] == {"blank_glyph_advance": 1}


def test_an_accented_glyph_built_from_components_is_proven_like_any_other(
        tmp_path, monkeypatch):
    # glyf records an accented glyph as references to other glyphs rather than
    # as contours. A pen that does not follow them hashes nothing comparable,
    # so such a character could never be proven - and by the all-or-nothing
    # rule one of them leaves a whole span raw.
    layout = {1: "D", 2: "0", 3: "4"}
    reference_dir = tmp_path / "reference"
    reference_dir.mkdir()
    reference_face(reference_dir, characters="D04", composite_index=2)
    program = subset_program(tmp_path / "subset.ttf", layout, composite_index=3)
    monkeypatch.setenv("BCS_GLYPH_REFERENCE_FONTS", str(reference_dir))
    gcr.clear_reference_font_cache()

    document = FakeDocument(type0_keys({1: 600, 2: 520, 3: 500}), program)
    entries = [(UNKNOWN, 1), (UNKNOWN, 3)]
    page = FakePage(document, FONT_RECORDS, [trace_span("SampleGothic", entries)])
    tdict = tdict_of(raw_span("SampleGothic", entries))

    gcr.recover_glyph_codes_in_place(page, tdict)

    assert span_text(tdict) == ["D4"]
    block = gcr.glyph_code_delivery_block(gcr.glyph_code_issues(document))
    assert block["glyphs_by_route"] == {"outline_identity": 2}


def test_no_fonttools_log_record_escapes_the_reference_index_build(tmp_path, monkeypatch):
    import logging

    captured = []

    class Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.name)

    (tmp_path / "broken.ttf").write_bytes(b"\x00\x01\x00\x00not a font at all")
    reference_face(tmp_path)
    monkeypatch.setenv("BCS_GLYPH_REFERENCE_FONTS", str(tmp_path))
    gcr.clear_reference_font_cache()

    handler = Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.DEBUG)
    try:
        assert len(gcr._reference_index(gcr.reference_font_directories())) == 1
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)

    assert [name for name in captured if name.startswith("fontTools")] == []

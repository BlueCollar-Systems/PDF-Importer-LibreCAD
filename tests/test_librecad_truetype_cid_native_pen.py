"""Source-bound native pens from TrueType outlines and CID-keyed CFF font dicts.

Fixtures are fictional fonts built here; no installed or customer font is read.
The pen is an approximation of the bound font program's dominant vertical stem,
never a default, and every refusal names why so the item keeps its fallback.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import io
import json
import math
from pathlib import Path

from fontTools.cffLib import FDArrayIndex, FDSelect, FontDict, PrivateDict
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
import pytest

import dxf_text_builder as builder
from test_librecad_native_text_weight import _cff, _source


ARIAL_LIKE_STEM = 90
ARIAL_LIKE_GLYPHS = "lI1HETPA"


def _shear(points, slant):
    return [(x + y * slant, y) for x, y in points]


def _contour(pen, points, slant=0.0):
    points = _shear(points, slant)
    pen.moveTo(points[0])
    for point in points[1:]:
        pen.lineTo(point)
    pen.closePath()


def _rect(pen, x0, y0, x1, y1, slant=0.0, hole=False):
    # TrueType outer contours run clockwise; a counter runs the other way.
    corners = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
    _contour(pen, corners[::-1] if hole else corners, slant)


def _glyph(char, stem, slant):
    """Draw one Arial-like glyph whose straight vertical stems are ``stem`` wide."""
    pen = TTGlyphPen(None)
    bar = round(stem * .85)
    if char == "l":
        _rect(pen, 60, 0, 60 + stem, 730, slant)
    elif char == "I":
        _rect(pen, 80, 0, 80 + stem, 700, slant)
    elif char == "1":
        _rect(pen, 300, 0, 300 + stem, 700, slant)
        _contour(pen, [(300, 700), (300 + stem, 700), (140, 560), (140, 560 - bar)], slant)
    elif char == "H":
        _rect(pen, 80, 0, 80 + stem, 700, slant)
        _rect(pen, 520 - stem, 0, 520, 700, slant)
        _rect(pen, 80, 330, 520, 330 + bar, slant)
    elif char == "E":
        _rect(pen, 80, 0, 80 + stem, 700, slant)
        for y in (0, 320, 700 - bar):
            _rect(pen, 80, y, 480, y + bar, slant)
    elif char == "T":
        _rect(pen, 30, 700 - bar, 530, 700, slant)
        _rect(pen, 280 - stem // 2, 0, 280 + stem - stem // 2, 700, slant)
    elif char == "P":
        _rect(pen, 80, 0, 80 + stem, 700, slant)
        _rect(pen, 80, 360, 470, 700, slant)
        _rect(pen, 80 + stem, 360 + bar, 470 - stem, 700 - bar, slant, hole=True)
    elif char == "A":
        _contour(pen, [(20, 0), (290, 700), (330, 700), (580, 0), (480, 0), (310, 560), (120, 0)], slant)
    else:
        raise AssertionError(char)
    return pen.glyph()


def _truetype(path: Path, *, glyphs=ARIAL_LIKE_GLYPHS, stem=ARIAL_LIKE_STEM, stems=None,
              italic_angle=0.0, units=1000, family="Fictional Stem Sans", extra_glyphs=0,
              symbol_code_page=None, panose_family=None, os2_version=3, os2=True):
    """Build a fictional Arial-like TrueType program with real glyf outlines.

    ``extra_glyphs`` adds unmapped box glyphs, standing in for the bulk of a
    large fully embedded program that the stem rule must never decompile.
    ``symbol_code_page`` sets OS/2 ulCodePageRange1 to the Symbol code page
    (bit 31) or to Latin 1, and ``panose_family`` the PANOSE family type (2 is
    Latin Text, 5 Pictorial); left out, FontBuilder's zero defaults stay.
    ``os2_version`` 0 has no code page ranges, and ``os2=False`` drops the
    table, as some PDF printers do with every subset.
    """
    ps_name = family.replace(" ", "")
    slant = math.tan(math.radians(-italic_angle))
    extra = [f"extra{index:05d}" for index in range(extra_glyphs)]
    order = [".notdef", "space", *(f"g{ord(char):04X}" for char in glyphs), *extra]
    cmap = {32: "space", **{ord(char): f"g{ord(char):04X}" for char in glyphs}}
    notdef = TTGlyphPen(None)
    _rect(notdef, 50, 0, 450, 700)
    outlines = {".notdef": notdef.glyph(), "space": TTGlyphPen(None).glyph()}
    for char in glyphs:
        outlines[f"g{ord(char):04X}"] = _glyph(char, (stems or {}).get(char, stem), slant)
    for name in extra:
        box = TTGlyphPen(None)
        _rect(box, 100, 0, 500, 600)
        outlines[name] = box.glyph()
    font = FontBuilder(units, isTTF=True)
    font.setupGlyphOrder(order)
    font.setupCharacterMap(cmap)
    font.setupGlyf(outlines)
    font.setupHorizontalMetrics({name: (600, 0) for name in order})
    font.setupHorizontalHeader(ascent=800, descent=-200)
    font.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800,
                  usWinDescent=200, sxHeight=500, sCapHeight=700)
    font.setupNameTable({"familyName": family, "styleName": "Regular",
                         "uniqueFontIdentifier": f"{ps_name}-{path.stem}",
                         "fullName": family, "psName": ps_name})
    font.setupPost(italicAngle=italic_angle)
    font.setupMaxp()
    table = font.font["OS/2"]
    if panose_family is not None:
        table.panose.bFamilyType = panose_family
    if symbol_code_page is not None:
        table.ulCodePageRange1 = (1 << 31) if symbol_code_page else 1  # bit 0: Latin 1
    if os2_version == 0:
        table.version = 0
        for field in ("ulCodePageRange1", "ulCodePageRange2", "sxHeight", "sCapHeight",
                      "usDefaultChar", "usBreakChar", "usMaxContext"):
            delattr(table, field)
    if not os2:
        del font.font["OS/2"]
    font.font.recalcTimestamp = False
    font.font["head"].created = font.font["head"].modified = 2_082_844_800
    font.save(str(path))
    return path


def _cid_cff(path: Path, *, fd_stems=((61, 62),), fd_for=None, fd_matrix=None):
    """Re-key a fictional CFF program as a CID font with one Private per FD."""
    named = _cff(path.with_name(path.stem + "-named.otf"))
    font = TTFont(str(named))
    cff = font["CFF "].cff
    top = cff.topDictIndex[0]
    order = font.getGlyphOrder()
    fd_array = FDArrayIndex()
    fd_array.strings = cff.strings
    fd_array.GlobalSubrs = top.GlobalSubrs
    for index, stems in enumerate(fd_stems):
        font_dict = FontDict()
        font_dict.setCFF2(False)
        font_dict.strings = cff.strings
        font_dict.rawDict = {"FontName": f"FictionalCID-{index}"}
        if fd_matrix is not None:
            font_dict.rawDict["FontMatrix"] = list(fd_matrix)
            font_dict.FontMatrix = list(fd_matrix)
        private = PrivateDict(strings=cff.strings)
        private.rawDict = {}
        if stems is not None:
            private.rawDict.update(StdVW=stems[0], StdHW=stems[1])
            private.StdVW, private.StdHW = stems
        font_dict.Private = private
        fd_array.append(font_dict)
    top.FDArray = fd_array
    top.ROS = ("Adobe", "Identity", 0)
    top.CIDCount = len(order)
    select = FDSelect()
    select.format = 3
    select.gidArray = [int((fd_for or {}).get(name, 0)) for name in order]
    top.FDSelect = select
    top.charset = [".notdef"] + [f"cid{index:05d}" for index in range(1, len(order))]
    del top.rawDict["Private"]
    font.save(str(path))
    font.close()
    with TTFont(str(path)) as check:
        assert hasattr(check["CFF "].cff.topDictIndex[0], "FDArray")
    return path


def _expected_code(width_mm):
    choices = [value for value in builder.VALID_DXF_LINEWEIGHTS if value > 0]
    return min(choices, key=lambda value: (abs(value / 100 - width_mm), -value))


@pytest.fixture
def native_fonts(tmp_path, monkeypatch):
    """A fictional selected LibreCAD installation with A/H/P native fonts."""
    from test_librecad_native_linear_font import ROMANS, UNICODE

    installation = tmp_path / "selected-native"
    fonts = installation / "resources/fonts"
    fonts.mkdir(parents=True)
    executable = installation / "LibreCAD.exe"
    executable.write_bytes(b"fictional installation; never run")
    (fonts / "unicode.lff").write_text(UNICODE, encoding="utf-8")
    (fonts / "romans.lff").write_text(ROMANS, encoding="utf-8")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(fonts / "unicode.lff"))
    return executable


@pytest.fixture(autouse=True)
def _fresh_stem_caches():
    builder.reset_text_styles()
    yield
    builder.reset_text_styles()


@pytest.mark.parametrize("rotation,nx,ny", [(0, 3.5, 3.5), (37, 3.5, 3.5), (90, 3.49, 3.5)])
def test_embedded_truetype_pen_is_measured_from_its_own_vertical_stems(tmp_path, rotation, nx, ny):
    path = _truetype(tmp_path / "arial-like.ttf")
    item, resolution = _source(path, text=" H E P ", nx=nx, ny=ny, rotation=rotation)
    original = deepcopy(item)
    proof = builder._source_native_text_lineweight(item, resolution)
    assert item == original
    measured = ARIAL_LIKE_STEM * nx / 1000
    assert proof["native_text_source_stem_rule"] == "truetype_outline_dominant_vertical_stem_max_observed_frame_v1"
    assert proof["native_text_source_stem_pen_source"] == "pen from TrueType outline stem"
    assert proof["native_text_source_stem_outline_vertical"] == ARIAL_LIKE_STEM
    assert proof["native_text_source_stem_units_per_em"] == 1000
    assert proof["native_text_source_stem_width_mm"] == pytest.approx(measured)
    assert proof["native_text_source_stem_widths_mm"]["vertical"] == pytest.approx(measured)
    assert proof["native_text_source_stem_widths_mm"]["horizontal"] is None
    assert proof["native_text_lineweight"] == _expected_code(measured) == 30
    assert proof["native_text_lineweight_mm"] == .30
    assert proof["native_text_lineweight_quantization_error_mm"] == pytest.approx(.30 - measured)
    assert proof["native_text_source_stem_frames_checked"] == 3
    assert proof["native_text_source_stem_font_sha256"] == resolution.asset_sha256
    # The approximation is disclosed exactly like the CFF hint path.
    assert proof["native_text_source_stem_approximation"] is True
    assert proof["native_text_lineweight_source_verified"] is True
    assert proof["native_text_weight_source_ink_parity_verified"] is False
    detail = proof["native_text_source_stem_outline"]
    assert detail["horizontal_stem_measured"] is False
    assert set(detail["measured_units"]) == set("lI1HETP")
    assert all(width == pytest.approx(ARIAL_LIKE_STEM) for width in detail["measured_units"].values())
    assert detail["agreeing_glyphs"] == sorted(detail["measured_units"])
    # "A" is no reference design: it is neither measured nor counted as stemless.
    assert detail["no_stem_glyphs"] == []
    # The proof must survive the report's JSON round trip unchanged.
    assert json.loads(json.dumps(proof)) == proof


def test_truetype_pen_scales_with_units_per_em_and_text_size(tmp_path):
    path = _truetype(tmp_path / "upm2048.ttf", units=2048, stem=194)
    item, resolution = _source(path, text="HEP", nx=2.5, ny=2.5)
    proof = builder._source_native_text_lineweight(item, resolution)
    measured = 194 * 2.5 / 2048
    assert proof["native_text_source_stem_width_mm"] == pytest.approx(measured)
    assert proof["native_text_lineweight"] == _expected_code(measured) == 25


def test_subset_with_two_agreeing_reference_glyphs_is_enough(tmp_path):
    path = _truetype(tmp_path / "subset.ttf", glyphs="EPA")
    item, resolution = _source(path, text="PAPA")
    proof = builder._source_native_text_lineweight(item, resolution)
    assert sorted(proof["native_text_source_stem_outline"]["measured_units"]) == ["E", "P"]


@pytest.mark.parametrize("glyphs,stems,text,reason", [
    ("PA", None, "PAPA", "fewer than 2 reference glyphs"),
    ("A", None, "AA", "fewer than 2 reference glyphs"),
    ("lIHEP", {"l": 40, "I": 200, "H": 120, "E": 60, "P": 160}, "PHP", "reference glyph stems disagree"),
    ("lIHEP", {"l": 8, "I": 8, "H": 8, "E": 8, "P": 8}, "PHP", "fewer than 2 reference glyphs"),
])
def test_truetype_without_agreeing_measurable_stems_cannot_create_a_pen(tmp_path, glyphs, stems, text, reason):
    path = _truetype(tmp_path / "unproved.ttf", glyphs=glyphs, stems=stems)
    item, resolution = _source(path, text=text)
    with pytest.raises(builder._RepresentationImpossible,
                       match="source-bound positive TrueType outline pen") as caught:
        builder._source_native_text_lineweight(item, resolution)
    assert reason in str(caught.value)


def test_box_glyph_truetype_has_no_measurable_stem(deterministic_exact_font):
    # Solid boxes are wider than any admitted stem: exact glyphs remain the route.
    item, resolution = _source(Path(deterministic_exact_font))
    with pytest.raises(builder._RepresentationImpossible,
                       match="TrueType outline pen: .*fewer than 2 reference glyphs"):
        builder._source_native_text_lineweight(item, resolution)


def test_slanted_truetype_stems_are_not_measured_as_vertical(tmp_path):
    path = _truetype(tmp_path / "italic.ttf", italic_angle=-12.0)
    item, resolution = _source(path, text="HEP")
    with pytest.raises(builder._RepresentationImpossible, match="fewer than 2 reference glyphs"):
        builder._source_native_text_lineweight(item, resolution)


def test_truetype_stem_cache_never_replaces_a_fresh_font_byte_check(tmp_path):
    path = _truetype(tmp_path / "changing.ttf")
    item, resolution = _source(path, text="HEP")
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 30
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(builder._RepresentationImpossible, match="bytes changed"):
        builder._source_native_text_lineweight(item, resolution)


def test_cached_truetype_detail_is_not_shared_with_callers(tmp_path):
    path = _truetype(tmp_path / "cached.ttf")
    item, resolution = _source(path, text="HEP")
    first = builder._source_native_text_lineweight(item, resolution)
    first["native_text_source_stem_outline"]["measured_units"]["H"] = 1
    second = builder._source_native_text_lineweight(item, resolution)
    assert second["native_text_source_stem_outline"]["measured_units"]["H"] == pytest.approx(ARIAL_LIKE_STEM)


def test_cid_keyed_cff_uses_the_bound_font_dict_private_stems(tmp_path):
    path = _cid_cff(tmp_path / "cid.otf", fd_stems=((61, 62),))
    item, resolution = _source(path)
    proof = builder._source_native_text_lineweight(item, resolution)
    assert proof["native_text_source_stem_rule"] == "cff_cid_fdarray_private_dominant_stem_max_observed_frame_v1"
    assert proof["native_text_source_stem_pen_source"] == "pen from CID CFF font-dict stem hints"
    assert proof["native_text_source_stem_StdVW"] == 61
    assert proof["native_text_source_stem_StdHW"] == 62
    assert proof["native_text_source_stem_cid_font_dicts"] == [0]
    measured = 62 * 3.5 / 1000
    assert proof["native_text_source_stem_width_mm"] == pytest.approx(measured)
    assert proof["native_text_lineweight"] == _expected_code(measured) == 20
    assert proof["native_text_source_stem_approximation"] is True
    assert proof["native_text_weight_source_ink_parity_verified"] is False
    assert json.loads(json.dumps(proof)) == proof


@pytest.mark.parametrize("fd_stems,fd_for,fd_matrix,reason", [
    ((None,), None, None, "CID font dict 0 has no finite positive StdVW/StdHW"),
    (((61, 62), (90, 91)), {"A": 1}, None, "disagree on dominant stems"),
    (((61, 62), None), {"A": 1}, None, "CID font dict 1 has no finite positive StdVW/StdHW"),
    (((61, 62),), None, (2, 0, 0, 1, 0, 0), "FontMatrix does not match source font units"),
])
def test_cid_keyed_cff_without_bound_stems_cannot_create_a_default_pen(tmp_path, fd_stems, fd_for,
                                                                      fd_matrix, reason):
    path = _cid_cff(tmp_path / "cid-unproved.otf", fd_stems=fd_stems, fd_for=fd_for, fd_matrix=fd_matrix)
    item, resolution = _source(path)
    with pytest.raises(builder._RepresentationImpossible, match="source-bound positive CFF pen") as caught:
        builder._source_native_text_lineweight(item, resolution)
    assert reason in str(caught.value)


def test_cid_font_dict_matrix_replaces_an_unstated_top_matrix(tmp_path):
    # The compiled top dict omits its default matrix; a font dict carrying the
    # font's own 1/1000 units is then the effective matrix, as in FreeType.
    path = _cid_cff(tmp_path / "cid-fd-matrix.otf", fd_matrix=(.001, 0, 0, .001, 0, 0))
    with TTFont(str(path)) as font:
        assert "FontMatrix" not in font["CFF "].cff.topDictIndex[0].rawDict
    item, resolution = _source(path)
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 20


def test_cid_font_dict_used_only_by_unspanned_glyphs_does_not_block_the_span(tmp_path):
    # "H" is not in the span " P A "; its font dict carries no stems.
    path = _cid_cff(tmp_path / "cid-other-fd.otf", fd_stems=((61, 62), None), fd_for={"H": 1})
    item, resolution = _source(path)
    assert builder._source_native_text_lineweight(item, resolution)["native_text_source_stem_cid_font_dicts"] == [0]


def test_name_keyed_cff_proof_keys_are_unchanged(tmp_path):
    """The CFF hint path's proof stays byte-for-byte what main wrote."""
    path = _cff(tmp_path / "named.otf")
    item, resolution = _source(path)
    proof = builder._source_native_text_lineweight(item, resolution)
    assert list(proof) == [
        "native_text_source_stem_rule",
        "native_text_source_stem_font_sha256",
        "native_text_source_stem_units_per_em",
        "native_text_source_stem_StdVW",
        "native_text_source_stem_StdHW",
        "native_text_source_stem_widths_mm",
        "native_text_source_stem_width_mm",
        "native_text_source_stem_frames_checked",
        "native_text_source_stem_approximation",
        "native_text_lineweight",
        "native_text_lineweight_mm",
        "native_text_lineweight_quantization_error_mm",
        "native_text_lineweight_source_verified",
        "native_text_weight_source_ink_parity_verified",
        "native_text_lineweight_plot_semantics",
    ]
    assert proof["native_text_source_stem_rule"] == "cff_private_dominant_stem_max_observed_frame_v1"


def test_non_embedded_font_refusal_says_the_pdf_has_no_font_program(tmp_path):
    path = _truetype(tmp_path / "installed-copy.ttf")
    item, resolution = _source(path, text="HEP")
    # The PDF names the font but embeds no program: MuPDF's stand-in face, not
    # the installed copy, is what the source characters are bound to.
    first, *rest = item.source_char_layout
    item = replace(item, source_char_layout=(replace(first, source_font_program_sha256="f" * 64), *rest))
    resolution = replace(resolution, pdf_font_failure_reason="embedded font stream is empty")
    with pytest.raises(builder._RepresentationImpossible, match="TrueType outline pen") as caught:
        builder._source_native_text_lineweight(item, resolution)
    assert "the PDF does not embed this font" in str(caught.value)


def test_native_pen_rule_identity_names_every_admitted_rule():
    identity = builder.native_text_pen_rule_identity()
    assert identity["rules"] == [
        "cff_private_dominant_stem_max_observed_frame_v1",
        "cff_cid_fdarray_private_dominant_stem_max_observed_frame_v1",
        "truetype_outline_dominant_vertical_stem_max_observed_frame_v1",
    ]
    assert identity["default_pen_allowed"] is False
    assert identity["truetype_reference_glyphs"] == builder._TRUETYPE_STEM_REFERENCE_GLYPHS


def test_resume_identity_binds_the_native_pen_rule():
    from dxf_import_engine import _resume_options_identity
    from pdfcadcore.import_config import ImportConfig

    _identity, payload = _resume_options_identity(ImportConfig.auto(), "R2010", None, True, True)
    assert payload["native_text_pen_rule"] == builder.native_text_pen_rule_identity()


def _page_report(stats):
    report = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    if "page_reports" in report:
        report = json.loads(Path(report["page_reports"][0]).read_text(encoding="utf-8"))
    return report


def test_embedded_truetype_editable_words_are_native_text_with_an_outline_measured_pen(
    native_fonts, tmp_path, monkeypatch,
):
    """The v1.0.117 regression: embedded TrueType notes are editable again.

    The pen comes from the embedded program's own stems, is rechecked against
    the serialized TEXT and fresh font bytes, and stays a disclosed approximation.
    """
    import ezdxf
    import pymupdf
    import dxf_import_engine as engine
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    from pdfcadcore.import_config import ImportConfig

    font = _truetype(tmp_path / "fictional-arial-like.ttf")
    source = tmp_path / "fictional-truetype-notes.pdf"
    content = "HAP PA"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_font(fontname="StemTT", fontfile=str(font))
        page.insert_text((72, 90), content, fontname="StemTT", fontsize=12)
        # Embed a subset, as drawing producers do with Arial: a tagged
        # program that keeps only the used glyphs and carries no cmap.
        pdf.subset_fonts()
        pdf.save(source)
    with pymupdf.open(source) as pdf:
        (xref, _ext, _kind, embedded_name, *_rest), = pdf.get_page_fonts(0)
        assert "+" in embedded_name
        program = TTFont(io.BytesIO(pdf.extract_font(xref)[3]))
        assert "glyf" in program and "cmap" not in program
        program.close()
    original_source = source.read_bytes()
    verifier = exporter._verify_serialized_text_deliveries
    calls = []

    def capture(doc, deliveries, **kwargs):
        verifier(doc, deliveries, **kwargs)
        calls.append((deliveries, kwargs))

    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", capture)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "truetype.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["delivered"] == "text"
    assert stats["text_delivery"]["editable_text_item_count"] == 1
    doc = ezdxf.readfile(output)
    actual, = doc.modelspace().query("TEXT")
    assert actual.dxf.text == content
    assert not doc.layers.get(actual.dxf.layer).is_frozen()
    assert not doc.modelspace().query("INSERT") and not doc.modelspace().query("IMAGE")
    deliveries, kwargs = calls[-1]
    evidence = deliveries[0]["attempts"][-1]["evidence"]
    em = evidence["source_font_em_height"]
    measured = ARIAL_LIKE_STEM / 1000 * em
    assert evidence["native_text_source_stem_rule"] == "truetype_outline_dominant_vertical_stem_max_observed_frame_v1"
    assert evidence["native_text_source_stem_pen_source"] == "pen from TrueType outline stem"
    assert evidence["native_text_source_stem_outline_vertical"] == ARIAL_LIKE_STEM
    # Only glyphs the page uses survive the subset; they are reached through
    # the PDF's own Unicode binding, so "A" (no reference design) is not counted.
    assert sorted(evidence["native_text_source_stem_outline"]["measured_units"]) == ["H", "P"]
    assert evidence["native_text_source_stem_width_mm"] == pytest.approx(measured)
    assert actual.dxf.lineweight == evidence["native_text_lineweight"] == _expected_code(measured)
    # A 12 pt note: a real 0.35-0.40 mm stem, nothing like the faint default pen.
    assert actual.dxf.lineweight >= 35
    assert evidence["native_text_source_stem_approximation"] is True
    assert evidence["native_text_lineweight_source_verified"] is True
    assert evidence["native_text_weight_source_ink_parity_verified"] is False
    assert evidence["parent_source_font_equivalence_verified"] is False
    assert evidence["parent_visual_fidelity_verified"] is False
    assert deliveries[0]["attempts"][-1]["visual_verified"] is False
    checkpoint = next((tmp_path / "truetype_resume").glob("page_*.dxf"))
    physical = ezdxf.readfile(checkpoint)
    verifier(physical, deliveries, **kwargs)
    native, = physical.modelspace().query("TEXT")
    native.dxf.lineweight = 13
    with pytest.raises(RuntimeError, match="source-bound native TEXT lineweight"):
        verifier(physical, deliveries, **kwargs)
    report = _page_report(stats)
    assert report["extra"]["editable_text"]["item_count"] == 1
    assert report["extra"]["editable_text"]["pen_sources"] == {"pen from TrueType outline stem": 1}
    assert source.read_bytes() == original_source


def test_editable_words_report_their_cff_pen_source(native_fonts, tmp_path):
    import pymupdf
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    source = tmp_path / "fictional-courier.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_text((72, 90), "PAPA", fontname="cour", fontsize=12)
        pdf.save(source)
    config = ImportConfig.auto()
    config.text_mode = "text"
    stats = engine.convert(str(source), str(tmp_path / "cff.dxf"), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["delivered"] == "text"
    assert _page_report(stats)["extra"]["editable_text"]["pen_sources"] == {
        "pen from CFF dominant-stem hints": 1}


@pytest.mark.parametrize("name,marker", [
    ("TTFZQP+AMGDT Regular", "gdt"),
    ("AIGDT", "gdt"),
    ("GDT", "gdt"),
    ("SWGDT", "gdt"),
    ("Amgdt_IV25", "gdt"),
    ("gdt_IV50", "gdt"),
    ("Symath", "symath"),
    ("symath_IV25", "symath"),
    ("SWMath", "swmath"),
    ("MT Extra", "mtextra"),
    ("CVWMPP+MT Extra Regular", "mtextra"),
    ("MT-Extra", "mtextra"),
    ("UniversalMath1 BT", "universalmath"),
    ("Marlett", "marlett"),
    ("SymbolMT", "symbol"),
    ("Wingdings-Regular", "wingding"),
    # AutoCAD's electrical reference font: letters at A-D, contact symbols at
    # N, O, W, m and x, behind an ordinary Unicode cmap.
    ("AcadEref", "acaderef"),
    ("DMXKPY+AcadEref Regular", "acaderef"),
    ("Acad Eref", "acaderef"),
    # Pi and icon fonts that mark themselves in OS/2, named for subsets whose
    # OS/2 table a PDF printer stripped.
    ("NKRINO+MS Reference Specialty Regular", "referencespecialty"),
    ("MSReferenceSpecialty", "referencespecialty"),
    ("CommercialPi BT", "commercialpi"),
    ("CommercialPiBT-Regular", "commercialpi"),
    ("MS Outlook", "msoutlook"),
    ("Segoe MDL2 Assets", "mdl2assets"),
    ("Segoe Fluent Icons", "fluenticons"),
])
def test_cad_symbol_font_names_are_symbolic(name, marker):
    # GD&T and math fonts draw symbols at letter codes ("n" is a diameter
    # sign) and keep ordinary capitals, so their stems alone prove nothing.
    item = builder.NormalizedText(id=1, text="n0.50 THRU", normalized="N0.50 THRU", font_name=name)
    evidence = builder._source_font_symbol_evidence(item)
    assert evidence == {
        "source_font_symbolic": True,
        "source_font_symbol_marker": marker,
        "source_font_symbol_name": name,
        "source_font_symbol_name_origin": "pdf_font_name",
    }


@pytest.mark.parametrize("name", [
    "Arial", "ArialMT", "PECJEM+Arial Regular", "Times New Roman", "Courier New", "Cambria Math",
    "ISOCPEUR", "Segoe UI", "Fictional Stem Sans", "Calibri Light", "",
    "RomanS", "Technic", "CityBlueprint", "Commercial Script BT", "Microsoft Sans Serif",
    "Fictional Pi Specialty",
    # Monotype text faces whose names contain the letters of "MT Extra".
    "Gloucester MT Extra Condensed", "GillSansMT-ExtraCondensedBold", "ABCDEF+Gill Sans MT Ext Condensed Bold",
])
def test_letter_font_names_are_not_symbolic(name):
    item = builder.NormalizedText(id=1, text="NOTE", normalized="NOTE", font_name=name)
    assert builder._source_font_symbol_evidence(item) is None


def test_bound_program_name_marks_a_renamed_cad_symbol_font(tmp_path):
    # The PDF calls the font "F1", but the embedded program names itself a
    # GD&T font. Its capitals agree on a stem, so the stem rule alone would
    # admit a pen: only the symbol-font check keeps the span out of TEXT.
    path = _truetype(tmp_path / "renamed-gdt.ttf", family="Fictional GDT")
    item, resolution = _source(path, text="HEP")
    item = replace(item, font_name="F1")
    resolution = replace(resolution, source_name="F1", family="F1")
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 30
    evidence = builder._source_font_symbol_evidence(item, resolution)
    assert evidence["source_font_symbol_marker"] == "gdt"
    assert evidence["source_font_symbol_name_origin"] == "font_program_name_table"
    assert evidence["source_font_symbol_name"] in {"Fictional GDT", "FictionalGDT"}
    # A program whose bytes changed proves nothing; the PDF's name decides.
    path.write_bytes(path.read_bytes() + b"changed")
    builder.reset_text_styles()
    assert builder._source_font_symbol_evidence(item, resolution) is None


def test_letter_program_names_do_not_mark_a_font_symbolic(tmp_path):
    path = _truetype(tmp_path / "letters.ttf")
    item, resolution = _source(path, text="HEP")
    assert builder._source_font_symbol_evidence(item, resolution) is None


def test_truetype_measurement_decompiles_only_reference_glyphs(tmp_path, monkeypatch):
    # A large fully embedded program must not be expanded glyph by glyph:
    # the stem rule draws only the reference letters it finds.
    from fontTools.ttLib.tables import _g_l_y_f

    path = _truetype(tmp_path / "large.ttf", extra_glyphs=3000)
    item, resolution = _source(path, text="HEP")
    expanded = []
    original_expand = _g_l_y_f.Glyph.expand

    def counting_expand(self, glyf_table):
        if hasattr(self, "data"):
            expanded.append(self)
        return original_expand(self, glyf_table)

    monkeypatch.setattr(_g_l_y_f.Glyph, "expand", counting_expand)
    proof = builder._source_native_text_lineweight(item, resolution)
    assert proof["native_text_lineweight"] == 30
    assert sorted(proof["native_text_source_stem_outline"]["measured_units"]) == sorted("lI1HETP")
    # Reference glyphs, plus the few the exact binding and cmap checks touch;
    # never the 3000 unmapped ones.
    assert len(expanded) < 40


def test_cad_symbol_truetype_words_keep_exact_glyphs_in_editable_text(native_fonts, tmp_path):
    """A GD&T font's words never become LibreCAD-font TEXT, whatever their stems.

    The letter font on the same page still becomes editable native TEXT, so
    the refusal is per span, reported, and keeps the searchable source string.
    """
    import ezdxf
    import pymupdf
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    symbol_font = _truetype(tmp_path / "fictional-gdt.ttf", family="Fictional GDT")
    letter_font = _truetype(tmp_path / "fictional-letters.ttf")
    source = tmp_path / "fictional-gdt-callout.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_font(fontname="SymTT", fontfile=str(symbol_font))
        page.insert_font(fontname="StemTT", fontfile=str(letter_font))
        page.insert_text((72, 90), "HAP PA", fontname="SymTT", fontsize=12)
        page.insert_text((72, 190), "PA HAP", fontname="StemTT", fontsize=12)
        pdf.subset_fonts()
        pdf.save(source)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "gdt.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(native_fonts))
    assert stats["text_delivery"]["editable_text_item_count"] == 1
    doc = ezdxf.readfile(output)
    texts = list(doc.modelspace().query("TEXT"))
    visible = [t for t in texts if not doc.layers.get(t.dxf.layer).is_frozen()]
    assert [t.dxf.text for t in visible] == ["PA HAP"]
    assert "HAP PA" in [t.dxf.text for t in texts if t not in visible]
    assert doc.modelspace().query("INSERT")
    report = _page_report(stats)
    assert report["extra"]["editable_text"]["pen_sources"] == {"pen from TrueType outline stem": 1}
    items = report["extra"]["text_representation_delivery"]["items"]
    symbol_item, = [i for i in items if any(
        a.get("evidence", {}).get("source_font_symbolic") for a in i.get("attempts", []))]
    assert symbol_item["final_representation"] == "glyphs"
    text_attempt, = [a for a in symbol_item["attempts"] if a.get("attempted_representation") == "text"]
    evidence = text_attempt["evidence"]
    assert evidence["source_font_symbol_marker"] == "gdt"
    assert evidence["source_font_symbol_name_origin"] == "pdf_font_name"
    assert text_attempt["outcome"] != "delivered"
    # No pen is measured for a span that cannot be LibreCAD-font TEXT.
    assert "native_text_source_stem_rule" not in evidence
    assert evidence.get("parent_native_font_substitution_accepted") is not True


def test_bound_program_name_marks_a_renamed_acaderef_font(tmp_path):
    # AcadEref draws letters at A-D but contact symbols at N, O, W, m and x;
    # its B, D, b and d agree on a stem, so only its name keeps it out.
    path = _truetype(tmp_path / "renamed-eref.ttf", family="Fictional AcadEref")
    item, resolution = _source(path, text="HEP")
    item = replace(item, font_name="F2")
    resolution = replace(resolution, source_name="F2", family="F2")
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 30
    evidence = builder._source_font_symbol_evidence(item, resolution)
    assert evidence["source_font_symbol_marker"] == "acaderef"
    assert evidence["source_font_symbol_name_origin"] == "font_program_name_table"


@pytest.mark.parametrize("symbol_code_page,panose_family,os2_version,marker", [
    # MS Reference Specialty, MS Outlook, Wingdings and Symbol set both.
    (True, 5, 3, "os2_symbol_code_page"),
    # Marlett and AIGDT declare only the Symbol code page.
    (True, 0, 3, "os2_symbol_code_page"),
    # CommercialPi, MT Extra and UniversalMath are PANOSE Pictorial only.
    (False, 5, 3, "panose_pictorial"),
    # A version 0 OS/2 table has no code page ranges; PANOSE still marks it.
    (None, 5, 0, "panose_pictorial"),
])
def test_truetype_os2_marks_a_symbol_font_whatever_its_name(tmp_path, symbol_code_page, panose_family,
                                                            os2_version, marker):
    # A pi font whose name is on no list, typed as plain letters: its letter
    # codes draw symbols, yet the subset's reference glyphs agree on a stem.
    path = _truetype(tmp_path / "pi.ttf", family="Fictional Pi Specialty",
                     symbol_code_page=symbol_code_page, panose_family=panose_family,
                     os2_version=os2_version)
    item, resolution = _source(path, text="HEP")
    item = replace(item, font_name="ABCDEF+Fictional Pi Specialty")
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 30
    evidence = builder._source_font_symbol_evidence(item, resolution)
    assert evidence["source_font_symbolic"] is True
    assert evidence["source_font_symbol_marker"] == marker
    assert evidence["source_font_symbol_name"] == "ABCDEF+Fictional Pi Specialty"
    assert evidence["source_font_symbol_name_origin"] == "font_program_os2_table"
    assert evidence["source_font_symbol_rule"] == "truetype_os2_symbol_code_page_or_panose_pictorial_v1"
    assert evidence["source_font_symbol_os2"] == {
        "table_version": os2_version,
        "symbol_code_page": bool(symbol_code_page),
        "panose_family_type": panose_family,
    }
    assert json.loads(json.dumps(evidence)) == evidence
    # Changed bytes prove nothing: the program is never read unverified.
    path.write_bytes(path.read_bytes() + b"changed")
    builder.reset_text_styles()
    assert builder._source_font_symbol_evidence(item, resolution) is None


@pytest.mark.parametrize("symbol_code_page,panose_family", [
    (False, 2),  # Arial, Times New Roman, ISOCPEUR, RomanS: Latin Text
    (None, None),  # zeros: no classification at all
    (False, 3),  # Latin Hand Written
    (False, 4),  # Latin Decorative
])
def test_truetype_os2_of_a_text_font_is_not_symbolic(tmp_path, symbol_code_page, panose_family):
    path = _truetype(tmp_path / "text.ttf", symbol_code_page=symbol_code_page, panose_family=panose_family)
    item, resolution = _source(path, text="HEP")
    assert builder._source_font_symbol_evidence(item, resolution) is None
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 30


def test_truetype_without_os2_or_a_listed_name_is_not_recognized(tmp_path):
    """The documented limit: names and OS/2 marks are the only evidence.

    Some PDF printers strip OS/2 from every TrueType subset. A symbol font
    embedded that way, under a name on no list, is not recognized; the
    validation note and the report say so instead of claiming otherwise.
    """
    path = _truetype(tmp_path / "pi-no-os2.ttf", family="Fictional Pi Specialty",
                     symbol_code_page=True, panose_family=5, os2=False)
    with TTFont(str(path)) as program:
        assert "OS/2" not in program
    item, resolution = _source(path, text="HEP")
    assert builder._bound_program_identity(resolution)["os2"] is None
    assert builder._source_font_symbol_evidence(item, resolution) is None


def test_cff_os2_marks_are_not_read(tmp_path):
    # A CFF program's OS/2 is not evidence: one wrapped from a PDF's bare CFF
    # program is synthesized. CFF delivery stays exactly as on main.
    from test_librecad_native_text_weight import _cff

    path = _cff(tmp_path / "pictorial-cff.otf")
    with TTFont(str(path)) as font:
        font["OS/2"].panose.bFamilyType = 5
        font["OS/2"].ulCodePageRange1 = 1 << 31
        font.save(str(path))
    item, resolution = _source(path)
    assert builder._bound_program_identity(resolution)["os2"] is None
    assert builder._source_font_symbol_evidence(item, resolution) is None
    assert builder._source_native_text_lineweight(item, resolution)["native_text_lineweight"] == 18


def test_native_pen_rule_identity_binds_the_symbol_font_gate():
    identity = builder.native_text_pen_rule_identity()
    assert "acaderef" in identity["cad_symbol_font_markers"]
    assert "commercialpi" in identity["pi_font_markers"]
    assert "wingding" in identity["symbol_font_markers"]
    assert identity["truetype_symbol_os2_rule"] == "truetype_os2_symbol_code_page_or_panose_pictorial_v1"


def _symbol_page_report(native_fonts, tmp_path, symbol_font, *, simple=False, text="HEP HEP"):
    """Convert one page: a symbol-font span above a letter-font span."""
    import ezdxf
    import pymupdf
    import dxf_import_engine as engine
    from pdfcadcore.import_config import ImportConfig

    letter_font = _truetype(tmp_path / "fictional-letters.ttf")
    source = tmp_path / "fictional-symbol-page.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_font(fontname="SymTT", fontfile=str(symbol_font), set_simple=simple)
        page.insert_font(fontname="StemTT", fontfile=str(letter_font), set_simple=simple)
        page.insert_text((72, 90), text, fontname="SymTT", fontsize=12)
        page.insert_text((72, 190), "PA HAP", fontname="StemTT", fontsize=12)
        pdf.subset_fonts()
        pdf.save(source)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "symbol.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=True, librecad_executable=str(native_fonts))
    doc = ezdxf.readfile(output)
    texts = list(doc.modelspace().query("TEXT"))
    visible = [t.dxf.text for t in texts if not doc.layers.get(t.dxf.layer).is_frozen()]
    hidden = [t.dxf.text for t in texts if doc.layers.get(t.dxf.layer).is_frozen()]
    report = _page_report(stats)
    items = report["extra"]["text_representation_delivery"]["items"]
    symbol_items = [i for i in items if any(
        a.get("evidence", {}).get("source_font_symbolic") for a in i.get("attempts", []))]
    return stats, doc, visible, hidden, report, symbol_items


@pytest.mark.parametrize("simple", [False, True], ids=["type0", "simple_truetype"])
def test_acaderef_words_keep_exact_glyphs_in_editable_text(native_fonts, tmp_path, simple):
    """Review fixtures a01/b02: AcadEref words became TEXT reading 'BD xN bd'.

    Embedded as a Type0 subset or as a simple TrueType font, a font named
    AcadEref keeps exact Glyph outlines; the letter note beside it is still
    editable TEXT.
    """
    symbol_font = _truetype(tmp_path / "fictional-acaderef.ttf", family="Fictional AcadEref")
    stats, doc, visible, hidden, report, symbol_items = _symbol_page_report(
        native_fonts, tmp_path, symbol_font, simple=simple)
    assert stats["text_delivery"]["editable_text_item_count"] == 1
    assert visible == ["PA HAP"]
    assert "HEP HEP" in hidden
    assert doc.modelspace().query("INSERT")
    assert report["extra"]["editable_text"]["pen_sources"] == {"pen from TrueType outline stem": 1}
    symbol_item, = symbol_items
    assert symbol_item["final_representation"] == "glyphs"
    text_attempt, = [a for a in symbol_item["attempts"] if a.get("attempted_representation") == "text"]
    assert text_attempt["evidence"]["source_font_symbol_marker"] == "acaderef"
    assert "native_text_source_stem_rule" not in text_attempt["evidence"]


@pytest.mark.parametrize("symbol_code_page,panose_family,marker", [
    (True, 5, "os2_symbol_code_page"),  # MS Reference Specialty-like
    (False, 5, "panose_pictorial"),  # CommercialPi-like
])
def test_os2_marked_pi_font_words_keep_exact_glyphs_in_editable_text(
    native_fonts, tmp_path, symbol_code_page, panose_family, marker,
):
    """Review fixture a02: pi fonts typed as plain letters became TEXT.

    The font's name is on no list, and its subset's letters agree on a stem.
    The embedded program's own OS/2 table still marks it as a symbol font,
    so its words stay exact Glyph outlines.
    """
    symbol_font = _truetype(tmp_path / "fictional-pi.ttf", family="Fictional Pi Specialty",
                            symbol_code_page=symbol_code_page, panose_family=panose_family)
    stats, doc, visible, hidden, report, symbol_items = _symbol_page_report(
        native_fonts, tmp_path, symbol_font)
    assert stats["text_delivery"]["editable_text_item_count"] == 1
    assert visible == ["PA HAP"]
    assert "HEP HEP" in hidden
    assert report["extra"]["editable_text"]["pen_sources"] == {"pen from TrueType outline stem": 1}
    symbol_item, = symbol_items
    assert symbol_item["final_representation"] == "glyphs"
    text_attempt, = [a for a in symbol_item["attempts"] if a.get("attempted_representation") == "text"]
    evidence = text_attempt["evidence"]
    assert evidence["source_font_symbol_marker"] == marker
    assert evidence["source_font_symbol_name_origin"] == "font_program_os2_table"
    assert evidence["source_font_symbol_os2"]["panose_family_type"] == panose_family
    assert "native_text_source_stem_rule" not in evidence
    assert evidence.get("parent_native_font_substitution_accepted") is not True
    # The report states the limit instead of claiming every symbol font is caught.
    note = report["extra"]["editable_text"]["note"]
    assert "OS/2" in note and "not recognized" in note

"""Native LFF cursor advance is not a FIT endpoint or an ink-box width."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import ezdxf
import pytest

import dxf_text_builder as builder
from pdfcadcore.primitives import NormalizedText


LFF = """# Format: LibreCAD Font 1
# Encoding: UTF-8
# LetterSpacing: 3
# WordSpacing: 6.75

[0050]
0,0;0,9;2.5,9;2.5,4,A-1;0,4

[0061]
0,0;4,0;4,5;0,5

[0067]
C0061
0,-3;4,-3

[0065]
C0061

[0031]
0,0;2,9

[0042]
C0050
-2,0;-1,1

[004E]
-3,0;-2,1

"""


@pytest.fixture
def bound_lff(tmp_path, monkeypatch):
    root = tmp_path / "native"
    executable = root / "LibreCAD.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"hermetic selected native installation")
    font = root / "resources/fonts/unicode.lff"
    font.parent.mkdir(parents=True)
    font.write_text(LFF, encoding="utf-8")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(font))
    builder.reset_text_styles()
    resolution = builder._resolve_librecad_unicode_lff(str(executable), fresh=True)
    assert resolution.verified and resolution.layout_metrics is not None
    assert resolution.sha256 == hashlib.sha256(font.read_bytes()).hexdigest()
    return resolution, font, executable


def _entity(doc, text, *, rotation=0.0, height=1.940952721439467):
    if not doc.styles.has_entry("unicode"):
        doc.styles.new("unicode", dxfattribs={"font": "unicode"})
    return doc.modelspace().add_text(text, dxfattribs={
        "style": "unicode", "insert": (24.97665697733561, 268.3085366143121),
        "height": height, "rotation": rotation,
    })


def test_proven_leading_space_fit_failure_is_replaced_by_measured_full_advance(bound_lff, tmp_path):
    resolution, _font, _executable = bound_lff
    text = " " * 70 + "Page    1"
    advance, ink = resolution.layout_metrics.run(text)
    assert advance == 533.5
    assert ink == (472.5, -3.0, 530.5, 9.0)
    source_advance = 163.86463720533578
    # Reproduce the pinned native FIT equation independently: source text is
    # not rebased, so its leading offset produces the actual 1523.773... edge.
    assert 24.97665697733561 + ink[2] * source_advance / (ink[2] - ink[0]) == pytest.approx(1523.773036933036)
    doc = ezdxf.new("R2018")
    text_entity = _entity(doc, text)
    measured = builder._fit_text_advance(text_entity, source_advance, parent_fit_alignment=True, native_lff=resolution)
    assert measured == pytest.approx(source_advance)
    assert text_entity.dxf.text == text and text_entity.dxf.halign == 0
    assert tuple(text_entity.dxf.insert)[:2] == (24.97665697733561, 268.3085366143121)
    for name in ("first.dxf", "fresh.dxf"):
        output = tmp_path / name
        doc.saveas(output)
        doc = ezdxf.readfile(output)
        text_entity = doc.modelspace().query("TEXT").first
        proof = builder._librecad_native_layout(text_entity, resolution)
        assert text_entity.dxf.text == text
        assert proof["native_lff_actual_advance"] == pytest.approx(source_advance)
        assert proof["native_lff_raw_advance"] == 533.5
        # Safe native ink envelope remains inside the source cursor advance;
        # it does not impose a source-font glyph-shape equivalence claim.
        assert proof["native_lff_rotated_ink_envelope"][2] < 24.97665697733561 + source_advance


@pytest.mark.parametrize(("text", "advance", "ink"), [
    (" P ", 21.5, (6.75, 0, 11.75, 9)),
    ("   ", 20.25, None),
    ("B", 8, (-2, 0, 5, 9)),
    ("N P", 14.75, (-3, 0, 11.75, 9)),
])
def test_native_bearings_references_spaces_and_negative_max_x(text, advance, ink):
    assert builder._LibreCadLffMetrics(LFF).run(text) == (advance, ink)


@pytest.mark.parametrize("rotation", [0, 33, 90, 180, 270])
def test_physical_left_fields_measure_advance_without_changing_source_transform(bound_lff, tmp_path, rotation):
    resolution, _font, _executable = bound_lff
    doc = ezdxf.new("R2018")
    entity = _entity(doc, "  P a  ", rotation=rotation)
    before = (entity.dxf.text, tuple(entity.dxf.insert), entity.dxf.height, entity.dxf.rotation)
    builder._fit_text_advance(entity, 22.5, parent_fit_alignment=True, native_lff=resolution)
    path = tmp_path / "rotated.dxf"
    doc.saveas(path)
    actual = ezdxf.readfile(path).modelspace().query("TEXT").first
    assert (actual.dxf.text, tuple(actual.dxf.insert), actual.dxf.height, actual.dxf.rotation) == before
    proof = builder._librecad_native_layout(actual, resolution)
    assert proof["native_lff_actual_advance"] == pytest.approx(22.5)
    assert all(math.isfinite(value) for value in proof["native_lff_rotated_ink_envelope"])
    actual.dxf.width *= 2
    assert builder._librecad_native_layout(actual, resolution)["native_lff_actual_advance"] == pytest.approx(45)


@pytest.mark.parametrize("body", ["C0050", "C0051", "0,0;nan,1", "0,0;1,1,Ano", "[0051]\n0,0;1,1"])
def test_cyclic_missing_or_uncertain_glyph_metrics_cannot_certify_native_layout(body):
    metrics = builder._LibreCadLffMetrics(f"# Format: LibreCAD Font 1\n[0050]\n{body}\n\n")
    with pytest.raises(ValueError):
        metrics.run("P")


@pytest.mark.parametrize("content", ["\t", "\n", "\u00a0", "\U0001f642"])
def test_only_literal_ascii_space_uses_native_word_spacing(content):
    with pytest.raises(ValueError):
        builder._LibreCadLffMetrics(LFF).run(content)


@pytest.mark.parametrize("change", [
    {"halign": 5}, {"valign": 1}, {"oblique": 1},
    {"text_generation_flag": 2}, {"extrusion": (0, 0, -1)},
    {"height": 9e-6}, {"width": 1e-8},
])
def test_native_layout_rejects_unsupported_physical_transforms(bound_lff, change):
    resolution, _font, _executable = bound_lff
    entity = _entity(ezdxf.new("R2018"), "P")
    entity.update_dxf_attribs(change)
    with pytest.raises(ValueError):
        builder._librecad_native_layout(entity, resolution)


def test_fresh_byte_binding_recomputes_spacing_even_with_preserved_file_mtime(bound_lff):
    import os

    resolution, font, executable = bound_lff
    stat = font.stat()
    font.write_text(LFF.replace("WordSpacing: 6.75", "WordSpacing: 7.75"), encoding="utf-8")
    os.utime(font, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    fresh = builder._resolve_librecad_unicode_lff(str(executable), fresh=True)
    assert fresh.sha256 != resolution.sha256
    assert fresh.layout_metrics.run(" P")[0] == 15.75
    assert resolution.layout_metrics.run(" P")[0] == 14.75


def test_missing_native_metrics_keeps_search_string_and_anchor_without_certifying_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "_resolve_librecad_unicode_lff", lambda *args, **kwargs: builder._LibreCadLffResolution())
    doc = ezdxf.new("R2018")
    item = NormalizedText(1, "  Page 1  ", "PAGE 1", insertion=(10, 12), font_size=3, advance_width=25)
    record = builder._write_search_text_companion(item, doc.modelspace(), "SEARCH", is_r12=False)
    assert record["status"] == "written" and record["native_lff_layout_verified"] is False
    entity = doc.entitydb[record["handle"]]
    assert entity.dxf.text == item.text and tuple(entity.dxf.insert)[:2] == item.insertion
    assert (entity.dxf.halign, entity.dxf.valign, entity.dxf.width) == (0, 0, 1)


def test_fit_endpoint_alone_no_longer_proves_a_label_width():
    from ezdxf.enums import TextEntityAlignment

    doc = ezdxf.new("R2018")
    entity = _entity(doc, " P")
    entity.set_placement(tuple(entity.dxf.insert)[:2], (50, 268.3085366143121), align=TextEntityAlignment.FIT)
    item = NormalizedText(1, " P", "P", insertion=tuple(entity.dxf.insert)[:2])
    _type_ok, visual, proof = builder._verify_label(entity, item, height=entity.dxf.height,
        target_width=25.02334302266439, measured_width=999, width_source="source_advance")
    assert visual is False and proof["fit_alignment_verified"] is False and proof["width_verified"] is False


@pytest.mark.parametrize("mutation", ["width", "alignment", "source_anchor", "font_bytes"])
def test_serialized_search_layout_replays_actual_fields_and_fresh_font(bound_lff, tmp_path, mutation):
    from librecad_pdf_importer.exporters import dxf_exporter as exporter

    _resolution, font, executable = bound_lff
    doc = ezdxf.new("R2018")
    layer = doc.layers.new("SEARCH", dxfattribs={"plot": 0})
    layer.freeze()
    item = NormalizedText(1, "  Page 1  ", "PAGE 1", insertion=(10, 12), font_size=3, advance_width=25)
    search = builder._write_search_text_companion(item, doc.modelspace(), "SEARCH", is_r12=False,
                                                librecad_executable=str(executable))
    path = tmp_path / "search.dxf"
    doc.saveas(path)
    actual = ezdxf.readfile(path)
    deliveries = [{"verified": True, "search_text": search}]
    exporter._verify_serialized_search_text(actual, deliveries, librecad_executable=str(executable))
    assert search["status"] == "written"
    entity = actual.entitydb[search["handle"]]
    if mutation == "width":
        entity.dxf.width *= 2
    elif mutation == "alignment":
        entity.dxf.halign = 5
    elif mutation == "source_anchor":
        entity.dxf.insert = (11, 12, 0)
    else:
        font.write_text(LFF.replace("WordSpacing: 6.75", "WordSpacing: 7.75"), encoding="utf-8")
    exporter._verify_serialized_search_text(actual, deliveries, librecad_executable=str(executable))
    assert search["status"] == "mismatch"
    assert deliveries[0]["verified"] is True  # A companion cannot certify/cost visible paint.


@pytest.mark.parametrize("editable", [False, True], ids=["hidden-search", "visible-editable"])
def test_real_pdf_window_pipeline_retains_full_string_with_independent_physical_native_advance(
    bound_lff, tmp_path, monkeypatch, editable,
):
    import json
    import pymupdf
    import dxf_import_engine as engine
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    from pdfcadcore.import_config import ImportConfig

    resolution, font, executable = bound_lff
    unicode_digest = resolution.sha256
    # The legacy FIT regression includes an arc-bearing P. The corrected
    # native route must use a bound linear face when horizontal fitting is
    # anisotropic, retaining these exact extrema and full advance.
    font.with_name("romans.lff").write_text(
        LFF.replace("0,0;0,9;2.5,9;2.5,4,A-1;0,4", "0,0;0,9;5,9;5,4;0,4")
        + "[0048]\n0,0;0,9;5,9;5,0\n\n", encoding="utf-8",
    )
    content = " " * 70 + "Page    1  "
    source = tmp_path / "fictional-spacing.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=1000, height=400)
        page.insert_text((72, 90), content, fontname="helv", fontsize=12)
        pdf.save(source)
    original_pdf = source.read_bytes()
    with pymupdf.open(source) as pdf:
        span = pdf[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        assert span["text"] == content
        # Use the actual saved PDF's float32 source frame, rather than an ideal
        # font width recomputed before PDF serialization.
        source_advance = (span["bbox"][2] - span["origin"][0]) * 25.4 / 72
    verifier = exporter._verify_serialized_text_deliveries
    calls = []

    def capture(doc, deliveries, **kwargs):
        verifier(doc, deliveries, **kwargs)
        calls.append((deliveries, kwargs))

    monkeypatch.setattr(exporter, "_verify_serialized_text_deliveries", capture)
    config = ImportConfig.auto()
    config.text_mode = "text"
    output = tmp_path / "assembled.dxf"
    stats = engine.convert(str(source), str(output), config=config, resumable=True,
                           editable_text=editable, librecad_executable=str(executable))
    doc = ezdxf.readfile(output)
    native, = doc.modelspace().query("TEXT")
    assert native.dxf.text == content
    assert native.dxf.halign == native.dxf.valign == 0
    assert doc.layers.get(native.dxf.layer).is_frozen() is (not editable)
    assert native.dxf.style.startswith("romans#" if editable else "unicode#")
    if editable:
        resolution = builder._resolve_librecad_lff(str(executable), font_name="romans", fresh=True)
    proof = builder._librecad_native_layout(native, resolution)
    assert proof["native_lff_actual_advance"] == pytest.approx(source_advance, abs=1e-9)
    report = json.loads(Path(stats["import_report_path"]).read_text(encoding="utf-8"))
    assert stats["text_delivery"]["delivered"] == ("text" if editable else "glyphs")
    assert report["text_items_degraded_total"] == 0
    assert calls
    # A real exporter authority/session can replay the physical page. Changing
    # the encoded width then fails a freshly measured native advance, even
    # though the old evidence booleans and old expected width remain untouched.
    deliveries, kwargs = calls[-1]
    checkpoint = next((tmp_path / "assembled_resume").glob("page_*.dxf"))
    physical_page = ezdxf.readfile(checkpoint)
    if editable:
        verifier(physical_page, deliveries, **kwargs)
        physical_page.modelspace().query("TEXT").first.dxf.width *= 2
        with pytest.raises(RuntimeError, match="LibreCAD native text evidence"):
            verifier(physical_page, deliveries, **kwargs)
    for name in ("first-save.dxf", "fresh-save.dxf"):
        path = tmp_path / name
        doc.saveas(path)
        doc = ezdxf.readfile(path)
        text, = doc.modelspace().query("TEXT")
        assert text.dxf.text == content
        assert builder._librecad_native_layout(text, resolution)["native_lff_actual_advance"] == pytest.approx(source_advance, abs=1e-9)
    assert source.read_bytes() == original_pdf
    assert hashlib.sha256(font.read_bytes()).hexdigest() == unicode_digest

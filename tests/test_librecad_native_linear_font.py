"""Executable-bound linear native fonts avoid LibreCAD's anisotropic arc gaps.

All native installation/PDF data are fictional. No native application is run.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import ezdxf
import pytest

import dxf_text_builder as builder


UNICODE = """# Format: LibreCAD Font 1
# Encoding: UTF-8
# LetterSpacing: 3
# WordSpacing: 6.75

[0048]
0,0;0,9
0,4.5;6,4.5
6,0;6,9

[0050]
0,0;0,9;2.5,9;2.5,4,A-1;0,4

[0041]
0,0;3,9;6,0
1,3;5,3

"""

ROMANS = UNICODE.replace(
    "0,0;0,9;2.5,9;2.5,4,A-1;0,4",
    "0,0;0,9;5,9;5,4;0,4",
)


@pytest.fixture
def native_fonts(tmp_path, monkeypatch):
    installation = tmp_path / "selected-native"
    installation.mkdir()
    executable = installation / "LibreCAD.exe"
    executable.write_bytes(b"hermetic native installation; never executed")
    fonts = installation / "resources/fonts"
    fonts.mkdir(parents=True)
    unicode = fonts / "unicode.lff"
    romans = fonts / "romans.lff"
    unicode.write_text(UNICODE, encoding="utf-8")
    romans.write_text(ROMANS, encoding="utf-8")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(executable))
    monkeypatch.setenv("BCS_LIBRECAD_UNICODE_LFF", str(unicode))
    builder.reset_text_styles()
    return executable, unicode, romans


def _entity(resolution, *, text=" P A ", height=9.0, rotation=0.0):
    family = resolution.evidence(text)["librecad_lff_font_family"]
    doc = ezdxf.new("R2018")
    doc.styles.add(family, font=family)
    entity = doc.modelspace().add_text(text, dxfattribs={
        "style": family, "height": height, "insert": (11.25, 23.5),
        "rotation": rotation,
    })
    return doc, entity


def test_exact_isotropic_unicode_is_retained_without_requiring_romans(native_fonts):
    executable, unicode, romans = native_fonts
    romans.unlink()
    # P's native maxX5 + spacing3 gives advance8 at native height9.
    selected = builder._select_librecad_native_lff("P", 9.0, 8.0, str(executable))
    assert Path(selected.path).resolve() == unicode.resolve()
    doc, entity = _entity(selected, text="P")
    builder._fit_text_advance(entity, 8.0, parent_fit_alignment=True, native_lff=selected)
    proof = builder._librecad_native_layout(entity, selected)
    assert proof["native_lff_font_family"] == "unicode"
    assert proof["native_lff_stroke_geometry_safe"] is True
    assert proof["native_lff_actual_advance"] == 8.0
    assert len(doc.modelspace()) == 1


@pytest.mark.parametrize("rotation", [0.0, 33.0, 90.0, 180.0])
def test_anisotropic_arc_font_selects_bound_linear_romans_and_preserves_physical_source(
    native_fonts, tmp_path, rotation,
):
    executable, unicode, romans = native_fonts
    text = " P A "
    selected = builder._select_librecad_native_lff(text, 9.0, 60.0, str(executable))
    assert Path(selected.path).resolve() == romans.resolve()
    assert selected.sha256 == hashlib.sha256(romans.read_bytes()).hexdigest()
    assert selected.sha256 != hashlib.sha256(unicode.read_bytes()).hexdigest()
    doc, entity = _entity(selected, text=text, rotation=rotation)
    original = (entity.dxf.text, tuple(entity.dxf.insert), entity.dxf.height, entity.dxf.rotation)
    builder._fit_text_advance(entity, 60.0, parent_fit_alignment=True, native_lff=selected)
    for name in ("first.dxf", "fresh.dxf"):
        output = tmp_path / name
        doc.saveas(output)
        doc = ezdxf.readfile(output)
        entity, = doc.modelspace().query("TEXT")
        assert (entity.dxf.text, tuple(entity.dxf.insert), entity.dxf.height, entity.dxf.rotation) == original
        assert entity.dxf.halign == entity.dxf.valign == 0
        assert doc.styles.get(entity.dxf.style).dxf.font.lower() == "romans"
        proof = builder._librecad_native_layout(entity, selected)
        assert proof["native_lff_font_family"] == "romans"
        assert proof["native_lff_stroke_geometry_safe"] is True
        assert proof["native_lff_actual_advance"] == pytest.approx(60.0, abs=1e-12)
        assert all(math.isfinite(v) for v in proof["native_lff_rotated_ink_envelope"])


@pytest.mark.parametrize("invalid", ["missing-file", "missing-glyph", "arc-reference", "shifted-cap"])
def test_missing_or_unqualified_romans_cannot_certify_anisotropic_unicode(native_fonts, invalid):
    executable, _unicode, romans = native_fonts
    if invalid == "missing-file":
        # An unrelated installed font cannot become an unreported substitute.
        romans.with_name("simplex.lff").write_text(ROMANS, encoding="utf-8")
        romans.unlink()
    elif invalid == "missing-glyph":
        romans.write_text(ROMANS.replace("[0050]", "[0051]"), encoding="utf-8")
    elif invalid == "arc-reference":
        romans.write_text(ROMANS.replace("0,0;0,9;5,9;5,4;0,4", "C0041").replace(
            "0,0;3,9;6,0\n1,3;5,3", "0,0;0,9;2.5,9;2.5,4,A-1;0,4"), encoding="utf-8")
    else:
        romans.write_text(ROMANS.replace("0,0;0,9\n0,4.5;6,4.5\n6,0;6,9", "0,1;0,10\n0,5.5;6,5.5\n6,1;6,10"), encoding="utf-8")
    with pytest.raises(builder._RepresentationImpossible):
        builder._select_librecad_native_lff("P", 9.0, 12.0, str(executable))


def test_selected_romans_comes_from_the_same_installation_and_rechecks_fresh_bytes(native_fonts):
    executable, unicode, romans = native_fonts
    selected = builder._select_librecad_native_lff(" P ", 9.0, 60.0, str(executable))
    assert Path(selected.path).resolve().parent == unicode.resolve().parent
    original = romans.stat()
    old_advance = selected.layout_metrics.run(" P ")[0]
    romans.write_text(ROMANS.replace("WordSpacing: 6.75", "WordSpacing: 7.75"), encoding="utf-8")
    import os
    os.utime(romans, ns=(original.st_atime_ns, original.st_mtime_ns))
    fresh = builder._resolve_librecad_lff(str(executable), font_name="romans", fresh=True)
    assert fresh.sha256 != selected.sha256
    assert fresh.layout_metrics.run(" P ")[0] == old_advance + 2.0
    assert selected.layout_metrics.run(" P ")[0] == old_advance


def test_real_editable_pipeline_binds_linear_font_and_rejects_saved_font_byte_changes(
    native_fonts, tmp_path, monkeypatch,
):
    import pymupdf
    import dxf_import_engine as engine
    from librecad_pdf_importer.exporters import dxf_exporter as exporter
    from pdfcadcore.import_config import ImportConfig

    executable, _unicode, romans = native_fonts
    content = "  PAPA  "
    source = tmp_path / "fictional-native-linear.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=500, height=300)
        page.insert_text((72, 90), content, fontname="cour", fontsize=12)
        pdf.save(source)
    original_source = source.read_bytes()
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
                           editable_text=True, librecad_executable=str(executable))
    assert stats["text_delivery"]["delivered"] == "text"
    doc = ezdxf.readfile(output)
    entity, = doc.modelspace().query("TEXT")
    assert entity.dxf.text == content
    assert not doc.layers.get(entity.dxf.layer).is_frozen()
    assert entity.dxf.halign == entity.dxf.valign == 0
    assert entity.dxf.style.lower().startswith("romans#")
    assert doc.styles.get(entity.dxf.style).dxf.font.lower() == "romans"
    selected = builder._resolve_librecad_lff(str(executable), font_name="romans", fresh=True)
    proof = builder._librecad_native_layout(entity, selected)
    assert proof["native_lff_font_family"] == "romans" and proof["native_lff_stroke_geometry_safe"] is True
    deliveries, kwargs = calls[-1]
    final = deliveries[0]["attempts"][-1]
    evidence = final["evidence"]
    assert evidence["parent_native_font_candidate"] == "romans"
    assert evidence["parent_source_font_equivalence_verified"] is False
    assert evidence["parent_visual_fidelity_verified"] is False
    assert final["visual_verified"] is False
    physical = ezdxf.readfile(next((tmp_path / "assembled_resume").glob("page_*.dxf")))
    verifier(physical, deliveries, **kwargs)
    romans.write_text(ROMANS.replace("LetterSpacing: 3", "LetterSpacing: 4"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="LibreCAD native text evidence"):
        verifier(physical, deliveries, **kwargs)
    assert source.read_bytes() == original_source

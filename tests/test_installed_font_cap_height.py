"""Installed font outlines retain PDF em scale after DXF save/reload."""
from pathlib import Path
import hashlib
import os
from types import SimpleNamespace

import ezdxf
from ezdxf import bbox
from ezdxf.fonts import fonts
from fontTools.ttLib import TTFont
import pytest

import dxf_text_builder as builder
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText


@pytest.fixture
def installed_font(tmp_path, deterministic_exact_font, monkeypatch):
    path = tmp_path / (tmp_path.name + "-metric.ttf")
    font = TTFont(deterministic_exact_font)
    for record in font["name"].names:
        value = {
            1: "BCS Metric Fixture", 2: "Regular",
            4: "BCS Metric Fixture Regular", 6: "BCSMetricFixture-Regular",
        }.get(record.nameID)
        if value is not None:
            record.string = value.encode(record.getEncoding())
    # Deliberately contradict the actual A outline (700/1000). The renderer
    # scales using its glyph measurement, so OS/2 alone is the wrong oracle.
    font["OS/2"].sCapHeight = 900
    font.save(path)
    font.close()
    fonts.font_manager.scan_folder(tmp_path)
    face = fonts.font_manager.get_font_face(path.name)
    monkeypatch.setattr(fonts, "find_best_match", lambda **_: face)
    builder.reset_text_styles()
    yield path
    builder.reset_text_styles()


def item():
    return NormalizedText(
        id=1, text="AH", normalized="AH", insertion=(12.0, 24.0),
        bbox=(12.0, 24.0, 30.0, 34.0), font_size=10.0, rotation=0.0,
        font_name="BCS Metric Fixture-Regular", page_number=1,
        advance_width=18.0,
    )


def test_installed_resolution_binds_actual_renderer_metric_and_file(installed_font):
    resolution = builder._resolve_exact_font(item().font_name)
    assert resolution.exact
    assert resolution.source_cap_height_ratio == pytest.approx(.7)
    assert resolution.asset_sha256 == hashlib.sha256(installed_font.read_bytes()).hexdigest()


@pytest.mark.parametrize("mode", ["text", "glyphs", "geometry"])
def test_saved_delivery_preserves_source_em_not_em_sized_capitals(
    installed_font, tmp_path, mode,
):
    doc = ezdxf.new("R2010")
    result = builder.build_text(
        item(), doc.modelspace(), "TEXT", ImportConfig(text_mode=mode),
        target_app="generic", return_delivery_result=True,
    )
    assert result.verified and result.final_representation == mode
    path = tmp_path / (mode + ".dxf")
    doc.saveas(path)
    loaded = ezdxf.readfile(path)
    if mode == "text":
        text, = loaded.modelspace().query("TEXT")
        assert text.dxf.height == pytest.approx(7.0)
    else:
        # Independent fixture geometry: capitals top at700, em1000, PDF size10.
        bounds = bbox.extents(loaded.modelspace())
        assert bounds.extmin.y == pytest.approx(24.0)
        assert bounds.extmax.y == pytest.approx(31.0)


@pytest.mark.parametrize("new_document", [False, True])
def test_changed_installed_file_cannot_reuse_stale_metrics(installed_font, new_document):
    builder._installed_font_metrics(installed_font.name)
    st = installed_font.stat()
    os.utime(installed_font, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    if new_document:
        builder.reset_text_styles()
    with pytest.raises(ValueError, match="changed during this import"):
        builder._installed_font_metrics(installed_font.name)


def test_font_read_failure_does_not_authorize_fallback(installed_font, monkeypatch):
    original = Path.read_bytes

    def read(path):
        if path == installed_font.resolve():
            raise OSError("synthetic read failure")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(ValueError, match="synthetic read failure") as caught:
        builder._installed_font_metrics(installed_font.name)
    assert not isinstance(caught.value, builder._RepresentationImpossible)


def test_silent_renderer_substitution_is_rejected(installed_font, monkeypatch):
    monkeypatch.setattr(
        builder.text2path, "get_font",
        lambda _: SimpleNamespace(glyph_cache=SimpleNamespace(font=object())),
    )
    with pytest.raises(ValueError, match="substituted"):
        builder._installed_font_metrics(installed_font.name)

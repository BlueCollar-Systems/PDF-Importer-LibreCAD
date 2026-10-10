"""An absent font program still permits the exact installed-face attempt."""
from dataclasses import replace
import copy
import hashlib

import ezdxf
import pytest

import dxf_text_builder as builder
from pdfcadcore.embedded_fonts import EmbeddedFontFailure
from pdfcadcore.import_config import ImportConfig
from test_representation_delivery_contract import _item
from test_positioned_fraction_dxf_delivery import _positioned_fraction


def empty_program_item():
    item = _item()
    item.font_failure = EmbeddedFontFailure(
        page_number=item.page_number, span_font_name=item.font_name, source_xref=17,
        reason="embedded_font_asset_build_failed", error_type="ExactFontSourceImpossible",
        detail="embedded font stream is empty", proof_category="source_specific_impossibility")
    return item


@pytest.mark.parametrize("mode", ["text", "labels", "3d_text", "glyphs", "geometry"])
def test_exact_installed_face_is_attempted_before_item_raster(mode):
    builder.reset_text_styles()
    item = empty_program_item()
    doc = ezdxf.new("R2010")
    result = builder.build_text(item, doc.modelspace(), "TEXT", ImportConfig(text_mode=mode),
        target_app="librecad", dxf_version="R2010", return_delivery_result=True)
    assert result.verified
    expected = (
        "text" if mode in {"text", "labels", "3d_text"}
        else "geometry" if mode == "geometry"
        else "glyphs"
    )
    assert result.final_representation == expected
    assert not result.terminal_fallback_authorized
    assert list(doc.modelspace())
    assert not any(e.dxftype() == "IMAGE" for e in doc.modelspace())


@pytest.mark.parametrize("changes", [
    {"detail": "embedded font stream is corrupt"}, {"error_type": "RuntimeError"},
    {"source_xref": None}, {"source_xref": True}, {"page_number": 99},
    {"span_font_name": "Different Font"}, {"proof_category": "runtime_inventory_unavailable_for_item"},
])
def test_installed_font_never_hides_corrupt_unbound_or_unknown_program(changes):
    item = empty_program_item()
    item.font_failure = replace(item.font_failure, **changes)
    result = builder._resolve_item_font(item, ImportConfig())
    assert not result.exact


@pytest.fixture
def mismatching_installed_candidate(deterministic_exact_font, monkeypatch):
    item = _positioned_fraction("vertical")
    item.font_asset = None
    item.font_name = "Arial"
    item.font_failure = replace(empty_program_item().font_failure,
        page_number=item.page_number, span_font_name="Arial")
    item.source_char_layout = (replace(item.source_char_layout[0], glyph_id=999),
                               *item.source_char_layout[1:])
    resolution = builder._ExactFontResolution(
        source_name="Arial", family="Arial", style="Regular", exact=True,
        filename=str(deterministic_exact_font), resolution_source="installed_exact_font",
        source_cap_height_ratio=.7,
        asset_sha256=hashlib.sha256(deterministic_exact_font.read_bytes()).hexdigest())
    monkeypatch.setattr(builder, "_resolve_exact_font", lambda _: resolution)
    return item, resolution


def deliver(item, mode="glyphs"):
    builder.reset_text_styles()
    doc = ezdxf.new("R2010")
    result = builder.build_text(item, doc.modelspace(), "TEXT", ImportConfig(text_mode=mode),
        target_app="librecad", dxf_version="R2010", return_delivery_result=True)
    assert not list(doc.modelspace())  # No rejected candidate ink survives.
    return result


@pytest.mark.parametrize("mode", ["text", "labels", "3d_text", "glyphs", "geometry"])
def test_observed_candidate_mismatch_is_bound_before_later_rungs(mismatching_installed_candidate, mode):
    item, resolution = mismatching_installed_candidate
    result = deliver(item, mode)
    assert not result.verified and result.terminal_fallback_authorized
    assert all(attempt.outcome == "impossible" for attempt in result.attempts)
    rejected = [attempt for attempt in result.attempts if "installed_font_rejection" in attempt.evidence]
    assert rejected
    for attempt in rejected:
        receipt = attempt.evidence["installed_font_rejection"]
        assert builder._installed_font_rejection_bound_to_item(item, attempt)
        assert receipt["font_sha256"] == resolution.asset_sha256
        assert receipt["observed_glyph_id"] == 999
        assert receipt["resolved_glyph_id"] == 18
        assert receipt["character"] == "1"
    assert {attempt.attempted_representation for attempt in result.attempts} >= {"glyphs", "geometry"}


@pytest.mark.parametrize("changes", [
    {"source_id": "another-span"}, {"source_page_number": 999}, {"source_xref": 99},
    {"span_font_name": "Other Font"}, {"font_sha256": "f" * 64},
    {"font_sha256": "unknown"}, {"character_index": 1}, {"character_index": True},
    {"character": "9"}, {"observed_glyph_id": 1}, {"resolved_glyph_id": 999},
    {"reason": "font lookup failed"},
])
def test_rejection_receipt_cannot_authorize_another_source(mismatching_installed_candidate, changes):
    item, _ = mismatching_installed_candidate
    result = deliver(item)
    attempt = copy.deepcopy(next(a for a in result.attempts if "installed_font_rejection" in a.evidence))
    attempt.evidence["installed_font_rejection"].update(changes)
    assert not builder._installed_font_rejection_bound_to_item(item, attempt)


def test_candidate_read_failure_does_not_authorize_raster(mismatching_installed_candidate, monkeypatch):
    item, resolution = mismatching_installed_candidate
    monkeypatch.setattr(builder, "_resolve_exact_font", lambda _: replace(resolution, filename="missing-font.ttf"))
    result = deliver(item)
    assert not result.terminal_fallback_authorized
    assert any(attempt.outcome == "failed" for attempt in result.attempts), [(a.outcome, a.reason) for a in result.attempts]
    assert all("installed_font_rejection" not in attempt.evidence for attempt in result.attempts)

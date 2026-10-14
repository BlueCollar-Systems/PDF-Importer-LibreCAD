"""Windowless UI capture through the real worker, serialized DXF and reports."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import ezdxf
import pymupdf as fitz
import pytest

pytest.importorskip("tkinter")
import gui
import dxf_import_engine
from pdfcadcore.import_report import build_human_summary


def source_pdf(path, *, original_image=False):
    with fitz.open() as document:
        page = document.new_page(width=200, height=150)
        page.insert_font(fontname="PublicSynthetic", fontbuffer=fitz.Font("helv").buffer)
        page.insert_text((20, 60), "PUBLIC CONTROL", fontname="PublicSynthetic", fontsize=12)
        if original_image:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 3, 2), False)
            pixmap.clear_with(255)
            pixmap.set_pixel(0, 0, (255, 0, 0))
            page.insert_image(fitz.Rect(10, 70, 40, 90), stream=pixmap.tobytes("png"))
        page.draw_line((10, 100), (150, 100))
        document.save(path)
    return path


def app_options(tmp_path, label, *, saved=False, original_image=False):
    source = source_pdf(tmp_path / "public.pdf", original_image=original_image)
    output = tmp_path / "copy.dxf"
    values = {"_var_input": str(source), "_var_scale": "1", "_var_import_text": True,
              "_var_text_mode": label, "_var_pages": "", "_var_dxf_ver": "R2010",
              "_var_launch_librecad": False}
    app = SimpleNamespace(**{key: SimpleNamespace(get=lambda value=value: value) for key, value in values.items()},
        _cancel_event=gui.threading.Event(), _finish_conversion=Mock(), _log=Mock(),
        after=lambda delay, callback: callback(), _handoff_path=str(tmp_path / "handoff.json"),
        _handoff_delivered=False)
    if saved:
        base = tmp_path / "base.dxf"
        document = ezdxf.new("R2010")
        document.units = 4
        document.modelspace().add_line((0, 0), (25, 0))
        document.saveas(base)
        app._saved_drawing = str(base)
    return app, gui.Pdf2DxfApp._capture_options(app), source, output


def authentic_report(path):
    report = json.loads(path.read_text())
    if report.get("schema") == "bcs.resumable_import_report/1.0":
        assert report["result"] == "complete" and report["pages_degraded"] == []
        return json.loads(Path(report["page_reports"][0]).read_text())
    return report


@pytest.mark.parametrize("saved", [False, True], ids=["ordinary", "saved-drawing"])
@pytest.mark.parametrize("original_image", [False, True], ids=["vector-only", "original-PDF-image"])
@pytest.mark.parametrize("label,expected,editable", [
    (gui.DEFAULT_TEXT_LABEL, "glyphs", False), (gui.EDITABLE_TEXT_LABEL, "text", True)],
    ids=["exact-look-default", "explicit-editable"])
def test_captured_choice_reaches_real_worker_and_physical_report(tmp_path, monkeypatch, saved, original_image, label, expected, editable):
    monkeypatch.setattr("librecad_pdf_importer.launchers.librecad_launcher.preferred_librecad_executable", lambda choice: None)
    monkeypatch.setattr("librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable", lambda choice: None)
    monkeypatch.setattr("librecad_pdf_importer.launchers.librecad_launcher.launch_librecad", Mock(side_effect=AssertionError("No native host may launch")))
    error = Mock()
    monkeypatch.setattr(gui.messagebox, "showerror", error)
    monkeypatch.setattr(gui.messagebox, "showinfo", Mock())
    monkeypatch.setattr(gui.messagebox, "showwarning", Mock())
    app, options, source, output = app_options(tmp_path, label, saved=saved, original_image=original_image)
    originals = {str(path): path.read_bytes() for path in (source, *([Path(options.saved_drawing)] if saved else []))}
    assert options.text_mode == expected and options.editable_text is editable
    # UI edits after capture cannot alter the worker's choice.
    app._var_text_mode.get = Mock(side_effect=AssertionError("Worker read live Tk state"))
    real_convert = dxf_import_engine.convert
    seen = []
    def converter(**kwargs):
        seen.append((kwargs["config"].text_mode, kwargs["editable_text"], kwargs["resumable"]))
        return real_convert(**kwargs)
    monkeypatch.setattr(dxf_import_engine, "convert", converter)
    gui.Pdf2DxfApp._run_conversion(app, str(source), str(output), options)
    assert not error.called, error.call_args
    assert seen == [(expected, editable, not saved)]
    handoff = json.loads((tmp_path / "handoff.json").read_text())
    assert handoff["status"] == "ok" and handoff["degraded_text_items"] == 0
    report = authentic_report(Path(handoff["report_path"]))
    delivery = report["extra"]["text_representation_delivery"]
    assert report["extra"]["text_mode"] == delivery["requested_representation"] == expected
    [item] = delivery["items"]
    assert item["verified"] and item["final_representation"] == "glyphs"
    assert item["attempts"][-1]["attempted_representation"] == "glyphs"
    if not editable:
        assert not item["fallback_used"] and len(item["attempts"]) == 1
        assert "with glyph geometry" in report["extra"]["human_summary"]
        assert "requested flat editable text" not in report["extra"]["human_summary"]
    else:
        # Without an installed host, explicit editable TEXT still requests TEXT
        # and truthfully reports its actual verified outlines fallback.
        assert item["requested_representation"] == "text" and item["fallback_used"]
        assert "glyph geometry (requested flat editable text)" in report["extra"]["human_summary"]
        assert "Verified text representation substitution" in report["extra"]["human_summary"]
        assert "Raster or degraded fallback" not in report["extra"]["human_summary"]
    drawing = ezdxf.readfile(output)
    assert drawing.modelspace().query("INSERT")
    from ezdxf.disassemble import recursive_decompose
    images = [entity for entity in recursive_decompose(drawing.modelspace()) if entity.dxftype() == "IMAGE"]
    assert len(images) == int(original_image)
    if original_image:
        assert report["extra"]["image_delivery"]["source_instances"] == 1
        assert report["extra"]["image_delivery"]["placements"] == 1
    assert all(Path(path).read_bytes() == original for path, original in originals.items())
    assert report["extra"]["diagnostics"]["visual_fidelity_measured"] is False
    assert "Overall fidelity:" not in report["extra"]["human_summary"]


def verified_substitution_report():
    return {"host": {"app": "librecad"}, "input": {"file": "public.pdf", "pages": 1},
        "result": {"primitives": 2, "text_entities": 1, "images": 0},
        "fallback": {"used": True, "text": {"requested": "text", "delivered": "glyphs"},
                     "reason": "text_mode_fallback: text -> glyphs (requested_representation_failed_verification)"},
        "extra": {"text_mode": "text", "text_items_degraded_total": 0,
            "diagnostics": {"quality_level": "low"}, "text_representation_delivery": {
                "verified": True, "requested_representation": "text", "items": [{
                    "requested_representation": "text", "final_representation": "glyphs", "verified": True,
                    "fallback_used": True, "attempts": [{"attempted_representation": "glyphs", "outcome": "verified",
                        "type_verified": True, "delivery_verified": True, "visual_verified": True,
                        "cleanup_verified": True, "superseded": False}]}]}}}


def test_summary_distinguishes_proven_outlines_from_raster_and_density():
    report = verified_substitution_report()
    before = deepcopy(report)
    summary = build_human_summary(report)
    assert "with glyph geometry (requested flat editable text)" in summary
    assert "Verified text representation substitution" in summary
    assert "Raster or degraded" not in summary and "Overall fidelity" not in summary
    assert "Visual fidelity has not been measured" in summary
    assert report == before


def test_original_image_count_does_not_reclassify_verified_text_substitution():
    report = verified_substitution_report()
    report["result"]["images"] = 1
    report["extra"]["image_delivery"] = {"source_instances": 1, "placements": 1}
    summary = build_human_summary(report)
    assert "Verified text representation substitution" in summary
    assert "Raster or degraded fallback" not in summary
    assert "1 raster/image placement" in summary


def test_actual_text_raster_is_disclosed_even_without_a_usable_image_count():
    report = verified_substitution_report()
    report["extra"]["text_representation_delivery"]["items"][0]["final_representation"] = "raster"
    summary = build_human_summary(report)
    assert "Raster or degraded fallback" in summary
    assert "Verified text representation substitution" not in summary


@pytest.mark.parametrize("mutation", ["unverified", "missing-attempt", "failed-attempt", "raster", "degraded", "other-fallback"])
def test_summary_never_certifies_unproven_or_mixed_fallback(mutation):
    report = verified_substitution_report()
    item = report["extra"]["text_representation_delivery"]["items"][0]
    if mutation == "unverified":
        item["verified"] = False
    elif mutation == "missing-attempt":
        item["attempts"] = []
    elif mutation == "failed-attempt":
        item["attempts"][-1]["visual_verified"] = False
    elif mutation == "raster":
        item["final_representation"] = "raster"
        report["result"]["images"] = 1
    elif mutation == "degraded":
        report["extra"]["text_items_degraded_total"] = 1
    else:
        report["fallback"]["reason"] += "; independent page raster fallback"
    summary = build_human_summary(report)
    assert "Verified text representation substitution" not in summary
    if mutation in {"raster", "degraded"}:
        assert "Raster or degraded fallback" in summary
    if mutation == "raster":
        assert "with item-scoped raster text" in summary


def test_mixed_delivered_and_dropped_summary_does_not_claim_requested_text():
    report = verified_substitution_report()
    report["extra"]["text_representation_delivery"]["items"].append({
        "requested_representation": "text", "final_representation": None, "verified": False})
    summary = build_human_summary(report)
    assert "mixed text delivery (glyph geometry, undelivered text)" in summary
    assert "Verified text representation substitution" not in summary

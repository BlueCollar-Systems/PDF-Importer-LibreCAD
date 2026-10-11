from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import threading

import ezdxf
import pytest

import gui
from librecad_pdf_importer import drawing_insert
from librecad_pdf_importer.drawing_copy import DrawingCopyCancelled


def make_app(tmp_path, monkeypatch, *, base_unit=1):
    base = tmp_path / "base.dxf"
    doc = ezdxf.new("R2007"); doc.units = base_unit
    doc.modelspace().add_line((0, 0), (4, 0)); doc.saveas(base)
    pdf = tmp_path / "input.pdf"; pdf.write_bytes(b"fictional PDF, converter mocked")
    handoff = tmp_path / "handoff.json"
    logs = []
    app = SimpleNamespace(
        _cancel_event=threading.Event(), _handoff_path=str(handoff),
        _handoff_delivered=False, _finish_conversion=Mock(),
        after=lambda delay, fn: fn(), _log=logs.append,
    )
    options = gui.ConversionOptions(1, True, "geometry", None, "R2010", False,
                                   saved_drawing=str(base))
    monkeypatch.setattr("pdf_open_guard.precheck_pdf", lambda path: 1)
    monkeypatch.setattr("librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
                        lambda path: "C:/owned/mock/LibreCAD.exe")
    info, error, warning = Mock(), Mock(), Mock()
    monkeypatch.setattr(gui.messagebox, "showinfo", info)
    monkeypatch.setattr(gui.messagebox, "showerror", error)
    monkeypatch.setattr(gui.messagebox, "showwarning", warning)
    seen = []
    def convert(**kwargs):
        seen.append(kwargs)
        converted = ezdxf.new("R2010"); converted.units = 4
        converted.modelspace().add_line((0, 0), (25.4, 0))
        converted.saveas(kwargs["output_path"])
        return {"pages": 1, "entities": 1, "text_items": 0,
                "text_delivery": {"requested": "geometry", "delivered": "geometry",
                                  "item_count": 0, "report_path": "fictional-report.json"}}
    monkeypatch.setattr("dxf_import_engine.convert", convert)
    return app, options, pdf, handoff, seen, info, error, logs


def test_worker_publishes_merged_copy_then_handoff_without_launching_host(tmp_path, monkeypatch):
    app, options, pdf, handoff, seen, info, error, logs = make_app(tmp_path, monkeypatch)
    output = tmp_path / "new.dxf"
    base_bytes = Path(options.saved_drawing).read_bytes()
    gui.Pdf2DxfApp._run_conversion(app, str(pdf), str(output), options)
    assert not error.called and app._finish_conversion.call_count == 1
    assert seen[0]["output_path"] != str(output) and not seen[0]["resumable"]
    assert json.loads(handoff.read_text())["output_path"] == str(output.resolve())
    assert Path(options.saved_drawing).read_bytes() == base_bytes
    doc = ezdxf.readfile(output)
    assert doc.units == 1
    assert doc.modelspace().query("INSERT").first.dxf.xscale == pytest.approx(1 / 25.4)
    assert any("PDF-only conversion and its report folder" in line for line in logs)


def test_merge_cancel_is_a_stop_with_no_handoff(tmp_path, monkeypatch):
    app, options, pdf, handoff, seen, info, error, logs = make_app(tmp_path, monkeypatch)
    def cancel(*args, **kwargs):
        raise DrawingCopyCancelled("deliberate merge stop")
    monkeypatch.setattr(drawing_insert, "insert_into_saved_drawing_copy", cancel)
    gui.Pdf2DxfApp._run_conversion(app, str(pdf), str(tmp_path / "new.dxf"), options)
    assert not error.called and info.call_args.args[0] == "Drawing copy stopped"
    assert app._finish_conversion.call_count == 1 and not handoff.exists()


def test_base_unit_error_precedes_pdf_conversion(tmp_path, monkeypatch):
    app, options, pdf, handoff, seen, info, error, logs = make_app(tmp_path, monkeypatch, base_unit=0)
    gui.Pdf2DxfApp._run_conversion(app, str(pdf), str(tmp_path / "new.dxf"), options)
    assert seen == [] and not handoff.exists()
    assert "Set known drawing units" in error.call_args.args[1]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["base.dxf", "input.pdf"]


def test_existing_copy_never_offers_replace_or_starts_worker(tmp_path, monkeypatch):
    app, options, pdf, handoff, seen, info, error, logs = make_app(tmp_path, monkeypatch)
    output = tmp_path / "existing.dxf"; output.write_bytes(b"native edits")
    var = lambda value: SimpleNamespace(get=lambda: value, set=Mock())
    app._converting = False; app._copying = False
    app._var_input = var(str(pdf)); app._var_output = var(str(output))
    app._capture_options = lambda: options
    replace = Mock()
    monkeypatch.setattr(gui.messagebox, "askyesno", replace)
    gui.Pdf2DxfApp._start_conversion(app)
    assert not replace.called and not app._converting
    assert output.read_bytes() == b"native edits" and seen == []

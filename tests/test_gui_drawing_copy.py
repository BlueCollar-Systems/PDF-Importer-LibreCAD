"""Copy-tool dialog/cancel/close contracts without opening any GUI or CAD host."""
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import gui
from librecad_pdf_importer.drawing_copy import DrawingCopyResult


@pytest.fixture
def app(tmp_path):
    state = SimpleNamespace(
        _converting=False, _copying=False, _close_when_finished=False,
        _copy_cancel_event=threading.Event(), _cancel_event=threading.Event(),
        _var_output=Mock(get=Mock(return_value=str(tmp_path / "converted.dxf"))),
        _btn_convert=Mock(), _btn_cancel=Mock(), _btn_copy_drawing=Mock(),
        _log=Mock(), _start_copy_worker=Mock(), _close_from_librecad_handoff=Mock(),
    )
    state._copy_initial_directory = lambda: gui.Pdf2DxfApp._copy_initial_directory(state)
    state._request_cancel = lambda: gui.Pdf2DxfApp._request_cancel(state)
    state._complete_copy = lambda *args, **kwargs: gui.Pdf2DxfApp._complete_copy(
        state, *args, **kwargs,
    )
    return state


@pytest.mark.parametrize("stage", ["source", "destination"])
def test_cancelled_file_dialog_does_not_start_a_worker(app, monkeypatch, stage):
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: "" if stage == "source"
                        else "original.dxf")
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", lambda **kw: "")
    gui.Pdf2DxfApp._copy_drawing_dialog(app)
    assert not app._copying
    app._start_copy_worker.assert_not_called()


def test_copy_dialog_preserves_existing_conversion_settings(app, monkeypatch, tmp_path):
    source = str(tmp_path / "saved-native.dxf")
    target = str(tmp_path / "copy.dxf")
    opened = Mock(return_value=source)
    saved = Mock(return_value=target)
    monkeypatch.setattr(gui.filedialog, "askopenfilename", opened)
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", saved)
    gui.Pdf2DxfApp._copy_drawing_dialog(app)
    assert app._copying and not app._converting
    assert opened.call_args.kwargs["initialdir"] == str(tmp_path)
    assert saved.call_args.kwargs["confirmoverwrite"] is False
    app._start_copy_worker.assert_called_once_with(source, target, None)
    assert app._var_output.get() == str(tmp_path / "converted.dxf")
    app._btn_cancel.configure.assert_called_once_with(state=gui.tk.NORMAL)


def test_missing_image_folder_prefills_current_conversion_output(app, monkeypatch, tmp_path):
    info = Mock()
    located = Mock(return_value=str(tmp_path / "images"))
    monkeypatch.setattr(gui.messagebox, "showinfo", info)
    monkeypatch.setattr(gui.filedialog, "askdirectory", located)
    gui.Pdf2DxfApp._locate_copy_images(app, "native-save-as.dxf", "copy.dxf", "missing images")
    assert located.call_args.kwargs["initialdir"] == str(tmp_path)
    app._start_copy_worker.assert_called_once_with("native-save-as.dxf", "copy.dxf",
                                                 str(tmp_path / "images"))


def test_cancelling_original_image_folder_restores_controls(app, monkeypatch):
    app._copying = True
    monkeypatch.setattr(gui.messagebox, "showinfo", Mock())
    monkeypatch.setattr(gui.messagebox, "showerror", Mock())
    monkeypatch.setattr(gui.filedialog, "askdirectory", lambda **kw: "")
    gui.Pdf2DxfApp._locate_copy_images(app, "native.dxf", "copy.dxf", "missing")
    assert not app._copying
    app._start_copy_worker.assert_not_called()
    app._btn_convert.configure.assert_called_with(state=gui.tk.NORMAL)


def test_copy_cancel_and_window_close_wait_for_safe_cleanup(app):
    app._copying = True
    gui.Pdf2DxfApp._request_close(app)
    assert app._copy_cancel_event.is_set() and app._close_when_finished
    app._close_from_librecad_handoff.assert_not_called()
    gui.Pdf2DxfApp._complete_copy(app, None, "cancelled", cancelled=True)
    assert not app._copying
    app._close_from_librecad_handoff.assert_called_once()


def test_success_shows_portable_bundle_guidance_and_reenables_controls(app, monkeypatch, tmp_path):
    app._copying = True
    info = Mock()
    monkeypatch.setattr(gui.messagebox, "showinfo", info)
    result = DrawingCopyResult(tmp_path / "copy.dxf", tmp_path / "copy-images", 2, 3, "abc")
    gui.Pdf2DxfApp._complete_copy(app, result, "")
    assert not app._copying
    assert "Keep this DXF and image folder together" in info.call_args.args[1]
    app._btn_cancel.configure.assert_called_with(state=gui.tk.DISABLED)


def test_failed_copy_returns_actionable_error_and_restores_controls(app, monkeypatch):
    app._copying = True
    error = Mock()
    monkeypatch.setattr(gui.messagebox, "showerror", error)
    gui.Pdf2DxfApp._complete_copy(app, None, "Destination exists; choose another filename")
    assert not app._copying
    error.assert_called_once_with("Drawing copy failed", "Destination exists; choose another filename")


def test_conversion_does_not_dispatch_while_copy_is_active(app):
    app._copying = True
    gui.Pdf2DxfApp._start_conversion(app)
    app._var_output.get.assert_not_called()

"""LibreCAD GUI contract: professional flow with all requested text modes."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("tkinter")
import gui

REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_PY = REPO_ROOT / "gui.py"


class TestLcGuiProfessionalImport(unittest.TestCase):
    """GUI hides strategy modes; always uses Auto internally."""

    def setUp(self) -> None:
        self.source = GUI_PY.read_text(encoding="utf-8")

    def test_no_mode_combobox_in_gui(self) -> None:
        self.assertNotIn('text="Mode:"', self.source)
        self.assertNotIn('"Auto":', self.source)
        self.assertNotIn('"Hybrid":', self.source)
        self.assertNotIn("_var_mode", self.source)

    def test_auto_only_conversion(self) -> None:
        self.assertIn("ImportConfig.auto()", self.source)
        self.assertIn("IMPORT_MODE_AUTO", self.source)
        self.assertIn('Import mode: Auto (per-page strategy)', self.source)

    def test_professional_import_tagline(self) -> None:
        self.assertIn("Professional import", self.source)

    def test_all_requested_text_modes_remain_available(self) -> None:
        self.assertEqual(
            set(gui.TEXT_MODES.values()),
            {"text", "labels", "3d_text", "glyphs", "geometry", "raster"},
        )
        self.assertNotIn("editable native TEXT", self.source)
        self.assertNotIn("3D Text (TEXT with thickness)", self.source)
        self.assertIn('"Glyphs (grouped outlines)": "glyphs"', self.source)
        self.assertIn('"Geometry (raw outlines)": "geometry"', self.source)
        self.assertIn('"Raster (exact item pixels)": "raster"', self.source)

    def test_default_request_remains_text(self) -> None:
        self.assertEqual(gui.TEXT_MODES[gui.DEFAULT_TEXT_LABEL], "text")
        self.assertIn('tk.StringVar(value=DEFAULT_TEXT_LABEL)', self.source)

    def test_librecad_2d_disclaimer_present(self) -> None:
        self.assertIn("LibreCAD is 2D", self.source)
        self.assertIn("Visible Text normally becomes verified outlines", self.source)
        self.assertIn("Any fallback or unverified item is listed", self.source)

    def test_explicit_geometry_selection_has_no_confirmation_roadblock(self) -> None:
        self.assertNotIn("messagebox.askokcancel(", self.source)

    def test_long_work_has_determinate_progress_cancel_and_resume(self) -> None:
        self.assertIn('text="Cancel"', self.source)
        self.assertIn('mode="determinate"', self.source)
        self.assertIn("self._cancel_event", self.source)
        self.assertIn("cancel_requested=self._cancel_event.is_set", self.source)
        self.assertIn("resumable=True", self.source)
        self.assertIn("restart_on_resume_mismatch=True", self.source)
        self.assertIn("Certified pages were kept", self.source)

    def test_completion_says_which_clipped_fills_were_left_out(self) -> None:
        # Resumed pages never pass through the progress log, so the line comes
        # from the returned stats: once in the log, once in the Done dialog.
        self.assertIn('clip_fill_warning = str(stats.get("clip_fill_warning") or "")', self.source)
        self.assertIn("self._log(clip_fill_warning)", self.source)
        self.assertIn('(f"\\n\\n{clip_fill_warning}" if clip_fill_warning else "")', self.source)


def _app_without_window(tmp_path):
    values = {
        "_var_input": str(tmp_path / "drawing.pdf"),
        "_var_output": str(tmp_path / "drawing.dxf"),
        "_var_scale": "1.0", "_var_import_text": True,
        "_var_text_mode": next(iter(gui.TEXT_MODES)), "_var_pages": "",
        "_var_dxf_ver": "R2010", "_var_launch_librecad": False,
    }
    (tmp_path / "drawing.pdf").write_bytes(b"test input; precheck mocked")
    app = SimpleNamespace(
        **{key: Mock(get=Mock(return_value=value)) for key, value in values.items()},
        _converting=False, _cancel_event=gui.threading.Event(),
        _btn_convert=Mock(), _btn_cancel=Mock(), _progress=Mock(), _log_text=Mock(),
        _log=Mock(), after=lambda _ms, callback: callback(), _finish_conversion=Mock(),
    )
    app._capture_options = lambda: gui.Pdf2DxfApp._capture_options(app)
    app._run_conversion = lambda *args: gui.Pdf2DxfApp._run_conversion(app, *args)
    return app


@pytest.mark.parametrize("scale", ["", "oops", "0", "-1", "nan", "inf", "-inf", "1e999"])
def test_invalid_scale_never_dispatches_or_clears_the_log(tmp_path, scale):
    app = _app_without_window(tmp_path)
    app._var_scale.get.return_value = scale
    with patch.object(gui.threading, "Thread") as thread, patch.object(
        gui.messagebox, "showwarning",
    ) as warning:
        gui.Pdf2DxfApp._start_conversion(app)
    thread.assert_not_called()
    warning.assert_called_once()
    assert "positive, finite number" in warning.call_args.args[1]
    app._log_text.delete.assert_not_called()
    assert not app._converting and not app._cancel_event.is_set()


@pytest.mark.parametrize("pages", ["0", "5-2", "1,,3", "all"])
def test_invalid_pages_are_rejected_before_dispatch(tmp_path, pages):
    app = _app_without_window(tmp_path)
    app._var_pages.get.return_value = pages
    with patch.object(gui.threading, "Thread") as thread, patch.object(
        gui.messagebox, "showwarning",
    ) as warning:
        gui.Pdf2DxfApp._start_conversion(app)
    thread.assert_not_called()
    warning.assert_called_once()
    assert not app._converting


@pytest.mark.parametrize("mode", ["text", "labels", "3d_text", "glyphs", "geometry", "raster"])
def test_worker_keeps_requested_settings_and_never_reads_tk_values(tmp_path, mode):
    app = _app_without_window(tmp_path)
    app._var_scale.get.return_value = " 0.5 "
    app._var_pages.get.return_value = "1,3-5"
    app._var_text_mode.get.return_value = next(
        label for label, value in gui.TEXT_MODES.items() if value == mode
    )
    with patch.object(gui.threading, "Thread") as thread:
        gui.Pdf2DxfApp._start_conversion(app)
    thread.return_value.start.assert_called_once()
    arguments = thread.call_args.kwargs["args"]
    # Subsequent UI edits, including the launch checkbox, must not affect this run.
    for key, value in vars(app).items():
        if key.startswith("_var_"):
            value.get.side_effect = AssertionError("worker read a live Tk variable")
    with patch("dxf_import_engine.convert", return_value={}) as convert, patch(
        "pdf_open_guard.precheck_pdf",
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=None,
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.launch_librecad",
    ) as launch, patch.object(gui.messagebox, "showinfo"), patch.object(
        gui.messagebox, "showerror",
    ) as error:
        app._run_conversion(*arguments)
    error.assert_not_called()
    convert.assert_called_once()
    config = convert.call_args.kwargs["config"]
    assert config.text_mode == mode and config.user_scale == 0.5
    assert config.import_text and config.pages == [0, 2, 3, 4]
    assert convert.call_args.kwargs["dxf_version"] == "R2010"
    launch.assert_not_called()
    app._finish_conversion.assert_called_once()


def test_capture_preserves_text_off_all_pages_and_launch_choice(tmp_path):
    app = _app_without_window(tmp_path)
    app._var_import_text.get.return_value = False
    app._var_launch_librecad.get.return_value = True
    options = app._capture_options()
    assert not options.import_text and options.pages is None and options.launch_librecad


if __name__ == "__main__":
    unittest.main(verbosity=2)

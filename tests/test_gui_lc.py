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

    def test_editable_text_choice_is_offered(self) -> None:
        # Owner ruling 2026-10-05: an Editable text choice, Exact look stays default.
        self.assertEqual(gui.EDITABLE_TEXT_LABEL, "Editable text (LibreCAD font)")
        self.assertEqual(gui.TEXT_MODES[gui.EDITABLE_TEXT_LABEL], "text")
        self.assertNotIn("Text (may become outlines)", self.source)

    def test_default_request_remains_text(self) -> None:
        self.assertEqual(gui.TEXT_MODES[gui.DEFAULT_TEXT_LABEL], "text")
        self.assertEqual(
            gui.DEFAULT_TEXT_LABEL, "Exact look - text as outlines (default)"
        )
        self.assertNotEqual(gui.DEFAULT_TEXT_LABEL, gui.EDITABLE_TEXT_LABEL)
        self.assertIn('tk.StringVar(value=DEFAULT_TEXT_LABEL)', self.source)

    def test_librecad_2d_disclaimer_present(self) -> None:
        self.assertIn("LibreCAD is 2D", self.source)
        self.assertIn("Exact look draws every word as exact outlines", self.source)
        self.assertIn("letter shapes differ", self.source)
        self.assertIn("Characters LibreCAD's font lacks still come in as", self.source)
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
    import pymupdf

    with pymupdf.open() as document:
        for _ in range(5):
            document.new_page()
        document.save(tmp_path / "drawing.pdf")
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


@pytest.mark.parametrize("pages", ["0", "5-2", "1,,3", "1,6", "1-1000000000"])
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


@pytest.mark.parametrize(
    ("label", "editable"),
    [(gui.DEFAULT_TEXT_LABEL, False), (gui.EDITABLE_TEXT_LABEL, True)],
    ids=["exact-look", "editable-text"],
)
def test_worker_passes_the_editable_text_choice_and_logs_the_count(
    tmp_path, label, editable
):
    app = _app_without_window(tmp_path)
    app._var_text_mode.get.return_value = label
    options = app._capture_options()
    assert options.text_mode == "text" and options.editable_text is editable
    stats = {
        "text_delivery": {
            "requested": "text", "delivered": "mixed", "item_count": 3,
            "editable_text_item_count": 2,
        }
    }
    with patch("dxf_import_engine.convert", return_value=stats) as convert, patch(
        "pdf_open_guard.precheck_pdf",
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=None,
    ), patch.object(gui.messagebox, "showinfo"), patch.object(
        gui.messagebox, "showerror",
    ) as error:
        app._run_conversion(
            str(tmp_path / "drawing.pdf"), str(tmp_path / "drawing.dxf"), options
        )
    error.assert_not_called()
    assert convert.call_args.kwargs["editable_text"] is editable
    assert convert.call_args.kwargs["config"].text_mode == "text"
    logged = [call.args[0] for call in app._log.call_args_list]
    editable_lines = [line for line in logged if "Editable text:" in line]
    if editable:
        assert editable_lines == [
            "  Editable text: 2 of 3 text item(s) came in as editable text in "
            "LibreCAD's font; the report says how each other one came in and why."
        ]
        assert any("text=editable (LibreCAD font)" in line for line in logged)
    else:
        assert editable_lines == []
        assert any("text=text;" in line for line in logged)


def test_capture_preserves_text_off_all_pages_and_launch_choice(tmp_path):
    app = _app_without_window(tmp_path)
    app._var_import_text.get.return_value = False
    app._var_launch_librecad.get.return_value = True
    options = app._capture_options()
    assert not options.import_text and options.pages is None and options.launch_librecad


if __name__ == "__main__":
    unittest.main(verbosity=2)


def test_gui_accepts_all_as_written_in_the_validation_message(tmp_path):
    app = _app_without_window(tmp_path)
    app._var_pages.get.return_value = " All "
    assert app._capture_options().pages is None


# --- The output follows the PDF, and an existing drawing is never replaced silently ---


class _Var:
    """A tk.StringVar stand-in for window-less tests."""

    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _browse_app(input_value: str = "", output_value: str = ""):
    return SimpleNamespace(_var_input=_Var(input_value), _var_output=_Var(output_value))


def test_output_follows_each_newly_browsed_pdf(tmp_path):
    first = (tmp_path / "D042" / "EX101.pdf").as_posix()
    second = (tmp_path / "D100" / "MXT-100.pdf").as_posix()
    app = _browse_app()
    with patch.object(gui.filedialog, "askopenfilename", return_value=first):
        gui.Pdf2DxfApp._browse_input(app)
    assert app._var_output.get() == (tmp_path / "D042" / "EX101.dxf").as_posix()
    with patch.object(gui.filedialog, "askopenfilename", return_value=second):
        gui.Pdf2DxfApp._browse_input(app)
    assert app._var_input.get() == second
    assert app._var_output.get() == (tmp_path / "D100" / "MXT-100.dxf").as_posix()


def test_output_the_user_picked_stays_when_another_pdf_is_browsed(tmp_path):
    first = (tmp_path / "D042" / "EX101.pdf").as_posix()
    second = (tmp_path / "D100" / "MXT-100.pdf").as_posix()
    custom = (tmp_path / "out" / "combined.dxf").as_posix()
    app = _browse_app()
    with patch.object(gui.filedialog, "askopenfilename", return_value=first):
        gui.Pdf2DxfApp._browse_input(app)
    with patch.object(gui.filedialog, "asksaveasfilename", return_value=custom):
        gui.Pdf2DxfApp._browse_output(app)
    with patch.object(gui.filedialog, "askopenfilename", return_value=second):
        gui.Pdf2DxfApp._browse_input(app)
    assert app._var_input.get() == second
    assert app._var_output.get() == custom


def test_cancelled_browse_changes_nothing(tmp_path):
    app = _browse_app("C:/jobs/D042/EX101.pdf", "C:/jobs/D042/EX101.dxf")
    with patch.object(gui.filedialog, "askopenfilename", return_value=""):
        gui.Pdf2DxfApp._browse_input(app)
    assert app._var_input.get() == "C:/jobs/D042/EX101.pdf"
    assert app._var_output.get() == "C:/jobs/D042/EX101.dxf"


def _write_session(output: Path, *, source_sha256: str, output_sha256: str | None) -> None:
    import json

    session = output.with_name(f"{output.stem}_resume")
    session.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "bcs.librecad_resume/1.0", "source_sha256": source_sha256}
    if output_sha256 is not None:
        manifest["assembled"] = {"output_sha256": output_sha256}
    (session / "session.json").write_text(json.dumps(manifest), encoding="utf-8")


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_existing_drawing_without_session_asks_and_no_keeps_it(tmp_path):
    app = _app_without_window(tmp_path)
    output = tmp_path / "drawing.dxf"
    output.write_bytes(b"0\nSECTION\n999\nUSER EDIT KEEP ME\n0\nEOF\n")
    before = output.read_bytes()
    with patch.object(gui.threading, "Thread") as thread, patch.object(
        gui.messagebox, "askyesno", return_value=False,
    ) as ask:
        gui.Pdf2DxfApp._start_conversion(app)
    ask.assert_called_once()
    assert ask.call_args.args[0] == "Replace drawing?"
    assert "drawing.dxf already exists. Replace it?" in ask.call_args.args[1]
    thread.assert_not_called()
    app._log_text.delete.assert_not_called()
    assert not app._converting
    assert output.read_bytes() == before


def test_existing_drawing_yes_replaces_it(tmp_path):
    app = _app_without_window(tmp_path)
    (tmp_path / "drawing.dxf").write_bytes(b"old drawing")
    with patch.object(gui.threading, "Thread") as thread, patch.object(
        gui.messagebox, "askyesno", return_value=True,
    ) as ask:
        gui.Pdf2DxfApp._start_conversion(app)
    ask.assert_called_once()
    thread.return_value.start.assert_called_once()
    assert app._converting


def test_untouched_output_of_the_same_pdf_resumes_without_asking(tmp_path):
    app = _app_without_window(tmp_path)
    output = tmp_path / "drawing.dxf"
    output.write_bytes(b"assembled by the importer")
    _write_session(
        output,
        source_sha256=_sha(tmp_path / "drawing.pdf"),
        output_sha256=_sha(output),
    )
    assert gui.output_replace_reason(str(tmp_path / "drawing.pdf"), str(output)) is None
    with patch.object(gui.threading, "Thread") as thread, patch.object(
        gui.messagebox, "askyesno",
    ) as ask:
        gui.Pdf2DxfApp._start_conversion(app)
    ask.assert_not_called()
    thread.return_value.start.assert_called_once()


def test_output_made_from_a_different_pdf_asks(tmp_path):
    app = _app_without_window(tmp_path)
    output = tmp_path / "drawing.dxf"
    output.write_bytes(b"assembled from another PDF")
    _write_session(output, source_sha256="0" * 64, output_sha256=_sha(output))
    with patch.object(gui.threading, "Thread") as thread, patch.object(
        gui.messagebox, "askyesno", return_value=False,
    ) as ask:
        gui.Pdf2DxfApp._start_conversion(app)
    ask.assert_called_once()
    assert "drawing.dxf was made from a different PDF" in ask.call_args.args[1]
    thread.assert_not_called()


def test_output_edited_after_import_asks(tmp_path):
    output = tmp_path / "drawing.dxf"
    app = _app_without_window(tmp_path)
    output.write_bytes(b"assembled by the importer")
    _write_session(
        output,
        source_sha256=_sha(tmp_path / "drawing.pdf"),
        output_sha256=_sha(output),
    )
    output.write_bytes(b"assembled by the importer\nUSER EDIT KEEP ME\n")
    assert (
        gui.output_replace_reason(str(tmp_path / "drawing.pdf"), str(output))
        == "was changed after it was imported"
    )


def test_missing_output_never_asks(tmp_path):
    assert gui.output_replace_reason(
        str(tmp_path / "drawing.pdf"), str(tmp_path / "missing.dxf"),
    ) is None


# --- LibreCAD not found: plain advice and a "Locate LibreCAD..." button ---


def _run_with_launch(app, tmp_path, *, found, launch_result):
    app._var_launch_librecad.get.return_value = True
    app._btn_locate_librecad = Mock(winfo_manager=Mock(return_value=""))
    options = gui.Pdf2DxfApp._capture_options(app)
    with patch("dxf_import_engine.convert", return_value={}), patch(
        "pdf_open_guard.precheck_pdf",
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=found,
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.launch_librecad",
        return_value=launch_result,
    ), patch.object(gui.messagebox, "showinfo") as info, patch.object(
        gui.messagebox, "showerror",
    ) as error:
        gui.Pdf2DxfApp._run_conversion(
            app, str(tmp_path / "drawing.pdf"), str(tmp_path / "drawing.dxf"), options,
        )
    error.assert_not_called()
    logged = [str(call.args[0]) for call in app._log.call_args_list]
    return logged, info.call_args.args[1]


def test_librecad_not_found_gives_plain_advice_and_shows_locate_button(tmp_path):
    app = _app_without_window(tmp_path)
    logged, done_text = _run_with_launch(
        app, tmp_path, found=None, launch_result=(False, "LibreCAD executable not found."),
    )
    assert gui.LIBRECAD_NOT_FOUND_TIP in logged
    assert "Locate LibreCAD..." in gui.LIBRECAD_NOT_FOUND_TIP
    assert not any("librecad_launcher" in line for line in logged)
    assert not any(line.startswith("Tip:") for line in logged)
    assert gui.LIBRECAD_NOT_FOUND_TIP in done_text
    app._btn_locate_librecad.pack.assert_called()


def test_librecad_found_but_not_started_says_so(tmp_path):
    app = _app_without_window(tmp_path)
    logged, done_text = _run_with_launch(
        app, tmp_path, found="C:/LC/LibreCAD.exe",
        launch_result=(False, "Failed to launch LibreCAD: access denied"),
    )
    assert gui.LIBRECAD_START_FAILED_TIP in logged
    assert gui.LIBRECAD_NOT_FOUND_TIP not in logged
    assert gui.LIBRECAD_START_FAILED_TIP in done_text
    app._btn_locate_librecad.pack.assert_called()


def test_locate_button_stays_hidden_when_librecad_opens(tmp_path):
    app = _app_without_window(tmp_path)
    logged, _done_text = _run_with_launch(
        app, tmp_path, found="C:/LC/LibreCAD.exe",
        launch_result=(True, "Launched LibreCAD: C:/LC/LibreCAD.exe"),
    )
    assert "Launched LibreCAD: C:/LC/LibreCAD.exe" in logged
    app._btn_locate_librecad.pack.assert_not_called()


def test_locate_librecad_remembers_the_choice_and_next_run_uses_it(tmp_path, monkeypatch):
    from librecad_pdf_importer.launchers import librecad_launcher

    monkeypatch.delenv("BCS_LIBRECAD_EXECUTABLE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    exe = tmp_path / "Tools" / "LibreCAD" / "LibreCAD.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fake LibreCAD")
    app = _app_without_window(tmp_path)
    app._librecad_choice = None
    app._btn_locate_librecad = Mock()
    with patch.object(gui.filedialog, "askopenfilename", return_value=exe.as_posix()):
        gui.Pdf2DxfApp._locate_librecad(app)
    assert app._librecad_choice == str(exe.resolve())
    assert librecad_launcher.load_saved_librecad_executable() == str(exe.resolve())
    app._btn_locate_librecad.pack_forget.assert_called_once()
    assert "remembered for next time" in app._log.call_args_list[-1].args[0]

    # A new window (no choice in memory) captures the remembered LibreCAD.
    fresh = _app_without_window(tmp_path)
    assert gui.Pdf2DxfApp._capture_options(fresh).librecad_executable == str(exe.resolve())


def test_locate_librecad_rejects_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _app_without_window(tmp_path)
    app._librecad_choice = None
    app._btn_locate_librecad = Mock()
    with patch.object(
        gui.filedialog, "askopenfilename", return_value=(tmp_path / "nope.exe").as_posix(),
    ), patch.object(gui.messagebox, "showwarning") as warning:
        gui.Pdf2DxfApp._locate_librecad(app)
    warning.assert_called_once()
    assert app._librecad_choice is None
    assert not (tmp_path / "local").exists()


def test_failed_lookup_without_launch_explains_the_button_once(tmp_path):
    app = _app_without_window(tmp_path)
    app._btn_locate_librecad = Mock(winfo_manager=Mock(return_value=""))
    options = gui.Pdf2DxfApp._capture_options(app)
    with patch("dxf_import_engine.convert", return_value={}), patch(
        "pdf_open_guard.precheck_pdf",
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=None,
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.launch_librecad",
    ) as launch, patch.object(gui.messagebox, "showinfo") as info:
        gui.Pdf2DxfApp._run_conversion(
            app, str(tmp_path / "drawing.pdf"), str(tmp_path / "drawing.dxf"), options,
        )
    launch.assert_not_called()
    logged = [str(call.args[0]) for call in app._log.call_args_list]
    assert logged.count(gui.LIBRECAD_NOT_FOUND_TIP) == 1
    # Not something the user asked for, so the Done box stays about the drawing.
    assert gui.LIBRECAD_NOT_FOUND_TIP not in info.call_args.args[1]
    app._btn_locate_librecad.pack.assert_called()

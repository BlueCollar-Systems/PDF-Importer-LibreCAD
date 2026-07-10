"""BCS-ARCH-001 clean-break contract: old --preset and quality-tier flags gone (LC)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_PY = REPO_ROOT / "gui.py"
CORE_CONFIG_PY = REPO_ROOT / "pdfcadcore" / "import_config.py"
PACKAGE_CONFIG_PY = REPO_ROOT / "librecad_pdf_importer" / "core" / "PDFImportConfig.py"
PLUGIN_MENU_CPP = REPO_ROOT / "plugin" / "lcpdf_menu" / "lcpdf_menu.cpp"
PDF2DXF_PY = REPO_ROOT / "pdf2dxf.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "librecad_pdf_importer.cli", *args]
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _write_argparse_pdf(tmp: str) -> Path:
    path = Path(tmp) / "argparse-anchor.pdf"
    path.write_bytes(b"%PDF-1.4\n% argparse-only portable fixture\n")
    return path


class TestCleanBreak(unittest.TestCase):
    """``--preset`` must have been deleted per BCS-ARCH-001 -- no shim."""

    def test_old_preset_flag_errors_out(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_clean_break_") as tmp:
            result = _run_cli(str(_write_argparse_pdf(tmp)), "--preset", "shop")
            self.assertNotEqual(
                result.returncode, 0,
                msg="--preset should be rejected; it was accepted instead",
            )
            combined = (result.stdout + result.stderr).lower()
            self.assertTrue(
                "unrecognized arguments" in combined or "--preset" in combined,
                msg=f"Unexpected error output: {combined!r}",
            )


class TestRule5FlagsRemoved(unittest.TestCase):
    """BCS-ARCH-001 Rule 5 sweep: quality-tier CLI flags must error out."""

    REMOVED_FLAGS = (
        "--hatch-mode",
        "--arc-mode",
        "--cleanup-level",
        "--lineweight-mode",
        "--raster-dpi",
        "--strict-text-fidelity",
        "--no-strict-text-fidelity",
        "--no-arcs",
        "--no-text",
        "--no-raster-fallback",
        "--grouping-mode",
    )

    def test_removed_flags_error_out(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_removed_flags_") as tmp:
            pdf_path = _write_argparse_pdf(tmp)
            for flag in self.REMOVED_FLAGS:
                with self.subTest(flag=flag):
                    result = _run_cli(str(pdf_path), flag, "x")
                    self.assertNotEqual(
                        result.returncode, 0,
                        msg=f"{flag!r} should be rejected; it was accepted instead",
                    )
                    combined = (result.stdout + result.stderr).lower()
                    self.assertTrue(
                        "unrecognized arguments" in combined or flag.lower() in combined,
                        msg=f"Unexpected output for {flag}: {combined!r}",
                    )


class TestRule5GuiCheckboxesRemoved(unittest.TestCase):
    """GUI must not expose quality-tier checkboxes after Rule 5 sweep."""

    REMOVED_VARS = (
        "_var_detect_arcs",
        "_var_map_dashes",
        "_var_make_faces",
    )

    REMOVED_LABELS = (
        '"Detect arcs"',
        '"Map dash patterns"',
        '"Make faces"',
    )

    def setUp(self) -> None:
        self.source = GUI_PY.read_text(encoding="utf-8")

    def test_removed_vars_not_declared(self) -> None:
        for var in self.REMOVED_VARS:
            self.assertNotIn(
                var, self.source,
                f"GUI still declares quality-tier variable {var!r} (BCS-ARCH-001 Rule 5).",
            )

    def test_removed_checkbox_labels_gone(self) -> None:
        for lbl in self.REMOVED_LABELS:
            self.assertNotIn(
                lbl, self.source,
                f"GUI still has quality-tier checkbox label {lbl!r} (BCS-ARCH-001 Rule 5).",
            )

    def test_no_legacy_preset_labels(self) -> None:
        for label in (
            "Fast", "Balanced", "Full", "Max Fidelity", "Raster Image",
            "Custom...", "Shop Drawing", "Technical Drawing",
        ):
            self.assertNotIn(
                f'"{label}"', self.source,
                f"GUI still references legacy preset label {label!r}.",
            )

    def test_gui_does_not_expose_strategy_mode_picker(self) -> None:
        self.assertNotIn("_var_mode", self.source)
        self.assertNotIn('text="Mode:"', self.source)

    def test_gui_text_default_is_labels_for_2d_lc(self) -> None:
        self.assertIn('tk.StringVar(value="Labels (editable TEXT)")', self.source)
        self.assertIn('TEXT_MODES.get(self._var_text_mode.get(), "labels")', self.source)


class TestTextDefaults(unittest.TestCase):
    """Core config defaults must not silently return to Labels."""

    def test_embedded_configs_default_to_3d_text(self) -> None:
        source = CORE_CONFIG_PY.read_text(encoding="utf-8")
        self.assertIn('text_mode: str = "3d_text"', source)
        self.assertNotIn('text_mode: str = "labels"', source)

    def test_legacy_pdf2dxf_uses_librecad_2d_default(self) -> None:
        source = PDF2DXF_PY.read_text(encoding="utf-8")
        self.assertIn('config.text_mode = "labels"', source)


class TestLibreCadPluginLauncher(unittest.TestCase):
    """Menu plugin must resolve installed Windows launcher apps, not only source scripts."""

    def test_installed_importer_exe_is_discoverable(self) -> None:
        source = PLUGIN_MENU_CPP.read_text(encoding="utf-8")
        self.assertIn("BC_LC_IMPORTER_EXE", source)
        self.assertIn("LibreCAD-PDF-Importer.exe", source)
        self.assertIn("Importer Apps (*.exe *.py *.pyw)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

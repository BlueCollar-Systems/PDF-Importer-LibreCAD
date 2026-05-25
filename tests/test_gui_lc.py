"""LibreCAD GUI contract: professional single-flow import and 2D text modes."""
from __future__ import annotations

import unittest
from pathlib import Path

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

    def test_text_modes_are_2d_labels_and_geometry_only(self) -> None:
        self.assertIn('"Labels (editable TEXT)": "labels"', self.source)
        self.assertIn('"Outlines (no editable text)": "geometry"', self.source)
        self.assertNotIn('"3D Text"', self.source)
        self.assertNotIn('"Glyphs"', self.source)

    def test_default_text_is_labels(self) -> None:
        self.assertIn('tk.StringVar(value="Labels (editable TEXT)")', self.source)
        self.assertIn('TEXT_MODES.get(self._var_text_mode.get(), "labels")', self.source)

    def test_librecad_2d_disclaimer_present(self) -> None:
        self.assertIn("LibreCAD is 2D", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

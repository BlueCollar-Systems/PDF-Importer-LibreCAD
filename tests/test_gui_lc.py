"""LibreCAD GUI contract: professional flow with all requested text modes."""
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

    def test_all_requested_text_modes_remain_available(self) -> None:
        self.assertIn('"Text (editable native TEXT)": "text"', self.source)
        self.assertIn('"Labels (closest Text fallback)": "labels"', self.source)
        self.assertIn('"3D Text (TEXT with thickness)": "3d_text"', self.source)
        self.assertIn('"Glyphs (grouped outlines)": "glyphs"', self.source)
        self.assertIn('"Geometry (raw outlines)": "geometry"', self.source)
        self.assertIn('"Raster (exact item pixels)": "raster"', self.source)

    def test_default_text_is_native_text(self) -> None:
        self.assertIn('tk.StringVar(value="Text (editable native TEXT)")', self.source)
        self.assertIn('TEXT_MODES.get(self._var_text_mode.get(), "text")', self.source)

    def test_librecad_2d_disclaimer_present(self) -> None:
        self.assertIn("LibreCAD is 2D", self.source)
        self.assertIn("any verified fallback is shown", self.source)

    def test_explicit_geometry_selection_has_no_confirmation_roadblock(self) -> None:
        self.assertNotIn("messagebox.askokcancel(", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

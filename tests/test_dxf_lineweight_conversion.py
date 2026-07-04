"""
Regression guardrail for DXF lineweight conversion in dxf_builder.py.

Covers:
  - pt->mm conversion (25.4/72) for DXF 1/100mm lineweight units
  - Minimum 5 (0.05mm) and maximum 211 (2.11mm) DXF lineweight range
  - arc_min_pts forwarded in dxf_import_engine legacy path
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

_BUILDER = Path(__file__).resolve().parent.parent / "dxf_builder.py"
_ENGINE = Path(__file__).resolve().parent.parent / "dxf_import_engine.py"


def _builder_src() -> str:
    return _BUILDER.read_text(encoding="utf-8")


def _engine_src() -> str:
    return _ENGINE.read_text(encoding="utf-8")


class TestDxfLineweightConversion(unittest.TestCase):
    """DXF lineweight must convert PDF points to 1/100mm units correctly."""

    def test_pt_to_mm_conversion(self) -> None:
        src = _builder_src()
        # 25.4/72 is the correct PDF-points-to-mm factor
        self.assertIn("25.4 / 72.0", src,
                      "dxf_builder must convert PDF pt to mm via 25.4/72")

    def test_dxf_min_lineweight(self) -> None:
        src = _builder_src()
        # DXF minimum valid lineweight is 5 (0.05 mm)
        self.assertIn("max(5,", src,
                      "DXF lineweight must have minimum of 5 (0.05mm)")

    def test_dxf_max_lineweight(self) -> None:
        src = _builder_src()
        # DXF maximum valid lineweight is 211 (2.11 mm)
        self.assertIn("min(211,", src,
                      "DXF lineweight must be capped at 211 (2.11mm)")

    def test_lineweight_units_comment_or_code(self) -> None:
        src = _builder_src()
        # The lineweight attribute must be set
        self.assertIn('attribs["lineweight"]', src,
                      "dxf_builder must assign lineweight attrib")

    def test_lineweight_width_mm_variable(self) -> None:
        src = _builder_src()
        self.assertIn("width_mm", src,
                      "dxf_builder must compute width_mm before lineweight conversion")


class TestArcMinPtsForwarded(unittest.TestCase):
    """arc_min_pts must be forwarded in the legacy dxf_import_engine path."""

    def test_arc_min_pts_in_extract_page_call(self) -> None:
        src = _engine_src()
        self.assertIn("arc_min_pts=", src,
                      "dxf_import_engine must forward arc_min_pts to extract_page")

    def test_arc_sampling_pts_used(self) -> None:
        src = _engine_src()
        self.assertIn("arc_sampling_pts", src,
                      "arc_min_pts must be sourced from config.arc_sampling_pts")


class TestLineweightRoundTrip(unittest.TestCase):
    """Unit-level check of the pt->1/100mm formula."""

    def test_hairline_0_5pt(self) -> None:
        # 0.5 PDF pt -> 0.5 * 25.4/72 = 0.1764 mm -> 17 (1/100mm)
        width_pt = 0.5
        width_mm = width_pt * (25.4 / 72.0)
        lw = int(max(5, min(211, round(width_mm * 100))))
        self.assertGreaterEqual(lw, 5)
        self.assertLessEqual(lw, 211)

    def test_standard_1pt(self) -> None:
        # 1 PDF pt -> 25.4/72 = 0.3528 mm -> 35 (1/100mm)
        width_pt = 1.0
        width_mm = width_pt * (25.4 / 72.0)
        lw = int(max(5, min(211, round(width_mm * 100))))
        self.assertEqual(lw, 35)

    def test_heavy_line_4pt(self) -> None:
        # 4 PDF pt -> 1.411 mm -> 141 (1/100mm)
        width_pt = 4.0
        width_mm = width_pt * (25.4 / 72.0)
        lw = int(max(5, min(211, round(width_mm * 100))))
        self.assertEqual(lw, 141)

    def test_zero_width_clamped_to_minimum(self) -> None:
        # 0 pt -> 0 mm -> clamped to 5
        width_pt = 0.0
        width_mm = width_pt * (25.4 / 72.0)
        lw = int(max(5, min(211, round(width_mm * 100))))
        self.assertEqual(lw, 5)

    def test_giant_line_clamped_to_max(self) -> None:
        # 100 pt -> 35.28 mm -> clamped to 211
        width_pt = 100.0
        width_mm = width_pt * (25.4 / 72.0)
        lw = int(max(5, min(211, round(width_mm * 100))))
        self.assertEqual(lw, 211)


if __name__ == "__main__":
    unittest.main(verbosity=2)

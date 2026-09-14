# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdfcadcore.import_bounds import compute_import_bounds, sheet_xy  # noqa: E402
from pdfcadcore.primitives import PageData, Primitive, next_id, reset_ids  # noqa: E402


class TestImportBounds(unittest.TestCase):
    def setUp(self):
        reset_ids()

    def test_sheet_xy_keeps_bottom_edge_and_remaps_z_fence(self):
        self.assertEqual(sheet_xy((10.0, 0.0)), (10.0, 0.0))
        self.assertEqual(sheet_xy((10.0, 20.0, 0.1)), (10.0, 20.0))
        self.assertEqual(sheet_xy((10.0, 0.0, 500.0)), (10.0, 500.0))

    def test_huge_outlier_bbox_uses_in_page_ink(self):
        page = PageData(
            page_number=1,
            width=1219.2,
            height=914.4,
            primitives=[
                Primitive(
                    id=next_id(),
                    type="line",
                    points=[(10.0, 10.0), (100.0, 20.0)],
                ),
                Primitive(
                    id=next_id(),
                    type="line",
                    bbox=(-1.0e6, -1.0e6, 1.0e6, 1.0e6),
                    points=[(-1.0e6, -1.0e6), (1.0e6, 1.0e6)],
                ),
            ],
        )
        bounds = compute_import_bounds(page, apply_padding=False)
        self.assertIsNotNone(bounds)
        assert bounds is not None
        self.assertGreater(bounds.min_x, -100.0)
        self.assertLess(bounds.max_x, 200.0)


if __name__ == "__main__":
    unittest.main()

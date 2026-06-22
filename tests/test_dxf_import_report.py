# -*- coding: utf-8 -*-
"""GUI/CLI pipeline writes import_report beside DXF output."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfcadcore.import_config import ImportConfig
from dxf_import_engine import convert

try:
    import pymupdf as fitz
except ImportError:
    import fitz


class TestDxfImportReport(unittest.TestCase):
    def test_convert_writes_import_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_dxf_report_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            dxf_path = tmp_path / "sample.dxf"

            doc = fitz.open()
            page = doc.new_page(width=200, height=120)
            page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
            doc.save(str(pdf_path))
            doc.close()

            stats = convert(
                input_path=str(pdf_path),
                output_path=str(dxf_path),
                config=ImportConfig.vector(),
                dxf_version="R2010",
            )
            report_path = Path(stats["import_report_path"])
            self.assertTrue(report_path.is_file())
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], "bcs.import_report/1.1")
            self.assertEqual(data["host"]["app"], "librecad")
            self.assertIn("text_mode", data["extra"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

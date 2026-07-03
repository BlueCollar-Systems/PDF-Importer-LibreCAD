from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from librecad_pdf_importer.importer import run_import, write_import_report
from pdf2dxf import __version__

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback


class TestImportReportWriter(unittest.TestCase):
    def test_write_import_report_uses_package_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_import_report_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            report_path = tmp_path / "import_report.json"

            doc = fitz.open()
            page = doc.new_page(width=200, height=120)
            page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
            doc.save(str(pdf_path))

            run = run_import(str(pdf_path), mode="vector", overrides={"pages": "1"})
            result = write_import_report(
                run,
                str(report_path),
                elapsed_ms=15.0,
                performance_phases={
                    "run_import_ms": 11.0,
                    "export_dxf_ms": 4.0,
                },
            )

            self.assertEqual(result, str(report_path))
            data = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], "bcs.import_report/1.1")
            self.assertEqual(data["host"]["app"], "librecad")
            self.assertEqual(data["importer"]["version"], __version__)
            self.assertGreaterEqual(data["result"]["primitives"], 1)
            self.assertEqual(data["performance"]["phases"]["run_import_ms"], 11.0)
            self.assertEqual(data["performance"]["phases"]["export_dxf_ms"], 4.0)
            self.assertEqual(data["performance"]["phases"]["total_ms"], 15.0)
            self.assertIn("text_source_spans", data["extra"])
            self.assertIn("text_glyph_estimate", data["extra"])
            self.assertIn("actual_text_entity_types", data["extra"])
            self.assertIn("dxf_text", data["extra"]["actual_text_entity_types"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

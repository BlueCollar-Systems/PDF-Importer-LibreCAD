from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from librecad_pdf_importer.core.document import DocumentExtraction, ExtractedPage
from librecad_pdf_importer.importer import ImportRun, run_import, write_import_report
from pdf2dxf import __version__
from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText, PageData

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback


class TestImportReportWriter(unittest.TestCase):
    def _write_blank_pdf(self, path: Path) -> None:
        doc = fitz.open()
        doc.new_page(width=200, height=120)
        doc.save(str(path))
        doc.close()

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

    def test_write_import_report_emits_parts_bootstrap_sidecar(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_parts_bootstrap_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            self._write_blank_pdf(pdf_path)
            report_path = tmp_path / "import_report.json"
            texts = [
                NormalizedText(1, "1017FR1", "1017FR1", insertion=(10, 100), page_number=1),
                NormalizedText(2, "1", "1", insertion=(20, 100), page_number=1),
                NormalizedText(3, "W12X30", "W12X30", insertion=(30, 100), page_number=1),
                NormalizedText(4, "13'-11 1/4\"", "13'-11 1/4\"", insertion=(40, 100), page_number=1),
                NormalizedText(5, "417", "417", insertion=(50, 100), page_number=1),
                NormalizedText(6, "GALV.", "GALV.", insertion=(60, 100), page_number=1),
                NormalizedText(7, "A992", "A992", insertion=(70, 100), page_number=1),
            ]
            page = ExtractedPage(
                page_data=PageData(page_number=1, width=200, height=120, text_items=texts),
                profile=SimpleNamespace(titleblock_likely=False),
                resolved_mode="vector",
            )
            run = ImportRun(
                extraction=DocumentExtraction(str(pdf_path), pages=[page], requested_mode="vector"),
                config=ImportConfig.vector(),
            )

            write_import_report(run, str(report_path), elapsed_ms=15.0)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["extra"]["parts_bootstrap"]["row_count"], 1)
            self.assertEqual(report["extra"]["parts_bootstrap"]["sidecar_path"], "parts_bootstrap.json")
            sidecar = json.loads((tmp_path / "parts_bootstrap.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["schema"], "bcs.parts_bootstrap/1.0")
            self.assertEqual(sidecar["part_count"], 1)
            self.assertEqual(sidecar["rows"][0]["piece_mark"], "1017FR1")
            self.assertEqual(sidecar["rows"][0]["profile_hint"], "W12X30")
            self.assertIn("report_sha256", sidecar["import_build_stamp"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

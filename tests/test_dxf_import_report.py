# -*- coding: utf-8 -*-
"""GUI/CLI pipeline writes import_report beside DXF output."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.assertIn("phases", data["performance"])
            self.assertIn("total_ms", data["performance"]["phases"])
            self.assertIn("text_source_spans", data["extra"])

    def test_convert_closes_the_importer_owned_image_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_dxf_cleanup_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            dxf_path = tmp_path / "sample.dxf"

            doc = fitz.open()
            page = doc.new_page(width=200, height=120)
            page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
            doc.save(str(pdf_path))
            doc.close()

            real_temporary_directory = tempfile.TemporaryDirectory
            retained_workspaces = []

            def tracked_workspace(*args, **kwargs):
                kwargs["dir"] = str(tmp_path)
                workspace = real_temporary_directory(*args, **kwargs)
                retained_workspaces.append(workspace)
                return workspace

            with patch(
                "librecad_pdf_importer.core.document.tempfile.TemporaryDirectory",
                side_effect=tracked_workspace,
            ):
                convert(
                    input_path=str(pdf_path),
                    output_path=str(dxf_path),
                    config=ImportConfig.vector(),
                    dxf_version="R2010",
                )

            self.assertTrue(retained_workspaces)
            self.assertTrue(all(not Path(item.name).exists() for item in retained_workspaces))


if __name__ == "__main__":
    unittest.main(verbosity=2)

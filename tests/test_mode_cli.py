"""BCS-ARCH-001 CLI contract: --mode auto produces an auto_mode block (LC)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:
    import fitz


def _write_sample_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=120)
    page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
    page.insert_text((30, 60), "AISC W12x26", fontsize=10)
    doc.save(str(pdf_path))
    doc.close()


class TestModeCli(unittest.TestCase):
    """Smoke-test the ``--mode auto`` CLI contract for BCS-ARCH-001."""

    def test_cli_writes_import_report_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_mode_cli_report_") as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample.pdf"
            out_path = tmp_path / "summary.json"
            out_dxf = tmp_path / "out.dxf"

            _write_sample_pdf(pdf_path)

            cmd = [
                sys.executable,
                "-m",
                "librecad_pdf_importer.cli",
                str(pdf_path),
                "--mode",
                "vector",
                "--out",
                str(out_dxf),
                "--json",
                str(out_path),
            ]
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"CLI failed: stdout={result.stdout!r} stderr={result.stderr!r}",
            )

            data = json.loads(out_path.read_text(encoding="utf-8"))
            report_path = Path(data["export"]["import_report_path"])
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["host"]["app"], "librecad")
            self.assertIn("phases", report["performance"])
            self.assertIn("text_source_spans", report["extra"])

    def test_auto_mode_produces_auto_mode_block(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_mode_cli_") as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            out_path = Path(tmp) / "summary.json"
            out_dxf = Path(tmp) / "out.dxf"
            _write_sample_pdf(pdf_path)
            cmd = [
                sys.executable,
                "-m",
                "librecad_pdf_importer.cli",
                str(pdf_path),
                "--mode",
                "auto",
                "--out",
                str(out_dxf),
                "--json",
                str(out_path),
            ]
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"CLI failed: stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertTrue(out_path.is_file(), f"Expected output file: {out_path}")

            data = json.loads(out_path.read_text(encoding="utf-8"))
            # LC CLI nests extraction summary under 'import'.
            self.assertIn("import", data, "Summary JSON missing 'import' block")
            import_block = data["import"]
            self.assertIn("auto_mode", import_block, "Summary missing auto_mode block")

            block = import_block["auto_mode"]
            self.assertEqual(block.get("requested"), "auto")
            self.assertIsInstance(block.get("per_page"), list)
            self.assertGreaterEqual(len(block["per_page"]), 1)
            first = block["per_page"][0]
            self.assertIn(first.get("resolved"), {"vector", "raster", "hybrid"})
            self.assertIn("reason", first)
            self.assertIsInstance(block.get("summary"), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)

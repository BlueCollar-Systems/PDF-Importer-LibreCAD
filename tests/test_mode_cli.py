"""BCS-ARCH-001 CLI contract: --mode auto produces an auto_mode block (LC)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TEST_PDF_CANDIDATES = (
    Path(r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\1015 - Rev 0.pdf"),
    Path(r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\1017 - Rev 0.pdf"),
    Path(r"C:\Users\Rowdy Payton\Desktop\PDFTest Files\1021 - Rev 0.pdf"),
)
TEST_PDF = next((path for path in TEST_PDF_CANDIDATES if path.is_file()), TEST_PDF_CANDIDATES[0])


class TestModeCli(unittest.TestCase):
    """Smoke-test the ``--mode auto`` CLI contract for BCS-ARCH-001."""

    @unittest.skipUnless(TEST_PDF.is_file(), f"Test PDF not available: {TEST_PDF}")
    def test_auto_mode_produces_auto_mode_block(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_mode_cli_") as tmp:
            out_path = Path(tmp) / "summary.json"
            out_dxf = Path(tmp) / "out.dxf"
            cmd = [
                sys.executable,
                "-m",
                "librecad_pdf_importer.cli",
                str(TEST_PDF),
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

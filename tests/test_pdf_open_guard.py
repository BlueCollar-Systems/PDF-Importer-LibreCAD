from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pdf_open_guard import PdfOpenError, precheck_pdf


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPdfOpenGuard(unittest.TestCase):
    def test_rejects_empty_pdf_with_typed_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_guard_") as tmp:
            path = Path(tmp) / "empty.pdf"
            path.write_bytes(b"")

            with self.assertRaises(PdfOpenError) as ctx:
                precheck_pdf(str(path))

            self.assertEqual(ctx.exception.reason, "empty_file")

    def test_rejects_non_pdf_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_guard_") as tmp:
            path = Path(tmp) / "not-a-pdf.pdf"
            path.write_text("hello", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "pdf2dxf.py", str(path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a valid PDF", result.stderr)
            self.assertNotIn("Traceback", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

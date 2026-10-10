# -*- coding: utf-8 -*-
"""Open-time PDF gate: malformed inputs must reject cleanly, not traceback."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdfcadcore import fitz_loader
from pdfcadcore.fitz_loader import PdfOpenError, safe_open


class TestPdfOpenGate(unittest.TestCase):
    def test_empty_file_rejects_cleanly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "empty.pdf"
            path.write_bytes(b"")
            with self.assertRaises(PdfOpenError) as ctx:
                safe_open(str(path))
            self.assertEqual(ctx.exception.reason, "empty_file")

    def test_non_pdf_rejects_cleanly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "not.pdf"
            path.write_text("not a pdf", encoding="utf-8")
            with self.assertRaises(PdfOpenError) as ctx:
                safe_open(str(path))
            self.assertIn(ctx.exception.reason, {"not_a_pdf", "corrupt", "empty_file"})

    def test_em_dash_filename_opens_via_normal_path_delegation(self) -> None:
        minimal_pdf = (
            b"%PDF-1.1\n"
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 3 3] >>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"0000000009 00000 n \n0000000068 00000 n \n0000000125 00000 n \n"
            b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n196\n%%EOF\n"
        )
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "Shop\u2014Drawing.pdf"
            path.write_bytes(minimal_pdf)
            doc = safe_open(str(path))
            try:
                self.assertGreaterEqual(int(doc.page_count), 1)
            finally:
                doc.close()

    def test_safe_open_accepts_spaces_in_filename(self) -> None:
        minimal_pdf = (
            b"%PDF-1.1\n"
            b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
            b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 3 3] >>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"0000000009 00000 n \n0000000068 00000 n \n0000000125 00000 n \n"
            b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n196\n%%EOF\n"
        )
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "Large Sheet_ Section Details Rev.0 markup.pdf"
            path.write_bytes(minimal_pdf)
            doc = safe_open(str(path))
            try:
                self.assertGreaterEqual(int(doc.page_count), 1)
            finally:
                doc.close()

    def test_blank_password_encryption_is_still_locked(self) -> None:
        import pymupdf as fitz

        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "locked.pdf"
            document = fitz.open()
            document.new_page()
            document.save(
                path,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw="owner-secret",
                user_pw="",
            )
            document.close()
            with self.assertRaises(PdfOpenError) as ctx:
                safe_open(str(path))
            self.assertEqual(ctx.exception.reason, "password_protected")
            self.assertIn("password-protected", str(ctx.exception))

    def test_page_list_loop_is_a_plain_error(self) -> None:
        import pymupdf as fitz

        from librecad_pdf_importer.core.document import ExtractionOptions, extract_document

        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "cycle.pdf"
            document = fitz.open()
            document.new_page(width=100, height=100)
            document.save(path)
            document.close()
            document = fitz.open(path)
            parent = int(document.xref_get_key(document[0].xref, "Parent")[1].split()[0])
            document.update_object(
                parent,
                f"<< /Type /Pages /Kids [{parent} 0 R] /Count 1 >>",
            )
            cycled = Path(tmp) / "cycled.pdf"
            document.save(cycled, garbage=0, deflate=False, incremental=False)
            document.close()
            path = cycled
            with self.assertRaises(ValueError) as ctx:
                extract_document(str(path), ExtractionOptions(import_images=False, import_text=False))
            self.assertIn("page list refers to itself", str(ctx.exception))
            self.assertNotIn("FzErrorFormat", str(ctx.exception))

    def test_safe_open_reads_only_the_header_before_path_delegation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lc_open_gate_") as tmp:
            path = Path(tmp) / "large—drawing.pdf"
            path.write_bytes(b"%PDF-1.7\nsynthetic")

            class HeaderOnly:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                @staticmethod
                def read(size=-1):
                    if size != 1024:
                        raise AssertionError("safe_open must not read the whole PDF")
                    return b"%PDF-1.7\n"

            document = SimpleNamespace(
                needs_pass=False,
                is_encrypted=False,
                page_count=1,
            )
            fitz = SimpleNamespace(open=Mock(return_value=document))
            with (
                patch("builtins.open", return_value=HeaderOnly()),
                patch.object(fitz_loader, "import_fitz", return_value=fitz),
            ):
                self.assertIs(fitz_loader.safe_open(str(path)), document)

            fitz.open.assert_called_once_with(str(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)

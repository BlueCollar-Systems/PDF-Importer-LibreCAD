"""The PDF audit note never aborts a finished import on unallocated xref numbers.

An Aspose markup export lists its xref stream with /Index gaps; MuPDF raises its own
FzErrorFormat (an Exception, not a RuntimeError) for every unallocated number, and
the audit that probes each object for JavaScript actions used to let it escape after
the geometry had already been written.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pdfcadcore.import_report import _pdf_audit_extras, build_pdf_interactive_note  # noqa: E402


class _UnallocatedObject(Exception):
    """Shape of pymupdf.mupdf.FzErrorFormat: derives from Exception, not RuntimeError."""


def test_pdf_interactive_note_survives_unallocated_xref_numbers():
    class Doc:
        def pdf_catalog(self):
            return 2

        def xref_get_key(self, xref, key):
            if xref in (1, 4):
                raise _UnallocatedObject(f"code=7: cannot find object in xref ({xref} 0 R)")
            if xref == 3 and key == "S":
                return ("name", "/JavaScript")
            return ("null", "null")

        def xref_length(self):
            return 6

    note = build_pdf_interactive_note(Doc())
    assert note["pdf_interactive_flags"] == ["JavaScript"]


def _write_sparse_xref_pdf(path: Path) -> None:
    """A valid PDF whose xref table allocates objects 2, 3 and 5 only."""
    objects = {
        2: b"<< /Type /Catalog /Pages 3 0 R >>",
        3: b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
        5: b"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 200 100] >>",
    }
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for number, body in objects.items():
        offsets[number] = len(buf)
        buf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_pos = len(buf)
    buf += b"xref\n2 2\n"
    buf += b"%010d 00000 n \n" % offsets[2] + b"%010d 00000 n \n" % offsets[3]
    buf += b"5 1\n" + b"%010d 00000 n \n" % offsets[5]
    buf += b"trailer\n<< /Size 6 /Root 2 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref_pos
    path.write_bytes(bytes(buf))


def test_pdf_audit_extras_completes_on_a_sparse_xref_file(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    pdf_path = tmp_path / "sparse_xref.pdf"
    _write_sparse_xref_pdf(pdf_path)
    doc = fitz.open(str(pdf_path))
    with pytest.raises(Exception) as raised:
        doc.xref_get_key(1, "JS")
    assert not isinstance(raised.value, RuntimeError)
    doc.close()

    extras = _pdf_audit_extras(str(pdf_path))
    assert isinstance(extras, dict)
    assert "pdf_interactive_flags" not in extras

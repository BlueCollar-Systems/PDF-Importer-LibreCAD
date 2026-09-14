"""An unused object number must not abort a valid drawing's report."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for package in (ROOT / 'PDFVectorImporter', ROOT / 'pdf_vector_importer', ROOT):
    if (package / 'pdfcadcore').is_dir():
        sys.path.insert(0, str(package))
        break

from pdfcadcore.fitz_loader import import_fitz
from pdfcadcore.import_report import build_pdf_interactive_note


def sparse_pdf(javascript=False, missing_object=True):
    objects = {
        2: b'<< /Type /Catalog /Pages 3 0 R >>',
        3: b'<< /Type /Pages /Count 1 /Kids [4 0 R] >>',
        4: b'<< /Type /Page /Parent 3 0 R /MediaBox [0 0 300 200] /Contents 5 0 R >>',
        5: b'<< /Length 18 >>\nstream\n10 10 m 90 90 l S\n\nendstream',
    }
    if javascript:
        objects[6] = b'<< /S /JavaScript /JS (void 0) >>'
    data = bytearray(b'%PDF-1.5\n')
    offsets = {}
    for xref, body in objects.items():
        offsets[xref] = len(data)
        data.extend(str(xref).encode() + b' 0 obj\n' + body + b'\nendobj\n')
    # A sparse /Index in a cross-reference stream omits unused object 1,
    # unlike a dense classic table that initializes every slot as null.
    start = len(data)
    xref_object = max(objects) + 1
    size = xref_object + 1
    offsets[xref_object] = start
    indices = [0] + list(range(2, size)) if missing_object else list(range(size))
    entries = bytearray()
    for xref in indices:
        if xref in offsets:
            entries.extend(b'\x01' + offsets[xref].to_bytes(4, 'big') + b'\x00\x00')
        else:
            entries.extend(b'\x00\x00\x00\x00\x00\xff\xff')
    index = '0 1 2 %d' % (size - 2) if missing_object else '0 %d' % size
    data.extend(('%d 0 obj\n<< /Type /XRef /Root 2 0 R /Size %d /W [1 4 2] /Index [%s] /Length %d >>\nstream\n' %
                 (xref_object, size, index, len(entries))).encode())
    data.extend(entries)
    data.extend(('\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n' % start).encode())
    return bytes(data)


@pytest.mark.parametrize('javascript', [False, True])
@pytest.mark.parametrize('missing_object', [False, True])
def test_sparse_xref_does_not_abort_or_hide_later_javascript(javascript, missing_object):
    fitz = import_fitz()
    with fitz.open(stream=sparse_pdf(javascript, missing_object), filetype='pdf') as doc:
        assert len(doc) == 1
        assert len(doc[0].get_drawings()) == 1
        note = build_pdf_interactive_note(doc)
    assert note.get('pdf_interactive_flags', []) == (['JavaScript'] if javascript else [])
    if missing_object:
        assert note['pdf_interactive_audit']['status'] == 'partial'
        assert note['pdf_interactive_audit']['unreadable_xrefs'] == [1]
    else:
        assert 'pdf_interactive_audit' not in note


def test_action_audit_keeps_multiple_unreadable_objects_and_scans_on():
    fitz = import_fitz()

    class Doc:
        def pdf_catalog(self):
            return 2

        def xref_length(self):
            return 7

        def xref_get_key(self, xref, key):
            if xref in (1, 3):
                raise fitz.mupdf.FzErrorFormat('unreadable object')
            if xref == 6 and key == 'S':
                return ('name', '/JavaScript')
            return ('null', 'null')

    note = build_pdf_interactive_note(Doc())
    assert note['pdf_interactive_flags'] == ['JavaScript']
    assert note['pdf_interactive_audit']['unreadable_xrefs'] == [1, 3]

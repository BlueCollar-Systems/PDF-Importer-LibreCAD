"""Reject the native runtime defect and failed repeated text extraction."""

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from librecad_pdf_importer.runtime_self_test import (
    require_pymupdf_runtime,
    verify_texttrace_runtime,
)


@pytest.mark.parametrize("version", ["", "1.27.2.3", "1.28.0", "1.28.1", "2.0.0"])
def test_unsafe_or_unqualified_version_fails_before_opening_a_document(version):
    runtime = SimpleNamespace(__version__=version)
    with pytest.raises(RuntimeError, match="1.28.2 is required"):
        verify_texttrace_runtime(runtime)


def test_legacy_module_version_attribute_is_accepted():
    require_pymupdf_runtime(SimpleNamespace(VersionBind="1.28.2"))


class TraceDocument:
    def __init__(self, fail_late=False, corrupt_late=False):
        self.calls = 0
        self.texts = []
        self.closed = False
        self.fail_late = fail_late
        self.corrupt_late = corrupt_late

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def new_page(self, **_kwargs):
        return self

    def insert_text(self, _point, text, **_kwargs):
        self.texts.append(text)

    def get_texttrace(self):
        self.calls += 1
        if self.fail_late and self.calls == 2000:
            raise RuntimeError("delayed native getter failure")
        texts = self.texts[:]
        if self.corrupt_late and self.calls == 2000:
            texts[-1] = "changed source text"
        return [{"chars": [(ord(character),) for character in text]} for text in texts]


@pytest.mark.parametrize("kind", ["fail_late", "corrupt_late"])
def test_delayed_trace_failure_cannot_pass_runtime_promotion(kind):
    document = TraceDocument(**{kind: True})
    runtime = SimpleNamespace(__version__="1.28.2", open=lambda: document)
    with pytest.raises(RuntimeError):
        verify_texttrace_runtime(runtime)
    assert document.calls == 2000
    assert document.closed


def test_real_runtime_workload_requires_a_natural_clean_process_exit():
    root = Path(__file__).resolve().parents[1]
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from librecad_pdf_importer.runtime_self_test import verify_texttrace_runtime; "
        "import pymupdf; verify_texttrace_runtime(pymupdf); "
        "print('TRACE_WORKLOAD_COMPLETED')"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", probe, str(root)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "TRACE_WORKLOAD_COMPLETED"

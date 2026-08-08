"""The CLI's diagnostics must never crash on the user's own alphabet.

The shipped ``pdf2dxf.exe`` crashed with exit 1 whenever stdout was a pipe and
the output path contained a character outside the console codepage:

    File "pdf2dxf.py", line 217, in main
    File "encodings/cp1252.py", line 19, in encode
    UnicodeEncodeError: 'charmap' codec can't encode characters ...

The DXF was already on disk — a *diagnostic print* decided the exit code. With
``--verbose`` it was worse: the banner prints before conversion starts, so the
tool aborted having done nothing. And no user-side escape exists: the frozen
bootloader initialises an isolated ``PyConfig``, so ``PYTHONUTF8`` /
``PYTHONIOENCODING`` never reach the interpreter (all four documented escapes
were tested against the shipped exe; all four are ignored).

Reproduced against shipped v1.0.80 bytes with Cyrillic, Polish and CJK paths;
this is Section 12's "non-ASCII profile paths" clean-machine axis — a user
whose profile is ``C:\\Users\\Иван`` hits it converting a PDF in their own
Documents folder with no unusual arguments at all.

Two-layer fix, both asserted here:

1. The PyInstaller invocations request ``X utf8=1`` so the frozen interpreter
   starts in UTF-8 mode (pinned by source assertion — the cheapest gate that
   fails on a dev machine for a clean-machine defect).
2. ``pdf2dxf.main`` reconfigures its streams to a non-strict error handler and
   routes path-carrying prints through a safe printer, so even a hostile
   strict stream degrades to backslash-escaped text instead of deciding the
   exit code.

Paths in these tests are built from components under ``tmp_path`` — never
literal home paths (test_ci_portability forbids those).
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdf2dxf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Assembled, not literal, so the file itself stays greppably ASCII-safe where
# it matters and the portability guard has nothing to object to.
CYRILLIC_DIR = "\u0418\u0432\u0430\u043d"          # Ivan
MIXED_DIR = "\u0141\u00f3d\u017a_\u6d4b\u8bd5"      # Lodz + CJK


def _tiny_pdf(target: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=120, height=80)
    page.insert_text((36, 40), "beam")
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(target))
    doc.close()
    return target


class _StrictConsole(io.TextIOWrapper):
    """Exactly what a captured cp1252 stdout is: strict, and reconfigurable."""


def _strict_cp1252():
    return _StrictConsole(io.BytesIO(), encoding="cp1252", errors="strict")


# --- (a) the build requests UTF-8 mode for every frozen exe -------------------


def test_pyinstaller_argv_requests_utf8_mode_for_every_entrypoint():
    portable = (ROOT / "build_windows_portable.py").read_text(encoding="utf-8")
    assert '"X utf8=1"' in portable, (
        "build_windows_portable.py must pass --python-option 'X utf8=1'; "
        "without it the frozen interpreter inherits the locale codepage and "
        "no environment variable can fix it from outside"
    )
    # One shared run_pyinstaller() builds the argv for all four ENTRYPOINTS,
    # so the flag inside it covers every exe; pin that structure too.
    assert portable.index('"X utf8=1"') > portable.index("def run_pyinstaller"), (
        "the flag must sit inside run_pyinstaller so every entrypoint gets it"
    )


def test_standalone_build_requests_utf8_mode_too():
    standalone = (ROOT / "build_standalone.py").read_text(encoding="utf-8")
    assert '"X utf8=1"' in standalone


# --- (b) a diagnostic print cannot decide the exit code -----------------------


def test_summary_survives_a_strict_cp1252_stdout(tmp_path, monkeypatch):
    pdf = _tiny_pdf(tmp_path / "src" / "tiny.pdf")
    out = tmp_path / CYRILLIC_DIR / "gate.dxf"
    out.parent.mkdir(parents=True)

    monkeypatch.setattr(sys, "stdout", _strict_cp1252())
    monkeypatch.setattr(sys, "stderr", _strict_cp1252())

    rc = pdf2dxf.main([str(pdf), str(out)])

    assert rc == 0, (
        "the conversion succeeded and the DXF is on disk; a summary print "
        "must not turn that into a failure"
    )
    assert out.is_file() and out.stat().st_size > 0


def test_verbose_banner_cannot_abort_before_conversion(tmp_path, monkeypatch):
    """--verbose prints the paths BEFORE convert(); on the shipped exe that
    meant exit 1 with no DXF at all — total data loss from a banner."""
    pdf = _tiny_pdf(tmp_path / "src" / "tiny.pdf")
    out = tmp_path / MIXED_DIR / "verbose.dxf"
    out.parent.mkdir(parents=True)

    monkeypatch.setattr(sys, "stdout", _strict_cp1252())
    monkeypatch.setattr(sys, "stderr", _strict_cp1252())

    rc = pdf2dxf.main([str(pdf), str(out), "--verbose"])

    assert rc == 0
    assert out.is_file() and out.stat().st_size > 0


def test_default_output_next_to_a_nonascii_input(tmp_path, monkeypatch):
    """No output argument at all: the path is derived from the input stem —
    Section 12's profile case, a PDF in the user's own folder."""
    pdf = _tiny_pdf(tmp_path / CYRILLIC_DIR / "tiny.pdf")

    monkeypatch.setattr(sys, "stdout", _strict_cp1252())
    monkeypatch.setattr(sys, "stderr", _strict_cp1252())

    rc = pdf2dxf.main([str(pdf)])

    assert rc == 0
    assert (tmp_path / CYRILLIC_DIR / "tiny.dxf").is_file()


def test_safe_print_degrades_even_without_reconfigure():
    """A stream with no reconfigure() at all still must not raise."""

    class Rigid:
        def __init__(self):
            self.lines = []

        def write(self, text):
            text.encode("cp1252", "strict")  # the hostile part
            self.lines.append(text)
            return len(text)

        def flush(self):
            return None

    rigid = Rigid()
    pdf2dxf._safe_print("path: " + CYRILLIC_DIR, file=rigid)
    joined = "".join(rigid.lines)
    assert "\\u" in joined, "unencodable text must degrade to escapes, not raise"


# --- (c) the shipped bytes, when present ------------------------------------


@pytest.mark.skipif(
    os.environ.get("BC_TEST_SHIPPED_EXES") != "1",
    reason="opt-in: dist/windows-portable holds bytes from the last release "
    "build, which predate source fixes until rebuilt; set "
    "BC_TEST_SHIPPED_EXES=1 after build_windows_portable.py to gate them",
)
def test_shipped_exe_survives_piped_stdout_and_nonascii_path(tmp_path):
    exe = ROOT / "dist" / "windows-portable" / "pdf2dxf.exe"
    assert exe.is_file(), "run build_windows_portable.py first"
    pdf = _tiny_pdf(tmp_path / CYRILLIC_DIR / "tiny.pdf")
    out = tmp_path / CYRILLIC_DIR / "shipped.dxf"
    for extra in ([], ["--verbose"]):
        result = subprocess.run(
            [str(exe), str(pdf), str(out)] + extra,
            capture_output=True,  # a pipe is the discriminator
            timeout=600,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        assert out.is_file()
        out.unlink()

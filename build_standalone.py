#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# build_standalone.py -- freeze the LibreCAD PDF Importer into a self-contained app.
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
"""
Build a fully self-contained Windows app for the LibreCAD PDF Importer.

Freezes the Tkinter GUI together with CPython, PyMuPDF, ezdxf, pdfcadcore,
and librecad_pdf_importer so the END USER needs NO system Python and NO pip
installs. Output: dist/LibreCAD-PDF-Importer/ (one-folder app). Wrap it with
installer/librecad-pdf-importer.iss (Inno Setup 6) to produce a double-click
Setup.exe.

Usage (from the repo root):
    python build_standalone.py

The script creates build/standalone-build-venv and installs only the freeze-time
dependencies needed for the release artifact.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "LibreCAD-PDF-Importer"
ENTRY = ROOT / "standalone_app.py"
ICON = ROOT / "installer" / "app.ico"  # optional; used if present
VENV_ROOT = ROOT / "build" / "standalone-build-venv"
WORK_ROOT = ROOT / "build" / "pyinstaller_standalone"
SPEC_ROOT = ROOT / "build" / "pyinstaller_standalone_specs"
DIST_ROOT = ROOT / "dist"
APP_DIST = DIST_ROOT / APP_NAME
BUILD_REQUIREMENTS = [
    "pyinstaller",
    "PyMuPDF>=1.24,<2.0",
    "ezdxf>=1.0",
]


def _read_version() -> str:
    """Single source of truth: pdf2dxf.__version__."""
    text = (ROOT / "pdf2dxf.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise RuntimeError("Could not read __version__ from pdf2dxf.py")
    return match.group(1)


def _build_python() -> Path:
    if not VENV_ROOT.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_ROOT)], cwd=ROOT, check=True)
    python_exe = VENV_ROOT / "Scripts" / "python.exe"
    subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            *BUILD_REQUIREMENTS,
        ],
        cwd=ROOT,
        check=True,
    )
    return python_exe


def main() -> int:
    version = _read_version()
    print(f"Building {APP_NAME} v{version}")

    python_exe = _build_python()

    for p in (APP_DIST, WORK_ROOT, SPEC_ROOT):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    cmd = [
        str(python_exe), "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",                       # GUI app: no console window
        "--name", APP_NAME,
        "--distpath", str(DIST_ROOT),
        "--workpath", str(WORK_ROOT),
        "--specpath", str(SPEC_ROOT),
        "--collect-all", "pymupdf",         # PyMuPDF binaries + data (embeds MuPDF)
        "--collect-data", "ezdxf",          # ezdxf resource data only (avoids optional PIL/matplotlib drawing addon)
        "--hidden-import", "fitz",          # PyMuPDF compat shim
        "--hidden-import", "pymupdf",
        "--collect-submodules", "pdfcadcore",
        "--collect-submodules", "librecad_pdf_importer",
        "--paths", str(ROOT),
    ]
    if ICON.exists():
        cmd += ["--icon", str(ICON)]
    cmd.append(str(ENTRY))

    print("Running:", " ".join(cmd))
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if result.returncode != 0:
        print("PyInstaller build FAILED", file=sys.stderr)
        return result.returncode

    print(f"\nBuild complete: {APP_DIST}")
    print("Next: compile installer/librecad-pdf-importer.iss with Inno Setup 6 (iscc).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

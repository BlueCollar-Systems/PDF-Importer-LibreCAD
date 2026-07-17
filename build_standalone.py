#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# build_standalone.py -- freeze the LibreCAD PDF Importer into a self-contained app.
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
"""
Build a fully self-contained Windows app for the LibreCAD PDF Importer.

Freezes the Tkinter GUI together with CPython, PyMuPDF, ezdxf, FontTools, pdfcadcore,
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

from release_notices import copy_python_distribution_notices, copy_release_notices
from runtime_requirements import load_runtime_requirements

ROOT = Path(__file__).resolve().parent
APP_NAME = "LibreCAD-PDF-Importer"
ENTRY = ROOT / "standalone_app.py"
ICON = ROOT / "installer" / "app.ico"  # optional; used if present
VENV_ROOT = ROOT / "build" / "standalone-build-venv"
WORK_ROOT = ROOT / "build" / "pyinstaller_standalone"
SPEC_ROOT = ROOT / "build" / "pyinstaller_standalone_specs"
DIST_ROOT = ROOT / "dist"
APP_DIST = DIST_ROOT / APP_NAME
BUILD_REQUIREMENTS = ["pyinstaller", *load_runtime_requirements(ROOT)]


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


def _remove_tree_strict(path: Path, *, allowed_parent: Path) -> None:
    """Remove a stale build tree or stop before producing a mixed artifact."""

    resolved = path.resolve()
    parent = allowed_parent.resolve()
    if resolved.parent != parent:
        raise RuntimeError(f"refusing to remove path outside build root: {resolved}")
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise RuntimeError(f"could not remove stale build path: {resolved}: {exc}") from exc
    if path.exists():
        raise RuntimeError(f"could not remove stale build path: {resolved}")


def main() -> int:
    version = _read_version()
    print(f"Building {APP_NAME} v{version}")

    python_exe = _build_python()

    for path, allowed_parent in (
        (APP_DIST, DIST_ROOT),
        (WORK_ROOT, WORK_ROOT.parent),
        (SPEC_ROOT, SPEC_ROOT.parent),
    ):
        _remove_tree_strict(path, allowed_parent=allowed_parent)

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
        "--collect-all", "fontTools",       # exact embedded-font parsing and outline conversion
        "--copy-metadata", "fonttools",     # preserve upstream licenses and package metadata
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

    copy_release_notices(ROOT, APP_DIST)
    copy_python_distribution_notices(
        python_exe.parent.parent / "Lib" / "site-packages",
        APP_DIST,
    )
    executable = APP_DIST / f"{APP_NAME}.exe"
    if not executable.is_file():
        print(f"PyInstaller build FAILED: missing {executable}", file=sys.stderr)
        return 1
    try:
        smoke = subprocess.run(
            [str(executable), "--self-test"],
            cwd=str(APP_DIST),
            env=env,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("PyInstaller runtime self-test TIMED OUT after 60s", file=sys.stderr)
        return 1
    if smoke.returncode != 0:
        print("PyInstaller runtime self-test FAILED", file=sys.stderr)
        return smoke.returncode or 1

    print(f"\nBuild complete: {APP_DIST}")
    print(
        "Next: compile with Inno Setup 6: "
        f"iscc /DAppVersion={version} installer/librecad-pdf-importer.iss"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

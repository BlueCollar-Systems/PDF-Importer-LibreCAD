# -*- coding: utf-8 -*-
# build_release.py -- Build a release zip for distribution
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Packages the PDF-to-DXF converter into a distributable zip file.
Output: LibreCAD-PDF-Importer_vX.Y.Z.zip.
Includes all Python source files and the pdfcadcore library.
Excludes ``__pycache__``, ``.pyc``, and ``tests/``.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent


def _read_version() -> str:
    """Extract ``__version__`` from ``pdf2dxf.py``."""
    init_path = _PROJECT_ROOT / "pdf2dxf.py"
    text = init_path.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        print("Warning: could not read version from pdf2dxf.py, using 0.0.0")
        return "0.0.0"
    return match.group(1)


def _should_include(rel_path: str) -> bool:
    """Return True if *rel_path* should be included in the release zip."""
    parts = rel_path.replace("\\", "/").split("/")

    if "_archived" in parts:
        return False

    # Exclude hidden directories
    if any(p.startswith(".") for p in parts):
        return False

    # Exclude generated/build directories
    if "generated" in parts or "release" in parts or "debug" in parts:
        return False

    # Exclude __pycache__ and compiled bytecode
    if "__pycache__" in parts:
        return False
    if rel_path.endswith((".pyc", ".pyo")):
        return False

    if rel_path.endswith(
        (
            ".obj", ".o", ".dll", ".lib", ".exp", ".pdb", ".ilk", ".idb",
            ".manifest", ".res", ".log", ".tlog", ".cache",
        )
    ):
        return False

    # Exclude test directories
    if "tests" in parts or "test" in parts:
        return False

    # Exclude benchmarks
    if "benchmarks" in parts:
        return False

    # Exclude dev-only files
    basename = os.path.basename(rel_path)
    if basename in ("requirements-dev.txt",):
        return False
    if basename.startswith("Makefile"):
        return False
    if basename.endswith("_resource.rc"):
        return False

    return True


def build(output_dir: str | None = None) -> Path:
    """Create the release zip and return its path."""
    version = _read_version()
    zip_name = f"LibreCAD-PDF-Importer_v{version}.zip"

    if output_dir is None:
        dist_dir = _PROJECT_ROOT / "dist"
    else:
        dist_dir = Path(output_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / zip_name

    # Collect files
    files_to_add: list[tuple[Path, str]] = []

    # Walk project root (top-level files)
    for item in _PROJECT_ROOT.iterdir():
        if item.is_file():
            rel = item.relative_to(_PROJECT_ROOT).as_posix()
            if _should_include(rel):
                files_to_add.append((item, rel))

    # Walk package and auxiliary directories
    for package_dir_name in ("pdfcadcore", "librecad_pdf_importer", "plugin", "lib"):
        package_dir = _PROJECT_ROOT / package_dir_name
        if not package_dir.is_dir():
            continue
        for root, _dirs, filenames in os.walk(package_dir):
            for fname in filenames:
                full = Path(root) / fname
                rel = full.relative_to(_PROJECT_ROOT).as_posix()
                if _should_include(rel):
                    files_to_add.append((full, rel))

    # Build zip
    print(f"Building {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for full_path, arc_name in sorted(files_to_add, key=lambda x: x[1]):
            zf.write(full_path, arc_name)
            print(f"  + {arc_name}")

    print(f"\nRelease archive: {zip_path}")
    print(f"  Files: {len(files_to_add)}")
    print(f"  Size:  {zip_path.stat().st_size:,} bytes")
    return zip_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    build(output_dir=out)

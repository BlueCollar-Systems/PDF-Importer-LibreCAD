# -*- coding: utf-8 -*-
# build_release.py -- Build a release zip for distribution
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Packages the PDF-to-DXF converter into a source-only distributable zip file.
Output: LibreCAD-PDF-Importer_vX.Y.Z.zip.
Includes all Python source files and the pdfcadcore library.
Excludes ``__pycache__``, ``.pyc``, and ``tests/``.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from deterministic_zip import write_deterministic_zip

_PROJECT_ROOT = Path(__file__).resolve().parent
_PACKAGE_DIRECTORIES = {
    "pdfcadcore",
    "librecad_pdf_importer",
    "plugin",
    "tools",
    "third_party",
    "installer",
    "scripts",
}


def _read_version() -> str:
    """Extract ``__version__`` from ``pdf2dxf.py``."""
    init_path = _PROJECT_ROOT / "pdf2dxf.py"
    text = init_path.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise RuntimeError("Could not read __version__ from pdf2dxf.py")
    return match.group(1)


def _should_include(rel_path: str) -> bool:
    """Return True if *rel_path* should be included in the release zip."""
    normalized = rel_path.replace("\\", "/")
    parts = normalized.split("/")
    lower_path = normalized.lower()
    lower_parts = [part.lower() for part in parts]
    basename = os.path.basename(normalized)
    lower_basename = basename.lower()

    # User-supplied PDFs, CAD/model outputs derived from them, sweep reports,
    # and nested archives are evidence -- never product payload.  This guard is
    # independent of .gitignore because the builder walks the live filesystem.
    if lower_basename.endswith(
        (
            ".pdf",
            ".dxf",
            ".dwg",
            ".skp",
            ".fcstd",
            ".fcstd1",
            ".blend",
            ".blend1",
            ".zip",
            ".7z",
            ".rar",
            ".tar",
            ".gz",
            ".rbz",
        )
    ):
        return False
    if lower_basename.endswith("_import_report.json") or lower_basename.endswith(
        "_failed_import_report.json"
    ):
        return False
    if any(part.endswith("_assets") for part in lower_parts):
        return False
    if any(
        marker in lower_path
        for marker in ("imported evidence", "pdf-test-corpus", "pdftest files")
    ):
        return False

    if "_archived" in parts:
        return False

    # Runtime wheels are never opportunistically copied into the source ZIP.
    # Users install the complete declared dependency set with preflight_check;
    # portable builds use the fail-closed PyInstaller builders instead.
    if parts and parts[0] == "lib":
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
    if basename in ("requirements-dev.txt",):
        return False
    if basename.startswith("Makefile"):
        return False
    if basename.endswith("_resource.rc"):
        return False

    return True


def _tracked_project_files(project_root: Path) -> list[Path] | None:
    """Return tracked files for a checkout, or ``None`` for a source archive."""

    if not (project_root / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={project_root.resolve()}",
                "ls-files",
                "-z",
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "release build could not enumerate tracked repository files"
        ) from exc

    tracked = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
        candidate = (project_root / relative).resolve()
        if not candidate.is_relative_to(project_root.resolve()):
            raise RuntimeError(f"tracked release path escapes repository: {relative}")
        if candidate.is_file():
            tracked.append(candidate)
    return tracked


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

    # Collect files. A live checkout is fail-closed to tracked paths so ignored
    # working-environment notes or fixtures cannot enter an accepted archive.
    files_to_add: list[tuple[Path, str]] = []
    tracked_files = _tracked_project_files(_PROJECT_ROOT)
    if tracked_files is not None:
        for item in tracked_files:
            relative = item.relative_to(_PROJECT_ROOT)
            if len(relative.parts) == 1 or relative.parts[0] in _PACKAGE_DIRECTORIES:
                rel = relative.as_posix()
                if _should_include(rel):
                    files_to_add.append((item, rel))
    else:
        # A distributed source ZIP has no .git metadata. Its contents were
        # already produced by the tracked-only checkout path above.
        for item in _PROJECT_ROOT.iterdir():
            if item.is_file():
                rel = item.relative_to(_PROJECT_ROOT).as_posix()
                if _should_include(rel):
                    files_to_add.append((item, rel))
        for package_dir_name in sorted(_PACKAGE_DIRECTORIES):
            package_dir = _PROJECT_ROOT / package_dir_name
            if not package_dir.is_dir():
                continue
            for root, _dirs, filenames in os.walk(package_dir):
                for fname in filenames:
                    full = Path(root) / fname
                    rel = full.relative_to(_PROJECT_ROOT).as_posix()
                    if _should_include(rel):
                        files_to_add.append((full, rel))

    # Build a byte-reproducible ZIP. Checkout mtimes and host OS metadata must
    # never change the accepted release hash for an identical source tree.
    print(f"Building {zip_path.name} ...")
    write_deterministic_zip(zip_path, files_to_add)
    for _full_path, arc_name in sorted(files_to_add, key=lambda x: x[1]):
        print(f"  + {arc_name}")

    print(f"\nRelease archive: {zip_path}")
    print(f"  Files: {len(files_to_add)}")
    print(f"  Size:  {zip_path.stat().st_size:,} bytes")
    return zip_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    build(output_dir=out)

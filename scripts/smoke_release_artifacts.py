#!/usr/bin/env python3
"""Smoke-test the shipped LibreCAD source and Windows-portable ZIPs."""
from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


SOURCE_REQUIRED_MEMBERS = {
    "pdf2dxf.py",
    "dxf_builder.py",
    "dxf_text_builder.py",
    "dxf_import_engine.py",
    "gui.py",
    "preflight_check.py",
    "pdfcadcore/fitz_loader.py",
    "librecad_pdf_importer/__init__.py",
}

PORTABLE_REQUIRED_MEMBERS = {
    "pdf2dxf.exe",
    "lcpdf-import.exe",
    "lcpdf-batch.exe",
    "lcpdf-gui.exe",
}


def _resolve_zip(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise SystemExit(f"No release ZIP matched {pattern!r}")
    return Path(matches[-1]).resolve()


def _check_members(zip_path: Path, required: set[str], label: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        missing = sorted(required - names)
        if missing:
            raise SystemExit(
                f"{label} is missing required members: " + ", ".join(missing)
            )


def _run_portable_cli_smoke(zip_path: Path) -> None:
    if sys.platform != "win32":
        return
    with zipfile.ZipFile(zip_path, "r") as zf:
        with tempfile.TemporaryDirectory(prefix="lc_portable_zip_") as tmp:
            root = Path(tmp)
            zf.extractall(root)
            for exe_name in ("pdf2dxf.exe", "lcpdf-import.exe", "lcpdf-batch.exe"):
                exe = root / exe_name
                proc = subprocess.run(
                    [str(exe), "--help"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode != 0:
                    raise SystemExit(
                        f"{exe_name} --help failed from portable ZIP: "
                        + (proc.stderr.strip() or proc.stdout.strip())
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_zip", help="Source ZIP path or glob pattern")
    parser.add_argument("portable_zip", help="Windows portable ZIP path or glob pattern")
    args = parser.parse_args()

    source_zip = _resolve_zip(args.source_zip)
    portable_zip = _resolve_zip(args.portable_zip)

    _check_members(source_zip, SOURCE_REQUIRED_MEMBERS, "Source release ZIP")
    _check_members(portable_zip, PORTABLE_REQUIRED_MEMBERS, "Windows portable ZIP")
    _run_portable_cli_smoke(portable_zip)

    print(f"Source ZIP smoke passed: {source_zip.name}")
    print(f"Portable ZIP smoke passed: {portable_zip.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

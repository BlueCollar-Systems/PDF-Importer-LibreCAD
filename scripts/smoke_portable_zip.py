#!/usr/bin/env python3
"""Smoke-test the shipped LibreCAD Windows portable ZIP."""
from __future__ import annotations

import argparse
import glob
import subprocess
import tempfile
import zipfile
from pathlib import Path


REQUIRED_EXES = (
    "lcpdf-gui.exe",
    "pdf2dxf.exe",
    "lcpdf-import.exe",
    "lcpdf-batch.exe",
)


def _resolve_zip(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise SystemExit(f"No portable ZIP matched {pattern!r}")
    return Path(matches[-1]).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", help="Portable ZIP path or glob pattern")
    args = parser.parse_args()

    zip_path = _resolve_zip(args.zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = {Path(n).name for n in zf.namelist()}
        missing = [exe for exe in REQUIRED_EXES if exe not in names]
        if missing:
            raise SystemExit(
                "Portable ZIP is missing required executables: "
                + ", ".join(missing)
            )

    with tempfile.TemporaryDirectory(prefix="lc_portable_") as tmp:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        proc = subprocess.run(
            [str(Path(tmp) / "pdf2dxf.exe"), "--help"],
            capture_output=True,
            text=True,
        )
        combined = (proc.stdout + proc.stderr).lower()
        if proc.returncode != 0 and "usage" not in combined:
            raise SystemExit(
                "pdf2dxf.exe --help failed: "
                + (proc.stderr.strip() or proc.stdout.strip())
            )

    print(f"Portable ZIP smoke passed: {zip_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# preflight_check.py — one-click dependency check for LibreCAD PDF Importer
# Copyright (c) 2024-2026 BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from librecad_pdf_importer.dependency_manager import (  # noqa: E402
    install_runtime_deps,
    print_diagnostics,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check/install LibreCAD PDF Importer dependencies")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install PyMuPDF, ezdxf, and FontTools into ./lib (no admin required)",
    )
    args = parser.parse_args()

    if args.install:
        ok = install_runtime_deps()
        if not ok:
            return 1
    return print_diagnostics()


if __name__ == "__main__":
    raise SystemExit(main())

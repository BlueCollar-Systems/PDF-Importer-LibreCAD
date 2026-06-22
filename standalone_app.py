# -*- coding: utf-8 -*-
# standalone_app.py -- PyInstaller entry point for the self-contained GUI.
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Entry point for the frozen, standalone LibreCAD PDF Importer.

This wraps gui.launch_gui so PyInstaller can bundle CPython + PyMuPDF +
ezdxf + pdfcadcore + librecad_pdf_importer into a single app that needs no
system Python and no pip installs. See build_standalone.py.
"""
from __future__ import annotations

import multiprocessing
import sys


def self_test() -> int:
    """Verify the frozen app can load its bundled runtime dependencies."""
    try:
        import ezdxf  # noqa: F401
        import pdfcadcore  # noqa: F401
        import librecad_pdf_importer  # noqa: F401
        try:
            import pymupdf as fitz  # noqa: F401
        except ImportError:
            import fitz  # noqa: F401
    except Exception as exc:
        print(f"LibreCAD PDF Importer self-test FAILED: {exc}")
        return 1
    print("LibreCAD PDF Importer self-test OK")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    # Required so frozen builds don't re-launch the GUI in worker processes.
    multiprocessing.freeze_support()
    from gui import launch_gui
    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

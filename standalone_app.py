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


def main() -> None:
    # Required so frozen builds don't re-launch the GUI in worker processes.
    multiprocessing.freeze_support()
    from gui import launch_gui
    launch_gui()


if __name__ == "__main__":
    main()

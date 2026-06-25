# -*- coding: utf-8 -*-
# pdf2dxf.py -- CLI entry point for PDF to DXF conversion
# Copyright (c) 2024-2026 BlueCollar Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""
Standalone PDF-to-DXF converter.  Generates DXF files that open natively
in LibreCAD, AutoCAD, DraftSight, QCAD, and any DXF-compatible program.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

__version__ = "1.0.46"

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so ``import pdfcadcore`` resolves
# when running from any working directory.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# BCS-ARCH-001: four modes, one classmethod each. No preset map.
DXF_VERSIONS = ("R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf2dxf",
        description=(
            "PDF to DXF Converter -- BlueCollar Systems\n"
            "Convert PDF vector drawings to DXF for use with LibreCAD, "
            "AutoCAD, DraftSight, QCAD, and any DXF-compatible CAD software."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", nargs="?", default=None, help="Input PDF file path")
    p.add_argument("output", nargs="?", default=None,
                   help="Output DXF file path (default: <input>.dxf)")

    p.add_argument("--pages", default=None,
                   help="Comma-separated page numbers to convert (default: all)")
    p.add_argument("--mode", default="auto",
                   choices=["auto", "vector", "raster", "hybrid"],
                   help="Import mode (BCS-ARCH-001, default: auto)")
    p.add_argument("--scale", type=float, default=1.0,
                   help="Scale factor (default: 1.0)")
    p.add_argument("--text-mode", default=None,
                   choices=["labels", "3d_text", "glyphs", "geometry"],
                   help="Text rendering (orthogonal to --mode)")
    p.add_argument("--import-text",
                   action=argparse.BooleanOptionalAction,
                   default=None,
                   help="Import text from the PDF (--no-import-text to skip)")
    p.add_argument("--dxf-version", default="R2010", choices=DXF_VERSIONS,
                   help="DXF version (default: R2010)")
    p.add_argument("--gui", action="store_true",
                   help="Launch the GUI instead of CLI conversion")
    p.add_argument("--verbose", action="store_true",
                   help="Print progress information")
    p.add_argument(
        "--preflight",
        action="store_true",
        help="Print pre-import guidance (text modes, scale trust) and exit",
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    return p


def _parse_pages(raw: str | None) -> list[int] | None:
    """Parse ``--pages 1,3,5`` into a zero-indexed list."""
    if raw is None:
        return None
    pages: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    # User supplies 1-based page numbers; convert to 0-based for PyMuPDF
    return [max(0, p - 1) for p in pages]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.preflight:
        from pdfcadcore.preflight_copy import preflight_paragraph

        print(preflight_paragraph("librecad"))
        return 0

    # --gui: hand off to tkinter frontend
    if args.gui:
        try:
            from gui import launch_gui  # noqa: WPS433
            launch_gui()
            return 0
        except ImportError as exc:
            print(f"GUI unavailable: {exc}", file=sys.stderr)
            return 1

    # Validate input (CLI mode only)
    if not args.input:
        print("Error: input file path is required unless --gui is used.", file=sys.stderr)
        return 1
    if not os.path.isfile(args.input):
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1

    # Open-time gate: reject encrypted/empty/non-PDF cleanly (no traceback).
    from pdf_open_guard import precheck_pdf, PdfOpenError
    try:
        precheck_pdf(args.input)
    except PdfOpenError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Derive output path
    output = args.output
    if output is None:
        stem = os.path.splitext(args.input)[0]
        output = stem + ".dxf"

    # BCS-ARCH-001: direct mode -> classmethod dispatch.
    from pdfcadcore.import_config import ImportConfig

    factory = getattr(ImportConfig, args.mode)
    config: ImportConfig = factory()
    config.user_scale = args.scale
    config.verbose = args.verbose
    if args.text_mode is not None:
        config.text_mode = args.text_mode
        config.import_text = True
    if args.import_text is not None:
        config.import_text = bool(args.import_text)
    if args.pages:
        config.pages = _parse_pages(args.pages)

    # Run conversion
    from dxf_import_engine import convert
    from pdfcadcore.fitz_loader import PdfOpenError

    if args.verbose:
        print(f"pdf2dxf {__version__} -- BlueCollar Systems")
        print(f"  Input:  {args.input}")
        print(f"  Output: {output}")
        print(f"  Mode:   {args.mode}")
        print(f"  DXF:    {args.dxf_version}")
        print()

    t0 = time.perf_counter()

    def _progress(msg: str) -> None:
        if args.verbose:
            print(f"  [{time.perf_counter() - t0:.1f}s] {msg}")

    try:
        stats = convert(
            input_path=args.input,
            output_path=output,
            config=config,
            dxf_version=args.dxf_version,
            progress_callback=_progress if args.verbose else None,
        )
    except PdfOpenError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    elapsed = time.perf_counter() - t0

    # Summary
    print()
    print("Conversion complete.")
    print(f"  Pages converted: {stats.get('pages', '?')}")
    print(f"  Entities:        {stats.get('entities', '?')}")
    print(f"  Text items:      {stats.get('text_items', 0)}")
    print(f"  Output:          {output}")
    print(f"  Time:            {elapsed:.2f}s")
    report_path = stats.get("import_report_path")
    if report_path:
        print(f"  import_report:   {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

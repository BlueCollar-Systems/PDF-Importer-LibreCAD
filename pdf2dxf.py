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

__version__ = "1.0.95"

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
                   choices=["text", "labels", "3d_text", "glyphs", "geometry", "raster"],
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
        "--resume",
        action="store_true",
        help=(
            "Checkpoint each certified page and resume matching work after Cancel "
            "or interruption"
        ),
    )
    p.add_argument(
        "--preflight",
        action="store_true",
        help="Print pre-import guidance (text modes, scale trust) and exit",
    )
    p.add_argument(
        "--self-test",
        action="store_true",
        help="Verify all bundled runtime dependencies and exit",
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    return p


def _parse_pages(raw: str | None) -> list[int] | None:
    """Parse ``--pages 1,3,5`` into a zero-indexed list."""
    from page_selection import parse_page_selection

    return parse_page_selection(raw)


def _ensure_stdio_can_carry_paths() -> None:
    """Stop the console codepage from deciding the exit code.

    A frozen console exe inherits the locale codepage (cp1252 on US Windows)
    for redirected stdio, and the PyInstaller bootloader's isolated PyConfig
    means PYTHONUTF8/PYTHONIOENCODING cannot fix it from outside. A strict
    stream then raises UnicodeEncodeError the moment a diagnostic print
    carries the user's own path -- after the DXF was already written. Keep the
    stream's encoding (so cp1252-representable names still render exactly) and
    relax only the error handler.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            pass


def _safe_print(text: str = "", *, file: object = None) -> None:
    """Print a diagnostic without ever letting it raise.

    Belt to _ensure_stdio_can_carry_paths' braces: a stream with no
    reconfigure() (or one swapped in later) still must not turn a successful
    conversion into a failure. Unencodable text degrades to ASCII escapes.
    """
    target = file if file is not None else sys.stdout
    try:
        print(text, file=target)
    except UnicodeEncodeError:
        print(text.encode("ascii", "backslashreplace").decode("ascii"),
              file=target)


def main(argv: list[str] | None = None) -> int:
    _ensure_stdio_can_carry_paths()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.preflight:
        from pdfcadcore.preflight_copy import preflight_paragraph

        print(preflight_paragraph("librecad"))
        return 0

    if args.self_test:
        from librecad_pdf_importer.runtime_self_test import run_runtime_self_test

        return run_runtime_self_test()

    # --gui: hand off to tkinter frontend
    if args.gui:
        try:
            from gui import launch_gui  # noqa: WPS433
            launch_gui()
            return 0
        except ImportError as exc:
            print(f"GUI unavailable: {exc}", file=sys.stderr)
            return 1

    if not args.input:
        from pdfcadcore.cli_error_copy import cli_error

        print(cli_error("missing_input"), file=sys.stderr)
        return 1
    if not os.path.isfile(args.input):
        from pdfcadcore.cli_error_copy import cli_error

        print(cli_error("file_not_found", path=args.input), file=sys.stderr)
        return 1

    # Open-time gate: reject encrypted/empty/non-PDF cleanly (no traceback).
    from pdf_open_guard import precheck_pdf, PdfOpenError
    try:
        precheck_pdf(args.input)
    except PdfOpenError as exc:
        from pdfcadcore.cli_error_copy import cli_error

        _safe_print(cli_error("not_a_pdf", message=str(exc)), file=sys.stderr)
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
    config.text_mode = "text"
    if args.text_mode is not None:
        config.text_mode = args.text_mode
        config.import_text = True
    if args.import_text is not None:
        config.import_text = bool(args.import_text)
    if args.pages:
        try:
            config.pages = _parse_pages(args.pages)
        except ValueError as exc:
            print(f"Invalid --pages value: {exc}", file=sys.stderr)
            return 2

    # Run conversion
    from dxf_import_engine import ConversionCancelled, convert
    from pdfcadcore.fitz_loader import PdfOpenError

    if args.verbose:
        # _safe_print: these carry the user's own paths and run BEFORE the
        # conversion -- a banner must never abort the tool with no DXF at all.
        _safe_print(f"pdf2dxf {__version__} -- BlueCollar Systems")
        _safe_print(f"  Input:  {args.input}")
        _safe_print(f"  Output: {output}")
        _safe_print(f"  Mode:   {args.mode}")
        _safe_print(f"  DXF:    {args.dxf_version}")
        _safe_print()

    t0 = time.perf_counter()

    def _progress(msg: str) -> None:
        if args.verbose:
            _safe_print(f"  [{time.perf_counter() - t0:.1f}s] {msg}")

    try:
        stats = convert(
            input_path=args.input,
            output_path=output,
            config=config,
            dxf_version=args.dxf_version,
            progress_callback=_progress if args.verbose else None,
            resumable=bool(args.resume),
        )
    except KeyboardInterrupt:
        print(
            "Conversion interrupted. Re-run the same command with --resume to "
            "continue any certified pages.",
            file=sys.stderr,
        )
        return 130
    except ConversionCancelled as exc:
        _safe_print(str(exc), file=sys.stderr)
        return 130
    except PdfOpenError as exc:
        from pdfcadcore.cli_error_copy import cli_error

        _safe_print(cli_error("not_a_pdf", message=str(exc)), file=sys.stderr)
        return 2

    elapsed = time.perf_counter() - t0

    # Summary. _safe_print throughout: the conversion has succeeded and the
    # DXF is on disk; a diagnostic that cannot be encoded must degrade, never
    # decide the exit code (it used to -- exit 1 from the Output line alone).
    _safe_print()
    _safe_print("Conversion complete.")
    _safe_print(f"  Pages converted: {stats.get('pages', '?')}")
    _safe_print(f"  Entities:        {stats.get('entities', '?')}")
    _safe_print(f"  Text items:      {stats.get('text_items', 0)}")
    _safe_print(f"  Output:          {output}")
    _safe_print(f"  Time:            {elapsed:.2f}s")
    report_path = stats.get("import_report_path")
    if report_path:
        _safe_print(f"  import_report:   {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

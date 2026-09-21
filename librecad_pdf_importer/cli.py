"""CLI for PDF -> DXF conversion tailored to LibreCAD."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from conversion_control import ImportStopped

from .exporters.dxf_exporter import (
    DxfExportOptions,
    degraded_text_item_lines,
    export_to_dxf,
    searchable_text_warning_line,
    summarize_text_delivery,
)
from .importer import (
    apply_uniform_scale,
    failure_import_report_path,
    run_import,
    terminal_failure_record,
    write_import_report,
)
from .launchers.librecad_launcher import find_librecad_executable, launch_librecad


def _default_import_report_path(output_path: Path) -> Path:
    return output_path.with_suffix("").with_name(f"{output_path.stem}_import_report.json")


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for LC CLI (BCS-ARCH-001 Rule 5 sweep).

    User-facing flags only: --mode, --text-mode, --import-text/--no-import-text,
    --searchable-text/--no-searchable-text, --pages, --scale, --dxf-version,
    --gui, --verbose, plus output/IO controls.
    Quality-tier flags (--hatch-mode, --arc-mode, --cleanup-level,
    --lineweight-mode, --raster-dpi, --strict-text-fidelity, --no-arcs,
    --no-raster-fallback, --grouping-mode) have been removed — their
    consolidated defaults apply universally. Distinct future capabilities are
    still allowed when they preserve maximum fidelity and are production-tested.
    """
    parser = argparse.ArgumentParser(description="Convert PDF vectors into LibreCAD-ready DXF.")
    parser.add_argument("pdf", help="Input PDF path")
    parser.add_argument("--out", help="Output DXF path (default: <pdf>.dxf)")
    parser.add_argument("--mode", default="auto",
                        choices=["auto", "vector", "raster", "hybrid"],
                        help="Import mode (BCS-ARCH-001)")
    parser.add_argument("--pages", default=None, help="Page spec: 1,3-5,all")
    parser.add_argument("--scale", type=float, default=None,
                        help="Manual scale multiplier")
    parser.add_argument("--text-mode", default=None,
                        choices=["text", "labels", "3d_text", "glyphs", "geometry", "raster"],
                        help="Text handling (orthogonal to --mode)")
    parser.add_argument("--import-text",
                        action=argparse.BooleanOptionalAction,
                        default=None,
                        help="Import text from the PDF (--no-import-text to skip)")
    parser.add_argument("--searchable-text",
                        action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Write each outlined/rastered string as hidden TEXT on the "
                             "frozen layer P###_TEXT_SEARCH so the DXF is searchable "
                             "(--no-searchable-text to skip)")
    parser.add_argument("--dxf-version", default="R2018",
                        choices=["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"],
                        help="Target DXF version")
    parser.add_argument("--page-arrangement", default="spread",
                        choices=["spread", "compact", "touch", "overlay"],
                        help="Multi-page placement mode (default: spread = 20%% gap)")
    parser.add_argument("--page-gap-ratio", type=float, default=0.02,
                        help="Gap ratio used when --page-arrangement=compact")
    parser.add_argument("--reference-detected-mm", type=float, default=None,
                        help="Measured length in imported geometry (mm)")
    parser.add_argument("--reference-real-mm", type=float, default=None,
                        help="Real-world reference length (mm)")
    parser.add_argument("--no-images", action="store_true", help="Skip image export")
    parser.add_argument("--json", help="Write JSON report")
    parser.add_argument("--launch", action="store_true", help="Launch LibreCAD after export")
    parser.add_argument("--librecad-exe", help="Explicit LibreCAD executable path")
    parser.add_argument("--verbose", action="store_true",
                        help="Print verbose progress")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Print pre-import guidance (text modes, scale trust) and exit",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Verify all bundled runtime dependencies and exit",
    )
    return parser


def main() -> int:
    try:
        return _main()
    except Exception as exc:  # noqa: BLE001
        # A console exe answers a failed import with one readable line, not a
        # Python traceback; --verbose keeps the traceback for a bug report.
        from pdfcadcore.cli_error_copy import cli_error

        if "--verbose" in sys.argv[1:]:
            import traceback

            traceback.print_exc()
        message = f"{type(exc).__name__}: {exc}"
        failure_report = str(getattr(exc, "failure_report_path", "") or "")
        report_error = str(getattr(exc, "failure_report_error", "") or "")
        if failure_report:  # a failed export leaves one, whatever stopped it
            message += f" (complete failure report: {failure_report})"
        elif report_error:  # ... unless the report itself could not be written
            message += f" (the failure report could not be written: {report_error})"
        _print_stderr(cli_error("import_failed", message=message))
        return 3


def _print_stderr(line: str) -> None:
    try:
        print(line, file=sys.stderr)
    except UnicodeEncodeError:  # a cp1252 console must not turn the message into a traceback
        print(line.encode("ascii", "backslashreplace").decode("ascii"), file=sys.stderr)


def _main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        from .runtime_self_test import run_runtime_self_test

        return run_runtime_self_test()

    args = build_parser().parse_args()

    if args.preflight:
        from pdfcadcore.preflight_copy import preflight_paragraph

        print(preflight_paragraph("librecad"))
        return 0

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        from pdfcadcore.cli_error_copy import cli_error

        print(cli_error("file_not_found", path=str(pdf_path)), file=sys.stderr)
        return 1

    from pdf_open_guard import precheck_pdf, PdfOpenError

    try:
        precheck_pdf(str(pdf_path))
    except PdfOpenError as exc:
        from pdfcadcore.cli_error_copy import cli_error

        print(cli_error("not_a_pdf", message=str(exc)), file=sys.stderr)
        return 1

    out_path = Path(args.out).expanduser().resolve() if args.out else pdf_path.with_suffix(".dxf")

    overrides = {}
    if args.pages is not None:
        overrides["pages"] = args.pages
    if args.scale is not None:
        overrides["user_scale"] = args.scale
    if args.text_mode is not None:
        overrides["text_mode"] = args.text_mode
        overrides["import_text"] = True
    if args.import_text is not None:
        overrides["import_text"] = bool(args.import_text)
    if args.no_images:
        overrides["ignore_images"] = True

    t0 = time.perf_counter()
    run = run_import(str(pdf_path), mode=args.mode, overrides=overrides)
    run_import_ms = (time.perf_counter() - t0) * 1000.0

    if args.reference_detected_mm and args.reference_real_mm:
        if args.reference_detected_mm <= 0:
            from pdfcadcore.cli_error_copy import cli_error

            print(cli_error("reference_detected_invalid"), file=sys.stderr)
            run.close()
            return 1
        scale_factor = args.reference_real_mm / args.reference_detected_mm
        apply_uniform_scale(run.extraction, scale_factor)

    resolved_librecad_executable = find_librecad_executable(args.librecad_exe)
    librecad_contract_executable = resolved_librecad_executable or (
        args.librecad_exe if args.librecad_exe is not None else ""
    )
    t_export = time.perf_counter()
    try:
        export = export_to_dxf(
            run.extraction,
            str(out_path),
            DxfExportOptions(
                # Text export reflects effective config — driven by --import-text
                # (already applied to run.config.import_text via overrides).
                include_text=bool(run.config.import_text)
                and (run.config.text_mode != "none"),
                text_mode=str(run.config.text_mode or "text"),
                include_images=not args.no_images,
                group_by_page=True,
                prefer_source_layers=True,
                attach_metadata=True,
                dxf_version=args.dxf_version,
                map_dashes=bool(run.config.map_dashes),
                librecad_executable=librecad_contract_executable,
                page_arrangement=args.page_arrangement,
                page_gap_ratio=max(0.0, float(args.page_gap_ratio or 0.0)),
                provenance_opts=run.config,
                searchable_text=bool(args.searchable_text),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - every failed export leaves a report
        # One unverifiable text item no longer lands here (it degrades and the
        # sheet exports); what does is a deliberate stop (ImportStopped: duplicate
        # source IDs or handles, post-write verification still failing after its
        # one retry) or an unexpected failure, which main() answers in one line.
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        try:
            failure_path = failure_import_report_path(str(out_path), run)
            write_import_report(
                run,
                failure_path,
                elapsed_ms=elapsed_ms,
                performance_phases={
                    "run_import_ms": run_import_ms,
                    "export_dxf_ms": (time.perf_counter() - t_export) * 1000.0,
                    "total_ms": elapsed_ms,
                },
                terminal_failure=terminal_failure_record(exc),
            )
        except Exception as report_exc:  # noqa: BLE001 - the ORIGINAL failure survives
            # Read-only folder, disk full: exactly when an export fails. Say so, and
            # keep the real cause and its exit code (2 deliberate, 3 otherwise).
            report_error = f"{type(report_exc).__name__}: {report_exc}"
            exc.failure_report_error = report_error
            report_note = f"The failure report could not be written: {report_error}"
        else:
            exc.failure_report_path = failure_path
            report_note = f"Complete failure report: {failure_path}"
        run.close()
        if not isinstance(exc, ImportStopped):
            raise
        _print_stderr(f"Import stopped: {exc}\n{report_note}")
        return 2
    export_dxf_ms = (time.perf_counter() - t_export) * 1000.0
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    import_report_path = _default_import_report_path(out_path)
    write_import_report(
        run,
        str(import_report_path),
        elapsed_ms=elapsed_ms,
        performance_phases={
            "run_import_ms": run_import_ms,
            "export_dxf_ms": export_dxf_ms,
            "total_ms": elapsed_ms,
        },
    )

    summary = {
        "import": run.extraction.summary(),
        "export": {
            "output_path": export.output_path,
            "entity_count": export.entity_count,
            "layer_count": export.layer_count,
            "image_count": export.image_count,
            "import_report_path": str(import_report_path),
            "text_delivery": summarize_text_delivery(
                str(run.config.text_mode or "none")
                if run.config.import_text
                else "none",
                export.text_deliveries,
                report_path=str(import_report_path),
            ),
            "searchable_text_companions": export.searchable_text_companions,
        },
    }

    summary_json = json.dumps(summary, indent=2, allow_nan=False)
    print(summary_json)
    clip_fill_warning = run.extraction.clip_fill_warning()
    if clip_fill_warning:
        _print_stderr(clip_fill_warning)
    # Recovered spans are stated and unproven ones warned about, in one line.
    glyph_code_warning = run.extraction.glyph_code_warning()
    if glyph_code_warning:
        _print_stderr(glyph_code_warning)
    # The DXF was written (exit code 0), but a degraded text item must be loud.
    text_delivery = summary["export"]["text_delivery"]
    for line in degraded_text_item_lines(
        text_delivery["degraded_items"], text_delivery["degraded_item_count"]
    ):
        _print_stderr(line)
    search_text_warning = searchable_text_warning_line(export.searchable_text_companions)
    if search_text_warning:
        _print_stderr(search_text_warning)

    if args.json:
        report = Path(args.json).expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(summary_json, encoding="utf-8")
        print(f"Wrote report: {report}")

    if args.launch:
        ok, message = launch_librecad(
            export.output_path,
            executable=librecad_contract_executable,
        )
        print(message)

    run.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

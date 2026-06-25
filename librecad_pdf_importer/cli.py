"""CLI for PDF -> DXF conversion tailored to LibreCAD."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from .importer import apply_uniform_scale, run_import, write_import_report
from .launchers.librecad_launcher import launch_librecad


def _default_import_report_path(output_path: Path) -> Path:
    return output_path.with_suffix("").with_name(f"{output_path.stem}_import_report.json")


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for LC CLI (BCS-ARCH-001 Rule 5 sweep).

    User-facing flags only: --mode, --text-mode, --import-text/--no-import-text,
    --pages, --scale, --dxf-version, --gui, --verbose, plus output/IO controls.
    Quality-tier flags (--hatch-mode, --arc-mode, --cleanup-level,
    --lineweight-mode, --raster-dpi, --strict-text-fidelity, --no-arcs,
    --no-raster-fallback, --grouping-mode) have been removed — their
    consolidated defaults apply universally.
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
                        choices=["labels", "3d_text", "glyphs", "geometry"],
                        help="Text handling (orthogonal to --mode)")
    parser.add_argument("--import-text",
                        action=argparse.BooleanOptionalAction,
                        default=None,
                        help="Import text from the PDF (--no-import-text to skip)")
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
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.preflight:
        from pdfcadcore.preflight_copy import preflight_paragraph

        print(preflight_paragraph("librecad"))
        return 0

    pdf_path = Path(args.pdf).expanduser().resolve()
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
            raise SystemExit("--reference-detected-mm must be > 0")
        scale_factor = args.reference_real_mm / args.reference_detected_mm
        apply_uniform_scale(run.extraction, scale_factor)

    t_export = time.perf_counter()
    export = export_to_dxf(
        run.extraction,
        str(out_path),
        DxfExportOptions(
            # Text export reflects effective config — driven by --import-text
            # (already applied to run.config.import_text via overrides).
            include_text=bool(run.config.import_text) and (run.config.text_mode != "none"),
            text_mode=str(run.config.text_mode or "labels"),
            include_images=not args.no_images,
            group_by_page=True,
            prefer_source_layers=True,
            attach_metadata=True,
            dxf_version=args.dxf_version,
            map_dashes=bool(run.config.map_dashes),
            page_arrangement=args.page_arrangement,
            page_gap_ratio=max(0.0, float(args.page_gap_ratio or 0.0)),
        ),
    )
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
        },
    }

    print(json.dumps(summary, indent=2))

    if args.json:
        report = Path(args.json).expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote report: {report}")

    if args.launch:
        ok, message = launch_librecad(export.output_path, executable=args.librecad_exe)
        print(message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

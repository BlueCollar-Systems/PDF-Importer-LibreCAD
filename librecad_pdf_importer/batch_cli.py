"""Batch CLI for PDF -> DXF conversion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from .importer import run_import


def _collect_pdfs(root: Path, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(p for p in root.rglob("*.pdf") if p.is_file())
    return sorted(p for p in root.glob("*.pdf") if p.is_file())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Batch-convert PDF vectors to LibreCAD-ready DXF.")
    p.add_argument("input_dir", help="Directory containing PDF files")
    p.add_argument("output_dir", help="Directory to write DXF files")
    p.add_argument("--mode", default="auto",
                   choices=["auto", "vector", "raster", "hybrid"],
                   help="Import mode (BCS-ARCH-001)")
    p.add_argument("--pages", default="all", help="Page spec (default: all)")
    p.add_argument("--dxf-version", default="R2018",
                   choices=["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"],
                   help="Target DXF version")
    p.add_argument("--page-arrangement", default="spread",
                   choices=["spread", "compact", "touch", "overlay"],
                   help="Multi-page placement mode (default: spread = 20%% gap)")
    p.add_argument("--page-gap-ratio", type=float, default=0.02,
                   help="Gap ratio used when --page-arrangement=compact")
    p.add_argument("--recursive", action="store_true", help="Include subfolders")
    p.add_argument("--json", default=None, help="Write aggregate JSON report")
    return p


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.input_dir).expanduser().resolve()
    out_root = Path(args.output_dir).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Input directory not found: {root}")
    out_root.mkdir(parents=True, exist_ok=True)

    pdfs = _collect_pdfs(root, recursive=args.recursive)
    if not pdfs:
        raise SystemExit(f"No PDF files found under: {root}")

    aggregate = {"root": str(root), "output_dir": str(out_root), "total": len(pdfs), "passed": 0, "failed": 0, "results": []}

    for pdf in pdfs:
        rel = pdf.relative_to(root)
        out_dxf = out_root / rel.with_suffix(".dxf")
        out_dxf.parent.mkdir(parents=True, exist_ok=True)
        overrides = {"pages": args.pages}
        run = None
        try:
            run = run_import(str(pdf), mode=args.mode, overrides=overrides)
            export = export_to_dxf(
                run.extraction,
                str(out_dxf),
                DxfExportOptions(
                    dxf_version=args.dxf_version,
                    include_text=run.config.text_mode != "none",
                    include_images=True,
                    map_dashes=bool(run.config.map_dashes),
                    page_arrangement=args.page_arrangement,
                    page_gap_ratio=max(0.0, float(args.page_gap_ratio or 0.0)),
                ),
            )
            aggregate["passed"] += 1
            aggregate["results"].append({
                "pdf": str(pdf),
                "dxf": export.output_path,
                "status": "PASS",
                "entities": export.entity_count,
                "images": export.image_count,
            })
        except Exception as exc:  # noqa: BLE001
            aggregate["failed"] += 1
            aggregate["results"].append({"pdf": str(pdf), "status": "FAIL", "error": str(exc)})
        finally:
            if run is not None:
                run.close()

    print(
        json.dumps(
            {k: v for k, v in aggregate.items() if k != "results"},
            indent=2,
            allow_nan=False,
        )
    )

    if args.json:
        out = Path(args.json).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(aggregate, indent=2, allow_nan=False), encoding="utf-8"
        )
        print(f"Wrote report: {out}")

    return 0 if aggregate["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke-test harness for LibreCAD PDF importer."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .exporters.dxf_exporter import DxfExportOptions, export_to_dxf
from .importer import run_import


def _collect_inputs(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".pdf":
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*.pdf") if p.is_file())
    return []


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run a smoke QA pass for the LibreCAD PDF importer.")
    p.add_argument("input_path", help="PDF file or directory of PDFs")
    p.add_argument("--mode", default="auto",
                   choices=["auto", "vector", "raster", "hybrid"],
                   help="Import mode (BCS-ARCH-001)")
    p.add_argument("--pages", default="1", help="Page spec")
    p.add_argument("--min-entities", type=int, default=1, help="Minimum entity count to pass")
    p.add_argument("--json", default=None, help="Write JSON report")
    return p


def main() -> int:
    args = build_parser().parse_args()
    target = Path(args.input_path).expanduser().resolve()
    pdfs = _collect_inputs(target)
    if not pdfs:
        raise SystemExit(f"No PDF inputs found at: {target}")

    report = {"target": str(target), "total": len(pdfs), "passed": 0, "failed": 0, "results": []}

    with tempfile.TemporaryDirectory(prefix="lc_smoke_") as td:
        td_path = Path(td)
        for pdf in pdfs:
            run = None
            try:
                run = run_import(str(pdf), mode=args.mode, overrides={"pages": args.pages})
                out_dxf = td_path / f"{pdf.stem}.dxf"
                export = export_to_dxf(run.extraction, str(out_dxf), DxfExportOptions())
                ok = export.entity_count >= args.min_entities
                if ok:
                    report["passed"] += 1
                else:
                    report["failed"] += 1
                report["results"].append({
                    "pdf": str(pdf),
                    "status": "PASS" if ok else "FAIL",
                    "entities": export.entity_count,
                    "images": export.image_count,
                })
            except Exception as exc:  # noqa: BLE001
                report["failed"] += 1
                report["results"].append({"pdf": str(pdf), "status": "FAIL", "error": str(exc)})
            finally:
                if run is not None:
                    run.close()

    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "results"},
            indent=2,
            allow_nan=False,
        )
    )

    if args.json:
        out = Path(args.json).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
        print(f"Wrote report: {out}")

    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

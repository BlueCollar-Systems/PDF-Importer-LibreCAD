"""End-to-end contracts for the directory batch CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import ezdxf

try:
    import pymupdf as fitz
except ImportError:
    import fitz


ROOT = Path(__file__).resolve().parents[1]


def _write_text_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.draw_line((20, 20), (120, 20), color=(0, 0, 0), width=1.0)
    page.insert_text((30, 60), "BATCH RASTER", fontsize=10)
    document.save(path)
    document.close()


def test_batch_cli_delivers_requested_item_raster_and_reports_request(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    report_path = tmp_path / "batch.json"
    input_dir.mkdir()
    pdf_path = input_dir / "sample.pdf"
    _write_text_pdf(pdf_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "librecad_pdf_importer.batch_cli",
            str(input_dir),
            str(output_dir),
            "--mode",
            "vector",
            "--text-mode",
            "raster",
            "--json",
            str(report_path),
        ],
        cwd=os.fspath(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["text_mode"] == "raster"
    assert report["results"][0]["text_mode"] == "raster"
    drawing = ezdxf.readfile(output_dir / "sample.dxf")
    entity_types = [entity.dxftype() for entity in drawing.modelspace()]
    assert entity_types.count("IMAGE") == 1
    assert "TEXT" not in entity_types

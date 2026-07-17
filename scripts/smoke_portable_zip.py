#!/usr/bin/env python3
"""Smoke-test every shipped LibreCAD Windows portable entry point."""
from __future__ import annotations

import argparse
import glob
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


REQUIRED_EXES = (
    "lcpdf-gui.exe",
    "pdf2dxf.exe",
    "lcpdf-import.exe",
    "lcpdf-batch.exe",
)
REQUIRED_NOTICES = (
    "LICENSE",
    "THIRD_PARTY_LICENSES.md",
    "licenses/FontTools/LICENSE",
    "licenses/FontTools/LICENSE.external",
    "licenses/PYTHON_DISTRIBUTIONS.md",
    "licenses/python-distributions.json",
)
SOURCE_REQUIRED_MEMBERS = (
    "pdf2dxf.py",
    "dxf_builder.py",
    "dxf_text_builder.py",
    "dxf_import_engine.py",
    "gui.py",
    "preflight_check.py",
    "requirements.txt",
    "runtime_requirements.py",
    "librecad_pdf_importer/runtime_self_test.py",
    "pdfcadcore/embedded_fonts.py",
    "tools/fetch_runtime_wheels.ps1",
    "third_party/fonttools/LICENSE",
    "third_party/fonttools/LICENSE.external",
    "scripts/smoke_portable_zip.py",
)
SELF_TEST_TIMEOUT_SECONDS = 120
CONVERSION_TIMEOUT_SECONDS = 180


def _run_process(
    command: list[str],
    *,
    timeout: int,
    label: str,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"{label} timed out after {timeout}s") from exc


def _run_self_test(executable: Path) -> subprocess.CompletedProcess:
    return _run_process(
        [str(executable), "--self-test"],
        timeout=SELF_TEST_TIMEOUT_SECONDS,
        label=f"{executable.name} --self-test",
    )


def _resolve_zip(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise SystemExit(f"No portable ZIP matched {pattern!r}")
    return Path(matches[-1]).resolve()


def _validate_source_zip(source_zip: Path) -> None:
    with zipfile.ZipFile(source_zip, "r") as archive:
        names = {name.replace("\\", "/").strip("/") for name in archive.namelist()}
    missing = [name for name in SOURCE_REQUIRED_MEMBERS if name not in names]
    if missing:
        raise SystemExit(
            "Source ZIP is missing required files: " + ", ".join(missing)
        )
    forbidden = sorted(
        name
        for name in names
        if name == "lib"
        or name.startswith("lib/")
        or name.startswith("lib.stage.")
        or name.startswith("lib.backup.")
    )
    if forbidden:
        raise SystemExit(
            "Source ZIP must not contain vendored runtime files: "
            + ", ".join(forbidden[:10])
        )


def _write_tiny_pdf(path: Path) -> None:
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore[no-redef]

    document = pymupdf.open()
    try:
        page = document.new_page(width=240, height=120)
        page.insert_text((24, 60), "BCS PORTABLE GLYPH", fontsize=14)
        document.save(path)
    finally:
        document.close()


def _validate_glyph_delivery(report_path: Path) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        delivery = report["extra"]["text_representation_delivery"]
        items = delivery["items"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Portable conversion report is invalid: {report_path}: {exc}") from exc

    exact_items = bool(items) and all(
        item.get("requested_representation") == "glyphs"
        and item.get("final_representation") == "glyphs"
        and item.get("verified") is True
        and item.get("fallback_used") is False
        for item in items
    )
    if (
        delivery.get("requested_representation") != "glyphs"
        or delivery.get("verified") is not True
        or not exact_items
    ):
        raise SystemExit(
            "Portable conversion did not deliver requested Glyphs as verified Glyphs"
        )


def _smoke_extracted_portable(root: Path) -> None:
    for executable_name in REQUIRED_EXES:
        executable = root / executable_name
        proc = _run_self_test(executable)
        combined = (proc.stdout + proc.stderr).lower()
        if proc.returncode != 0 or "self-test ok" not in combined:
            raise SystemExit(
                f"{executable_name} --self-test failed: "
                + (proc.stderr.strip() or proc.stdout.strip())
            )

    pdf_path = root / "portable_smoke.pdf"
    dxf_path = root / "portable_smoke.dxf"
    report_path = root / "portable_smoke_import_report.json"
    _write_tiny_pdf(pdf_path)
    proc = _run_process(
        [
            str(root / "pdf2dxf.exe"),
            str(pdf_path),
            str(dxf_path),
            "--mode",
            "vector",
            "--text-mode",
            "glyphs",
        ],
        timeout=CONVERSION_TIMEOUT_SECONDS,
        label="pdf2dxf.exe Glyph conversion",
    )
    if proc.returncode != 0:
        raise SystemExit(
            "pdf2dxf.exe real Glyph conversion failed: "
            + (proc.stderr.strip() or proc.stdout.strip())
        )
    if not dxf_path.is_file() or dxf_path.stat().st_size == 0:
        raise SystemExit("pdf2dxf.exe reported success without a non-empty DXF")
    if not report_path.is_file():
        raise SystemExit("pdf2dxf.exe reported success without an import report")
    _validate_glyph_delivery(report_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", help="Portable ZIP path or glob pattern")
    parser.add_argument(
        "--source-zip",
        help="Source ZIP path or glob pattern to validate in the same release gate",
    )
    args = parser.parse_args()

    zip_path = _resolve_zip(args.zip_path)
    if args.source_zip:
        source_zip = _resolve_zip(args.source_zip)
        _validate_source_zip(source_zip)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = {name.replace("\\", "/").strip("/") for name in zf.namelist()}
        missing = [name for name in (*REQUIRED_EXES, *REQUIRED_NOTICES) if name not in names]
        if missing:
            raise SystemExit(
                "Portable ZIP is missing required files: " + ", ".join(missing)
            )

    with tempfile.TemporaryDirectory(prefix="lc_portable_") as tmp:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        _smoke_extracted_portable(Path(tmp))

    print(f"Portable ZIP smoke passed: {zip_path.name}")
    if args.source_zip:
        print(f"Source ZIP smoke passed: {source_zip.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

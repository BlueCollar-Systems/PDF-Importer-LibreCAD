#!/usr/bin/env python3
"""Smoke-test every shipped LibreCAD Windows portable entry point."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
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
    "deterministic_zip.py",
    "gui.py",
    "preflight_check.py",
    "release_build_contract.py",
    "requirements-release-win-py312.lock",
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
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
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
    _validate_representation_delivery(
        report_path,
        requested="glyphs",
        final="glyphs",
        fallback_used=False,
    )


def _validate_representation_delivery(
    report_path: Path,
    *,
    requested: str,
    final: str,
    fallback_used: bool,
    dxf_path: Path | None = None,
    expected_executable: Path | None = None,
    expected_lff: Path | None = None,
) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        delivery = report["extra"]["text_representation_delivery"]
        items = delivery["items"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Portable conversion report is invalid: {report_path}: {exc}") from exc

    exact_items = bool(items) and all(
        item.get("requested_representation") == requested
        and item.get("final_representation") == final
        and item.get("verified") is True
        and item.get("fallback_used") is fallback_used
        for item in items
    )
    if (
        delivery.get("requested_representation") != requested
        or delivery.get("verified") is not True
        or not exact_items
    ):
        if requested == "glyphs" and final == "glyphs":
            raise SystemExit(
                "Portable conversion did not deliver requested Glyphs as verified Glyphs"
            )
        raise SystemExit(
            "Portable conversion did not deliver "
            f"requested {requested!r} as verified {final!r}"
        )
    if final == "text":
        if dxf_path is None or expected_executable is None or expected_lff is None:
            raise SystemExit(
                "Portable native-text validation requires the DXF and exact "
                "LibreCAD executable/LFF binding"
            )
        _validate_native_text_delivery(
            items,
            dxf_path=Path(dxf_path),
            expected_executable=Path(expected_executable),
            expected_lff=Path(expected_lff),
        )


def _validate_native_text_delivery(
    items: list[object],
    *,
    dxf_path: Path,
    expected_executable: Path,
    expected_lff: Path,
) -> None:
    """Reopen the DXF and independently verify every native LibreCAD delivery."""

    try:
        import ezdxf
    except ImportError as exc:
        raise SystemExit(
            "ezdxf is required to reopen the portable native-text smoke output"
        ) from exc
    try:
        drawing = ezdxf.readfile(dxf_path)
    except Exception as exc:
        raise SystemExit(f"Portable native-text DXF cannot be reopened: {exc}") from exc

    executable = expected_executable.resolve()
    lff = expected_lff.resolve()
    if not executable.is_file() or not lff.is_file():
        raise SystemExit("Portable native-text LibreCAD executable/LFF binding is missing")
    lff_bytes = lff.read_bytes()
    lff_sha256 = hashlib.sha256(lff_bytes).hexdigest()
    modelspace = drawing.modelspace()
    modelspace_handles = {
        str(entity.dxf.handle): entity
        for entity in modelspace
        if str(entity.dxf.handle or "")
    }
    seen_handles: set[str] = set()

    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise SystemExit(f"Portable native-text delivery item {index} is invalid")
        handles = raw_item.get("entity_handles")
        attempts = raw_item.get("attempts")
        if (
            not isinstance(handles, list)
            or len(handles) != 1
            or not all(isinstance(handle, str) and handle for handle in handles)
            or not isinstance(attempts, list)
        ):
            raise SystemExit(
                f"Portable native-text delivery item {index} lacks one exact entity handle"
            )
        verified_attempts = [
            attempt
            for attempt in attempts
            if isinstance(attempt, dict) and attempt.get("outcome") == "verified"
        ]
        if len(verified_attempts) != 1:
            raise SystemExit(
                f"Portable native-text delivery item {index} must have exactly one "
                "verified attempt"
            )
        attempt = verified_attempts[0]
        if (
            attempt.get("delivery_verified") is not True
            or attempt.get("visual_verified") is not False
            or attempt.get("entity_handles") != handles
        ):
            raise SystemExit(
                f"Portable native-text delivery item {index} attempt flags/handles changed"
            )
        evidence = attempt.get("evidence")
        if not isinstance(evidence, dict):
            raise SystemExit(
                f"Portable native-text delivery item {index} evidence is invalid"
            )
        required_true = (
            "librecad_parent_installation_verified",
            "librecad_lff_executable_binding_verified",
            "librecad_lff_asset_verified",
            "librecad_lff_coverage_verified",
            "librecad_lff_required_glyphs_drawable_verified",
            "parent_native_font_asset_coverage_verified",
            "parent_native_text_reopen_verified",
            "parent_native_text_reopen_asset_coverage_verified",
            "serialized_cap_height_invariant_verified",
            "delivery_evidence_verified",
        )
        if evidence.get("target_app") != "librecad" or any(
            evidence.get(key) is not True for key in required_true
        ):
            raise SystemExit(
                f"Portable native-text delivery item {index} lacks verified "
                "LibreCAD reopen/LFF evidence"
            )
        if evidence.get("parent_native_text_reopen_renderability_verified") is not False:
            raise SystemExit(
                f"Portable native-text delivery item {index} misstates parent "
                "renderability evidence"
            )
        if (
            evidence.get("librecad_lff_size_bytes") != len(lff_bytes)
            or evidence.get("librecad_lff_sha256") != lff_sha256
            or evidence.get("librecad_lff_missing_codepoints") != []
            or evidence.get("librecad_lff_invalid_codepoints") != []
        ):
            raise SystemExit(
                f"Portable native-text delivery item {index} LFF hash/coverage changed"
            )
        local_diagnostics = evidence.get("local_only_diagnostics")
        if not isinstance(local_diagnostics, dict) or (
            local_diagnostics.get("classification") != "local_sensitive_paths"
            or local_diagnostics.get("shareable") is not False
            or Path(str(local_diagnostics.get("librecad_executable_path") or "")).resolve()
            != executable
            or Path(str(local_diagnostics.get("librecad_lff_path") or "")).resolve()
            != lff
        ):
            raise SystemExit(
                f"Portable native-text delivery item {index} local executable/LFF "
                "binding changed"
            )

        handle = handles[0]
        entity = modelspace_handles.get(handle)
        if (
            handle in seen_handles
            or entity is None
            or not getattr(entity, "is_alive", True)
            or entity.dxftype() != "TEXT"
        ):
            raise SystemExit(
                f"Portable native-text delivery item {index} has a missing or dead "
                "DXF TEXT handle"
            )
        seen_handles.add(handle)
        delivered_content = evidence.get("delivered_content")
        if not isinstance(delivered_content, str) or entity.dxf.text != delivered_content:
            raise SystemExit(
                f"Portable native-text delivery item {index} DXF content changed"
            )
        style_name = str(entity.dxf.style or "")
        try:
            style_font = str(drawing.styles.get(style_name).dxf.font or "")
        except Exception as exc:
            raise SystemExit(
                f"Portable native-text delivery item {index} style is missing"
            ) from exc
        if style_name.lower() != "unicode" or style_font.lower() != "unicode":
            raise SystemExit(
                f"Portable native-text delivery item {index} lost its unicode LFF style"
            )


def _write_synthetic_librecad_lff(path: Path) -> None:
    """Create a deterministic CI-only printable-ASCII LibreCAD font."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Format:            LibreCAD Font 1",
        "# Name:              Portable Release Smoke",
        "# Encoding:          UTF-8",
        "",
    ]
    for codepoint in range(33, 127):
        lines.extend((f"[{codepoint:04X}]", "0,0;1,1", ""))
    path.write_text("\n".join(lines), encoding="utf-8")


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
    _write_tiny_pdf(pdf_path)
    synthetic_executable = root / "LibreCAD.exe"
    synthetic_executable.write_bytes(b"MZ synthetic release-smoke marker\n")
    synthetic_lff = root / "resources" / "fonts" / "unicode.lff"
    _write_synthetic_librecad_lff(synthetic_lff)
    native_environment = dict(os.environ)
    native_environment["BCS_LIBRECAD_EXECUTABLE"] = str(synthetic_executable)
    native_environment["BCS_LIBRECAD_UNICODE_LFF"] = str(synthetic_lff)

    smoke_modes = (
        ("glyphs", "glyphs", False, None),
        ("text", "text", False, native_environment),
        ("labels", "text", True, native_environment),
    )
    for requested, final, fallback_used, environment in smoke_modes:
        dxf_path = root / f"portable_smoke_{requested}.dxf"
        report_path = root / f"portable_smoke_{requested}_import_report.json"
        proc = _run_process(
            [
                str(root / "pdf2dxf.exe"),
                str(pdf_path),
                str(dxf_path),
                "--mode",
                "vector",
                "--text-mode",
                requested,
            ],
            timeout=CONVERSION_TIMEOUT_SECONDS,
            label=f"pdf2dxf.exe {requested} conversion",
            environment=environment,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"pdf2dxf.exe real {requested} conversion failed: "
                + (proc.stderr.strip() or proc.stdout.strip())
            )
        if not dxf_path.is_file() or dxf_path.stat().st_size == 0:
            raise SystemExit("pdf2dxf.exe reported success without a non-empty DXF")
        if not report_path.is_file():
            raise SystemExit("pdf2dxf.exe reported success without an import report")
        _validate_representation_delivery(
            report_path,
            requested=requested,
            final=final,
            fallback_used=fallback_used,
            dxf_path=dxf_path if final == "text" else None,
            expected_executable=synthetic_executable if final == "text" else None,
            expected_lff=synthetic_lff if final == "text" else None,
        )


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

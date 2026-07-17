"""Locks against CI, packaging, and dependency-management dead ends."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

import build_standalone
import build_windows_portable
from scripts import smoke_portable_zip


ROOT = Path(__file__).resolve().parents[1]


def test_ci_clones_optional_corpus_before_tests_and_runs_minimum_dependencies() -> None:
    workflow = (ROOT / ".github" / "workflows" / "lc-pdfimporter-ci.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.index("Optional corpus clone") < workflow.index("Run unit tests")
    assert "minimum-dependencies:" in workflow
    assert '"PyMuPDF==1.24.0"' in workflow
    assert '"ezdxf==1.0.0"' in workflow
    assert '"fonttools==4.50.0"' in workflow
    assert "pip install --no-deps -e ." in workflow
    assert workflow.count("python -m pytest tests/ -v") >= 2


def test_runtime_requirements_have_one_source_of_truth() -> None:
    from runtime_requirements import load_runtime_requirements

    expected = tuple(
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert load_runtime_requirements(ROOT) == expected
    assert build_standalone.BUILD_REQUIREMENTS == ["pyinstaller", *expected]
    assert build_windows_portable.BUILD_REQUIREMENTS == ["pyinstaller", *expected]


def test_powershell_fetcher_delegates_to_transactional_python_preflight() -> None:
    source = (ROOT / "tools" / "fetch_runtime_wheels.ps1").read_text(
        encoding="utf-8"
    )

    assert "preflight_check.py" in source
    assert "--install" in source
    assert "$LASTEXITCODE -ne 0" in source
    assert "pip install" not in source
    assert "lib.stage." not in source
    assert "fonttools>=4.50" not in source.lower()


def test_standalone_cleanup_fails_closed_when_a_stale_tree_is_locked(
    monkeypatch,
    tmp_path,
) -> None:
    stale = tmp_path / "build" / "stale"
    stale.mkdir(parents=True)

    def locked(_path):
        raise PermissionError("locked")

    monkeypatch.setattr(build_standalone.shutil, "rmtree", locked)
    with pytest.raises(RuntimeError, match="could not remove stale build path"):
        build_standalone._remove_tree_strict(stale, allowed_parent=tmp_path / "build")


def test_every_frozen_entrypoint_exposes_a_noninteractive_self_test() -> None:
    assert build_windows_portable.ENTRYPOINTS["lcpdf-gui"][:2] == (
        "standalone_app",
        "main",
    )
    cli = (ROOT / "librecad_pdf_importer" / "cli.py").read_text(encoding="utf-8")
    batch = (ROOT / "librecad_pdf_importer" / "batch_cli.py").read_text(
        encoding="utf-8"
    )
    assert 'sys.argv[1:] == ["--self-test"]' in cli
    assert 'sys.argv[1:] == ["--self-test"]' in batch


def test_portable_smoke_runs_all_entrypoints_and_real_glyph_conversion(
    monkeypatch,
    tmp_path,
) -> None:
    for name in smoke_portable_zip.REQUIRED_EXES:
        (tmp_path / name).write_bytes(b"exe")

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if "--text-mode" in command:
            output = Path(command[2])
            output.write_text("DXF", encoding="utf-8")
            report = output.with_name(f"{output.stem}_import_report.json")
            report.write_text(
                json.dumps(
                    {
                        "extra": {
                            "text_representation_delivery": {
                                "requested_representation": "glyphs",
                                "verified": True,
                                "items": [
                                    {
                                        "requested_representation": "glyphs",
                                        "final_representation": "glyphs",
                                        "verified": True,
                                        "fallback_used": False,
                                    }
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="Conversion complete", stderr="")
        return SimpleNamespace(returncode=0, stdout="Self-test OK", stderr="")

    monkeypatch.setattr(smoke_portable_zip.subprocess, "run", fake_run)
    monkeypatch.setattr(
        smoke_portable_zip,
        "_write_tiny_pdf",
        lambda path: path.write_bytes(b"%PDF-test"),
    )

    smoke_portable_zip._smoke_extracted_portable(tmp_path)

    assert [Path(call[0]).name for call in calls[:4]] == list(
        smoke_portable_zip.REQUIRED_EXES
    )
    conversion = calls[-1]
    assert Path(conversion[0]).name == "pdf2dxf.exe"
    assert conversion[-4:] == ["--mode", "vector", "--text-mode", "glyphs"]


def test_portable_smoke_rejects_report_only_or_substituted_glyph_delivery(
    tmp_path,
) -> None:
    report = tmp_path / "bad_import_report.json"
    report.write_text(
        json.dumps(
            {
                "extra": {
                    "text_representation_delivery": {
                        "requested_representation": "glyphs",
                        "verified": True,
                        "items": [
                            {
                                "requested_representation": "glyphs",
                                "final_representation": "geometry",
                                "verified": True,
                                "fallback_used": True,
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="did not deliver requested Glyphs"):
        smoke_portable_zip._validate_glyph_delivery(report)


def test_obsolete_duplicate_release_smoke_is_removed() -> None:
    assert not (ROOT / "scripts" / "smoke_release_artifacts.py").exists()


def test_canonical_release_smoke_rejects_partial_runtime_in_source_zip(tmp_path) -> None:
    source_zip = tmp_path / "source.zip"
    with zipfile.ZipFile(source_zip, "w") as archive:
        for member in smoke_portable_zip.SOURCE_REQUIRED_MEMBERS:
            archive.writestr(member, member)
        archive.writestr("lib/fontTools/__init__.py", "partial runtime")

    with pytest.raises(SystemExit, match="must not contain vendored runtime"):
        smoke_portable_zip._validate_source_zip(source_zip)


def test_release_workflow_smokes_the_built_source_and_portable_archives() -> None:
    workflow = (ROOT / ".github" / "workflows" / "auto-release.yml").read_text(
        encoding="utf-8"
    )

    smoke_line = next(
        line for line in workflow.splitlines() if "scripts/smoke_portable_zip.py" in line
    )
    assert "--source-zip" in smoke_line
    assert "LibreCAD-PDF-Importer_v*.zip" in smoke_line

"""Locks against CI, packaging, and dependency-management dead ends."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

import build_standalone
import build_windows_portable
import deterministic_zip
import release_build_contract
from scripts import smoke_portable_zip


ROOT = Path(__file__).resolve().parents[1]


def test_ci_clones_optional_corpus_before_tests_and_runs_minimum_dependencies() -> None:
    workflow = (ROOT / ".github" / "workflows" / "lc-pdfimporter-ci.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.index("Optional corpus clone") < workflow.index("Run unit tests")
    assert "minimum-dependencies:" in workflow
    assert '"PyMuPDF==1.24.0"' in workflow
    assert '"ezdxf==1.1.0"' in workflow
    assert '"fonttools==4.50.0"' in workflow
    assert '"numpy==1.23.5"' in workflow
    assert '"matplotlib==3.7.0"' in workflow
    assert "pip install --no-deps -e ." in workflow
    assert workflow.count("python -m pytest tests/ -v") >= 2


def test_declared_ezdxf_floor_matches_the_production_font_api() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    # ezdxf 1.0.x has ezdxf.tools.fonts only. The accepted runtime is exact so
    # source installs and portable builds cannot silently resolve different APIs.
    assert "ezdxf==1.4.4" in requirements
    assert '"ezdxf==1.4.4"' in project


def test_runtime_requirements_have_one_source_of_truth() -> None:
    from runtime_requirements import load_runtime_requirements

    expected = tuple(
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert load_runtime_requirements(ROOT) == expected
    assert all("==" in requirement for requirement in expected)


def test_release_build_is_hash_locked_and_ci_hash_verifies_before_publish() -> None:
    lock_path = ROOT / "requirements-release-win-py312.lock"
    lock = lock_path.read_text(encoding="utf-8")
    requirements = [
        line.strip()
        for line in lock.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(requirements) == 21
    assert all("==" in requirement and "--hash=sha256:" in requirement for requirement in requirements)
    ci_lock = (ROOT / "requirements-ci-win-py312.lock").read_text(encoding="utf-8")
    ci_requirements = [
        line.strip()
        for line in ci_lock.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(ci_requirements) == 6
    assert all(
        "==" in requirement and "--hash=sha256:" in requirement
        for requirement in ci_requirements
    )
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12"' in project

    contract = (ROOT / "release_build_contract.py").read_text(encoding="utf-8")
    assert 'EXPECTED_PYTHON_VERSION = (3, 12, 10)' in contract
    assert 'SOURCE_DATE_EPOCH = "315532800"' in contract
    assert 'PYTHONHASHSEED = "0"' in contract
    assert '"--require-hashes"' in contract
    assert '"--only-binary=:all:"' in contract
    assert "normalize_release_metadata_records" in contract

    for builder_name in ("build_windows_portable.py", "build_standalone.py"):
        builder = (ROOT / builder_name).read_text(encoding="utf-8")
        assert "create_release_venv" in builder
        assert "release_environment" in builder

    workflow = (ROOT / ".github" / "workflows" / "auto-release.yml").read_text(
        encoding="utf-8"
    )
    assert "runs-on: windows-2025" in workflow
    assert 'python-version: "3.12.10"' in workflow
    assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in workflow
    assert "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405" in workflow
    assert "actions/github-script@373c709c69115d41ff229c7e5df9f8788daa9553 # v9" in workflow
    assert (
        "pip install --require-hashes --only-binary=:all: "
        "-r requirements-ci-win-py312.lock"
    ) in workflow
    assert "pip install pytest==" not in workflow
    verify = workflow.index("scripts/verify_release_artifacts.py")
    publish = workflow.index("gh release create")
    assert verify < publish


def test_release_record_normalization_removes_only_path_sensitive_launchers(
    tmp_path,
) -> None:
    python_exe = tmp_path / "venv-with-an-arbitrary-name" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_bytes(b"")
    metadata = python_exe.parent.parent / "Lib" / "site-packages" / "demo-1.0.dist-info"
    metadata.mkdir(parents=True)
    record = metadata / "RECORD"
    record.write_text(
        "\n".join(
            [
                "demo/__init__.py,sha256=runtime,10",
                "../../Scripts/demo.exe,sha256=path-sensitive,123",
                "..\\..\\Scripts\\demo-helper.exe,sha256=path-sensitive-too,124",
                "demo/Scripts/data.txt,sha256=runtime-data,20",
                "demo-1.0.dist-info/RECORD,,",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = release_build_contract.normalize_release_metadata_records(python_exe)

    assert result == {"records_changed": 1, "launcher_rows_removed": 2}
    assert record.read_text(encoding="utf-8") == "\n".join(
        [
            "demo/__init__.py,sha256=runtime,10",
            "demo/Scripts/data.txt,sha256=runtime-data,20",
            "demo-1.0.dist-info/RECORD,,",
            "",
        ]
    )


def test_release_artifact_manifest_verifier_rejects_byte_mutation(tmp_path) -> None:
    from release_build_contract import (
        CHECKOUT_ACTION,
        CI_LOCK_FILENAME,
        EXPECTED_ARCHITECTURE,
        EXPECTED_PYTHON_VERSION,
        GITHUB_SCRIPT_ACTION,
        PYTHONHASHSEED,
        RELEASE_RUNNER,
        RELEASE_LOCK_FILENAME,
        SETUP_PYTHON_ACTION,
        SOURCE_DATE_EPOCH,
    )
    from scripts.verify_release_artifacts import (
        ArtifactVerificationError,
        REQUIRED_ARTIFACTS,
        verify_release_artifacts,
    )

    lock = tmp_path / "requirements-release-win-py312.lock"
    lock.write_text("locked\n", encoding="utf-8")
    ci_lock = tmp_path / CI_LOCK_FILENAME
    ci_lock.write_text("ci locked\n", encoding="utf-8")
    artifacts = {}
    for index, name in enumerate(REQUIRED_ARTIFACTS, start=1):
        path = tmp_path / f"{name}.bin"
        path.write_bytes(f"artifact-{index}".encode())
        artifacts[name] = {
            "path": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest = {
        "schema": "bcs.release_artifacts/1.0",
        "version": "9.9.9",
        "build_contract": {
            "python": ".".join(map(str, EXPECTED_PYTHON_VERSION)),
            "architecture": EXPECTED_ARCHITECTURE,
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "pythonhashseed": PYTHONHASHSEED,
            "requirements_lock": RELEASE_LOCK_FILENAME,
            "requirements_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "ci_lock": CI_LOCK_FILENAME,
            "ci_lock_sha256": hashlib.sha256(ci_lock.read_bytes()).hexdigest(),
            "runner": RELEASE_RUNNER,
            "checkout_action": CHECKOUT_ACTION,
            "python_setup_action": SETUP_PYTHON_ACTION,
            "github_script_action": GITHUB_SCRIPT_ACTION,
        },
        "artifacts": artifacts,
    }
    manifest_path = tmp_path / "accepted-artifacts.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verified = verify_release_artifacts(
        manifest_path=manifest_path,
        root=tmp_path,
        expected_version="9.9.9",
    )
    assert set(verified) == set(REQUIRED_ARTIFACTS)

    (tmp_path / artifacts["portable_zip"]["path"]).write_bytes(b"mutated")
    with pytest.raises(ArtifactVerificationError, match="portable_zip.*SHA-256"):
        verify_release_artifacts(
            manifest_path=manifest_path,
            root=tmp_path,
            expected_version="9.9.9",
        )


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


def test_source_and_portable_archives_are_mtime_independent(
    monkeypatch,
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pdf2dxf.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (project / "payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    package = project / "pdfcadcore"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    output = tmp_path / "source-dist"
    monkeypatch.setattr(__import__("build_release"), "_PROJECT_ROOT", project)

    source_first = __import__("build_release").build(str(output)).read_bytes()
    os.utime(project / "payload.py", (2_000_000_000, 2_000_000_000))
    os.utime(package / "__init__.py", (1_000_000_000, 1_000_000_000))
    source_second = __import__("build_release").build(str(output)).read_bytes()
    assert source_first == source_second

    clean_checkout = tmp_path / "clean-checkout"
    clean_checkout.mkdir()
    (clean_checkout / "pdf2dxf.py").write_text(
        '__version__ = "9.9.9"\n', encoding="utf-8"
    )
    (clean_checkout / "payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    clean_package = clean_checkout / "pdfcadcore"
    clean_package.mkdir()
    (clean_package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(__import__("build_release"), "_PROJECT_ROOT", clean_checkout)
    clean_source = __import__("build_release").build(
        str(tmp_path / "clean-dist")
    ).read_bytes()
    assert source_first == clean_source

    portable_root = tmp_path / "portable"
    portable_root.mkdir()
    (portable_root / "pdf2dxf.exe").write_bytes(b"portable exe")
    (portable_root / "NOTICE.txt").write_text("notice\n", encoding="utf-8")
    portable_zip = tmp_path / "portable.zip"
    build_windows_portable.archive_portable(portable_root, portable_zip)
    portable_first = portable_zip.read_bytes()
    os.utime(portable_root / "pdf2dxf.exe", (2_000_000_000, 2_000_000_000))
    os.utime(portable_root / "NOTICE.txt", (1_000_000_000, 1_000_000_000))
    build_windows_portable.archive_portable(portable_root, portable_zip)
    portable_second = portable_zip.read_bytes()
    assert portable_first == portable_second

    with zipfile.ZipFile(portable_zip) as archive:
        infos = archive.infolist()
    assert [info.filename for info in infos] == ["NOTICE.txt", "pdf2dxf.exe"]
    assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
    assert all(info.create_system == 3 for info in infos)
    modes = {info.filename: (info.external_attr >> 16) & 0o777 for info in infos}
    assert modes == {"NOTICE.txt": 0o644, "pdf2dxf.exe": 0o755}


@pytest.mark.parametrize(
    "arcname",
    ["/absolute.txt", "\\absolute.txt", "C:/absolute.txt", "../escape.txt", "."],
)
def test_deterministic_zip_rejects_unsafe_member_paths(tmp_path, arcname) -> None:
    payload = tmp_path / "payload.txt"
    payload.write_text("payload\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe ZIP member path"):
        deterministic_zip.write_deterministic_zip(
            tmp_path / "unsafe.zip",
            [(payload, arcname)],
        )

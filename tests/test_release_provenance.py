from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts import verify_release_artifacts as release_artifacts


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "user.name=Release Test",
        "-c",
        "user.email=release-test@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _release_checkout(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".gitignore").write_text("dist/\nbuild/\n", encoding="utf-8")
    (root / "pdf2dxf.py").write_text('__version__ = "1.0.78"\n', encoding="utf-8")
    (root / "payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    package = root / "pdfcadcore"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_only.py").write_text("TEST_ONLY = 1\n", encoding="utf-8")
    release = root / ".release"
    release.mkdir()
    (release / "accepted-artifacts.json").write_text("{}\n", encoding="utf-8")
    (root / release_artifacts.RELEASE_LOCK_FILENAME).write_bytes(b"release lock\n")
    (root / release_artifacts.CI_LOCK_FILENAME).write_bytes(b"ci lock\n")
    _git(root, "init", "-q")
    head = _commit_all(root, "candidate")
    return root, head


def _write_candidate_zips(root: Path) -> tuple[Path, Path]:
    dist = root / "dist"
    dist.mkdir()
    source = dist / "LibreCAD-PDF-Importer_v1.0.78.zip"
    portable = dist / "LibreCAD-PDF-Importer-Windows-Portable_v1.0.78.zip"
    source.write_bytes(b"source-candidate\n")
    portable.write_bytes(b"portable-candidate\n")
    return source, portable


def _write_structured_candidate_zips(root: Path) -> tuple[Path, Path, dict[str, bytes]]:
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    source = dist / "LibreCAD-PDF-Importer_v1.0.78.zip"
    portable = dist / "LibreCAD-PDF-Importer-Windows-Portable_v1.0.78.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("pdf2dxf.py", '__version__ = "1.0.78"\n')
    executable_payloads = {
        "pdf2dxf.exe": b"pdf2dxf hosted bytes",
        "lcpdf-import.exe": b"import hosted bytes",
        "lcpdf-batch.exe": b"batch hosted bytes",
        "lcpdf-gui.exe": b"gui hosted bytes",
    }
    with zipfile.ZipFile(portable, "w") as archive:
        for name, payload in executable_payloads.items():
            archive.writestr(name, payload)
        archive.writestr("LICENSE", "license\n")
    return source, portable, executable_payloads


def _metadata(head: str) -> dict[str, str]:
    return {
        "repository": "BlueCollar-Systems/PDF-Importer-LibreCAD",
        "workflow": "auto-release",
        "workflow_ref": (
            "BlueCollar-Systems/PDF-Importer-LibreCAD/"
            ".github/workflows/auto-release.yml@refs/heads/main"
        ),
        "workflow_sha": head,
        "run_id": "123456",
        "run_attempt": "2",
        "head_sha": head,
        "event_name": "push",
        "runner_os": "Windows",
        "runner_arch": "X64",
        "image_os": "win25",
        "image_version": "20260727.1",
    }


def _expected_run_invocation(source: dict[str, object]) -> str:
    return (
        "https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/actions/runs/"
        f"{source['run_id']}/attempts/{source['run_attempt']}"
    )


def _attestation_result(
    source: dict[str, object],
    subjects: dict[str, str],
    *,
    bundle_marker: str = "shared-bundle",
) -> dict[str, object]:
    source_ref = str(source["workflow_ref"]).split("@", 1)[1]
    workflow_sha = str(source["workflow_sha"])
    workflow_uri = (
        "https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/"
        f".github/workflows/auto-release.yml@{source_ref}"
    )
    certificate = {
        "githubWorkflowSHA": workflow_sha,
        "githubWorkflowRepository": "BlueCollar-Systems/PDF-Importer-LibreCAD",
        "githubWorkflowRef": source_ref,
        "githubWorkflowTrigger": source["event_name"],
        "githubWorkflowName": "auto-release",
        "buildSignerURI": workflow_uri,
        "buildSignerDigest": workflow_sha,
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": (
            "https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD"
        ),
        "sourceRepositoryDigest": source["head_sha"],
        "sourceRepositoryRef": source_ref,
        "buildConfigURI": workflow_uri,
        "buildConfigDigest": workflow_sha,
        "buildTrigger": source["event_name"],
        "runInvocationURI": _expected_run_invocation(source),
    }
    return {
        "attestation": {"bundleMarker": bundle_marker},
        "verificationResult": {
            "signature": {"certificate": certificate},
            "statement": {
                "subject": [
                    {"name": name, "digest": {"sha256": digest}}
                    for name, digest in subjects.items()
                ]
            },
        },
    }


def _offline_attestation_verifier(
    _artifact: Path,
    *,
    source: dict[str, object],
    expected_subjects: dict[str, str],
) -> frozenset[str]:
    assert source["head_sha"]
    assert len(expected_subjects) == 3
    return frozenset({"offline-shared-bundle"})


def _write_candidate_provenance(path: Path, provenance: dict[str, object]) -> None:
    path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_candidate_provenance_records_run_and_exact_zip_hashes(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    source, portable = _write_candidate_zips(root)

    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )

    assert provenance["schema"] == "bcs.release_candidate_provenance/1.0"
    assert provenance["version"] == "1.0.78"
    assert provenance["source"] == {
        "event_name": "push",
        "head_sha": head,
        "repository": "BlueCollar-Systems/PDF-Importer-LibreCAD",
        "run_attempt": 2,
        "run_id": 123456,
        "workflow": "auto-release",
        "workflow_ref": (
            "BlueCollar-Systems/PDF-Importer-LibreCAD/"
            ".github/workflows/auto-release.yml@refs/heads/main"
        ),
        "workflow_sha": head,
    }
    assert provenance["runner"] == {
        "architecture": "X64",
        "image_os": "win25",
        "image_version": "20260727.1",
        "label": "windows-2025",
        "os": "Windows",
    }
    assert provenance["artifacts"]["source_zip"] == {
        "path": "dist/LibreCAD-PDF-Importer_v1.0.78.zip",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "size_bytes": len(b"source-candidate\n"),
    }
    assert provenance["artifacts"]["portable_zip"] == {
        "path": "dist/LibreCAD-PDF-Importer-Windows-Portable_v1.0.78.zip",
        "sha256": hashlib.sha256(portable.read_bytes()).hexdigest(),
        "size_bytes": len(b"portable-candidate\n"),
    }
    assert provenance["release_payload"]["file_count"] == 5
    assert len(provenance["release_payload"]["sha256"]) == 64


def test_release_payload_digest_ignores_files_excluded_by_build_release(tmp_path) -> None:
    root, candidate_head = _release_checkout(tmp_path)
    candidate = release_artifacts.release_payload_contract(root, candidate_head)

    (root / "tests" / "test_only.py").write_text("TEST_ONLY = 2\n", encoding="utf-8")
    (root / ".release" / "accepted-artifacts.json").write_text(
        '{"accepted": true}\n', encoding="utf-8"
    )
    excluded_head = _commit_all(root, "excluded changes")

    assert release_artifacts.release_payload_contract(root, excluded_head) == candidate

    (root / "payload.py").write_text("VALUE = 2\n", encoding="utf-8")
    included_head = _commit_all(root, "included change")

    assert release_artifacts.release_payload_contract(root, included_head) != candidate


def test_release_acceptance_requires_explicit_candidate_provenance(tmp_path) -> None:
    root, _head = _release_checkout(tmp_path)
    manifest_path = root / ".release" / "accepted-artifacts.json"

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="candidate provenance is required",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=manifest_path,
            root=root,
            expected_version="1.0.78",
        )


def test_release_acceptance_smokes_and_atomically_replaces_extracted_exes(
    tmp_path,
) -> None:
    root, head = _release_checkout(tmp_path)
    source, portable, executable_payloads = _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    stale_root = root / "dist" / "windows-portable"
    stale_root.mkdir()
    (stale_root / "stale.exe").write_bytes(b"must disappear")

    accepted = release_artifacts.accept_release_artifacts(
        manifest_path=root / ".release" / "accepted-artifacts.json",
        root=root,
        expected_version="1.0.78",
        provenance_path=provenance_path,
        smoke_runner=lambda portable_zip, source_zip: None,
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: None,
    )

    assert accepted["schema"] == "bcs.release_artifacts/1.1"
    assert accepted["provenance"] == provenance
    assert not (stale_root / "stale.exe").exists()
    for name, payload in executable_payloads.items():
        assert (stale_root / name).read_bytes() == payload
    verified = release_artifacts.verify_release_artifacts(
        manifest_path=root / ".release" / "accepted-artifacts.json",
        root=root,
        expected_version="1.0.78",
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: None,
    )
    assert set(verified) == set(release_artifacts.REQUIRED_ARTIFACTS)
    assert Path(verified["portable_zip"]["path"]) == portable.resolve()
    assert Path(verified["source_zip"]["path"]) == source.resolve()


def test_candidate_provenance_writer_maps_github_environment(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    output = root / "dist" / "release-candidate-provenance.json"
    environment = {
        "GITHUB_REPOSITORY": "BlueCollar-Systems/PDF-Importer-LibreCAD",
        "GITHUB_WORKFLOW": "auto-release",
        "GITHUB_WORKFLOW_REF": (
            "BlueCollar-Systems/PDF-Importer-LibreCAD/"
            ".github/workflows/auto-release.yml@refs/heads/main"
        ),
        "GITHUB_WORKFLOW_SHA": head,
        "GITHUB_RUN_ID": "987654",
        "GITHUB_RUN_ATTEMPT": "3",
        "GITHUB_SHA": head,
        "GITHUB_EVENT_NAME": "push",
        "RUNNER_OS": "Windows",
        "RUNNER_ARCH": "X64",
        "ImageOS": "win25",
        "ImageVersion": "20260727.1",
    }

    written = release_artifacts.write_candidate_provenance(
        output_path=output,
        root=root,
        environment=environment,
    )

    assert written == output.resolve()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source"]["head_sha"] == head
    assert payload["source"]["run_id"] == 987654
    assert payload["source"]["run_attempt"] == 3
    assert payload["source"]["workflow_sha"] == head
    assert payload["runner"]["image_version"] == "20260727.1"


def test_github_attestation_verification_binds_exact_release_identity(
    tmp_path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "candidate.zip"
    artifact.write_bytes(b"attested candidate")
    source = {
        "event_name": "push",
        "head_sha": "a" * 40,
        "repository": "BlueCollar-Systems/PDF-Importer-LibreCAD",
        "run_attempt": 2,
        "run_id": 123456,
        "workflow": "auto-release",
        "workflow_ref": (
            "BlueCollar-Systems/PDF-Importer-LibreCAD/"
            ".github/workflows/auto-release.yml@refs/heads/main"
        ),
        "workflow_sha": "b" * 40,
    }
    expected_subjects = {
        "candidate.zip": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "source.zip": "c" * 64,
        "release-candidate-provenance.json": "d" * 64,
    }
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps([_attestation_result(source, expected_subjects)]),
            stderr="",
        )

    monkeypatch.setattr(release_artifacts.subprocess, "run", fake_run)

    identities = release_artifacts._verify_github_attestation(
        artifact,
        source=source,
        expected_subjects=expected_subjects,
    )

    assert len(identities) == 1

    assert calls == [
        (
            [
                "gh",
                "attestation",
                "verify",
                str(artifact.resolve()),
                "--repo",
                "BlueCollar-Systems/PDF-Importer-LibreCAD",
                "--signer-workflow",
                (
                    "BlueCollar-Systems/PDF-Importer-LibreCAD/"
                    ".github/workflows/auto-release.yml"
                ),
                "--signer-digest",
                "b" * 40,
                "--source-digest",
                "a" * 40,
                "--source-ref",
                "refs/heads/main",
                "--deny-self-hosted-runners",
                "--format",
                "json",
            ],
            {
                "capture_output": True,
                "check": True,
                "text": True,
            },
        )
    ]


def test_acceptance_requires_one_shared_attestation_for_all_candidate_files(
    tmp_path,
) -> None:
    root, head = _release_checkout(tmp_path)
    source, portable, _payloads = _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    verified_subjects = []

    def verify_attestation(artifact, *, source, expected_subjects):
        verified_subjects.append((artifact, source, expected_subjects))
        return frozenset({"one-shared-bundle"})

    accepted = release_artifacts.accept_release_artifacts(
        manifest_path=root / ".release" / "accepted-artifacts.json",
        root=root,
        expected_version="1.0.78",
        provenance_path=provenance_path,
        smoke_runner=lambda portable_zip, source_zip: None,
        attestation_verifier=verify_attestation,
        hosted_run_verifier=lambda **kwargs: None,
    )

    expected_paths = [
        source.resolve(),
        portable.resolve(),
        provenance_path.resolve(),
    ]
    assert [item[0] for item in verified_subjects] == expected_paths
    assert all(item[1]["head_sha"] == head for item in verified_subjects)
    assert all(len(item[2]) == 3 for item in verified_subjects)
    assert all(
        set(item[2]) == {source.name, portable.name, provenance_path.name}
        for item in verified_subjects
    )
    assert accepted["provenance"]["source"]["head_sha"] == head


def test_acceptance_rejects_candidate_files_from_different_attestation_bundles(
    tmp_path,
) -> None:
    root, head = _release_checkout(tmp_path)
    source, portable, _payloads = _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)

    def split_attestations(artifact, **_kwargs):
        if artifact == provenance_path.resolve():
            return frozenset({"different-bundle"})
        return frozenset({"zip-bundle"})

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="same GitHub attestation",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=root / ".release" / "accepted-artifacts.json",
            root=root,
            expected_version="1.0.78",
            provenance_path=provenance_path,
            smoke_runner=lambda portable_zip, source_zip: None,
            attestation_verifier=split_attestations,
            hosted_run_verifier=lambda **kwargs: None,
        )


def test_github_attestation_selects_matching_result_from_history(
    tmp_path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "candidate.zip"
    artifact.write_bytes(b"attested candidate")
    source = {
        "event_name": "push",
        "head_sha": "a" * 40,
        "repository": "BlueCollar-Systems/PDF-Importer-LibreCAD",
        "run_attempt": 2,
        "run_id": 123456,
        "workflow": "auto-release",
        "workflow_ref": (
            "BlueCollar-Systems/PDF-Importer-LibreCAD/"
            ".github/workflows/auto-release.yml@refs/heads/main"
        ),
        "workflow_sha": "b" * 40,
    }
    subjects = {
        artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "source.zip": "c" * 64,
        "release-candidate-provenance.json": "d" * 64,
    }
    historical_source = dict(source, run_attempt=1)
    results = [
        _attestation_result(
            historical_source,
            subjects,
            bundle_marker="historical-bundle",
        ),
        _attestation_result(source, subjects, bundle_marker="current-bundle"),
    ]

    monkeypatch.setattr(
        release_artifacts.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(results),
            stderr="",
        ),
    )

    identities = release_artifacts._verify_github_attestation(
        artifact,
        source=source,
        expected_subjects=subjects,
    )

    assert len(identities) == 1


@pytest.mark.parametrize(
    "workflow_path",
    [
        ".github/workflows/auto-release.yml",
        ".github/workflows/auto-release.yml@main",
        ".github/workflows/auto-release.yml@refs/heads/main",
    ],
)
def test_hosted_run_verification_matches_failed_run_and_retained_candidate(
    tmp_path,
    monkeypatch,
    workflow_path,
) -> None:
    root, head = _release_checkout(tmp_path)
    source, portable, _payloads = _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ["gh", "api"] and command[2].endswith("/123456"):
            payload = {
                "id": 123456,
                "run_attempt": 2,
                "head_sha": head,
                "path": workflow_path,
                "event": "push",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "failure",
                "repository": {
                    "full_name": "BlueCollar-Systems/PDF-Importer-LibreCAD"
                },
                "head_repository": {
                    "full_name": "BlueCollar-Systems/PDF-Importer-LibreCAD"
                },
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(payload), stderr=""
            )
        if command[:2] == ["gh", "api"]:
            payload = {
                "artifacts": [
                    {
                        "id": 987,
                        "name": "failed-release-candidate-123456-2",
                        "expired": False,
                        "workflow_run": {"id": 123456, "head_sha": head},
                    }
                ]
            }
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(payload), stderr=""
            )
        destination = Path(command[command.index("--dir") + 1])
        (destination / "dist").mkdir(parents=True)
        for candidate in (source, portable, provenance_path):
            (destination / "dist" / candidate.name).write_bytes(
                candidate.read_bytes()
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(release_artifacts.subprocess, "run", fake_run)

    release_artifacts._verify_hosted_candidate_run(
        provenance=provenance,
        artifact_paths={"source_zip": source, "portable_zip": portable},
        provenance_path=provenance_path,
    )

    assert [command[:2] for command, _kwargs in calls] == [
        ["gh", "api"],
        ["gh", "api"],
        ["gh", "run"],
    ]
    assert "repos/BlueCollar-Systems/PDF-Importer-LibreCAD/actions/runs/123456" in calls[0][0]
    assert "--name" in calls[2][0]
    assert "failed-release-candidate-123456-2" in calls[2][0]


def test_acceptance_requires_hosted_run_binding(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    hosted_candidates = []

    release_artifacts.accept_release_artifacts(
        manifest_path=root / ".release" / "accepted-artifacts.json",
        root=root,
        expected_version="1.0.78",
        provenance_path=provenance_path,
        smoke_runner=lambda portable_zip, source_zip: None,
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: hosted_candidates.append(kwargs),
    )

    assert len(hosted_candidates) == 1
    assert hosted_candidates[0]["provenance"] == provenance
    assert hosted_candidates[0]["provenance_path"] == provenance_path.resolve()


def test_default_acceptance_fails_closed_when_github_attestation_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    smoke_called = False

    def unavailable(_path, **_kwargs):
        raise release_artifacts.ArtifactVerificationError(
            "GitHub artifact attestation verification failed"
        )

    def smoke(_portable_zip, _source_zip):
        nonlocal smoke_called
        smoke_called = True

    monkeypatch.setattr(release_artifacts, "_verify_github_attestation", unavailable)

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="attestation verification failed",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=root / ".release" / "accepted-artifacts.json",
            root=root,
            expected_version="1.0.78",
            provenance_path=provenance_path,
            smoke_runner=smoke,
        )

    assert smoke_called is False


def test_candidate_builder_rejects_non_string_runner_metadata(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_candidate_zips(root)
    metadata = dict(_metadata(head))
    metadata["runner_os"] = 123

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="runner_os.*string",
    ):
        release_artifacts.build_candidate_provenance(root=root, metadata=metadata)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_loader_rejects_non_finite_numbers(tmp_path, constant) -> None:
    path = tmp_path / "non-finite.json"
    path.write_text(f'{{"value": {constant}}}', encoding="utf-8")

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="non-finite JSON number",
    ):
        release_artifacts._load_json_mapping(path, label="test manifest")


def test_json_loader_rejects_duplicate_keys(tmp_path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema": "one", "schema": "two"}', encoding="utf-8")

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="duplicate JSON key",
    ):
        release_artifacts._load_json_mapping(path, label="test manifest")


def test_candidate_schema_rejects_unknown_private_metadata(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance["private_metadata"] = {
        "workspace": "Z:/PrivateRoot/Sensitive Person/private-corpus"
    }

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="candidate provenance.*unknown keys.*private_metadata",
    ):
        release_artifacts._validate_candidate_provenance(
            provenance,
            root=root,
            version="1.0.78",
            manifest_path=root / ".release" / "accepted-artifacts.json",
        )


def test_accepted_manifest_schema_rejects_unknown_keys(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    manifest_path = root / ".release" / "accepted-artifacts.json"
    accepted = release_artifacts.accept_release_artifacts(
        manifest_path=manifest_path,
        root=root,
        expected_version="1.0.78",
        provenance_path=provenance_path,
        smoke_runner=lambda portable_zip, source_zip: None,
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: None,
    )
    accepted["unexpected"] = "private local note"
    manifest_path.write_text(json.dumps(accepted), encoding="utf-8")

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="accepted artifact manifest.*unknown keys.*unexpected",
    ):
        release_artifacts.verify_release_artifacts(
            manifest_path=manifest_path,
            root=root,
            expected_version="1.0.78",
        )


def test_portable_extraction_uses_only_canonical_repo_dist(tmp_path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    _source, portable, executable_payloads = _write_structured_candidate_zips(root)

    release_artifacts._extract_portable_atomically(portable, root=root)

    target = root / "dist" / "windows-portable"
    assert {
        name: (target / name).read_bytes()
        for name in release_artifacts.REQUIRED_EXE_FILENAMES
    } == executable_payloads


def test_portable_extraction_rejects_reparse_dist_before_mutation(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    _source, portable, _payloads = _write_structured_candidate_zips(root)
    dist = root / "dist"
    target = dist / "windows-portable"
    target.mkdir()
    sentinel = target / "preserve.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")

    monkeypatch.setattr(
        release_artifacts,
        "_path_is_reparse_point",
        lambda path: Path(path) == dist,
    )

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="reparse point.*dist",
    ):
        release_artifacts._extract_portable_atomically(portable, root=root)

    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_acceptance_rejects_dirty_tracked_candidate_checkout(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    (root / "payload.py").write_text("DIRTY = True\n", encoding="utf-8")

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="clean candidate checkout",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=root / ".release" / "accepted-artifacts.json",
            root=root,
            expected_version="1.0.78",
            provenance_path=provenance_path,
            smoke_runner=lambda portable_zip, source_zip: None,
            attestation_verifier=_offline_attestation_verifier,
            hosted_run_verifier=lambda **kwargs: None,
        )


def test_acceptance_rejects_candidate_zip_mutated_after_provenance(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _source, portable, _payloads = _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    portable.write_bytes(b"mutated after hosted run")

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="portable_zip SHA-256/size provenance mismatch",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=root / ".release" / "accepted-artifacts.json",
            root=root,
            expected_version="1.0.78",
            provenance_path=provenance_path,
            smoke_runner=lambda portable_zip, source_zip: None,
            attestation_verifier=_offline_attestation_verifier,
            hosted_run_verifier=lambda **kwargs: None,
        )


def test_zip_slip_rejection_preserves_existing_portable_directory(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    source, portable, executable_payloads = _write_structured_candidate_zips(root)
    with zipfile.ZipFile(portable, "a") as archive:
        archive.writestr("../escape.exe", b"escape")
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    portable_root = root / "dist" / "windows-portable"
    portable_root.mkdir()
    sentinel = portable_root / "prior-build.txt"
    sentinel.write_text("preserve on failure\n", encoding="utf-8")

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="unsafe portable ZIP member path",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=root / ".release" / "accepted-artifacts.json",
            root=root,
            expected_version="1.0.78",
            provenance_path=provenance_path,
            smoke_runner=lambda portable_zip, source_zip: None,
            attestation_verifier=_offline_attestation_verifier,
            hosted_run_verifier=lambda **kwargs: None,
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve on failure\n"
    assert not (root / "dist" / "escape.exe").exists()
    assert not (root / "escape.exe").exists()


def test_final_verifier_allows_only_manifest_descendant_of_candidate(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    manifest_path = root / ".release" / "accepted-artifacts.json"
    release_artifacts.accept_release_artifacts(
        manifest_path=manifest_path,
        root=root,
        expected_version="1.0.78",
        provenance_path=provenance_path,
        smoke_runner=lambda portable_zip, source_zip: None,
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: None,
    )
    accepted_head = _commit_all(root, "accept hosted candidate")

    verified = release_artifacts.verify_release_artifacts(
        manifest_path=manifest_path,
        root=root,
        expected_version="1.0.78",
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: None,
    )

    assert accepted_head != head
    assert set(verified) == set(release_artifacts.REQUIRED_ARTIFACTS)

    (root / "payload.py").write_text("VALUE = 999\n", encoding="utf-8")
    _commit_all(root, "unexpected package mutation")
    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="may change only the accepted-artifact manifest",
    ):
        release_artifacts.verify_release_artifacts(
            manifest_path=manifest_path,
            root=root,
            expected_version="1.0.78",
        )


def test_final_verifier_reauthenticates_two_commit_forged_manifest(tmp_path) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    manifest_path = root / ".release" / "accepted-artifacts.json"
    release_artifacts.accept_release_artifacts(
        manifest_path=manifest_path,
        root=root,
        expected_version="1.0.78",
        provenance_path=provenance_path,
        smoke_runner=lambda portable_zip, source_zip: None,
        attestation_verifier=_offline_attestation_verifier,
        hosted_run_verifier=lambda **kwargs: None,
    )
    _commit_all(root, "accept hosted candidate")

    forged = json.loads(manifest_path.read_text(encoding="utf-8"))
    forged["provenance"]["source"]["run_id"] += 1
    manifest_path.write_text(
        json.dumps(forged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _commit_all(root, "forge accepted run identity")
    attempted_subjects = []

    def reject_forged_attestation(artifact, **_kwargs):
        attempted_subjects.append(Path(artifact).name)
        raise release_artifacts.ArtifactVerificationError(
            "forged manifest has no matching cryptographic attestation"
        )

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="no matching cryptographic attestation",
    ):
        release_artifacts.verify_release_artifacts(
            manifest_path=manifest_path,
            root=root,
            expected_version="1.0.78",
            attestation_verifier=reject_forged_attestation,
            hosted_run_verifier=lambda **kwargs: None,
        )

    assert attempted_subjects == ["LibreCAD-PDF-Importer_v1.0.78.zip"]


def test_cli_writes_candidate_provenance_sidecar_from_hosted_environment(
    tmp_path,
    monkeypatch,
) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    output = root / "dist" / "release-candidate-provenance.json"
    for key, value in _metadata(head).items():
        environment_key = {
            "repository": "GITHUB_REPOSITORY",
            "workflow": "GITHUB_WORKFLOW",
            "workflow_ref": "GITHUB_WORKFLOW_REF",
            "workflow_sha": "GITHUB_WORKFLOW_SHA",
            "run_id": "GITHUB_RUN_ID",
            "run_attempt": "GITHUB_RUN_ATTEMPT",
            "head_sha": "GITHUB_SHA",
            "event_name": "GITHUB_EVENT_NAME",
            "runner_os": "RUNNER_OS",
            "runner_arch": "RUNNER_ARCH",
            "image_os": "ImageOS",
            "image_version": "ImageVersion",
        }[key]
        monkeypatch.setenv(environment_key, value)
    monkeypatch.setattr(release_artifacts, "ROOT", root)

    exit_code = release_artifacts.main(
        ["--write-candidate-provenance", str(output)]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source"]["head_sha"] == head
    assert payload["artifacts"]["portable_zip"]["size_bytes"] > 0


def test_release_workflow_generates_and_retains_candidate_provenance() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "auto-release.yml"
    ).read_text(encoding="utf-8")

    smoke = workflow.index("scripts/smoke_portable_zip.py")
    provenance = workflow.index("--write-candidate-provenance")
    verify = workflow.index("scripts/verify_release_artifacts.py", provenance + 1)

    assert smoke < provenance < verify
    assert (
        "python scripts/verify_release_artifacts.py "
        "--write-candidate-provenance dist/release-candidate-provenance.json"
    ) in workflow
    assert "dist/release-candidate-provenance.json" in workflow[verify:]


def test_release_workflow_cryptographically_attests_both_zips() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "auto-release.yml"
    ).read_text(encoding="utf-8")

    assert (
        "permissions:\n  actions: read\n  contents: read\n  id-token: write\n"
        "  attestations: write"
    ) in workflow
    attest = workflow.index(
        "actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d # v4"
    )
    verify = workflow.index("scripts/verify_release_artifacts.py", attest)
    assert attest < verify
    subject_block = workflow[attest:verify]
    assert "subject-path: |" in subject_block
    assert "dist/LibreCAD-PDF-Importer_v${{ steps.version.outputs.version }}.zip" in subject_block
    assert (
        "dist/LibreCAD-PDF-Importer-Windows-Portable_v"
        "${{ steps.version.outputs.version }}.zip"
    ) in subject_block
    assert "dist/release-candidate-provenance.json" in subject_block
    verify_step = workflow.rfind("- name: Verify exact accepted release bytes", attest, verify)
    verify_block = workflow[verify_step : workflow.index("- name:", verify + 10)]
    assert "GH_TOKEN: ${{ github.token }}" in verify_block


def test_acceptance_preserves_prior_manifest_when_candidate_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    root, head = _release_checkout(tmp_path)
    _write_structured_candidate_zips(root)
    provenance = release_artifacts.build_candidate_provenance(
        root=root,
        metadata=_metadata(head),
    )
    provenance_path = root / "dist" / "release-candidate-provenance.json"
    _write_candidate_provenance(provenance_path, provenance)
    manifest_path = root / ".release" / "accepted-artifacts.json"
    prior_manifest = manifest_path.read_bytes()

    def reject_candidate(**_kwargs) -> None:
        raise release_artifacts.ArtifactVerificationError(
            "forced candidate verification failure"
        )

    monkeypatch.setattr(
        release_artifacts,
        "verify_release_artifacts",
        reject_candidate,
    )

    with pytest.raises(
        release_artifacts.ArtifactVerificationError,
        match="forced candidate verification failure",
    ):
        release_artifacts.accept_release_artifacts(
            manifest_path=manifest_path,
            root=root,
            expected_version="1.0.78",
            provenance_path=provenance_path,
            smoke_runner=lambda portable_zip, source_zip: None,
            attestation_verifier=_offline_attestation_verifier,
            hosted_run_verifier=lambda **kwargs: None,
        )

    assert manifest_path.read_bytes() == prior_manifest
    assert not list((root / "dist").glob(f".{manifest_path.name}.*.candidate"))

#!/usr/bin/env python3
"""Verify exact accepted release bytes before any GitHub publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from release_build_contract import (  # noqa: E402
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
    assert_release_interpreter,
)
from pdfcadcore.atomic_io import atomic_write_text  # noqa: E402
from build_release import _PACKAGE_DIRECTORIES, _should_include  # noqa: E402


DEFAULT_MANIFEST = ROOT / ".release" / "accepted-artifacts.json"
CANDIDATE_PROVENANCE_SCHEMA = "bcs.release_candidate_provenance/1.0"
CANDIDATE_PROVENANCE_PATH = ROOT / "dist" / "release-candidate-provenance.json"
ACCEPTED_MANIFEST_SCHEMA = "bcs.release_artifacts/1.1"
LEGACY_MANIFEST_SCHEMA = "bcs.release_artifacts/1.0"
EXPECTED_REPOSITORY = "BlueCollar-Systems/PDF-Importer-LibreCAD"
EXPECTED_WORKFLOW = "auto-release"
EXPECTED_WORKFLOW_PATH = ".github/workflows/auto-release.yml"
EXPECTED_SIGNER_WORKFLOW = f"{EXPECTED_REPOSITORY}/{EXPECTED_WORKFLOW_PATH}"
REQUIRED_ARTIFACTS = (
    "source_zip",
    "portable_zip",
    "pdf2dxf_exe",
    "lcpdf_import_exe",
    "lcpdf_batch_exe",
    "lcpdf_gui_exe",
)
REQUIRED_EXE_FILENAMES = (
    "pdf2dxf.exe",
    "lcpdf-import.exe",
    "lcpdf-batch.exe",
    "lcpdf-gui.exe",
)
_CANDIDATE_KEYS = {
    "schema",
    "version",
    "source",
    "runner",
    "build_contract",
    "release_payload",
    "artifacts",
}
_SOURCE_KEYS = {
    "event_name",
    "head_sha",
    "repository",
    "run_attempt",
    "run_id",
    "workflow",
    "workflow_ref",
    "workflow_sha",
}
_RUNNER_KEYS = {"architecture", "image_os", "image_version", "label", "os"}
_BUILD_CONTRACT_KEYS = {
    "architecture",
    "ci_lock",
    "ci_lock_sha256",
    "checkout_action",
    "github_script_action",
    "python",
    "python_setup_action",
    "pythonhashseed",
    "requirements_lock",
    "requirements_lock_sha256",
    "runner",
    "source_date_epoch",
}
_RELEASE_PAYLOAD_KEYS = {"file_count", "sha256"}
_ARTIFACT_KEYS = {"path", "sha256", "size_bytes"}
_LEGACY_MANIFEST_KEYS = {"schema", "version", "build_contract", "artifacts"}
_ACCEPTED_MANIFEST_KEYS = _LEGACY_MANIFEST_KEYS | {"provenance"}


class ArtifactVerificationError(RuntimeError):
    """Accepted release manifest or artifact bytes are not exact."""


def _require_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactVerificationError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(
    value: object,
    expected: set[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    mapping = _require_mapping(value, label=label)
    actual = set(mapping)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise ArtifactVerificationError(
            f"{label} has unknown keys: {', '.join(unknown)}"
        )
    if missing:
        raise ArtifactVerificationError(
            f"{label} is missing keys: {', '.join(missing)}"
        )
    return mapping


def _require_string(value: object, *, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise ArtifactVerificationError(f"{label} must be {qualifier}")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ArtifactVerificationError(f"{label} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactVerificationError(f"{label} must be a non-negative integer")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    digest = _require_string(value, label=label)
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ArtifactVerificationError(f"{label} must be a lowercase SHA-256")
    return digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={Path(root).resolve()}",
            *arguments,
        ],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    return completed.stdout


def _release_payload_path_included(raw_path: str) -> bool:
    normalized = str(raw_path).replace("\\", "/")
    parts = normalized.split("/")
    return bool(
        (len(parts) == 1 or parts[0] in _PACKAGE_DIRECTORIES)
        and _should_include(normalized)
    )


def release_payload_contract(root: Path, commit: str) -> dict[str, Any]:
    """Hash the exact Git blob set selected by ``build_release.py``."""

    project_root = Path(root).resolve()
    raw_tree = _git_output(
        project_root,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        str(commit),
        binary=True,
    )
    assert isinstance(raw_tree, bytes)
    entries: list[tuple[str, str]] = []
    for raw_record in raw_tree.split(b"\0"):
        if not raw_record:
            continue
        metadata, raw_path = raw_record.split(b"\t", 1)
        _mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        if object_type != "blob":
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        if _release_payload_path_included(path):
            entries.append((path, object_id))
    entries.sort(key=lambda item: item[0])
    digest = hashlib.sha256()
    for path, object_id in entries:
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(object_id.encode("ascii"))
        digest.update(b"\n")
    return {"file_count": len(entries), "sha256": digest.hexdigest()}


def _build_contract(root: Path) -> dict[str, Any]:
    release_lock = Path(root) / RELEASE_LOCK_FILENAME
    ci_lock = Path(root) / CI_LOCK_FILENAME
    if not release_lock.is_file():
        raise ArtifactVerificationError(
            f"release dependency lock is missing: {release_lock}"
        )
    if not ci_lock.is_file():
        raise ArtifactVerificationError(f"CI dependency lock is missing: {ci_lock}")
    return {
        "architecture": EXPECTED_ARCHITECTURE,
        "ci_lock": CI_LOCK_FILENAME,
        "ci_lock_sha256": _sha256(ci_lock),
        "checkout_action": CHECKOUT_ACTION,
        "github_script_action": GITHUB_SCRIPT_ACTION,
        "python": ".".join(map(str, EXPECTED_PYTHON_VERSION)),
        "python_setup_action": SETUP_PYTHON_ACTION,
        "pythonhashseed": PYTHONHASHSEED,
        "requirements_lock": RELEASE_LOCK_FILENAME,
        "requirements_lock_sha256": _sha256(release_lock),
        "runner": RELEASE_RUNNER,
        "source_date_epoch": SOURCE_DATE_EPOCH,
    }


def build_candidate_provenance(
    *,
    root: Path = ROOT,
    metadata: Mapping[str, str],
) -> dict[str, Any]:
    """Describe one hosted candidate without trusting mutable local outputs."""

    project_root = Path(root).resolve()
    version = _read_project_version(project_root)
    text_metadata = {
        key: _require_string(
            metadata.get(key),
            label=f"candidate {key}",
        )
        for key in (
            "repository",
            "workflow",
            "workflow_ref",
            "workflow_sha",
            "run_id",
            "run_attempt",
            "head_sha",
            "event_name",
            "runner_os",
            "runner_arch",
            "image_os",
            "image_version",
        )
    }
    head_sha = text_metadata["head_sha"].strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        raise ArtifactVerificationError("candidate head SHA must be a full Git SHA-1")
    workflow_sha = text_metadata["workflow_sha"].strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", workflow_sha) is None:
        raise ArtifactVerificationError(
            "candidate workflow SHA must be a full Git SHA-1"
        )
    actual_head = str(_git_output(project_root, "rev-parse", "HEAD")).strip().lower()
    if actual_head != head_sha:
        raise ArtifactVerificationError(
            f"candidate checkout HEAD mismatch: expected {head_sha}, got {actual_head}"
        )
    try:
        run_id = int(text_metadata["run_id"])
        run_attempt = int(text_metadata["run_attempt"])
    except ValueError as exc:
        raise ArtifactVerificationError("candidate run id/attempt must be integers") from exc
    if run_id <= 0 or run_attempt <= 0:
        raise ArtifactVerificationError("candidate run id/attempt must be positive")

    canonical = _canonical_artifact_paths(project_root, version)
    artifacts: dict[str, dict[str, Any]] = {}
    for name in ("source_zip", "portable_zip"):
        path = canonical[name]
        if not path.is_file():
            raise ArtifactVerificationError(f"candidate {name} is missing: {path}")
        artifacts[name] = {
            "path": path.relative_to(project_root).as_posix(),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }

    return {
        "schema": CANDIDATE_PROVENANCE_SCHEMA,
        "version": version,
        "source": {
            "event_name": text_metadata["event_name"],
            "head_sha": head_sha,
            "repository": text_metadata["repository"],
            "run_attempt": run_attempt,
            "run_id": run_id,
            "workflow": text_metadata["workflow"],
            "workflow_ref": text_metadata["workflow_ref"],
            "workflow_sha": workflow_sha,
        },
        "runner": {
            "architecture": text_metadata["runner_arch"],
            "image_os": text_metadata["image_os"],
            "image_version": text_metadata["image_version"],
            "label": RELEASE_RUNNER,
            "os": text_metadata["runner_os"],
        },
        "build_contract": _build_contract(project_root),
        "release_payload": release_payload_contract(project_root, head_sha),
        "artifacts": artifacts,
    }


def write_candidate_provenance(
    *,
    output_path: Path = CANDIDATE_PROVENANCE_PATH,
    root: Path = ROOT,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Write hosted-run metadata and candidate ZIP hashes as an atomic sidecar."""

    project_root = Path(root).resolve()
    output = Path(output_path).resolve()
    if not output.is_relative_to(project_root):
        raise ArtifactVerificationError(f"candidate provenance escapes repository: {output}")
    env = os.environ if environment is None else environment
    metadata = {
        "repository": str(env.get("GITHUB_REPOSITORY", "")),
        "workflow": str(env.get("GITHUB_WORKFLOW", "")),
        "workflow_ref": str(env.get("GITHUB_WORKFLOW_REF", "")),
        "workflow_sha": str(env.get("GITHUB_WORKFLOW_SHA", "")),
        "run_id": str(env.get("GITHUB_RUN_ID", "")),
        "run_attempt": str(env.get("GITHUB_RUN_ATTEMPT", "")),
        "head_sha": str(env.get("GITHUB_SHA", "")),
        "event_name": str(env.get("GITHUB_EVENT_NAME", "")),
        "runner_os": str(env.get("RUNNER_OS", "")),
        "runner_arch": str(env.get("RUNNER_ARCH", "")),
        "image_os": str(env.get("ImageOS", env.get("IMAGE_OS", ""))),
        "image_version": str(
            env.get("ImageVersion", env.get("IMAGE_VERSION", ""))
        ),
    }
    provenance = build_candidate_provenance(root=project_root, metadata=metadata)
    candidate_head = str(provenance["source"]["head_sha"])
    _assert_clean_candidate_checkout(project_root, candidate_head)
    atomic_write_text(
        output,
        _canonical_candidate_provenance_text(provenance),
    )
    return output


def _confined(root: Path, raw_path: object) -> Path:
    candidate = (root / str(raw_path)).resolve()
    if not candidate.is_relative_to(root):
        raise ArtifactVerificationError(f"artifact path escapes repository: {raw_path}")
    return candidate


def _strict_json_loads(payload: str, *, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload,
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
    except ValueError as exc:
        raise ArtifactVerificationError(f"cannot read {label}: {exc}") from exc


def _load_json_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactVerificationError(f"cannot read {label}: {exc}") from exc
    value = _strict_json_loads(payload, label=label)
    if not isinstance(value, Mapping):
        raise ArtifactVerificationError(f"{label} must be a JSON object")
    return value


def _canonical_candidate_provenance_text(provenance: Mapping[str, Any]) -> str:
    return json.dumps(
        provenance,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _assert_clean_candidate_checkout(root: Path, candidate_head: str) -> None:
    actual_head = str(_git_output(root, "rev-parse", "HEAD")).strip().lower()
    if actual_head != candidate_head:
        raise ArtifactVerificationError(
            f"acceptance checkout HEAD mismatch: expected {candidate_head}, got {actual_head}"
        )
    status = str(
        _git_output(root, "status", "--porcelain=v1", "--untracked-files=all")
    ).strip()
    if status:
        raise ArtifactVerificationError(
            "acceptance requires a clean candidate checkout; canonical ignored dist "
            f"outputs are the only permitted local files: {status}"
        )


def _artifact_contract(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_artifact_record(value: object, *, label: str) -> Mapping[str, Any]:
    record = _require_exact_keys(value, _ARTIFACT_KEYS, label=label)
    _require_string(record["path"], label=f"{label} path")
    _require_sha256(record["sha256"], label=f"{label} sha256")
    _require_nonnegative_int(record["size_bytes"], label=f"{label} size_bytes")
    return record


def _validate_build_contract_shape(value: object, *, label: str) -> Mapping[str, Any]:
    contract = _require_exact_keys(value, _BUILD_CONTRACT_KEYS, label=label)
    for key, field_value in contract.items():
        _require_string(field_value, label=f"{label} {key}")
    return contract


def _validate_candidate_provenance(
    provenance: Mapping[str, Any],
    *,
    root: Path,
    version: str,
    manifest_path: Path,
) -> str:
    provenance = _require_exact_keys(
        provenance,
        _CANDIDATE_KEYS,
        label="candidate provenance",
    )
    if provenance.get("schema") != CANDIDATE_PROVENANCE_SCHEMA:
        raise ArtifactVerificationError("candidate provenance schema is invalid")
    if provenance.get("version") != version:
        raise ArtifactVerificationError(
            "candidate provenance version mismatch: "
            f"expected {version}, got {provenance.get('version')}"
        )
    source = _require_exact_keys(
        provenance["source"],
        _SOURCE_KEYS,
        label="candidate source provenance",
    )
    runner = _require_exact_keys(
        provenance["runner"],
        _RUNNER_KEYS,
        label="candidate runner provenance",
    )
    for key in (
        "event_name",
        "head_sha",
        "repository",
        "workflow",
        "workflow_ref",
        "workflow_sha",
    ):
        _require_string(source[key], label=f"candidate source {key}")
    for key, value in runner.items():
        _require_string(value, label=f"candidate runner {key}")
    candidate_head = source["head_sha"].strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", candidate_head) is None:
        raise ArtifactVerificationError("candidate provenance head SHA is invalid")
    workflow_sha = source["workflow_sha"].strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", workflow_sha) is None:
        raise ArtifactVerificationError("candidate provenance workflow SHA is invalid")
    if source.get("repository") != EXPECTED_REPOSITORY:
        raise ArtifactVerificationError("candidate repository provenance is invalid")
    if source.get("workflow") != EXPECTED_WORKFLOW:
        raise ArtifactVerificationError("candidate workflow provenance is invalid")
    workflow_ref = str(source.get("workflow_ref", ""))
    expected_workflow_ref = f"{EXPECTED_REPOSITORY}/{EXPECTED_WORKFLOW_PATH}@"
    if not workflow_ref.startswith(expected_workflow_ref):
        raise ArtifactVerificationError("candidate workflow ref provenance is invalid")
    for key in ("run_id", "run_attempt"):
        _require_positive_int(source[key], label=f"candidate {key} provenance")
    if source.get("event_name") not in {"push", "workflow_dispatch"}:
        raise ArtifactVerificationError("candidate event provenance is invalid")
    if (
        runner.get("label") != RELEASE_RUNNER
        or runner.get("os") != "Windows"
        or runner.get("architecture") != "X64"
        or not runner["image_os"].strip()
        or not runner["image_version"].strip()
    ):
        raise ArtifactVerificationError("candidate runner provenance is invalid")
    build_contract = _validate_build_contract_shape(
        provenance["build_contract"],
        label="candidate build contract",
    )
    if build_contract != _build_contract(root):
        raise ArtifactVerificationError("candidate build contract provenance is invalid")

    release_payload = _require_exact_keys(
        provenance["release_payload"],
        _RELEASE_PAYLOAD_KEYS,
        label="candidate release payload",
    )
    _require_nonnegative_int(
        release_payload["file_count"],
        label="candidate release payload file_count",
    )
    _require_sha256(
        release_payload["sha256"],
        label="candidate release payload sha256",
    )

    try:
        _git_output(root, "cat-file", "-e", f"{candidate_head}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise ArtifactVerificationError(
            f"candidate commit is unavailable in checkout: {candidate_head}"
        ) from exc
    expected_payload = release_payload_contract(root, candidate_head)
    if provenance.get("release_payload") != expected_payload:
        raise ArtifactVerificationError("candidate package payload provenance is invalid")

    canonical = _canonical_artifact_paths(root, version)
    expected_artifacts = _require_exact_keys(
        provenance["artifacts"],
        {"source_zip", "portable_zip"},
        label="candidate ZIP provenance",
    )
    for name in ("source_zip", "portable_zip"):
        path = canonical[name]
        if not path.is_file():
            raise ArtifactVerificationError(f"candidate {name} is missing: {path}")
        expected = _validate_artifact_record(
            expected_artifacts[name],
            label=f"candidate {name}",
        )
        if expected != _artifact_contract(path, root):
            raise ArtifactVerificationError(
                f"candidate {name} SHA-256/size provenance mismatch"
            )

    current_head = str(_git_output(root, "rev-parse", "HEAD")).strip().lower()
    if current_head != candidate_head:
        try:
            _git_output(root, "merge-base", "--is-ancestor", candidate_head, current_head)
        except subprocess.CalledProcessError as exc:
            raise ArtifactVerificationError(
                "current release commit is not a descendant of the candidate head"
            ) from exc
        raw_changed = _git_output(
            root,
            "diff",
            "--name-only",
            "-z",
            f"{candidate_head}..{current_head}",
            binary=True,
        )
        assert isinstance(raw_changed, bytes)
        changed = {
            item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
            for item in raw_changed.split(b"\0")
            if item
        }
        allowed_manifest = manifest_path.resolve().relative_to(root.resolve()).as_posix()
        if changed != {allowed_manifest}:
            raise ArtifactVerificationError(
                "release descendant may change only the accepted-artifact manifest: "
                f"got {sorted(changed)}"
            )
    current_payload = release_payload_contract(root, current_head)
    if current_payload != expected_payload:
        raise ArtifactVerificationError(
            "current package-included tracked bytes differ from candidate head"
        )
    return candidate_head


def _safe_zip_member_path(raw_name: str) -> PurePosixPath:
    normalized = str(raw_name).replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or any(":" in part for part in path.parts)
    ):
        raise ArtifactVerificationError(f"unsafe portable ZIP member path: {raw_name!r}")
    return path


def _lexical_absolute(path: Path) -> Path:
    """Return an absolute normalized path without following links/reparse points."""

    return Path(os.path.abspath(os.fspath(path)))


def _path_is_reparse_point(path: Path) -> bool:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ArtifactVerificationError(
            f"cannot inspect portable extraction path {path}: {exc}"
        ) from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = int(getattr(path_stat, "st_file_attributes", 0) or 0)
    return bool(stat.S_ISLNK(path_stat.st_mode) or file_attributes & reparse_flag)


def _assert_no_reparse_components(root: Path, *paths: Path) -> None:
    lexical_root = _lexical_absolute(root)
    for raw_path in (lexical_root, *paths):
        path = _lexical_absolute(raw_path)
        if not path.is_relative_to(lexical_root):
            raise ArtifactVerificationError(
                f"portable extraction path escapes canonical repository: {path}"
            )
        current = lexical_root
        components = (current,)
        relative = path.relative_to(lexical_root)
        if relative.parts:
            expanded = []
            for part in relative.parts:
                current = current / part
                expanded.append(current)
            components += tuple(expanded)
        for component in components:
            if _path_is_reparse_point(component):
                raise ArtifactVerificationError(
                    f"portable extraction reparse point is forbidden: {component}"
                )


def _remove_portable_tree(path: Path, *, root: Path, dist_root: Path) -> None:
    candidate = _lexical_absolute(path)
    if candidate.parent != dist_root or candidate == dist_root:
        raise ArtifactVerificationError(
            f"refusing to remove non-canonical portable extraction path: {candidate}"
        )
    _assert_no_reparse_components(root, dist_root, candidate)
    if os.path.lexists(candidate):
        if not candidate.is_dir():
            raise ArtifactVerificationError(
                f"portable extraction cleanup target is not a directory: {candidate}"
            )
        shutil.rmtree(candidate)


def _extract_portable_atomically(portable_zip: Path, *, root: Path) -> None:
    lexical_root = _lexical_absolute(root)
    dist_root = lexical_root / "dist"
    target = dist_root / "windows-portable"
    _assert_no_reparse_components(lexical_root, dist_root, target)
    dist_root.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_components(lexical_root, dist_root, target)
    nonce = uuid.uuid4().hex
    candidate = dist_root / f".windows-portable.{nonce}.candidate"
    backup = dist_root / f".windows-portable.{nonce}.backup"
    candidate.mkdir()
    _assert_no_reparse_components(
        lexical_root,
        dist_root,
        target,
        candidate,
        backup,
    )
    swapped = False
    try:
        seen: set[str] = set()
        with zipfile.ZipFile(portable_zip, "r") as archive:
            for info in archive.infolist():
                member = _safe_zip_member_path(info.filename)
                member_key = member.as_posix().casefold().rstrip("/")
                if member_key in seen:
                    raise ArtifactVerificationError(
                        f"duplicate portable ZIP member path: {member.as_posix()}"
                    )
                seen.add(member_key)
                unix_mode = (info.external_attr >> 16) & 0o170000
                dos_attributes = info.external_attr & 0xFFFF
                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                if stat.S_ISLNK(unix_mode) or dos_attributes & reparse_flag:
                    raise ArtifactVerificationError(
                        f"portable ZIP symlink/reparse entry is forbidden: "
                        f"{member.as_posix()}"
                    )
                destination = candidate.joinpath(*member.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
        missing = [name for name in REQUIRED_EXE_FILENAMES if not (candidate / name).is_file()]
        if missing:
            raise ArtifactVerificationError(
                "portable ZIP is missing required executables: " + ", ".join(missing)
            )
        _assert_no_reparse_components(
            lexical_root,
            dist_root,
            target,
            candidate,
            backup,
        )
        if os.path.lexists(target):
            target.rename(backup)
        try:
            _assert_no_reparse_components(
                lexical_root,
                dist_root,
                target,
                candidate,
                backup,
            )
            candidate.rename(target)
        except Exception:
            _assert_no_reparse_components(lexical_root, dist_root, target, backup)
            if os.path.lexists(backup) and not os.path.lexists(target):
                backup.rename(target)
            raise
        swapped = True
        if os.path.lexists(backup):
            try:
                _remove_portable_tree(
                    backup,
                    root=lexical_root,
                    dist_root=dist_root,
                )
            except OSError as exc:
                raise ArtifactVerificationError(
                    f"could not remove prior portable extraction backup: {backup}: {exc}"
                ) from exc
    except Exception:
        _assert_no_reparse_components(lexical_root, dist_root, target, backup)
        if (
            not swapped
            and not os.path.lexists(target)
            and os.path.lexists(backup)
        ):
            backup.rename(target)
        raise
    finally:
        if os.path.lexists(candidate):
            _remove_portable_tree(
                candidate,
                root=lexical_root,
                dist_root=dist_root,
            )
        if os.path.lexists(backup) and swapped:
            try:
                _remove_portable_tree(
                    backup,
                    root=lexical_root,
                    dist_root=dist_root,
                )
            except OSError:
                pass


def _run_candidate_smoke(portable_zip: Path, source_zip: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "smoke_portable_zip.py"),
            str(portable_zip),
            "--source-zip",
            str(source_zip),
        ],
        cwd=ROOT,
        check=True,
    )


def _attestation_source_ref(source: Mapping[str, Any]) -> str:
    workflow_ref = _require_string(
        source.get("workflow_ref"),
        label="candidate source workflow_ref",
    )
    prefix = f"{EXPECTED_SIGNER_WORKFLOW}@"
    if not workflow_ref.startswith(prefix):
        raise ArtifactVerificationError(
            "candidate workflow ref is not the release workflow"
        )
    source_ref = workflow_ref.removeprefix(prefix)
    if source_ref not in {"refs/heads/main", "refs/heads/master"}:
        raise ArtifactVerificationError(
            "candidate workflow ref is not an auto-release branch"
        )
    return source_ref


def _matching_attestation_identity(
    entry: object,
    *,
    source: Mapping[str, Any],
    source_ref: str,
    expected_subjects: Mapping[str, str],
) -> str | None:
    """Return a stable bundle identity only for one exact trusted run result."""

    if not isinstance(entry, Mapping):
        return None
    attestation = entry.get("attestation")
    verification_result = entry.get("verificationResult")
    if not isinstance(attestation, Mapping) or not isinstance(
        verification_result, Mapping
    ):
        return None
    signature = verification_result.get("signature")
    statement = verification_result.get("statement")
    if not isinstance(signature, Mapping) or not isinstance(statement, Mapping):
        return None
    certificate = signature.get("certificate")
    if not isinstance(certificate, Mapping):
        return None

    workflow_sha = str(source["workflow_sha"]).lower()
    candidate_head = str(source["head_sha"]).lower()
    workflow_uri = f"https://github.com/{EXPECTED_SIGNER_WORKFLOW}@{source_ref}"
    expected_certificate = {
        "githubWorkflowSHA": workflow_sha,
        "githubWorkflowRepository": EXPECTED_REPOSITORY,
        "githubWorkflowRef": source_ref,
        "githubWorkflowTrigger": source["event_name"],
        "buildSignerURI": workflow_uri,
        "buildSignerDigest": workflow_sha,
        "buildTrigger": source["event_name"],
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": f"https://github.com/{EXPECTED_REPOSITORY}",
        "sourceRepositoryDigest": candidate_head,
        "sourceRepositoryRef": source_ref,
        "runInvocationURI": (
            f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/"
            f"{source['run_id']}/attempts/{source['run_attempt']}"
        ),
    }
    if any(certificate.get(key) != value for key, value in expected_certificate.items()):
        return None
    if (
        "githubWorkflowName" in certificate
        and certificate.get("githubWorkflowName") != EXPECTED_WORKFLOW
    ):
        return None

    raw_subjects = statement.get("subject")
    if not isinstance(raw_subjects, list):
        return None
    subjects: dict[str, str] = {}
    for raw_subject in raw_subjects:
        if not isinstance(raw_subject, Mapping):
            return None
        name = raw_subject.get("name")
        digest = raw_subject.get("digest")
        if not isinstance(name, str) or not isinstance(digest, Mapping):
            return None
        sha256 = digest.get("sha256")
        if (
            not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or name in subjects
        ):
            return None
        subjects[name] = sha256
    if subjects != dict(expected_subjects):
        return None

    try:
        canonical_bundle = json.dumps(
            attestation,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical_bundle).hexdigest()


def _verify_github_attestation(
    artifact: Path,
    *,
    source: Mapping[str, Any],
    expected_subjects: Mapping[str, str],
) -> frozenset[str]:
    """Return exact matching GitHub attestation bundle identities for a subject."""

    candidate_head = _require_string(
        source.get("head_sha"),
        label="candidate source head_sha",
    ).lower()
    workflow_sha = _require_string(
        source.get("workflow_sha"),
        label="candidate source workflow_sha",
    ).lower()
    if re.fullmatch(r"[0-9a-f]{40}", candidate_head) is None:
        raise ArtifactVerificationError("candidate source head SHA is invalid")
    if re.fullmatch(r"[0-9a-f]{40}", workflow_sha) is None:
        raise ArtifactVerificationError("candidate workflow SHA is invalid")
    source_ref = _attestation_source_ref(source)
    artifact_digest = _sha256(Path(artifact))
    if artifact_digest not in expected_subjects.values():
        raise ArtifactVerificationError(
            f"attestation subject set does not contain {Path(artifact).name}"
        )

    command = [
        "gh",
        "attestation",
        "verify",
        str(Path(artifact).resolve()),
        "--repo",
        EXPECTED_REPOSITORY,
        "--signer-workflow",
        EXPECTED_SIGNER_WORKFLOW,
        "--signer-digest",
        workflow_sha,
        "--source-digest",
        candidate_head,
        "--source-ref",
        source_ref,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(
            "GitHub CLI is required for cryptographic artifact attestation verification"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = str(exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise ArtifactVerificationError(
            f"GitHub artifact attestation verification failed for "
            f"{Path(artifact).name}{suffix}"
        ) from exc

    results = _strict_json_loads(
        str(completed.stdout or ""),
        label=f"GitHub attestation verification for {Path(artifact).name}",
    )
    if not isinstance(results, list):
        raise ArtifactVerificationError(
            "GitHub attestation verification output must be a JSON array"
        )
    identities = frozenset(
        identity
        for entry in results
        if (
            identity := _matching_attestation_identity(
                entry,
                source=source,
                source_ref=source_ref,
                expected_subjects=expected_subjects,
            )
        )
    )
    if not identities:
        raise ArtifactVerificationError(
            f"no GitHub attestation for {Path(artifact).name} matches the exact "
            "workflow run, runner, source ref, and complete candidate subject set"
        )
    return identities


def _run_authenticated_gh(command: list[str], *, label: str) -> str:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(
            "GitHub CLI is required for hosted release-run verification"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = str(exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise ArtifactVerificationError(f"{label} failed{suffix}") from exc
    return str(completed.stdout or "")


def _verify_hosted_candidate_run(
    *,
    provenance: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
    provenance_path: Path,
) -> None:
    """Authenticate the asserted failed run and compare its retained bytes."""

    source = _require_exact_keys(
        provenance.get("source"),
        _SOURCE_KEYS,
        label="candidate source provenance",
    )
    run_id = _require_positive_int(
        source["run_id"],
        label="candidate run_id provenance",
    )
    run_attempt = _require_positive_int(
        source["run_attempt"],
        label="candidate run_attempt provenance",
    )
    candidate_head = _require_string(
        source["head_sha"],
        label="candidate source head_sha",
    ).lower()
    workflow_ref = _require_string(
        source["workflow_ref"],
        label="candidate source workflow_ref",
    )
    workflow_ref_prefix = f"{EXPECTED_SIGNER_WORKFLOW}@refs/heads/"
    if not workflow_ref.startswith(workflow_ref_prefix):
        raise ArtifactVerificationError(
            "candidate workflow ref is not a canonical branch workflow ref"
        )
    expected_branch = workflow_ref.removeprefix(workflow_ref_prefix)
    if expected_branch not in {"main", "master"}:
        raise ArtifactVerificationError(
            "candidate hosted run branch is not an auto-release branch"
        )

    run_endpoint = f"repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}"
    run_payload = _strict_json_loads(
        _run_authenticated_gh(
            ["gh", "api", run_endpoint],
            label="GitHub hosted run lookup",
        ),
        label="GitHub hosted run metadata",
    )
    run = _require_mapping(run_payload, label="GitHub hosted run metadata")
    repository = _require_mapping(
        run.get("repository"),
        label="GitHub hosted run repository",
    )
    head_repository = _require_mapping(
        run.get("head_repository"),
        label="GitHub hosted run head repository",
    )
    expected_run_fields = {
        "id": run_id,
        "run_attempt": run_attempt,
        "head_sha": candidate_head,
        "event": source["event_name"],
        "head_branch": expected_branch,
        "status": "completed",
        "conclusion": "failure",
    }
    for key, expected in expected_run_fields.items():
        if run.get(key) != expected:
            raise ArtifactVerificationError(
                f"GitHub hosted run {key} mismatch: expected {expected!r}, "
                f"got {run.get(key)!r}"
            )
    expected_workflow_paths = {
        EXPECTED_WORKFLOW_PATH,
        f"{EXPECTED_WORKFLOW_PATH}@{expected_branch}",
        f"{EXPECTED_WORKFLOW_PATH}@refs/heads/{expected_branch}",
    }
    if run.get("path") not in expected_workflow_paths:
        raise ArtifactVerificationError(
            "GitHub hosted run path mismatch: expected the auto-release workflow "
            f"on {expected_branch!r}, got {run.get('path')!r}"
        )
    if (
        repository.get("full_name") != EXPECTED_REPOSITORY
        or head_repository.get("full_name") != EXPECTED_REPOSITORY
    ):
        raise ArtifactVerificationError(
            "GitHub hosted run repository or head repository is invalid"
        )

    retained_name = f"failed-release-candidate-{run_id}-{run_attempt}"
    artifact_endpoint = (
        f"repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}/artifacts"
        f"?per_page=100&name={retained_name}"
    )
    artifact_payload = _strict_json_loads(
        _run_authenticated_gh(
            ["gh", "api", artifact_endpoint],
            label="GitHub retained candidate lookup",
        ),
        label="GitHub retained candidate metadata",
    )
    artifact_listing = _require_mapping(
        artifact_payload,
        label="GitHub retained candidate metadata",
    )
    artifacts = artifact_listing.get("artifacts")
    if not isinstance(artifacts, list):
        raise ArtifactVerificationError(
            "GitHub retained candidate artifact list is invalid"
        )
    matching = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, Mapping)
        and artifact.get("name") == retained_name
        and artifact.get("expired") is False
        and isinstance(artifact.get("id"), int)
        and not isinstance(artifact.get("id"), bool)
        and isinstance(artifact.get("workflow_run"), Mapping)
        and artifact["workflow_run"].get("id") == run_id
        and artifact["workflow_run"].get("head_sha") == candidate_head
    ]
    if len(matching) != 1:
        raise ArtifactVerificationError(
            "expected exactly one non-expired retained candidate artifact for "
            f"GitHub run {run_id}"
        )

    with tempfile.TemporaryDirectory(prefix="lc_attested_candidate_") as temp_name:
        download_root = Path(temp_name)
        _run_authenticated_gh(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--repo",
                EXPECTED_REPOSITORY,
                "--name",
                retained_name,
                "--dir",
                str(download_root),
            ],
            label="GitHub retained candidate download",
        )
        downloaded_dist = download_root / "dist"
        expected_files = {
            "source ZIP": (
                downloaded_dist / artifact_paths["source_zip"].name,
                Path(artifact_paths["source_zip"]),
            ),
            "portable ZIP": (
                downloaded_dist / artifact_paths["portable_zip"].name,
                Path(artifact_paths["portable_zip"]),
            ),
            "candidate provenance": (
                downloaded_dist / Path(provenance_path).name,
                Path(provenance_path),
            ),
        }
        _assert_no_reparse_components(
            download_root,
            downloaded_dist,
            *(downloaded for downloaded, _local in expected_files.values()),
        )
        for label, (downloaded, local) in expected_files.items():
            if not downloaded.is_file() or not local.is_file():
                raise ArtifactVerificationError(
                    f"retained {label} is missing from GitHub candidate artifact"
                )
            if (
                downloaded.stat().st_size != local.stat().st_size
                or _sha256(downloaded) != _sha256(local)
            ):
                raise ArtifactVerificationError(
                    f"retained {label} bytes differ from acceptance input"
                )


def _read_project_version(root: Path) -> str:
    source = (root / "pdf2dxf.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', source)
    if match is None:
        raise ArtifactVerificationError("cannot read project version from pdf2dxf.py")
    return match.group(1)


def _canonical_artifact_paths(root: Path, version: str) -> dict[str, Path]:
    portable_root = root / "dist" / "windows-portable"
    return {
        "source_zip": root / "dist" / f"LibreCAD-PDF-Importer_v{version}.zip",
        "portable_zip": (
            root
            / "dist"
            / f"LibreCAD-PDF-Importer-Windows-Portable_v{version}.zip"
        ),
        "pdf2dxf_exe": portable_root / "pdf2dxf.exe",
        "lcpdf_import_exe": portable_root / "lcpdf-import.exe",
        "lcpdf_batch_exe": portable_root / "lcpdf-batch.exe",
        "lcpdf_gui_exe": portable_root / "lcpdf-gui.exe",
    }


def _authenticate_candidate_provenance(
    *,
    provenance: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
    provenance_path: Path,
    attestation_verifier: Callable[..., frozenset[str]] | None = None,
    hosted_run_verifier: Callable[..., None] | None = None,
) -> dict[str, frozenset[str]]:
    verify_attestation = (
        _verify_github_attestation
        if attestation_verifier is None
        else attestation_verifier
    )
    candidate_subject_paths = [
        Path(artifact_paths["source_zip"]).resolve(),
        Path(artifact_paths["portable_zip"]).resolve(),
        Path(provenance_path).resolve(),
    ]
    expected_subjects = {path.name: _sha256(path) for path in candidate_subject_paths}
    if len(expected_subjects) != len(candidate_subject_paths):
        raise ArtifactVerificationError(
            "candidate attestation subject basenames are not unique"
        )
    source_provenance = _require_mapping(
        provenance.get("source"),
        label="candidate source provenance",
    )
    attestation_identities: list[frozenset[str]] = []
    verified_by_digest: dict[str, frozenset[str]] = {}
    for path in candidate_subject_paths:
        identities = frozenset(
            verify_attestation(
                path,
                source=source_provenance,
                expected_subjects=expected_subjects,
            )
        )
        if not identities or not all(
            isinstance(identity, str) and identity for identity in identities
        ):
            raise ArtifactVerificationError(
                f"candidate attestation verifier returned no bundle for {path.name}"
            )
        attestation_identities.append(identities)
        verified_by_digest[_sha256(path)] = identities
    if not set.intersection(*(set(identities) for identities in attestation_identities)):
        raise ArtifactVerificationError(
            "candidate ZIPs and provenance sidecar were not verified by the same "
            "GitHub attestation bundle"
        )

    verify_hosted_run = (
        _verify_hosted_candidate_run
        if hosted_run_verifier is None
        else hosted_run_verifier
    )
    verify_hosted_run(
        provenance=provenance,
        artifact_paths={
            "source_zip": candidate_subject_paths[0],
            "portable_zip": candidate_subject_paths[1],
        },
        provenance_path=candidate_subject_paths[2],
    )
    return verified_by_digest


def accept_release_artifacts(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    root: Path = ROOT,
    expected_version: str | None = None,
    provenance_path: Path | None = None,
    smoke_runner: Callable[[Path, Path], None] | None = None,
    attestation_verifier: Callable[..., frozenset[str]] | None = None,
    hosted_run_verifier: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Accept one provenance-bound hosted candidate from its exact Git head."""

    assert_release_interpreter()
    if provenance_path is None:
        raise ArtifactVerificationError("candidate provenance is required for acceptance")
    root = _lexical_absolute(Path(root))
    manifest_path = _lexical_absolute(Path(manifest_path))
    if not manifest_path.is_relative_to(root):
        raise ArtifactVerificationError(
            f"accepted artifact manifest escapes repository: {manifest_path}"
        )
    version = expected_version or _read_project_version(root)
    provenance_path = _lexical_absolute(Path(provenance_path))
    if not provenance_path.is_relative_to(root):
        raise ArtifactVerificationError(
            f"candidate provenance escapes repository: {provenance_path}"
        )
    provenance = _load_json_mapping(provenance_path, label="candidate provenance")
    if provenance_path.read_text(encoding="utf-8") != _canonical_candidate_provenance_text(
        provenance
    ):
        raise ArtifactVerificationError(
            "candidate provenance sidecar is not in the canonical attested encoding"
        )
    candidate_head = _validate_candidate_provenance(
        provenance,
        root=root,
        version=version,
        manifest_path=manifest_path,
    )
    _assert_clean_candidate_checkout(root, candidate_head)

    artifact_paths = _canonical_artifact_paths(root, version)
    verified_attestations = _authenticate_candidate_provenance(
        provenance=provenance,
        artifact_paths={
            "source_zip": artifact_paths["source_zip"].resolve(),
            "portable_zip": artifact_paths["portable_zip"].resolve(),
        },
        provenance_path=provenance_path,
        attestation_verifier=attestation_verifier,
        hosted_run_verifier=hosted_run_verifier,
    )
    smoke = _run_candidate_smoke if smoke_runner is None else smoke_runner
    smoke(artifact_paths["portable_zip"], artifact_paths["source_zip"])
    _extract_portable_atomically(
        artifact_paths["portable_zip"],
        root=root,
    )

    artifacts: dict[str, dict[str, Any]] = {}
    if set(artifact_paths) != set(REQUIRED_ARTIFACTS):
        raise ArtifactVerificationError("canonical release artifact set is incomplete")
    for name in REQUIRED_ARTIFACTS:
        path = artifact_paths[name].resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ArtifactVerificationError(f"{name} is missing: {path}")
        artifacts[name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }

    manifest: dict[str, Any] = {
        "schema": ACCEPTED_MANIFEST_SCHEMA,
        "version": version,
        "build_contract": _build_contract(root),
        "provenance": dict(provenance),
        "artifacts": artifacts,
    }
    candidate_path = root / "dist" / (
        f".{manifest_path.name}.{uuid.uuid4().hex}.candidate"
    )

    def previously_verified_attestation(
        path: Path,
        **_kwargs: object,
    ) -> frozenset[str]:
        identities = verified_attestations.get(_sha256(Path(path)))
        if not identities:
            raise ArtifactVerificationError(
                f"candidate bytes changed after attestation verification: {Path(path).name}"
            )
        return identities

    try:
        atomic_write_text(
            candidate_path,
            json.dumps(manifest, allow_nan=False, indent=2, sort_keys=True) + "\n",
        )
        verify_release_artifacts(
            manifest_path=candidate_path,
            root=root,
            expected_version=version,
            attestation_verifier=previously_verified_attestation,
            hosted_run_verifier=lambda **_kwargs: None,
        )
        candidate_path.replace(manifest_path)
    finally:
        candidate_path.unlink(missing_ok=True)
    return manifest


def verify_release_artifacts(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    root: Path = ROOT,
    expected_version: str | None = None,
    attestation_verifier: Callable[..., frozenset[str]] | None = None,
    hosted_run_verifier: Callable[..., None] | None = None,
) -> dict[str, dict[str, Any]]:
    root = Path(root).resolve()
    manifest_path = Path(manifest_path).resolve()
    manifest = _load_json_mapping(
        manifest_path,
        label="accepted artifact manifest",
    )
    schema = manifest.get("schema")
    if schema not in {LEGACY_MANIFEST_SCHEMA, ACCEPTED_MANIFEST_SCHEMA}:
        raise ArtifactVerificationError("accepted artifact manifest schema is invalid")
    manifest = _require_exact_keys(
        manifest,
        (
            _LEGACY_MANIFEST_KEYS
            if schema == LEGACY_MANIFEST_SCHEMA
            else _ACCEPTED_MANIFEST_KEYS
        ),
        label="accepted artifact manifest",
    )
    version = expected_version or _read_project_version(root)
    if manifest.get("version") != version:
        raise ArtifactVerificationError(
            f"accepted artifact version mismatch: expected {version}, got {manifest.get('version')}"
        )
    if schema == LEGACY_MANIFEST_SCHEMA and version != "1.0.77":
        raise ArtifactVerificationError(
            "legacy accepted artifact schema is supported only for v1.0.77 history"
        )
    provenance: Mapping[str, Any] | None = None
    if schema == ACCEPTED_MANIFEST_SCHEMA:
        provenance = manifest.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ArtifactVerificationError("accepted candidate provenance is missing")
        _validate_candidate_provenance(
            provenance,
            root=root,
            version=version,
            manifest_path=manifest_path,
        )

    contract = _validate_build_contract_shape(
        manifest["build_contract"],
        label="accepted build contract",
    )
    expected_contract = _build_contract(root)
    for key, expected in expected_contract.items():
        if contract.get(key) != expected:
            raise ArtifactVerificationError(
                f"accepted build contract mismatch for {key}: expected {expected}, got {contract.get(key)}"
            )
    artifact_contracts = _require_exact_keys(
        manifest["artifacts"],
        set(REQUIRED_ARTIFACTS),
        label="accepted artifact set",
    )
    verified = {}
    for name in REQUIRED_ARTIFACTS:
        expected = _validate_artifact_record(
            artifact_contracts[name],
            label=f"accepted {name}",
        )
        path = _confined(root, expected["path"])
        if not path.is_file():
            raise ArtifactVerificationError(f"{name} is missing: {path}")
        actual_hash = _sha256(path)
        actual_size = path.stat().st_size
        if (
            actual_hash != expected["sha256"]
            or actual_size != expected["size_bytes"]
        ):
            raise ArtifactVerificationError(
                f"{name} SHA-256/size mismatch: expected "
                f"{expected['sha256']}/{expected['size_bytes']}, "
                f"got {actual_hash}/{actual_size}"
            )
        verified[name] = {
            "path": str(path),
            "sha256": actual_hash,
            "size_bytes": actual_size,
        }
    if provenance is not None:
        with tempfile.TemporaryDirectory(
            prefix="lc_accepted_provenance_"
        ) as temp_name:
            reconstructed_sidecar = (
                Path(temp_name) / "release-candidate-provenance.json"
            )
            atomic_write_text(
                reconstructed_sidecar,
                _canonical_candidate_provenance_text(provenance),
            )
            _authenticate_candidate_provenance(
                provenance=provenance,
                artifact_paths={
                    "source_zip": Path(verified["source_zip"]["path"]),
                    "portable_zip": Path(verified["portable_zip"]["path"]),
                },
                provenance_path=reconstructed_sidecar,
                attestation_verifier=attestation_verifier,
                hosted_run_verifier=hosted_run_verifier,
            )
    return verified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--provenance",
        type=Path,
        help="machine-readable hosted candidate provenance used by --accept",
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="atomically accept an exact provenance-bound hosted candidate",
    )
    parser.add_argument(
        "--write-candidate-provenance",
        type=Path,
        help="write hosted run/runner/head and exact candidate ZIP hashes",
    )
    args = parser.parse_args(argv)
    if args.write_candidate_provenance is not None:
        if args.accept or args.provenance is not None:
            parser.error("--write-candidate-provenance cannot be combined with acceptance")
        written = write_candidate_provenance(
            output_path=args.write_candidate_provenance,
            root=ROOT,
        )
        print(
            json.dumps(
                {"status": "CANDIDATE_PROVENANCE_WRITTEN", "path": str(written)},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.accept:
        manifest = accept_release_artifacts(
            manifest_path=args.manifest,
            provenance_path=args.provenance,
            root=ROOT,
        )
        print(
            json.dumps(
                {
                    "status": "ACCEPTED",
                    "version": manifest["version"],
                    "manifest": str(args.manifest.resolve()),
                    "artifacts": manifest["artifacts"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    verified = verify_release_artifacts(manifest_path=args.manifest)
    print(json.dumps({"status": "PASS", "artifacts": verified}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

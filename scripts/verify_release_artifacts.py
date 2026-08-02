#!/usr/bin/env python3
"""Verify exact accepted release bytes before any GitHub publication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
import uuid


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


DEFAULT_MANIFEST = ROOT / ".release" / "accepted-artifacts.json"
REQUIRED_ARTIFACTS = (
    "source_zip",
    "portable_zip",
    "pdf2dxf_exe",
    "lcpdf_import_exe",
    "lcpdf_batch_exe",
    "lcpdf_gui_exe",
)


class ArtifactVerificationError(RuntimeError):
    """Accepted release manifest or artifact bytes are not exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _confined(root: Path, raw_path: object) -> Path:
    candidate = (root / str(raw_path)).resolve()
    if not candidate.is_relative_to(root):
        raise ArtifactVerificationError(f"artifact path escapes repository: {raw_path}")
    return candidate


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


def accept_release_artifacts(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    root: Path = ROOT,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Atomically record exact locally built bytes for deliberate acceptance."""

    assert_release_interpreter()
    root = Path(root).resolve()
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_relative_to(root):
        raise ArtifactVerificationError(
            f"accepted artifact manifest escapes repository: {manifest_path}"
        )
    version = expected_version or _read_project_version(root)
    release_lock = root / RELEASE_LOCK_FILENAME
    ci_lock = root / CI_LOCK_FILENAME
    if not release_lock.is_file():
        raise ArtifactVerificationError(
            f"release dependency lock is missing: {release_lock}"
        )
    if not ci_lock.is_file():
        raise ArtifactVerificationError(f"CI dependency lock is missing: {ci_lock}")

    artifacts: dict[str, dict[str, Any]] = {}
    artifact_paths = _canonical_artifact_paths(root, version)
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
        "schema": "bcs.release_artifacts/1.0",
        "version": version,
        "build_contract": {
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
        },
        "artifacts": artifacts,
    }
    candidate_path = manifest_path.with_name(
        f".{manifest_path.name}.{uuid.uuid4().hex}.candidate"
    )
    try:
        atomic_write_text(
            candidate_path,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        verify_release_artifacts(
            manifest_path=candidate_path,
            root=root,
            expected_version=version,
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
) -> dict[str, dict[str, Any]]:
    root = Path(root).resolve()
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest: Mapping[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactVerificationError(f"cannot read accepted artifact manifest: {exc}") from exc
    if manifest.get("schema") != "bcs.release_artifacts/1.0":
        raise ArtifactVerificationError("accepted artifact manifest schema is invalid")
    version = expected_version or _read_project_version(root)
    if manifest.get("version") != version:
        raise ArtifactVerificationError(
            f"accepted artifact version mismatch: expected {version}, got {manifest.get('version')}"
        )

    contract = manifest.get("build_contract", {})
    expected_contract = {
        "python": ".".join(map(str, EXPECTED_PYTHON_VERSION)),
        "architecture": EXPECTED_ARCHITECTURE,
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "pythonhashseed": PYTHONHASHSEED,
        "requirements_lock": RELEASE_LOCK_FILENAME,
        "ci_lock": CI_LOCK_FILENAME,
        "runner": RELEASE_RUNNER,
        "checkout_action": CHECKOUT_ACTION,
        "python_setup_action": SETUP_PYTHON_ACTION,
        "github_script_action": GITHUB_SCRIPT_ACTION,
    }
    for key, expected in expected_contract.items():
        if contract.get(key) != expected:
            raise ArtifactVerificationError(
                f"accepted build contract mismatch for {key}: expected {expected}, got {contract.get(key)}"
            )
    lock_path = _confined(root, contract["requirements_lock"])
    if not lock_path.is_file():
        raise ArtifactVerificationError(f"release dependency lock is missing: {lock_path}")
    actual_lock_hash = _sha256(lock_path)
    if contract.get("requirements_lock_sha256") != actual_lock_hash:
        raise ArtifactVerificationError("release dependency lock SHA-256 mismatch")
    ci_lock_path = _confined(root, contract["ci_lock"])
    if not ci_lock_path.is_file():
        raise ArtifactVerificationError(f"CI dependency lock is missing: {ci_lock_path}")
    actual_ci_lock_hash = _sha256(ci_lock_path)
    if contract.get("ci_lock_sha256") != actual_ci_lock_hash:
        raise ArtifactVerificationError("CI dependency lock SHA-256 mismatch")

    artifact_contracts = manifest.get("artifacts", {})
    if set(artifact_contracts) != set(REQUIRED_ARTIFACTS):
        raise ArtifactVerificationError(
            "accepted artifact set mismatch: "
            f"expected {sorted(REQUIRED_ARTIFACTS)}, got {sorted(artifact_contracts)}"
        )
    verified = {}
    for name in REQUIRED_ARTIFACTS:
        expected = artifact_contracts[name]
        path = _confined(root, expected.get("path"))
        if not path.is_file():
            raise ArtifactVerificationError(f"{name} is missing: {path}")
        actual_hash = _sha256(path)
        actual_size = path.stat().st_size
        if (
            actual_hash != expected.get("sha256")
            or actual_size != int(expected.get("size_bytes", -1))
        ):
            raise ArtifactVerificationError(
                f"{name} SHA-256/size mismatch: expected "
                f"{expected.get('sha256')}/{expected.get('size_bytes')}, "
                f"got {actual_hash}/{actual_size}"
            )
        verified[name] = {
            "path": str(path),
            "sha256": actual_hash,
            "size_bytes": actual_size,
        }
    return verified


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--accept",
        action="store_true",
        help="atomically accept the canonical locally built artifact set",
    )
    args = parser.parse_args(argv)
    if args.accept:
        manifest = accept_release_artifacts(manifest_path=args.manifest)
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

"""Fail-closed, reproducible Windows release build environment."""

from __future__ import annotations

import csv
import io
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping


EXPECTED_PYTHON_VERSION = (3, 12, 10)
EXPECTED_ARCHITECTURE = "AMD64"
SOURCE_DATE_EPOCH = "315532800"
PYTHONHASHSEED = "0"
RELEASE_LOCK_FILENAME = "requirements-release-win-py312.lock"
CI_LOCK_FILENAME = "requirements-ci-win-py312.lock"
RELEASE_RUNNER = "windows-2025"
CHECKOUT_ACTION = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
SETUP_PYTHON_ACTION = "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405"
GITHUB_SCRIPT_ACTION = (
    "actions/github-script@373c709c69115d41ff229c7e5df9f8788daa9553"
)
_LOCK_LINE = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^\s]+)\s+--hash=sha256:([0-9a-f]{64})$"
)


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def load_locked_versions(root: Path) -> dict[str, str]:
    lock_path = Path(root) / RELEASE_LOCK_FILENAME
    if not lock_path.is_file():
        raise RuntimeError(f"release dependency lock is missing: {lock_path}")
    locked: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        lock_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        if match is None:
            raise RuntimeError(
                f"invalid release lock line {line_number}: expected exact version and SHA-256"
            )
        name, version, _wheel_hash = match.groups()
        canonical = _canonical_distribution_name(name)
        if canonical in locked:
            raise RuntimeError(f"duplicate release dependency: {canonical}")
        locked[canonical] = version
    if not locked:
        raise RuntimeError(f"release dependency lock is empty: {lock_path}")
    return locked


def assert_release_interpreter() -> None:
    actual_version = tuple(sys.version_info[:3])
    if actual_version != EXPECTED_PYTHON_VERSION:
        raise RuntimeError(
            "release build requires exact Python "
            f"{'.'.join(map(str, EXPECTED_PYTHON_VERSION))}; got "
            f"{'.'.join(map(str, actual_version))}"
        )
    actual_architecture = platform.machine().upper()
    if actual_architecture != EXPECTED_ARCHITECTURE:
        raise RuntimeError(
            f"release build requires {EXPECTED_ARCHITECTURE}; got {actual_architecture}"
        )


def release_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONHASHSEED"] = PYTHONHASHSEED
    environment["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    return environment


def _freeze_versions(python_exe: Path, environment: Mapping[str, str]) -> dict[str, str]:
    output = subprocess.check_output(
        [str(python_exe), "-m", "pip", "freeze", "--all"],
        text=True,
        cwd=python_exe.parent,
        env=dict(environment),
    )
    frozen = {}
    for raw_line in output.splitlines():
        if "==" not in raw_line:
            raise RuntimeError(f"unexpected distribution in release environment: {raw_line}")
        name, version = raw_line.split("==", 1)
        frozen[_canonical_distribution_name(name)] = version
    return frozen


def normalize_release_metadata_records(python_exe: Path) -> dict[str, int]:
    """Remove venv-path-dependent launcher rows from installed wheel RECORDs.

    Pip-generated launchers embed the absolute venv interpreter path. Their
    hashes and sizes therefore vary with the checkout path, and PyInstaller
    collects those rows as package metadata even though it does not collect the
    launchers themselves. Runtime/package rows remain byte-for-byte intact.
    """

    venv_root = Path(python_exe).resolve().parent.parent
    site_packages = (venv_root / "Lib" / "site-packages").resolve()
    if site_packages.parent.parent != venv_root or not site_packages.is_dir():
        raise RuntimeError(f"release site-packages path is invalid: {site_packages}")

    records_changed = 0
    launcher_rows_removed = 0
    for record_path in sorted(
        site_packages.glob("*.dist-info/RECORD"),
        key=lambda path: path.as_posix().casefold(),
    ):
        if record_path.is_symlink() or not record_path.resolve().is_relative_to(
            site_packages
        ):
            raise RuntimeError(f"release metadata RECORD escapes venv: {record_path}")
        with record_path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        for row in rows:
            if len(row) != 3:
                raise RuntimeError(f"malformed release metadata RECORD: {record_path}")
        kept_rows = [
            row
            for row in rows
            if not row[0].replace("\\", "/").casefold().startswith("../../scripts/")
        ]
        removed = len(rows) - len(kept_rows)
        if not removed:
            continue

        payload = io.StringIO(newline="")
        csv.writer(payload, lineterminator="\n").writerows(kept_rows)
        temporary = record_path.with_name("RECORD.normalized.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                stream.write(payload.getvalue())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, record_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        records_changed += 1
        launcher_rows_removed += removed

    return {
        "records_changed": records_changed,
        "launcher_rows_removed": launcher_rows_removed,
    }


def create_release_venv(root: Path, venv_root: Path) -> Path:
    """Create a clean venv and install only the exact hash-locked wheels."""

    assert_release_interpreter()
    project_root = Path(root).resolve()
    build_root = (project_root / "build").resolve()
    target = Path(venv_root).resolve()
    if target.parent != build_root:
        raise RuntimeError(f"release venv must be directly below {build_root}: {target}")
    if target.exists():
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise RuntimeError(f"could not remove stale release venv: {target}: {exc}") from exc
    subprocess.run([sys.executable, "-m", "venv", str(target)], cwd=project_root, check=True)
    python_exe = target / "Scripts" / "python.exe"
    if not python_exe.is_file():
        raise RuntimeError(f"release venv did not create Python: {python_exe}")

    environment = release_environment()
    lock_path = project_root / RELEASE_LOCK_FILENAME
    locked_versions = load_locked_versions(project_root)
    subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(lock_path),
        ],
        cwd=project_root,
        check=True,
        env=environment,
    )
    subprocess.run(
        [str(python_exe), "-m", "pip", "check"],
        cwd=project_root,
        check=True,
        env=environment,
    )
    frozen_versions = _freeze_versions(python_exe, environment)
    if frozen_versions != locked_versions:
        raise RuntimeError(
            "release environment differs from the exact lock: "
            f"expected {locked_versions}, got {frozen_versions}"
        )
    normalization = normalize_release_metadata_records(python_exe)
    print(
        "Normalized release metadata RECORDs: "
        f"{normalization['records_changed']} files, "
        f"{normalization['launcher_rows_removed']} launcher rows"
    )
    return python_exe

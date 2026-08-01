"""Fail-closed, reproducible Windows release build environment."""

from __future__ import annotations

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
    return python_exe

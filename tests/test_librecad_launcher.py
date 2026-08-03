"""Safety and executable-resolution contracts for the LibreCAD launcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from librecad_pdf_importer.launchers import librecad_launcher


def _fake_executable(root: Path, name: str) -> Path:
    executable = root / name / "LibreCAD.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake LibreCAD executable\n")
    return executable


def test_explicit_librecad_executable_wins_when_multiple_installs_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = _fake_executable(tmp_path, "explicit")
    configured = _fake_executable(tmp_path, "configured")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(configured))

    assert librecad_launcher.find_librecad_executable(str(explicit)) == str(
        explicit.resolve()
    )


def test_portable_librecad_environment_executable_is_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portable = _fake_executable(tmp_path, "portable")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(portable))

    assert librecad_launcher.find_librecad_executable() == str(portable.resolve())


def test_missing_explicit_executable_does_not_fall_through_to_another_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _fake_executable(tmp_path, "configured")
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(configured))

    assert (
        librecad_launcher.find_librecad_executable(
            str(tmp_path / "missing" / "LibreCAD.exe")
        )
        is None
    )


def test_launch_never_terminates_existing_librecad_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = _fake_executable(tmp_path, "safe-launch")
    dxf_path = tmp_path / "drawing.dxf"
    dxf_path.write_text("0\nEOF\n", encoding="ascii")
    popen = Mock()
    monkeypatch.setattr(librecad_launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(
        librecad_launcher.subprocess,
        "run",
        Mock(side_effect=AssertionError("must not terminate existing LibreCAD")),
    )

    ok, message = librecad_launcher.launch_librecad(
        str(dxf_path),
        executable=str(executable),
    )

    assert ok is True
    assert str(executable.resolve()) in message
    popen.assert_called_once_with([str(executable.resolve()), str(dxf_path.resolve())])

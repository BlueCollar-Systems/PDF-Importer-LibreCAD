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


def test_ensure_librecad_menu_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from librecad_pdf_importer import librecad_plugin_install as installer

    documents = tmp_path / "Documents"
    legacy = tmp_path / "home" / ".librecad" / "plugins"
    ini_file = tmp_path / "appdata" / "LibreCAD" / "bc_pdf_importer_plugin.ini"
    monkeypatch.setattr(installer, "documents_directory", lambda: documents)
    monkeypatch.setattr(installer, "librecad_legacy_plugin_directories", lambda: [legacy])
    monkeypatch.setattr(installer, "plugin_settings_ini", lambda: ini_file)

    # Leftovers from the earlier two-name / three-folder installer.
    plugins = documents / "LibreCAD" / "plugins"
    for folder in (plugins, legacy):
        folder.mkdir(parents=True)
        (folder / "bc_lcpdf_menu1.dll").write_bytes(b"old")
    (legacy / "bc_lcpdf_menu.dll").write_bytes(b"old")
    ini_file.parent.mkdir(parents=True)
    ini_file.write_text(
        "[General]\nscript_path=C:/old/launch_lcpdf_gui.pyw\nother=1\n", encoding="utf-8"
    )

    fake_dll = tmp_path / "bc_lcpdf_menu.dll"
    fake_dll.write_bytes(b"dummy dll content")
    fake_script = tmp_path / "custom_launcher.pyw"
    fake_script.write_text("# launcher", encoding="utf-8")

    ok, message = librecad_launcher.ensure_librecad_menu_plugin(
        script_or_exe_path=str(fake_script),
        plugin_dll_path=str(fake_dll),
    )

    assert ok is True
    assert "LibreCAD menu plugin installed" in message
    # Exactly one plugin DLL anywhere LibreCAD scans: a second copy doubles
    # every menu entry.
    assert sorted(p.name for p in plugins.iterdir()) == [
        "bc_lcpdf_menu-importer.txt", "bc_lcpdf_menu.dll",
    ]
    assert list(legacy.iterdir()) == []
    assert (plugins / "bc_lcpdf_menu.dll").read_bytes() == b"dummy dll content"
    assert "custom_launcher.pyw" in (plugins / "bc_lcpdf_menu-importer.txt").read_text(
        encoding="utf-8"
    )
    # The stale Settings pin is dropped so the recorded launcher is used.
    assert ini_file.read_text(encoding="utf-8") == "[General]\nother=1\n"


def test_ensure_librecad_menu_plugin_reports_a_missing_dll(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from librecad_pdf_importer import librecad_plugin_install as installer

    monkeypatch.setattr(installer, "bundled_plugin_dll", lambda: None)
    monkeypatch.setattr(installer, "documents_directory", lambda: tmp_path)
    ok, message = librecad_launcher.ensure_librecad_menu_plugin()
    assert ok is False and "portable ZIP" in message


# --- "Locate LibreCAD..." choice: remembered per user, never breaks a run ---


def _no_automatic_librecad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every automatic lookup place at empty folders."""
    import librecad_runtime

    monkeypatch.delenv("BCS_LIBRECAD_EXECUTABLE", raising=False)
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        folder = tmp_path / ("empty-" + variable.replace("(", "").replace(")", ""))
        folder.mkdir(exist_ok=True)
        monkeypatch.setenv(variable, str(folder))
    monkeypatch.setattr(librecad_runtime.shutil, "which", lambda _name: None)


def test_saved_librecad_choice_round_trips_under_localappdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert librecad_launcher.load_saved_librecad_executable() is None
    assert librecad_launcher.save_librecad_executable("D:/Tools/LibreCAD/LibreCAD.exe")
    settings = (
        tmp_path / "local" / "BlueCollarSystems" / "LibreCAD-PDF-Importer" / "settings.json"
    )
    assert librecad_launcher.settings_path() == settings
    assert settings.is_file()
    assert (
        librecad_launcher.load_saved_librecad_executable()
        == "D:/Tools/LibreCAD/LibreCAD.exe"
    )
    # Written atomically: no temporary file is left next to it.
    assert sorted(p.name for p in settings.parent.iterdir()) == ["settings.json"]


@pytest.mark.parametrize(
    "content", ["{not json", "[1, 2]", '{"librecad_executable": 7}', ""],
)
def test_corrupt_settings_file_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    settings = librecad_launcher.settings_path()
    settings.parent.mkdir(parents=True)
    settings.write_text(content, encoding="utf-8")
    assert librecad_launcher.load_saved_librecad_executable() is None
    # Saving over a corrupt file repairs it.
    assert librecad_launcher.save_librecad_executable("C:/LC/LibreCAD.exe")
    assert librecad_launcher.load_saved_librecad_executable() == "C:/LC/LibreCAD.exe"


def test_unwritable_settings_never_raise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the settings folder should be", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    assert librecad_launcher.save_librecad_executable("C:/LC/LibreCAD.exe") is False
    assert librecad_launcher.load_saved_librecad_executable() is None


def test_saved_librecad_is_found_when_no_automatic_place_has_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_automatic_librecad(tmp_path, monkeypatch)
    assert librecad_launcher.find_librecad_executable() is None
    saved = _fake_executable(tmp_path, "unusual-place")
    assert librecad_launcher.save_librecad_executable(str(saved))

    preferred = librecad_launcher.preferred_librecad_executable()
    assert librecad_launcher.find_librecad_executable(preferred) == str(saved.resolve())

    popen = Mock()
    monkeypatch.setattr(librecad_launcher.subprocess, "Popen", popen)
    dxf_path = tmp_path / "EX101.dxf"
    dxf_path.write_text("0\nEOF\n", encoding="ascii")
    ok, _message = librecad_launcher.launch_librecad(str(dxf_path), executable=preferred)
    assert ok is True
    popen.assert_called_once_with([str(saved.resolve()), str(dxf_path.resolve())])


def test_environment_setting_still_wins_over_the_saved_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_automatic_librecad(tmp_path, monkeypatch)
    saved = _fake_executable(tmp_path, "saved")
    configured = _fake_executable(tmp_path, "configured")
    assert librecad_launcher.save_librecad_executable(str(saved))
    monkeypatch.setenv("BCS_LIBRECAD_EXECUTABLE", str(configured))

    preferred = librecad_launcher.preferred_librecad_executable(str(saved))
    assert preferred is None
    assert librecad_launcher.find_librecad_executable(preferred) == str(configured.resolve())


def test_stale_saved_choice_falls_back_to_the_normal_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_automatic_librecad(tmp_path, monkeypatch)
    assert librecad_launcher.save_librecad_executable(str(tmp_path / "gone" / "LibreCAD.exe"))
    assert librecad_launcher.preferred_librecad_executable() is None

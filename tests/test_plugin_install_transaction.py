"""Installer failures preserve the last usable plugin and launcher pair."""
from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from librecad_pdf_importer import librecad_plugin_install as installer


@pytest.fixture
def installation(tmp_path, monkeypatch):
    plugins = tmp_path / "documents" / "plugins"
    legacy = tmp_path / "legacy" / "plugins"
    program = tmp_path / "program" / "plugins"
    for folder in (plugins, legacy, program):
        folder.mkdir(parents=True)
    source = tmp_path / "new-plugin.bin"
    source.write_bytes(b"MZ new plugin")
    launcher = tmp_path / "new-importer.exe"
    launcher.write_bytes(b"MZ new importer")
    dll = plugins / installer.PLUGIN_DLL_NAME
    dll.write_bytes(b"MZ working plugin")
    sidecar = plugins / installer.SIDECAR_NAME
    sidecar.write_bytes(b"# Working importer\nC:/working/lcpdf-gui.exe\n")
    stale = [plugins / "bc_lcpdf_menu1.dll", legacy / installer.PLUGIN_DLL_NAME,
             legacy / "bc_lcpdf_menu1.dll", program / installer.PLUGIN_DLL_NAME]
    for path in stale:
        path.write_bytes(b"MZ old plugin")
    unknown = program / "stock-plugin.dll"
    unknown.write_bytes(b"MZ unrelated plugin")
    user_unknown = plugins / "other-plugin.dll"
    user_unknown.write_bytes(b"MZ unrelated user plugin")
    settings = tmp_path / "settings.ini"
    settings.write_bytes(b"[General]\r\nscript_path=C:/working/lcpdf-gui.exe\r\nkeep=1\r\n")
    monkeypatch.setattr(installer, "librecad_user_plugin_directory", lambda: plugins)
    monkeypatch.setattr(installer, "librecad_legacy_plugin_directories", lambda: [legacy])
    monkeypatch.setattr(installer, "librecad_program_plugin_directories", lambda: [program])
    monkeypatch.setattr(installer, "plugin_settings_ini", lambda: settings)
    files = [dll, sidecar, *stale, unknown, user_unknown, settings]
    return SimpleNamespace(source=source, launcher=launcher, plugins=plugins, dll=dll,
                           sidecar=sidecar, stale=stale, unknown=unknown, settings=settings,
                           before={path: path.read_bytes() for path in files}, root=tmp_path)


def install(state):
    return installer.install_librecad_plugin(state.source, launcher_path=state.launcher)


def assert_preserved(state):
    assert {path: path.read_bytes() for path in state.before} == state.before
    assert not list(state.root.rglob("*.partial"))


def test_sidecar_write_failure_preserves_working_installation(installation, monkeypatch):
    state = installation
    real_write = Path.write_text
    real_replace = installer.os.replace

    def denied(path, *args, **kwargs):
        if path == state.sidecar:
            raise PermissionError(errno.EACCES, "sidecar denied", str(path))
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", denied)

    def denied_replace(source, target):
        if Path(target) == state.sidecar:
            raise PermissionError(errno.EACCES, "sidecar denied", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(installer.os, "replace", denied_replace)
    with pytest.raises(installer.PluginInstallError, match="sidecar"):
        install(state)
    assert_preserved(state)


@pytest.mark.parametrize("target_name", ["dll", "sidecar", "settings"])
def test_commit_permission_failure_restores_every_known_file(
    installation, monkeypatch, target_name,
):
    state = installation
    target = getattr(state, target_name)
    real_replace = installer.os.replace

    def denied(source, destination):
        if Path(destination) == target:
            raise PermissionError(errno.EACCES, "destination denied", str(destination))
        return real_replace(source, destination)

    monkeypatch.setattr(installer.os, "replace", denied)
    with pytest.raises(installer.PluginInstallError, match="Close LibreCAD"):
        install(state)
    assert_preserved(state)
    # Clearing the fault makes exactly the same installation retryable.
    monkeypatch.setattr(installer.os, "replace", real_replace)
    result = install(state)
    assert result.dll_path.read_bytes() == state.source.read_bytes()
    assert str(state.launcher.resolve()) in result.sidecar_path.read_text(encoding="utf-8")
    assert not list(state.root.rglob("*.partial"))


def test_source_copy_failure_does_not_mutate_existing_files(installation, monkeypatch):
    state = installation
    real_read = Path.read_bytes

    def denied(path):
        if path == state.source:
            raise PermissionError(errno.EACCES, "source copy denied", str(path))
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(installer.PluginInstallError, match="source copy denied"):
        install(state)
    assert_preserved(state)


@pytest.mark.parametrize("partial_write", [False, True])
def test_staging_permission_or_disk_full_leaves_old_install_usable(
    installation, monkeypatch, partial_write,
):
    state = installation
    real_open = Path.open

    class DiskFullWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self.stream.__exit__(*exc)

        def write(self, contents):
            self.stream.write(contents[:2])
            self.stream.flush()
            raise OSError(errno.ENOSPC, "disk full after partial write")

    def failed_open(path, mode="r", *args, **kwargs):
        if mode == "xb":
            if partial_write:
                return DiskFullWriter(real_open(path, mode, *args, **kwargs))
            raise PermissionError(errno.EACCES, "staging denied", str(path))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failed_open)
    with pytest.raises(installer.PluginInstallError, match="free disk space"):
        install(state)
    assert_preserved(state)


def test_corrupt_staged_copy_is_rejected_before_live_changes(installation, monkeypatch):
    state = installation
    real_read = Path.read_bytes

    def corrupted(path):
        contents = real_read(path)
        if path.suffix == ".partial" and contents == state.source.read_bytes():
            return b"corrupt copy"
        return contents

    monkeypatch.setattr(Path, "read_bytes", corrupted)
    with pytest.raises(installer.PluginInstallError, match="staging readback"):
        install(state)
    assert_preserved(state)


def test_late_legacy_removal_failure_restores_prior_removed_copies(installation, monkeypatch):
    state = installation
    real_unlink = Path.unlink
    already_removed = []

    def denied(path, *args, **kwargs):
        if path == state.stale[2]:
            assert state.stale[0] in already_removed and state.stale[1] in already_removed
            raise PermissionError(errno.EACCES, "legacy copy in use", str(path))
        result = real_unlink(path, *args, **kwargs)
        if path in state.stale:
            already_removed.append(path)
        return result

    monkeypatch.setattr(Path, "unlink", denied)
    with pytest.raises(installer.PluginInstallError, match="legacy copy in use"):
        install(state)
    assert_preserved(state)


def test_program_copy_without_backup_permission_is_retained_and_reported(
    installation, monkeypatch,
):
    state = installation
    program_copy = state.stale[-1]
    real_open = Path.open

    def denied(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.parent == program_copy.parent:
            raise PermissionError(errno.EACCES, "program folder denied", str(path))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    result = install(state)
    assert result.blocked_stale == (program_copy,)
    assert program_copy not in result.removed_stale
    assert program_copy.read_bytes() == state.before[program_copy]
    assert state.unknown.read_bytes() == state.before[state.unknown]
    assert state.dll.read_bytes() == state.source.read_bytes()
    assert not list(state.root.rglob("*.partial"))


def test_failed_first_install_does_not_leave_an_unpaired_dll(installation, monkeypatch):
    state = installation
    for path in (state.dll, state.sidecar):
        path.unlink()
        del state.before[path]
    real_replace = installer.os.replace

    def denied(source, target):
        if Path(target) == state.sidecar:
            raise PermissionError(errno.EACCES, "sidecar denied", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(installer.os, "replace", denied)
    with pytest.raises(installer.PluginInstallError):
        install(state)
    assert not state.dll.exists() and not state.sidecar.exists()
    assert_preserved(state)


def test_rollback_failure_preserves_verified_recovery_bytes_and_primary_error(
    installation, monkeypatch,
):
    state = installation
    real_replace = installer.os.replace

    def denied(source, target):
        if Path(target) == state.sidecar:
            raise OSError(errno.ENOSPC, "primary sidecar failure", str(target))
        if Path(target) == state.dll and Path(source).read_bytes() == state.before[state.dll]:
            raise PermissionError(errno.EACCES, "rollback blocked", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(installer.os, "replace", denied)
    with pytest.raises(installer.PluginInstallError) as error:
        install(state)
    assert "primary sidecar failure" in str(error.value)
    assert "could not be restored" in str(error.value)
    assert "rollback blocked" in str(error.value)
    recovery = list(state.root.rglob("*.partial"))
    assert len(recovery) == 1 and recovery[0].read_bytes() == state.before[state.dll]
    assert str(recovery[0]) in str(error.value) and ".dll" not in recovery[0].name
    assert state.sidecar.read_bytes() == state.before[state.sidecar]
    assert all(path.read_bytes() == state.before[path] for path in state.stale)


def test_concurrent_change_is_not_overwritten_by_rollback(installation, monkeypatch):
    state = installation
    real_replace = installer.os.replace

    def changed(source, target):
        if Path(target) == state.sidecar:
            state.dll.write_bytes(b"a different installer now owns this file")
            raise PermissionError(errno.EACCES, "sidecar denied", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(installer.os, "replace", changed)
    with pytest.raises(installer.PluginInstallError, match="not overwritten"):
        install(state)
    assert state.dll.read_bytes() == b"a different installer now owns this file"
    recovery = list(state.root.rglob("*.partial"))
    assert len(recovery) == 1 and recovery[0].read_bytes() == state.before[state.dll]
    assert state.sidecar.read_bytes() == state.before[state.sidecar]


def test_staging_name_collision_never_deletes_a_foreign_file(installation, monkeypatch):
    state = installation
    monkeypatch.setattr(installer.uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    foreign = state.plugins / "bc_lcpdf_menu-collision.partial"
    foreign.write_bytes(b"another installation owns this file")
    with pytest.raises(installer.PluginInstallError):
        install(state)
    assert foreign.read_bytes() == b"another installation owns this file"
    assert {path: path.read_bytes() for path in state.before} == state.before
    assert list(state.root.rglob("*.partial")) == [foreign]


def test_gui_reports_transaction_failure_without_a_success_dialog(installation, monkeypatch):
    import gui

    state = installation
    monkeypatch.setattr(installer, "bundled_plugin_dll", lambda: state.source)
    monkeypatch.setattr(installer, "importer_launcher_path", lambda: state.launcher)
    real_replace = installer.os.replace

    def denied(source, target):
        if Path(target) == state.sidecar:
            raise PermissionError(errno.EACCES, "sidecar denied", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(installer.os, "replace", denied)
    with patch.object(gui.messagebox, "showerror") as error, patch.object(
        gui.messagebox, "showinfo",
    ) as info:
        gui.Pdf2DxfApp._install_librecad_menu(SimpleNamespace())
    info.assert_not_called()
    error.assert_called_once()
    assert "sidecar denied" in error.call_args.args[1]
    assert "previous menu files were kept or restored" in error.call_args.args[1]
    assert_preserved(state)


def test_cli_reports_actionable_failure_without_a_traceback(installation, monkeypatch, capsys):
    state = installation
    real_replace = installer.os.replace

    def denied(source, target):
        if Path(target) == state.sidecar:
            raise PermissionError(errno.EACCES, "sidecar denied", str(target))
        return real_replace(source, target)

    monkeypatch.setattr(installer.os, "replace", denied)
    result = installer.main([
        "--dll", str(state.source), "--launcher", str(state.launcher),
        "--plugin-dir", str(state.plugins),
    ])
    output = capsys.readouterr()
    assert result == 1 and "ERROR:" in output.err
    assert "sidecar denied" in output.err and "Close LibreCAD" in output.err
    assert "Traceback" not in output.err and "Installed LibreCAD menu plugin" not in output.out
    assert_preserved(state)

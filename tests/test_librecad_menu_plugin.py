"""LibreCAD "Plugins > Import PDF (BlueCollar)..." menu entry: handoff + install."""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from librecad_pdf_importer import librecad_handoff, librecad_plugin_install  # noqa: E402
from librecad_pdf_importer.librecad_handoff import (  # noqa: E402
    HANDOFF_FLAG,
    handoff_path_from_argv,
    write_handoff_result,
)
from librecad_pdf_importer.librecad_plugin_install import (  # noqa: E402
    PLUGIN_DLL_NAME,
    SIDECAR_NAME,
    PluginInstallError,
    install_librecad_plugin,
    uninstall_librecad_plugin,
)

PLUGIN_CPP = REPO_ROOT / "plugin" / "lcpdf_menu" / "lcpdf_menu.cpp"


@pytest.fixture(autouse=True)
def _isolate_user_folders(tmp_path, monkeypatch):
    """Never touch the real Documents, ~/.librecad or %APPDATA% from tests."""
    monkeypatch.setattr(librecad_plugin_install, "documents_directory",
                        lambda: tmp_path / "iso-documents")
    monkeypatch.setattr(librecad_plugin_install, "librecad_legacy_plugin_directories",
                        lambda: [tmp_path / "iso-home" / ".librecad" / "plugins"])
    monkeypatch.setattr(librecad_plugin_install, "plugin_settings_ini",
                        lambda: tmp_path / "iso-appdata" / "LibreCAD" / "bc_pdf_importer_plugin.ini")
PLUGIN_SDK = REPO_ROOT / "plugin" / "sdk"


# ---------------------------------------------------------------------------
# Handoff contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["--librecad-handoff", r"C:\Temp\h.json"], r"C:\Temp\h.json"),
        (["--librecad-handoff=C:/T/h.json"], "C:/T/h.json"),
        (["-x", "--librecad-handoff", "/tmp/a b.json", "y"], "/tmp/a b.json"),
        (["--librecad-handoff"], None),
        (["--librecad-handoff", "  "], None),
        (["--librecad-handoff="], None),
    ],
)
def test_handoff_path_is_parsed_from_argv(argv, expected):
    assert handoff_path_from_argv(argv) == expected


def test_ok_handoff_is_atomic_json_with_the_absolute_dxf_path(tmp_path):
    dxf = tmp_path / "drawing \u00e9.dxf"
    dxf.write_text("0\nEOF\n", encoding="ascii")
    target = tmp_path / "handoff.json"
    write_handoff_result(target, status="ok", output_path=dxf, degraded_text_items=2,
                         report_path="r.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == {
        "schema": 1, "status": "ok", "output_path": str(dxf.resolve()),
        "degraded_text_items": 2, "report_path": "r.json",
    }
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".partial"] == []


def test_closed_handoff_and_invalid_calls(tmp_path):
    target = tmp_path / "h.json"
    write_handoff_result(target, status="closed")
    assert json.loads(target.read_text(encoding="utf-8")) == {"schema": 1, "status": "closed"}
    with pytest.raises(ValueError):
        write_handoff_result(target, status="paused")
    with pytest.raises(ValueError):
        write_handoff_result(target, status="ok")


# ---------------------------------------------------------------------------
# The C++ plugin and the Python side must agree on the contract
# ---------------------------------------------------------------------------
def test_plugin_source_matches_python_contract():
    source = PLUGIN_CPP.read_text(encoding="utf-8")
    assert f'"{HANDOFF_FLAG}"' in source
    assert f'"{SIDECAR_NAME}"' in source
    # LibreCAD loads every plugins-folder file whose name contains ".dll".
    assert ".dll" not in SIDECAR_NAME
    for status in librecad_handoff.HANDOFF_STATUSES:
        assert f'status == "{status}"' in source
    assert '"output_path"' in source
    for entry in (
        "Import PDF (BlueCollar)...",
        "Import PDF into Current Drawing (BlueCollar)...",
        "PDF Importer Settings (BlueCollar)...",
    ):
        assert f'"{entry}"' in source
    # Same code path as File > Open inside LibreCAD.
    assert '"slotFileOpen(QString)"' in source
    assert "Qt::QueuedConnection" in source


def test_vendored_sdk_headers_are_librecad_2_2_1_interfaces():
    plugin_iface = (PLUGIN_SDK / "qc_plugininterface.h").read_text(encoding="utf-8")
    assert '#define LC_DocumentInterface_iid "org.librecad.PluginInterface/1.0"' in plugin_iface
    # LibreCAD 2.2.1.x PluginMenuLocation has exactly two members.
    location = plugin_iface.split("class PluginMenuLocation", 1)[1].split("};", 1)[0]
    assert re.findall(r"^\s*QString\s+(\w+);", location, re.MULTILINE) == [
        "menuEntryPoint", "menuEntryActionName",
    ]
    doc_iface = (PLUGIN_SDK / "document_interface.h").read_text(encoding="utf-8")
    assert "virtual QString addBlockfromFromdisk(QString fullName) = 0;" in doc_iface
    assert "virtual void addInsert(QString name, QPointF ins, QPointF scale, qreal rot) = 0;" in doc_iface


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------
def _fake_payload(tmp_path):
    dll = tmp_path / "src" / PLUGIN_DLL_NAME
    dll.parent.mkdir()
    dll.write_bytes(b"MZ fake plugin")
    launcher = tmp_path / "portable folder \u00e9" / "lcpdf-gui.exe"
    launcher.parent.mkdir()
    launcher.write_bytes(b"MZ fake gui")
    return dll, launcher


def test_install_copies_dll_and_records_the_launcher(tmp_path):
    dll, launcher = _fake_payload(tmp_path)
    plugins = tmp_path / "Documents" / "LibreCAD" / "plugins"
    result = install_librecad_plugin(dll, launcher_path=launcher, plugin_directory=plugins)
    assert result.dll_path == plugins / PLUGIN_DLL_NAME
    assert result.dll_path.read_bytes() == b"MZ fake plugin"
    assert not result.replaced_existing
    lines = result.sidecar_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#") and lines[1] == str(launcher.resolve())
    # Nothing but the plugin itself may carry ".dll" in the folder.
    assert [p.name for p in plugins.iterdir() if ".dll" in p.name.lower()] == [PLUGIN_DLL_NAME]
    again = install_librecad_plugin(dll, launcher_path=launcher, plugin_directory=plugins)
    assert again.replaced_existing
    assert sorted(p.name for p in uninstall_librecad_plugin(plugins)) == sorted(
        [PLUGIN_DLL_NAME, SIDECAR_NAME]
    )
    assert list(plugins.iterdir()) == []


def test_install_removes_duplicate_copies_and_a_stale_pin(tmp_path):
    dll, launcher = _fake_payload(tmp_path)
    plugins = tmp_path / "iso-documents" / "LibreCAD" / "plugins"
    legacy = tmp_path / "iso-home" / ".librecad" / "plugins"
    for folder in (plugins, legacy):
        folder.mkdir(parents=True)
        (folder / "bc_lcpdf_menu1.dll").write_bytes(b"old")
    (legacy / PLUGIN_DLL_NAME).write_bytes(b"old")
    (plugins / "other_plugin.dll").write_bytes(b"not ours")
    ini = tmp_path / "iso-appdata" / "LibreCAD" / "bc_pdf_importer_plugin.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[General]\npython_path=C:/py.exe\nscript_path=C:/x.pyw\nkeep=1\n",
                   encoding="utf-8")
    result = install_librecad_plugin(dll, launcher_path=launcher)
    assert result.dll_path == plugins / PLUGIN_DLL_NAME
    assert sorted(p.name for p in plugins.iterdir()) == sorted(
        [PLUGIN_DLL_NAME, SIDECAR_NAME, "other_plugin.dll"]
    )
    assert list(legacy.iterdir()) == []
    assert len(result.removed_stale) == 3 and result.cleared_pin
    assert ini.read_text(encoding="utf-8") == "[General]\nkeep=1\n"


def test_install_without_a_bundled_dll_explains_where_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setattr(librecad_plugin_install, "bundled_plugin_dll", lambda: None)
    with pytest.raises(PluginInstallError, match="portable ZIP"):
        install_librecad_plugin(plugin_directory=tmp_path)


def test_install_reports_a_locked_dll_as_close_librecad(tmp_path, monkeypatch):
    dll, launcher = _fake_payload(tmp_path)

    def locked(_src, _dst):
        raise PermissionError("in use")

    monkeypatch.setattr(librecad_plugin_install.os, "replace", locked)
    with pytest.raises(PluginInstallError, match="Close LibreCAD"):
        install_librecad_plugin(dll, launcher_path=launcher, plugin_directory=tmp_path / "p")
    assert [p.name for p in (tmp_path / "p").iterdir()] == []


def test_frozen_install_points_the_menu_at_lcpdf_gui(tmp_path, monkeypatch):
    portable = tmp_path / "portable"
    (portable / "librecad-plugin").mkdir(parents=True)
    (portable / "librecad-plugin" / PLUGIN_DLL_NAME).write_bytes(b"MZ")
    (portable / "lcpdf-gui.exe").write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(portable / "lcpdf-gui.exe"))
    assert librecad_plugin_install.bundled_plugin_dll() == (
        portable.resolve() / "librecad-plugin" / PLUGIN_DLL_NAME
    )
    assert librecad_plugin_install.importer_launcher_path() == portable.resolve() / "lcpdf-gui.exe"


def test_install_cli_reports_success_and_failure(tmp_path, capsys):
    dll, launcher = _fake_payload(tmp_path)
    code = librecad_plugin_install.main(
        ["--dll", str(dll), "--launcher", str(launcher), "--plugin-dir", str(tmp_path / "p")]
    )
    assert code == 0 and "Plugins > Import PDF (BlueCollar)..." in capsys.readouterr().out
    assert librecad_plugin_install.main(
        ["--dll", str(tmp_path / "missing.dll"), "--plugin-dir", str(tmp_path / "p")]
    ) == 1


# ---------------------------------------------------------------------------
# GUI handoff mode
# ---------------------------------------------------------------------------
def _gui_app(tmp_path, handoff_path, launch_librecad):
    gui = pytest.importorskip("gui")
    values = {
        "_var_scale": "1.0", "_var_import_text": True,
        "_var_text_mode": next(iter(gui.TEXT_MODES)), "_var_pages": "",
        "_var_dxf_ver": "R2010", "_var_launch_librecad": launch_librecad,
    }
    app = SimpleNamespace(
        **{key: Mock(get=Mock(return_value=value)) for key, value in values.items()},
        _cancel_event=gui.threading.Event(), _log=Mock(),
        after=lambda _ms, callback: callback(), _finish_conversion=Mock(),
        _handoff_path=handoff_path, _handoff_delivered=False,
    )
    return gui, app


def _run(gui, app, tmp_path, convert_result=None):
    output = tmp_path / "out.dxf"
    output.write_text("0\nEOF\n", encoding="ascii")
    with patch("dxf_import_engine.convert", return_value=convert_result or {}), patch(
        "pdf_open_guard.precheck_pdf",
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=None,
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.launch_librecad",
        return_value=(True, "launched"),
    ) as launch, patch.object(gui.messagebox, "showinfo") as info, patch.object(
        gui.messagebox, "showwarning",
    ), patch.object(gui.messagebox, "showerror") as error:
        gui.Pdf2DxfApp._run_conversion(
            app, str(tmp_path / "in.pdf"), str(output), gui.Pdf2DxfApp._capture_options(app),
        )
    return output, launch, info, error


def test_gui_hands_the_finished_dxf_to_librecad_and_never_starts_another(tmp_path):
    handoff = tmp_path / "handoff.json"
    gui, app = _gui_app(tmp_path, str(handoff), launch_librecad=True)
    output, launch, info, error = _run(gui, app, tmp_path)
    error.assert_not_called()
    info.assert_called_once()  # the operator still sees the Done summary
    launch.assert_not_called()
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["output_path"] == str(output.resolve())
    assert app._handoff_delivered is True


def test_gui_without_handoff_is_unchanged(tmp_path):
    gui, app = _gui_app(tmp_path, None, launch_librecad=True)
    _output, launch, info, error = _run(gui, app, tmp_path)
    error.assert_not_called()
    info.assert_called_once()
    launch.assert_called_once()
    assert app._handoff_delivered is False
    assert list(tmp_path.glob("*.json")) == []


def test_failed_conversion_hands_nothing_back(tmp_path):
    handoff = tmp_path / "handoff.json"
    gui, app = _gui_app(tmp_path, str(handoff), launch_librecad=False)
    with patch("dxf_import_engine.convert", side_effect=RuntimeError("boom")), patch(
        "pdf_open_guard.precheck_pdf",
    ), patch(
        "librecad_pdf_importer.launchers.librecad_launcher.find_librecad_executable",
        return_value=None,
    ), patch.object(gui.messagebox, "showerror") as error:
        gui.Pdf2DxfApp._run_conversion(
            app, str(tmp_path / "in.pdf"), str(tmp_path / "o.dxf"),
            gui.Pdf2DxfApp._capture_options(app),
        )
    error.assert_called_once()
    assert not handoff.exists() and app._handoff_delivered is False


def test_closing_the_handoff_window_releases_the_waiting_plugin(tmp_path):
    gui = pytest.importorskip("gui")
    handoff = tmp_path / "handoff.json"
    app = SimpleNamespace(_handoff_path=str(handoff), _handoff_delivered=False, destroy=Mock())
    gui.Pdf2DxfApp._close_from_librecad_handoff(app)
    assert json.loads(handoff.read_text(encoding="utf-8"))["status"] == "closed"
    app.destroy.assert_called_once()


def test_finish_closes_the_window_only_after_a_handoff(tmp_path):
    gui = pytest.importorskip("gui")
    for delivered in (False, True):
        app = SimpleNamespace(_btn_convert=Mock(), _btn_cancel=Mock(), _converting=True,
                              _handoff_delivered=delivered, destroy=Mock())
        gui.Pdf2DxfApp._finish_conversion(app)
        assert app.destroy.called is delivered


def test_every_gui_entry_point_forwards_the_handoff_flag(monkeypatch):
    gui = pytest.importorskip("gui")
    seen = []
    monkeypatch.setattr(gui, "launch_gui", lambda handoff_path=None: seen.append(handoff_path))
    import standalone_app

    monkeypatch.setattr(sys, "argv", ["lcpdf-gui.exe", HANDOFF_FLAG, "C:/T/h.json"])
    assert standalone_app.main() == 0
    assert seen == ["C:/T/h.json"]
    launcher = (REPO_ROOT / "launch_lcpdf_gui.pyw").read_text(encoding="utf-8")
    assert "launch_gui(handoff_path_from_argv(sys.argv[1:]))" in launcher
    gui_source = (REPO_ROOT / "gui.py").read_text(encoding="utf-8")
    assert "launch_gui(handoff_path_from_argv(sys.argv[1:]))" in gui_source


# ---------------------------------------------------------------------------
# Packaging checks
# ---------------------------------------------------------------------------
def _portable_zip(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


def test_portable_smoke_requires_a_real_librecad_plugin():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import smoke_portable_zip as smoke
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    good_dll = b"MZ" + b"\0" * 8 + b"".join(smoke.LIBRECAD_PLUGIN_MARKERS)
    members = {
        "librecad-plugin/bc_lcpdf_menu.dll": good_dll,
        "librecad-plugin/README.txt": b"r",
        "librecad-plugin/LICENSE.GPL-2.0.txt": b"l",
    }
    archive = _portable_zip(members)
    smoke._validate_librecad_plugin(set(members), archive)

    with pytest.raises(SystemExit, match="missing the LibreCAD menu plugin"):
        smoke._validate_librecad_plugin({"lcpdf-gui.exe"}, archive)
    bad = dict(members, **{"librecad-plugin/bc_lcpdf_menu.dll": b"MZ not a plugin"})
    with pytest.raises(SystemExit, match="not a LibreCAD Qt plugin"):
        smoke._validate_librecad_plugin(set(bad), _portable_zip(bad))
    stray = dict(members, **{"librecad-plugin/old.dll.bak": b"x"})
    with pytest.raises(SystemExit, match="Unexpected DLL-like"):
        smoke._validate_librecad_plugin(set(stray), _portable_zip(stray))


def test_plugin_import_policy_rejects_the_cpp_runtime(monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import build_librecad_plugin as builder
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    fine = ["Qt5Widgets.dll", "Qt5Core.dll", "KERNEL32.dll", "VCRUNTIME140.dll",
            "api-ms-win-crt-heap-l1-1-0.dll"]
    monkeypatch.setattr(builder, "pe_imports", lambda _p: fine)
    assert builder.check_imports(Path("x.dll")) == fine
    monkeypatch.setattr(builder, "pe_imports", lambda _p: fine + ["MSVCP140.dll"])
    with pytest.raises(builder.PluginBuildError, match="MSVCP140"):
        builder.check_imports(Path("x.dll"))

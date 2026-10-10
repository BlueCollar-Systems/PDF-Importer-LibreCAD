"""Locate and launch LibreCAD for generated DXF files."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import uuid
from typing import Optional, Tuple

from librecad_runtime import resolve_librecad_installation

# Per-user settings of the converter window ("Locate LibreCAD..." choice).
SETTINGS_FOLDER = ("BlueCollarSystems", "LibreCAD-PDF-Importer")
SETTINGS_FILE = "settings.json"
_LIBRECAD_EXECUTABLE_KEY = "librecad_executable"


def settings_path() -> Path:
    """``%LOCALAPPDATA%\\BlueCollarSystems\\LibreCAD-PDF-Importer\\settings.json``."""
    base = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
    if not base:
        base = str(Path.home() / ("AppData/Local" if os.name == "nt" else ".config"))
    return Path(base).joinpath(*SETTINGS_FOLDER, SETTINGS_FILE)


def _load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_saved_librecad_executable() -> Optional[str]:
    """The LibreCAD.exe the user picked with "Locate LibreCAD...", or None.

    A missing, unreadable or corrupt settings file never stops a run.
    """
    value = _load_settings().get(_LIBRECAD_EXECUTABLE_KEY)
    return value.strip() if isinstance(value, str) and value.strip() else None


def save_librecad_executable(executable: str) -> bool:
    """Remember *executable* for later runs; False when it could not be saved."""
    path = settings_path()
    settings = _load_settings()
    settings[_LIBRECAD_EXECUTABLE_KEY] = str(executable)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        return False
    return True


def preferred_librecad_executable(session_choice: Optional[str] = None) -> Optional[str]:
    """The LibreCAD.exe the window should use, or None for the normal lookup.

    ``BCS_LIBRECAD_EXECUTABLE`` always wins (None here lets the lookup read it).
    Otherwise a choice made in this window, then the remembered choice, as
    long as that file still exists; a stale choice falls back to the normal
    lookup instead of hiding an installed LibreCAD.
    """
    if str(os.environ.get("BCS_LIBRECAD_EXECUTABLE", "") or "").strip():
        return None
    for candidate in (session_choice, load_saved_librecad_executable()):
        if candidate and Path(candidate).expanduser().is_file():
            return str(candidate)
    return None


def find_librecad_executable(executable: Optional[str] = None) -> Optional[str]:
    installation = resolve_librecad_installation(executable)
    return installation.executable_path if installation is not None else None


def launch_librecad(dxf_path: str, executable: Optional[str] = None) -> Tuple[bool, str]:
    exe = find_librecad_executable(executable)
    if not exe:
        return False, "LibreCAD executable not found."

    dxf = str(Path(dxf_path).expanduser().resolve())

    try:
        subprocess.Popen([exe, dxf])
        return True, f"Launched LibreCAD: {exe}"
    except (OSError, ValueError) as exc:
        return False, f"Failed to launch LibreCAD: {exc}"


def ensure_librecad_menu_plugin(
    script_or_exe_path: Optional[str] = None,
    plugin_dll_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Install the LibreCAD ``Plugins > Import PDF (BlueCollar)...`` menu entry.

    Compatibility wrapper around
    :func:`librecad_pdf_importer.librecad_plugin_install.install_librecad_plugin`:
    one ``bc_lcpdf_menu.dll`` in ``Documents\\LibreCAD\\plugins`` (LibreCAD loads
    every ``*.dll`` there, so a second copy doubles every menu entry), legacy
    copies removed, and the launcher recorded for the plugin.
    """
    from librecad_pdf_importer.librecad_plugin_install import (
        PluginInstallError,
        install_librecad_plugin,
    )

    try:
        result = install_librecad_plugin(plugin_dll_path, launcher_path=script_or_exe_path)
    except PluginInstallError as exc:
        return False, str(exc)
    return True, (
        f"LibreCAD menu plugin installed: {result.dll_path} "
        f"(starts {result.launcher_path})."
    )

"""Locate and launch LibreCAD for generated DXF files."""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Optional, Tuple

from librecad_runtime import resolve_librecad_installation


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

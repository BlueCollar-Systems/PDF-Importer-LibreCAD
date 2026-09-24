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
    """Ensure LibreCAD plugin DLL and launcher configuration are installed.

    Installs the native LibreCAD menu plugin (bc_lcpdf_menu1.dll) to LibreCAD's
    standard plugin directories and updates %APPDATA%/LibreCAD/bc_pdf_importer_plugin.ini
    so that LibreCAD's 'Plugins' and 'Tools' menus can launch the importer directly.
    """
    import configparser
    import os
    import shutil
    import sys

    repo_or_app_root = Path(__file__).resolve().parents[2]

    # Resolve launcher target
    if script_or_exe_path is None:
        if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
            resolved_target = Path(sys.executable)
        else:
            launcher_pyw = repo_or_app_root / "launch_lcpdf_gui.pyw"
            gui_py = repo_or_app_root / "gui.py"
            if launcher_pyw.exists():
                resolved_target = launcher_pyw
            elif gui_py.exists():
                resolved_target = gui_py
            else:
                resolved_target = Path(sys.executable)
    else:
        resolved_target = Path(script_or_exe_path).resolve()

    # Configure INI file for LibreCAD plugin
    appdata = os.environ.get("APPDATA")
    if appdata:
        ini_dir = Path(appdata) / "LibreCAD"
    else:
        ini_dir = Path.home() / "AppData" / "Roaming" / "LibreCAD"

    ini_dir.mkdir(parents=True, exist_ok=True)
    ini_path = ini_dir / "bc_pdf_importer_plugin.ini"

    config = configparser.ConfigParser()
    if ini_path.exists():
        try:
            config.read(str(ini_path), encoding="utf-8")
        except Exception:
            pass
    if not config.has_section("General"):
        config.add_section("General")
    config.set("General", "script_path", str(resolved_target).replace("\\", "/"))
    try:
        with open(ini_path, "w", encoding="utf-8") as f:
            config.write(f)
    except Exception:
        pass

    # Locate source plugin DLL
    candidate_dll_locations = []
    if plugin_dll_path:
        candidate_dll_locations.append(Path(plugin_dll_path))
    candidate_dll_locations.extend([
        repo_or_app_root / "plugin" / "lcpdf_menu" / "release" / "bc_lcpdf_menu1.dll",
        repo_or_app_root / "plugin" / "bc_lcpdf_menu1.dll",
        repo_or_app_root / "bc_lcpdf_menu1.dll",
    ])

    source_dll: Optional[Path] = None
    for cand in candidate_dll_locations:
        if cand.exists():
            source_dll = cand
            break

    target_dirs = [
        Path.home() / "Documents" / "LibreCAD" / "plugins",
        Path.home() / "Documents" / "librecad" / "plugins",
        Path.home() / ".librecad" / "plugins",
    ]

    installed_count = 0
    if source_dll and source_dll.exists():
        for tdir in target_dirs:
            try:
                tdir.mkdir(parents=True, exist_ok=True)
                for dll_name in ("bc_lcpdf_menu1.dll", "bc_lcpdf_menu.dll"):
                    dst = tdir / dll_name
                    shutil.copy2(source_dll, dst)
                installed_count += 1
            except Exception:
                pass

    if installed_count > 0:
        return True, f"LibreCAD plugin installed to {installed_count} directories and configured in {ini_path}."
    return True, f"LibreCAD plugin launcher path configured in {ini_path}."


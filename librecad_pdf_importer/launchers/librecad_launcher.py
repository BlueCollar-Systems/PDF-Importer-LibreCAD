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

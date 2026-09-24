# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 BlueCollar-Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""Install the LibreCAD ``Plugins > Import PDF (BlueCollar)...`` menu entry.

Copies ``bc_lcpdf_menu.dll`` (shipped in the Windows portable ZIP under
``librecad-plugin/``) into LibreCAD's per-user plugin folder
``Documents\\LibreCAD\\plugins`` -- a folder LibreCAD 2.2.x always scans, so
no administrator rights are needed -- and records which importer the menu
entry should start in ``bc_lcpdf_menu-importer.txt`` beside it.

Usage (source checkout)::

    python -m librecad_pdf_importer.librecad_plugin_install [--dll PATH]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

PLUGIN_DLL_NAME = "bc_lcpdf_menu.dll"
PLUGIN_BUNDLE_DIR = "librecad-plugin"
# Must not contain ".dll": LibreCAD tries to load every such file in the folder.
SIDECAR_NAME = "bc_lcpdf_menu-importer.txt"
TARGET_LIBRECAD = "LibreCAD 2.2.x for Windows (Qt 5.15, 64-bit)"
# Earlier builds were installed as bc_lcpdf_menu1.dll (qmake VERSION suffix)
# and also copied to ~/.librecad/plugins. LibreCAD loads every "*.dll" in every
# plugin folder it scans, so any leftover copy with another name doubles each
# menu entry. The installer removes these (they are only ever ours).
LEGACY_DLL_NAMES = ("bc_lcpdf_menu1.dll",)
SETTINGS_INI_NAME = "bc_pdf_importer_plugin.ini"
PINNED_SETTING_KEYS = ("script_path", "python_path")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PluginInstallError(RuntimeError):
    """The menu entry could not be installed; the message says why."""


@dataclass(frozen=True)
class PluginInstallResult:
    dll_path: Path
    sidecar_path: Path
    launcher_path: Path
    replaced_existing: bool
    removed_stale: tuple[Path, ...] = ()
    cleared_pin: bool = False


def documents_directory() -> Path:
    """The folder Qt reports as DocumentsLocation (honours OneDrive redirection)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            folder_id = _GUID(
                0xFDD39AD0, 0x238F, 0x46AF,
                (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
            )
            path_pointer = ctypes.c_wchar_p()
            shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
            ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
            result = shell32.SHGetKnownFolderPath(
                ctypes.byref(folder_id), 0, None, ctypes.byref(path_pointer)
            )
            try:
                if result == 0 and path_pointer.value:
                    return Path(path_pointer.value)
            finally:
                ole32.CoTaskMemFree(path_pointer)
        except (OSError, AttributeError, ValueError):
            pass
    return Path.home() / "Documents"


def librecad_user_plugin_directory() -> Path:
    return documents_directory() / "LibreCAD" / "plugins"


def librecad_legacy_plugin_directories() -> list[Path]:
    """Other per-user folders LibreCAD 2.2.x scans for plugins."""
    return [Path.home() / ".librecad" / "plugins"]


def plugin_settings_ini() -> Path:
    """QSettings(IniFormat, UserScope, "LibreCAD", "bc_pdf_importer_plugin")."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "LibreCAD" / SETTINGS_INI_NAME


def _remove_stale_copies(target_dir: Path, keep: Path) -> list[Path]:
    removed = []
    candidates = [target_dir / name for name in LEGACY_DLL_NAMES]
    for folder in librecad_legacy_plugin_directories():
        candidates += [folder / PLUGIN_DLL_NAME] + [folder / name for name in LEGACY_DLL_NAMES]
    for path in candidates:
        try:
            if path.exists() and path.resolve() != keep.resolve():
                path.unlink()
                removed.append(path)
        except PermissionError as exc:
            raise PluginInstallError(
                f"LibreCAD is using an old copy of the menu plugin ({path}). "
                "Close LibreCAD and try again."
            ) from exc
        except OSError:
            pass
    return removed


def _clear_pinned_launcher(ini_path: Path) -> bool:
    """Drop a Settings pin so the plugin follows this install's sidecar."""
    if not ini_path.is_file():
        return False
    try:
        lines = ini_path.read_text(encoding="utf-8", errors="surrogateescape").splitlines(True)
    except OSError:
        return False
    kept = [
        line for line in lines
        if line.split("=", 1)[0].strip() not in PINNED_SETTING_KEYS
    ]
    if kept == lines:
        return False
    try:
        ini_path.write_text("".join(kept), encoding="utf-8", errors="surrogateescape")
    except OSError:
        return False
    return True


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_plugin_dll() -> Path | None:
    """Find the plugin DLL shipped with this importer, if any."""
    roots = []
    if _is_frozen():
        roots.append(Path(sys.executable).resolve().parent)
    roots.extend([_PROJECT_ROOT, _PROJECT_ROOT / "build"])
    for root in roots:
        for candidate in (root / PLUGIN_BUNDLE_DIR / PLUGIN_DLL_NAME, root / PLUGIN_DLL_NAME):
            if candidate.is_file():
                return candidate
    return None


def importer_launcher_path() -> Path:
    """The program the LibreCAD menu entry should start."""
    if _is_frozen():
        executable = Path(sys.executable).resolve()
        sibling_gui = executable.parent / "lcpdf-gui.exe"
        return sibling_gui if sibling_gui.is_file() else executable
    return _PROJECT_ROOT / "launch_lcpdf_gui.pyw"


def install_librecad_plugin(
    dll_path: str | os.PathLike[str] | None = None,
    *,
    launcher_path: str | os.PathLike[str] | None = None,
    plugin_directory: str | os.PathLike[str] | None = None,
    settings_ini: str | os.PathLike[str] | None = None,
) -> PluginInstallResult:
    """Copy the plugin DLL into LibreCAD's user plugin folder and record the launcher."""
    source = Path(dll_path) if dll_path else bundled_plugin_dll()
    if source is None or not source.is_file():
        raise PluginInstallError(
            f"The LibreCAD plugin ({PLUGIN_DLL_NAME}) is not in this copy of the importer. "
            f"Use the Windows portable ZIP, which ships it in '{PLUGIN_BUNDLE_DIR}\\'."
        )
    launcher = Path(launcher_path) if launcher_path else importer_launcher_path()
    if not launcher.is_file():
        raise PluginInstallError(f"Importer launcher not found: {launcher}")
    target_dir = Path(plugin_directory) if plugin_directory else librecad_user_plugin_directory()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PluginInstallError(f"Cannot create {target_dir}: {exc}") from exc

    target = target_dir / PLUGIN_DLL_NAME
    replaced = target.exists()
    # Staging name deliberately lacks ".dll" so LibreCAD never loads a leftover.
    staging = target_dir / f"bc_lcpdf_menu-{uuid.uuid4().hex}.partial"
    try:
        staging.write_bytes(source.read_bytes())
        os.replace(staging, target)
    except PermissionError as exc:
        raise PluginInstallError(
            "LibreCAD is using the current menu plugin. Close LibreCAD and try again."
        ) from exc
    except OSError as exc:
        raise PluginInstallError(f"Cannot install {target}: {exc}") from exc
    finally:
        if staging.exists():
            try:
                staging.unlink()
            except OSError:
                pass

    removed = _remove_stale_copies(target_dir, target)
    sidecar = target_dir / SIDECAR_NAME
    sidecar.write_text(
        "# Written by the BlueCollar PDF Importer. The LibreCAD menu entry starts:\n"
        f"{launcher.resolve()}\n",
        encoding="utf-8",
    )
    cleared = _clear_pinned_launcher(Path(settings_ini) if settings_ini else plugin_settings_ini())
    return PluginInstallResult(
        dll_path=target,
        sidecar_path=sidecar,
        launcher_path=launcher.resolve(),
        replaced_existing=replaced,
        removed_stale=tuple(removed),
        cleared_pin=cleared,
    )


def uninstall_librecad_plugin(plugin_directory: str | os.PathLike[str] | None = None) -> list[Path]:
    """Remove the plugin DLL and sidecar; returns the files removed."""
    target_dir = Path(plugin_directory) if plugin_directory else librecad_user_plugin_directory()
    removed = []
    paths = [target_dir / name for name in (PLUGIN_DLL_NAME, SIDECAR_NAME, *LEGACY_DLL_NAMES)]
    for folder in librecad_legacy_plugin_directories():
        paths += [folder / PLUGIN_DLL_NAME] + [folder / name for name in LEGACY_DLL_NAMES]
    for path in paths:
        if path.exists():
            try:
                path.unlink()
            except PermissionError as exc:
                raise PluginInstallError(
                    "LibreCAD is using the menu plugin. Close LibreCAD and try again."
                ) from exc
            removed.append(path)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dll", help=f"path to {PLUGIN_DLL_NAME} (default: bundled copy)")
    parser.add_argument("--launcher", help="importer GUI the menu entry starts")
    parser.add_argument("--plugin-dir", help="LibreCAD plugin folder (default: Documents\\LibreCAD\\plugins)")
    parser.add_argument("--uninstall", action="store_true", help="remove the menu entry")
    args = parser.parse_args(argv)
    try:
        if args.uninstall:
            removed = uninstall_librecad_plugin(args.plugin_dir)
            print("Removed: " + (", ".join(str(p) for p in removed) or "nothing installed"))
            return 0
        result = install_librecad_plugin(
            args.dll, launcher_path=args.launcher, plugin_directory=args.plugin_dir
        )
    except PluginInstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Installed LibreCAD menu plugin: {result.dll_path}")
    print(f"Menu entry starts: {result.launcher_path}")
    print("Restart LibreCAD, then use Plugins > Import PDF (BlueCollar)...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

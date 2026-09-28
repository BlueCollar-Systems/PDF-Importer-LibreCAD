#!/usr/bin/env python3
"""Build (and optionally smoke-test) the LibreCAD ``Import PDF (BlueCollar)`` plugin.

The plugin must match the target LibreCAD's Qt kit: LibreCAD 2.2.1.x for
Windows ships Qt 5.15.2 built with MSVC (x64, release), so the DLL is built
with Qt 5.15.2 ``msvc2019_64`` and the MSVC toolchain from ``vcvars64.bat``.

Output: ``build/librecad-plugin/bc_lcpdf_menu.dll``

Qt kit lookup order: ``--qt-root``, ``$LCPDF_QT_ROOT``, ``$QT_ROOT_DIR`` (set by
install-qt-action), ``C:\\Qt\\5.15.2\\msvc2019_64``.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SRC = ROOT / "plugin"
BUILD_ROOT = ROOT / "build" / "librecad-plugin-build"
OUTPUT_DIR = ROOT / "build" / "librecad-plugin"
DLL_NAME = "bc_lcpdf_menu.dll"
REQUIRED_QT_PREFIX = "5.15."
DEFAULT_QT_ROOT = Path(r"C:\Qt\5.15.2\msvc2019_64")
# Runtime DLLs the plugin may import. LibreCAD's installer ships its own
# (possibly older) VC++ redistributable, so the C++ standard library DLL
# (MSVCP140*.dll) is deliberately NOT allowed: the plugin must only need the
# C runtime that every VC++ 2015+ redistributable provides.
ALLOWED_IMPORT_PREFIXES = (
    "qt5core.dll",
    "qt5gui.dll",
    "qt5widgets.dll",
    "kernel32.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "api-ms-win-crt-",
)


class PluginBuildError(RuntimeError):
    pass


def find_qt_root(explicit: str | None = None) -> Path | None:
    candidates = [explicit, os.environ.get("LCPDF_QT_ROOT"), os.environ.get("QT_ROOT_DIR")]
    for raw in candidates:
        if raw and (Path(raw) / "bin" / "qmake.exe").is_file():
            return Path(raw)
    if (DEFAULT_QT_ROOT / "bin" / "qmake.exe").is_file():
        return DEFAULT_QT_ROOT
    return None


def find_vcvars64() -> Path | None:
    explicit = os.environ.get("LCPDF_VCVARS64")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(program_files_x86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        output = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-requires",
             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            capture_output=True, text=True, check=True,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in output:
        candidate = Path(line.strip()) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if candidate.is_file():
            return candidate
    return None


def qt_version(qt_root: Path) -> str:
    return subprocess.run(
        [str(qt_root / "bin" / "qmake.exe"), "-query", "QT_VERSION"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _run_msvc(vcvars: Path, commands: list[str], cwd: Path) -> None:
    script = cwd / "_build.cmd"
    script.write_text(
        "@echo off\r\n"
        f'call "{vcvars}" >nul || exit /b 1\r\n'
        + "".join(f"{command} || exit /b 1\r\n" for command in commands),
        encoding="utf-8",
    )
    subprocess.run(["cmd.exe", "/d", "/c", str(script)], cwd=cwd, check=True)


def _qmake_build(qt_root: Path, vcvars: Path, project: Path, build_dir: Path, out_dir: Path) -> None:
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    qmake = qt_root / "bin" / "qmake.exe"
    out_arg = out_dir.as_posix()
    _run_msvc(
        vcvars,
        [f'"{qmake}" "{project}" "BC_PLUGIN_OUT={out_arg}"', "nmake /nologo"],
        build_dir,
    )


def pe_imports(path: Path) -> list[str]:
    """Return the DLL names a PE32+ image imports (minimal parser, no deps)."""
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise PluginBuildError(f"{path} is not a PE image")
    number_of_sections = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    if struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise PluginBuildError(f"{path} is not a 64-bit (PE32+) image")
    import_rva = struct.unpack_from("<I", data, optional + 120)[0]
    sections = []
    table = optional + optional_size
    for index in range(number_of_sections):
        base = table + index * 40
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", data, base + 8)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer))

    def offset(rva: int) -> int:
        for virtual_address, size, raw_pointer in sections:
            if virtual_address <= rva < virtual_address + size:
                return rva - virtual_address + raw_pointer
        raise PluginBuildError(f"RVA {rva:#x} outside sections")

    names = []
    cursor = offset(import_rva)
    while True:
        name_rva = struct.unpack_from("<I", data, cursor + 12)[0]
        if name_rva == 0:
            break
        start = offset(name_rva)
        names.append(data[start:data.index(b"\0", start)].decode("ascii"))
        cursor += 20
    return names


def check_imports(dll: Path) -> list[str]:
    imports = pe_imports(dll)
    unexpected = [
        name for name in imports
        if not name.lower().startswith(ALLOWED_IMPORT_PREFIXES)
    ]
    if unexpected:
        raise PluginBuildError(
            f"{dll.name} imports DLLs LibreCAD does not guarantee: {', '.join(unexpected)}"
        )
    return imports


def build_plugin(qt_root: Path | None = None, *, output_dir: Path = OUTPUT_DIR) -> Path:
    if sys.platform != "win32":
        raise PluginBuildError("The LibreCAD Windows plugin can only be built on Windows.")
    qt_root = qt_root or find_qt_root()
    if qt_root is None:
        raise PluginBuildError(
            "Qt 5.15.2 msvc2019_64 kit not found (set LCPDF_QT_ROOT or QT_ROOT_DIR)."
        )
    version = qt_version(qt_root)
    if not version.startswith(REQUIRED_QT_PREFIX):
        raise PluginBuildError(f"Qt {version} at {qt_root}; LibreCAD 2.2.x needs Qt 5.15.")
    vcvars = find_vcvars64()
    if vcvars is None:
        raise PluginBuildError("MSVC vcvars64.bat not found (install VS C++ build tools).")
    print(f"LibreCAD plugin: Qt {version} at {qt_root}; MSVC env {vcvars}")
    _qmake_build(
        qt_root, vcvars, PLUGIN_SRC / "lcpdf_menu" / "lcpdf_menu.pro",
        BUILD_ROOT / "lcpdf_menu", output_dir,
    )
    dll = output_dir / DLL_NAME
    if not dll.is_file():
        raise PluginBuildError(f"Build finished but {dll} is missing")
    for leftover in output_dir.glob("bc_lcpdf_menu.*"):
        if leftover.suffix.lower() in {".exp", ".lib"}:
            leftover.unlink()
    imports = check_imports(dll)
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()
    print(f"Built {dll} ({dll.stat().st_size} bytes, sha256 {digest})")
    print("Imports: " + ", ".join(imports))
    return dll


def smoke_plugin(dll: Path, qt_root: Path | None = None, *, e2e: bool = True) -> None:
    """Load the DLL the way LibreCAD does and, optionally, run the full handoff."""
    qt_root = qt_root or find_qt_root()
    vcvars = find_vcvars64()
    if qt_root is None or vcvars is None:
        raise PluginBuildError("Qt kit / MSVC needed for the plugin smoke test")
    smoke_out = BUILD_ROOT / "smoke-out"
    _qmake_build(qt_root, vcvars, PLUGIN_SRC / "smoke" / "plugin_smoke.pro",
                 BUILD_ROOT / "smoke", smoke_out)
    harness = smoke_out / "plugin_smoke.exe"
    environment = dict(os.environ)
    environment["PATH"] = str(qt_root / "bin") + os.pathsep + environment.get("PATH", "")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["QT_PLUGIN_PATH"] = str(qt_root / "plugins")
    for key in ("BC_LC_IMPORTER_EXE", "BC_LC_IMPORTER_SCRIPT", "BC_LC_IMPORTER_PYTHON"):
        environment.pop(key, None)
    command = [str(harness), str(dll)]
    with tempfile.TemporaryDirectory(prefix="lcpdf_plugin_smoke_") as tmp:
        if e2e:
            dxf = Path(tmp).resolve() / "handoff sample \u00e9.dxf"
            dxf.write_text("0\nEOF\n", encoding="ascii")
            command += ["--e2e", sys.executable, str(PLUGIN_SRC / "smoke" / "fake_importer.py"), str(dxf)]
        result = subprocess.run(command, env=environment, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120)
    print(result.stdout.strip().encode("ascii", "backslashreplace").decode("ascii"))
    if result.returncode != 0 or "PLUGIN SMOKE OK" not in result.stdout:
        raise PluginBuildError(
            f"plugin smoke failed (exit {result.returncode}): {result.stderr.strip()}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--qt-root", help="Qt 5.15.x msvc2019_64 kit root")
    parser.add_argument("--smoke", action="store_true", help="load-test the built DLL")
    parser.add_argument("--no-e2e", action="store_true", help="skip the handoff round trip")
    parser.add_argument("--install", action="store_true",
                        help="install into Documents\\LibreCAD\\plugins after building")
    args = parser.parse_args(argv)
    try:
        qt_root = find_qt_root(args.qt_root)
        dll = build_plugin(qt_root)
        if args.smoke:
            smoke_plugin(dll, qt_root, e2e=not args.no_e2e)
        if args.install:
            sys.path.insert(0, str(ROOT))
            from librecad_pdf_importer.librecad_plugin_install import install_librecad_plugin

            result = install_librecad_plugin(dll)
            print(f"Installed {result.dll_path} -> starts {result.launcher_path}")
    except (PluginBuildError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

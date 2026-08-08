#!/usr/bin/env python3
"""Build self-contained Windows executables for the LibreCAD PDF importer."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

from deterministic_zip import write_deterministic_zip
from release_notices import copy_python_distribution_notices, copy_release_notices
from release_build_contract import create_release_venv, release_environment


ROOT = Path(__file__).resolve().parent
BUILD_ROOT = ROOT / "build" / "pyinstaller_entrypoints"
DIST_ROOT = ROOT / "dist" / "windows-portable"
VENV_ROOT = ROOT / "build" / "portable-build-venv"

ENTRYPOINTS = {
    "pdf2dxf": ("pdf2dxf", "main", "console"),
    "lcpdf-import": ("librecad_pdf_importer.cli", "main", "console"),
    "lcpdf-batch": ("librecad_pdf_importer.batch_cli", "main", "console"),
    "lcpdf-gui": ("standalone_app", "main", "windowed"),
}

HIDDEN_IMPORTS = [
    "pymupdf",
    "fitz",
    "ezdxf",
    "ezdxf.addons",
    "ezdxf.entities",
    "ezdxf.layouts",
    "ezdxf.math",
    "matplotlib",
    "tkinter",
]

COLLECT_ALL = ["fontTools"]
COPY_METADATA = ["fonttools"]

def read_version() -> str:
    text = (ROOT / "pdf2dxf.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise RuntimeError("Could not read __version__ from pdf2dxf.py")
    return match.group(1)


def write_entrypoint(name: str, module: str, function: str) -> Path:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    path = BUILD_ROOT / f"_entry_{name.replace('-', '_')}.py"
    path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import sys",
                f"from {module} import {function}",
                "",
                "if __name__ == '__main__':",
                f"    raise SystemExit({function}())",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def build_python() -> Path:
    return create_release_venv(ROOT, VENV_ROOT)


def run_pyinstaller(name: str, entrypoint: Path, mode: str, python_exe: Path) -> None:
    # Do not freeze pdf2dxf with the same internal name as pdf2dxf.py; PyInstaller
    # can shadow the real module and create a circular import in the executable.
    build_name = "lcpdf-pdf2dxf" if name == "pdf2dxf" else name
    cmd = [
        str(python_exe),
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        build_name,
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build" / "pyinstaller_specs"),
        "--paths",
        str(ROOT),
        # Start the frozen interpreter in UTF-8 mode. Without this, redirected
        # stdio inherits the locale codepage (cp1252 on US Windows) and a
        # diagnostic print of the user's own non-ASCII path raises
        # UnicodeEncodeError -- and the bootloader's isolated PyConfig means
        # PYTHONUTF8/PYTHONIOENCODING cannot supply it from outside the exe.
        # Pinned by tests/test_frozen_stdio_alphabet.py.
        "--python-option",
        "X utf8=1",
    ]
    if mode == "windowed":
        cmd.append("--windowed")
    for hidden in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", hidden])
    for package in COLLECT_ALL:
        cmd.extend(["--collect-all", package])
    for distribution in COPY_METADATA:
        cmd.extend(["--copy-metadata", distribution])
    cmd.append(str(entrypoint))
    print("Running:", " ".join(cmd))
    env = release_environment()
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)
    if build_name != name:
        built = DIST_ROOT / f"{build_name}.exe"
        target = DIST_ROOT / f"{name}.exe"
        if target.exists():
            target.unlink()
        built.rename(target)


def archive_portable(source_root: Path, archive_path: Path) -> Path:
    """Archive the portable payload without checkout/build timestamp drift."""

    files = [
        (path, path.relative_to(source_root).as_posix())
        for path in source_root.rglob("*")
        if path.is_file()
    ]
    return write_deterministic_zip(archive_path, files)


def build() -> Path:
    version = read_version()
    python_exe = build_python()
    if BUILD_ROOT.exists():
        shutil.rmtree(BUILD_ROOT)
    if DIST_ROOT.exists():
        shutil.rmtree(DIST_ROOT)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)

    for name, (module, function, mode) in ENTRYPOINTS.items():
        entrypoint = write_entrypoint(name, module, function)
        run_pyinstaller(name, entrypoint, mode, python_exe)

    copy_release_notices(ROOT, DIST_ROOT)
    copy_python_distribution_notices(
        python_exe.parent.parent / "Lib" / "site-packages",
        DIST_ROOT,
    )

    archive_path = (
        ROOT / "dist" / f"LibreCAD-PDF-Importer-Windows-Portable_v{version}.zip"
    )
    archive_portable(DIST_ROOT, archive_path)
    print(f"Portable app folder: {DIST_ROOT}")
    print(f"Portable zip: {archive_path}")
    return Path(archive_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

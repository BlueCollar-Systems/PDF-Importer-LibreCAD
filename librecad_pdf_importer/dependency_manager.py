# -*- coding: utf-8 -*-
# dependency_manager.py — PyMuPDF / ezdxf dependency management
# Copyright (c) 2024-2026 BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DOWNLOADS = {
    "pymupdf": "https://pypi.org/project/PyMuPDF/",
    "ezdxf": "https://pypi.org/project/ezdxf/",
}


def get_lib_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "lib"


def ensure_lib_path() -> None:
    lib_dir = str(get_lib_dir())
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)


def check_pymupdf() -> bool:
    ensure_lib_path()
    try:
        from pdfcadcore.fitz_loader import import_fitz

        import_fitz(prefer_lib_dir=str(get_lib_dir()))
        return True
    except ImportError:
        return False


def check_ezdxf() -> bool:
    ensure_lib_path()
    try:
        import ezdxf  # noqa: F401
        return True
    except ImportError:
        return False


def install_runtime_deps() -> bool:
    lib_dir = get_lib_dir()
    lib_dir.mkdir(parents=True, exist_ok=True)
    python_exe = sys.executable
    try:
        subprocess.check_call(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                "--target",
                str(lib_dir),
                "--upgrade",
                "PyMuPDF>=1.24,<2.0",
                "ezdxf",
            ],
            timeout=300,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        print(f"[LibreCAD PDF Importer] Dependency install failed: {exc}")
        return False

    ensure_lib_path()
    return check_pymupdf() and check_ezdxf()


def print_diagnostics() -> int:
    print("[LibreCAD PDF Importer] --- Dependency Diagnostics ---")
    print(f"Python: {sys.version}")
    print(f"Lib dir: {get_lib_dir()}")
    print(f"PyMuPDF: {'OK' if check_pymupdf() else 'MISSING'}")
    print(f"ezdxf: {'OK' if check_ezdxf() else 'MISSING'}")
    if not check_pymupdf() or not check_ezdxf():
        print("Install with:")
        print(f'  python -m pip install --target "{get_lib_dir()}" "PyMuPDF>=1.24,<2.0" ezdxf')
        print("Or run:")
        print("  python preflight_check.py --install")
        return 1
    print("[LibreCAD PDF Importer] --- End Diagnostics ---")
    return 0

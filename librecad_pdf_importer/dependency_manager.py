# -*- coding: utf-8 -*-
# dependency_manager.py — PyMuPDF / ezdxf / FontTools dependency management
# Copyright (c) 2024-2026 BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
import uuid

from runtime_requirements import load_runtime_requirements


PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def check_fonttools() -> bool:
    ensure_lib_path()
    try:
        from librecad_pdf_importer.runtime_self_test import (
            load_fonttools_dependencies,
        )

        load_fonttools_dependencies()
        return True
    except ImportError:
        return False


def install_runtime_deps() -> bool:
    lib_dir = get_lib_dir()
    parent = lib_dir.parent.resolve()
    stage_dir = parent / f"lib.stage.{uuid.uuid4().hex}"
    backup_dir = parent / f"lib.backup.{uuid.uuid4().hex}"
    for managed in (lib_dir, stage_dir, backup_dir):
        if managed.resolve().parent != parent:
            print(f"[LibreCAD PDF Importer] Refusing unsafe dependency path: {managed}")
            return False

    python_exe = sys.executable
    promoted = False
    try:
        stage_dir.mkdir(parents=False, exist_ok=False)
        subprocess.check_call(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                "--target",
                str(stage_dir),
                "--upgrade",
                *load_runtime_requirements(PROJECT_ROOT),
            ],
            timeout=300,
        )
        probe = (
            "import sys; "
            "sys.path[:0] = [sys.argv[1], sys.argv[2]]; "
            "from librecad_pdf_importer.runtime_self_test import "
            "load_runtime_dependencies; "
            "load_runtime_dependencies()"
        )
        subprocess.check_call(
            [
                python_exe,
                "-I",
                "-S",
                "-c",
                probe,
                str(stage_dir),
                str(parent),
            ],
            timeout=120,
        )
        (stage_dir / "THIRD_PARTY_NOTICES.txt").write_text(
            "Vendored runtime: PyMuPDF, ezdxf, FontTools\n",
            encoding="utf-8",
        )

        had_existing = lib_dir.exists()
        if had_existing:
            lib_dir.rename(backup_dir)
        try:
            stage_dir.rename(lib_dir)
        except OSError:
            if had_existing and backup_dir.exists() and not lib_dir.exists():
                backup_dir.rename(lib_dir)
            raise
        promoted = True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ) as exc:
        print(f"[LibreCAD PDF Importer] Dependency install failed: {exc}")
        return False
    finally:
        if stage_dir.exists():
            try:
                shutil.rmtree(stage_dir)
            except OSError as exc:
                print(
                    "[LibreCAD PDF Importer] Staging cleanup failed; manual "
                    f"cleanup is required: {stage_dir}: {exc}"
                )

    if promoted and backup_dir.exists():
        try:
            shutil.rmtree(backup_dir)
        except OSError as exc:
            print(
                "[LibreCAD PDF Importer] New runtime is active, but old backup "
                f"cleanup failed: {exc}"
            )
    ensure_lib_path()
    return promoted


def print_diagnostics() -> int:
    pymupdf_ok = check_pymupdf()
    ezdxf_ok = check_ezdxf()
    fonttools_ok = check_fonttools()
    print("[LibreCAD PDF Importer] --- Dependency Diagnostics ---")
    print(f"Python: {sys.version}")
    print(f"Lib dir: {get_lib_dir()}")
    print(f"PyMuPDF: {'OK' if pymupdf_ok else 'MISSING'}")
    print(f"ezdxf: {'OK' if ezdxf_ok else 'MISSING'}")
    print(f"FontTools: {'OK' if fonttools_ok else 'MISSING'}")
    if not (pymupdf_ok and ezdxf_ok and fonttools_ok):
        print("Install with:")
        print(
            f'  python -m pip install --target "{get_lib_dir()}" '
            '"PyMuPDF>=1.24,<2.0" ezdxf "fonttools>=4.50,<5.0"'
        )
        print("Or run:")
        print("  python preflight_check.py --install")
        return 1
    print("[LibreCAD PDF Importer] --- End Diagnostics ---")
    return 0

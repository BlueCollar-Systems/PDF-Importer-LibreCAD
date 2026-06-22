# -*- coding: utf-8 -*-
"""Import PyMuPDF with validation (skip namespace-only pymupdf stubs)."""
from __future__ import annotations

import importlib
import os
import sys
from typing import Any, List, Optional


class PdfOpenError(Exception):
    """Typed rejection for malformed, empty, or encrypted PDFs at open time."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _module_has_open(mod: Any) -> bool:
    return mod is not None and callable(getattr(mod, "open", None))


def import_fitz(*, prefer_lib_dir: Optional[str] = None) -> Any:
    """Return a fitz-compatible module (pymupdf or legacy fitz) with ``.open``."""
    lib_dir = str(prefer_lib_dir) if prefer_lib_dir else None
    attempts: List[tuple[str, bool]] = [
        ("pymupdf", True),
        ("fitz", True),
        ("pymupdf", False),
        ("fitz", False),
    ]

    last_exc: Optional[BaseException] = None
    for name, use_lib in attempts:
        saved = list(sys.path)
        try:
            if lib_dir and use_lib:
                if lib_dir not in sys.path:
                    sys.path.insert(0, lib_dir)
            elif lib_dir and not use_lib:
                sys.path[:] = [p for p in sys.path if p != lib_dir]
            mod = importlib.import_module(name)
            if _module_has_open(mod):
                return mod
            # Namespace-only stub (failed pip target) — purge and retry without lib_dir.
            if name in sys.modules:
                del sys.modules[name]
            if lib_dir and use_lib:
                sys.path[:] = [p for p in sys.path if p != lib_dir]
                continue
        except ImportError as exc:
            last_exc = exc
        finally:
            sys.path[:] = saved

    msg = "PyMuPDF (fitz) is not available"
    if last_exc is not None:
        raise ImportError(msg) from last_exc
    raise ImportError(msg)


def _classify_open_failure(exc: BaseException) -> PdfOpenError:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "password" in msg or "encrypt" in msg:
        return PdfOpenError(
            "password_protected",
            "This PDF is password-protected; supply credentials to import.",
        )
    if name in {"EmptyFileError"}:
        return PdfOpenError("empty_file", "File is empty — not a valid PDF.")
    if name in {"FileDataError", "FileNotFoundError"}:
        return PdfOpenError("not_a_pdf", "This file is not a valid PDF.")
    return PdfOpenError("not_a_pdf", "This file is not a valid PDF.")


def safe_open(path: str, *, prefer_lib_dir: Optional[str] = None) -> Any:
    """Open a PDF with clean typed errors instead of raw PyMuPDF tracebacks."""
    pdf_path = str(path)
    if not os.path.exists(pdf_path):
        raise PdfOpenError("empty_file", f"File not found: {pdf_path}")
    if os.path.getsize(pdf_path) == 0:
        raise PdfOpenError("empty_file", "File is empty — not a valid PDF.")

    fitz = import_fitz(prefer_lib_dir=prefer_lib_dir)
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # noqa: BLE001 — normalize host-facing open failures
        raise _classify_open_failure(exc) from exc

    if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
        doc.close()
        raise PdfOpenError(
            "password_protected",
            "This PDF is password-protected; supply credentials to import.",
        )
    if int(getattr(doc, "page_count", 0) or 0) == 0:
        doc.close()
        raise PdfOpenError("corrupt", "PDF has no readable pages.")
    return doc


def sample_process_mb() -> float:
    """Best-effort working-set sample for import_report peak_mb telemetry."""
    try:
        if sys.platform == "win32":
            import ctypes

            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            ):
                return round(counters.WorkingSetSize / (1024.0 * 1024.0), 2)
        elif os.path.isfile("/proc/self/status"):
            with open("/proc/self/status", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        return round(kb / 1024.0, 2)
    except Exception:
        pass
    return 0.0

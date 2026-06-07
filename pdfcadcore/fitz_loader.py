# -*- coding: utf-8 -*-
"""Import PyMuPDF with validation (skip namespace-only pymupdf stubs)."""
from __future__ import annotations

import importlib
import sys
from typing import Any, List, Optional


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

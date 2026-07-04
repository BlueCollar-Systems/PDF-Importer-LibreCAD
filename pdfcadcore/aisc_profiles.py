# -*- coding: utf-8 -*-
"""Load AISC profile dimensions from the corpus catalog (R8-A / R8-E)."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional


def _normalize_designation(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").upper())


def _corpus_profiles_path() -> Optional[Path]:
    root = os.environ.get("BCS_CORPUS_ROOT")
    if root:
        candidate = Path(root) / "profiles" / "aisc_v16_profiles.json"
        if candidate.is_file():
            return candidate
    default = Path(r"C:\1pdf-test-corpus\profiles\aisc_v16_profiles.json")
    if default.is_file():
        return default
    return None


@lru_cache(maxsize=1)
def load_aisc_profiles() -> Dict[str, Dict[str, Any]]:
    path = _corpus_profiles_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        return {}
    return profiles


def lookup_profile(designation: str) -> Optional[Dict[str, Any]]:
    """Return profile record for a rolled-shape designation or None."""
    key = _normalize_designation(designation)
    if not key:
        return None
    profiles = load_aisc_profiles()
    if key in profiles:
        return dict(profiles[key])
    alt = key.replace("X", "x")
    if alt in profiles:
        return dict(profiles[alt])
    return None


__all__ = ["load_aisc_profiles", "lookup_profile", "_normalize_designation"]

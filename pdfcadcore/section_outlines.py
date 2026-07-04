"""AISC cross-section outlines for semantic 3D member generation (R8-A).

Host-neutral geometry: given a designation from ``model_3d_intent.members``
(e.g. ``W12X30``), resolve its true dimensions from the corpus profile
catalog (``profiles/aisc_v16_profiles.json``) and emit the cross-section
outline every host can extrude along the BOM length:

  FreeCAD  -> Part.Face(outer wire - hole wires) . extrude
  Blender  -> bmesh face + solidify/extrude
  SketchUp -> face from points + pushpull (Ruby port mirrors this module)

Outlines are sharp-cornered (no fillets/tapers) — the honest v1
simplification, recorded as ``"idealized": true`` so reports never claim
mill-exact geometry. Units: inches, centered on the section centroid axis
conventions used by AISC tables (origin at section center).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["load_profiles", "resolve_profile", "section_outline"]

_PROFILE_REL = os.path.join("profiles", "aisc_v16_profiles.json")
_cache: Dict[str, Dict[str, Any]] = {}


def _default_profiles_path() -> Optional[Path]:
    root = os.environ.get("BCS_CORPUS_ROOT", r"C:\1pdf-test-corpus")
    p = Path(root) / _PROFILE_REL
    return p if p.is_file() else None


def load_profiles(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load and cache the canonical profile catalog; None when unavailable."""
    p = Path(path) if path else _default_profiles_path()
    if p is None or not p.is_file():
        return None
    key = str(p)
    if key not in _cache:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(doc.get("profiles"), dict):
            return None
        _cache[key] = doc
    return _cache[key]


def resolve_profile(designation: str,
                    profiles_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """'W12X30' / 'HSS6X6X1/4' / 'Pipe3STD' -> profile dims dict or None."""
    doc = load_profiles(profiles_path)
    if doc is None or not designation:
        return None
    key = str(designation).upper().replace(" ", "")
    return doc["profiles"].get(key)


Point = Tuple[float, float]


def _i_shape(d: float, bf: float, tf: float, tw: float) -> List[Point]:
    """W/M/S/HP doubly-symmetric I: 12 sharp corners, centered."""
    hd, hb, hw = d / 2.0, bf / 2.0, tw / 2.0
    return [
        (-hb, hd), (hb, hd), (hb, hd - tf), (hw, hd - tf),
        (hw, -hd + tf), (hb, -hd + tf), (hb, -hd), (-hb, -hd),
        (-hb, -hd + tf), (-hw, -hd + tf), (-hw, hd - tf), (-hb, hd - tf),
    ]


def _tee(d: float, bf: float, tf: float, tw: float) -> List[Point]:
    """WT/MT/ST: flange on top, stem down; origin at section center."""
    hb, hw, hd = bf / 2.0, tw / 2.0, d / 2.0
    return [
        (-hb, hd), (hb, hd), (hb, hd - tf), (hw, hd - tf),
        (hw, -hd), (-hw, -hd), (-hw, hd - tf), (-hb, hd - tf),
    ]


def _channel(d: float, bf: float, tf: float, tw: float) -> List[Point]:
    """C/MC: web on the left, flanges opening +x; centered on depth."""
    hd = d / 2.0
    return [
        (0.0, hd), (bf, hd), (bf, hd - tf), (tw, hd - tf),
        (tw, -hd + tf), (bf, -hd + tf), (bf, -hd), (0.0, -hd),
    ]


def _angle(leg_d: float, leg_b: float, t: float) -> List[Point]:
    """L: heel at origin, legs along +x and +y."""
    return [
        (0.0, 0.0), (leg_b, 0.0), (leg_b, t), (t, t),
        (t, leg_d), (0.0, leg_d),
    ]


def section_outline(profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Profile dims -> extrudable section geometry.

    Returns one of (all coordinates/radii in inches):
      {"kind": "polygon", "outer": [...], "holes": [[...]], "idealized": True}
      {"kind": "ring", "outer_r": R, "inner_r": r, "idealized": True}
    or None when the family/dims are insufficient.
    """
    if not isinstance(profile, dict):
        return None
    fam = profile.get("family")
    g = profile.get

    def poly(outer: List[Point], holes: Optional[List[List[Point]]] = None):
        return {"kind": "polygon", "outer": outer, "holes": holes or [],
                "idealized": True}

    if fam in ("W", "M", "S", "HP") and all(g(k) for k in ("d", "bf", "tf", "tw")):
        return poly(_i_shape(g("d"), g("bf"), g("tf"), g("tw")))
    if fam in ("WT", "MT", "ST") and all(g(k) for k in ("d", "bf", "tf", "tw")):
        return poly(_tee(g("d"), g("bf"), g("tf"), g("tw")))
    if fam in ("C", "MC") and all(g(k) for k in ("d", "bf", "tf", "tw")):
        return poly(_channel(g("d"), g("bf"), g("tf"), g("tw")))
    if fam in ("L", "2L") and all(g(k) for k in ("d", "b", "t")):
        return poly(_angle(g("d"), g("b"), g("t")))
    if fam == "HSS":
        t = g("tdes")
        if g("OD") and t:  # round HSS
            return {"kind": "ring", "outer_r": g("OD") / 2.0,
                    "inner_r": max(g("OD") / 2.0 - t, 0.0), "idealized": True}
        if g("Ht") and g("B") and t:  # rectangular HSS
            ho, bo = g("Ht") / 2.0, g("B") / 2.0
            hi, bi = ho - t, bo - t
            if hi <= 0 or bi <= 0:
                return None
            outer = [(-bo, ho), (bo, ho), (bo, -ho), (-bo, -ho)]
            hole = [(-bi, hi), (bi, hi), (bi, -hi), (-bi, -hi)]
            return {"kind": "polygon", "outer": outer, "holes": [hole],
                    "idealized": True}
        return None
    if fam == "PIPE" and g("OD") and g("tdes"):
        return {"kind": "ring", "outer_r": g("OD") / 2.0,
                "inner_r": max(g("OD") / 2.0 - g("tdes"), 0.0),
                "idealized": True}
    return None

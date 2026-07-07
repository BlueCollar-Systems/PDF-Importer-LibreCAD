# -*- coding: utf-8 -*-
"""Semantic AISC member solid generation (R8-A) — host-neutral planning layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .aisc_profiles import lookup_profile

DEFAULT_MEMBER_LENGTH_IN = 12.0


@dataclass
class SemanticMemberPlan:
    designation: str
    family: str
    mark: Optional[str]
    length_in: float
    count: int = 1
    length_assumed: bool = False
    profile_found: bool = False
    profile: Optional[Dict[str, Any]] = None
    skip_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticMemberResult:
    enabled: bool
    members_created: int = 0
    members_skipped: int = 0
    plans: List[SemanticMemberPlan] = field(default_factory=list)
    skipped_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "members_created": self.members_created,
            "members_skipped": self.members_skipped,
            "plans": [p.to_dict() for p in self.plans],
            "skipped_reason": self.skipped_reason,
        }


def plan_semantic_members(
    model3d_intent: Optional[Dict[str, Any]],
    *,
    enabled: bool = False,
) -> SemanticMemberResult:
    """Build member extrusion plans from import_report model_3d_intent."""
    if not enabled:
        return SemanticMemberResult(enabled=False, skipped_reason="semantic members off")
    if not model3d_intent or not model3d_intent.get("feasible"):
        return SemanticMemberResult(
            enabled=True,
            skipped_reason="no feasible 3D intent evidence",
        )

    raw_members = model3d_intent.get("members") or []
    if not raw_members:
        return SemanticMemberResult(
            enabled=True,
            skipped_reason="no member designations detected",
        )

    plans: List[SemanticMemberPlan] = []
    for item in raw_members:
        if not isinstance(item, dict):
            continue
        designation = str(item.get("designation") or "").strip()
        if not designation:
            continue
        profile = lookup_profile(designation)
        length_raw = item.get("length_in")
        length_assumed = length_raw is None
        length_in = float(length_raw) if length_raw is not None else DEFAULT_MEMBER_LENGTH_IN
        plan = SemanticMemberPlan(
            designation=designation,
            family=str(item.get("family") or ""),
            mark=item.get("mark"),
            length_in=length_in,
            count=max(1, int(item.get("count") or 1)),
            length_assumed=length_assumed,
            profile_found=profile is not None,
            profile=profile,
            skip_reason=None if profile else "designation not in AISC catalog",
        )
        plans.append(plan)

    created = sum(p.count for p in plans if p.profile_found)
    skipped = sum(p.count for p in plans if not p.profile_found)
    return SemanticMemberResult(
        enabled=True,
        members_created=created,
        members_skipped=skipped,
        plans=plans,
    )


def create_semantic_members(
    members: List[Dict[str, Any]],
    *,
    doc: Any = None,
    scale_to_mm: bool = True,
) -> Dict[str, Any]:
    """Create FreeCAD Part solids from member intent (R8-A). Default OFF at call site."""
    intent = {"feasible": True, "members": members, "plates": []}
    plan = plan_semantic_members(intent, enabled=True)
    report = plan.to_dict()
    report["objects_created"] = 0

    if doc is None or not plan.plans:
        return report

    try:
        import FreeCAD  # type: ignore  # noqa: F401 - availability probe
        import Part  # type: ignore  # noqa: F401 - availability probe
    except ImportError:
        report["skipped_reason"] = "FreeCAD Part module unavailable"
        return report

    INCH = 25.4
    group_name = "3D Members"
    group = doc.getObject(group_name)
    if group is None:
        group = doc.addObject("App::DocumentObjectGroup", group_name)

    created = 0
    for item in plan.plans:
        if not item.profile_found or not item.profile:
            continue
        for idx in range(item.count):
            face = _profile_face(item.profile, item.family)
            if face is None:
                continue
            length_mm = item.length_in * INCH
            solid = face.extrude(FreeCAD.Vector(0, 0, length_mm))
            label = item.mark or item.designation
            if item.count > 1:
                label = f"{label}_{idx + 1}"
            obj = doc.addObject("Part::Feature", f"Member_{label}")
            obj.Shape = solid
            obj.Label = f"{item.designation}_{label}"
            group.addObject(obj)
            created += 1

    report["objects_created"] = created
    report["members_created"] = created
    return report


def _profile_face(profile: Dict[str, Any], family: str) -> Any:
    """Build a Part.Face for supported AISC families (inches -> model units)."""
    try:
        import Part  # type: ignore
    except ImportError:
        return None

    fam = (family or profile.get("family") or "").upper()
    if fam == "W":
        d = float(profile.get("d") or 0)
        bf = float(profile.get("bf") or 0)
        tw = float(profile.get("tw") or 0)
        tf = float(profile.get("tf") or 0)
        if min(d, bf, tw, tf) <= 0:
            return None
        outer = Part.makePolygon([
            (-bf / 2, 0), (bf / 2, 0), (bf / 2, tf), (tw / 2, tf),
            (tw / 2, d - tf), (bf / 2, d - tf), (bf / 2, d),
            (-bf / 2, d), (-bf / 2, d - tf), (-tw / 2, d - tf),
            (-tw / 2, tf), (-bf / 2, tf), (-bf / 2, 0),
        ])
        wire = Part.Wire(outer)
        return Part.Face(wire)
    if fam == "L":
        d = float(profile.get("d") or profile.get("b") or 0)
        t = float(profile.get("t") or 0)
        if min(d, t) <= 0:
            return None
        outer = Part.makePolygon([(0, 0), (d, 0), (d, t), (t, t), (t, d), (0, d), (0, 0)])
        return Part.Face(Part.Wire(outer))
    return None


__all__ = [
    "SemanticMemberPlan",
    "SemanticMemberResult",
    "plan_semantic_members",
    "create_semantic_members",
    "DEFAULT_MEMBER_LENGTH_IN",
]

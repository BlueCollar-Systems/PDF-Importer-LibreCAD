# -*- coding: utf-8 -*-
# PDFValidation.py — Confidence and validation layer
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations


def validate_recognition(recognition_result: dict) -> dict:
    """Post-process recognition results with final validation pass."""
    if not recognition_result or not recognition_result.get("domain"):
        return recognition_result

    domain = recognition_result["domain"]
    plates = domain.get("plates", [])
    holes = domain.get("holes", [])

    # Cross-validate plates vs dimensions
    for plate in plates:
        if plate.thickness_note and plate.width_geom and plate.height_geom:
            plate.evidence.append(
                f"Dimensions: {plate.width_geom:.1f} x {plate.height_geom:.1f}mm, "
                f"thickness={plate.thickness_note}")

    # Flag orphaned holes (not inside any plate)
    for hole in holes:
        if hole.inside_plate_id is None and hole.confidence > 0.5:
            hole.warnings.append("Hole not inside any detected plate")

    return recognition_result


CONFIDENCE_THRESHOLDS = {
    "trusted":    0.85,
    "build_warn": 0.75,
    "candidate":  0.60,
    "report_only": 0.0,
}

def action_for_confidence(score: float) -> str:
    if score >= 0.85: return "trusted"
    if score >= 0.75: return "build_warn"
    if score >= 0.60: return "candidate"
    return "report_only"


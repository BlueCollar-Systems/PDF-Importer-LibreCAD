# -*- coding: utf-8 -*-
"""Page source semantics profile — Auto fidelity design, phase 2 increment 1.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
The design calls for a *closed-world* scanner: a bounded PDF operator lexer that
accounts for every invoked occurrence on a page, so that "no unaccounted semantics
remain" is an equality rather than the absence of a red flag. Only such a profile
may authorise a native route.

**This module does not implement that lexer.** It implements the profile record,
the enforced resource limits, and an honest *feature detector* that reports which
visible constructs a page carries. It therefore always reports
``accounting_mode = "feature_detection"`` and ``closed_world = False``, and
:func:`profile_is_native_eligible` always returns False.

That distinction is the whole point. A partial scanner that reported ``complete``
would recreate the exact defect the design exists to kill: a downstream consumer
reading "no problems detected" as "page fully accounted for". Absence of detected
features is not proof of completeness, and this module refuses to imply otherwise.

Its usable output is observe-only telemetry: run it across a corpus and learn which
pages carry semantics that will need a capability lookup, and how close real pages
run to the resource limits — without changing any routing.

RESOURCE LIMITS
---------------
The caps below are measured replacements for the design's proposed values, not
guesses. Across 270 pages of the pinned corpus (all pages, operands excluded,
resources walked recursively to depth 8):

    metric                       p50      p99       max   old cap   new cap
    resolved indirect objects      7      649       904       128     4096
    decoded content bytes     154556  6590487   7329808     8 MiB   16 MiB
    operator tokens            11902   493632    753271   1000000  (unchanged)
    annotation entries             0        0         1      2048  (unchanged)

The old object cap was exceeded 7.1x by ordinary municipal map sheets, and the old
byte cap had 12.6% headroom. Both made a *pathology guard* into the binding
constraint on legitimate documents. The real memory bounds are elsewhere — decoded
content and the semantic worker's RSS ceiling — so these caps are set far above
observed usage, where a pathology guard belongs.

Caveat of record: the measured corpus skews to municipal/geo maps. Every breach was
on those sheets. Validate against a structural-steel corpus before freezing.

Shared core: FreeCAD canonical; Blender/LibreCAD embed byte-identical copies. A
Ruby 2.2 parity port is required before this profile can gate anything, and does
not exist yet — another reason this increment is observe-only.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

SCHEMA = "bcs.page_source_semantics/2.0"

# --- resource limits (measured; see module docstring) ------------------------
CAP_FORM_DEPTH = 8
CAP_RESOLVED_OBJECTS = 4096          # was 128; measured max 904
CAP_DECODED_BYTES = 16 * 1024 * 1024  # was 8 MiB; measured max ~6.99 MiB
CAP_OPERATOR_TOKENS = 1_000_000      # unchanged; measured max 753,271
CAP_ANNOTATIONS = 2048               # unchanged; measured max 1

# --- accounting modes --------------------------------------------------------
# Only CLOSED_WORLD may ever authorise a native route. This increment emits the
# other one, always.
ACCOUNTING_FEATURE_DETECTION = "feature_detection"
ACCOUNTING_CLOSED_WORLD = "closed_world"

SCAN_STATUSES = ("partial", "incomplete", "error")
# NOTE: "complete" is deliberately absent. It belongs to the closed-world scanner
# and must not be emitable by feature detection.

STATUS_CODES = (
    "source_profile_partial",
    "semantic_scan_incomplete",
    # The reason-code split: a budget breach means "we could not afford to look",
    # which has a different remedy and a different user meaning than "this page
    # uses something we cannot account for". Conflating them hides limit
    # regressions inside a semantic count.
    "resource_budget_incomplete",
    "semantic_scan_error",
)

VISIBLE_FEATURE_CODES = (
    "pdf_shading_paint",
    "pdf_shading_pattern_paint",
    "pdf_tiling_pattern_paint",
    "pdf_visible_annotation_appearance",
    "pdf_visible_widget_appearance",
    "pdf_non_normal_blend",
    "pdf_fill_alpha",
    "pdf_stroke_alpha",
    "pdf_soft_mask_composite",
    "pdf_image_mask_composite",
    "pdf_transparency_group",
    "pdf_knockout_group",
    "pdf_type3_glyph_program",
    "pdf_inline_image_paint",
    "pdf_text_clip",
    "pdf_nontrivial_clip",
    "pdf_complex_color_space",
    "pdf_postscript_xobject",
)

# Fields that would turn a source profile into a routing decision. The design keeps
# source facts, IR capability and host proof strictly separate; a profile that
# carries a strategy has collapsed that separation.
_ROUTING_FIELDS = ("effective_strategy", "terminal_raster", "delivery_scope",
                   "isolated_image_hybrid", "editable")


def new_profile(
    page_index: int = 0,
    scan_status: str = "partial",
    status_code: str = "source_profile_partial",
    visible_feature_codes: "List[str] | None" = None,
    resolved_objects: int = 0,
    decoded_bytes: int = 0,
    operator_tokens: int = 0,
    annotation_entries: int = 0,
    limit_breaches: "List[str] | None" = None,
) -> Dict[str, Any]:
    """Build a page source profile.

    Defaults are pessimistic: ``partial`` accounting that cannot authorise native.
    """
    codes = sorted(set(visible_feature_codes or []))
    return {
        "schema": SCHEMA,
        "accounting_mode": ACCOUNTING_FEATURE_DETECTION,
        "closed_world": False,
        "page_index": int(page_index),
        "scan_status": scan_status,
        "status_code": status_code,
        "visible_feature_codes": codes,
        "resolved_objects": int(resolved_objects),
        "decoded_bytes": int(decoded_bytes),
        "operator_tokens": int(operator_tokens),
        "annotation_entries": int(annotation_entries),
        "limit_breaches": sorted(set(limit_breaches or [])),
        "limits": {
            "form_depth": CAP_FORM_DEPTH,
            "resolved_objects": CAP_RESOLVED_OBJECTS,
            "decoded_bytes": CAP_DECODED_BYTES,
            "operator_tokens": CAP_OPERATOR_TOKENS,
            "annotation_entries": CAP_ANNOTATIONS,
        },
    }


def validate_profile(profile: Dict[str, Any]) -> List[str]:
    """Return every conformance violation; empty means the record is legal."""
    violations: List[str] = []

    if profile.get("schema") != SCHEMA:
        violations.append("schema=%r is not %s" % (profile.get("schema"), SCHEMA))

    mode = profile.get("accounting_mode")
    if mode == ACCOUNTING_CLOSED_WORLD:
        violations.append(
            "accounting_mode=closed_world is not implementable by this module: the "
            "closed operator lexer does not exist yet, and claiming it would let a "
            "partial scan authorise a native route"
        )
    elif mode != ACCOUNTING_FEATURE_DETECTION:
        violations.append("accounting_mode=%r is not %s" % (mode, ACCOUNTING_FEATURE_DETECTION))

    if profile.get("closed_world"):
        violations.append("closed_world must be False for a feature-detection profile")

    status = profile.get("scan_status")
    if status == "complete":
        violations.append(
            "scan_status=complete is reserved for the closed-world scanner; feature "
            "detection cannot prove completeness (absence of detected features is "
            "not proof)"
        )
    elif status not in SCAN_STATUSES:
        violations.append("scan_status=%r is not one of %s" % (status, ", ".join(SCAN_STATUSES)))

    if profile.get("status_code") not in STATUS_CODES:
        violations.append("status_code=%r is not one of %s"
                          % (profile.get("status_code"), ", ".join(STATUS_CODES)))

    codes = profile.get("visible_feature_codes")
    if not isinstance(codes, list):
        violations.append("visible_feature_codes must be a list")
    else:
        for code in codes:
            if code not in VISIBLE_FEATURE_CODES:
                violations.append("unknown visible feature code %r" % code)
        if codes != sorted(set(codes)):
            violations.append("visible_feature_codes must be sorted and unique")

    for field in _ROUTING_FIELDS:
        if field in profile:
            violations.append(
                "%s must not appear in a source profile: source facts, IR capability "
                "and host proof stay separate" % field
            )
    return violations


def profile_is_native_eligible(profile: Dict[str, Any]) -> bool:
    """Whether this profile may authorise a native (non-recovery) route.

    Always False in this increment. Native eligibility requires closed-world
    accounting -- every invoked occurrence classified, zero unknowns -- which
    feature detection cannot supply. Stated as a function rather than an implicit
    absence so a caller cannot forget to ask.
    """
    if profile.get("accounting_mode") != ACCOUNTING_CLOSED_WORLD:
        return False
    if profile.get("scan_status") != "complete":
        return False
    return not profile.get("visible_feature_codes")


def record_limit_breaches(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Flag any measured value that exceeds its cap, and mark the profile
    ``resource_budget_incomplete`` rather than ``semantic_scan_incomplete``."""
    breaches: List[str] = []
    for key, cap in (
        ("resolved_objects", CAP_RESOLVED_OBJECTS),
        ("decoded_bytes", CAP_DECODED_BYTES),
        ("operator_tokens", CAP_OPERATOR_TOKENS),
        ("annotation_entries", CAP_ANNOTATIONS),
    ):
        if int(profile.get(key) or 0) > cap:
            breaches.append(key)
    if breaches:
        profile["limit_breaches"] = sorted(set(breaches))
        profile["scan_status"] = "incomplete"
        profile["status_code"] = "resource_budget_incomplete"
    return profile


def canonical_profile_json(profile: Dict[str, Any]) -> str:
    """Stable UTF-8 JSON, sorted keys, LF. Python and Ruby will compare these bytes
    once the parity port exists."""
    return json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

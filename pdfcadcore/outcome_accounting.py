# -*- coding: utf-8 -*-
"""Binding outcome accounting for Auto page strategy versus requested representation.

Phase 1 of the Auto fidelity design. This module carries no page-scanning, no
routing, and no rendering: it is only the record shape and the six laws that
keep a *picture of a page* from being reported as *the editable representation
the user asked for*.

Why it exists, concretely: an audit of the certification corpus found 278 cells
recorded PASS on a subprocess return code with no delivery evidence behind them.
The failure mode is never a deliberate lie -- it is a roll-up. Some summary,
validator, or dashboard sees "an artifact was produced" and folds that into
"the cell passed". Writing the axes down in a design document does not stop
that; only a validator that refuses the combination does.

So the axes here are deliberately *independent*, and the illegal combinations
are rejected rather than normalised:

* ``structural_status`` -- did the page's native structure get delivered?
* ``visual_status``     -- is the page's appearance proved against a reference?
* ``requested_representation_status`` -- did the user get the mode they asked for?
* ``cell_status``       -- the conjunction, and it is never inferred from the others
                           being merely "not bad".

The single most important rule is Law 4: a *certified* recovery image can make
the visual axis pass while the cell still fails. That combination is legal,
expected, and must survive every summary layer untouched.

This module is shared-core: FreeCAD is canonical and Blender/LibreCAD embed
byte-identical copies (see pdfcadcore_sync_check.py). SketchUp carries a
behaviour-equivalent Ruby 2.2 port. Keep the law set and the vocabulary
identical across all four or the cross-host matrix stops meaning anything.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

SCHEMA = "bcs.auto_outcome_accounting/1.0"

# --- axis vocabularies -------------------------------------------------------
# Fixed tokens only. A value outside these sets is a conformance error, never a
# "close enough" match -- an unrecognised status is exactly how an unearned PASS
# slips through a downstream comparison.
PAGE_STRATEGIES = ("native", "host_proved_hybrid", "visual_recovery", "incomplete")
REPRESENTATIONS = ("text", "labels", "3d_text", "glyphs", "geometry", "raster", "none")
STRUCTURAL_STATUSES = ("pass", "fail", "not_certified")
VISUAL_STATUSES = ("pass", "fail", "unproved")
REQUESTED_REPRESENTATION_STATUSES = ("pass", "fail", "not_applicable")
CELL_STATUSES = ("pass", "fail")
VISUAL_RECOVERY_STATES = ("absent", "attempted", "certified", "failed")

# The five editable rungs. Raster is deliberately excluded: requested Raster is a
# different binding outcome that certifies through the existing Raster contract
# (Law 5), and "none" means the cell manifest asked for no representation at all.
EDITABLE_REPRESENTATIONS = ("text", "labels", "3d_text", "glyphs", "geometry")

# Fields a recovery page may never carry. A recovery artifact has page/source/
# render/placement proof -- it has no item identities and no ladder edges, so if
# either of these appears on a recovery record something upstream has confused a
# picture with a delivery.
_DELIVERY_ONLY_FIELDS = ("delivered_representation", "item_transitions")

_REQUIRED_FIELDS = (
    "requested_page_strategy",
    "effective_page_strategy",
    "requested_representation",
    "structural_status",
    "visual_status",
    "requested_representation_status",
    "cell_status",
    "visual_recovery",
)

_COMPLETION_RECOVERY = "visual recovery created; requested representation not certified"


def new_outcome(
    requested_page_strategy="auto",
    effective_page_strategy="incomplete",
    requested_representation="none",
    structural_status="not_certified",
    visual_status="unproved",
    requested_representation_status="not_applicable",
    cell_status="fail",
    visual_recovery="absent",
    native_peer_count=0,
    visual_proof_digest="",
):
    # type: (str, str, str, str, str, str, str, str, int, str) -> Dict[str, Any]
    """Build an outcome record.

    Every default is the pessimistic value. A caller that forgets to set an axis
    gets ``fail``/``unproved``/``not_certified``, never an accidental pass.
    """
    return {
        "schema": SCHEMA,
        "requested_page_strategy": requested_page_strategy,
        "effective_page_strategy": effective_page_strategy,
        "requested_representation": requested_representation,
        "structural_status": structural_status,
        "visual_status": visual_status,
        "requested_representation_status": requested_representation_status,
        "cell_status": cell_status,
        "visual_recovery": visual_recovery,
        "native_peer_count": int(native_peer_count),
        "visual_proof_digest": visual_proof_digest,
    }


def _check_vocabulary(record):
    # type: (Dict[str, Any]) -> List[str]
    violations = []  # type: List[str]
    for field in _REQUIRED_FIELDS:
        if field not in record:
            violations.append("missing required field %s" % field)
    pairs = (
        ("effective_page_strategy", PAGE_STRATEGIES),
        ("requested_representation", REPRESENTATIONS),
        ("structural_status", STRUCTURAL_STATUSES),
        ("visual_status", VISUAL_STATUSES),
        ("requested_representation_status", REQUESTED_REPRESENTATION_STATUSES),
        ("cell_status", CELL_STATUSES),
        ("visual_recovery", VISUAL_RECOVERY_STATES),
    )
    for field, allowed in pairs:
        value = record.get(field)
        if value is not None and value not in allowed:
            violations.append(
                "%s=%r is not one of %s" % (field, value, ", ".join(allowed))
            )
    return violations


def validate_outcome(record):
    # type: (Dict[str, Any]) -> List[str]
    """Return every law violation in *record*; an empty list means it is legal.

    Returning a list rather than raising is deliberate: a report writer should be
    able to record *all* the ways a roll-up went wrong in one pass, and a caller
    that wants hard failure can simply assert the list is empty.
    """
    violations = _check_vocabulary(record)
    if violations:
        # Vocabulary is a precondition for the law checks below; comparing
        # unknown tokens would produce misleading follow-on violations.
        return violations

    strategy = record.get("effective_page_strategy")
    requested = record.get("requested_representation")
    req_status = record.get("requested_representation_status")
    recovery = record.get("visual_recovery")
    visual = record.get("visual_status")

    is_recovery = strategy == "visual_recovery"
    editable_requested = requested in EDITABLE_REPRESENTATIONS

    # --- Law 5: requested Raster is a different binding outcome ---------------
    # It certifies through the Raster contract and grants no outgoing ladder
    # edge, so the visual_recovery label must not be applied to it at all.
    if requested == "raster" and (is_recovery or recovery != "absent"):
        violations.append(
            "requested_representation=raster cannot use the visual_recovery label; "
            "requested Raster certifies through the Raster contract (Law 5)"
        )

    # --- Law 2: recovery is not delivery --------------------------------------
    if is_recovery:
        for field in _DELIVERY_ONLY_FIELDS:
            if record.get(field):
                violations.append(
                    "%s must be absent on a visual_recovery page: a recovery "
                    "artifact has no item identities or ladder edges (Law 2)" % field
                )
        if req_status == "pass":
            violations.append(
                "requested_representation_status=pass is illegal on a "
                "visual_recovery page: a page image never satisfies a requested "
                "representation (Law 2)"
            )

        # --- Law 3: recovery-page axes ----------------------------------------
        if record.get("structural_status") != "not_certified":
            violations.append(
                "structural_status must be not_certified on a visual_recovery "
                "page (Law 3)"
            )
        if editable_requested and req_status != "fail":
            violations.append(
                "requested_representation=%s was requested but "
                "requested_representation_status=%r; it must be fail on a "
                "recovery page, and not_applicable only when nothing editable "
                "was requested (Law 3)" % (requested, req_status)
            )

        # --- Law 6: a recovery page keeps no native peers ---------------------
        if int(record.get("native_peer_count") or 0) != 0:
            violations.append(
                "native_peer_count=%s on a visual_recovery page: the recovery "
                "artifact must have zero native peers (Law 6)"
                % record.get("native_peer_count")
            )

    # --- Law 3/6: a visual pass needs candidate-bound proof, and a failed
    # recovery can never report one.
    if visual == "pass":
        if not record.get("visual_proof_digest"):
            violations.append(
                "visual_status=pass requires a candidate-bound visual_proof_digest; "
                "existence, dimensions, or a return code are not proof (Law 3)"
            )
        if recovery == "failed":
            violations.append(
                "visual_status=pass is illegal while visual_recovery=failed (Law 6)"
            )

    # --- Law 4: the cell conjunction, never coerced ---------------------------
    if record.get("cell_status") == "pass":
        legal = derive_cell_status(record)
        if legal != "pass":
            violations.append(
                "cell_status=pass is not supported by its axes "
                "(structural=%s, requested_representation=%s, visual=%s). A "
                "certified recovery artifact may pass the visual axis while the "
                "cell still fails; no roll-up may coerce that to PASS (Law 4)"
                % (
                    record.get("structural_status"),
                    req_status,
                    visual,
                )
            )

    return violations


def derive_cell_status(record):
    # type: (Dict[str, Any]) -> str
    """Compute the only cell status the axes support.

    Law 4: a required cell passes only when its structural requirements pass, its
    requested representation was delivered through a legal certified chain, and
    its visual requirements pass. Anything else is ``fail``. There is no
    "partial" and no "pass with notes" -- those are the shapes that let an
    unearned PASS survive.
    """
    if record.get("effective_page_strategy") == "visual_recovery":
        # A recovery page is structurally uncertified by Law 3, so it can never
        # reach a passing cell. Stated explicitly because this is the exact case
        # a summary layer is most tempted to round up.
        return "fail"
    if record.get("structural_status") != "pass":
        return "fail"
    if record.get("requested_representation_status") not in ("pass", "not_applicable"):
        return "fail"
    if record.get("visual_status") != "pass":
        return "fail"
    return "pass"


def completion_class(record):
    # type: (Dict[str, Any]) -> str
    """The user-facing completion sentence.

    Recovery pages get fixed wording that cannot be misread as delivery. This
    string is part of the contract, not cosmetic copy.
    """
    if record.get("effective_page_strategy") == "visual_recovery":
        return _COMPLETION_RECOVERY
    if derive_cell_status(record) == "pass":
        return "requested representation delivered and certified"
    return "requested representation not certified"


def canonical_json(record):
    # type: (Dict[str, Any]) -> str
    """Stable UTF-8 JSON with sorted keys and LF endings.

    Python and Ruby compare these bytes, so formatting is part of the contract.
    """
    return json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def assert_outcome_legal(record):
    # type: (Dict[str, Any]) -> None
    """Raise ``ValueError`` when *record* breaks any law.

    For call sites on the delivery path that must fail closed rather than
    accumulate violations.
    """
    violations = validate_outcome(record)
    if violations:
        raise ValueError(
            "illegal outcome accounting record:\n  " + "\n  ".join(violations)
        )

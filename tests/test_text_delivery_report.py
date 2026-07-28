from __future__ import annotations

import json

import pytest

from pdfcadcore.text_delivery_report import (
    build_text_representation_delivery,
    resolve_text_representation_delivery,
)


def _attempt(
    source_item_id: str,
    attempted_type: str,
    outcome: str,
    *,
    final_type: str | None = None,
    cleanup_complete: bool = True,
    sentinel: str | None = None,
) -> dict:
    evidence = (
        {"sentinel": sentinel}
        if sentinel is not None
        else {"test_evidence": True}
    )
    created_id = f"created:{source_item_id}:{attempted_type}"
    return {
        "source_item_id": source_item_id,
        "requested_type": "3d_text",
        "attempted_type": attempted_type,
        "final_type": final_type,
        "outcome": outcome,
        "cleanup_complete": cleanup_complete,
        "record_verified": outcome == "verified",
        "type_verified": outcome == "verified",
        "visual_verified": outcome == "verified",
        "ownership_verified": outcome == "verified",
        "created_entity_ids": [created_id],
        "removed_entity_ids": (
            [created_id] if outcome == "proven_impossible" else []
        ),
        "delivery_entity_ids": (
            [created_id] if outcome == "verified" else []
        ),
        "support_entity_ids": [],
        "referenced_entity_ids": [],
        "reused_entity_ids": [],
        "evidence": evidence,
    }


def test_builds_compact_projection_over_one_canonical_attempt_ledger() -> None:
    sentinel = "UNIQUE-LARGE-EVIDENCE-SENTINEL"
    ledger = [
        _attempt("p1:s0", "3d_text", "proven_impossible"),
        _attempt("p1:s0", "glyphs", "verified", final_type="glyphs"),
        _attempt(
            "p1:s1",
            "3d_text",
            "verified",
            final_type="3d_text",
            sentinel=sentinel,
        ),
    ]

    delivery = build_text_representation_delivery(
        ledger,
        requested_type="3d_text",
        required=True,
        expected_source_item_ids={"p1:s0", "p1:s1"},
    )

    assert delivery == {
        "schema": "bcs.text_representation_delivery/1.1",
        "required": True,
        "requested_type": "3d_text",
        "verified": True,
        "attempt_count": 3,
        "source_item_count": 2,
        "delivered_item_count": 2,
        "failed_item_count": 0,
        "items": [
            {
                "source_item_id": "p1:s0",
                "terminal_attempt_index": 1,
                "final_type": "glyphs",
                "verified": True,
            },
            {
                "source_item_id": "p1:s1",
                "terminal_attempt_index": 2,
                "final_type": "3d_text",
                "verified": True,
            },
        ],
        "invalid_reasons": [],
    }
    payload = json.dumps(
        {
            "extra": {
                "text_delivery_attempts": ledger,
                "text_representation_delivery": delivery,
            }
        },
        sort_keys=True,
    )
    assert payload.count(sentinel) == 1

    resolution = resolve_text_representation_delivery(
        ledger,
        delivery,
        expected_source_item_ids={"p1:s0", "p1:s1"},
    )
    assert resolution["verified"] is True
    assert resolution["terminal_attempts"] == [ledger[1], ledger[2]]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda report: report["items"][0].update(terminal_attempt_index=99), "items"),
        (lambda report: report.update(attempt_count=99), "attempt_count"),
        (lambda report: report.update(verified=False), "verified"),
    ],
)
def test_resolver_recomputes_and_rejects_tampered_projection(mutation, reason) -> None:
    ledger = [_attempt("p1:s0", "3d_text", "verified", final_type="3d_text")]
    delivery = build_text_representation_delivery(
        ledger,
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )
    mutation(delivery)

    resolution = resolve_text_representation_delivery(
        ledger,
        delivery,
        expected_source_item_ids={"p1:s0"},
    )

    assert resolution["verified"] is False
    assert any(reason in item for item in resolution["invalid_reasons"])


def test_unproven_or_unclean_prior_attempt_blocks_verified_delivery() -> None:
    for outcome, cleanup_complete in (("failed", True), ("proven_impossible", False)):
        ledger = [
            _attempt(
                "p1:s0",
                "3d_text",
                outcome,
                cleanup_complete=cleanup_complete,
            ),
            _attempt("p1:s0", "glyphs", "verified", final_type="glyphs"),
        ]

        delivery = build_text_representation_delivery(
            ledger,
            requested_type="3d_text",
            expected_source_item_ids={"p1:s0"},
        )

        assert delivery["verified"] is False
        assert delivery["delivered_item_count"] == 0
        assert delivery["failed_item_count"] == 1
        assert delivery["items"][0]["verified"] is False
        assert delivery["invalid_reasons"]


def test_expected_source_set_must_match_ledger_exactly() -> None:
    ledger = [_attempt("p1:s0", "3d_text", "verified", final_type="3d_text")]

    delivery = build_text_representation_delivery(
        ledger,
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0", "p1:s1"},
    )

    assert delivery["verified"] is False
    assert any("source_item_ids" in item for item in delivery["invalid_reasons"])


def test_one_delivered_entity_cannot_satisfy_two_source_items() -> None:
    ledger = [
        _attempt("p1:s0", "3d_text", "verified", final_type="3d_text"),
        _attempt("p1:s1", "3d_text", "verified", final_type="3d_text"),
    ]
    ledger[1]["delivery_entity_ids"] = list(ledger[0]["delivery_entity_ids"])

    delivery = build_text_representation_delivery(
        ledger,
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0", "p1:s1"},
    )

    assert delivery["verified"] is False
    assert any("delivery_entity_ids" in item for item in delivery["invalid_reasons"])


def test_fallback_requires_a_proven_requested_representation_attempt() -> None:
    ledger = [_attempt("p1:s0", "glyphs", "verified", final_type="glyphs")]

    delivery = build_text_representation_delivery(
        ledger,
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )

    assert delivery["verified"] is False
    assert any("start with requested_type" in item for item in delivery["invalid_reasons"])


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda attempt: attempt.update(evidence={}), "evidence"),
        (
            lambda attempt: attempt.update(
                created_entity_ids=["partial"], removed_entity_ids=[]
            ),
            "cleanup ownership",
        ),
    ],
)
def test_prior_impossibility_requires_evidence_and_exact_cleanup(mutation, reason) -> None:
    prior = _attempt("p1:s0", "3d_text", "proven_impossible")
    prior["evidence"] = {"item_specific_proof": True}
    terminal = _attempt("p1:s0", "glyphs", "verified", final_type="glyphs")
    mutation(prior)

    delivery = build_text_representation_delivery(
        [prior, terminal],
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )

    assert delivery["verified"] is False
    assert any(reason in item for item in delivery["invalid_reasons"])


@pytest.mark.parametrize(
    "field",
    ["record_verified", "type_verified", "visual_verified", "ownership_verified"],
)
def test_terminal_requires_record_type_and_visual_verification(field) -> None:
    terminal = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    terminal["evidence"] = {"host_bound": True}
    terminal[field] = False

    delivery = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )

    assert delivery["verified"] is False
    assert any(field in item for item in delivery["invalid_reasons"])


def test_terminal_requires_explicit_binding_for_reused_delivery_entities() -> None:
    terminal = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    terminal["delivery_entity_ids"] = ["preexisting:1"]

    invalid = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )
    assert invalid["verified"] is False
    assert any("reused_entity_ids" in item for item in invalid["invalid_reasons"])

    terminal["created_entity_ids"] = []
    terminal["reused_entity_ids"] = ["preexisting:1"]
    valid = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )
    assert valid["verified"] is True


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda attempt: attempt["created_entity_ids"].append("orphan:1"),
            "created entities are not exactly",
        ),
        (
            lambda attempt: attempt.update(
                support_entity_ids=list(attempt["delivery_entity_ids"])
            ),
            "delivery and support entity roles overlap",
        ),
        (
            lambda attempt: attempt["removed_entity_ids"].append("unowned:1"),
            "removed entities were not created",
        ),
    ],
)
def test_terminal_ownership_is_an_exact_partition(mutation, reason) -> None:
    terminal = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    mutation(terminal)

    delivery = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )

    assert delivery["verified"] is False
    assert any(reason in item for item in delivery["invalid_reasons"])


@pytest.mark.parametrize(
    "invalid_ids",
    [[None, "valid"], [" padded"], [1], ["duplicate", "duplicate"]],
)
def test_entity_identity_arrays_reject_invalid_members(invalid_ids) -> None:
    terminal = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    terminal["referenced_entity_ids"] = invalid_ids

    delivery = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids={"p1:s0"},
    )

    assert delivery["verified"] is False
    assert any("referenced_entity_ids is invalid" in item for item in delivery["invalid_reasons"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda attempt: attempt.update(source_item_id=123),
        lambda attempt: attempt.update(source_item_id=" p1:s0 "),
        lambda attempt: attempt.update(requested_type=" 3d_text "),
        lambda attempt: attempt.update(attempted_type=" 3d_text "),
        lambda attempt: attempt.update(final_type=" 3d_text "),
        lambda attempt: attempt.update(outcome=" verified "),
    ],
)
def test_contract_identity_and_state_strings_are_exact(mutation) -> None:
    terminal = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    mutation(terminal)

    delivery = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids=["p1:s0"],
    )

    assert delivery["verified"] is False
    assert delivery["invalid_reasons"]


def test_numeric_source_identity_is_not_coerced_to_expected_text() -> None:
    terminal = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    terminal["source_item_id"] = 123

    delivery = build_text_representation_delivery(
        [terminal],
        requested_type="3d_text",
        expected_source_item_ids=["123"],
    )

    assert delivery["verified"] is False
    assert any("source_item_id" in item for item in delivery["invalid_reasons"])


@pytest.mark.parametrize("shared_role", ["delivery", "support"])
def test_retained_entities_are_unique_across_source_items(shared_role) -> None:
    left = _attempt("p1:s0", "3d_text", "verified", final_type="3d_text")
    right = _attempt("p1:s1", "3d_text", "verified", final_type="3d_text")
    shared_id = "shared:retained"
    left["support_entity_ids"] = [shared_id]
    left["created_entity_ids"].append(shared_id)
    if shared_role == "delivery":
        right["delivery_entity_ids"] = [shared_id]
        right["created_entity_ids"] = [shared_id]
    else:
        right["support_entity_ids"] = [shared_id]
        right["created_entity_ids"].append(shared_id)

    delivery = build_text_representation_delivery(
        [left, right],
        requested_type="3d_text",
        expected_source_item_ids=["p1:s0", "p1:s1"],
    )

    assert delivery["verified"] is False
    assert any("retained entity identities" in item for item in delivery["invalid_reasons"])


def test_removed_attempt_artifact_cannot_reappear_as_reused_delivery() -> None:
    prior = _attempt("p1:s0", "3d_text", "proven_impossible")
    removed_id = prior["created_entity_ids"][0]
    terminal = _attempt("p1:s0", "glyphs", "verified", final_type="glyphs")
    terminal["created_entity_ids"] = []
    terminal["delivery_entity_ids"] = [removed_id]
    terminal["reused_entity_ids"] = [removed_id]

    delivery = build_text_representation_delivery(
        [prior, terminal],
        requested_type="3d_text",
        expected_source_item_ids=["p1:s0"],
    )

    assert delivery["verified"] is False
    assert any("reused entities were created or removed" in item for item in delivery["invalid_reasons"])

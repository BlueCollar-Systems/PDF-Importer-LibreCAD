from __future__ import annotations

import pytest

from dxf_text_builder import TextDeliveryAttempt, TextDeliveryResult


def test_verified_attempt_cannot_serialize_without_all_terminal_proofs() -> None:
    attempt = TextDeliveryAttempt(
        source_id="text_span:1:1",
        requested_representation="text",
        attempted_representation="text",
        strategy="synthetic",
        outcome="verified",
        type_verified=True,
        delivery_verified=True,
        visual_verified=False,
        cleanup_verified=True,
    )
    result = TextDeliveryResult(
        source_id=attempt.source_id,
        requested_representation="text",
        final_representation="text",
        verified=True,
        entity_handles=["A1"],
        attempts=[attempt],
    )

    with pytest.raises(RuntimeError, match="verified attempt is missing terminal proof"):
        result.to_dict()

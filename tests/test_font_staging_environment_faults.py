"""Record font staging diagnostics without authorizing representation fallback.

Disk, permission, path and helper failures do not establish impossibility in
the source PDF. The resolver must report these as failed attempts; only an
affirmatively proven source impossibility may descend the representation ladder.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dxf_text_builder as builder  # noqa: E402
from pdfcadcore.atomic_io import AtomicWriteError  # noqa: E402


class _Config:
    """Only the attributes the resolver reads off the config."""

    def __init__(self, paths=None, faults=None):
        self._embedded_font_asset_paths = dict(paths or {})
        if faults is not None:
            self._embedded_font_staging_faults = dict(faults)


def _resolution(**overrides):
    base = {
        "source_name": "Arial",
        "family": "Arial",
        "exact": False,
        "reason": "exact embedded font was not staged for this export",
        "asset_id": "sha256:" + "a" * 64,
    }
    base.update(overrides)
    return builder._ExactFontResolution(**base)


# --- the discriminator itself -------------------------------------------------


def test_proven_impossibility_descends():
    attempt = builder.TextDeliveryAttempt(
        source_id="p1:s0",
        requested_representation="text",
        attempted_representation="text",
        strategy="native_dxf_text",
    )
    resolved = _resolution(item_impossibility_proven=True)

    with pytest.raises(builder._RepresentationImpossible):
        builder._raise_for_unusable_font(resolved, attempt)


def test_unproven_failure_still_aborts():
    """An unexplained miss must NOT be silently downgraded to a descent."""
    attempt = builder.TextDeliveryAttempt(
        source_id="p1:s0",
        requested_representation="text",
        attempted_representation="text",
        strategy="native_dxf_text",
    )
    resolved = _resolution(item_impossibility_proven=False)

    with pytest.raises(ValueError) as caught:
        builder._raise_for_unusable_font(resolved, attempt)
    assert not isinstance(caught.value, builder._RepresentationImpossible), (
        "an unproven font miss must stay a generic failure; downgrading it "
        "wholesale would let real bugs pass as fallbacks"
    )


# --- a recorded staging fault is an actionable diagnostic --------------------


def test_recorded_staging_fault_preserves_environment_reason():
    config = _Config(
        faults={"sha256:" + "a" * 64: "could not publish fonts/aaa.otf: disk full"}
    )
    recorded, reason = builder._staging_fault_for_asset(config, "sha256:" + "a" * 64)
    assert recorded is True
    assert "disk full" in reason, "the environment reason must reach the report"


def test_absent_staging_fault_is_not_proven():
    config = _Config(faults={})
    proven, reason = builder._staging_fault_for_asset(config, "sha256:" + "b" * 64)
    assert proven is False
    assert reason == ""


def test_config_without_the_attribute_is_not_proven():
    """Older callers that never set the attribute must not be treated as faults."""
    config = _Config()
    proven, _ = builder._staging_fault_for_asset(config, "sha256:" + "c" * 64)
    assert proven is False


# --- the staging helper must record rather than escape ------------------------


def test_staging_records_write_faults_instead_of_raising(monkeypatch, tmp_path):
    from librecad_pdf_importer.exporters import dxf_exporter

    def _explode(path, content):
        raise AtomicWriteError(f"could not publish {path}: simulated")

    monkeypatch.setattr(dxf_exporter, "atomic_write_bytes", _explode, raising=False)

    faults: dict = {}
    recorded = dxf_exporter._record_font_staging_fault(
        faults, "sha256:" + "d" * 64, AtomicWriteError("could not publish x: locked")
    )
    assert recorded is True
    assert "sha256:" + "d" * 64 in faults
    assert "locked" in faults["sha256:" + "d" * 64]

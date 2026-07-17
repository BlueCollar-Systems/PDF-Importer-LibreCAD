"""Atomic, output-scoped evidence artifacts for completed imports."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pdfcadcore.import_report import ImportReport
from pdfcadcore.parts_bootstrap import write_parts_bootstrap_sidecar
from pdfcadcore.source_provenance import SourceProvenanceManifest


@pytest.mark.parametrize(
    "writer",
    [
        lambda path: ImportReport().write_json(str(path)),
        lambda path: SourceProvenanceManifest().write_json(str(path)),
        lambda path: write_parts_bootstrap_sidecar(
            str(path), str(path.with_suffix(".pdf")), page_count=1
        ),
    ],
)
def test_json_evidence_writers_preserve_prior_artifact_when_publish_fails(
    tmp_path: Path,
    writer,
) -> None:
    destination = tmp_path / "accepted.json"
    prior = b'{"accepted": true}\n'
    destination.write_bytes(prior)

    with patch.object(Path, "replace", side_effect=OSError("publish denied")):
        with pytest.raises(OSError, match="publish denied"):
            writer(destination)

    assert destination.read_bytes() == prior
    assert not [path for path in tmp_path.iterdir() if path.name != destination.name]

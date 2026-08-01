from __future__ import annotations

import json
from pathlib import Path

import fitz

from scripts.generate_public_synthetic_corpus import generate_corpus


def test_generator_creates_declared_privacy_safe_cases(tmp_path: Path) -> None:
    manifest_path = generate_corpus(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["license"] == "CC0-1.0"
    assert manifest["generated_only"] is True
    assert set(manifest["cases"]) == {
        "engineering_multimode",
        "blank_page",
        "malformed_input",
    }

    engineering = tmp_path / manifest["cases"]["engineering_multimode"]["file"]
    with fitz.open(engineering) as document:
        assert document.page_count == 3
        assert document[1].rotation == 90
        assert document[0].get_text().strip()
        assert document[2].get_images(full=True)

    blank = tmp_path / manifest["cases"]["blank_page"]["file"]
    with fitz.open(blank) as document:
        assert document.page_count == 1
        assert not document[0].get_text().strip()

    malformed = tmp_path / manifest["cases"]["malformed_input"]["file"]
    assert malformed.read_bytes() == b"%PDF-1.7\nsynthetic-truncated-object\n"


def test_generator_never_writes_outside_requested_directory(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "corpus"
    manifest_path = generate_corpus(output)

    assert manifest_path.parent == output.resolve()
    assert all(path.is_relative_to(output) for path in output.rglob("*"))

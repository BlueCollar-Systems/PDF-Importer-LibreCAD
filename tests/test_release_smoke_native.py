from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest

from scripts import smoke_portable_zip


def _write_native_delivery(
    output: Path,
    *,
    requested: str,
    executable: Path,
    lff: Path,
    reported_handle: str | None = None,
) -> None:
    drawing = ezdxf.new("R2010")
    drawing.styles.add("unicode", font="unicode")
    native = drawing.modelspace().add_text(
        "BCS PORTABLE GLYPH",
        dxfattribs={"style": "unicode", "height": 1.0},
    )
    drawing.saveas(output)
    handle = reported_handle or str(native.dxf.handle)
    lff_digest = hashlib.sha256(lff.read_bytes()).hexdigest()
    evidence = {
        "target_app": "librecad",
        "delivered_content": "BCS PORTABLE GLYPH",
        "librecad_evidence_sensitivity": (
            "shareable_with_classified_local_diagnostics"
        ),
        "local_only_diagnostics": {
            "classification": "local_sensitive_paths",
            "shareable": False,
            "librecad_executable_path": str(executable.resolve()),
            "librecad_installation_root": str(executable.parent.resolve()),
            "librecad_lff_path": str(lff.resolve()),
        },
        "librecad_lff_size_bytes": lff.stat().st_size,
        "librecad_lff_sha256": lff_digest,
        "librecad_lff_missing_codepoints": [],
        "librecad_lff_invalid_codepoints": [],
        "librecad_parent_installation_verified": True,
        "librecad_lff_executable_binding_verified": True,
        "librecad_lff_asset_verified": True,
        "librecad_lff_coverage_verified": True,
        "librecad_lff_required_glyphs_drawable_verified": True,
        "parent_native_font_asset_coverage_verified": True,
        "parent_native_text_reopen_verified": True,
        "parent_native_text_reopen_renderability_verified": False,
        "parent_native_text_reopen_asset_coverage_verified": True,
        "serialized_cap_height_invariant_verified": True,
        "delivery_evidence_verified": True,
    }
    report = output.with_name(f"{output.stem}_import_report.json")
    report.write_text(
        json.dumps(
            {
                "extra": {
                    "text_representation_delivery": {
                        "requested_representation": requested,
                        "verified": True,
                        "items": [
                            {
                                "requested_representation": requested,
                                "final_representation": "text",
                                "verified": True,
                                "fallback_used": requested == "labels",
                                "entity_handles": [handle],
                                "attempts": [
                                    {
                                        "attempted_representation": "text",
                                        "outcome": "verified",
                                        "delivery_verified": True,
                                        "visual_verified": False,
                                        "entity_handles": [handle],
                                        "evidence": evidence,
                                    }
                                ],
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_portable_smoke_exercises_glyphs_and_visible_text_fallbacks(
    monkeypatch,
    tmp_path,
) -> None:
    for name in smoke_portable_zip.REQUIRED_EXES:
        (tmp_path / name).write_bytes(b"exe")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if "--text-mode" not in command:
            return SimpleNamespace(returncode=0, stdout="Self-test OK", stderr="")
        mode = command[command.index("--text-mode") + 1]
        output = Path(command[2])
        drawing = ezdxf.new("R2010")
        drawing.modelspace().add_line((0, 0), (1, 1))
        drawing.saveas(output)
        report = output.with_name(f"{output.stem}_import_report.json")
        report.write_text(
            json.dumps(
                {
                    "extra": {
                        "text_representation_delivery": {
                            "requested_representation": mode,
                            "verified": True,
                            "items": [
                                {
                                    "requested_representation": mode,
                                    "final_representation": "glyphs",
                                    "verified": True,
                                    "fallback_used": mode != "glyphs",
                                }
                            ],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="Conversion complete", stderr="")

    monkeypatch.setattr(smoke_portable_zip.subprocess, "run", fake_run)
    monkeypatch.setattr(
        smoke_portable_zip,
        "_write_tiny_pdf",
        lambda path: path.write_bytes(b"%PDF-test"),
    )

    smoke_portable_zip._smoke_extracted_portable(tmp_path)

    conversions = [call for call in calls if "--text-mode" in call[0]]
    assert [
        command[command.index("--text-mode") + 1]
        for command, _kwargs in conversions
    ] == ["glyphs", "text", "labels"]
    for _command, kwargs in conversions[1:]:
        environment = kwargs["env"]
        lff_path = Path(environment["BCS_LIBRECAD_UNICODE_LFF"])
        assert lff_path.is_file()
        assert "# Format:            LibreCAD Font 1" in lff_path.read_text(
            encoding="utf-8"
        )
        executable_path = Path(environment["BCS_LIBRECAD_EXECUTABLE"])
        assert executable_path == tmp_path / "LibreCAD.exe"
        assert executable_path.is_file()


def test_native_delivery_validation_rejects_report_handle_missing_from_reopened_dxf(
    tmp_path,
) -> None:
    executable = tmp_path / "LibreCAD.exe"
    executable.write_bytes(b"MZ")
    lff = tmp_path / "resources" / "fonts" / "unicode.lff"
    smoke_portable_zip._write_synthetic_librecad_lff(lff)
    output = tmp_path / "native.dxf"
    _write_native_delivery(
        output,
        requested="text",
        executable=executable,
        lff=lff,
        reported_handle="DEADBEEF",
    )

    with pytest.raises(SystemExit, match="missing or dead DXF TEXT handle"):
        smoke_portable_zip._validate_representation_delivery(
            output.with_name("native_import_report.json"),
            requested="text",
            final="text",
            fallback_used=False,
            dxf_path=output,
            expected_executable=executable,
            expected_lff=lff,
        )

"""Regression locks for the canonical LibreCAD LLM context-pack preset."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repo_context_builder_core import ContextBuilder


ROOT = Path(__file__).resolve().parents[1]
PRESET_PATH = ROOT / "0build_master_output_1LC-PDFimporter.py"


def _load_preset() -> dict:
    spec = importlib.util.spec_from_file_location("librecad_context_preset", PRESET_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PRESET


def _configured_paths(preset: dict) -> set[str]:
    configured = set()
    for key in (
        "config_paths",
        "script_paths",
        "source_roots",
        "test_roots",
        "dependency_files",
        "tree_full_depth_roots",
        "navigation_roots",
    ):
        configured.update(preset.get(key, []))
    configured.update(preset.get("tree_shallow_depth_roots", {}))
    for paths in preset.get("expected_files", {}).values():
        configured.update(paths)
    return configured


def test_context_builder_directory_exclusions_support_standard_globs(tmp_path) -> None:
    for directory in (
        "lib",
        "lib.stage.0123456789abcdef",
        "lib.backup.0123456789abcdef",
        "pdf2dxf.egg-info",
        "kept",
    ):
        root = tmp_path / directory
        root.mkdir()
        (root / "marker.py").write_text("MARKER = True\n", encoding="utf-8")

    builder = ContextBuilder(
        {
            "project_root": str(tmp_path),
            "exclude_dir_names": [
                "lib",
                "lib.stage.*",
                "lib.backup.*",
                "*.egg-info",
            ],
        }
    )

    assert builder.is_excluded_dir(tmp_path / "lib")
    assert builder.is_excluded_dir(tmp_path / "lib.stage.0123456789abcdef")
    assert builder.is_excluded_dir(tmp_path / "lib.backup.0123456789abcdef")
    assert builder.is_excluded_dir(tmp_path / "pdf2dxf.egg-info")
    assert not builder.is_excluded_dir(tmp_path / "library")
    assert not builder.is_excluded_dir(tmp_path / "lib.stage")

    collected = {
        path.relative_to(tmp_path).as_posix()
        for path in builder.collect_files(["."])
    }
    assert collected == {"kept/marker.py"}

    inventory_names = {name for name, _metric, _is_dir in builder.top_level_inventory()}
    assert inventory_names == {"kept/"}

    tree = "\n".join(builder._build_tree_lines())
    assert "kept/" in tree
    assert "lib.stage." not in tree
    assert "lib.backup." not in tree
    assert "pdf2dxf.egg-info" not in tree


def test_canonical_context_preset_has_no_dangling_paths_and_collects_runtime_surfaces() -> None:
    preset = _load_preset()
    missing = sorted(
        relative
        for relative in _configured_paths(preset)
        if relative == "." or not (ROOT / relative).exists()
    )
    assert missing == []

    assert {"lib", "lib.stage.*", "lib.backup.*"} <= set(
        preset["exclude_dir_names"]
    )

    builder = ContextBuilder({**preset, "project_root": str(ROOT)})
    collected = {
        path.relative_to(ROOT).as_posix()
        for path in (
            *builder.collect_named_files(preset["config_paths"]),
            *builder.collect_named_files(preset["script_paths"]),
            *builder.collect_files(preset["source_roots"]),
        )
    }
    required_surfaces = {
        ".github/workflows/auto-release.yml",
        ".github/workflows/lc-pdfimporter-ci.yml",
        "LICENSE",
        "THIRD_PARTY_LICENSES.md",
        "build_release.py",
        "build_standalone.py",
        "build_windows_portable.py",
        "installer/librecad-pdf-importer.iss",
        "librecad_pdf_importer/runtime_self_test.py",
        "pdf2dxf.py",
        "preflight_check.py",
        "pyproject.toml",
        "release_notices.py",
        "requirements.txt",
        "scripts/smoke_portable_zip.py",
        "standalone_app.py",
        "third_party/fonttools/LICENSE",
        "third_party/fonttools/LICENSE.external",
        "tools/fetch_runtime_wheels.ps1",
    }

    assert required_surfaces <= collected

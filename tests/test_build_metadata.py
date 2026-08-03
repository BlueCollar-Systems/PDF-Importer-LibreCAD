from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import build_release
import build_standalone
import build_windows_portable


@pytest.mark.parametrize(
    "reader",
    [
        build_release._read_version,
        build_standalone._read_version,
        build_windows_portable.read_version,
    ],
)
def test_release_builders_share_the_exact_product_version(reader) -> None:
    assert reader() == "1.0.80"


def test_source_release_refuses_to_publish_an_unknown_version() -> None:
    with patch.object(build_release.Path, "read_text", return_value="no version here"):
        with pytest.raises(RuntimeError, match="Could not read __version__"):
            build_release._read_version()


def test_standalone_release_refuses_to_publish_an_unknown_version() -> None:
    with patch.object(build_standalone.Path, "read_text", return_value="no version here"):
        with pytest.raises(RuntimeError, match="Could not read __version__"):
            build_standalone._read_version()


def test_source_release_excludes_cross_repository_workspace_tools() -> None:
    assert not build_release._should_include("pdfcadcore_sync_check.py")
    assert not build_release._should_include("pdfcadcore_sync_manifest.json")


def test_portable_upgrade_guidance_uses_only_bundled_commands() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    upgrade = readme.split("## Upgrading / skipping versions", 1)[1].split(
        "### Source ZIP fallback", 1
    )[0]
    assert "preflight_check.py" not in upgrade
    assert ".\\pdf2dxf.exe" in upgrade


def test_documented_host_baseline_and_portable_plugin_paths_are_consistent() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    compatibility = Path("COMPATIBILITY.md").read_text(encoding="utf-8")
    plugin_readme = Path("plugin/README.md").read_text(encoding="utf-8")
    plugin_source = Path("plugin/lcpdf_menu/lcpdf_menu.cpp").read_text(
        encoding="utf-8"
    )

    assert "LibreCAD 2.2+" in readme
    assert "**LibreCAD 2.2+**" in compatibility
    assert "C:\\1PDF-Importer" not in compatibility
    assert "C:/1PDF-Importer" not in plugin_readme
    assert "C:/1PDF-Importer" not in plugin_source


def test_resume_guidance_discloses_native_runtime_binding_identity() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    resume = readme.split("Resume identity includes", 1)[1].split(
        "Force raster mode", 1
    )[0]
    assert "LibreCAD executable" in resume
    assert "LFF" in resume
    assert "SHA-256" in resume

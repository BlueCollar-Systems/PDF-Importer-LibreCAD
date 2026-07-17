"""Regression locks for deterministic, host-independent CI fixtures."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_declares_the_free_fonttools_dependency() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert re.search(
        r'^\s*"fonttools>=4\.50,<5\.0"\s*,?\s*$',
        project,
        flags=re.MULTILINE | re.IGNORECASE,
    )


def test_tests_do_not_hardcode_an_owner_desktop_pdf_path() -> None:
    home_patterns = (
        re.compile(r"^[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", re.I),
        re.compile(r"^/(?:home|Users)/[^/]+/", re.I),
    )
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if any(pattern.match(node.value) for pattern in home_patterns):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []


def test_lower_bound_tests_never_bypass_the_pymupdf_import_fallback() -> None:
    offenders = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            module_name = node.args[0]
            if not (
                isinstance(module_name, ast.Constant)
                and module_name.value == "pymupdf"
            ):
                continue
            bypasses_fallback = (
                isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
            ) or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pytest"
                and node.func.attr == "importorskip"
            )
            if bypasses_fallback:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert offenders == []


def test_synthetic_delivery_items_use_the_controlled_test_font() -> None:
    source = (ROOT / "tests" / "test_representation_delivery_contract.py").read_text(
        encoding="utf-8"
    )

    assert 'font_name="BCS Deterministic Test"' in source
    assert re.search(r'^\s*font_name="Arial"', source, flags=re.MULTILINE) is None


def test_supplied_pdf_locator_resolves_an_explicit_fixture_root(
    monkeypatch,
    tmp_path,
) -> None:
    from conftest import _supplied_pdf

    fixture = tmp_path / "Welding-Symbol-Chart.pdf"
    fixture.write_bytes(b"fixture")
    monkeypatch.setenv("BCS_PDF_TEST_FILES", str(tmp_path))

    assert _supplied_pdf(fixture.name) == fixture.resolve()


def test_supplied_pdf_locator_visible_skips_when_fixture_is_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    from conftest import _supplied_pdf

    monkeypatch.delenv("BCS_PDF_TEST_FILES", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with pytest.raises(pytest.skip.Exception, match="set BCS_PDF_TEST_FILES"):
        _supplied_pdf("not-present.pdf")


def test_every_runtime_distribution_path_includes_fonttools() -> None:
    standalone = (ROOT / "build_standalone.py").read_text(encoding="utf-8")
    portable = (ROOT / "build_windows_portable.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    dependencies = (
        ROOT / "librecad_pdf_importer" / "dependency_manager.py"
    ).read_text(encoding="utf-8")
    fetch_script = (ROOT / "tools" / "fetch_runtime_wheels.ps1").read_text(
        encoding="utf-8"
    )

    assert "fonttools>=4.50,<5.0" in requirements.lower()
    assert "matplotlib>=3.7,<4.0" in requirements.lower()
    assert "load_runtime_requirements(ROOT)" in standalone
    assert '"--collect-all", "fonttools"' in standalone.lower()
    assert '"--copy-metadata", "fonttools"' in standalone.lower()
    assert "load_runtime_requirements(ROOT)" in portable
    assert 'collect_all = ["fonttools"]' in portable.lower()
    assert 'copy_metadata = ["fonttools"]' in portable.lower()
    assert "load_runtime_requirements(PROJECT_ROOT)" in dependencies
    assert "def check_fonttools()" in dependencies
    assert "preflight_check.py" in fetch_script
    assert "--install" in fetch_script


def test_fonttools_runtime_and_license_are_documented_truthfully() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")

    assert "FontTools >=4.50,<5.0" in readme
    assert "FontTools" in install
    assert "| FontTools | >=4.50,<5.0 | MIT |" in notices
    assert "https://github.com/fonttools/fonttools" in notices


def test_source_release_never_opportunistically_bundles_a_partial_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    import build_release

    assert build_release._should_include("lib/fontTools/__init__.py") is False

    project = tmp_path / "project"
    project.mkdir()
    (project / "pdf2dxf.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    for relative in (
        "tools/fetch_runtime_wheels.ps1",
        "third_party/fonttools/LICENSE",
        "lib/fontTools/__init__.py",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    monkeypatch.setattr(build_release, "_PROJECT_ROOT", project)
    archive = build_release.build(str(tmp_path / "dist"))
    with zipfile.ZipFile(archive) as source_zip:
        names = set(source_zip.namelist())

    assert "tools/fetch_runtime_wheels.ps1" in names
    assert "third_party/fonttools/LICENSE" in names
    assert "lib/fontTools/__init__.py" not in names


def test_ci_does_not_swallow_shared_core_failures_or_cancel_sibling_versions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "lc-pdfimporter-ci.yml").read_text(
        encoding="utf-8"
    )

    assert "fail-fast: false" in workflow
    assert '|| echo "No tests yet"' not in workflow
    assert "cd pdfcadcore" not in workflow


def test_controlled_font_bytes_and_ascii_space_are_deterministic(tmp_path) -> None:
    from fontTools.ttLib import TTFont
    from conftest import _build_deterministic_test_font

    first = tmp_path / "first.ttf"
    second = tmp_path / "second.ttf"
    _build_deterministic_test_font(first)
    _build_deterministic_test_font(second)

    assert first.read_bytes() == second.read_bytes()
    font = TTFont(first, lazy=False, recalcTimestamp=False)
    assert font["head"].created == 2_082_844_800
    assert font["head"].modified == 2_082_844_800
    assert font.getBestCmap()[32] == "space"
    assert font["glyf"]["space"].numberOfContours == 0
    cmap = font.getBestCmap()
    glyphs = font["glyf"]
    a_coordinates = tuple(glyphs[cmap[ord("A")]].getCoordinates(glyphs)[0])
    b_coordinates = tuple(glyphs[cmap[ord("B")]].getCoordinates(glyphs)[0])
    assert a_coordinates != b_coordinates
    font.close()


def test_checked_in_fonttools_notices_are_complete_and_user_visible() -> None:
    license_text = (ROOT / "third_party" / "fonttools" / "LICENSE").read_text(
        encoding="utf-8"
    )
    external = (
        ROOT / "third_party" / "fonttools" / "LICENSE.external"
    ).read_text(encoding="utf-8")

    assert "Copyright (c) 2017 Just van Rossum" in license_text
    assert "Permission is hereby granted, free of charge" in license_text
    assert "SIL OPEN FONT LICENSE Version 1.1" in external


def test_inno_installer_requires_the_current_version_define() -> None:
    installer = (
        ROOT / "installer" / "librecad-pdf-importer.iss"
    ).read_text(encoding="utf-8")
    builder = (ROOT / "build_standalone.py").read_text(encoding="utf-8")

    assert re.search(r'#define\s+AppVersion\s+"\d+\.\d+\.\d+"', installer) is None
    assert re.search(r'/DAppVersion=\d+\.\d+\.\d+', installer) is None
    assert "#error" in installer
    assert "/DAppVersion=" in installer
    assert "/DAppVersion={version}" in builder


def test_runtime_wheel_fetch_delegates_to_the_canonical_fail_closed_installer() -> None:
    wrapper = (ROOT / "tools" / "fetch_runtime_wheels.ps1").read_text(
        encoding="utf-8"
    )
    installer = (
        ROOT / "librecad_pdf_importer" / "dependency_manager.py"
    ).read_text(encoding="utf-8")

    assert "preflight_check.py" in wrapper
    assert "--install" in wrapper
    assert "$LASTEXITCODE -ne 0" in wrapper
    assert "pip install" not in wrapper
    assert '"-I"' in installer and '"-S"' in installer
    assert installer.index("subprocess.check_call(") < installer.index(
        "stage_dir.rename(lib_dir)"
    )
    assert "lib.backup." in installer
    assert "load_runtime_dependencies" in installer

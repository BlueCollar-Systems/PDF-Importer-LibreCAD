"""Behavioral locks for complete source, portable, and frozen runtimes."""

from __future__ import annotations

import ast
import builtins
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import build_standalone
import build_windows_portable
from librecad_pdf_importer import dependency_manager
from librecad_pdf_importer.runtime_self_test import load_fonttools_dependencies
from release_notices import copy_python_distribution_notices
from scripts import smoke_portable_zip


def test_fonttools_probe_imports_every_production_api(monkeypatch) -> None:
    imported = set()
    original_import = builtins.__import__

    def tracking_import(name, *args, **kwargs):
        imported.add(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracking_import)
    load_fonttools_dependencies()

    minimum_expected = {
        "fontTools.agl",
        "fontTools.cffLib",
        "fontTools.fontBuilder",
        "fontTools.pens.basePen",
        "fontTools.pens.boundsPen",
        "fontTools.pens.ttGlyphPen",
        "fontTools.ttLib",
        "fontTools.ttLib.tables._c_m_a_p",
    }
    assert minimum_expected <= imported

    root = Path(__file__).resolve().parents[1]
    production_modules = set()
    production_paths = [*root.glob("*.py")]
    production_paths.extend((root / "pdfcadcore").rglob("*.py"))
    production_paths.extend((root / "librecad_pdf_importer").rglob("*.py"))
    for path in production_paths:
        if path.name == "runtime_self_test.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith(
                "fontTools"
            ):
                production_modules.add(str(node.module))
            elif isinstance(node, ast.Import):
                production_modules.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("fontTools")
                )

    assert production_modules <= imported


def test_dependency_installer_requests_and_verifies_fonttools(
    monkeypatch,
    tmp_path,
) -> None:
    commands = []
    monkeypatch.setattr(dependency_manager, "get_lib_dir", lambda: tmp_path / "lib")
    monkeypatch.setattr(
        dependency_manager.subprocess,
        "check_call",
        lambda command, **_kwargs: commands.append(command),
    )

    assert dependency_manager.install_runtime_deps() is True
    assert 'fonttools>=4.50,<5.0' in commands[0]
    assert commands[1][1:3] == ["-I", "-S"]
    assert not list(tmp_path.glob("lib.stage.*"))
    assert not list(tmp_path.glob("lib.backup.*"))


def test_dependency_install_probe_failure_preserves_the_prior_runtime(
    monkeypatch,
    tmp_path,
) -> None:
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    marker = lib_dir / "known-good.txt"
    marker.write_text("prior runtime", encoding="utf-8")
    calls = 0

    def fail_probe(_command, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise subprocess.CalledProcessError(1, "probe")

    monkeypatch.setattr(dependency_manager, "get_lib_dir", lambda: lib_dir)
    monkeypatch.setattr(dependency_manager.subprocess, "check_call", fail_probe)

    assert dependency_manager.install_runtime_deps() is False
    assert marker.read_text(encoding="utf-8") == "prior runtime"
    assert not list(tmp_path.glob("lib.stage.*"))
    assert not list(tmp_path.glob("lib.backup.*"))


def test_dependency_diagnostics_fail_closed_when_fonttools_is_missing(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(dependency_manager, "check_pymupdf", lambda: True)
    monkeypatch.setattr(dependency_manager, "check_ezdxf", lambda: True)
    monkeypatch.setattr(dependency_manager, "check_fonttools", lambda: False)

    assert dependency_manager.print_diagnostics() == 1
    output = capsys.readouterr().out
    assert "FontTools: MISSING" in output
    assert '"fonttools>=4.50,<5.0"' in output


def test_dependency_install_timeout_returns_a_clean_failure(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setattr(dependency_manager, "get_lib_dir", lambda: tmp_path / "lib")

    def time_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("pip", 300)

    monkeypatch.setattr(dependency_manager.subprocess, "check_call", time_out)

    assert dependency_manager.install_runtime_deps() is False
    assert "Dependency install failed" in capsys.readouterr().out


def test_portable_pyinstaller_command_collects_fonttools(monkeypatch, tmp_path) -> None:
    commands = []
    entrypoint = tmp_path / "entry.py"
    entrypoint.write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr(
        build_windows_portable.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    build_windows_portable.run_pyinstaller(
        "lcpdf-import",
        entrypoint,
        "console",
        Path("python"),
    )

    command = commands[0]
    assert ["--collect-all", "fontTools"] == command[
        command.index("--collect-all") : command.index("--collect-all") + 2
    ]
    assert ["--copy-metadata", "fonttools"] == command[
        command.index("--copy-metadata") : command.index("--copy-metadata") + 2
    ]


def test_standalone_builder_collects_fonttools_copies_notices_and_self_tests(
    monkeypatch,
    tmp_path,
) -> None:
    commands = []
    app_dist = tmp_path / "dist" / build_standalone.APP_NAME
    monkeypatch.setattr(build_standalone, "APP_DIST", app_dist)
    monkeypatch.setattr(build_standalone, "DIST_ROOT", tmp_path / "dist")
    monkeypatch.setattr(build_standalone, "WORK_ROOT", tmp_path / "build" / "work")
    monkeypatch.setattr(build_standalone, "SPEC_ROOT", tmp_path / "build" / "spec")
    monkeypatch.setattr(build_standalone, "ICON", tmp_path / "missing.ico")
    monkeypatch.setattr(build_standalone, "_build_python", lambda: Path("python"))
    monkeypatch.setattr(
        build_standalone,
        "copy_python_distribution_notices",
        lambda *_args, **_kwargs: tmp_path / "licenses" / "PYTHON_DISTRIBUTIONS.md",
    )

    def fake_run(command, **_kwargs):
        commands.append(command)
        if "PyInstaller" in command:
            app_dist.mkdir(parents=True, exist_ok=True)
            (app_dist / f"{build_standalone.APP_NAME}.exe").write_bytes(b"exe")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(build_standalone.subprocess, "run", fake_run)

    assert build_standalone.main() == 0
    pyinstaller = commands[0]
    assert ["--collect-all", "fontTools"] == pyinstaller[
        pyinstaller.index("--collect-all", pyinstaller.index("--collect-all") + 1) :
        pyinstaller.index("--collect-all", pyinstaller.index("--collect-all") + 1) + 2
    ]
    assert ["--copy-metadata", "fonttools"] == pyinstaller[
        pyinstaller.index("--copy-metadata") : pyinstaller.index("--copy-metadata") + 2
    ]
    assert commands[-1][-1] == "--self-test"
    assert (app_dist / "THIRD_PARTY_LICENSES.md").is_file()
    assert (app_dist / "licenses" / "FontTools" / "LICENSE").is_file()
    assert (app_dist / "licenses" / "FontTools" / "LICENSE.external").is_file()


def test_build_environment_inventory_copies_exact_notices_and_versions(tmp_path) -> None:
    site_packages = tmp_path / "site-packages"
    destination = tmp_path / "portable"
    distributions = (
        ("PyInstaller", "6.21.0", "GPL-2.0-or-later WITH Bootloader-exception"),
        ("PyMuPDF", "1.24.0", "AGPL-3.0-only"),
        ("ezdxf", "1.1.0", "MIT"),
        ("fonttools", "4.50.0", "MIT"),
        ("matplotlib", "3.7.0", "PSF-based"),
        ("numpy", "1.26.4", "BSD-3-Clause"),
        ("pyparsing", "3.1.0", "MIT"),
        ("typing_extensions", "4.6.0", "PSF-2.0"),
    )
    for name, version, license_expression in distributions:
        dist_info = site_packages / f"{name}-{version}.dist-info"
        license_path = dist_info / "licenses" / "LICENSE"
        license_path.parent.mkdir(parents=True)
        (dist_info / "METADATA").write_text(
            "\n".join(
                (
                    "Metadata-Version: 2.4",
                    f"Name: {name}",
                    f"Version: {version}",
                    f"License-Expression: {license_expression}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (dist_info / "RECORD").write_text(
            f"{dist_info.name}/licenses/LICENSE,,\n",
            encoding="utf-8",
        )
        license_path.write_text(f"Exact notice for {name}\n", encoding="utf-8")

    manifest_path = copy_python_distribution_notices(site_packages, destination)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema"] == "bcs.python_distribution_notices/1.0"
    assert {item["name"] for item in manifest["distributions"]} == {
        item[0] for item in distributions
    }
    assert all(item["notices"] for item in manifest["distributions"])
    assert (destination / "licenses" / "PYTHON_DISTRIBUTIONS.md").is_file()
    for item in manifest["distributions"]:
        for relative in item["notices"]:
            assert (destination / relative).is_file()


def test_portable_smoke_requires_dynamic_python_notice_inventory() -> None:
    assert "licenses/PYTHON_DISTRIBUTIONS.md" in smoke_portable_zip.REQUIRED_NOTICES
    assert "licenses/python-distributions.json" in smoke_portable_zip.REQUIRED_NOTICES


def test_runtime_probe_imports_the_complete_ezdxf_text_production_surface() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "librecad_pdf_importer"
        / "runtime_self_test.py"
    ).read_text(encoding="utf-8")

    assert "from ezdxf.addons import text2path" in source
    assert "from ezdxf.fonts import fonts as ezdxf_fonts" in source
    assert "from ezdxf.fonts.font_face import FontFace" in source
    assert "Matplotlib" in source

    dependency_manager_source = (
        Path(__file__).resolve().parents[1]
        / "librecad_pdf_importer"
        / "dependency_manager.py"
    ).read_text(encoding="utf-8")
    assert "from ezdxf.fonts import fonts as ezdxf_fonts" in dependency_manager_source
    assert "from ezdxf.fonts.font_face import FontFace" in dependency_manager_source


def test_portable_self_test_timeout_fails_closed(monkeypatch, tmp_path) -> None:
    executable = tmp_path / "pdf2dxf.exe"
    monkeypatch.setattr(
        smoke_portable_zip.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("pdf2dxf.exe", 120)
        ),
    )

    with __import__("pytest").raises(SystemExit, match="timed out after 120s"):
        smoke_portable_zip._run_self_test(executable)

"""Exercise the wheel from outside the checkout, as a source-install user does."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile

import pymupdf


def test_installed_wheel_opens_and_converts_without_checkout_modules(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    for name in ("pyproject.toml", "README.md", "LICENSE", "requirements.txt"):
        shutil.copy2(root / name, source / name)
    for name in metadata["tool"]["setuptools"]["py-modules"]:
        shutil.copy2(root / f"{name}.py", source / f"{name}.py")
    for name in ("pdfcadcore", "librecad_pdf_importer"):
        shutil.copytree(root / name, source / name, ignore=shutil.ignore_patterns("__pycache__"))
    wheels = tmp_path / "wheels"
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
         "--wheel-dir", str(wheels)],
        cwd=source, capture_output=True, text=True, timeout=180,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    installed = tmp_path / "installed"
    with zipfile.ZipFile(next(wheels.glob("*.whl"))) as wheel:
        wheel.extractall(installed)
    drawing = tmp_path / "drawing.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=144, height=144)
        page.draw_line((20, 20), (100, 100))
        doc.save(drawing)
    output = tmp_path / "drawing.dxf"
    probe = """
import sys
sys.path.insert(0, sys.argv[1])
from librecad_pdf_importer import dependency_manager
from runtime_requirements import load_runtime_requirements
from pdf_open_guard import precheck_pdf
import pdf2dxf
assert len(load_runtime_requirements()) == 5
assert precheck_pdf(sys.argv[2]) == 1
raise SystemExit(pdf2dxf.main([sys.argv[2], sys.argv[3], '--no-import-text']))
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(installed), str(drawing), str(output)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    import ezdxf

    assert len(ezdxf.readfile(output).modelspace()) > 0
    assert output.with_name("drawing_import_report.json").is_file()

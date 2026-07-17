"""Copy required visible license notices into distributable runtime folders."""

from __future__ import annotations

from importlib.metadata import Distribution
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil


NOTICE_FILES = (
    ("LICENSE", "LICENSE"),
    ("THIRD_PARTY_LICENSES.md", "THIRD_PARTY_LICENSES.md"),
    ("third_party/fonttools/LICENSE", "licenses/FontTools/LICENSE"),
    (
        "third_party/fonttools/LICENSE.external",
        "licenses/FontTools/LICENSE.external",
    ),
)

REQUIRED_PYTHON_DISTRIBUTIONS = frozenset(
    {
        "pyinstaller",
        "pymupdf",
        "ezdxf",
        "fonttools",
        "numpy",
        "pyparsing",
        "typing-extensions",
    }
)


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name).strip()).lower()


def _is_notice_file(relative: PurePosixPath) -> bool:
    filename = relative.name.lower()
    return filename.startswith(("license", "licence", "copying", "notice"))


def _markdown_cell(value: object) -> str:
    return str(value or "not declared").replace("|", "\\|").replace("\n", " ")


def copy_release_notices(root: Path, destination: Path) -> tuple[Path, ...]:
    copied = []
    for source_relative, destination_relative in NOTICE_FILES:
        source = root / source_relative
        if not source.is_file():
            raise RuntimeError(f"required release notice is missing: {source_relative}")
        target = destination / destination_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(target)
    return tuple(copied)


def copy_python_distribution_notices(
    site_packages: Path,
    destination: Path,
) -> Path:
    """Inventory an isolated build venv and copy its exact packaged notices."""

    site_packages = Path(site_packages).resolve()
    if not site_packages.is_dir():
        raise RuntimeError(f"build site-packages directory is missing: {site_packages}")

    licenses_root = Path(destination) / "licenses"
    python_root = licenses_root / "Python"
    python_root.mkdir(parents=True, exist_ok=True)
    entries = []
    seen = set()

    distributions = sorted(
        Distribution.discover(path=[str(site_packages)]),
        key=lambda dist: _canonical_distribution_name(dist.metadata.get("Name") or ""),
    )
    for distribution in distributions:
        name = str(distribution.metadata.get("Name") or "").strip()
        version = str(distribution.version or "").strip()
        canonical = _canonical_distribution_name(name)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        notice_paths = []
        for packaged_file in distribution.files or ():
            relative = PurePosixPath(str(packaged_file).replace("\\", "/"))
            if ".." in relative.parts or not _is_notice_file(relative):
                continue
            source = Path(distribution.locate_file(packaged_file)).resolve()
            if not source.is_file() or not source.is_relative_to(site_packages):
                continue
            target = python_root / f"{canonical}-{version}" / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            notice_paths.append(target.relative_to(destination).as_posix())

        entries.append(
            {
                "name": name,
                "canonical_name": canonical,
                "version": version,
                "license_expression": distribution.metadata.get("License-Expression"),
                "license": distribution.metadata.get("License"),
                "homepage": distribution.metadata.get("Home-page"),
                "notices": sorted(set(notice_paths)),
            }
        )

    missing = sorted(REQUIRED_PYTHON_DISTRIBUTIONS - seen)
    if missing:
        raise RuntimeError(
            "isolated build environment is missing required distributions: "
            + ", ".join(missing)
        )
    without_notices = sorted(
        entry["canonical_name"]
        for entry in entries
        if entry["canonical_name"] in REQUIRED_PYTHON_DISTRIBUTIONS
        and not entry["notices"]
    )
    if without_notices:
        raise RuntimeError(
            "required distributions contain no packaged license notice: "
            + ", ".join(without_notices)
        )

    manifest = {
        "schema": "bcs.python_distribution_notices/1.0",
        "scope": (
            "all Python distributions installed in the isolated Windows build "
            "environment; some are build tools rather than frozen runtime modules"
        ),
        "distributions": entries,
    }
    manifest_path = licenses_root / "python-distributions.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Exact Python Distribution Notices",
        "",
        "Generated from the isolated build environment. This intentionally includes",
        "build tools as well as runtime distributions so transitive dependency and",
        "PyInstaller bootloader notices cannot silently disappear.",
        "",
        "| Distribution | Exact version | Declared license | Copied notices |",
        "|---|---:|---|---:|",
    ]
    for entry in entries:
        declared_license = entry["license_expression"] or entry["license"]
        lines.append(
            "| {name} | {version} | {license} | {count} |".format(
                name=_markdown_cell(entry["name"]),
                version=_markdown_cell(entry["version"]),
                license=_markdown_cell(declared_license),
                count=len(entry["notices"]),
            )
        )
    markdown_path = licenses_root / "PYTHON_DISTRIBUTIONS.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path

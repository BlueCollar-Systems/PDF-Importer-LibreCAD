#!/usr/bin/env python3
"""Verify vendored pdfcadcore and repo_context_builder_core.py stay in sync.

FC/BL/LC embed byte-identical copies of pdfcadcore. FC is canonical. This script
fails CI when any core file drifts from the canonical hash manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "pdfcadcore_sync_manifest.json"

REPO_CORE_DIRS: Dict[str, Path] = {
    "FC": SCRIPT_DIR / "PDFVectorImporter" / "pdfcadcore",
    "BL": Path(r"C:\1BL-PDFimporter") / "pdf_vector_importer" / "pdfcadcore",
    "LC": Path(r"C:\1LC-PDFimporter") / "pdfcadcore",
}

REPO_CONTEXT_BUILDER_PATHS: Tuple[Path, ...] = (
    Path(r"C:\1 Structural_Steel_Shapes_App") / "repo_context_builder_core.py",
    Path(r"C:\1BlueCollar-Website") / "repo_context_builder_core.py",
    Path(r"C:\1SU-PDFimporter") / "repo_context_builder_core.py",
    Path(r"C:\1BL-PDFimporter") / "repo_context_builder_core.py",
    Path(r"C:\1FC-PDFimporter") / "repo_context_builder_core.py",
    Path(r"C:\1LC-PDFimporter") / "repo_context_builder_core.py",
)

# No intentional divergences: all repos must match the canonical manifest exactly.
# A real per-repo difference must be recorded with its own expected hash, never a blind skip.
KNOWN_DIVERGENCES: Dict[str, Tuple[str, ...]] = {}


def sha256_file(path: Path) -> str:
    """Hash file content with line endings normalized (CRLF -> LF).

    The repos store LF via .gitattributes, but local tools sometimes leave
    CRLF working copies while CI checkouts are LF. Hashing normalized bytes
    keeps the manifest stable across both, so EOL churn can never read as
    core drift (same lesson as the corpus-level checker, 2026-06-08).
    """
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().lower()


def load_manifest() -> Dict[str, str]:
    if not MANIFEST_PATH.is_file():
        raise SystemExit(f"Missing manifest: {MANIFEST_PATH}")
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {str(k): str(v).lower() for k, v in data.items()}


def detect_local_repo() -> Optional[str]:
    if (SCRIPT_DIR / "PDFVectorImporter" / "pdfcadcore").is_dir():
        return "FC"
    if (SCRIPT_DIR / "pdf_vector_importer" / "pdfcadcore").is_dir():
        return "BL"
    if (SCRIPT_DIR / "pdfcadcore").is_dir() and (SCRIPT_DIR / "dxf_builder.py").is_file():
        return "LC"
    return None


def iter_core_files(core_dir: Path) -> Iterable[Path]:
    for path in sorted(core_dir.glob("*.py")):
        if path.name.startswith("."):
            continue
        yield path


def check_repo_core(
    repo: str,
    core_dir: Path,
    manifest: Dict[str, str],
    fix: bool,
    canonical_dir: Path,
) -> List[str]:
    errors: List[str] = []
    allowed = set(KNOWN_DIVERGENCES.get(repo, ()))

    if not core_dir.is_dir():
        return [f"{repo}: missing core directory {core_dir}"]

    for path in iter_core_files(core_dir):
        name = path.name
        if name not in manifest:
            errors.append(f"{repo}: unexpected core file not in manifest: {name}")
            continue

        actual = sha256_file(path)
        expected = manifest[name]
        if actual == expected:
            continue

        if name in allowed:
            print(f"NOTE: {repo}/{name} differs from canonical (expected divergence)")
            continue

        errors.append(
            f"{repo}/{name}: hash mismatch (expected {expected[:12]}..., got {actual[:12]}...)"
        )
        if fix and repo != "FC":
            src = canonical_dir / name
            if src.is_file():
                shutil.copy2(src, path)
                print(f"FIXED: copied canonical {name} -> {path}")

    # A manifest file absent from the embedded copy is drift too — without
    # this, a newly added core module can silently never ship to a host.
    present = {p.name for p in iter_core_files(core_dir)}
    for name in sorted(set(manifest) - present - {"repo_context_builder_core.py"}):
        errors.append(f"{repo}: missing core file listed in manifest: {name}")
        if fix and repo != "FC":
            src = canonical_dir / name
            if src.is_file():
                shutil.copy2(src, core_dir / name)
                print(f"FIXED: copied canonical {name} -> {core_dir / name}")

    return errors


def check_repo_context_builder(manifest: Dict[str, str]) -> List[str]:
    key = "repo_context_builder_core.py"
    if key not in manifest:
        return [f"manifest missing {key}"]

    expected = manifest[key]
    existing: List[Tuple[Path, str]] = []
    for path in REPO_CONTEXT_BUILDER_PATHS:
        if path.is_file():
            existing.append((path, sha256_file(path)))

    if not existing:
        print(f"SKIP: no {key} files found (single-repo checkout?)")
        return []

    unique = {digest for _, digest in existing}
    if len(unique) == 1 and unique.pop() == expected:
        print(f"OK: {key} in sync across {len(existing)} repos")
        return []

    errors: List[str] = []
    for path, digest in existing:
        if digest != expected:
            errors.append(
                f"{path}: hash mismatch (expected {expected[:12]}..., got {digest[:12]}...)"
            )
    if len(unique) > 1:
        errors.append(f"{key}: cross-repo drift among {len(existing)} copies")
    return errors


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Copy canonical FC files into drifted BL/LC copies (local dev only).",
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Rewrite pdfcadcore_sync_manifest.json from canonical FC pdfcadcore.",
    )
    parser.add_argument(
        "--skip-cross-repo",
        action="store_true",
        help="Only validate the current repo against the manifest.",
    )
    args = parser.parse_args(argv)

    canonical_dir = REPO_CORE_DIRS["FC"]
    if args.write_manifest:
        manifest: Dict[str, str] = {}
        for path in iter_core_files(canonical_dir):
            manifest[path.name] = sha256_file(path)
        rcb = SCRIPT_DIR / "repo_context_builder_core.py"
        if rcb.is_file():
            manifest["repo_context_builder_core.py"] = sha256_file(rcb)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote manifest: {MANIFEST_PATH}")
        for repo, core_dir in REPO_CORE_DIRS.items():
            if repo == "FC":
                continue
            repo_root = core_dir.parents[1] if repo == "BL" else core_dir.parent
            dest_manifest = repo_root / "pdfcadcore_sync_manifest.json"
            if repo_root.is_dir():
                dest_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                print(f"Copied manifest -> {dest_manifest}")
        return 0

    manifest = load_manifest()
    errors: List[str] = []

    local_repo = detect_local_repo()
    if local_repo:
        core_dir = REPO_CORE_DIRS[local_repo]
        if not core_dir.is_dir():
            # Fall back to path relative to script for CI checkout layout.
            if local_repo == "FC":
                core_dir = SCRIPT_DIR / "PDFVectorImporter" / "pdfcadcore"
            elif local_repo == "BL":
                core_dir = SCRIPT_DIR / "pdf_vector_importer" / "pdfcadcore"
            else:
                core_dir = SCRIPT_DIR / "pdfcadcore"
        errors.extend(check_repo_core(local_repo, core_dir, manifest, args.fix, canonical_dir))
    else:
        print("WARN: could not detect local repo layout")

    if not args.skip_cross_repo:
        for repo, core_dir in REPO_CORE_DIRS.items():
            if local_repo and repo == local_repo:
                continue
            if core_dir.is_dir():
                errors.extend(check_repo_core(repo, core_dir, manifest, args.fix, canonical_dir))

    errors.extend(check_repo_context_builder(manifest))

    if errors:
        print("DRIFT DETECTED:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("ALL IN SYNC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""release_safety.py — bound stranded-release warnings without blocking fixes.

Round 21 Task 5: a small canonical gate that makes the existing-tag "stranded
release" path explicit, stateful, and bounded.  It does not mint releases; it
only decides whether a push that leaves an existing tag un-bumped is safe.

Modes:
  audit-existing-tag    Runs when a release already exists for the current
                        version.  Records a warning on the first product push
                        past the tag, and exits 2 in release mode once the
                        acknowledgement deadline expires.
  acknowledge           Adds a version-bump plan or future-deferral record to
                        .release-safety/warnings.json.

State (.release-safety/warnings.json):
  {"schema_version":1,"warnings":[{"repo":"...","tag":"...",
    "first_seen":"<ISO-8601>","deadline":"<ISO-8601>",
    "responsible_session":"...", ("version_bump_plan":"x.y.z"|
    "release_deferred_until":"<ISO-8601>")}]}

The deadline is always first_seen + 24h.  A version_bump_plan must be acted on
before that deadline.  A release_deferred_until extends the safe window to that
future date, after which the deferral expires and the gate fails again.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

DEFAULT_EXCLUDES = [
    "*.md",
    "docs/**",
    "tests/**",
    "test/**",
    ".github/**",
    "_archived/**",
    "dist/_archived/**",
    "dev_logs/**",
    "steel_shapes/**",
    ".release-safety/**",
    "test_*.py",
    "*_test.py",
    "*_test.rb",
    "**/test_*.py",
    "**/*_test.py",
    "**/*_test.rb",
]

# ISO 8601 timestamp with timezone.
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _match_path(path: str, pattern: str) -> bool:
    """Segment-aware glob matching supporting ** and * without crossing /.

    fnmatch alone treats * as crossing path separators; this helper splits on /
    and uses ** for zero-or-more segments.
    """
    path_parts = path.replace("\\", "/").split("/")
    pat_parts = pattern.split("/")

    def _recurse(pp: list[str], ppat: list[str]) -> bool:
        if not ppat:
            return not pp
        if ppat[0] == "**":
            for k in range(len(pp) + 1):
                if _recurse(pp[k:], ppat[1:]):
                    return True
            return False
        if not pp:
            return False
        if fnmatch.fnmatch(pp[0], ppat[0]):
            return _recurse(pp[1:], ppat[1:])
        return False

    return _recurse(path_parts, pat_parts)


def is_product_path(path: str, *, exclude_patterns: Sequence[str] = DEFAULT_EXCLUDES) -> bool:
    """Return True if [path] is a product-affecting file.

    Excludes docs, tests, workflow-only changes, and CI metadata.  Keeps
    packaging/build tools (build_release.py, scripts/smoke_*.py, tools/*.py
    except test_*.py) in the product delta because those can change shipped bytes.
    """
    for pat in exclude_patterns:
        if _match_path(path, pat):
            return False
    return True


class _Completed:
    """Lightweight CompletedProcess stand-in for tests."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_git(
    repo_root: Path,
    git_command: Callable[..., _Completed],
    args: Sequence[str],
) -> _Completed:
    return git_command(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        check=True,
    )


def _git_names(tag: str, repo_root: Path, git_command: Callable[..., _Completed]) -> list[str]:
    proc = _run_git(repo_root, git_command, ["diff", "--name-only", f"{tag}..HEAD", "--", "."])
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _git_commits(
    tag: str, repo_root: Path, git_command: Callable[..., _Completed]
) -> list[tuple[str, str]]:
    proc = _run_git(repo_root, git_command, ["log", "--no-merges", "--format=%H %s", f"{tag}..HEAD"])
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        sha = parts[0]
        subject = parts[1] if len(parts) > 1 else ""
        out.append((sha, subject))
    return out


def _git_commit_files(sha: str, repo_root: Path, git_command: Callable[..., _Completed]) -> list[str]:
    proc = _run_git(repo_root, git_command, ["diff-tree", "--no-commit-id", "--name-only", "-r", sha])
    return [line for line in proc.stdout.splitlines() if line.strip()]


def collect_delta(
    tag: str,
    *,
    exclude_patterns: Sequence[str] | None = None,
    repo_root: Path | None = None,
    git_command: Callable[..., _Completed] = subprocess.run,
) -> tuple[list[str], list[str]]:
    """Return (product_files, product_commits) changed since [tag]."""
    exclude_patterns = exclude_patterns if exclude_patterns is not None else DEFAULT_EXCLUDES
    repo_root = repo_root or Path.cwd()
    files = _git_names(tag, repo_root, git_command)
    commits = _git_commits(tag, repo_root, git_command)

    product_files = [f for f in files if is_product_path(f, exclude_patterns=exclude_patterns)]
    product_commits: list[str] = []
    for sha, subject in commits:
        names = _git_commit_files(sha, repo_root, git_command)
        if any(is_product_path(n, exclude_patterns=exclude_patterns) for n in names):
            product_commits.append(f"{sha} {subject}")

    return product_files, product_commits


def _parse_iso(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_warning(w: dict) -> None:
    required = {"repo", "tag", "first_seen", "deadline"}
    missing = required - set(w.keys())
    if missing:
        raise ValueError(f"warning missing required keys: {sorted(missing)}")
    for key in ("first_seen", "deadline"):
        if not _ISO_RE.match(str(w[key])):
            raise ValueError(f"{key} is not an ISO-8601 timestamp: {w[key]!r}")
    first = _parse_iso(str(w["first_seen"]))
    deadline = _parse_iso(str(w["deadline"]))
    if deadline > first + datetime.timedelta(hours=24):
        raise ValueError(f"deadline {deadline} is more than 24h after first_seen {first}")
    if "version_bump_plan" in w and "release_deferred_until" in w:
        raise ValueError("warning has both version_bump_plan and release_deferred_until")
    if "release_deferred_until" in w:
        if not _ISO_RE.match(str(w["release_deferred_until"])):
            raise ValueError(f"release_deferred_until is not an ISO-8601 timestamp: {w['release_deferred_until']!r}")


def load_warning_record(path: Path) -> dict:
    """Load .release-safety/warnings.json or return an empty record."""
    if not path.exists():
        return {"schema_version": 1, "warnings": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("warnings.json must be a JSON object")
    if data.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
    warnings = data.get("warnings", [])
    if not isinstance(warnings, list):
        raise ValueError("warnings must be a list")
    for w in warnings:
        _validate_warning(w)
    return {"schema_version": 1, "warnings": warnings}


def _format_summary(product_files: list[str], product_commits: list[str]) -> str:
    lines = ["### Stranded product commits past existing tag"]
    lines.append("")
    lines.append("Product files changed:")
    for f in product_files:
        lines.append(f"  - {f}")
    lines.append("")
    lines.append("Product commits:")
    for c in product_commits:
        lines.append(f"  - {c}")
    return "\n".join(lines)


def evaluate_warning(
    record: dict,
    repo: str,
    tag: str,
    product_files: list[str],
    product_commits: list[str],
    now: datetime.datetime,
    session_id: str,
    release_mode: bool = False,
) -> tuple[int, str, dict]:
    """Return (exit_code, summary, updated_record)."""
    record = copy.deepcopy(record)
    warnings = record.setdefault("warnings", [])
    key = (repo, tag)
    existing = None
    for w in warnings:
        if w.get("repo") == repo and w.get("tag") == tag:
            existing = w
            break

    if not product_files:
        return 0, "", record

    summary = _format_summary(product_files, product_commits)

    if existing is None:
        first_seen = now
        deadline = first_seen + datetime.timedelta(hours=24)
        warnings.append(
            {
                "repo": repo,
                "tag": tag,
                "first_seen": first_seen.isoformat(),
                "deadline": deadline.isoformat(),
                "responsible_session": session_id,
            }
        )
        return 0, f"::warning::First stranded-release warning for {repo}:{tag}.\n{summary}", record

    # Validate first_seen/deadline already done by load_warning_record, but re-parse here.
    first_seen = _parse_iso(existing["first_seen"])
    deadline = _parse_iso(existing["deadline"])

    if "release_deferred_until" in existing:
        defer_until = _parse_iso(existing["release_deferred_until"])
        if now < defer_until:
            return 0, f"Release deferred until {defer_until.isoformat()} for {repo}:{tag}.", record
        return 2, f"::error::Deferred release date expired for {repo}:{tag}.\n{summary}", record

    if "version_bump_plan" in existing:
        if now <= deadline:
            return 0, f"Version bump plan '{existing['version_bump_plan']}' acknowledged for {repo}:{tag}; deadline {deadline.isoformat()}.", record
        return 2, f"::error::Version bump plan for {repo}:{tag} exceeded deadline {deadline.isoformat()}.\n{summary}", record

    # Unacknowledged.
    if now <= deadline:
        return 0, f"::warning::Stranded product changes for {repo}:{tag} not yet acknowledged (deadline {deadline.isoformat()}).\n{summary}", record

    if release_mode:
        return 2, f"::error::Stranded release for {repo}:{tag} not acknowledged before deadline {deadline.isoformat()}.\n{summary}", record

    return 0, f"::warning::Stranded product changes for {repo}:{tag} past deadline (non-release run).\n{summary}", record


def _write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def _find_warning(record: dict, repo: str, tag: str) -> dict | None:
    for w in record.get("warnings", []):
        if w.get("repo") == repo and w.get("tag") == tag:
            return w
    return None


def _main_audit(args: argparse.Namespace) -> int:
    tag = args.tag
    repo = args.repo
    session_id = args.session_id or ""
    record_path = Path(args.warnings_file)
    repo_root = Path(args.repo_root) if args.repo_root else Path.cwd()

    product_files, product_commits = collect_delta(
        tag,
        exclude_patterns=args.exclude,
        repo_root=repo_root,
    )

    record = load_warning_record(record_path)
    exit_code, summary, record = evaluate_warning(
        record,
        repo,
        tag,
        product_files,
        product_commits,
        _now(),
        session_id,
        release_mode=args.release_mode,
    )
    _write_record(record_path, record)
    if summary:
        print(summary)
    return exit_code


def _main_acknowledge(args: argparse.Namespace) -> int:
    record_path = Path(args.warnings_file)
    record = load_warning_record(record_path)
    warning = _find_warning(record, args.repo, args.tag)
    if warning is None:
        print(f"No warning exists for {args.repo}:{args.tag}; run audit-existing-tag first.", file=sys.stderr)
        return 1

    if args.version_bump_plan:
        warning["version_bump_plan"] = args.version_bump_plan
        warning.pop("release_deferred_until", None)
    elif args.release_deferred_until:
        # Validate ISO date.
        when = _parse_iso(args.release_deferred_until)
        warning["release_deferred_until"] = when.isoformat()
        warning.pop("version_bump_plan", None)
    else:
        print("acknowledge requires --version-bump-plan or --release-deferred-until", file=sys.stderr)
        return 1

    warning["responsible_session"] = args.session_id or warning.get("responsible_session", "")
    _validate_warning(warning)
    _write_record(record_path, record)
    print(f"Acknowledged {args.repo}:{args.tag}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release_safety.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit-existing-tag", help="audit an existing release tag for stranded commits")
    audit.add_argument("--repo", required=True, help="repository identifier (owner/repo)")
    audit.add_argument("--tag", required=True, help="existing tag to audit")
    audit.add_argument("--session-id", default="", help="session/run identifier for the warning")
    audit.add_argument("--release-mode", action="store_true", help="exit 2 when a stranded deadline has expired")
    audit.add_argument("--warnings-file", default=".release-safety/warnings.json", help="path to warnings.json")
    audit.add_argument("--repo-root", default=None, help="git repository root (default: cwd)")
    audit.add_argument("--exclude", action="append", default=None, help="additional glob to exclude (can repeat)")

    ack = subparsers.add_parser("acknowledge", help="acknowledge a stranded-release warning")
    ack.add_argument("--repo", required=True)
    ack.add_argument("--tag", required=True)
    ack.add_argument("--session-id", default="")
    ack.add_argument("--warnings-file", default=".release-safety/warnings.json")
    group = ack.add_mutually_exclusive_group(required=True)
    group.add_argument("--version-bump-plan", help="planned version that will ship the stranded changes")
    group.add_argument("--release-deferred-until", help="ISO-8601 date until which the release is deferred")

    args = parser.parse_args(argv)
    if args.command == "audit-existing-tag":
        return _main_audit(args)
    if args.command == "acknowledge":
        return _main_acknowledge(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Bump the release version everywhere it is recorded, in one step.

WHY THIS EXISTS
---------------
auto-release reads the version from committed files and mints a tag for it. The
same number lives in three places, and every one of them is verified:

    pdf2dxf.py      __version__ = "X.Y.Z"
    pyproject.toml  version = "X.Y.Z"
    README.md       Version-X.Y.Z-blue   (badge)

Editing those by hand is how releases break. Miss one and "Read committed
version" fails with a mismatch; miss all three and the job builds both ZIPs and
the candidate provenance before failing minutes later.

USAGE
-----
    python scripts/prepare_release.py 1.0.82     # bump all three
    python scripts/prepare_release.py --check    # verify they agree
    python scripts/prepare_release.py --current  # print the current version

Then commit and push. auto-release sees a version with no tag and mints it. A
push whose version is unchanged is skipped, not failed -- that is the normal
state for ordinary product commits.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

# (path, pattern whose group(1) is the version)
TARGETS: List[Tuple[Path, re.Pattern]] = [
    (ROOT / "pdf2dxf.py", re.compile(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"')),
    (ROOT / "pyproject.toml",
     re.compile(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)),
    (ROOT / "README.md", re.compile(r"Version-(\d+\.\d+\.\d+)-blue")),
]


def read_all() -> List[Tuple[Path, str]]:
    found = []
    for path, pattern in TARGETS:
        if not path.is_file():
            found.append((path, "<file missing>"))
            continue
        match = pattern.search(path.read_text(encoding="utf-8"))
        found.append((path, match.group(1) if match else "<no match>"))
    return found


def check() -> int:
    found = read_all()
    versions = {version for _, version in found}
    for path, version in found:
        print("  %-24s %s" % (path.relative_to(ROOT).as_posix(), version))
    if len(versions) == 1 and VERSION_RE.match(next(iter(versions))):
        print("OK: all three agree on %s" % next(iter(versions)))
        return 0
    print("MISMATCH: the release build will refuse this.")
    return 1


def current() -> str:
    match = TARGETS[0][1].search(TARGETS[0][0].read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("could not read __version__ from pdf2dxf.py")
    return match.group(1)


def tag_exists(version: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "-q", "--verify",
         "refs/tags/v%s^{commit}" % version],
        capture_output=True,
    )
    return result.returncode == 0


def bump(new_version: str) -> int:
    if not VERSION_RE.match(new_version):
        raise SystemExit("version must look like X.Y.Z, got %r" % new_version)

    now = current()
    if new_version == now:
        raise SystemExit(
            "version is already %s; a release needs a new number because the "
            "existing tag is immutable" % now
        )
    if tag_exists(new_version):
        raise SystemExit("tag v%s already exists; pick a higher version" % new_version)
    if tuple(int(p) for p in new_version.split(".")) < tuple(
        int(p) for p in now.split(".")
    ):
        raise SystemExit("%s is lower than the current %s" % (new_version, now))

    changed = []
    for path, pattern in TARGETS:
        if not path.is_file():
            raise SystemExit("missing file: %s" % path)
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            raise SystemExit("no version found in %s" % path)
        # Rewrite only the captured number so surrounding syntax is untouched.
        updated = text[: match.start(1)] + new_version + text[match.end(1):]
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)

    print("bumped %s -> %s" % (now, new_version))
    for path in changed:
        print("  %s" % path.relative_to(ROOT).as_posix())
    print()
    print("Now commit and push:")
    print('  git commit -am "chore: release LibreCAD importer v%s"' % new_version)
    print("  git push")
    return check()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("version", nargs="?", help="new version, e.g. 1.0.82")
    parser.add_argument("--check", action="store_true",
                        help="verify all three files agree")
    parser.add_argument("--current", action="store_true",
                        help="print the current version and exit")
    args = parser.parse_args(argv)

    if args.current:
        print(current())
        return 0
    if args.check or not args.version:
        return check()
    return bump(args.version)


if __name__ == "__main__":
    sys.exit(main())

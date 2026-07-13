#!/usr/bin/env python3
"""test_release_safety.py — lock release_safety.py contract."""

from __future__ import annotations

import datetime
import json
import re
import sys
import tempfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import release_safety as rs  # noqa: E402


class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_git_factory(
    files: list[str] = None,
    commits: list[tuple[str, str]] = None,
    commit_files_map: dict[str, list[str]] = None,
):
    files = files or []
    commits = commits or []
    commit_files_map = commit_files_map or {}

    def git_command(cmd, *, capture_output=True, text=True, cwd=None, check=True):
        # cmd is like ['git', 'diff', '--name-only', 'tag..HEAD', '--', '.']
        args = cmd[1:]
        if args[:2] == ["diff", "--name-only"]:
            return FakeCompleted(stdout="\n".join(files))
        if args and args[0] == "log":
            return FakeCompleted(stdout="\n".join(f"{sha} {subj}" for sha, subj in commits))
        if args and args[0] == "diff-tree":
            sha = args[-1]
            return FakeCompleted(stdout="\n".join(commit_files_map.get(sha, [])))
        raise AssertionError(f"unexpected git command: {cmd}")

    return git_command


class ReleaseSafetyTest:
    def test_packaging_tools_are_product(self):
        assert rs.is_product_path("build_release.py")
        assert rs.is_product_path("tools/build_release.py")
        assert rs.is_product_path("tools/prune_poppler_bundle.py")
        assert rs.is_product_path("scripts/smoke_release_zip.py")

    def test_docs_and_tests_are_excluded(self):
        assert not rs.is_product_path("README.md")
        assert not rs.is_product_path("docs/usage.md")
        assert not rs.is_product_path("tests/test_foo.py")
        assert not rs.is_product_path("test/smoke_test.rb")
        assert not rs.is_product_path(".github/workflows/ci.yml")
        assert not rs.is_product_path("tools/test_release_safety.py")

    def test_collect_delta_filters_commits_by_files(self):
        git = fake_git_factory(
            files=["build_release.py", "README.md", "tests/test_foo.py"],
            commits=[("abc123", "fix package"), ("def456", "docs update")],
            commit_files_map={
                "abc123": ["build_release.py"],
                "def456": ["README.md"],
            },
        )
        files, commits = rs.collect_delta("v1.0.0", git_command=git, repo_root=Path("."))
        assert files == ["build_release.py"]
        assert len(commits) == 1
        assert commits[0].startswith("abc123")

    def test_load_record_creates_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warnings.json"
            record = rs.load_warning_record(path)
            assert record == {"schema_version": 1, "warnings": []}

    def test_load_record_rejects_malformed_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warnings.json"
            path.write_text(
                '{"schema_version":1,"warnings":[{"repo":"r","tag":"t","first_seen":"2026-07-12T00:00:00+00:00","first_seen_sha":"abc","deadline":"2026-07-13T01:00:00+00:00","responsible_session":"sess"}]}',
                encoding="utf-8",
            )
            try:
                rs.load_warning_record(path)
            except ValueError as e:
                assert "more than 24h" in str(e)

    def test_evaluate_first_warning_exits_zero_and_writes_record(self):
        record = {"schema_version": 1, "warnings": []}
        now = datetime.datetime(2026, 7, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-1"
        )
        assert code == 0
        assert "First stranded-release warning" in summary
        assert len(out["warnings"]) == 1
        assert out["warnings"][0]["repo"] == "owner/repo"
        assert out["warnings"][0]["tag"] == "v1.0.0"

    def test_evaluate_second_warning_past_deadline_exits_two_in_release_mode(self):
        first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                }
            ],
        }
        now = first_seen + datetime.timedelta(hours=25)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-2", release_mode=True
        )
        assert code == 2
        assert "not acknowledged before deadline" in summary

    def test_evaluate_second_warning_non_release_exits_zero(self):
        first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                }
            ],
        }
        now = first_seen + datetime.timedelta(hours=25)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-2", release_mode=False
        )
        assert code == 0
        assert "past deadline (non-release run)" in summary

    def test_evaluate_version_bump_plan_accepted_within_deadline(self):
        first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                    "version_bump_plan": "1.0.1",
                }
            ],
        }
        now = first_seen + datetime.timedelta(hours=12)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-2"
        )
        assert code == 0
        assert "Version bump plan" in summary

    def test_evaluate_version_bump_plan_expires(self):
        first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                    "version_bump_plan": "1.0.1",
                }
            ],
        }
        now = first_seen + datetime.timedelta(hours=25)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-2", release_mode=True
        )
        assert code == 2
        assert "exceeded deadline" in summary

    def test_evaluate_release_deferred_until_accepted_future(self):
        first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
        defer = datetime.datetime(2026, 7, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                    "release_deferred_until": defer.isoformat(),
                }
            ],
        }
        now = first_seen + datetime.timedelta(hours=25)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-2", release_mode=True
        )
        assert code == 0
        assert "Release deferred" in summary

    def test_evaluate_release_deferred_until_expired(self):
        first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
        defer = datetime.datetime(2026, 7, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                    "release_deferred_until": defer.isoformat(),
                }
            ],
        }
        now = first_seen + datetime.timedelta(hours=25)
        code, summary, out = rs.evaluate_warning(
            record, "owner/repo", "v1.0.0", ["build_release.py"], ["abc fix"], now, "sess-2", release_mode=True
        )
        assert code == 2
        assert "Deferred release date expired" in summary

    def test_main_audit_creates_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            warnings_path = repo_root / ".release-safety" / "warnings.json"
            # No real git repo, so monkeypatch collect_delta for argument wiring.
            original = rs.collect_delta
            try:
                rs.collect_delta = lambda *args, **kwargs: (["build_release.py"], ["abc fix"])
                code = rs.main(
                    [
                        "audit-existing-tag",
                        "--repo", "owner/repo",
                        "--tag", "v1.0.0",
                        "--session-id", "sess-1",
                        "--warnings-file", str(warnings_path),
                    ]
                )
                assert code == 0
                assert warnings_path.exists()
                record = json.loads(warnings_path.read_text(encoding="utf-8"))
                assert len(record["warnings"]) == 1
            finally:
                rs.collect_delta = original

    def test_main_acknowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            warnings_path = Path(tmp) / "warnings.json"
            first_seen = datetime.datetime(2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc)
            warnings_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "warnings": [
                            {
                                "repo": "owner/repo",
                                "tag": "v1.0.0",
                                "first_seen": first_seen.isoformat(),
                                "first_seen_sha": "abc",
                                "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                                "responsible_session": "sess-1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            code = rs.main(
                [
                    "acknowledge",
                    "--repo", "owner/repo",
                    "--tag", "v1.0.0",
                    "--version-bump-plan", "1.0.1",
                    "--warnings-file", str(warnings_path),
                ]
            )
            assert code == 0
            record = json.loads(warnings_path.read_text(encoding="utf-8"))
            assert record["warnings"][0]["version_bump_plan"] == "1.0.1"

    def test_later_product_push_without_persisted_state_blocks_release(self):
        record = {"schema_version": 1, "warnings": []}
        first_seen = datetime.datetime(
            2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        code, summary, out = rs.evaluate_warning(
            record,
            "owner/repo",
            "v1.0.0",
            ["build_release.py"],
            ["abc first product", "def later product"],
            first_seen + datetime.timedelta(hours=1),
            "sess-2",
            release_mode=True,
            later_product_push=True,
            first_seen_sha="abc",
            first_seen_at=first_seen,
        )
        assert code == 2
        assert "later product push" in summary.lower()
        assert out["warnings"][0]["first_seen_sha"] == "abc"
        assert out["warnings"][0]["responsible_session"] == "derived:abc"

    def test_expired_deferral_report_mode_stays_green(self):
        first_seen = datetime.datetime(
            2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "first_seen_sha": "abc",
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                    "release_deferred_until": (
                        first_seen + datetime.timedelta(hours=12)
                    ).isoformat(),
                }
            ],
        }
        code, summary, _ = rs.evaluate_warning(
            record,
            "owner/repo",
            "v1.0.0",
            ["build_release.py"],
            ["abc fix"],
            first_seen + datetime.timedelta(hours=25),
            "sess-2",
            release_mode=False,
        )
        assert code == 0
        assert "expired" in summary.lower()

    def test_load_record_rejects_naive_timestamp_and_wrong_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warnings.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "warnings": [
                            {
                                "repo": "wrong/repo",
                                "tag": "v1.0.0",
                                "first_seen": "2026-07-12T00:00:00",
                                "first_seen_sha": "abc",
                                "deadline": "2026-07-13T00:00:00",
                                "responsible_session": "sess-1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            try:
                rs.load_warning_record(
                    path, expected_repo="owner/repo", expected_tag="v1.0.0"
                )
            except ValueError:
                pass
            else:
                raise AssertionError("naive/wrong-repository state was accepted")

    def test_release_safety_helper_is_not_a_product_path(self):
        assert not rs.is_product_path("tools/release_safety.py")
        assert not rs.is_product_path("scripts/release_safety.py")

    def test_collect_delta_accepts_explicit_head(self):
        git = fake_git_factory(
            files=["build_release.py"],
            commits=[("abc123", "fix package")],
            commit_files_map={"abc123": ["build_release.py"]},
        )
        files, commits = rs.collect_delta(
            "v1.0.0", head="push-head", git_command=git, repo_root=Path(".")
        )
        assert files == ["build_release.py"]
        assert commits == ["abc123 fix package"]

    def test_multi_commit_first_push_warns_once_and_lists_every_sha(self):
        record = {"schema_version": 1, "warnings": []}
        now = datetime.datetime(
            2026, 7, 12, 0, 0, 0, tzinfo=datetime.timezone.utc
        )
        commits = ["abc root product", "def merge product"]
        code, summary, out = rs.evaluate_warning(
            record,
            "owner/repo",
            "v1.0.0",
            ["build_release.py", "installer/setup.py"],
            commits,
            now,
            "sess-1",
            release_mode=True,
            later_product_push=False,
            first_seen_sha="abc",
            first_seen_at=now,
        )
        assert code == 0
        assert "First stranded-release warning" in summary
        assert "abc root product" in summary
        assert "def merge product" in summary
        assert out["warnings"][0]["first_seen_sha"] == "abc"
        assert out["warnings"][0]["responsible_session"] == "sess-1"

    def test_main_uses_prior_and_current_push_ranges_without_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "warnings.json"
            original_collect = rs.collect_delta
            original_before = rs._effective_before
            original_time = rs._git_commit_time
            try:
                def fake_collect(base, *, head="HEAD", **_kwargs):
                    ranges = {
                        ("v1.0.0", "headsha"): (
                            ["build_release.py", "installer/setup.py"],
                            ["abc first", "def later"],
                        ),
                        ("beforesha", "headsha"): (
                            ["installer/setup.py"],
                            ["def later"],
                        ),
                        ("v1.0.0", "beforesha"): (
                            ["build_release.py"],
                            ["abc first"],
                        ),
                    }
                    return ranges[(base, head)]

                rs.collect_delta = fake_collect
                rs._effective_before = lambda *_args: "beforesha"
                rs._git_commit_time = lambda *_args: datetime.datetime(
                    2026, 7, 12, tzinfo=datetime.timezone.utc
                )
                code = rs.main(
                    [
                        "audit-existing-tag",
                        "--repo", "owner/repo",
                        "--tag", "v1.0.0",
                        "--before", "beforesha",
                        "--head", "headsha",
                        "--mode", "release",
                        "--session-id", "sess-2",
                        "--warnings-file", str(state),
                        "--repo-root", str(root),
                    ]
                )
                assert code == 2
            finally:
                rs.collect_delta = original_collect
                rs._effective_before = original_before
                rs._git_commit_time = original_time

    def test_main_docs_only_followup_never_escalates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "warnings.json"
            original_collect = rs.collect_delta
            original_before = rs._effective_before
            try:
                def fake_collect(base, *, head="HEAD", **_kwargs):
                    if (base, head) == ("v1.0.0", "headsha"):
                        return ["build_release.py"], ["abc first"]
                    if (base, head) == ("beforesha", "headsha"):
                        return [], []
                    raise AssertionError((base, head))

                rs.collect_delta = fake_collect
                rs._effective_before = lambda *_args: "beforesha"
                code = rs.main(
                    [
                        "audit-existing-tag",
                        "--repo", "owner/repo",
                        "--tag", "v1.0.0",
                        "--before", "beforesha",
                        "--head", "headsha",
                        "--mode", "release",
                        "--warnings-file", str(state),
                        "--repo-root", str(root),
                    ]
                )
                assert code == 0
                assert not state.exists()
            finally:
                rs.collect_delta = original_collect
                rs._effective_before = original_before

    def test_all_zero_before_falls_back_to_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert rs._effective_before("0" * 40, "v1.0.0", Path(tmp)) == "v1.0.0"

    def test_unresolvable_before_falls_back_to_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert rs._effective_before("deadbeef", "v1.0.0", Path(tmp)) == "v1.0.0"

    def test_load_record_rejects_duplicate_and_wrong_tag(self):
        warning = {
            "repo": "owner/repo",
            "tag": "v0.9.0",
            "first_seen": "2026-07-12T00:00:00+00:00",
            "first_seen_sha": "abc",
            "deadline": "2026-07-13T00:00:00+00:00",
            "responsible_session": "sess-1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warnings.json"
            path.write_text(
                json.dumps({"schema_version": 1, "warnings": [warning, warning]}),
                encoding="utf-8",
            )
            try:
                rs.load_warning_record(
                    path, expected_repo="owner/repo", expected_tag="v1.0.0"
                )
            except ValueError:
                pass
            else:
                raise AssertionError("duplicate/wrong-tag state was accepted")

    def test_expired_version_plan_report_mode_stays_green(self):
        first_seen = datetime.datetime(
            2026, 7, 12, tzinfo=datetime.timezone.utc
        )
        record = {
            "schema_version": 1,
            "warnings": [
                {
                    "repo": "owner/repo",
                    "tag": "v1.0.0",
                    "first_seen": first_seen.isoformat(),
                    "first_seen_sha": "abc",
                    "deadline": (first_seen + datetime.timedelta(hours=24)).isoformat(),
                    "responsible_session": "sess-1",
                    "version_bump_plan": "1.0.1",
                }
            ],
        }
        code, _, _ = rs.evaluate_warning(
            record,
            "owner/repo",
            "v1.0.0",
            ["build_release.py"],
            ["abc fix"],
            first_seen + datetime.timedelta(hours=25),
            "sess-2",
            release_mode=False,
        )
        assert code == 0

    def test_workflow_passes_push_boundary_and_gates_every_downstream_step(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "auto-release.yml").read_text(
            encoding="utf-8"
        )
        assert '--before "${{ github.event.before }}"' in workflow
        assert '--head "$GITHUB_SHA"' in workflow
        assert "--mode release" in workflow
        assert '--summary "$GITHUB_STEP_SUMMARY"' in workflow
        audit_at = workflow.index("release_safety.py audit-existing-tag")
        false_at = workflow.rfind('echo "minted=false"', 0, audit_at)
        assert false_at >= 0
        token_at = workflow.index("- name: Check website dispatch token secret")
        token_block = workflow[token_at : workflow.index("- name:", token_at + 8)]
        assert "if: steps.mint.outputs.minted == 'true'" in token_block
        assert not re.search(r"^\s*gh release upload\b", workflow, re.MULTILINE)
        assert "--clobber" not in workflow

    def test_acknowledge_rejects_past_deferral(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warnings.json"
            first_seen = datetime.datetime(
                2026, 7, 12, tzinfo=datetime.timezone.utc
            )
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "warnings": [
                            {
                                "repo": "owner/repo",
                                "tag": "v1.0.0",
                                "first_seen": first_seen.isoformat(),
                                "first_seen_sha": "abc",
                                "deadline": (
                                    first_seen + datetime.timedelta(hours=24)
                                ).isoformat(),
                                "responsible_session": "sess-1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = rs.main(
                    [
                        "acknowledge",
                        "--repo", "owner/repo",
                        "--tag", "v1.0.0",
                        "--release-deferred-until", "2000-01-01T00:00:00+00:00",
                        "--warnings-file", str(path),
                    ]
                )
            assert code == 1
            assert "must be in the future" in stderr.getvalue()


if __name__ == "__main__":
    # Minimal runner; run with pytest or unittest as well.
    t = ReleaseSafetyTest()
    for name in dir(t):
        if name.startswith("test_"):
            print(f"RUN {name}")
            getattr(t, name)()
    print("OK")

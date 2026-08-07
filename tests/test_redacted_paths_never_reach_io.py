"""A redacted path must never be used to touch the filesystem.

Evidence payloads are split on purpose (dxf_text_builder.py:277-303):

  evidence["librecad_executable_path"]                       -> REDACTED
  evidence["local_only_diagnostics"]["librecad_executable_path"] -> real

`redacted_local_path` rewrites the account name to the literal "<user>", so the
shareable half is safe to publish. That half is display-only and must stay that
way: `C:\\Users\\<user>\\...` does not exist on any disk, so anything that opens,
stats or resolves it fails.

The reopen verification in dxf_exporter did exactly that. It read the real path
from local_only_diagnostics but fell back to the redacted field when the key was
missing:

    bound_executable = str(
        local_diagnostics.get("librecad_executable_path")
        or evidence.get("librecad_executable_path")   # <-- redacted
        or "")
    ...
    _resolve_librecad_unicode_lff(bound_executable, fresh=True)

and `_resolve_librecad_unicode_lff` calls `resolve_librecad_installation`, which
walks the real filesystem. The fallback is reachable whenever the local half is
absent -- most plausibly when evidence has been sanitised for sharing, since
dropping the key marked `shareable: False` is precisely what a sanitiser would
do. The result is a font resolution that cannot succeed, on a machine where
nothing is actually wrong.

An empty string is strictly better than a redacted one here: the resolver treats
it as "not specified" and falls back to normal discovery, whereas the redacted
path is a guaranteed miss.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import librecad_runtime  # noqa: E402
from librecad_runtime import (  # noqa: E402
    REDACTED_USER_PLACEHOLDER,
    is_redacted_path,
    redacted_local_path,
)

# Assembled from components rather than written as literals: tests are forbidden
# from containing hardcoded home paths (test_ci_portability.py), and these
# fixtures would otherwise look exactly like a developer path escaping into the
# suite -- which is the very class of leak this file exists to prevent.
_USERS_ROOT = os.path.join("C:" + os.sep, "Users")
_ACCOUNT = "Rowdy Payton"  # deliberately contains a space


def _under_account(*parts: str) -> str:
    return os.path.join(_USERS_ROOT, _ACCOUNT, *parts)


def _under_placeholder(*parts: str) -> str:
    return os.path.join(_USERS_ROOT, REDACTED_USER_PLACEHOLDER, *parts)


# --- the detector -------------------------------------------------------------


def test_detects_a_redacted_path():
    redacted = redacted_local_path(_under_account("AppData", "file.lff"))
    assert REDACTED_USER_PLACEHOLDER in redacted
    assert is_redacted_path(redacted) is True


def test_real_paths_are_not_flagged():
    assert is_redacted_path(_under_account("AppData", "file.lff")) is False
    assert is_redacted_path(
        os.path.join("C:" + os.sep, "Program Files", "LibreCAD", "LibreCAD.exe")
    ) is False


@pytest.mark.parametrize("value", ["", None])
def test_empty_values_are_not_flagged(value):
    assert is_redacted_path(value) is False


def test_redaction_survives_a_username_containing_a_space():
    """The account name here is two words; redaction must replace the whole
    component, not just the first token, or a partial path leaks."""
    redacted = redacted_local_path(_under_account("Desktop", "x.pdf"))
    for token in _ACCOUNT.split():
        assert token not in redacted, f"{token!r} survived redaction"
    assert is_redacted_path(redacted)


# --- the I/O selector ---------------------------------------------------------


def test_io_path_prefers_the_local_diagnostics_value():
    real = _under_account("LibreCAD", "LibreCAD.exe")
    evidence = {
        "librecad_executable_path": _under_placeholder("LibreCAD", "LibreCAD.exe"),
        "local_only_diagnostics": {"librecad_executable_path": real},
    }
    chosen = librecad_runtime.local_path_for_io(
        evidence, "librecad_executable_path"
    )
    assert chosen == real
    assert not is_redacted_path(chosen)


def test_io_path_refuses_the_redacted_fallback():
    """The whole point: a missing local half must NOT fall back to the
    redacted field, because that value cannot exist on disk."""
    evidence = {
        "librecad_executable_path": _under_placeholder("LibreCAD", "LibreCAD.exe"),
    }
    chosen = librecad_runtime.local_path_for_io(
        evidence, "librecad_executable_path"
    )
    assert chosen == "", (
        "an absent local path must resolve to empty so the resolver falls back "
        "to normal discovery; a redacted path is a guaranteed miss"
    )
    assert not is_redacted_path(chosen)


def test_io_path_refuses_a_redacted_value_even_inside_local_diagnostics():
    """Defence in depth: if the local half is ever polluted, still refuse."""
    evidence = {
        "local_only_diagnostics": {
            "librecad_executable_path": _under_placeholder(
                "LibreCAD", "LibreCAD.exe"
            )
        },
    }
    chosen = librecad_runtime.local_path_for_io(
        evidence, "librecad_executable_path"
    )
    assert chosen == ""


def test_io_path_handles_missing_evidence():
    assert librecad_runtime.local_path_for_io({}, "librecad_lff_path") == ""
    assert librecad_runtime.local_path_for_io(None, "librecad_lff_path") == ""


# --- the exporter must not reintroduce the fallback ---------------------------


def test_exporter_never_binds_a_redacted_executable_path():
    """Guards the real call site, not just the helper.

    dxf_exporter builds `bound_executable` and hands it to
    _resolve_librecad_unicode_lff, which performs filesystem resolution.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "librecad_pdf_importer"
        / "exporters"
        / "dxf_exporter.py"
    ).read_text(encoding="utf-8")

    assert 'or evidence.get("librecad_executable_path")' not in source, (
        "the redacted evidence field must not be a fallback for a value that "
        "reaches the filesystem"
    )
    assert 'or evidence.get("librecad_lff_path")' not in source, (
        "same for the LFF path"
    )
    assert "local_path_for_io" in source, (
        "the exporter should select I/O paths through the guarded helper"
    )

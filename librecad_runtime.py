"""Resolve one concrete LibreCAD installation for export and launch."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
from typing import Any, Optional, Tuple


LIBRECAD_RUNTIME_BINDING_CONTRACT_VERSION = "bcs.librecad-runtime-binding/1"
_MAX_FINGERPRINTED_LFF_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class LibreCadInstallation:
    """The executable and resource paths belonging to one LibreCAD install."""

    executable_path: str
    installation_root: str
    executable_resolution_source: str
    unicode_lff_candidates: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class LibreCadRuntimeBinding:
    """Immutable executable/resource fingerprints used by resume identity."""

    executable_resolution_source: str
    executable_path: str = ""
    executable_size_bytes: int = 0
    executable_sha256: str = ""
    unicode_lff_resolution_source: str = ""
    unicode_lff_path: str = ""
    unicode_lff_size_bytes: int = 0
    unicode_lff_sha256: str = ""
    binding_verified: bool = False
    reason: str = ""

    def identity_payload(self) -> dict[str, Any]:
        return {
            "contract_version": LIBRECAD_RUNTIME_BINDING_CONTRACT_VERSION,
            "executable_resolution_source": self.executable_resolution_source,
            "unicode_lff_resolution_source": (
                self.unicode_lff_resolution_source or None
            ),
            "binding_verified": bool(self.binding_verified),
            "reason": self.reason,
            "evidence_sensitivity": (
                "shareable_with_classified_local_diagnostics"
            ),
            "executable": {
                "path": redacted_local_path(self.executable_path),
                "size_bytes": int(self.executable_size_bytes),
                "sha256": self.executable_sha256 or None,
            },
            "unicode_lff": {
                "path": redacted_local_path(self.unicode_lff_path),
                "size_bytes": int(self.unicode_lff_size_bytes),
                "sha256": self.unicode_lff_sha256 or None,
            },
            "local_only_diagnostics": {
                "classification": "local_sensitive_paths",
                "shareable": False,
                "librecad_executable_path": self.executable_path or None,
                "librecad_lff_path": self.unicode_lff_path or None,
            },
        }


REDACTED_USER_PLACEHOLDER = "<user>"


def redacted_local_path(path: str) -> Optional[str]:
    """Return a stable display path without a local account name.

    DISPLAY ONLY. The result names an account that does not exist, so it can
    never be opened, stat-ed or resolved. Use local_path_for_io when a value is
    going to touch the filesystem.
    """

    if not path:
        return None
    parts = list(Path(path).parts)
    for index, part in enumerate(parts[:-1]):
        if part.casefold() in {"users", "home"}:
            parts[index + 1] = REDACTED_USER_PLACEHOLDER
    return str(Path(*parts))


def is_redacted_path(path: Optional[str]) -> bool:
    """True if this string has been through redacted_local_path."""

    if not path:
        return False
    return REDACTED_USER_PLACEHOLDER in str(path)


def local_path_for_io(evidence: Optional[dict], key: str) -> str:
    """Pick the real path for a filesystem operation, or nothing at all.

    Evidence carries two halves: a shareable one whose paths are redacted, and
    ``local_only_diagnostics`` (``shareable: False``) holding the real ones.
    Only the second may be used for I/O.

    Falling back to the shareable half looks harmless and is not: a redacted
    path is a guaranteed miss, so the caller fails on a machine where nothing is
    wrong. Returning "" instead lets resolvers fall back to normal discovery,
    which can actually succeed. A redacted value found anywhere -- including
    inside local_only_diagnostics, in case that half is ever polluted -- is
    refused for the same reason.
    """

    if not isinstance(evidence, dict):
        return ""
    local = evidence.get("local_only_diagnostics")
    if not isinstance(local, dict):
        return ""
    value = str(local.get(key) or "")
    if not value or is_redacted_path(value):
        return ""
    return value


def _stable_file_fingerprint(
    path: Path,
    *,
    max_bytes: Optional[int] = None,
) -> tuple[int, str, str]:
    """Fresh-hash one stable file descriptor or fail closed on a race."""

    try:
        with path.open("rb") as stream:
            stat_before = os.fstat(stream.fileno())
            size = int(stat_before.st_size)
            if max_bytes is not None and size > max_bytes:
                return size, "", f"asset exceeds the {max_bytes}-byte safety limit"
            digest = hashlib.sha256()
            bytes_read = 0
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                bytes_read += len(chunk)
            stat_after = os.fstat(stream.fileno())
        path_stat_after = path.stat()
    except OSError as exc:
        return 0, "", f"asset is unreadable ({type(exc).__name__})"
    before_signature = (
        int(stat_before.st_dev),
        int(stat_before.st_ino),
        int(stat_before.st_size),
        int(stat_before.st_mtime_ns),
    )
    after_signature = (
        int(stat_after.st_dev),
        int(stat_after.st_ino),
        int(stat_after.st_size),
        int(stat_after.st_mtime_ns),
    )
    path_signature = (
        int(path_stat_after.st_dev),
        int(path_stat_after.st_ino),
        int(path_stat_after.st_size),
        int(path_stat_after.st_mtime_ns),
    )
    if (
        before_signature != after_signature
        or after_signature != path_signature
        or bytes_read != size
    ):
        return size, "", "asset changed while it was being fingerprinted"
    return size, digest.hexdigest(), ""


def _resource_candidates(executable: Path) -> Tuple[Tuple[str, str], ...]:
    executable_dir = executable.parent
    candidates = (
        (
            executable_dir / "resources" / "fonts" / "unicode.lff",
            "executable_resources",
        ),
        (
            executable_dir.parent / "share" / "librecad" / "fonts" / "unicode.lff",
            "executable_share",
        ),
        (
            executable_dir.parent / "Resources" / "fonts" / "unicode.lff",
            "application_resources",
        ),
    )
    unique = []
    seen: set[str] = set()
    for path, source in candidates:
        resolved = path.resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            unique.append((str(resolved), source))
    return tuple(unique)


def _executable_candidates(
    executable: Optional[str],
) -> Tuple[Tuple[Path, str], ...]:
    if executable is not None:
        configured = str(executable).strip()
        return (
            ((Path(configured).expanduser(), "explicit_argument"),)
            if configured
            else ()
        )

    configured = str(os.environ.get("BCS_LIBRECAD_EXECUTABLE", "") or "").strip()
    if configured:
        return ((Path(configured).expanduser(), "environment_executable"),)

    candidates = []
    for name in ("LibreCAD.exe", "librecad.exe", "librecad"):
        discovered = shutil.which(name)
        if discovered:
            candidates.append((Path(discovered), "path_executable"))
            break

    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = str(os.environ.get(variable, "") or "").strip()
            if root:
                candidates.append(
                    (Path(root) / "LibreCAD" / "librecad.exe", variable)
                )
        local_app_data = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if local_app_data:
            candidates.append(
                (
                    Path(local_app_data)
                    / "Programs"
                    / "LibreCAD"
                    / "librecad.exe",
                    "LOCALAPPDATA_Programs",
                )
            )
    else:
        candidates.extend(
            (
                (Path("/usr/bin/librecad"), "system_bin"),
                (Path("/usr/local/bin/librecad"), "local_bin"),
                (
                    Path("/Applications/LibreCAD.app/Contents/MacOS/LibreCAD"),
                    "applications",
                ),
            )
        )
    return tuple(candidates)


def resolve_librecad_installation(
    executable: Optional[str] = None,
) -> Optional[LibreCadInstallation]:
    """Resolve a single installation; explicit choices never fall through."""

    for candidate, source in _executable_candidates(executable):
        resolved = candidate.resolve()
        if resolved.is_file():
            return LibreCadInstallation(
                executable_path=str(resolved),
                installation_root=str(resolved.parent),
                executable_resolution_source=source,
                unicode_lff_candidates=_resource_candidates(resolved),
            )
    return None


def resolve_librecad_runtime_binding(
    executable: Optional[str] = None,
) -> LibreCadRuntimeBinding:
    """Resolve and fresh-fingerprint one executable-bound Unicode LFF asset."""

    installation = resolve_librecad_installation(executable)
    if installation is None:
        if executable is not None:
            source = "explicit_argument"
        elif str(os.environ.get("BCS_LIBRECAD_EXECUTABLE", "") or "").strip():
            source = "environment_executable"
        else:
            source = "automatic_discovery"
        return LibreCadRuntimeBinding(
            executable_resolution_source=source,
            reason="LibreCAD executable could not be resolved",
        )

    executable_path = Path(installation.executable_path)
    executable_size, executable_sha256, executable_reason = (
        _stable_file_fingerprint(executable_path)
    )
    configured_lff = str(
        os.environ.get("BCS_LIBRECAD_UNICODE_LFF", "") or ""
    ).strip()
    candidates = [
        (Path(path).resolve(), source)
        for path, source in installation.unicode_lff_candidates
    ]
    selected_lff: Optional[Path] = None
    selected_source = ""
    selection_reason = ""
    if configured_lff:
        configured_path = Path(configured_lff).expanduser().resolve()
        bound_candidates = {
            os.path.normcase(str(path)): (path, source)
            for path, source in candidates
        }
        selected = bound_candidates.get(os.path.normcase(str(configured_path)))
        if selected is None:
            selection_reason = (
                "configured unicode.lff is not bound to the resolved executable"
            )
            selected_source = "unbound_environment_override"
        else:
            selected_lff = selected[0]
            selected_source = "bound_environment_override"
    else:
        for candidate, source in candidates:
            if candidate.is_file():
                selected_lff = candidate
                selected_source = source
                break
        if selected_lff is None:
            selection_reason = "no executable-bound unicode.lff asset was found"

    lff_size = 0
    lff_sha256 = ""
    lff_reason = selection_reason
    if selected_lff is not None:
        lff_size, lff_sha256, lff_reason = _stable_file_fingerprint(
            selected_lff,
            max_bytes=_MAX_FINGERPRINTED_LFF_BYTES,
        )
    reasons = [reason for reason in (executable_reason, lff_reason) if reason]
    verified = bool(
        executable_sha256
        and selected_lff is not None
        and lff_sha256
        and not reasons
    )
    return LibreCadRuntimeBinding(
        executable_resolution_source=installation.executable_resolution_source,
        executable_path=installation.executable_path,
        executable_size_bytes=executable_size,
        executable_sha256=executable_sha256,
        unicode_lff_resolution_source=selected_source,
        unicode_lff_path=str(selected_lff) if selected_lff is not None else "",
        unicode_lff_size_bytes=lff_size,
        unicode_lff_sha256=lff_sha256,
        binding_verified=verified,
        reason=(
            "verified executable-bound LibreCAD runtime assets"
            if verified
            else "; ".join(reasons)
        ),
    )


__all__ = [
    "LIBRECAD_RUNTIME_BINDING_CONTRACT_VERSION",
    "REDACTED_USER_PLACEHOLDER",
    "LibreCadInstallation",
    "LibreCadRuntimeBinding",
    "is_redacted_path",
    "local_path_for_io",
    "redacted_local_path",
    "resolve_librecad_installation",
    "resolve_librecad_runtime_binding",
]

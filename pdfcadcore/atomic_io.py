"""Small atomic file-publish helpers used by import evidence artifacts.

Callers on the delivery path treat these as infallible, so a failure here does
not degrade one item -- it aborts the whole import. Two things made that far
more likely than it needed to be:

* No Windows extended-length prefix, so any target past MAX_PATH (260) failed
  even though the filesystem itself was willing.
* The temp sibling was named ".{full name}.{32-hex}.tmp", which added 38
  characters on top of the real name. Staged assets are 64-hex digests, so the
  temp file ran ~106 characters where the target ran 68: the helper pushed its
  own callers over the limit it then failed on.

Failures now raise AtomicWriteError, which subclasses OSError so existing
`except OSError` handlers keep working, while callers that can descend a
representation rung are able to recognise "this environment could not take the
write" and do so instead of aborting.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid


class AtomicWriteError(OSError):
    """An artifact could not be published atomically.

    Subclasses OSError deliberately: existing handlers keep catching it, and
    callers on the representation ladder can catch this specific type to
    descend a rung rather than fail the import.
    """


def _extended_path(path: Path) -> Path:
    """Return the Windows extended-length form of an absolute path.

    Without the \\\\?\\ prefix the Win32 API refuses anything over MAX_PATH
    regardless of the filesystem or the LongPathsEnabled setting. Relative
    paths are returned unchanged -- the prefix is only valid on a fully
    qualified path -- as are paths that already carry it.
    """
    if os.name != "nt":
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    if not path.is_absolute():
        return path
    # The prefix disables all normalisation, so the path must already be
    # canonical: no forward slashes, no "." or ".." segments.
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute.lstrip("\\"))
    return Path("\\\\?\\" + absolute)


def _temporary_name(name: str) -> str:
    """Name for the temp sibling, kept short on purpose.

    Bounded at 30 characters however long the target is, so publishing a
    64-hex digest asset can never be the thing that crosses MAX_PATH.
    """
    stem = Path(name).stem[:12]
    return f".{stem}.{uuid.uuid4().hex[:12]}.tmp"


def read_bytes(path: str | Path) -> bytes:
    """Read a file that may sit beyond MAX_PATH."""
    return _extended_path(Path(path)).read_bytes()


def atomic_write_bytes(output_path: str | Path, content: bytes) -> str:
    """Publish ``content`` without exposing a partial or truncated target."""

    logical = Path(output_path)
    target = _extended_path(logical)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AtomicWriteError(
            f"could not create directory for {logical}: {exc}"
        ) from exc

    temporary = target.with_name(_temporary_name(logical.name))
    try:
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if temporary.read_bytes() != content:
                raise OSError(f"atomic write byte verification failed: {logical}")
            temporary.replace(target)
        except OSError as exc:
            # Includes the verification failure above; the previous artifact is
            # left untouched because the replace never happened.
            raise AtomicWriteError(f"could not publish {logical}: {exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(logical)


def atomic_write_text(
    output_path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> str:
    return atomic_write_bytes(output_path, content.encode(encoding))


__all__ = [
    "AtomicWriteError",
    "atomic_write_bytes",
    "atomic_write_text",
    "read_bytes",
]

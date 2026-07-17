"""Small atomic file-publish helpers used by import evidence artifacts."""

from __future__ import annotations

import os
from pathlib import Path
import uuid


def atomic_write_bytes(output_path: str | Path, content: bytes) -> str:
    """Publish ``content`` without exposing a partial or truncated target."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != content:
            raise OSError(f"atomic write byte verification failed: {path}")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(path)


def atomic_write_text(
    output_path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> str:
    return atomic_write_bytes(output_path, content.encode(encoding))


__all__ = ["atomic_write_bytes", "atomic_write_text"]

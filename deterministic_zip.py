"""Create byte-reproducible ZIP archives from an explicit file manifest."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Iterable
import zipfile


FIXED_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_REGULAR_FILE_MODE = 0o100644
_EXECUTABLE_FILE_MODE = 0o100755


def _canonical_arcname(raw: str) -> str:
    normalized = str(raw).replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or any(":" in part for part in path.parts)
    ):
        raise ValueError(f"unsafe ZIP member path: {raw!r}")
    return path.as_posix()


def _external_attr(arcname: str) -> int:
    mode = (
        _EXECUTABLE_FILE_MODE
        if PurePosixPath(arcname).suffix.lower() in {".exe", ".bat", ".cmd"}
        else _REGULAR_FILE_MODE
    )
    return mode << 16


def write_deterministic_zip(
    output_path: str | os.PathLike[str],
    files: Iterable[tuple[Path, str]],
) -> Path:
    """Write sorted payload bytes with fixed metadata, then replace atomically."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for source, raw_arcname in files:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"ZIP payload file is missing: {path}")
        arcname = _canonical_arcname(raw_arcname)
        member_key = arcname.casefold()
        if member_key in seen:
            raise ValueError(f"duplicate ZIP member path: {arcname}")
        seen.add(member_key)
        entries.append((arcname, path))
    entries.sort(key=lambda item: item[0])

    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for arcname, source in entries:
                info = zipfile.ZipInfo(arcname, date_time=FIXED_ZIP_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = _external_attr(arcname)
                info.flag_bits = 0x800
                archive.writestr(info, source.read_bytes(), compresslevel=9)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output

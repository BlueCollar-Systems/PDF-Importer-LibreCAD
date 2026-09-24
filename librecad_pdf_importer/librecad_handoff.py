# -*- coding: utf-8 -*-
# Copyright (c) 2024-2026 BlueCollar-Systems -- BUILT. NOT BOUGHT.
# Licensed under the MIT License. See LICENSE for details.
"""GUI <-> LibreCAD plugin handoff contract.

LibreCAD's ``Plugins > Import PDF (BlueCollar)...`` entry starts the importer
GUI as ``lcpdf-gui.exe --librecad-handoff <result.json>``. After a successful
conversion the GUI writes ``{"status": "ok", "output_path": ...}`` to that
file (atomically), and the plugin opens the DXF inside the running LibreCAD.
Closing the GUI without a finished drawing writes ``{"status": "closed"}``.

The contract only carries the path of the DXF the converter already wrote;
it never alters conversion settings or output.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Sequence

HANDOFF_FLAG = "--librecad-handoff"
HANDOFF_SCHEMA = 1
HANDOFF_STATUSES = ("ok", "closed")


def handoff_path_from_argv(argv: Sequence[str]) -> str | None:
    """Return the ``--librecad-handoff`` target from *argv*, if present."""
    args = list(argv)
    for index, arg in enumerate(args):
        if arg == HANDOFF_FLAG:
            if index + 1 < len(args) and args[index + 1].strip():
                return args[index + 1]
            return None
        if arg.startswith(HANDOFF_FLAG + "="):
            value = arg.split("=", 1)[1]
            return value if value.strip() else None
    return None


def write_handoff_result(
    handoff_path: str | os.PathLike[str],
    *,
    status: str,
    output_path: str | os.PathLike[str] | None = None,
    degraded_text_items: int = 0,
    report_path: str = "",
) -> Path:
    """Atomically write the handoff result the LibreCAD plugin polls for."""
    if status not in HANDOFF_STATUSES:
        raise ValueError(f"unknown handoff status: {status!r}")
    if status == "ok" and not output_path:
        raise ValueError("an 'ok' handoff needs the converted DXF path")
    target = Path(handoff_path)
    payload: dict[str, object] = {"schema": HANDOFF_SCHEMA, "status": status}
    if status == "ok":
        payload["output_path"] = str(Path(output_path).expanduser().resolve())  # type: ignore[arg-type]
        payload["degraded_text_items"] = int(degraded_text_items)
        payload["report_path"] = str(report_path or "")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".partial", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target

# -*- coding: utf-8 -*-
"""Plain-English CLI stderr messages shared across Python PDF importers."""

from __future__ import annotations

CLI_ERRORS = {
    "missing_input": (
        "Error: input file path is required unless --gui or --preflight is used."
    ),
    "file_not_found": "Error: input file not found: {path}",
    "not_a_pdf": "Error: {message}",
    "gui_unavailable": "GUI unavailable: {exc}",
    "reference_detected_invalid": "Error: --reference-detected-mm must be greater than zero.",
    "import_failed": "Error: import failed — {message}",
}


def cli_error(code: str, **kwargs: object) -> str:
    """Return a user-facing stderr line for a known CLI failure code."""

    template = CLI_ERRORS.get(code, "Error: {message}")
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


__all__ = ["CLI_ERRORS", "cli_error"]

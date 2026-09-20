"""Bounded, user-requested cancellation and progress for long conversions."""
from __future__ import annotations

from typing import Callable, Optional


class ActivePageCancelled(RuntimeError):
    """Control-flow signal: discard only the currently active page."""


class ImportStopped(RuntimeError):
    """The import was stopped deliberately and says why; no DXF was written.

    The console entry points answer this family with "Import stopped: ..." and
    exit code 2, naming ``failure_report_path`` once that report was written.
    Any other exception is an unexpected failure (one line, exit code 3).
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.failure_report_path = ""


def check_cancel(
    cancel_requested: Optional[Callable[[], bool]],
    boundary: str,
) -> None:
    if cancel_requested is not None and bool(cancel_requested()):
        raise ActivePageCancelled(f"Cancel requested at {boundary}.")


def report_progress(
    callback: Optional[Callable[[str], None]],
    message: str,
) -> None:
    if callback is not None:
        callback(str(message))

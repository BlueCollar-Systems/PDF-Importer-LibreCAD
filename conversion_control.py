"""Bounded, user-requested cancellation and progress for long conversions."""
from __future__ import annotations

from typing import Callable, Optional


class ActivePageCancelled(RuntimeError):
    """Control-flow signal: discard only the currently active page."""


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

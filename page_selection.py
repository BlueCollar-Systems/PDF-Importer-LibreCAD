"""One unambiguous user-facing page-range parser shared by CLI and GUI."""
from __future__ import annotations

import re


_PAGE_PART = re.compile(r"^(\d+)(?:-(\d+))?$")


def parse_page_selection(raw: str | None) -> list[int] | None:
    """Return sorted zero-based indices for a one-based ``1,3-5`` selection."""
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        raise ValueError("The page selection is empty; use All or enter pages such as 1,3-5.")

    pages: set[int] = set()
    for token in value.split(","):
        part = token.strip()
        match = _PAGE_PART.fullmatch(part)
        if match is None:
            raise ValueError(f"Invalid page selection {part!r}; use positive pages such as 1,3-5.")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first < 1 or last < 1:
            raise ValueError("The first valid page number is 1.")
        if last < first:
            raise ValueError(f"Invalid page range {part!r}; the ending page precedes the start.")
        pages.update(range(first - 1, last))
    return sorted(pages)

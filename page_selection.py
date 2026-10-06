"""One unambiguous user-facing page-range parser shared by CLI and GUI."""
from __future__ import annotations

import re
from collections.abc import Iterable


_PAGE_PART = re.compile(r"^(\d+)(?:-(\d+))?$")


def parse_page_selection(raw: str | None, page_count: int | None = None) -> list[int] | None:
    """Return sorted zero-based indices for a one-based ``1,3-5`` selection."""
    if raw is None:
        return None
    value = str(raw).strip()
    if value.lower() == "all":
        return None
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
        if page_count is not None and last > page_count:
            raise ValueError(
                f"Requested page {last} is outside this {page_count}-page PDF; "
                f"choose pages 1-{page_count}."
            )
        pages.update(range(first - 1, last))
    return sorted(pages)


def validate_page_indices(pages: Iterable[int], page_count: int) -> list[int]:
    """Validate the entire zero-based request before importing any peer page."""
    selected = []
    for page in pages:
        if isinstance(page, bool) or not isinstance(page, int):
            raise ValueError("Page indices must be whole, zero-based numbers.")
        if not 0 <= page < page_count:
            raise ValueError(
                f"Requested page {page + 1} is outside this {page_count}-page PDF; "
                f"choose pages 1-{page_count}."
            )
        selected.append(page)
    if not selected:
        raise ValueError("The page selection is empty; choose at least one page.")
    return sorted(set(selected))

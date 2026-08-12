# -*- coding: utf-8 -*-
# stage_timing.py — Split stage timing for the shared extraction pipeline
# BlueCollar Systems — BUILT. NOT BOUGHT.
"""Attribute import time between PDF extraction and host-object construction.

Why this exists: FreeCAD, Blender and LibreCAD had **no** per-stage timings, so every
optimization proposal for them was a guess. That is not hypothetical — third-party
advice named the SketchUp content-stream tokenizer as *the* bottleneck, and when
SketchUp was finally instrumented the tokenizer measured 971 ms of a 60,000 ms import
(1.6%), an Amdahl ceiling below the machine's own ~2% noise floor. The advice was wrong
by roughly 35x. Timers are cheaper than being wrong.

Two design rules are inherited from the SketchUp instrumentation, both learned by
getting them wrong first:

1. **Parents are declared, never inferred.** An earlier version guessed that a stage
   name ending in ``_total_ms`` was a parent. That generalized from a sample of two and
   broke on the third case. Enclosing stages must be listed in ``DECLARED_PARENTS``, so
   reinterpreting a key is an auditable edit rather than silent magic.
2. **Unattributed time is reported, not hidden.** ``unaccounted_ms`` is emitted whenever
   a wall-clock total is known. A timing report that silently sums to the total invites
   the belief that everything is measured; the residual is what tells you it is not.
   SketchUp still carries 8,313 ms (13.9%) of unattributed time, and that number is the
   only reason anyone knows to go looking.

The split itself is free. ``iter_pages`` is a generator: time spent inside it is
extraction, and time between a yield and the next resume is the host building objects
from what it was handed. Nothing in the host has to change, which is what keeps this
instrumentation compliant with "timers land without IR/host mutation".
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

SCHEMA = "bcs.pdfcadcore_stage_timing/1.0"

#: Stages that enclose other stages. Summing a parent alongside its children would
#: double-count and understate ``unaccounted_ms`` -- the exact defect that field exists
#: to expose. Empty today: every stage below is a leaf. Add a name here in the same
#: commit that makes it enclose something.
DECLARED_PARENTS: frozenset = frozenset()

#: Stage keys this module is known to emit. A key outside this set still records
#: normally but is also listed in ``unclassified``, because an unrecognized stage might
#: be a parent, and summing it as a leaf would corrupt the remainder.
KNOWN_STAGES: frozenset = frozenset(
    {
        "extract_ms",        # inside pdfcadcore: PDF -> PageData
        "host_build_ms",     # host side: PageData -> host entities
        "cache_lookup_ms",   # IR cache probe, when enabled
        "cache_store_ms",    # IR cache write, when enabled
    }
)


class StageTimer:
    """Accumulates named stage durations in milliseconds.

    Deliberately not a global. A module-level accumulator would silently blend two
    concurrent imports and would need resetting at exactly the right moment; passing an
    instance makes the lifetime obvious and keeps ``iter_pages`` re-entrant.

    Every method is safe to call and none raises on bad input: instrumentation must
    never be able to fail an import. A nonsense duration is dropped, not propagated.
    """

    __slots__ = ("_stages", "_counts", "_pages")

    def __init__(self) -> None:
        self._stages: Dict[str, float] = {}
        self._counts: Dict[str, int] = {}
        self._pages: int = 0

    def add(self, stage: str, ms: float) -> None:
        """Accumulate ``ms`` against ``stage``. Negative or non-finite values drop."""
        try:
            value = float(ms)
        except (TypeError, ValueError):
            return
        # A monotonic clock should never go backwards, but a bad value must not be able
        # to make a stage look faster than it was.
        if value != value or value in (float("inf"), float("-inf")) or value < 0.0:
            return
        key = str(stage)
        self._stages[key] = self._stages.get(key, 0.0) + value
        self._counts[key] = self._counts.get(key, 0) + 1

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        """Time the enclosed block against ``stage``, including on exception.

        The duration is recorded in a ``finally`` so a page that raises still reports
        the work it consumed; dropping it would make a failing import look cheap.
        """
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add(stage, (time.perf_counter() - started) * 1000.0)

    def note_page(self) -> None:
        self._pages += 1

    @property
    def pages(self) -> int:
        return self._pages

    def get(self, stage: str) -> float:
        return self._stages.get(str(stage), 0.0)

    def leaf_total_ms(self) -> float:
        """Sum of stages that are not declared parents."""
        return sum(
            ms for name, ms in self._stages.items() if name not in DECLARED_PARENTS
        )

    def as_dict(self, total_ms: Optional[float] = None) -> Dict[str, object]:
        """Canonical timing payload.

        ``total_ms`` is the caller's wall-clock measurement for the whole import. When
        supplied, ``unaccounted_ms`` reports what the stages do not explain. When it is
        omitted the field is absent rather than zero, because a fabricated zero would
        assert complete attribution that was never measured.
        """
        out: Dict[str, object] = {"schema": SCHEMA}
        for name in sorted(self._stages):
            out[name] = round(self._stages[name], 3)
        if self._pages:
            out["pages"] = self._pages
        counts = {n: c for n, c in sorted(self._counts.items())}
        if counts:
            out["stage_counts"] = counts
        parents = sorted(n for n in self._stages if n in DECLARED_PARENTS)
        if parents:
            out["stage_parents"] = parents
        unclassified = sorted(
            n for n in self._stages if n not in KNOWN_STAGES and n not in DECLARED_PARENTS
        )
        if unclassified:
            # Loud rather than silent: an unclassified stage may be an enclosing one,
            # and summing it as a leaf would understate the remainder below.
            out["stage_unclassified"] = unclassified
        if total_ms is not None:
            try:
                total = float(total_ms)
            except (TypeError, ValueError):
                return out
            if total == total and total not in (float("inf"), float("-inf")):
                out["total_ms"] = round(total, 3)
                remainder = total - self.leaf_total_ms()
                # Clamped at zero only because a negative remainder means the clocks
                # disagree, not that time was created. The clamp is safe here precisely
                # because parents are declared rather than inferred, so children are
                # never summed alongside an enclosing stage.
                out["unaccounted_ms"] = round(remainder if remainder > 0.0 else 0.0, 3)
                if total > 0.0:
                    out["extract_share_pct"] = round(
                        self.get("extract_ms") / total * 100.0, 2
                    )
                    out["host_build_share_pct"] = round(
                        self.get("host_build_ms") / total * 100.0, 2
                    )
        return out

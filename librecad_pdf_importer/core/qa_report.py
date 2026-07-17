# -*- coding: utf-8 -*-
"""Standard QA report schema for BlueCollar PDF importers."""

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List


def compute_counts_delta(
    counts_before: Dict[str, int],
    counts_after: Dict[str, int],
) -> Dict[str, int]:
    """Compute simple after-before deltas for count dictionaries."""
    keys = set(counts_before.keys()) | set(counts_after.keys())
    delta: Dict[str, int] = {}
    for key in sorted(keys):
        before = int(counts_before.get(key, 0) or 0)
        after = int(counts_after.get(key, 0) or 0)
        delta[key] = after - before
    return delta


@dataclass
class QAReport:
    """Cross-importer QA record for one run."""

    schema_version: str = "1.0"
    test_id: str = ""
    importer: str = ""
    platform: str = ""
    status: str = "unknown"
    message: str = ""
    input_pdf: str = ""
    preset: str = ""
    page_range: str = "all"
    pages: int = 0
    started_at: str = ""
    finished_at: str = ""
    runtime_seconds: float = 0.0
    counts_before: Dict[str, int] = field(default_factory=dict)
    counts_after: Dict[str, int] = field(default_factory=dict)
    counts_delta: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def finalize_counts_delta(self) -> None:
        """Auto-populate counts_delta from before/after values."""
        self.counts_delta = compute_counts_delta(self.counts_before, self.counts_after)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            self.to_dict(), indent=indent, sort_keys=False, allow_nan=False
        )

    def write_json(self, output_path: str, indent: int = 2) -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.to_json(indent=indent))
            f.write("\n")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QAReport":
        report = cls(
            schema_version=str(data.get("schema_version", "1.0")),
            test_id=str(data.get("test_id", "")),
            importer=str(data.get("importer", "")),
            platform=str(data.get("platform", "")),
            status=str(data.get("status", "unknown")),
            message=str(data.get("message", "")),
            input_pdf=str(data.get("input_pdf", "")),
            preset=str(data.get("preset", "")),
            page_range=str(data.get("page_range", "all")),
            pages=int(data.get("pages", 0) or 0),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            runtime_seconds=float(data.get("runtime_seconds", 0.0) or 0.0),
            counts_before=dict(data.get("counts_before", {}) or {}),
            counts_after=dict(data.get("counts_after", {}) or {}),
            counts_delta=dict(data.get("counts_delta", {}) or {}),
            warnings=list(data.get("warnings", []) or []),
            errors=list(data.get("errors", []) or []),
            extra=dict(data.get("extra", {}) or {}),
        )
        if not report.counts_delta:
            report.finalize_counts_delta()
        return report

    @classmethod
    def read_json(cls, input_path: str) -> "QAReport":
        with open(input_path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


__all__ = ["QAReport", "compute_counts_delta"]

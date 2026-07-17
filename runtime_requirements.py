"""Read the canonical runtime requirements used by every build/install path."""

from __future__ import annotations

from pathlib import Path


def load_runtime_requirements(root: Path | None = None) -> tuple[str, ...]:
    project_root = Path(root) if root is not None else Path(__file__).resolve().parent
    requirements_file = project_root / "requirements.txt"
    requirements = tuple(
        line.strip()
        for line in requirements_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not requirements:
        raise RuntimeError(f"runtime requirements are empty: {requirements_file}")
    return requirements

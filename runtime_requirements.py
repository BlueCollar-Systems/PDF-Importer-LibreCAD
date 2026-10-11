"""Read the canonical runtime requirements used by every build/install path."""

from __future__ import annotations

from pathlib import Path
from importlib.metadata import distribution


def load_runtime_requirements(root: Path | None = None) -> tuple[str, ...]:
    project_root = Path(root) if root is not None else Path(__file__).resolve().parent
    requirements_file = project_root / "requirements.txt"
    if requirements_file.is_file():
        requirements = tuple(
            line.strip()
            for line in requirements_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    elif project_root.resolve() == Path(__file__).resolve().parent:
        # An installed wheel has no checkout-level requirements.txt. Its
        # dependency metadata is generated from the same pinned pyproject.
        installed = distribution("pdf2dxf")
        module = Path(installed.locate_file("runtime_requirements.py")).resolve()
        if module != Path(__file__).resolve():
            raise FileNotFoundError(requirements_file)
        requirements = tuple(installed.requires or ())
    else:
        raise FileNotFoundError(requirements_file)
    if not requirements:
        raise RuntimeError(f"runtime requirements are empty: {requirements_file}")
    return requirements

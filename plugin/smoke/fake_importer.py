"""Fake importer used by plugin_smoke --e2e: honours the GUI handoff contract."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from librecad_pdf_importer.librecad_handoff import (  # noqa: E402
    handoff_path_from_argv,
    write_handoff_result,
)


def main() -> int:
    handoff = handoff_path_from_argv(sys.argv[1:])
    if not handoff:
        return 2
    # plugin_smoke writes the expected DXF path beside the handoff file.
    target = Path(handoff).parent / "bc_fake_importer_target.txt"
    write_handoff_result(
        handoff,
        status="ok",
        output_path=target.read_text(encoding="utf-8").strip(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

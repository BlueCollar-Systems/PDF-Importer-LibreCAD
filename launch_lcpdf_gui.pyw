from __future__ import annotations

import sys

from gui import launch_gui
from librecad_pdf_importer.librecad_handoff import handoff_path_from_argv
from librecad_pdf_importer.drawing_insert import saved_drawing_from_argv


if __name__ == "__main__":
    launch_gui(handoff_path_from_argv(sys.argv[1:]), saved_drawing_from_argv(sys.argv[1:]))

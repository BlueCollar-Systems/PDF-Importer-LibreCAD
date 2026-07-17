
#!/usr/bin/env python3
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from repo_context_builder_core import main_with_preset

PRESET = {
  "title": "LLM Context Pack \u2014 LibreCAD PDF Importer",
  "config_paths": [
    "README.md",
    "INSTALL.md",
    "COMPATIBILITY.md",
    "HUMAN_CONFIRMATION.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "pdfcadcore_sync_manifest.json",
    "LICENSE",
    "THIRD_PARTY_LICENSES.md",
    "third_party/fonttools/LICENSE",
    "third_party/fonttools/LICENSE.external"
  ],
  "script_paths": [
    "0build_master_output_1LC-PDFimporter.py",
    "0build_master_output_1LC-PDFimporter.cmd",
    "repo_context_builder_core.py",
    ".github/workflows/auto-release.yml",
    ".github/workflows/lc-pdfimporter-ci.yml",
    ".github/workflows/notify-website-deploy.yml",
    ".github/workflows/release-safety-audit.yml",
    "build_release.py",
    "build_standalone.py",
    "build_windows_portable.py",
    "preflight_check.py",
    "standalone_app.py",
    "release_notices.py",
    "installer/librecad-pdf-importer.iss",
    "tools/fetch_runtime_wheels.ps1",
    "scripts/smoke_portable_zip.py",
    "scripts/release_safety.py",
    "pdfcadcore_sync_check.py",
    "pdf_open_guard.py",
    "corpus_paths.py",
    "gui.py",
    "launch_lcpdf_gui.pyw",
    "pdf2dxf.py",
    "dxf_builder.py",
    "dxf_import_engine.py",
    "dxf_text_builder.py"
  ],
  "source_roots": [
    "librecad_pdf_importer",
    "pdfcadcore",
    "plugin"
  ],
  "test_roots": [
    "tests"
  ],
  "dependency_files": [
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt"
  ],
  "expected_files": {
    "expected_everywhere": [
      "README.md",
      "INSTALL.md",
      "COMPATIBILITY.md",
      "pyproject.toml",
      "requirements.txt",
      "preflight_check.py",
      "build_release.py",
      "build_standalone.py",
      "build_windows_portable.py",
      "release_notices.py",
      "librecad_pdf_importer/runtime_self_test.py",
      "scripts/smoke_portable_zip.py",
      "tools/fetch_runtime_wheels.ps1",
      "installer/librecad-pdf-importer.iss",
      "LICENSE",
      "THIRD_PARTY_LICENSES.md",
      "third_party/fonttools/LICENSE",
      "third_party/fonttools/LICENSE.external",
      ".github/workflows/auto-release.yml",
      ".github/workflows/lc-pdfimporter-ci.yml"
    ],
    "expected_some_envs": []
  },
  "exclude_dir_names": [
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".release-safety",
    ".superpowers",
    "_LLM_CONTROL_PACK",
    "dist",
    "build",
    "dev_logs",
    ".venv",
    "venv",
    "lib",
    "lib.stage.*",
    "lib.backup.*",
    "benchmarks",
    "generated",
    "release",
    "debug",
    "Output",
    "_archived",
    "*.egg-info"
  ],
  "exclude_file_names": [],
  "exclude_suffixes": [
    ".pyc",
    ".dxf"
  ],
  "include_extensions": [
    "",
    ".bat",
    ".c",
    ".cfg",
    ".cmake",
    ".cmd",
    ".conf",
    ".cpp",
    ".css",
    ".dart",
    ".external",
    ".go",
    ".gradle",
    ".h",
    ".hpp",
    ".htm",
    ".html",
    ".ini",
    ".iss",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".md",
    ".php",
    ".plist",
    ".ps1",
    ".py",
    ".pyw",
    ".r",
    ".rb",
    ".rs",
    ".sample",
    ".scss",
    ".sh",
    ".sql",
    ".svg",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml"
  ],
  "tree_full_depth_roots": [
    ".github",
    "installer",
    "librecad_pdf_importer",
    "pdfcadcore",
    "plugin",
    "scripts",
    "tests",
    "third_party",
    "tools"
  ],
  "tree_shallow_depth_roots": {},
  "default_tree_depth": 2,
  "navigation_grep_patterns": [
    "\\bQAction\\b",
    "\\btriggered\\.connect\\b",
    "\\bshow\\(",
    "\\bexec_\\("
  ],
  "navigation_roots": [
    "librecad_pdf_importer",
    "pdfcadcore",
    "plugin",
    "gui.py",
    "pdf2dxf.py",
    "dxf_builder.py",
    "dxf_import_engine.py",
    "dxf_text_builder.py"
  ],
  "check_commands": [
    [
      "python",
      "-m",
      "pytest",
      "-q"
    ]
  ]
}

if __name__ == "__main__":
    raise SystemExit(main_with_preset(PRESET))

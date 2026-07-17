
#!/usr/bin/env python3
"""
Generic LLM Context Builder

Features:
- High-signal project snapshot for LLM analysis
- Depth-limited file tree
- Exclusion/skip report
- Dependency summary
- Missing expected files report
- Optional command checks via --run-checks
- Safe truncation and light secret redaction
"""

from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import json
import os
import re
import shutil
import sqlite3
import subprocess
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

MAX_FILE_LINES = 3000
MAX_HEAD_LINES = 2000
MAX_TAIL_LINES = 500

DEFAULT_REDACTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"""(?im)(\b(?:api[_-]?key|token|secret|password|client[_-]?secret)\b\s*[:=]\s*)(["'])([^"']+)\2"""
        ),
        r"\1\2<REDACTED>\2",
    ),
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "<REDACTED_PRIVATE_KEY_BLOCK>",
    ),
]

TEXT_PREVIEW_EXTENSIONS = {
    ".py", ".rb", ".dart", ".js", ".ts", ".tsx", ".jsx", ".css", ".scss",
    ".html", ".htm", ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".sql", ".xml", ".plist", ".kts", ".gradle",
    ".cmake", ".sh", ".ps1", ".bat", ".cmd", ".c", ".cpp", ".h", ".hpp",
    ".java", ".kt", ".swift", ".go", ".rs", ".php", ".r", ".lua", ".svg"
}

def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def _choose_fence(text: str) -> str:
    max_backticks = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    max_tildes = max((len(m.group(0)) for m in re.finditer(r"~+", text)), default=0)
    if max_backticks <= max_tildes:
        return "`" * max(3, max_backticks + 1)
    return "~" * max(3, max_tildes + 1)

def _detect_language(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    mapping = {
        ".py": "python",".rb": "ruby",".dart": "dart",".js": "javascript",".ts": "typescript",
        ".tsx": "tsx",".jsx": "jsx",".css": "css",".scss": "scss",".html": "html",".htm": "html",
        ".json": "json",".yaml": "yaml",".yml": "yaml",".xml": "xml",".plist": "xml",".md": "markdown",
        ".txt": "text",".sql": "sql",".toml": "toml",".kts": "kotlin",".gradle": "groovy",".sh": "bash",
        ".ps1": "powershell",".bat": "bat",".cmd": "bat",".svg": "xml",
    }
    if suffix == ".cmake" or name == "cmakelists.txt":
        return "cmake"
    return mapping.get(suffix, "")

def _redact(text: str) -> str:
    out = text
    for pattern, replacement in DEFAULT_REDACTION_PATTERNS:
        out = pattern.sub(replacement, out)
    return out

def _truncate_text(text: str):
    lines = text.splitlines()
    if len(lines) <= MAX_FILE_LINES:
        return text, False
    head = lines[:MAX_HEAD_LINES]
    tail = lines[-MAX_TAIL_LINES:]
    clipped = "\n".join(head) + "\n\n# ... SNIPPED ...\n\n" + "\n".join(tail)
    return clipped, True

def _write_heading(out, title: str, level: int = 1) -> None:
    out.write(f"{'#' * max(1, level)} {title}\n\n")

def _write_fenced_block(out, content: str, language: str = "") -> None:
    fence = _choose_fence(content)
    out.write(f"{fence}{language}\n")
    out.write(content)
    if not content.endswith("\n"):
        out.write("\n")
    out.write(f"{fence}\n\n")

def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

class ContextBuilder:
    def __init__(self, preset: Dict):
        self.preset = preset
        self.project_root = Path(preset.get("project_root", Path(__file__).resolve().parent)).resolve()
        self.dev_logs = self.project_root / preset.get("dev_logs_dir", "dev_logs")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_path = self.dev_logs / f"llm_context_{ts}.md"
        self.latest_path = self.dev_logs / "latest_llm_context.md"
        self.skip_reasons = defaultdict(list)
        self.truncated_files = []
        self.previewed_files = []

    @property
    def exclude_dir_names(self):
        return set(self.preset.get("exclude_dir_names", []))

    @property
    def exclude_file_names(self):
        return set(self.preset.get("exclude_file_names", []))

    @property
    def exclude_suffixes(self):
        return tuple(self.preset.get("exclude_suffixes", []))

    @property
    def include_extensions(self):
        return set(self.preset.get("include_extensions", sorted(TEXT_PREVIEW_EXTENSIONS)))

    def is_excluded_dir(self, path: Path) -> bool:
        name = path.name
        for pattern in self.exclude_dir_names:
            if name == pattern:
                return True
            if any(token in pattern for token in ("*", "?", "[")) and fnmatchcase(
                name, pattern
            ):
                return True
        return False

    def is_previewable_file(self, path: Path) -> bool:
        if path.name in self.exclude_file_names:
            self.skip_reasons["excluded_name"].append(_safe_rel(path, self.project_root))
            return False
        if any(path.name.endswith(sfx) for sfx in self.exclude_suffixes):
            self.skip_reasons["excluded_suffix"].append(_safe_rel(path, self.project_root))
            return False
        if path.suffix.lower() in self.include_extensions or path.name.lower() == "cmakelists.txt":
            return True
        self.skip_reasons["non_text_or_unlisted_extension"].append(_safe_rel(path, self.project_root))
        return False

    def iter_filtered_files(self, root: Path):
        for current_root, dirs, files in os.walk(root):
            root_path = Path(current_root)
            original_dirs = list(dirs)
            dirs[:] = [d for d in sorted(dirs) if not self.is_excluded_dir(root_path / d)]
            for d in original_dirs:
                if d not in dirs:
                    self.skip_reasons["excluded_directory"].append(_safe_rel(root_path / d, self.project_root))
            for file_name in sorted(files):
                file_path = root_path / file_name
                if self.is_previewable_file(file_path):
                    yield file_path

    def collect_files(self, relative_roots):
        items = []
        for rel in relative_roots:
            base = self.project_root / rel
            if not base.exists():
                continue
            if base.is_file():
                if self.is_previewable_file(base):
                    items.append(base)
                continue
            for path in self.iter_filtered_files(base):
                items.append(path)
        return sorted(set(items))

    def collect_named_files(self, relative_paths):
        paths = []
        for rel in relative_paths:
            candidate = self.project_root / rel
            if candidate.exists() and candidate.is_file() and self.is_previewable_file(candidate):
                paths.append(candidate)
        return paths

    def file_metadata(self, path: Path) -> str:
        stat = path.stat()
        rel = _safe_rel(path, self.project_root)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return f"- Path: `{rel}`\n- Size: `{_format_size(stat.st_size)}`\n- Modified: `{modified}`\n"

    def write_file_section(self, out, path: Path) -> None:
        rel = _safe_rel(path, self.project_root)
        _write_heading(out, rel, 3)
        out.write(self.file_metadata(path))
        out.write("\n")
        text = _redact(_read_text(path))
        text, truncated = _truncate_text(text)
        if truncated:
            self.truncated_files.append(rel)
            out.write("- Note: File was truncated for token safety.\n\n")
        self.previewed_files.append(rel)
        _write_fenced_block(out, text, _detect_language(path))

    def top_level_inventory(self):
        rows = []
        for child in sorted(self.project_root.iterdir(), key=lambda p: p.name.lower()):
            if self.is_excluded_dir(child):
                continue
            if child.is_dir():
                count = 0
                for current_root, dirs, files in os.walk(child):
                    root_path = Path(current_root)
                    dirs[:] = [
                        directory
                        for directory in dirs
                        if not self.is_excluded_dir(root_path / directory)
                    ]
                    count += len(files)
                rows.append((child.name + "/", count, True))
            else:
                rows.append((child.name, child.stat().st_size, False))
        return rows

    def write_inventory_section(self, out) -> None:
        _write_heading(out, "Project Inventory", 2)
        out.write("Filtered inventory for context quality. Heavy/generated folders are excluded.\n\n")
        for name, metric, is_dir in self.top_level_inventory():
            out.write(f"- `{name}`: {metric} files\n" if is_dir else f"- `{name}`: {_format_size(metric)}\n")
        out.write("\n")

    def _tree_depth_for(self, first_part: str) -> int:
        full = set(self.preset.get("tree_full_depth_roots", []))
        shallow = self.preset.get("tree_shallow_depth_roots", {})
        if first_part in full:
            return 99
        return int(shallow.get(first_part, self.preset.get("default_tree_depth", 2)))

    def _build_tree_lines(self):
        root = self.project_root
        lines = [f"{root.name}/"]
        def add_dir(dir_path: Path, prefix: str = ""):
            try:
                rel_parts = dir_path.relative_to(root).parts
            except Exception:
                rel_parts = ()
            entries = []
            try:
                for p in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    if p.is_dir() and self.is_excluded_dir(p):
                        continue
                    entries.append(p)
            except Exception:
                return
            for i, entry in enumerate(entries):
                last = i == len(entries) - 1
                branch = "└── " if last else "├── "
                lines.append(prefix + branch + entry.name + ("/" if entry.is_dir() else ""))
                if entry.is_dir():
                    rel = entry.relative_to(root)
                    rel_parts = rel.parts
                    depth_limit = self._tree_depth_for(rel_parts[0] if rel_parts else "")
                    if len(rel_parts) < depth_limit:
                        add_dir(entry, prefix + ("    " if last else "│   "))
        add_dir(root, "")
        return lines

    def write_tree_section(self, out) -> None:
        _write_heading(out, "Repo Tree", 2)
        out.write("Depth-limited tree. Full depth for selected roots, shallow for noisy areas.\n\n")
        _write_fenced_block(out, "\n".join(self._build_tree_lines()), "text")

    def parse_dependency_summary(self):
        summary = defaultdict(list)
        for rel in self.preset.get("dependency_files", []):
            path = self.project_root / rel
            if not path.exists() or not path.is_file():
                continue
            text = _read_text(path)
            low = rel.lower()
            if path.name == "pubspec.yaml":
                current = None
                for line in text.splitlines():
                    if re.match(r"^\s*dependencies:\s*$", line):
                        current = "dependencies"; continue
                    if re.match(r"^\s*dev_dependencies:\s*$", line):
                        current = "dev_dependencies"; continue
                    if re.match(r"^\S", line):
                        current = None
                    if current and re.match(r"^\s{2,}[A-Za-z0-9_.-]+:\s*", line):
                        name = line.strip().split(":", 1)[0]
                        if name != "sdk":
                            summary[current].append(line.strip())
            elif low.endswith("requirements.txt") or low.endswith("requirements-dev.txt"):
                key = path.name
                for line in text.splitlines():
                    s = line.strip()
                    if s and not s.startswith("#"):
                        summary[key].append(s)
            elif low.endswith("pyproject.toml"):
                section = None
                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("[tool.poetry.dependencies]"):
                        section = "poetry_dependencies"
                    elif s.startswith("[tool.poetry.group.dev.dependencies]"):
                        section = "poetry_dev_dependencies"
                    elif s.startswith("["):
                        section = None
                    elif "=" in s and section in {"poetry_dependencies", "poetry_dev_dependencies"}:
                        summary[section].append(s)
            elif low.endswith("package.json"):
                try:
                    data = json.loads(text)
                    for key in ("dependencies", "devDependencies"):
                        for name, version in sorted(data.get(key, {}).items()):
                            summary[key].append(f"{name}: {version}")
                except Exception:
                    summary[path.name].append("<failed to parse package.json>")
        return summary

    def write_dependency_summary(self, out) -> None:
        _write_heading(out, "Dependency Summary", 2)
        deps = self.parse_dependency_summary()
        if not deps:
            out.write("No configured dependency files found.\n\n")
            return
        for section, items in deps.items():
            out.write(f"### {section}\n\n")
            _write_fenced_block(out, "\n".join(items) if items else "None detected.", "text")

    def write_missing_expected_files(self, out) -> None:
        _write_heading(out, "Missing Expected Files", 2)
        for group, key in (("Expected Everywhere", "expected_everywhere"), ("Expected In Some Environments", "expected_some_envs")):
            out.write(f"### {group}\n\n")
            expected = self.preset.get("expected_files", {}).get(key, [])
            missing = [rel for rel in expected if not (self.project_root / rel).exists()]
            if missing:
                _write_fenced_block(out, "\n".join(missing), "text")
            else:
                out.write("None missing.\n\n")

    def write_navigation_inventory(self, out) -> None:
        patterns = self.preset.get("navigation_grep_patterns", [])
        roots = self.preset.get("navigation_roots", self.preset.get("source_roots", []))
        if not patterns or not roots:
            return
        compiled = [re.compile(p) for p in patterns]
        matches = []
        for path in self.collect_files(roots):
            try:
                text = _read_text(path)
            except Exception:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                for pat in compiled:
                    if pat.search(line):
                        matches.append(f"{_safe_rel(path, self.project_root)}:{line_no}: {line.strip()}")
                        break
        _write_heading(out, "Navigation Call-Site Inventory", 2)
        if not matches:
            out.write("No configured navigation call-sites found.\n\n")
            return
        _write_fenced_block(out, "\n".join(matches[:500]), "text")
        if len(matches) > 500:
            out.write(f"- Note: {len(matches) - 500} additional matches omitted.\n\n")

    def write_sqlite_section(self, out) -> None:
        db_paths = self.preset.get("sqlite_paths", [])
        if not db_paths:
            return
        _write_heading(out, "SQLite Schema Snapshot", 2)
        db_path = None
        for rel in db_paths:
            candidate = self.project_root / rel
            if candidate.exists():
                db_path = candidate
                break
        if db_path is None:
            out.write("No SQLite database found in configured locations.\n\n")
            return
        out.write(f"- Database: `{_safe_rel(db_path, self.project_root)}`\n")
        out.write(f"- Size: `{_format_size(db_path.stat().st_size)}`\n\n")
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [r[0] for r in cur.fetchall()]
                out.write("Tables:\n")
                for name in tables:
                    out.write(f"- `{name}`\n")
                out.write("\n")
        except Exception as exc:
            out.write(f"Database read failed: {exc}\n\n")

    def run_checks(self):
        results = []
        for cmd in self.preset.get("check_commands", []):
            try:
                proc = subprocess.run(
                    cmd, cwd=self.project_root, text=True, capture_output=True,
                    shell=isinstance(cmd, str), timeout=int(self.preset.get("check_timeout_seconds", 180)),
                )
                output = (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
                results.append((cmd if isinstance(cmd, str) else " ".join(cmd), proc.returncode, output.strip()))
            except Exception as exc:
                results.append((cmd if isinstance(cmd, str) else " ".join(cmd), 999, f"Check failed to start: {exc}"))
        return results

    def write_checks_section(self, out, run_checks: bool) -> None:
        _write_heading(out, "Optional Checks", 2)
        if not run_checks:
            out.write("Checks were not run. Use `--run-checks` to capture configured command output.\n\n")
            return
        results = self.run_checks()
        if not results:
            out.write("No check commands configured for this repo.\n\n")
            return
        for cmd, code, output in results:
            out.write("### Command\n\n")
            _write_fenced_block(out, cmd, "text")
            out.write(f"- Exit code: `{code}`\n\n")
            _write_fenced_block(out, output or "<no output>", "text")

    def write_exclusion_report(self, out) -> None:
        _write_heading(out, "Exclusion / Skip Report", 2)
        if not self.skip_reasons and not self.truncated_files:
            out.write("No exclusions or truncations recorded.\n\n")
            return
        for reason in sorted(self.skip_reasons):
            items = sorted(set(self.skip_reasons[reason]))
            out.write(f"### {reason.replace('_', ' ').title()}\n\n")
            out.write(f"- Count: {len(items)}\n\n")
            preview = items[:200]
            _write_fenced_block(out, "\n".join(preview), "text")
            if len(items) > len(preview):
                out.write(f"- Note: {len(items) - len(preview)} additional items omitted.\n\n")
        if self.truncated_files:
            out.write("### Truncated Files\n\n")
            _write_fenced_block(out, "\n".join(sorted(set(self.truncated_files))), "text")

    def build(self, run_checks: bool = False):
        self.dev_logs.mkdir(parents=True, exist_ok=True)
        config_files = self.collect_named_files(self.preset.get("config_paths", []))
        script_files = self.collect_named_files(self.preset.get("script_paths", []))
        source_files = self.collect_files(self.preset.get("source_roots", []))
        test_files = self.collect_files(self.preset.get("test_roots", []))
        with self.output_path.open("w", encoding="utf-8", newline="\n") as out:
            _write_heading(out, self.preset.get("title", "LLM Context Pack"), 1)
            out.write(f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n")
            out.write(f"- Project Root: `{self.project_root.as_posix()}`\n")
            out.write(f"- Output File: `{self.output_path.as_posix()}`\n")
            out.write("- Formatting Safety: dynamic fenced blocks are used to avoid fence collisions.\n\n")
            self.write_inventory_section(out)
            self.write_tree_section(out)
            self.write_dependency_summary(out)
            self.write_missing_expected_files(out)
            _write_heading(out, "Core Configuration Files", 2)
            if not config_files:
                out.write("No configuration files were found.\n\n")
            for path in config_files:
                self.write_file_section(out, path)
            _write_heading(out, "Source Files", 2)
            out.write(f"Included files: `{len(source_files)}`\n\n")
            for path in source_files:
                self.write_file_section(out, path)
            _write_heading(out, "Test Files", 2)
            out.write(f"Included files: `{len(test_files)}`\n\n")
            for path in test_files:
                self.write_file_section(out, path)
            _write_heading(out, "Project Scripts", 2)
            if not script_files:
                out.write("No script files were found.\n\n")
            for path in script_files:
                self.write_file_section(out, path)
            self.write_navigation_inventory(out)
            self.write_sqlite_section(out)
            self.write_checks_section(out, run_checks)
            self.write_exclusion_report(out)
            _write_heading(out, "End of Pack", 2)
            out.write("Context pack completed.\n")
        shutil.copyfile(self.output_path, self.latest_path)
        return self.output_path

def main_with_preset(preset: Dict) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-checks", action="store_true", help="Run configured optional checks and append output")
    parser.add_argument("--project-root", default=None, help="Override detected project root")
    args = parser.parse_args()
    if args.project_root:
        preset = dict(preset)
        preset["project_root"] = args.project_root
    try:
        builder = ContextBuilder(preset)
        output = builder.build(run_checks=args.run_checks)
        print("=" * 72)
        print("LLM context pack complete")
        print(f"Output: {output}")
        print(f"Latest: {builder.latest_path}")
        print("=" * 72)
        return 0
    except Exception as exc:
        print("Build failed.")
        print(str(exc))
        print(traceback.format_exc())
        return 1

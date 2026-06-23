# Round 3 — Reviewer B: Improvement Opportunities

**Date:** 2026-06-23  
**Scope:** Deferred Round-2 items, parity, tests, INSTALL, CI risks  
**Method:** Repo scan + doc cross-check vs Round-2 resolution register (R2-1..R2-10).

---

## Executive summary

Core libraries are healthy; improvement work centers on **falsifiable measurement** (strict timing, per-phase telemetry on Ruby host), **test parity** (Blender vs LibreCAD import_report coverage), **INSTALL/website accuracy**, and **process gates** (auto-release during review, corpus opt-out trending).

---

## Findings (≥5)

### B-1 — Blender import_report test coverage thinner than LibreCAD

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-Blender` vs `C:\1PDF-Importer-LibreCAD` |
| **File** | BL: `tests/test_import_report_writer.py` only. LC: + `test_import_report_text_mode.py`, `test_dxf_import_report.py` |
| **Severity** | **P2** |
| **Evidence** | BL pytest import_report slice: 2 passed. LC same class: 5 passed across three modules. |
| **Recommend** | Port LC text-mode and DXF report tests to BL (adapt host paths). **Defer** if Blender report path deemed stable. |

### B-2 — Correctness oracle still absent (R2-4)

| Field | Value |
|-------|-------|
| **Repo** | All importers |
| **File** | `C:\1PDF-Importer-SketchUp\test\fixtures\corpus_baselines\` (stability hashes only) |
| **Severity** | **P2** |
| **Evidence** | Round-2 resolution R2-4: need Tier-1 checklist or golden vectors beyond hash baselines. No new oracle files in Round-3 scan. |
| **Recommend** | Add 3–5 named PDFs with human-verified primitive counts / layer expectations. **Defer** until after R2-3 timing gate passes. |

### B-3 — OCG / per-span layer tagging undocumented for geometry text (R2-5)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` (+ Python hosts) |
| **File** | Round-2 resolution; `QA-2026-06-22_text-mode-parity-status.md` (canonical in FC `_LLM_CONTROL_PACK`) |
| **Severity** | **P2** |
| **Evidence** | Round-2 upheld: geometry text uses one `text_layer`, not per-span OCG tags. No new doc commit in INSTALL/README surfacing this for end users. |
| **Recommend** | Add short "Layer / OCG behavior" section to each host `COMPATIBILITY.md`. **Defer** code change unless field retest shows user-visible regression. |

### B-4 — CORPUS_STRESS_OPTOUT warns but does not fail CI (R2-6)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` |
| **File** | `test/support/corpus_harness.rb` lines 85–101; `test/CORPUS_STRESS_OPTOUT.md` |
| **Severity** | **P2** |
| **Evidence** | Soft cap warns when opt-out list > 5; no CI step fails on growth. `corpus-placement.yml` skips full corpus without `BCS_CORPUS_ROOT`. |
| **Recommend** | Add CI assertion: opt-out count ≤ cap, or require PR note when list grows. **Defer** if corpus remains manual-only. |

### B-5 — LibreCAD INSTALL lacks prominent in-host version command (R2-8 partial)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-LibreCAD` |
| **File** | `INSTALL.md` (no `--version`); `README.md` line 129 documents `python pdf2dxf.py --version` |
| **Severity** | **P2** |
| **Evidence** | Round-2 R2-8 asked for in-host version command on download page + docs. README has CLI flag; INSTALL portable path does not mention `pdf2dxf.exe --version` or `lcpdf-gui` about box. |
| **Recommend** | Add one line to INSTALL Option 0: "`pdf2dxf.exe --version` prints importer version." Mirror on website LC card. **Fix** low effort. |

### B-6 — FreeCAD repo root holds stale local release zips (hygiene)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-FreeCAD` |
| **File** | `FreeCAD-PDF-Importer_v4.0.30.zip`, `v4.0.31.zip` (~18 MB each) |
| **Severity** | **P2** |
| **Evidence** | Files present on disk; `git ls-files "*.zip"` → empty (not tracked). Current `pyproject.toml` version = 4.0.40. |
| **Recommend** | Delete local artifacts or move to `dist/`; ensure `.gitignore` covers `*.zip` at root. **Defer** commit; local cleanup only. |

### B-7 — Auto-release not gated on open QA state (R2-9)

| Field | Value |
|-------|-------|
| **Repo** | All importers (`auto-release.yml` in SU/FC/LC/BL) |
| **File** | e.g. `C:\1PDF-Importer-SketchUp\.github\workflows\auto-release.yml` |
| **Severity** | **P2** (process) |
| **Evidence** | Round-2: v3.7.55 shipped during open review. Round-3 scan: all repos at latest tags (SU v3.7.56, FC v4.0.40, LC/BL v1.0.34) with clean trees — releases continue on version bumps. |
| **Recommend** | Add workflow guard (label, manual approval, or `RELEASE_GATE=1` repo variable). **Defer** to owner decision. |

### B-8 — Desktop Q&A folder under-documented vs in-repo mirror

| Field | Value |
|-------|-------|
| **Repo** | Infra |
| **File** | `C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A\` (Instructions only before Round 3); `_LLM_CONTROL_PACK/QA/` in each repo |
| **Severity** | **P2** |
| **Evidence** | Round-2 R2-7 requested Q&A visibility. In-repo `Q&A_INDEX.md` is rich; Desktop folder had no index until this Round-3 drop. |
| **Recommend** | Keep Desktop + `_LLM_CONTROL_PACK/QA` in sync after each round. **Fix** via copy script in website `tools/`. |

---

## Round-2 deferred items — status snapshot

| ID | Item | Round-3 status |
|----|------|----------------|
| R2-2 | Per-phase timing in import_report | **Partial** — Python hosts + pdfcadcore done; SketchUp Ruby host still total-only |
| R2-3 | Strict wall-clock benchmark | **Open** — opt-in test exists, not in CI |
| R2-4 | Correctness oracle | **Open** |
| R2-5 | OCG/layer docs | **Open** |
| R2-6 | CORPUS_STRESS_OPTOUT cap enforcement | **Partial** — warn only |
| R2-7 | Mirror Q&A | **Partial** — in-repo yes; Desktop catching up |
| R2-8 | LC 2D TEXT-only + version command | **Partial** — COMPATIBILITY exists; INSTALL/website gaps |
| R2-9 | Gate release on review | **Open** |
| R2-10 | Retire dead shape repos / junction paths | **Open** — `C:\1SU-PDFimporter` etc. absent on this machine |

---

*Anonymous Reviewer B — Round 3 scan. No code changes made.*

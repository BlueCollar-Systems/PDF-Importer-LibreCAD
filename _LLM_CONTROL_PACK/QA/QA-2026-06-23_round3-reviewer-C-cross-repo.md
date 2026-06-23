# Round 3 — Reviewer C: Cross-Repo Sync, Parity & CI

**Date:** 2026-06-23  
**Scope:** pdfcadcore embedding, versions, CI, workspace layout, release alignment

---

## Executive summary

**Embedded pdfcadcore is in sync** across FreeCAD, LibreCAD, and Blender (manifest + `pdfcadcore_sync_check.py`). Version numbers align between `pyproject.toml` / package metadata and GitHub releases for the current wave. Cross-host **text-mode parity** remains intentionally asymmetric (LibreCAD 2D-limited). CI provides syntax/smoke coverage but **not** strict performance proof or full corpus placement without secrets/self-hosted runners.

---

## Findings (≥5)

### C-1 — pdfcadcore sync check passes (positive evidence)

| Field | Value |
|-------|-------|
| **Repos** | FC, LC, BL |
| **File** | `pdfcadcore_sync_check.py`, `pdfcadcore_sync_manifest.json` |
| **Severity** | **Info** (no error) |
| **Evidence** | FC: `ALL IN SYNC`. LC/BL: identical output. Manifest lists 22 files including `qa_report.py`, `import_report.py`. |
| **Recommend** | Keep sync check in FC/LC/BL CI pre-release. **No action.** |

### C-2 — Text-mode parity matrix unchanged (by design)

| Field | Value |
|-------|-------|
| **Repos** | SU, BL, FC, LC |
| **File** | `QA-2026-06-22_text-mode-parity-status.md` (FC `_LLM_CONTROL_PACK/QA/`) |
| **Severity** | **P2** (documentation, not bug) |
| **Evidence** | Full four-mode parity: SU + BL. FC: true `3d_text` via ShapeString (v4.0.31+). LC: `3d_text`/`glyphs` → DXF TEXT. |
| **Recommend** | State limits on website LC download card and in LC GUI labels. **Defer** 3D to LC (host format limit). |

### C-3 — Version scheme divergence across hosts (expected)

| Field | Value |
|-------|-------|
| **Repos** | All importers |
| **File** | `pyproject.toml` / `metadata.rb` / GitHub releases |
| **Severity** | **P2** |
| **Evidence** | SU `3.7.56` (`metadata.rb` + `bc_pdf_vector_importer.rb`). FC `4.0.40`. LC/BL `1.0.34`. Releases on GitHub match (verified via `repo-metadata.json` generated 2026-06-23). |
| **Recommend** | Maintain per-host semver; use `repo-metadata.json` on website as single display source. **No unify** unless product decision. |

### C-4 — Corpus placement CI is structural-only on GitHub-hosted runners

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` |
| **File** | `.github/workflows/corpus-placement.yml` lines 37–40, 72 |
| **Severity** | **P1** (measurement gap) |
| **Evidence** | Without `BCS_CORPUS_ROOT`, workflow validates baseline JSON only and emits `::warning::Full corpus placement gate skipped`. |
| **Recommend** | Self-hosted runner with corpus mount, or commit minimal Tier-1 PDF subset for CI. **Defer** full corpus to manual QA with documented opt-out list. |

### C-5 — Open-gate policy inconsistency across hosts (documented)

| Field | Value |
|-------|-------|
| **Repos** | SU vs LC/FC/BL |
| **File** | LC `INSTALL.md` lines 31–33; SU `pdf_open_gate.rb` / `main.rb` |
| **Severity** | **P2** |
| **Evidence** | Python hosts fail closed on bad PDF at open. SketchUp fails open on gate implementation errors. |
| **Recommend** | Cross-link behavior in all `COMPATIBILITY.md` files. **Defer** code alignment pending product call. |

### C-6 — Dead workspace junction paths (Round-2 R2-10 still open)

| Field | Value |
|-------|-------|
| **Paths** | `C:\1SU-PDFimporter`, `C:\1FC-PDFimporter`, `C:\1LC-PDFimporter`, `C:\1BL-PDFimporter`, `C:\1pdfcadcore`, `C:\1pdf-test-corpus` |
| **Severity** | **P2** (dev ergonomics) |
| **Evidence** | All `Test-Path` → **MISSING** on scan machine. Active clones live at `C:\1PDF-Importer-*`. Cursor workspace may reference dead junctions. |
| **Recommend** | Recreate junctions or update IDE workspace roots to `C:\1PDF-Importer-*`. **Owner decision.** |

### C-7 — `repo-metadata.json` under-lists LibreCAD release assets

| Field | Value |
|-------|-------|
| **Repo** | `C:\1BlueCollar-Website` |
| **File** | `repo-metadata.json` lines 74–81 vs `gh release view v1.0.34` |
| **Severity** | **P2** |
| **Evidence** | Metadata JSON lists only `LibreCAD-PDF-Importer_v1.0.34.zip` (120 KB). GitHub release also has `LibreCAD-PDF-Importer-Windows-Portable_v1.0.34.zip` (186 MB). |
| **Recommend** | Fix `tools/sync_repo_metadata.py` to include all release assets or prefer portable asset for website LC card. **Fix** before next website deploy. |

### C-8 — LC/BL share importer version; FC/SU independent (positive)

| Field | Value |
|-------|-------|
| **Repos** | LC + BL |
| **Severity** | **Info** |
| **Evidence** | Both `version = "1.0.34"` in `pyproject.toml`; shared pdfcadcore hashes identical per sync manifest. |
| **Recommend** | Continue bumping LC/BL together when pdfcadcore changes. **No action.** |

---

## CI inventory (Round 3)

| Repo | Workflows observed | Automated tests run locally |
|------|-------------------|----------------------------|
| SketchUp | `su-pdfimporter-ci.yml`, `corpus-placement.yml`, `auto-release.yml` | `qa_report_test.rb` ✓ |
| FreeCAD | `fc-pdfimporter-ci.yml`, `windows-release.yml`, `auto-release.yml` | 60 pytest ✓, sync ✓ |
| LibreCAD | `lc-pdfimporter-ci.yml`, `release.yml`, `auto-release.yml` | 39 pytest ✓, sync ✓ |
| Blender | `auto-release.yml` (+ CI via pyproject) | 36 pytest ✓, sync ✓ |
| Website | deploy workflows | `validate_static_metadata.py` ✓ |
| Steel app | GitHub Actions (Flutter) | `flutter analyze` ✓, 153 `flutter test` ✓ |

---

*Anonymous Reviewer C — Round 3 scan.*

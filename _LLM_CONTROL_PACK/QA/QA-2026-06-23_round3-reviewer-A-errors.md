# Round 3 — Reviewer A: Errors & Bugs

**Date:** 2026-06-23  
**Scope:** All six active repos + embedded pdfcadcore (FC/LC/BL)  
**Method:** Real commands on local clones (`C:\1PDF-Importer-*`, website, Steel app). No code modified.

---

## Executive summary

No test-suite failures or sync drift were observed. Remaining items are **process/measurement gaps** carried from Round 2 (R2-3, R2-2 partial on SketchUp) and **documented behavioral parity differences** (open gate fail-open). None are P0 crashes in automated checks; R2-3 manual/strict timing is still the top sign-off blocker.

---

## Findings (≥5)

### A-1 — Round-2 strict timing benchmark not enforced in CI (R2-3)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` |
| **File** | `test/corpus_strict_timing_test.rb` (lines 12–13 opt-in gate); `.github/workflows/su-pdfimporter-ci.yml` (no `CORPUS_STRICT_TIMING`) |
| **Severity** | **P1** (blocking sign-off per Round-2 resolution) |
| **Evidence** | `ruby test/corpus_strict_timing_test.rb` exits 0 immediately (skipped unless `CORPUS_STRICT_TIMING=1`). `rg CORPUS_STRICT_TIMING .github` → no matches. |
| **Recommend** | Wire strict timing into a dedicated CI job (self-hosted + `BCS_CORPUS_ROOT`) or document as mandatory manual gate before release. **Defer** only if team explicitly accepts manual-only proof. |

### A-2 — SketchUp import_report lacks granular phase timings (R2-2 partial)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` |
| **File** | `extracted/sketchup_ext/bc_pdf_vector_importer/qa_report.rb` lines 70–76 |
| **Severity** | **P2** |
| **Evidence** | `performance.phases` only sets `{ total_ms: elapsed_ms }`. Python hosts populate `open_pdf_ms`, `pages_import_ms`, etc. (`PDFImporterCore.py` ~3470+). `pdfcadcore/qa_report.py` has `phase_timings` in FC/LC/BL (sync verified). Ruby host does not mirror. |
| **Recommend** | Instrument Ruby pipeline phases and emit matching keys in `import_report.json`. **Defer** if Round-3 team agrees SketchUp uses `performance.phases` schema only. |

### A-3 — SketchUp PDF open gate fail-open on gate exceptions

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` |
| **File** | `extracted/sketchup_ext/bc_pdf_vector_importer/main.rb` lines 1398–1400; `pdf_open_gate.rb` lines 58–61 |
| **Severity** | **P2** |
| **Evidence** | `handle_open_gate` rescues `StandardError` and returns `nil` (import proceeds). `PdfOpenGate.inspect_path` also returns `{ ok: true }` on sniff errors. LC `INSTALL.md` documents SU as fail-open vs Python fail-closed. |
| **Recommend** | Either align to fail-closed (log + refuse) or document as intentional in `COMPATIBILITY.md` and close R2 parity question. **Defer** behavior change if documented. |

### A-4 — Missing git tag `v3.7.53` (tag continuity gap)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-SketchUp` |
| **File** | git tags |
| **Severity** | **P2** |
| **Evidence** | `git tag -l 'v3.7.*'` shows `v3.7.52`, `v3.7.54`, `v3.7.55`, `v3.7.56` — no `v3.7.53`. Round-2 R2-9 / reviewer C flagged tag gaps. |
| **Recommend** | Cite VERSION + SHA in release notes (already at 3.7.56). **Defer** retroactive tag unless audit trail required. |

### A-5 — FreeCAD pytest Windows cleanup PermissionError (local/self-hosted CI risk)

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-FreeCAD` |
| **File** | `.pytest_tmp/` (pytest atexit cleanup) |
| **Severity** | **P2** |
| **Evidence** | After `python -m pytest tests/ -q` (60 passed): `PermissionError: [WinError 5] Access is denied` on `.pytest_tmp\...\pytest-current`. Tests themselves passed. |
| **Recommend** | Set `TMPDIR`/`pytest tmp_path` to user-writable dir in `conftest.py` or document Windows cleanup quirk. **Defer** if Linux CI is sole gate. |

### A-6 — FreeCAD deprecated `PDFImportConfig` import in tests

| Field | Value |
|-------|-------|
| **Repo** | `C:\1PDF-Importer-FreeCAD` |
| **File** | `tests/test_clean_break.py` line 32; `PDFVectorImporter/src/PDFImportConfig.py` line 6 |
| **Severity** | **P2** |
| **Evidence** | Pytest warning: `DeprecationWarning: PDFImportConfig is deprecated; import from pdfcadcore.import_config instead.` |
| **Recommend** | Update test + `freecad_harness.py` import paths to `pdfcadcore.import_config`. **Fix** in next code wave. |

### A-7 — Website stale LibreCAD portable filename example

| Field | Value |
|-------|-------|
| **Repo** | `C:\1BlueCollar-Website` |
| **File** | `index.html` line 204 |
| **Severity** | **P2** |
| **Evidence** | Page cites `LibreCAD-PDF-Importer-Windows-Portable_v1.0.33.zip`. Current release is v1.0.34 (`gh release view v1.0.34` lists `LibreCAD-PDF-Importer-Windows-Portable_v1.0.34.zip`). |
| **Recommend** | Update example to v1.0.34 or generic `vX.Y.Z` placeholder. **Fix** with website metadata sync. |

---

## Automated checks (Reviewer A)

| Check | Result |
|-------|--------|
| `python pdfcadcore_sync_check.py` (FC) | **ALL IN SYNC** |
| `ruby test/qa_report_test.rb` (SU) | 4 runs, 20 assertions, **0 failures** |
| `python -m pytest tests/` (FC, corpus/integration ignored) | **60 passed**, 1 deprecation warning |
| `python -m pytest tests/` (LC) | **39 passed** |
| `python -m pytest tests/` (BL) | **36 passed** |
| Blocking TODO/FIXME in app code | **None** (vendor PyMuPDF FIXMEs in BL only) |

---

*Anonymous Reviewer A — Round 3 scan. Await team feedback before any commit.*

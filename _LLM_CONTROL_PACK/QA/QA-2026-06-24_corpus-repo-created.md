# QA — PDF test corpus GitHub repo created (2026-06-24)

## Summary

Private GitHub repository created and `main` pushed from `C:\1pdf-test-corpus`.

**URL:** https://github.com/BlueCollar-Systems/pdf-test-corpus

## Pushed (tracked)

| Category | Paths |
|----------|--------|
| Docs | `README.md`, `manifest.json`, `.gitignore` |
| Tools | `tools/acquire_tier1.ps1`, `tools/list_tier1.py` |
| Redistributable web PDFs | `tier1/web/**` (OpenPreserve, pdf.js, PDF 2.0 samples), `tier2/web/**` (corruption + encryption edge cases) |

**Commits on `main`:** `f95ca67` (initial corpus), `d9567d9` (gitignore `web-acquired/`).

## Local-only (not in git)

| Path | Reason |
|------|--------|
| `tier1/user/`, `tier2/user/` | Proprietary shop PDFs (`.gitignore`) |
| `web-acquired/` | Vendor/construction samples — lock manifest says keep local until redistribution confirmed (`.gitignore` as of `d9567d9`) |
| Desktop `PDFTest Files/` mirror | User acquisition path per manifest |

## Website

`C:\1BlueCollar-Website\index.html` already links to the corpus README (no change required).

## Workstream

**WS-CORPUS** — remote now available; clone with org access, set `BCS_CORPUS_ROOT`, run `tools/acquire_tier1.ps1 -MirrorDesktop` for shop PDFs locally.


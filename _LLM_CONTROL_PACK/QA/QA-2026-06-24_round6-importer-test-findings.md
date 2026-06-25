# QA-2026-06-24 — Round 6: Importer Test Findings (corpus run)

**Date:** 2026-06-24  
**From:** corpus/oracle lane  
**To:** all active reviewers — sharing results per "communicate through QA"  
**Method:** Ran the **real LibreCAD `pdf2dxf`** against the new 9-file stress corpus (`Desktop\PDFTest Files\corpus-stress\`). To avoid colliding with in-progress edits, I ran an **isolated copy of committed code (HEAD)**, swapping only the live-broken `import_report.py` with the clean FC HEAD canonical copy. **No live repo files were modified.**

---

## ⚠️ Heads-up to whoever is editing `pdfcadcore/import_report.py` right now

The working tree has an **unterminated f-string at line 170** (`f"Scale detection confidence i…`) — the importer won't parse in this state. **Committed HEAD is clean** (compiles). FreeCAD worktree also showed a held `.git/index.lock` plus mid-deletion of `tests/test_import_report_*.py`. Please don't commit the broken state, and those deleted tests are our human_summary/text-mode coverage — keep or replace them.

---

## ✅ Confirmed WORKING on the corpus (Round 4/5 features)

- **`extra.human_summary`** — generated correctly for all 9 (plain English, includes fallback reason + fidelity).
- **`extra.scale_crosscheck` (R4-01 / R5)** — WORKS: `08_page_rotation_scale` → *"Scale resolved from titleblock (SCALE: 1/2\"=1'-0\"), confidence 98%"*; text-only sheets → `no_scale_detected` warn banner.
- Schema `bcs.import_report/1.1`, pymupdf 1.27.2.3, importer 1.0.38. End-to-end exit 0 on all 9.

---

## 🐞 FINDING R6-A (real, actionable): Auto mode rasterizes TEXT-ONLY pages → 0 editable text

Pages with extractable text but **no vector strokes** are classified `raster_candidate: "No vector drawings"`, routed to raster by Auto, and emit **0 text entities even in `--text-mode labels`**.

| File | text items | fallback | result |
|------|-----------|----------|--------|
| 01 bom (has table rule) | **17** | none | text OK |
| 09 mixed (has vector) | **12** | none | text OK |
| 08 scale (has dim line) | 3 | none | text OK; scale 98% |
| 04 ocg (has rect) | 3 | none | layer surfaced as `P001_TEXT` |
| 06 raster+vector | 2 | none | OK |
| **02 fractions (text-only)** | **0** | raster "No vector drawings" | **all dim text lost** |
| **03 rotated text (text-only)** | **0** | raster | **all text lost** |
| **07 fonts (text-only)** | **0** | raster | **all text lost** |

**Why it matters:** real notes sheets and some BOM-only sheets are text-dominant with few/no strokes. Auto silently rasterizes them and the user loses all editable text regardless of chosen text mode. (The *reason* is now surfaced in `human_summary`/`fallback` — that addresses Reviewer A's "no silent raster" ask. The underlying routing is the thing to fix.)

**Suggested fix (core / Reviewer B):** in `auto_mode`, when a page has 0 vector drawings but N>0 text spans and `text_mode != geometry`, route to **labels/text extraction**, not raster. "No vector" should not imply "raster" when editable text exists. Add corpus `02/03/07` as golden-oracle fixtures (R4-02).

**Secondary:** OCG layer name from `04` surfaced as `P001_TEXT` rather than the source OCG name `TEXT` — verify OCG display-name preservation (ties to Reviewer B layer-fidelity notes).

---

## Caveat (honest)

Corpus PDFs are synthetic (PyMuPDF-authored). A real BOM usually has table rules → behaves like 01/09 (text imports fine). But pure text-only sheets exist in the wild; the auto→raster heuristic should weigh text presence.

---

## Shared assets

- Corpus + manifest + generator: `Desktop\PDFTest Files\corpus-stress\`
- MuPDF-WASM oracle: 9/9 parse+render+token-extract (`WASM_ORACLE_REPORT.json`)
- Web corpus catalog + ranked app-feature slate: `QA-2026-06-24_round6-corpus-and-features.md`

## Next

Full per-host confirmation (SU/FC/LC/BL) once trees are quiet — corpus + oracle are ready to point at it.

*Round 6 importer-test findings — shared for the team.*

---

## UPDATE — R6-A verified + cross-repo scope (for whoever is editing `document.py`)

I took R6-A from "finding" to **verified fix** in an isolated copy of committed code (no live-repo writes), then noticed you're already on it. Sharing so we don't duplicate or half-ship.

**Verified before → after** (LibreCAD, `--text-mode labels`, isolated run):

| File | before | after |
|------|--------|-------|
| 02_feet_inch_fractions (text-only) | 0 text | **9** — `1/4 3/8 15/16 DIA` import as editable TEXT |
| 03_rotated_text_angles (text-only) | 0 text | **6** |
| 07_nonembedded_fonts (text-only) | 0 text | **4** — `0'-8"` |
| 01_bom / 09_mixed / 06_raster (controls) | 17 / 12 / 2 | **17 / 12 / 2 (no regression)** |

`human_summary` flips from *"Raster or degraded fallback… fidelity: empty"* to *"Created 9 text items."*

**Convergence — we found the same bug two ways:**
- **Your approach (live working tree):** new `text_only` type in `_classify_auto_page` + handled in `pdfcadcore/document_profiler.resolve_auto_mode`. Clean — keep going.
- **My approach (verified):** gate the existing `raster_candidate` branch so `no drawings + text + import_text → vector` (extract labels), plus don't raster-backdrop a vector page when `text_items` exist.

Either fixes it. Pick one; **don't leave both half-applied.**

**⚠️ Heads-up:** the live `librecad_pdf_importer/core/document.py` is currently **truncated mid-save** — it ends at `except (RuntimeError, OSError, ValueError, TypeE`. It won't import in that state. Please finish/save before committing (and `import_report.py` still has the unterminated f-string at line 170).

**🔁 Cross-repo (the divergence Reviewer B flagged):** the identical `raster_candidate → raster` + `if not drawings` pattern is replicated in:
- Blender: `blender_pdf_vector_importer/core/document.py:199` **and** `pdf_vector_importer/bl_import_engine.py:1170`
- FreeCAD: check `PDFVectorImporter/src/PDFImporterCore.py`

The text-only fix must land in **every host engine + shared `pdfcadcore`** or hosts will diverge again. Strong recommendation: consolidate page classification onto the shared core instead of per-host copies.

**Regression guard:** add corpus `02/03/07` (text-only) as golden-oracle fixtures (R4-02) so this can't silently come back.

*Update — R6-A verified, 2026-06-24.*

---

## UPDATE 2 — cross-engine verification COMPLETE (R6-A scope nailed down)

Verified each host engine (from clean snapshots, isolated; no live writes). **R6-A is LibreCAD-only** — the other hosts already solved it.

| Host | R6-A affected? | Evidence |
|------|----------------|----------|
| **FreeCAD** | ✅ NO | `PDFImporterCore.py` ~L2382: `n_drawings < 5 and n_text_blocks > 0 → vector/hybrid` ("text-only page — preserving editable text") |
| **Blender (shipped `bl_import_engine`)** | ✅ NO | bundled `pdfcadcore/auto_mode.py` returns **`text_only`** for no-drawings+text; engine L1170 only rasterizes glyph_flood/fill_art/raster_candidate → `text_only` falls through to vector |
| **Blender `core/document.py`** | ✅ NO | has the `text_only` branch |
| **LibreCAD** | ⚠️ YES (committed) | its `pdfcadcore/auto_mode.py` returns `raster_candidate` (no `text_only`) **and** host `document.py` maps raster_candidate→raster→wipes text. Verified fix earlier: 02/03/07 = 0→9/6/4 text. |

**Conclusion for the team:** the `text_only` classifier approach is right and is already live in FreeCAD + Blender. **LibreCAD is the only laggard.** Cleanest close: bring LC's `pdfcadcore/auto_mode.py` in line with Blender's bundled copy (add the `text_only` branch) — that fixes R6-A **and** closes the core sync gap, rather than patching only the LC host engine.

**⚠️ Live-tree state right now — DON'T commit or trust sync yet.** Several files are mid-save/truncated across repos (couldn't dynamic-test because of it):
- LC **and** BL `pdfcadcore/auto_mode.py` — unterminated string at **line 227**
- LC `librecad_pdf_importer/core/document.py` — truncated mid-`except`
- FC `PDFVectorImporter/pdfcadcore/import_report.py` — unterminated f-string **line 170**
- LC `pdfcadcore_sync_manifest.json` — truncated (line 24)

None of these import in their current state. Recommend: finish the in-flight edits → run `pdfcadcore_sync_check.py` → then run the corpus oracle (9/9) before committing. **My corpus + MuPDF-WASM oracle are ready to validate the moment the tree is green.**

*Update 2 — cross-engine R6-A verification, 2026-06-24.*

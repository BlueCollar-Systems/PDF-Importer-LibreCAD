# Round 4 — Reviewer B: Python Hosts + pdfcadcore

**Session:** 2026-06-24  
**Persona:** Anonymous — extraction engineer who trusts spans, spans, spans  
**Mandate:** Innovate at the core so FC/LC/BL inherit magic without forking logic.

---

## What we already have

- **pdfcadcore** byte-synced across FC, LC, BL (`pdfcadcore_sync_check.py` — FC canonical).
- `build_import_report()` with `extra.auto_reason`, phase timings, shapestring skip tallies (FC).
- `build_fidelity_diagnostics()` — portable quality signals (Round 4 pre-work).
- Hybrid/auto mode that already records *why* raster fired — underused in UI.

---

## Outside-the-box ideas (≥5)

### B-1 — Confidence heatmaps (per-page overlay PNG)

**Idea:** Optional `--heatmap` flag writes a PNG per page: green = high vector confidence, amber = mixed, red = raster-eligible. Sidecar in `import_report.extra.heatmap_paths`.

**Why it matters:** Engineers *see* where auto mode struggled. Support gets a visual without sharing the whole model. Accuracy debugging becomes falsifiable.

**Host limit:** SketchUp Ruby path wouldn’t get this cheaply — keep Python-first, document gap honestly.

---

### B-2 — Per-span quality scores in `import_report.extra`

**Idea:** Aggregate histogram: `% spans with embedded font`, `% missing ToUnicode`, `% oversized glyph bounds`. No per-glyph spam — summary stats only.

**Why it matters:** Text mode choice (Labels vs Glyphs) should be data-driven. “14 spans seen, 0 entities created” already signals trouble — span scores explain *why*.

**Status:** Partially present via `text_source_spans`, `text_glyph_estimate`, diagnostics signals — extend with `span_quality` block.

---

### B-3 — Hybrid auto mode that explains WHY (vector vs raster)

**Idea:** Surface `extra.auto_reason` + `raster_fallback_reasons[]` as a single sentence in UI/CLI exit text and in **`extra.human_summary`**.

**Why it matters:** Users think auto is magic or broken. Plain English — “Page 2 raster: scanned image, no vector operators” — builds trust.

**Status this session:** **Shipped** — `build_human_summary()` in pdfcadcore + SketchUp mirror.

---

### B-4 — Extraction replay bundle

**Idea:** Zip `import_report.json`, page classification JSON, first 50 KB of content stream hashes — one attachment for bug reports.

**Why it matters:** Reproducing customer PDFs is legally messy; replay metadata often suffices to fix classifiers.

---

### B-5 — Oracle-lite golden vectors (3 PDFs, human counts)

**Idea:** Named corpus entries with expected primitive ranges (+/- 2%), not just stability hashes.

**Why it matters:** Round 3 deferred R2-4. Without oracles, we optimize vibes.

**Peer challenge to A:** Your live preview is flashy — but if golden vectors fail, preview just shows wrong geometry faster.

---

### B-6 — Parallel page extraction with memory budget

**Idea:** `pdfcadcore.streaming` already exists — expose soft budget in report (`performance.phases.extract_ms` per page). Auto-throttle on 8 GB shop PCs.

**Why it matters:** Accuracy dies when users switch to raster out of frustration with hangs.

---

## Peer challenges

**To Reviewer C:** Plain-English errors are necessary but not sufficient — pair every error with `recommended_actions` from diagnostics (already in schema).

**To Reviewer D:** Steel detection in pdfcadcore should emit `extra.domain_hints: ["steel_fabrication"]` — app deep-link is useless without structured hint.

---

## Rank self (impact / effort)

| Idea | Impact | Effort |
|------|--------|--------|
| B-3 human_summary | High | Low — **done** |
| B-2 span quality | High | Medium |
| B-5 golden vectors | High | Medium |
| B-1 heatmaps | Medium | Medium |
| B-4 replay bundle | Medium | Low |
| B-6 parallel budget | Medium | High |

---

*Reviewer B — Round 4, 2026-06-24*

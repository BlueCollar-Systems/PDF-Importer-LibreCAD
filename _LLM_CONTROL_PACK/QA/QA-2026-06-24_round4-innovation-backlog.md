# Round 4 — Innovation Backlog

**Session:** 2026-06-24  
**Source:** Debate ranking + four vision docs  
**Legend:** P0 = next sprint magic · P1 = near-term · P2 = moonshot

---

## P0 — Next-sprint magic (high impact, medium effort)

| ID | Item | Owner lens | Notes |
|----|------|------------|-------|
| R4-01 | Scale cross-check banner (title block vs dimension) | A | Non-blocking; uses existing parsers |
| R4-02 | Golden vectors (3–5 PDFs, primitive ranges) | B | Closes R2-4 oracle gap |
| R4-03 | CLI plain-English stderr templates (LC/BL) | C | Map `fallback.reason` → sentence |
| R4-04 | Preflight wizard — shared copy deck | C | Host-specific UI later |
| R4-05 | `span_quality` aggregate in import_report | B | Extends diagnostics |
| R4-06 | LC/BL first-run dependency one-liner in `--preflight` | C | Mirror SU Compatibility Report |

---

## P1 — Backlog (medium impact)

| ID | Item | Owner lens |
|----|------|------------|
| R4-10 | One-click Match PDF Layers → Tags | A |
| R4-11 | Import Health “Copy summary” button | A/C |
| R4-12 | Extraction replay bundle (zip metadata) | B |
| R4-13 | Confidence heatmap PNG sidecar | B |
| R4-14 | In-host “What will I get?” dialog | C |
| R4-15 | First-run 3-tooltip tour | C |
| R4-16 | Steel `domain_hints` in report | D |
| R4-17 | Release train alignment doc (steel-v*) | D |
| R4-18 | COMPATIBILITY.md OCG/geometry text section | B (R2-5) |

---

## P2 — Moonshots (excite brilliant engineers)

| ID | Item | Owner lens | Why moonshot |
|----|------|------------|--------------|
| R4-20 | Live import preview (ghost geometry) | A | Second extraction pass + UI sync |
| R4-21 | Revision diff re-import | A | Stable primitive IDs |
| R4-22 | View-aligned import plane | A | Cross-host math + UX |
| R4-23 | Parallel page extract + memory budget UI | B | Streaming hardening |
| R4-24 | Steel designation batch placeholders | D | pdfcadcore + 3 host builders |
| R4-25 | `steellogic://` deep link | D | App + importer contract |
| R4-26 | Fabricator CSV from import metadata | D | Parser + export pipeline |

---

## Shipped this session (2026-06-24)

| ID | Item | Version notes |
|----|------|---------------|
| R4-S1 | `build_human_summary()` → `extra.human_summary` | pdfcadcore FC/LC/BL; SU qa_report.rb |
| R4-S2 | SketchUp **Import Health…** menu | SU v3.7.61 |
| R4-S3 | Website install-help capability matrix | Website v1.0.56 |

---

## Dependencies / host limits (honest)

- Heatmaps, span replay: **Python hosts only** until SU embeds pdfcadcore extraction (not planned — Ruby path stays).
- 3D text / glyphs: **LibreCAD 2D host** — matrix must keep saying “No 3D text.”
- SketchUp 2017: Import Health works; HtmlDialog preview features may degrade.

---

*Backlog maintained for Round 4 creative QA.*

---

## Addendum — net-new ideas (post-resolution, 2026-06-24)

Source: `QA-2026-06-24_round4-blue-sky-ideation.md` (reconciled fork). Deduped against all items above — these are additive, not duplicates.

| ID | Item | Tier | Why net-new |
|----|------|------|-------------|
| R4-27 | WASM zero-dependency extraction core | P2 (high ceiling) | Eliminates system pip / Ghostscript / PyMuPDF-ABI field failures |
| R4-28 | Browser "drop a PDF → DXF/SVG" tool | P1 (after R4-27) | Zero-install trial + host-independent oracle |
| R4-29 | Multi-renderer consensus (Poppler/MuPDF/mutool) | P1 | Flags silent renderer disagreement; complements R4-02/R4-13 |
| R4-30 | Confidence % line inside `human_summary` | P0 candidate | Cheap bridge from shipped R4-S1 to deferred heatmap R4-13 |
| R4-31 | Plain-language import intent (LLM→config + offline fallback) | P1 | New control surface over mature import config |
| R4-32 | Part-mark cross-reference graph | P1 | Navigation graph; distinct from parser R4-24 / CSV R4-26 |
| R4-33 | Opt-in self-learning correction loop → golden corpus | P2 | Heuristics sharpen on real corrections; feeds R4-02 |

**Suggested first spike:** R4-27 (WASM core) — highest ceiling and directly retires the recurring dependency-failure class.

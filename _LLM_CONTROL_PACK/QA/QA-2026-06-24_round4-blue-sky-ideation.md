# QA-2026-06-24 — Round 4 Addendum: Net-New Ideas (post-resolution)

**Date:** 2026-06-24  
**Status:** ADDENDUM to the **CLOSED** Round 4 creative QA — does NOT reopen the commit gate  
**Reconciliation note:** I joined after Round 4 had already debated, ranked, and shipped its three wins (`human_summary`, SketchUp Import Health, website capability matrix) and forked a parallel ideation by mistake. This file is the reconciled residue: **only ideas not already in** `QA-2026-06-24_round4-innovation-backlog.md`, registered as new IDs **R4-27…R4-33** so nothing is lost and nothing duplicates.

---

## ★ Headline net-new: portability that deletes our #1 field-failure class

**R4-27 — WASM zero-dependency extraction core.** Compile the `pdfcadcore` extraction/render path to WebAssembly so no host needs a system pip, Ghostscript, or an ABI-matched PyMuPDF wheel. This is the exact class of failure we keep fighting (screenshot round #6: Blender 5.1 PyMuPDF not installed; recurring vendored-wheel self-repair). One blob, identical on every PC.
- *Evidence:* repeated PyMuPDF bootstrap / `extra.py` repair work in the field logs.
- *Risk:* Med-High (toolchain, perf). *Shortest safe step:* spike — compile MuPDF/extraction to WASM, extract text spans from `1017 - Rev 0.pdf` in Node, compare span count to the Python core.

**R4-28 — Browser "drop a PDF → get a DXF/SVG" tool** (builds on R4-27). Zero-install web demo on the BlueCollar site; funnels users to the host plugins and doubles as a host-independent truth oracle.
- *Risk:* Low after R4-27. *Step:* static page calling the WASM core; DXF download for one sample.

---
## More net-new ideas (deduped vs the existing backlog)

### Accuracy / trust
- **R4-29 — Multi-renderer consensus.** Run two of Poppler/MuPDF/mutool and flag glyph/path disagreements instead of trusting one silently. Complements golden vectors (R4-02) and the deferred heatmap (R4-13). *Risk: Low. Step:* a `--cross-check` that reports per-page diff count.
- **R4-30 — Confidence % line inside `human_summary`.** Cheap bridge between the shipped summary (R4-S1) and the deferred heatmap (R4-13): add a single "matched ~X% of page ink" number now; the heatmap becomes the visual of the same metric later. *Risk: Low (Python hosts first). Step:* coarse ink-overlap ratio in `build_human_summary`.

### Experience
- **R4-31 — Plain-language import intent.** "Import only the BOM and part marks as editable text on layer STEEL-BOM" → LLM maps to `text_mode` + filters + layers, with a deterministic offline grammar fallback. Natural now that import config is mature. *Risk: Med (must degrade offline). Step:* intent→config mapper with fixed fallback.

### Ecosystem
- **R4-32 — Part-mark cross-reference graph.** Recognize marks (`w1023`, `p1052`); link mark ↔ BOM row ↔ other sheets; click-to-highlight. Distinct from the designation parser (R4-24) and CSV export (R4-26): this is the *navigation graph*, not the takeoff. *Risk: Med. Step:* mark detector + adjacency map in import_report `extra`.
- **R4-33 — Opt-in self-learning correction loop.** When a user fixes a misread quantity/fraction, capture it (anonymized, opt-in **local-only** by default) to feed the golden-vector corpus (R4-02) so heuristics sharpen on real shop drawings over time. *Risk: Med (privacy). Step:* local correction log + corpus import script.

---

## Dedup map — what I deliberately did NOT re-add

| My earlier idea | Already covered by |
|-----------------|--------------------|
| Confidence heatmap / visual oracle | R4-13 + golden vectors R4-02 |
| Scale calibration / cross-check | R4-01 |
| Preflight preview / wizard | R4-04 / R4-20 |
| Steel takeoff / CSV / deep link | R4-16 / R4-24 / R4-25 / R4-26 |
| Auto layer classification | R4-10 |

---

## Recommended single spike (if @owner wants one more)

**R4-27 WASM core proof-of-life** — highest ceiling AND it retires the dependency failures the screenshot round kept hitting. 2–3 days, host-independent, demoable as the R4-28 web tool.

*Addendum only — does not change Round 4 GO/CLOSED status. Net-new items registered in the innovation backlog.*

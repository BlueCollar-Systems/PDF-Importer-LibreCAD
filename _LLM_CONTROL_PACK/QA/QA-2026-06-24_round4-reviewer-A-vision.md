# Round 4 — Reviewer A: SketchUp / 3D CAD Lens

**Session:** 2026-06-24  
**Persona:** Anonymous — thinks like a detailer who lives in SketchUp Pro on a dusty shop PC  
**Mandate:** Wild but grounded. Accuracy and editability beat demo glitter.

---

## What we already have (celebrate honestly)

- `import_report.json` (schema `bcs.import_report/1.1`) on every successful import — machine-readable truth.
- Four text modes (Labels, Geometry, Glyphs, 3D Text) with real trade-offs, not fake parity.
- Bundled Poppler helpers on Windows RBZ; Compatibility Report for first-run sanity.
- Resolved scale from title blocks when the PDF cooperates — this is rare in consumer importers.

---

## Outside-the-box ideas (≥5)

### A-1 — Live import preview (ghost geometry before commit)

**Idea:** While the user picks pages/mode in Import Dialog, render a faint preview group at origin — edges only, no tags committed — updating within 2s on a typical sheet.

**Why it matters:** Shop users abort bad imports *before* polluting the model. Accuracy improves because they catch wrong scale/mode early. UX win: confidence without reading JSON.

**Grounding:** Reuse existing primitive extraction; skip full arc fit / text for preview pass. Host limit: SU 2017 WebDialog vs HtmlDialog — preview must degrade to bounding-box wireframe on old builds.

---

### A-2 — Smart scale from title block + dimension cross-check

**Idea:** When title block says `1/4" = 1'-0"` but a labeled dimension string disagrees by >3%, show a **non-blocking** scale confidence banner: “Title block says 48×; dimension `24'-0"` implies 47.6× — pick one.”

**Why it matters:** Wrong scale is the #1 silent accuracy killer. Cross-checking two independent PDF signals beats guessing.

**Peer challenge to B:** Your confidence heatmaps are pretty — but can they *disagree with each other* loudly enough that a foreman notices?

---

### A-3 — One-click “Match PDF layers → Tags”

**Idea:** Post-import menu: **Match PDF Layers** — maps OCG/layer names to existing Tags by fuzzy match (`A-WALL` → `A-Wall`), with a dry-run list before apply.

**Why it matters:** Detailers already organized tags; re-tagging imports wastes hours. Layer fidelity is an accuracy feature when steel/conduit packs expect named tags.

**Host limit:** Geometry text still lands on one `text_layer` (Round 3 ruling) — this is about *vector* layers, not per-span OCG on text.

---

### A-4 — Import Health dashboard in-model

**Idea:** Extensions menu item showing last run: `import_report` path, `text_mode`, `resolved_scale`, timing, plain-English `human_summary`, log path — no digging in `%TEMP%`.

**Why it matters:** Support calls drop when users can screenshot one dialog. Ties machine report to human language.

**Status this session:** **Shipped** as *Import Health…* (v3.7.61).

---

### A-5 — “What changed since last import?” diff

**Idea:** When re-importing the same PDF (SHA256 match), highlight new/changed primitive counts per page and offer to import only changed pages.

**Why it matters:** Revision clouds on fab drawings are everyday. Importer that respects deltas feels like CAD, not a stamp tool.

**Effort:** Moonshot — needs stable primitive IDs across runs.

---

### A-6 — View-aligned import (pick a scene camera → flatten to 2D working plane)

**Idea:** For skewed PDF exports or screenshot-PDFs, let user pick two model axes + scale line; importer projects vectors onto that plane instead of assuming top view.

**Why it matters:** Field photos and vendor PDFs aren’t always plan-normal. Accuracy for weird inputs without forcing raster-only.

---

## Peer challenges

**To Reviewer C:** Preflight wizard is essential — but don’t hide the four text modes behind jargon. A foreman needs “editable labels vs exact outlines” in the first screen, not page 3.

**To Reviewer D:** Steel shape packs are gold. Link them from Import Health when generic classifier sees `fabrication` profile — “W-shapes detected; open Steel Logic?”

---

## Rank self (impact / effort)

| Idea | Impact | Effort |
|------|--------|--------|
| A-4 Import Health | High | Low — **done** |
| A-2 Scale cross-check | High | Medium |
| A-3 Layer match | High | Medium |
| A-1 Live preview | High | High |
| A-5 Revision diff | Medium | Very high |
| A-6 View-aligned | Medium | High |

---

*Reviewer A — Round 4, 2026-06-24*

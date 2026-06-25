# QA-2026-06-24 — R4-27 / R4-28 Technical Design: WASM Zero-Dependency Core

**Date:** 2026-06-24  
**Status:** DESIGN / PROPOSAL — no code committed; spike-gated  
**Relates to:** backlog `R4-27` (WASM core) + `R4-28` (browser tool); addendum `QA-2026-06-24_round4-blue-sky-ideation.md`  
**Owner decision needed:** substrate/license (see §7) and go/no-go on the Phase-1 spike

---

## 1. Phase 0 feasibility — VALIDATED TODAY (real run, not theory)

Ran in a clean Linux/Node 22 sandbox, no native libraries:

| Probe | Result |
|-------|--------|
| `npm i mupdf` (MuPDF compiled to WASM) | added 1 package in ~5s; **14 MB** on disk; zero native deps |
| Load in Node (ESM) | OK (module is ESM/top-level-await — use `import()`, not `require()`) |
| `openDocument()` + `countPages()` | OK — 1 page |
| `page.toStructuredText().asJSON()` | OK — returned `blocks → lines` with `bbox`, `font {name,family}`, `wmode`; `"WASM 123"` round-tripped |
| `page.toPixmap(...)` raster | OK — 300×200 RGB pixmap |
| Malformed stream `/Length` | MuPDF **auto-repaired** ("PDF stream Length incorrect" warning, still parsed) |

**Takeaway:** the WASM substrate gives us *both* vector text/geometry extraction **and** raster rendering, with MuPDF's well-known tolerance for broken real-world PDFs, in a 14 MB browser-capable package and **no system pip, Ghostscript, or ABI-matched wheel.** That is the entire premise of R4-27, de-risked on day one.

---

## 2. Goal & non-goals

**Goal:** a single extraction/render engine that runs identically on every host and in a browser, eliminating the field-install failure class (Blender 5.1 PyMuPDF ABI, vendored-wheel self-repair) and unlocking the R4-28 web tool.

**Non-goals (this design):**
- Not replacing the SketchUp Ruby engine path (see §5 — SU stays Ruby by ruling).
- Not promising perfect arbitrary-PDF→CAD fidelity (Round 3 / Reviewer B stance stands).
- Not reopening any commit gate; this is a design + spike plan.

---
## 3. The central tension (and how we resolve it)

Reviewer B's strongest point: don't let extraction logic fork. Today `pdfcadcore` (Python) is the canonical engine; the SketchUp path is separate Ruby. A WASM engine risks becoming a **third** implementation that silently diverges.

**Resolution — the contract is the output, not the code.** We freeze the extraction **schema** (the normalized primitives + page data + `import_report` that the core already emits, evolving toward Reviewer B's semantic IR) and make *every* engine prove equivalence against a shared **conformance corpus** (this is exactly R4-02 golden vectors, reused). Divergence becomes a failing test, not a field surprise.

So the WASM engine is not "another importer" — it is a second *conformant producer* of the same IR, gated by the same oracle.

---

## 4. Architecture

```
            ┌─────────────────────────────┐
 PDF ─────▶ │  WASM substrate (MuPDF/…)    │  parse + raster, tolerant
            │  page ops, stext, pixmap     │
            └─────────────┬───────────────┘
                          ▼
            ┌─────────────────────────────┐
            │  Extraction layer            │  heuristics: arc promotion,
            │  → normalized IR + import_   │  flood detect, scale, OCG,
            │    report (FROZEN SCHEMA)    │  dimension parse, text spans
            └─────────────┬───────────────┘
        ┌─────────────────┼───────────────────────────┐
        ▼                 ▼                            ▼
  Browser tool (R4-28)  Python hosts (FC/LC/BL)   Standalone CLI
  DXF/SVG download      call WASM instead of        pdf→dxf, no install
                        requiring native PyMuPDF
```

SketchUp consumes the **same IR/report schema** from its Ruby engine (conformance-tested), but does not embed the WASM runtime.

**Where the extraction layer lives — two strategies:**

- **Strat-A (Pyodide):** run the *existing* `pdfcadcore` Python under Pyodide (CPython→WASM) with a WASM PDF backend. Pro: one codebase, near-zero port, instant lockstep. Con: bundle is large (Pyodide+CPython ~ tens of MB), cold-start slower, and a WASM `fitz`/PyMuPDF backend is the hard part.
- **Strat-B (TS port on MuPDF-WASM):** reimplement the extraction heuristics in TypeScript over the 14 MB MuPDF-WASM proven in §1. Pro: small, fast, browser-native. Con: a second implementation — *only acceptable because* the conformance corpus (§3) holds it to the Python core's output.

Recommendation: **Strat-B for the browser tool/CLI now** (small, proven), **evaluate Strat-A later** for desktop hosts if we want literally one codebase. Both are bound by the same IR conformance tests.

---
## 5. Substrate & licensing — the one decision to get right first

The §1 proof used **MuPDF-WASM**, which is **AGPL-3.0 or commercial (Artifex)** — same family as the **PyMuPDF** the desktop hosts already ship.

| Implication | Detail |
|-------------|--------|
| Desktop bundling (FC/LC/BL) | Already accepting AGPL via vendored PyMuPDF; public repos satisfy source-availability. No new posture. |
| **Public web tool (R4-28)** | AGPL **§13** (network use) requires offering the served app's source to users. Fine **only if** the web tool is open-sourced; otherwise it's a license violation. |

**Permissive alternatives (no copyleft) for the public web tool:**

- **PDFium-WASM** (BSD-3, Google) — strong parse + raster; clean for hosted/redistributed use.
- **pdf.js** (Apache-2.0, Mozilla) — pure JS, browser-native, good text/op extraction; no WASM blob at all.

**Recommendation:** desktop hosts may keep the MuPDF/PyMuPDF line; for the **public web tool prefer PDFium-WASM or pdf.js** unless @owner is comfortable AGPL-licensing the web tool source. Given the team's licensing caution (SketchUp-2017 policy), this is **Decision D-LIC** and should be settled before Phase 2.

---

## 6. Phased plan & acceptance criteria

| Phase | Work | Acceptance | Effort |
|-------|------|-----------|--------|
| **0 — substrate** ✅ | Prove WASM parse+raster (done §1) | MuPDF-WASM parses + rasters a PDF, no native deps | DONE |
| **1 — IR conformance spike** | On real `1017 - Rev 0.pdf`: WASM extract → emit frozen `import_report` IR; diff span/drawing counts + key anchors vs Python `pdfcadcore` | Counts within tolerance; side-by-side diff report produced; D-LIC chosen | 2–3 d |
| **2 — web tool (R4-28)** | Static page: drop PDF → extract → **DXF/SVG download**; honest capability copy; link from site | `1017` downloads a DXF that opens in LibreCAD with expected layers/text | 3–4 d |
| **3 — desktop adoption (optional)** | FC/LC/BL call WASM engine via bridge; native PyMuPDF becomes fallback | Fresh machine, **no** system PyMuPDF, imports `1017` OK — kills the field-failure class | larger |

Every phase is gated by the **conformance corpus (R4-02)** so the WASM and Python engines cannot silently diverge.

---
## 7. Host impact

| Host | Changes | Benefit | Risk |
|------|---------|---------|------|
| Browser/web (new) | New static tool on site | Zero-install trial + host-independent oracle | License (D-LIC); fidelity expectations |
| FreeCAD / LibreCAD / Blender | Optional WASM bridge; native PyMuPDF kept as fallback | Ends ABI/wheel install failures | Perf; bridge plumbing |
| **SketchUp** | **None** — Ruby engine stays; only consumes the shared IR schema | Conformance keeps it honest vs other hosts | — |
| Steel Logic app | Could later embed the same WASM extractor for in-app preview | Unifies the pipeline | Out of scope here |

---

## 8. Risks & mitigations

- **License (AGPL)** → D-LIC: permissive substrate (PDFium/pdf.js) for the public web tool. *Highest-priority risk.*
- **Bundle size / cold start** → MuPDF-WASM is 14 MB (fine for desktop/CLI; lazy-load + cache for web). Pyodide path (Strat-A) is much heavier — defer.
- **Fonts in WASM (no system fonts)** → bundle base-14; non-embedded fonts fall back to outline/metrics; surface as an `import_report` warning (ties to span-quality R4-05).
- **WASM-vs-native determinism** → pin substrate version (B3 deterministic fixtures); use R4-29 multi-renderer consensus to flag drift.
- **IR drift between engines** → the conformance corpus (R4-02) is the guardrail; no engine ships without passing it.
- **Strat-A PyMuPDF-in-Pyodide availability** → unproven; keep Strat-B (proven §1) as the path; revisit Strat-A only if "one codebase" becomes a priority.

---

## 9. Open decisions (for @owner / reviewers)

| ID | Question | Options |
|----|----------|---------|
| D-LIC | Web-tool substrate license | MuPDF/AGPL + open-source the tool / **PDFium-WASM (BSD)** / pdf.js (Apache) |
| D-STRAT | Extraction implementation | **Strat-B (TS on WASM, proven)** / Strat-A (Pyodide, one codebase) |
| D-SCOPE | Web tool exposure | public marketing tool / internal oracle first |
| D-OWN | Spike owner | Reviewer B (core) likely, with D (website) for Phase 2 |

---

## 10. Recommended next step

Approve the **Phase-1 conformance spike on `1017 - Rev 0.pdf`** (2–3 days), evaluating a permissive substrate in parallel for D-LIC. Phase 0 already proves the substrate works; Phase 1 proves the *output matches the canonical core*, which is the real question. I can execute Phase 1 on request.

*Design — does not change any commit/ship status. Builds on Phase-0 evidence captured 2026-06-24.*

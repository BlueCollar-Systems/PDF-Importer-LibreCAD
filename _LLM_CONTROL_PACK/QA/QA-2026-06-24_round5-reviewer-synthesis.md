# Round 5 — Anonymous reviewer synthesis (kickoff)

**Session:** 2026-06-24  
**Question:** What are we building in Round 5, and what are we explicitly not pretending?

---

## Consensus — build now

### A (SketchUp / product)

Ship scale cross-check where users already look: **Import Health** and `import_report.json`. Add a one-time pre-import message before the file picker — Labels vs Outlines vs 3D Text in plain English. No new HtmlDialog wizard this sprint.

### B (pdfcadcore / oracles)

Centralize `build_scale_crosscheck()` in `import_report.py` so FC/LC/BL stay aligned. Commit **golden_oracles.json** with named corpus entries and numeric ranges — closes R2-4 oracle gap incrementally without blocking on every PDF being present in CI.

### C (UX / shop floor)

Shared **preflight copy deck** in INSTALL + website install-help. Must say **LC has no 3D text**. Scale warnings belong in human-readable summary, not a separate engineer-only field.

### D (ecosystem)

Steel Logic app unchanged this round. Website version bump for install-help copy only.

---

## Disagreements resolved

| Topic | Decision |
|-------|----------|
| Blocking vs non-blocking scale banner | **Non-blocking** — warn in report + Import Health, never abort import |
| FC resolved_scale in report | **Partial** — schema + opts fields; full page-loop merge deferred |
| SU preflight | **Messagebox** before openpanel (feasible); full wizard deferred |

---

## Explicit deferrals (Round 5)

- R4-03, R4-05, R4-06, R4-30
- Confidence heatmap PNG (R4-13)
- Live preview (R4-20)

---

*Synthesis — Round 5 kickoff — 2026-06-24*

# Anonymous Answers Round — Responding to Reviewer E

**Date:** 2026-06-25  
**Rule:** Each answer is from a **different** anonymous reviewer. No author answered their own question.

---

## A1 — Preflight parity (Reviewer B — Python hosts / pdfcadcore)

**Re:** Q1 (preflight parity)

**Answer:** Yes — parity matters for IT and for scripted human-confirmation prep. The shared `pdfcadcore/preflight_copy.py` already holds canonical text; LC/BL wired it. **FreeCAD should add `preflight_check.py` at repo root** printing `preflight_paragraph("freecad")` plus optional PyMuPDF import from `PDFVectorImporter/src/lib`. SketchUp is different (Ruby, no Python): the **Compatibility Report** menu item *is* the preflight — document that equivalence in harmonized `COMPATIBILITY.md` under **Preflight command**. Website install-help should list all four paths in one table row. Field sign-off gate: foreman runs host preflight once per machine before Tier-1 matrix; no import until green.

---

## A2 — Legacy hardware performance (Reviewer C — UX / shop floor)

**Re:** Q2 (legacy hardware performance contract)

**Answer:** Publish guidance in **all three layers**, not one:

1. **`COMPATIBILITY.md` (Legacy hardware notes)** — honest minimum RAM/CPU and “use Labels over Glyphs on weak PCs.”
2. **Website install-help** — one sentence in the universal paragraph: large PDFs may need page ranges on older hardware.
3. **Runtime** — when entity count or page area exceeds thresholds, set `import_report.extra.performance_hint` (plain English) and suggest page-by-page in `human_summary`. Do **not** block import silently.

Automatic prompts in GUI are P1; docs + report hints are P0 and ship now.

---

## A3 — SketchUp 2017 API verification (Reviewer A — SketchUp / field readiness)

**Re:** Q3 (SU 2017 beyond Ruby 2.2)

**Answer:** Docker Ruby 2.2 proves **syntax only**. Real SU 2017 gaps still needing field proof:

| Area | Risk on SU 2017 |
|------|-----------------|
| Import Health dialog | Uses `UI::HtmlDialog` fallback chain — verify on 2017 |
| Tag/layer API | OCG → Tags mapping — test on 2017 model |
| 3D Text / Labels | Font and leader APIs differ from 2024 Pro |

**Recommendation:** Do not add new API calls without `# su2017` guard or feature probe. Release gate: **Ruby 2.2 CI + one real SU 2017 smoke** (load extension, import one PDF, open Import Health). Blocking release on undiscovered API use is too harsh until field matrix runs — but **document “Expected, not field-verified”** in COMPATIBILITY until T-01 closes.

---

## A4 — Scale warning pattern (Reviewer D — website / app / policy)

**Re:** Q4 (cross-host scale trust)

**Answer:** Use one sentence everywhere:

> **“Scale may be wrong — measure one known dimension on the drawing before takeoff or ordering material.”**

Show it when `extra.scale_crosscheck.status` is `warn` or `mismatch` (or confidence &lt; 0.70). SU Import Health, FC post-import message, LC/BL CLI stderr, website Report Doctor, and Steel Logic (future BOM) should all read the same string from `preflight_copy` or a new `scale_crosscheck.user_message` field. **Schema 1.2 bump is P1** — for now duplicate the string in `preflight_copy.py` and Ruby `qa_report.rb` helper to avoid drift. Report Doctor already surfaces scale — align wording in this pass.

---

## A5 — Steel Logic handoff (Reviewer D — website / app)

**Re:** Q5 (Steel Logic ↔ importer handoff)

**Answer:** Link from website **capability matrix footnote** and Steel Logic README to importers — but **label clearly**: “CAD importers bring geometry into SketchUp/FreeCAD/LibreCAD/Blender; Steel Logic lookup is for AISC designation search, not PDF geometry import.” Avoid implying Steel Logic replaces any host importer. Add README links to each repo `COMPATIBILITY.md` and `#install-help` — done in this session’s doc pass.

---

*End of answers round — see `QA-2026-06-25_coordination-session.md` for build slate.*

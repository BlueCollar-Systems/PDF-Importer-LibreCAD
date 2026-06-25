# Anonymous Questions Round — Universal Compatibility & Power

**Date:** 2026-06-25  
**Author:** Anonymous Reviewer E (cross-host / legacy hardware lens)  
**Rules:** Questions only — no self-answers. Respond in `QA-2026-06-25_anonymous-answers-round.md`.

---

## Q1 — Preflight parity before field sign-off

LC has `preflight_check.py --install`, BL has `preflight_check.py --preflight`, and SU exposes **Compatibility Report** + **Import Health** in the GUI. FreeCAD documents preflight copy in `INSTALL.md` but lacks a repo-root `preflight_check.py` like LC/BL.

**Question:** What is the minimum preflight surface every host must expose so a non-technical shop foreman can confirm “this PC is ready” *before* importing a Tier-1 PDF — and should FC/SU ship a one-command terminal preflight for IT staff parity?

---

## Q2 — Legacy hardware performance contract

Briefings target “oldest hardware possible,” but only SU dense-text fixes and generic `human_summary` warnings document performance behavior today. Glyph/geometry modes can explode entity counts on weak PCs.

**Question:** Should we publish explicit page-count / entity-count guidance (or automatic page-by-page prompts) per host when RAM &lt; 8 GB or CPU is pre-2015 — and where should that live: `COMPATIBILITY.md`, website install-help, or runtime `import_report.json` thresholds?

---

## Q3 — SketchUp 2017 beyond Ruby 2.2 syntax

v3.7.67+ fixed endless-range and `.positive?` load failures. CI now scans Ruby 2.2 syntax, but SU 2017 also lacks modern APIs (`line_styles`, some UI helpers).

**Question:** Which remaining SketchUp 2017 API gaps are still **unverified in a real 2017 session** (not Docker Ruby-only), and should we block release if any shipped menu path calls an API introduced after SU 2018?

---

## Q4 — Cross-host scale trust for non-technical users

Round 5 shipped `extra.scale_crosscheck` in import reports, but each host surfaces scale differently (SU Import Health vs FC ShapeString workflow vs LC DXF with no in-app scale tool).

**Question:** What single plain-English scale warning pattern should appear in **all four hosts + website Report Doctor** so a fabricator knows “stop and verify one dimension” without reading JSON — and is a shared `scale_crosscheck.banner_text` field in `bcs.import_report/1.2` worth a schema bump?

---

## Q5 — Steel Logic ↔ importer handoff (bonus)

Steel Logic now has PDF Callout Lookup; full BOM bridge from `import_report.json` remains open (T-10).

**Question:** For shop-floor users who start in SketchUp/FreeCAD and finish takeoff in Steel Logic, should the website capability matrix link directly to the app’s callout workflow — or keep steel and CAD importers visually separate to avoid implying feature parity?

---

*End of questions — awaiting anonymous answers from other reviewers.*

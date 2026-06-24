# Round 5 — Kickoff

**Session:** 2026-06-24  
**Follows:** Round 4 Phase 1 complete · Phase 2 open  
**Goal:** Ship first P0 backlog slice with honest deferrals

---

## Scope (this session)

| ID | P0 item | Target |
|----|---------|--------|
| R4-01 | Scale cross-check banner | `extra.scale_crosscheck` + `human_summary` + SU Import Health |
| R4-02 | Golden-vector oracles | `test/fixtures/golden_oracles.json` + QA doc |
| R4-04 | Preflight copy deck | INSTALL + website `#install-help` + SU pre-import messagebox |

**Deferred to next session:** R4-03 CLI stderr templates · R4-05 span_quality · R4-06 LC/BL `--preflight` one-liner · R4-30 confidence % in summary

---

## Success criteria

- [ ] Scale warning appears in import_report when confidence &lt; 70% or title-block tension detected
- [ ] SU Import Health surfaces scale warning line
- [ ] Golden oracles JSON committed with 3–5 named entries
- [ ] Shared preflight text in FC/LC INSTALL + website
- [ ] Tests green: SU `qa_report_test.rb`, FC `test_import_report_human_summary.py`, pdfcadcore sync
- [ ] Version bumps for user-visible hosts only
- [ ] Commits pushed on all touched repos

---

## Host notes

- **pdfcadcore** canonical in FreeCAD; sync LC/BL
- **SketchUp** Ruby mirror in `qa_report.rb` (no embedded pdfcadcore)
- **FreeCAD** `resolved_scale` wiring in ImportOptions prepared; full page-loop merge deferred
- **Field PDFs** not required for unit tests; oracles use corpus_key + ranges

---

*Round 5 kickoff — 2026-06-24*

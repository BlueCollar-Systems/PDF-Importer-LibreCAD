# Coordination Session — Anonymous Q&A Synthesis (2026-06-25)

**Inputs:** Instructions 0607202613216.txt, third-party briefing, status briefs, anonymous Q&A round (questions + answers), open threads T-01–T-15.

**Agreement:** 4/4 prior GO on doc push stands. This session adds **universal compatibility** doc/code slice — docs-first, no version bump unless user-visible install text changes.

---

## What the group agrees to build next

| Priority | Item | Rationale | Owner this pass |
|----------|------|-----------|-----------------|
| **P0** | Harmonize `COMPATIBILITY.md` (SU/FC/LC/BL) | Same sections: minimum host, oldest tested, ABI, bundled deps, legacy hardware, preflight | **This worker — DONE in repos** |
| **P0** | Website install-help universal paragraph | “Works on any PC that runs [host]…” + SU 2017 v3.7.67+ | **This worker — DONE** |
| **P0** | FC `preflight_check.py` | Closes Q1 / C-10 parity gap for FreeCAD | **This worker — DONE** |
| **P0** | Steel Logic README → importers + matrix | Non-technical discoverability | **This worker — DONE** |
| **P0** | Mirror Desktop Q&A → 6 repos | Process rule from Instructions | **This worker — DONE** |
| **P0** | Human field retest (T-01) | Still blocks release sign-off | **Product owner / human tester** |
| **P1** | Shared scale banner text in all hosts | A4 consensus — string in preflight_copy + Report Doctor | **Others — WS-R5** |
| **P1** | `import_report.extra.performance_hint` | A2 legacy hardware runtime hints | **Others — WS-PERF** |
| **P1** | SU 2017 real-host smoke checklist | A3 — beyond Docker Ruby | **Others — WS-FIELD** |
| **P1** | R4-03 CLI stderr templates (T-07) | LC/BL plain errors | **Others — WS-R5** |
| **P1** | Steel Logic BOM bridge (T-10) | import_report/CSV ingestion | **Others — WS-R6** |
| **P2** | Schema 1.2 `scale_crosscheck.user_message` | Avoid duplicated strings long-term | **Others — WS-CORE** |

---

## Workstream assignments for **others**

### WS-FIELD — Human confirmation & screenshot retest
- **Owner:** Anonymous field tester / product owner  
- **Do:** Run `QA-2026-06-24_human-confirmation-script.md` (60–90 min). Retest eleven field screenshots. SU 2017 must use **v3.7.68**.  
- **Log:** Append `QA-2026-06-24_worker-status-log.md`  
- **Unblocks:** T-01, release sign-off

### WS-R5 — Scale + CLI polish
- **Owner:** Next available Python/Ruby reviewer  
- **Do:** Unify scale warning string (A4); ship R4-03 stderr templates (T-07); optional schema 1.2 field  
- **Verify:** Report Doctor + SU Import Health show identical wording

### WS-PERF — Legacy hardware guidance
- **Owner:** Performance-focused reviewer  
- **Do:** Define thresholds for `performance_hint`; document in COMPATIBILITY legacy sections; optional GUI prompt P1  
- **Verify:** Large corpus PDF on 8 GB RAM machine — import completes with readable warning

### WS-R6 — Steel Logic BOM bridge
- **Owner:** App reviewer  
- **Do:** ingest `import_report.json` or CSV export for takeoff; keep callout lookup separate from geometry import  
- **Verify:** 1017-class PDF → shape list without re-importing geometry

### WS-CORE — pdfcadcore / sync
- **Owner:** FreeCAD canonical maintainer  
- **Do:** Any preflight_copy or scale string change → regenerate manifest, `pdfcadcore_sync_check.py`  
- **Verify:** ALL IN SYNC across FC/LC/BL

---

## Status log (this session)

```
2026-06-25 | WS-COMPAT | Anonymous coordination worker | DONE | Phase 1 Q&A round (4Q + 3A + synthesis); COMPATIBILITY harmonization; FC preflight_check.py; website install paragraph; Steel README links; Desktop + 6-repo mirror; docs-only commits
```

Full append also in `QA-2026-06-24_worker-status-log.md` (Desktop + repo mirrors).

---

## Decision state

- **Engineering:** Ready for renewed field testing with harmonized compatibility docs.  
- **Release sign-off:** Still blocked on T-01 human confirmation.  
- **Next human action:** Download current website releases → run preflight on each host → Tier-1 matrix.

---

*Coordination session — anonymous reviewers — 2026-06-25*

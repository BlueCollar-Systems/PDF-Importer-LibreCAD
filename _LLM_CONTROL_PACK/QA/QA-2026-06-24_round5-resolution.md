# Round 5 — Resolution

**Session:** 2026-06-24  
**Status:** **Partial ship — P0 slice 1**

---

## Shipped

| ID | Item | Notes |
|----|------|-------|
| R4-01 | Scale cross-check banner | `build_scale_crosscheck()` in pdfcadcore; `extra.scale_crosscheck` + banner in `human_summary`; SU Ruby mirror; Import Health warning line; LC/BL wired |
| R4-02 | Golden-vector oracles | `test/fixtures/golden_oracles.json` — 5 named oracles with path/text/placement/scale ranges |
| R4-04 | Preflight copy deck | `pdfcadcore/preflight_copy.py`; FC/LC INSTALL; website `#install-help`; SU pre-import messagebox |

---

## Deferred (honest)

| ID | Item | Reason |
|----|------|--------|
| R4-03 | CLI plain-English stderr templates | Needs LC/BL CLI error map pass |
| R4-05 | `span_quality` aggregate | Depends on span replay infra |
| R4-06 | LC/BL `--preflight` one-liner | Next host CLI pass |
| R4-30 | Confidence % in human_summary | Cheap follow-up after scale banner validated |
| FC full resolved_scale page merge | ImportOptions fields added; page-loop detection not wired this session |

---

## Versions (user-visible)

| Host | Version |
|------|---------|
| SketchUp | 3.7.62 |
| Website | 1.0.59 |
| FreeCAD | 4.0.44 |
| LibreCAD | 1.0.38 |
| Blender | 1.0.41 |

---

## Tests run

| Check | Result |
|-------|--------|
| SU `ruby test/qa_report_test.rb` | see commit |
| FC `python -m pytest tests/test_import_report_human_summary.py` | see commit |
| pdfcadcore sync | FC canonical → LC/BL copied |

---

## Round 4 status after Round 5

Round 4 remains **Phase 2 open**. Round 5 closed three P0 items; four P0 items remain on backlog.

---

*Resolution — 2026-06-24*

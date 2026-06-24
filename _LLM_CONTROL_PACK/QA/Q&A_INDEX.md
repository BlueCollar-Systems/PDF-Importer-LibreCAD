# Q&A Index

Updated: 2026-06-24 (Field screenshot review — validation/commit in progress)

## Source Instructions

- `Instructions 0607202613216.txt`

---

## Field screenshot review (2026-06-24) — **FIXED LOCALLY / VALIDATING**

Eleven field screenshots — BOM vertical text, Blender 5.1 PyMuPDF, LC launcher, SketchUp 2017 installer policy.

| File | Role |
|------|------|
| `QA-2026-06-24_screenshot-review-synthesis.md` | Per-screenshot symptoms, root causes, fixes |
| `QA-2026-06-24_text-mode-verification-matrix.md` | Host × text mode expected output + verify steps |
| `QA-2026-06-24_sketchup-2017-installer-website-policy.md` | **Do not host** SketchUp Make 2017 installer |

**Headline:** SU v3.7.59+ BOM quantity rotation/anchor; Blender PyMuPDF bootstrap plus helper/path repair; FC ShapeString sizing; LC installed launcher discovery + portable-first docs; website non-redistribution note.

---

## Text & leader alignment (2026-06-23) — **FIXED**

SketchUp Labels + 3D Text placement/leader alignment root cause and verification.

| File | Role |
|------|------|
| `QA-2026-06-23_text-leader-alignment-rootcause.md` | What was wrong (leader vector vs rotation; double 3D anchor shift) |
| `QA-2026-06-23_text-leader-alignment-fix.md` | What changed, how to verify, test commands |

**Headline:** SketchUp v3.7.58 — horizontal labels use zero leader vector; rotated labels route to mesh text; 3D Text shares single left/baseline anchor with Labels. FreeCAD/LibreCAD text paths unchanged; Blender gained headless import-report robustness during validation.

---

## Round 3 — Full-repo scan (2026-06-23) — **CLOSED**

**Status:** All questions **RESOLVED** (Q1–Q5). **GO** to push — see `QA-2026-06-23_round3-resolution.md`.

| File | Role |
|------|------|
| `QA-2026-06-23_round3-reviewer-A-errors.md` | Errors/bugs (or evidence of none) |
| `QA-2026-06-23_round3-reviewer-B-improvements.md` | Improvement opportunities, Round-2 deferred items |
| `QA-2026-06-23_round3-reviewer-C-cross-repo.md` | pdfcadcore sync, parity, CI across repos |
| `QA-2026-06-23_round3-reviewer-D-app-website.md` | Steel Logic app + BlueCollar website |
| `QA-2026-06-23_round3-synthesis.md` | Consolidated findings, disagreements, commit plan |
| `QA-2026-06-23_round3-resolution.md` | **Final agreement** — all disagreements closed, GO to push |
| `QA-2026-06-23_round3-awaiting-feedback.md` | Feedback phase (**CLOSED**) |
| `QA-2026-06-23_round3-user-rulings.md` | User rulings log (Q1–Q5) |

**Round-3 headline:** Automated tests and pdfcadcore sync green; Q1–Q5 ruled via Round 2 defaults; QA mirrors committed to all six repos.

---

## Round 2 — Challenge & Resolution (2026-06-23)

Round-1 conclusions challenged by three skeptical reviewers; resolution sets **CONDITIONAL GO** for field retest.

| File | Location |
|------|----------|
| Round-2 reports | `_LLM_CONTROL_PACK/QA/` in each importer repo and `1BlueCollar-Website` |
| Authoritative outcome | `QA-2026-06-23_round2-resolution.md` |

**Round-2 conclusion:** Dense-text fix accepted; soften overclaims; blocking sign-off = R2-3 timed benchmark + manual retest after SketchUp restart.

---

## Round 1 — Anonymous improvement reports (2026-06-23)

See `_LLM_CONTROL_PACK/QA/` in repos for:

- `QA-2026-06-23_improvement-report-01.md` … `04.md`
- `QA-2026-06-23_improvement-reports-synthesis.md`

---

## Mirror note

Desktop folder (`PDFTest Files\Q&A`) is the **anonymous reviewer drop zone**. In-repo copies live under `_LLM_CONTROL_PACK/QA/` — synced after Round 3 closure (2026-06-23).

---

## Test evidence (Round 3 session)

| Check | Result |
|-------|--------|
| SU `qa_report_test.rb` | 4/4 pass |
| FC/LC/BL `pdfcadcore_sync_check.py` | ALL IN SYNC |
| FC pytest (subset) | 60 pass |
| LC pytest | 39 pass |
| BL pytest | 36 pass |
| Website `validate_static_metadata.py` | pass |
| Steel `flutter analyze` / `flutter test` | clean / 153 pass |

---

*Index maintained for anonymous Q&A workflow.*

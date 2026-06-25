# Q&A Index

Updated: 2026-06-25 (Four-reviewer agreement GO · Round 4 Phase 2 open · field retest pending)

---

## Coordination Hub — **READ THIS FIRST**

All agents, reviewers, and human testers communicate through the hub — not in isolation.

| File | Role |
|------|------|
| **`QA-2026-06-24_COORDINATION-HUB.md`** | **Single source of truth** — active workstreams, blockers, handoffs, agreement state |
| `QA-2026-06-24_worker-status-log.md` | Append-only status log (start / update / blocked / done) |
| `QA-2026-06-24_open-threads.md` | Unresolved questions; reply in `QA-*-reply-*.md` |
| `QA-2026-06-25_commit-readiness-confirmation.md` | Prior commit-readiness gate (5 signals) |
| **`QA-2026-06-24_agreement-synthesis.md`** | **Four-reviewer vote table — 4/4 AGREE, GO to push** |
| `QA-2026-06-24_agreement-reviewer-A.md` | SketchUp / field-readiness vote |
| `QA-2026-06-24_agreement-reviewer-B.md` | Python hosts + pdfcadcore sync vote |
| `QA-2026-06-24_agreement-reviewer-C.md` | Process / coordination vote |
| `QA-2026-06-24_agreement-reviewer-D.md` | Website + Steel app + policy vote |

Mirrors: `_LLM_CONTROL_PACK/QA/` in each of the six repos.

---

## Source Instructions

- `Instructions 0607202613216.txt`

---

## Round 6 - Public corpus, synthetic stress, app feature slate (2026-06-24) - **ACTIVE**

Fresh "get serious" pass: scour the web for PDF stress files, acquire/test a stronger corpus, identify app features, and prepare for full human interactive confirmation.

| File | Role |
|------|------|
| `QA-2026-06-24_test-corpus-web-research.md` | Web corpus sources, licensing, tiered acquisition recommendations |
| `QA-2026-06-24_app-feature-recommendations.md` | Steel Logic/importer ecosystem feature priorities |
| `QA-2026-06-24_human-confirmation-script.md` | Human confirmation checklist and host matrix |
| `QA-2026-06-24_round6-corpus-and-features.md` | Synthetic stress corpus + oracle notes + feature slate |
| `QA-2026-06-24_round6-public-corpus-coordination-addendum.md` | Public web-acquired corpus tooling, validation, cross-review challenge list |
| `QA-2026-06-24_round6-app-shape-lookup-implementation.md` | Steel Logic copied-callout shape lookup implementation and validation |

**Round-6 headline so far:** targeted synthetic stress corpus exists in the shared test folder; public web-acquired corpus is now locally acquired under `C:\1pdf-test-corpus\web-acquired`; SketchUp headless corpus placement gate passes 26 PDFs with 25 OK + 1 expected encrypted-PDF refusal; Steel Logic now has copied-callout shape lookup, while the larger PDF-BOM/takeoff bridge remains open.

---

## Outside-Box Extension (2026-06-24) — **ACTIVE / LATEST PASS IMPLEMENTED**

Follow-up reviewer pass after Round 4 asked whether we had pushed far enough on accuracy, power, install trust, and user support.

| File | Role |
|------|------|
| `QA-2026-06-24_outside-box-reviewer-A-sketchup.md` | SketchUp/product-engineering review |
| `QA-2026-06-24_outside-box-reviewer-B-fc-lc-core.md` | FreeCAD/LibreCAD/pdfcadcore review |
| `QA-2026-06-24_outside-box-reviewer-C-blender.md` | Blender review and Blender 5.1.2 smoke evidence |
| `QA-2026-06-24_outside-box-reviewer-D-website-app.md` | Website/app/download/install UX review |
| `QA-2026-06-24_outside-box-resolution-and-actions.md` | Implemented actions, deferred work, validation, commit scope |

**Latest implemented pass:** website Report Doctor for local `import_report.json` analysis; public metadata no longer includes private Steel-Shapes release assets; metadata validation now guards that rule; Steel Logic privacy policy now reflects inventory/job-clock/export/support/sync behavior.

**Important status correction:** this does **not** close the overall QA session. It only records the latest implemented/validated pass while reviewers and follow-up work remain active.

---

## Round 5 — P0 backlog (2026-06-24) — **IN PROGRESS / PARTIAL SHIP**

First P0 slice from Round 4 backlog: scale cross-check, golden oracles, preflight copy.

| File | Role |
|------|------|
| `QA-2026-06-24_round5-kickoff.md` | Scope, P0 targets, success criteria |
| `QA-2026-06-24_round5-reviewer-synthesis.md` | Anonymous reviewer kickoff synthesis |
| `QA-2026-06-24_round5-resolution.md` | Shipped vs deferred, versions, tests |

**Round-5 headline:** `extra.scale_crosscheck` in import_report (pdfcadcore + SU); golden oracles JSON; preflight copy in INSTALL + website + SU messagebox; SU v3.7.62; website v1.0.59.

---

## Round 4 — Creative QA (2026-06-24) — **PHASE 1 COMPLETE · PHASE 2 OPEN**

Anonymous reviewers asked: *Have we gone outside the box?* Debated, ranked, and shipped the first low-risk build slate. The wider outside-box QA session remains active until all reviewers are finished, disagreements are resolved, implementation is complete, validation is green, and commits/pushes are confirmed.

| File | Role |
|------|------|
| `QA-2026-06-24_round4-reviewer-A-vision.md` | SketchUp / 3D CAD — preview, scale, layers, Import Health |
| `QA-2026-06-24_round4-reviewer-B-vision.md` | pdfcadcore — heatmaps, span quality, human_summary |
| `QA-2026-06-24_round4-reviewer-C-vision.md` | UX / shop floor — preflight, plain errors, capability matrix |
| `QA-2026-06-24_round4-reviewer-D-vision.md` | Steel Logic ecosystem — PDF→steel workflow |
| `QA-2026-06-24_round4-debate.md` | Cross-review debate + impact/effort ranking |
| `QA-2026-06-24_round4-innovation-backlog.md` | P0 / P1 / moonshot backlog |
| `QA-2026-06-24_round4-resolution.md` | **Phase 1 shipped · Phase 2 open** |
| `QA-2026-06-24_round4-status-reopen.md` | Honest team status note (reopen) |
| `QA-2026-06-24_round4-blue-sky-ideation.md` | Post-resolution addendum — net-new ideas R4-27…R4-33 (WASM core, web tool, multi-renderer, NL import, part-mark graph, self-learning) |
| `QA-2026-06-24_round4-report-doctor-implementation.md` | Round 4 extension — website Import Report Doctor implementation and safety decisions |
| `QA-2026-06-24_round4-status-correction.md` | Corrects premature "closed" wording; Round 4 remains active |

**Round-4 headline:** `extra.human_summary` in import_report (all Python hosts + SketchUp); **Import Health…** menu (SU v3.7.61); website install-help capability matrix (v1.0.56); website Import Report Doctor for local report diagnosis (v1.0.57).

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

Desktop folder (`PDFTest Files\Q&A`) is the **anonymous reviewer drop zone**. In-repo copies live under `_LLM_CONTROL_PACK/QA/` and are synced as implementation passes finish.

---

## Test evidence (Round 4 session)

| Check | Result |
|-------|--------|
| SU `qa_report_test.rb` | run at commit |
| FC `test_import_report_human_summary.py` | run at commit |
| FC/LC/BL `pdfcadcore_sync_check.py` | ALL IN SYNC |
| Website capability matrix | manual / metadata validate |

---

*Index maintained for anonymous Q&A workflow.*

# Q&A Index

Updated: 2026-07-01 (full contributor handoff published)

---

## **START HERE for new contributors**

| File | Role |
|------|------|
| **`QA-2026-06-26_contributor-handoff.md`** | **AUTHORITATIVE** — complete autonomous onboarding: all repos, architecture, QA, release pipeline, day-one playbook, backlog, anti-patterns |
| **`Instructions 0607202613216.txt`** | Anonymous Q&A rules — ≥4 questions, ≥3 cross-answers, no self-answers |

Read the contributor handoff first. Follow linked paths into repo mirrors only when you need depth on a specific topic.

---

## Active session — field regression + Round 2 (2026-06-25/26)

Anonymous reviewers maximizing accuracy, power, and **any-PC / any-host** compatibility per `Instructions 0607202613216.txt`.

| File | Role |
|------|------|
| **`QA-2026-06-26_regression-popup-scale-alignment.md`** | Field regression — SketchUp popup removal, Labels-mode entity contract, FreeCAD bbox-fit for Labels/3D Text |
| **QA-2026-06-26_regression-popup-alignment-questions.md** | Field regression Q — popup, BOM, FC overlap |
| **QA-2026-06-26_regression-popup-alignment-answers.md** | Answers |
| **QA-2026-06-26_regression-popup-alignment-resolution.md** | Shipped R26-1…R26-5 |
| **`QA-2026-06-24_third-party-project-briefing.md`** | Extended onboarding — mission, architecture, versions, FAQ *(repo mirror)* |
| **`QA-2026-06-25_round2-anonymous-questions.md`** | Round 2 — Reviewers F/G/H/I (offline, fonts, roam, PDF JS) |
| **`QA-2026-06-25_round2-anonymous-answers.md`** | Round 2 — Full cross-matrix answers |
| **`QA-2026-06-25_round2-resolution.md`** | Round 2 — Agreements R2-1…R2-8 + GO gate |
| **`QA-2026-06-25_round2-coordination-addendum.md`** | Shipped slice + open threads |
| **`QA-2026-06-25_anonymous-questions-round.md`** | Round 1 — Reviewer E *(repo mirror)* |
| **`QA-2026-06-25_anonymous-answers-round.md`** | Round 1 — Reviewers A/B/C/D *(repo mirror)* |
| **`QA-2026-06-25_coordination-session.md`** | Round 1 build slate *(repo mirror)* |
| **`QA-2026-06-25_reply-ecosystem-audit-and-cross-round.md`** | 11-lens audit (23 findings, 3 P0 in release pipeline) |
| **`QA-2026-06-25_release-pipeline-p0-resolution.md`** | P0-A/B/C shipped (FC windows + smoke, LC portable `--latest`, all-host release gates) |
| **`QA-2026-06-25_reply-dependency-confidence-and-live-state.md`** | Bundled-dependency manifest tool *(repo mirror)* |
| **`QA-2026-06-24_worker-status-log.md`** | Append-only status |
| **`QA-2026-06-24_COORDINATION-HUB.md`** | Single team channel *(repo mirror)* |
| **`QA-2026-06-24_open-threads.md`** | P0/P1/P2 threads *(repo mirror)* |
| **`QA-2026-06-24_human-confirmation-script.md`** | 60–90 min field test script *(repo mirror)* |

> ✅ **P0 RESOLVED (2026-06-25):** release-pipeline fixes in `QA-2026-06-25_release-pipeline-p0-resolution.md` — FC/LC auto-release on `windows-latest`, LC portable published as `--latest`, all four hosts gate before publish.

**Canonical repo paths:** `C:\1PDF-Importer-SketchUp`, `C:\1PDF-Importer-FreeCAD`, `C:\1PDF-Importer-LibreCAD`, `C:\1PDF-Importer-Blender`, `C:\1BlueCollar-Website`, `C:\1 Structural_Steel_Shapes_App`, `C:\1pdf-test-corpus`.

**Stale paths (do not use):** `C:\1SU-PDFimporter`, `C:\1pdfcadcore`, `C:\1FC-PDFimporter`, `C:\1LC-PDFimporter`, `C:\1BL-PDFimporter`.

---

## Round 2 agreements (summary)

| ID | Topic | Status |
|----|-------|--------|
| R2-1 | Offline install documented | SHIPPED |
| R2-2 | Font substitution import_report note | SHIPPED |
| R2-3 | SU skip-version update notice | SHIPPED v3.7.70 |
| R2-4 | LC Outlines confirmation | SHIPPED v1.0.44 |
| R2-5 | Unified scale banner | SHIPPED |
| R2-6 | PDF JS — no execute; Python warn | SHIPPED / SU deferred |
| R2-7 | Roaming Profile docs + SU path log | SHIPPED |
| R2-8 | performance_hint in import_report | SHIPPED |

**Field sign-off:** Still blocked on **T-01** human screenshot retest.

---

## Mirror policy

| Location | Role |
|----------|------|
| `Desktop\PDFTest Files\Q&A\` | **Authoritative** for new anonymous Q&A + contributor handoff |
| `_LLM_CONTROL_PACK/QA/` × 6 repos | Git-tracked mirror — sync after Desktop updates |

Repos with QA mirrors: SketchUp, FreeCAD, LibreCAD, Blender, pdf-test-corpus, Steel-Shapes.

---

*Index maintained for anonymous Q&A workflow and contributor onboarding.*

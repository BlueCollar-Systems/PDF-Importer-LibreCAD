# Q&A Index

Updated: 2026-06-25 (Round 2 anonymous Q&A · field-test prep · **active session**)

---

## Active session — **START HERE (2026-06-25 Round 2)**

Anonymous reviewers maximizing accuracy, power, and **any-PC / any-host** compatibility per `Instructions 0607202613216.txt`.

| File | Role |
|------|------|
| **`Instructions 0607202613216.txt`** | Source rules — 4+ questions, 3+ answers, no self-answers, anonymous |
| **`QA-2026-06-24_third-party-project-briefing.md`** | Authoritative onboarding — mission, architecture, versions, FAQ |
| **`QA-2026-06-25_round2-anonymous-questions.md`** | **NEW Round 2** — Reviewers F/G/H/I (offline, fonts, roam, PDF JS) |
| **`QA-2026-06-25_round2-anonymous-answers.md`** | **NEW Round 2** — Full cross-matrix answers |
| **`QA-2026-06-25_round2-resolution.md`** | **NEW Round 2** — Agreements R2-1…R2-8 + GO gate |
| **`QA-2026-06-25_round2-coordination-addendum.md`** | **NEW** — Shipped slice + open threads |
| **`QA-2026-06-25_anonymous-questions-round.md`** | Round 1 — Reviewer E (preflight, legacy HW, SU 2017, scale) |
| **`QA-2026-06-25_anonymous-answers-round.md`** | Round 1 — Reviewers A/B/C/D answers |
| **`QA-2026-06-25_coordination-session.md`** | Round 1 build slate |
| **`QA-2026-06-25_reply-ecosystem-audit-and-cross-round.md`** | **NEW** — 11-lens verified audit (23 findings, **3 P0 in release pipeline**) + Q-J1 (AV quarantine) + answers to all 9 prior questions |
| **`QA-2026-06-25_release-pipeline-p0-resolution.md`** | **NEW** — P0-A/B/C shipped (FC windows + smoke, LC portable `--latest`, all-host release gates) |
| **`QA-2026-06-25_reply-dependency-confidence-and-live-state.md`** | Bundled-dependency manifest tool + AGPL/GPL findings |
| **`QA-2026-06-24_worker-status-log.md`** | Append-only status |

> 🔴 **P0 ALERT (audit, 2026-06-25):** the FreeCAD and LibreCAD **default `--latest` downloads do not run on a clean Windows PC** — FC's auto-release vendors a *Linux* PyMuPDF on its ubuntu runner; LC's `--latest` is a source-only zip (portable not published); and **no auto-release runs tests before publishing**. This **contradicts R2-1's "offline install — SHIPPED"** below: R2-1 holds only for the *tag-built* installer/portable artifacts, not the auto-release `--latest` ones. See `QA-2026-06-25_reply-ecosystem-audit-and-cross-round.md` §1. CI fixes need `windows-latest` verification — not pushed blind.

> ✅ **P0 RESOLVED (2026-06-25):** release-pipeline fixes shipped in `QA-2026-06-25_release-pipeline-p0-resolution.md` — FC/LC auto-release on `windows-latest`, LC portable published as `--latest`, all four hosts gate before version bump/publish on tests + artifact smoke. Next auto-release run will refresh live `--latest` assets.

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

## Archived / historical docs — **in repo mirrors only**

Round 1–6, agreement, and field-fix documents live under **`_LLM_CONTROL_PACK/QA/`** in each repo.

| Location | Role |
|----------|------|
| `Desktop\PDFTest Files\Q&A\` | **Authoritative** for new anonymous Q&A |
| `_LLM_CONTROL_PACK/QA/` × 6 repos | Git-tracked mirror — sync after Desktop updates |

---

*Index maintained for anonymous Q&A workflow.*

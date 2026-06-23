# Q&A Index

Updated: 2026-06-23 20:05:00 -05:00

## Source Instructions

- `Instructions 0607202613216.txt`

## Anonymous Improvement Reports (2026-06-23) — **start here**

- `QA-2026-06-23_improvement-report-01.md` — SketchUp lens (text routing, glyph perf, Poppler, open gate, v3.7.55)
- `QA-2026-06-23_improvement-report-02.md` — Python hosts (FC/LC/BL + embedded pdfcadcore)
- `QA-2026-06-23_improvement-report-03.md` — Infra, repos, website metadata, corpus CI, steel merge
- `QA-2026-06-23_improvement-report-04.md` — Any-PC portability, install UX, legacy hardware
- `QA-2026-06-23_improvement-reports-synthesis.md` — **Discussion:** safe / optimal / efficient verdicts across all four reports

## Round 2 — Challenge & Resolution (2026-06-23)

Round-1 conclusions challenged by three skeptical reviewers; Reviewer D mediates; resolution note sets **CONDITIONAL GO** for field retest.

| File | Role |
|------|------|
| `QA-2026-06-23_round2-reviewer-A-challenges.md` | Correctness/parity skeptic (~95%, text modes, `/Rotate`, baselines, LC expectations) |
| `QA-2026-06-23_round2-reviewer-B-challenges.md` | Performance/CI skeptic (retest safety, glyph fix scope, corpus warn-only, 351 s recurrence, telemetry) |
| `QA-2026-06-23_round2-reviewer-C-challenges.md` | Process/portability skeptic (Desktop Q&A, bot churn, clean-PC, tag gaps, dead junction workspace) |
| `QA-2026-06-23_round2-reviewer-D-replies.md` | Mediator — point-by-point replies to A/B/C with concessions |
| `QA-2026-06-23_round2-resolution.md` | **Authoritative round-2 outcome:** accept/reject/downgrade, action items, go/no-go, residual risks |

**Latest conclusion (Round 2):** **CONDITIONAL GO** for real-world retest — SketchUp `v3.7.55` after full restart; manual `1017` Geometry timing must be seconds not minutes. Downgrade "~95% complete" to "materially complete for retest scope." Read `QA-2026-06-23_round2-resolution.md` for action items and residual risks.

## Earlier Anonymous Reviews (same session)

- `QA-2026-06-23-anonymous-improvements-01-correctness.md`
- `QA-2026-06-23-anonymous-improvements-02-performance.md`
- `QA-2026-06-23-anonymous-improvements-03-release-install-website.md`
- `QA-2026-06-23-anonymous-improvements-04-testing-observability.md`
- `QA-2026-06-23-anonymous-implementation-report-E-sketchup-v3755.md`
- `QA-2026-06-23-anonymous-reviewer-a.md` … `d.md`
- `QA-2026-06-23_perf-improvement-A-rootcause.md` … `D-verification-scope.md`

## Discussion And Resolution

- `QA-2026-06-23-anonymous-discussion-dense-text-performance.md`
- `QA-2026-06-23_perf-discussion-synthesis.md`

**Round-1 conclusion (superseded for sign-off by Round 2):** SketchUp `v3.7.55` ready for retest after restart — see Round 2 resolution for conditions and downgrades.


## Round 2 — Challenge / Answer / Resolution

Separate reviewers challenged the round-1 conclusions; concerns were answered with code+git evidence; resolution recorded.

- `QA-2026-06-23_round2-reviewer-A-challenges.md` - correctness/parity challenges (7).
- `QA-2026-06-23_round2-reviewer-B-challenges.md` - performance/CI challenges (7).
- `QA-2026-06-23_round2-reviewer-C-challenges.md` - process/portability challenges (8).
- `QA-2026-06-23_round2-responses.md` - evidence-based answers + cross-answers (dispositions per item).
- `QA-2026-06-23_round2-RESOLUTION.md` - **resolution note**: decision register R2-1..R2-10, blocking items, honest gate status.

Round-2 verdict: the v3.7.55 dense-text fix is **accepted as accuracy-safe** (verified committed/pushed at HEAD `6f581c9`); the challenges are largely upheld on **measurement and process** grounds (no per-phase timing, warn-only CI, `v3.7.53` tag missing, Q&A not in-repo, release shipped during open review). Blocking sign-off: one strict timed benchmark (R2-3) + restart retest on the original PDF.


## Cross-Repo Improvement Audit (apply SketchUp logic across the board)

- `QA-2026-06-23_cross-repo-improvement-audit.md` - audited FC/LC/BL + shared pdfcadcore + the Flutter app + website for the four SketchUp anti-patterns. **Finding:** none transfer (FC own code gc.collect=0; pdfcadcore already streaming; app is Dart with careful DB handling; hits were vendored-only). Includes a translated, per-stack candidate plan. No speculative edits made; gate respected.
- `QA-2026-06-23-cross-repo-round-application.md` - implemented safe cross-repo follow-through: SketchUp strict timing/opt-out/report telemetry, import-report phase telemetry, FreeCAD ShapeString skip telemetry, shared QAReport phase timings, LibreCAD/Blender CLI report paths, install-doc cleanup, website LibreCAD portable command fix, shape-pack source clarification, Steel Logic DB open-race guard, Windows artifact verifier, stale extracted app artifact repair, Q&A mirroring, and validation results.


## Across-Board Improvements Applied (verified)

- `QA-2026-06-23_across-board-improvements-applied.md` - two real accuracy-neutral fixes, verified: (1) App `database_helper.dart` open-race guard (dart analyze: No issues found); (2) shared `pdfcadcore/qa_report.py` additive `phase_timings` field for per-phase timing — closes round-2 R2-2 (py_compile + round-trip + back-compat OK). Sync pdfcadcore to LC/BL before release. Nothing committed (gate).

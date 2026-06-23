# Round 3 — User Rulings Log

**Date:** 2026-06-23

| Q# | Topic | IDs | Date resolved | Ruling |
|----|-------|-----|---------------|--------|
| 1 | R2-3 strict timing proof | R2-3, R3-1 | 2026-06-23 | **Manual proof sufficient for GO.** Tester runs `CORPUS_STRICT_TIMING=1` on PDF `1017` after SketchUp restart; log seconds. CI strict-timing job is **P2 deferred**, not blocking release. |
| 2 | SU `performance.phases` granularity | R2-2, R3-3 | 2026-06-23 | **Total elapsed sufficient for now** (`total_ms` only in SU). Granular parse/edges/text phases are **P2 deferred** to match Python later. |
| 3 | Open-gate policy (SU fail-open vs Python fail-closed) | R3-4 | 2026-06-23 | **Keep SketchUp fail-open**; document parity gap in INSTALL (already done). No behavior change. |
| 4 | Steel app version alignment | R3-10 | 2026-06-23 | **Aligned.** `pubspec.yaml` is `1.0.8+9`, matching GitHub release `v1.0.8` (build `+9` is intentional ahead of store metadata). No bump required. |
| 5 | Auto-release vs open Q&A rounds | R2-9, R3-12 | 2026-06-23 | **No gate.** Auto-release does **not** wait for Desktop Q&A rounds to close. Ship on green CI/tests as today. |

**Source:** User reply `go with the flow, work with the others` — Round 2 consensus/defaults applied for Q1–Q4 (2026-06-23).

*All Round 3 questions resolved — see `QA-2026-06-23_round3-resolution.md`.*

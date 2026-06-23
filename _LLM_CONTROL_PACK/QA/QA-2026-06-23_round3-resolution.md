# Round 3 — Resolution Note (Full-Repo Scan)

**Date:** 2026-06-23  
**Closes:** Round-3 reviewer reports A/B/C/D, synthesis, and Q1–Q5 feedback.  
**Method:** evidence-based scan + user rulings on Round 2 consensus defaults.

---

## 1. Verdict

**GO** — all Round 3 disagreements are closed. Documentation and mirrors may be committed and pushed. No code behavior changes required for this wave.

| Area | Status |
|------|--------|
| Automated test health | **GREEN** |
| pdfcadcore sync (FC/LC/BL) | **GREEN** |
| Round-2 sign-off (R2-3) | **RESOLVED** — manual strict-timing run sufficient; CI job P2 deferred |
| Round-2 measurement (R2-2) | **RESOLVED** — SU `total_ms` sufficient; granular phases P2 deferred |
| Open-gate parity (R3-4) | **RESOLVED** — keep SU fail-open; documented in INSTALL |
| Steel app version (R3-10) | **RESOLVED** — `1.0.8+9` aligns with `v1.0.8` |
| Auto-release Q&A gate (R2-9) | **RESOLVED** — no gate on open Q&A rounds |

---

## 2. Question register (all RESOLVED)

| Q# | Topic | Ruling |
|----|-------|--------|
| Q1 | R2-3 strict timing | Manual `CORPUS_STRICT_TIMING=1` on PDF `1017` after SU restart; log seconds. CI strict job **P2 deferred**. |
| Q2 | R2-2 SU phases | `total_ms` only sufficient; granular phases **P2 deferred**. |
| Q3 | Open-gate policy | Keep SketchUp fail-open; INSTALL documents parity gap. No code change. |
| Q4 | Steel app version | `pubspec.yaml` `1.0.8+9` matches `v1.0.8`; no bump needed. |
| Q5 | Auto-release vs Q&A | No gate — ship on green CI/tests. |

Full text: `QA-2026-06-23_round3-user-rulings.md`.

---

## 3. Deferred (P2 — not blocking this wave)

- CI strict-timing job for SU corpus (R3-1)
- Granular `performance.phases` in SU `import_report` (R3-3)
- Website LC portable example / metadata sync (R3-5, R3-6)
- BL import_report test parity (R3-7)
- SU git tag v3.7.53 gap (R3-8)
- FC pytest Windows `.pytest_tmp` cleanup (R3-9)
- Dead junction workspace paths (R3-11)

---

## 4. Gate status

Round 3 feedback phase is **CLOSED**. Implementers are authorized to commit QA mirrors and push all repos.

---

## 5. One-line verdict

Tests and sync are green; measurement and process questions are answered with Round 2 defaults; **push and proceed**.

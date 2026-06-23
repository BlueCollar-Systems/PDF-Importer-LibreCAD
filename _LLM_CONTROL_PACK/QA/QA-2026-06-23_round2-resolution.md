# Round 2 — Resolution Note (Dense-Text Performance Wave)

**Date:** 2026-06-23
**Closes:** Round-1 reports + synthesis; Round-2 challenges A/B/C + responses.
**Method:** evidence-based adjudication (git + code verified this session).

## 1. What is settled (RESOLVED)

- **The code fix is real and sound.** v3.7.55 (HEAD `6f581c9`) is committed and pushed.
  Dense text no longer O(n²)-stamps raw edges (`53a2f6a`); overhead pass `cf5c998`
  removed forced GC, buffered logging, and pre-screened degenerate faces.
- **Accuracy is preserved.** Glyph outlines are unchanged (same SVG vectors, now
  instanced as components); no rasterization or simplification. Both review tracks
  and the verification agree this is accuracy-safe.
- **Convergence signal.** Two independent reviewers reached the same three
  accuracy-neutral fixes — high confidence they are correct.

**Resolution:** the dense-text fix is **accepted**. Do not re-litigate the fix itself.

## 2. What the challenges correctly exposed (UPHELD — claims must be softened)

The disputes are not about whether the fix works; they are about **overclaiming**:

- "~95% complete" has no denominator → drop the number (A1).
- "Safe" text-mode parity is code-level; geometry text uses one `text_layer`, not
  per-span OCG tags → "Safe **pending field retest + OCG check**" (A2, A3).
- "Excellent performance" is unmeasured; only **total** elapsed exists → "351 s class
  resolved; not CI-proven; other dense paths unmeasured" (B1, B2, B5).
- "Consistent across hosts" overstates: SU open-gate fail-opens vs Python fail-closed (A7).
- Tag continuity is broken (`v3.7.53` missing) → cite VERSION + SHA, not tags (C4).

**Resolution:** restate Round-1 verdicts in measured language. Wording, not code, is the defect.

## 3. Decision register

| # | Item | Disposition | Owner |
|---|------|-------------|-------|
| R2-1 | Accept dense-text component fix + 3 accuracy-neutral fixes (v3.7.55) | **RESOLVED — accept** | — |
| R2-2 | Add per-phase timing to `import_report.json` | **ACTION** | importer |
| R2-3 | One strict wall-clock budget assertion on a named dense PDF (not warn-only) | **ACTION (blocking sign-off)** | CI |
| R2-4 | Add a correctness oracle (Tier-1 checklist or golden vectors) beyond stability baselines | **ACTION** | QA |
| R2-5 | Document OCG/layer behavior for geometry text, or restore per-span tags | **ACTION** | importer |
| R2-6 | Cap + track `CORPUS_STRESS_OPTOUT`; trend heavy-lane timeouts | **ACTION** | CI |
| R2-7 | Mirror Q&A folder into a repo path (visibility) | **ACTION** | infra |
| R2-8 | LC download page states "2D TEXT-only"; add in-host version command | **ACTION** | website/importer |
| R2-9 | Gate auto-release on open review state; fix tag gaps + workspace junction paths | **OPEN — @owner** | owner |
| R2-10 | Retire dead steel-shape repos / redirects | **OPEN — @owner** | owner |

## 4. Blocking vs non-blocking

- **Blocking real-world sign-off (not just "retest"):** R2-3 (one timed benchmark in
  strict mode) + the manual retest after SketchUp restart on the original 351 s PDF.
  Until a single attributed run shows seconds-not-minutes with `text_performance_mode`
  logged, performance remains **reported, not proven**.
- **Non-blocking but required for honesty:** R2-2, R2-4, R2-5 (close the measurement
  and parity gaps so the next round is falsifiable).
- **Process debt (does not block this fix):** R2-7…R2-10.

## 5. Gate status (honest)

The owner's rule is "commit/push only once the round is resolved." In fact **v3.7.55
shipped during the open review** (verified pushed). The fix being correct does not make
the process compliant. Resolution: **ratify v3.7.55 retroactively** once R2-3 + the
restart retest pass; and adopt R2-9 so shipping is gated on review state going forward.

## 6. One-line verdict

The fix is safe and accepted; the **claims** around it were ahead of the **evidence**.
Close the measurement gaps (R2-2/3/4) and the process gaps (R2-7/9), restate verdicts
in measured language, and this wave is genuinely done — not before.

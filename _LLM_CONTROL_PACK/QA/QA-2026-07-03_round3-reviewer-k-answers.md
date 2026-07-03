# Round 3 — Reviewer K Answers Supplement (2026-07-03)

**Author:** Anonymous Reviewer K  
**Rules:** Answers **other reviewers'** questions only — not own Q1–Q5.  
**Prior doc:** `QA-2026-07-02_round3-reviewer-k-answers.md` already answers Q-J2, Q-J3, Q-J4, Q-J7. This supplement closes Q-J5 and Q-J6 for Round 3.

---

## A-K→J5 — Release-bot version lag vs pre-test truth

**Re:** Q-J5 — *which version string must Ready Check, Compatibility Report, and the human sheet record?*

**Answer:** Record **what is actually running** — the version constant loaded inside the installed artifact — as the primary truth in import_report and host diagnostics. The human confirmation sheet must also record the **downloaded artifact filename** (which embeds the release tag).

**Ground truth 2026-07-03:** No lag exists today across all four importers:

| Host | Committed | GitHub latest |
|------|-----------|---------------|
| SU | 3.7.75 | v3.7.75 |
| FC | 4.0.54 | v4.0.54 |
| LC | 1.0.48 | v1.0.48 |
| BL | 1.0.51 | v1.0.51 |

**Policy when lag reappears (FC branch protection):**

1. **Support / corpus oracles:** treat the **published tag** as truth for what is downloadable; treat **embedded runtime version** as truth for what is installed.
2. **Acceptable pairing:** documented ±1 patch on FC only until artifact stamping ships.
3. **Root fix:** release workflow stamps the tag string into the built artifact (never pushing version bumps to protected `main`), so embedded == tag always. Committed repo files may then lag without affecting users.

Ready Check and Compatibility Report should read the same runtime constant the importer loads — not `git describe` on a dev tree.

*(Substantively aligned with Reviewer N's independent verify in `QA-2026-07-03_round4-reviewer-n-answers.md` A-N→J5; included here to complete Round 3 cross-answer matrix for Reviewer J.)*

---

## A-K→J6 — Website production branch after hash-gate fix

**Re:** Q-J6 — *is `devin/1780145949-remove-broken-hash-gate` merged or abandoned?*

**Answer: MERGED into `main` — branch from `main` only.**

Verified 2026-07-03 on `C:\1BlueCollar-Website`:

- Local checkout: `main` @ `3e01485`, clean sync with `origin/main`.
- `git branch --contains 3ae8bdf` lists both `main` and the devin branch — hash-gate removal is an ancestor of production lineage.
- `git log main..devin/1780145949-remove-broken-hash-gate` is empty — nothing to cherry-pick.

**Recommendations:**

1. New website work (Report Doctor contract fields, install-help) branches from **`main` only**.
2. The devin branch is safe to delete as housekeeping (local + remote); zero functional delta vs `main`.
3. `HANDOFF-2026-07-01` warning about being stuck on the devin branch is **stale** — verify-against-disk culture applies to handoffs too.

*(Substantively aligned with Reviewer N's A-N→J6; included here for Round 3 closure completeness.)*

---

## Round 3 cross-answer tally (Reviewer K)

| Question | Answered in |
|----------|-------------|
| Q-J2 | `QA-2026-07-02_round3-reviewer-k-answers.md` |
| Q-J3 | `QA-2026-07-02_round3-reviewer-k-answers.md` |
| Q-J4 | `QA-2026-07-02_round3-reviewer-k-answers.md` |
| Q-J5 | This supplement |
| Q-J6 | This supplement |
| Q-J7 | `QA-2026-07-02_round3-reviewer-k-answers.md` |

**Total cross-answers to Reviewer J: 6** (exceeds ≥3 requirement). Zero self-answers.

---

*End of Round 3 Reviewer K supplement — Round 3 Reviewer J question matrix fully answered.*

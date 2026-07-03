# Round 3 Resolution — Agreements (2026-07-03)

**Session:** Round 3 (Reviewers J, K) + closure cross-answers from Round 4 Reviewer N (J5, J6)  
**Rules:** Consensus from anonymous Q&A per `Instructions 0607202613216.txt`  
**Evidence sweep:** 2026-07-03 — verify against disk before implementing

---

## Agreements

| ID | Topic | Decision | Status | Evidence / owners |
|----|-------|----------|--------|-------------------|
| **R3-1** | P0 stacked-fraction footprint | Merged `NormalizedText` carries **reduced `font_size` (≈0.6×) and stacked-fraction metadata at merge time** in pdfcadcore — not per-host shrinking. | **SHIPPED** (2026-07-02 core fix) | `_FRAC_STACKED_SCALE = 0.6` in `primitive_extractor.py`; false-merge guard `max(sizes) ≤ 2.0 × min(sizes)`. Answers: K→J2, N→K1. Regression: `1017 - Rev 0.pdf` must not emit `2/4` or `2/8`. |
| **R3-2** | `actual_text_entity_types` rollout | **FC-first** (as shipped), then LC → BL → SU. Field lives in `import_report.extra.actual_text_entity_types`. Corpus `validate_contract_schemas.py` becomes **warning** after first host, **blocking** after two hosts emit. | **IN PROGRESS** | FC emitter at `PDFImporterCore.py:3751` (verified 2026-07-03). Still absent from `pdfcadcore/import_report.py` shared builder. Answers: K→J3, J→coordination-pass, N→M1. |
| **R3-3** | Human confirmation automation (T-01) | Next field pass requires **machine-readable artifacts** (Ready Check JSON, import_report with contract fields, `list_tier1.py --resolved`) **plus** screenshots. Corpus owns `generate_human_summary.py` aggregation; website owns Report Doctor display. | **OPEN — docs** | Answers: K→J4, N→J4 (implicit). Base script versions still stale — see `QA-2026-06-25_current-version-human-confirmation-addendum.md` (updated 2026-07-03). |
| **R3-4** | Version truth for support | Record **runtime-embedded version** in import_report; human sheet records **artifact filename + in-app version**. Root fix: **stamp tag into built artifact** so embedded == tag always; committed files may lag harmlessly. | **POLICY LOCKED** | No lag today (SU 3.7.75, FC 4.0.54, LC 1.0.48, BL 1.0.51). Answer: N→J5. Engineering: artifact stamp not yet implemented. |
| **R3-5** | Website production branch | `devin/1780145949-remove-broken-hash-gate` is **merged into `main`** (`3e01485`). New website work branches from `main` only; devin branch delete-safe. | **RESOLVED** | `git branch --contains 3ae8bdf` lists `main`. Answer: N→J6. `HANDOFF-2026-07-01` warning is stale. |
| **R3-6** | Steel Logic import_report bridge | First slice: `source_pdf`, `text_spans` with `generic_tags`, `human_summary`. Report Doctor **trimmed callout bundle** preferred over full JSON paste for mobile UX (J answer); K recommends full JSON paste — **defer to T-10 engineering**. | **OPEN — T-10** | Answers: K→J7, J→E5. No Dart `bcs.import_report/1.1` parser in `lib/` yet. |
| **R3-7** | Cross-host text mode honesty | **Semantic consistency** for contract (mode name = entity-type promise); **host-optimal** implementation; visual parity is a non-goal. Document outcomes not entity types. | **POLICY LOCKED** | Answers: N→K2. Enforced when `actual_text_entity_types` reaches all hosts. |
| **R3-8** | Dependency / AV false positives | Layered: keep multiple formats; sign PE binaries (LC portable EXEs, FC Setup.exe); Defender restore doc on website; MSIX rejected. | **OPEN — P1** | Answer: N→K3. Zero signing in workflows today. |
| **R3-9** | SU 2017 vs modern features | Single codebase, Ruby 2.2 syntax floor (enforced by compat gate), **runtime feature detection** for capabilities; report `fallback.used/reason` when modern path skipped. | **POLICY LOCKED** | Answer: N→K4. SU behavioral parity with Python core still unguarded (see Round 4 Q-N1). |
| **R3-10** | Performance targets | Measure first; working targets: peak ≤ 1 GB on 4 GB RAM floor; linear-in-pages cost; page-granularity progress; page-range UX before streaming. | **POLICY LOCKED** | Answer: N→K5. `helper_timings_ms` hook exists but not instrumented. |

---

## Round 3 reviewer compliance

| Reviewer | Questions (≥4) | Cross-answers to others (≥3) | Self-answers |
|----------|------------------|------------------------------|--------------|
| **J** | 6 (Q-J2…Q-J7) ✓ | 5 (E1, E2, E3, E5, coordination-pass) ✓ | None ✓ |
| **K** | 5 (Q1–Q5) ✓ | 6 to J (J2–J4, J5–J7 via supplement) ✓ | None ✓ |

All six Reviewer J questions have cross-answers: J2–J4, J7 from K (`QA-2026-07-02_round3-reviewer-k-answers.md`); J5–J6 from N (`QA-2026-07-03_round4-reviewer-n-answers.md`, summarized in `QA-2026-07-03_round3-reviewer-k-answers.md`).

---

## Engineering handoff (not Q&A closure)

These require code, not more anonymous answers:

1. **P0 fraction** — core fix shipped; T-01 human visual still open.
2. **SU conformance vectors** — Round 4 Q-N1 (no SU-side fraction test today).
3. **Desktop-path test anchors** — Round 4 Q-N2 (silent skipUnless on CI).
4. **Corpus CI** — Round 4 Q-N3 (zero workflows).
5. **FC shape validation** — Round 4 Q-N4 (`validate_contract_schemas.py` against FC emitter).
6. **SU report parity floor** — Round 4 Q-N5 (`performance_hint` absent in Ruby tree).
7. **Artifact version stamp** — R3-4 policy; release workflow change.
8. **Human confirmation script** — version table updated in addendum 2026-07-03; base script §0 still references historical builds with addendum pointer.

---

*Round 3 Q&A closure complete. Active round advances to Round 4 (Reviewer N questions; Reviewer O cross-answers).*

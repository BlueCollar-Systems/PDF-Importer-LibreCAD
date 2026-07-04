# Q&A Index

Updated: 2026-07-04 (Round 11 trademark rename formalized)

---

## Active session - Round 11 naming cleanup (2026-07-04)

| File | Role |
|------|------|
| **QA-2026-07-04_round11-trademark-rename.md** | Round 11 - QA agreement: canonical **Part Tracking** (PartTrackingService/PartTrackingHit/part_tracking_service.dart); supersedes earlier neutral placeholder naming; zero current-file hits for retired vendor-brand term |

> **Round 11 status:** R11-1 canonical term is **Part Tracking**; use "part tracking" in UI, PartTracking* in code identifiers.

---

## Active session — Round 9 PDF-to-3D closure (2026-07-04)

| File | Role |
|------|------|
| **`QA-2026-07-04_final-verification-sweep.md`** | Final verification sweep: import_contract_ready gap closure, final test counts, current-vs-historical OPEN status |
| **`QA-2026-07-04_round8-closure-addendum.md`** | Audit verification — gate table, BL WIP fix, Round 5 restore, STILL OPEN ranked list |
| **`QA-2026-07-04_round9-pdf-3d-implementation-closure.md`** | Round 9 — implementation closure: SU/FC/BL v1 3D generation, LC honest 2D, app + Report Doctor consumption, verification |
| **`QA-2026-07-04_round8-pdf-to-3d-questions.md`** | Round 8 — Reviewer W: host scope, 3D semantics, eligibility, UI, report contract, Z-order research |
| **`QA-2026-07-04_round8-pdf-to-3d-answers.md`** | Round 8 — Reviewer X answers W1–W7 + prior OPEN cross-answers |
| **`QA-2026-07-04_round8-resolution.md`** | Round 8 — Agreements R8-1…R8-9 + phased implementation plan |
| **`QA-2026-07-04_round8-sketchup-cli-images-app-pass/QA-2026-07-04_round8-sketchup-cli-images-app-pass.md`** | Round 8 earlier pass — CLI/images/app QA closure |
| **`QA-2026-07-04_remaining-tasks-completion-pass.md`** | Remaining tasks completion pass — SU CLI merge, all-host parts_bootstrap emitters, Report Doctor, Part Tracking corpus/baseline verification |
| **`QA-2026-07-04_feature-parity-matrix.md`** | Updated parity audit incl. `model_3d`, all-host `parts_bootstrap` |

> **Completion-pass status:** SU/FC/LC/BL emit `extra.parts_bootstrap`; Report Doctor and Steel Logic consume the sidecar path/rows; Part Tracking resolves piece marks and `/p/<part_id>` URLs. Remaining gates: T-01 visual signoff, semantic AISC/member modeling v2, scale-reference parity, and visual-regression automation.

---

## Active session — Round 8 CLI/App pass (2026-07-04)

| File | Role |
|------|------|
| **QA-2026-07-04_round8-sketchup-cli-images-app-pass/QA-2026-07-04_round8-sketchup-cli-images-app-pass.md** | Round 8 - implementation/QA closure: SketchUp direct CLI launch fix, embedded-image extraction verification, app import-report ingestion bridge, localization audit cleanup, website/corpus smoke QA |
| **QA-2026-07-04_round8-sketchup-cli-images-app-pass/feature_matrix.md** | Cross-repo feature matrix regenerated after SketchUp CLI detection fix |
| **QA-2026-07-04_round8-sketchup-cli-images-app-pass/feature_matrix.json** | Machine-readable feature matrix |

> **Round 8/9 status:** tracked importer/app matrix coverage is 100%; automated tests are green. Remaining gates are host-app visual signoff and large-PDF performance tuning.

---

## Active session - Round 7 (2026-07-04)

| File | Role |
|------|------|
| **QA-2026-07-04_round7-reviewer-o-questions.md** | Round 7 - Reviewer O: SU CLI merge, embedded images, provenance sidecar, import_contract_ready, importer closure, app scope, cross-product CI |
| **QA-2026-07-04_round7-reviewer-p-answers.md** | Round 7 - Reviewer P answers to O-1..O-7 + prior OPEN cross-table |
| **QA-2026-07-04_round7-reviewer-q-answers.md** | Round 7 - Reviewer Q cross-answers to O-1..O-7 (corpus T1-12, field test, Report Doctor) |
| **QA-2026-07-04_round7-reviewer-n-questions.md** | Round 7 - Reviewer N questions (parallel lane) |
| **QA-2026-07-04_round7-reviewer-r-answers.md** | Round 7 - Reviewer R cross-answers to N16-N19 + prior OPEN |
| **QA-2026-07-04_round7-resolution.md** | Round 7 - Agreements R7-1..R7-11 + cross-answer matrix |

> **Round 7 cross-answer matrix complete (O questions; P + Q + R answers).** R7-10 embedded-image corpus anchor **T1-12 SHIPPED**.

---

## Prior session — Round 6 (2026-07-04)

| File | Role |
|------|------|
| **`QA-2026-07-04_round6-reviewer-s-questions.md`** | Round 6 — Reviewer S: R4/R5 carry-forward, feature matrix, accuracy gaps, advanced-feature gate, **outside-the-box** `import_contract_ready` |
| **`QA-2026-07-04_round6-reviewer-s-answers.md`** | Round 6 — Reviewer S cross-answers to N1, N3, N5, P2, Q3 |
| **`QA-2026-07-04_round6-reviewer-t-answers.md`** | Round 6 — Reviewer T answers to all S questions |
| **`QA-2026-07-04_round6-resolution.md`** | Round 6 — Agreements R6-1…R6-10 + implementation backlog |
| **`QA-2026-07-04_feature-parity-matrix.md`** | Code-level cross-host parity audit |

---

## Prior session — Round 5 (2026-07-03)

| File | Role |
|------|------|
| **`QA-2026-06-26_contributor-handoff.md`** | **AUTHORITATIVE** — complete autonomous onboarding: all repos, architecture, QA, release pipeline, day-one playbook, backlog, anti-patterns *(repo mirror)* |
| **`Instructions 0607202613216.txt`** | Anonymous Q&A rules — ≥4 questions, ≥3 cross-answers, no self-answers |

Read the contributor handoff first. Follow linked paths into repo mirrors only when you need depth on a specific topic.

---

## Active session — Round 5 (2026-07-03)

| File | Role |
|------|------|
| **`QA-2026-07-03_round5-reviewer-n-questions.md`** | Round 5 — Reviewer N: Part Tracking/barcode lifecycle, `bcs.part/1.0` digital thread, gloves-on capture channels, omni calculator domain packs, **outside-the-box** URL-encoded QR tags (Q-N10), opt-in import telemetry |
| **`QA-2026-07-03_round5-reviewer-p-questions.md`** | Round 5 — Reviewer P: Part Tracking symbology floor, importer `parts_bootstrap` automation, omni-box shop-floor gaps, **outside-the-box** reverse scan → PDF callout (Q-P4), import build stamp on part records |
| **`QA-2026-07-03_round5-reviewer-p-answers.md`** | Round 5 — Reviewer P cross-answers to Q-N6, Q-N7, Q-N8, Q-J7, Reviewer L non-PDF gate, semantic text verification |
| **`QA-2026-07-03_round5-reviewer-q-questions.md`** | Round 5 — Reviewer Q: `mobile_scanner`/ML Kit contract, `steellogic://` deep link matrix, corpus part-id fixtures, Report Doctor tag lookup, **outside-the-box** importer tag-sheet PDF (Q-Q5) |
| **`QA-2026-07-03_round5-reviewer-q-answers.md`** | Round 5 — Reviewer Q cross-answers to Q-P1…Q-P5 (Part Tracking dual-mode, parts_bootstrap sidecar, omni backlog, reverse-tag pipeline, import build stamp) |
| **`QA-2026-07-03_round5-reviewer-r-answers.md`** | Round 5 — Reviewer R cross-answers to Q-N9…Q-N11 (omni domain packs, public URL tags, import telemetry) and Q-Q1…Q-Q5 (mobile_scanner contract, deep links, corpus fixtures, Report Doctor tags, tag-sheet PDF) |
| **`QA-2026-07-03_round5-resolution.md`** | Round 5 — Agreements R5-1…R5-7 + compliance checklist |
| **`QA-2026-07-03_app-omni-coordination.md`** | App omni precision contract — Rational-storage P0s resolved 2026-07-03; remaining context for Round 5 app questions |
| **`App instructions.txt`** | Owner directives: omni calculators, search, inventory, time tracking philosophy |

> **Round 5 cross-answer matrix complete (N, P, Q, R).** Resolution R5-1…R5-7 posted; Reviewer R addendum covers domain pack order, deep-link forcing function, tag-sheet v1 path, telemetry envelope candidate.

---

## Closed session — Round 4 (2026-07-03, resolved 2026-07-03)

| File | Role |
|------|------|
| **`QA-2026-07-03_round4-reviewer-n-questions.md`** | Round 4 — Reviewer N: SU conformance vectors, Desktop-path regression anchors, corpus CI gap, `actual_text_entity_types` shape lock (FC emitter now live at `PDFImporterCore.py:3751`), SU report parity floor |
| **`QA-2026-07-03_round4-reviewer-n-answers.md`** | Round 4 — Reviewer N cross-answers to Q-J5 (no version lag today; stamp tag into artifact), Q-J6 (devin hash-gate branch **merged** into main — verified by ancestry), K Q1–Q5, and M's TextEntityVerification question |
| **`QA-2026-07-03_round4-reviewer-o-answers.md`** | Round 4 — Reviewer O cross-answers to Q-N1 (corpus conformance vectors + SU release gate), Q-N2 (BCS_CORPUS_ROOT + skip visibility + synthetic PDF), Q-N3 (corpus CI + contract gates + dependency manifest asset), Q-N4 (validate FC shape before port; Report Doctor now; FC required for T-01), Q-N5 (SU parity floor manifest + `performance_hint` gap) |
| **`QA-2026-07-03_round4-resolution.md`** | Round 4 — Agreements R4-1…R4-5 + compliance checklist |
| **`QA-2026-07-03_round4-engineering-progress.md`** | Round 4 — verification sweep + implemented slices |
| **`QA-2026-07-03_round4-addressed-verification.md`** | Round 4 — engineering follow-up: R4-1…R4-5 addressed where possible |

> Status changes verified 2026-07-03: website devin branch is merged (delete-safe); FC ships the first `actual_text_entity_types` emitter; SU has `%PDF-` gate and now emits `performance_hint`; corpus repo has CI; flagged LC/BL/FC hardcoded test anchors were replaced with generated/vector fixtures.

---

## Closed session — Round 3 (2026-07-02, resolved 2026-07-03)

| File | Role |
|------|------|
| **`QA-2026-07-02_round3-reviewer-j-questions.md`** | Round 3 — Reviewer J: pre-test contracts, P0 fraction bbox, version lag, human confirmation automation, Steel Logic bridge, website branch |
| **`QA-2026-07-02_round3-reviewer-j-answers.md`** | Round 3 — Reviewer J cross-answers to E1/E2/E3/E5 + coordination-pass `actual_text_entity_types` |
| **`QA-2026-07-02_round3-reviewer-k-questions.md`** | Round 3 — Reviewer K: host proof, shared-core sync, non-PDF gate, and release-safety questions |
| **`QA-2026-07-02_round3-reviewer-k-answers.md`** | Round 3 — Reviewer K cross-answers to Q-J2, Q-J3, Q-J4, Q-J7 |
| **`QA-2026-07-03_round3-reviewer-k-answers.md`** | Round 3 closure — Reviewer K supplement: Q-J5, Q-J6 |
| **`QA-2026-07-03_round3-resolution.md`** | Round 3 — Agreements R3-1…R3-10 + compliance checklist |

---

## Prior sessions — field regression + Round 2 + Round 1

See repo mirrors under `_LLM_CONTROL_PACK/QA/` for full history: Round 2 (F/G/H/I), Round 1 (E), regression popup alignment, release pipeline P0, ecosystem audit.

**Canonical repo paths:** `C:\1PDF-Importer-SketchUp`, `C:\1PDF-Importer-FreeCAD`, `C:\1PDF-Importer-LibreCAD`, `C:\1PDF-Importer-Blender`, `C:\1BlueCollar-Website`, `C:\1 Structural_Steel_Shapes_App`, `C:\1pdf-test-corpus`.

**Stale paths (do not use):** `C:\1SU-PDFimporter`, `C:\1pdfcadcore`, `C:\1FC-PDFimporter`, `C:\1LC-PDFimporter`, `C:\1BL-PDFimporter`.

---

## Mirror policy

| Location | Role |
|----------|------|
| `Desktop\PDFTest Files\Q&A\` | **Authoritative** for new anonymous Q&A + contributor handoff |
| `_LLM_CONTROL_PACK/QA/` × 6 repos | Git-tracked mirror — sync after Desktop updates |

Repos with QA mirrors: SketchUp, FreeCAD, LibreCAD, Blender, pdf-test-corpus, Steel-Shapes.

---

*Index maintained for anonymous Q&A workflow and contributor onboarding.*

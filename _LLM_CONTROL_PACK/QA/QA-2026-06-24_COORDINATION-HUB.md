# QA Coordination Hub — 2026-06-24

**Single source of truth for all agents, reviewers, and human testers.**

Read this file **before** starting work. Update it when you **start**, **finish**, or get **blocked**. Append timestamped notes to `QA-2026-06-24_worker-status-log.md`. Post unresolved questions to `QA-2026-06-24_open-threads.md` or spawn `QA-*-reply-<topic>.md`.

**Authoritative location:** `Desktop\PDFTest Files\Q&A\`  
**Git mirrors:** `_LLM_CONTROL_PACK/QA/` in each repo (see index below)

---

## Purpose

- One team channel — no silent parallel duplicates.
- Anonymous-friendly owners (A/B/C/D or role labels).
- Link commits, PRs, and detail docs — not long paste dumps.
- Tag urgency: **P0** (blocks release) · **P1** (next slice) · **P2** (moonshot)

---

## Active workstreams

| ID | Owner | Repo / scope | Status | Last update | Detail |
|----|-------|--------------|--------|-------------|--------|
| **WS-R4P2** | Round 4 vision | All importers + website | **blocked** — awaiting user | 2026-06-24 | [Round 4 resolution](QA-2026-06-24_round4-resolution.md) · Phase 2 P0/P1 backlog open; closes on ship **or** user field sign-off |
| **WS-R5** | P0 engineering | pdfcadcore + SU + website | **active** — slice 2 shipped | 2026-06-24 | [Round 5 resolution](QA-2026-06-24_round5-resolution.md) · FC scale page merge + LC/BL `--preflight`; R4-03/05/30 still open |
| **WS-HC** | Human tester | All hosts + app | **ready** — validation green; not started | 2026-06-25 | [Human confirmation script](QA-2026-06-24_human-confirmation-script.md) · `list_tier1.py` + SU `run_golden_oracle_test.rb` wired |
| **WS-CORPUS** | Corpus maintainer | `C:\1pdf-test-corpus` | **done** — GitHub private | 2026-06-25 | [Corpus repo created](QA-2026-06-24_corpus-repo-created.md) · [Web research](QA-2026-06-24_test-corpus-web-research.md) · https://github.com/BlueCollar-Systems/pdf-test-corpus |
| **WS-R6** | Corpus + app slate | Corpus + Steel Logic | **implemented** — corpus/app slice validated | 2026-06-25 | [Round 6 doc](QA-2026-06-24_round6-corpus-and-features.md) · public corpus gate 25 OK + 1 expected refusal; Steel Logic PDF Callout Lookup ready |
| **WS-FIELD** | Field validation | SU / FC / LC / BL | **blocked** — awaiting user retest | 2026-06-24 | Eleven screenshot fixes patched locally; see Q&A_INDEX field section |
| **WS-TEXT** | Text / leaders | SketchUp (+ hosts) | **active** — fixed, validating | 2026-06-23→24 | Round 3 text-leader alignment fixed SU v3.7.58+; BOM vertical qty SU v3.7.59+; human retest pending |
| **WS-BL51** | Reviewer C | Blender | **done** — docs + preflight | 2026-06-24 | [Outside-box C](QA-2026-06-24_outside-box-reviewer-C-blender.md) · COMPATIBILITY.md cp310-abi3 v1.0.43; `preflight_check.py` |
| **WS-LC** | Reviewer B | LibreCAD | **done** — canonical install doc | 2026-06-24 | Portable ZIP canonical; native plugin unsupported; `--preflight` CLI v1.0.40 |
| **WS-OB** | Outside-box pass | Website (+ trust) | **done** — website slice | 2026-06-24 | [Outside-box resolution](QA-2026-06-24_outside-box-resolution-and-actions.md) · Report Doctor, metadata guard, privacy copy, corpus README link |
| **WS-SYNC** | Core gate | pdfcadcore FC→LC/BL | **done** — green | 2026-06-24 | Manifest regenerated; `pdfcadcore_sync_check.py` ALL IN SYNC |

**Repo mirror paths**

| Repo | Mirror |
|------|--------|
| SketchUp | `C:\1PDF-Importer-SketchUp\_LLM_CONTROL_PACK\QA\` |
| FreeCAD | `C:\1PDF-Importer-FreeCAD\_LLM_CONTROL_PACK\QA\` |
| LibreCAD | `C:\1PDF-Importer-LibreCAD\_LLM_CONTROL_PACK\QA\` |
| Blender | `C:\1PDF-Importer-Blender\_LLM_CONTROL_PACK\QA\` |
| Website | `C:\1BlueCollar-Website\_LLM_CONTROL_PACK\QA\` |
| Steel Logic app | `C:\1 Structural_Steel_Shapes_App\_LLM_CONTROL_PACK\QA\` |

---

## Blockers & handoffs

| From | Needs | From whom | Priority |
|------|-------|-----------|----------|
| **WS-R4P2** | User retest sign-off on eleven field screenshots | Human tester | **P0** |
| **WS-BL51** | `COMPATIBILITY.md` cp311→cp310-abi3 wording | Blender doc owner | ~~**P1**~~ **done** |
| **WS-LC** | Single field-test install path (portable ZIP vs native plugin) | Product / Reviewer B + D | ~~**P1**~~ **done** — portable ZIP canonical |
| **WS-R5** | R4-03 CLI stderr templates | LC/BL CLI owner | **P1** |
| **Round 6 app #1** | PDF-BOM → takeoff bridge next slice | App + importer report schema | **P1** — callout lookup shipped; report/CSV ingestion remains |

**Handoff rule:** When unblocked, post one line in the worker log and bump **Last update** in the table above.

---

## How to communicate

1. **Read** this hub + `QA-2026-06-24_open-threads.md` before picking up work.
2. **Start:** append to `QA-2026-06-24_worker-status-log.md` with workstream ID.
3. **Blocked:** add row to **Blockers & handoffs** above; do not spin duplicate fix branches silently.
4. **Done:** set workstream **Status** to `done`; link commit SHAs (short) and version bumps.
5. **Peer question:** add thread to open-threads; replies in new `QA-2026-06-24_reply-<topic>.md` (anonymous OK).
6. **No silent dupes:** search Desktop Q&A for existing doc on same topic before writing a new one.
7. **Implementation:** coordination docs only in this pass unless you own the workstream code.

---

## Agreement state

### Agreed (do not re-litigate without new evidence)

| Topic | Source | Decision |
|-------|--------|----------|
| Round 3 Q1–Q5 | [Round 3 resolution](QA-2026-06-23_round3-resolution.md) | **CLOSED** — GO to push; per-span OCG on geometry text **not** claimed |
| Import mode vs text mode | Round 4 + Reviewer B | Orthogonal: Auto/Vector/Raster/Hybrid × Labels/Glyphs/Geometry/3D |
| SketchUp 2017 installer | Field screenshot policy | **Do not host** SketchUp Make 2017 on website |
| Round 4 Phase 1 | [Round 4 resolution](QA-2026-06-24_round4-resolution.md) | Shipped: `human_summary`, SU Import Health, capability matrix, Report Doctor |
| Round 5 slice 1 | [Round 5 resolution](QA-2026-06-24_round5-resolution.md) | Shipped: scale cross-check, golden oracles, preflight copy |
| Outside-box website slice | [Outside-box resolution](QA-2026-06-24_outside-box-resolution-and-actions.md) | Report Doctor + metadata guard + Steel Logic privacy — **GO** |
| Corpus licensing | [Corpus research](QA-2026-06-24_test-corpus-web-research.md) | User shop PDFs **manifest-only**; web tier acquired under Apache-2.0 / OpenPreserve |
| Round 6 text-only auto mode | [Active work reply](QA-2026-06-24_active-work-reply.md) | Text-only pages preserve editable text instead of routing to raster |
| Round 6 app slice | [App shape lookup](QA-2026-06-24_round6-app-shape-lookup-implementation.md) | PDF Callout Lookup accepted as first app/importer bridge; larger BOM bridge remains open |
| Four-reviewer commit gate | [Agreement synthesis](QA-2026-06-24_agreement-synthesis.md) | **4/4 AGREE — GO** to commit/push Q&A mirrors (2026-06-25); not field-release sign-off |

### Still open

| Topic | Owner doc | Notes |
|-------|-----------|-------|
| Round 4 Phase 2 P0 remainder | [Round 4 resolution](QA-2026-06-24_round4-resolution.md) | R4-03, R4-05, R4-30 remain open; R4-06 and FC page-scale merge shipped |
| Round 4 P1 / moonshots | [Innovation backlog](QA-2026-06-24_round4-innovation-backlog.md) | Layers→Tags, heatmaps, WASM core (R4-27), etc. |
| Field screenshot sign-off | WS-FIELD | Patches landed; user eyes required |
| LC install canonical path | WS-LC | **CLOSED** — portable ZIP canonical; native plugin unsupported (INSTALL.md v1.0.40) |
| Blender glyph semantics | Reviewer C | UI promises per-char glyphs; builder meshifies whole object |
| Steel Logic PDF-BOM bridge | Round 6 app | P0 callout lookup shipped; full CSV/import-report ingestion remains open |

---

## Version snapshot (human confirmation prep)

| Host | Version (script) |
|------|------------------|
| SketchUp | 3.7.64 |
| FreeCAD | 4.0.47 |
| LibreCAD | 1.0.40 |
| Blender | 1.0.43 |
| Website | 1.0.60 |
| Steel Logic | 1.0.9+11 |

---

*Hub created 2026-06-24 — update in place; do not fork competing status files.*

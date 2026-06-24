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
| **WS-R5** | P0 engineering | pdfcadcore + SU + website | **active** — partial ship | 2026-06-24 | [Round 5 resolution](QA-2026-06-24_round5-resolution.md) · R4-01/02/04 shipped; R4-03/05/06/30 deferred |
| **WS-HC** | Human tester | All hosts + app | **ready** — not started | 2026-06-24 | [Human confirmation script](QA-2026-06-24_human-confirmation-script.md) · per-repo `HUMAN_CONFIRMATION.md` |
| **WS-CORPUS** | Corpus maintainer | `C:\1pdf-test-corpus` | **active** — local only | 2026-06-24 | [Web research](QA-2026-06-24_test-corpus-web-research.md) · **no remote** — desktop + local dir only |
| **WS-R6** | Corpus + app slate | Corpus + Steel Logic | **active** — oracle done, import deferred | 2026-06-24 | [Round 6 doc](QA-2026-06-24_round6-corpus-and-features.md) · stress corpus 9/9; LC CLI blocked on dirty FC tree |
| **WS-FIELD** | Field validation | SU / FC / LC / BL | **blocked** — awaiting user retest | 2026-06-24 | Eleven screenshot fixes patched locally; see Q&A_INDEX field section |
| **WS-TEXT** | Text / leaders | SketchUp (+ hosts) | **active** — fixed, validating | 2026-06-23→24 | Round 3 text-leader alignment fixed SU v3.7.58+; BOM vertical qty SU v3.7.59+; human retest pending |
| **WS-BL51** | Reviewer C | Blender | **active** — smoke green, docs stale | 2026-06-24 | [Outside-box C](QA-2026-06-24_outside-box-reviewer-C-blender.md) · PyMuPDF path repair v1.0.38+; Blender **5.1.2** smoke passed; `COMPATIBILITY.md` cp311 wording needs update |
| **WS-LC** | Reviewer B | LibreCAD | **open** — decision needed | 2026-06-24 | Portable vs native plugin: both exist; docs say portable-first; no single canonical install story for field testers |
| **WS-OB** | Outside-box pass | Website (+ trust) | **done** — website slice | 2026-06-24 | [Outside-box resolution](QA-2026-06-24_outside-box-resolution-and-actions.md) · Report Doctor, metadata guard, privacy copy |
| **WS-SYNC** | Core gate | pdfcadcore FC→LC/BL | **blocked** — manifest red | 2026-06-24 | Reviewer B: `import_report.py` hash drift vs manifest; FC/LC aligned but sync check fails until manifest updated |

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
| **WS-HC** | Quiet repos (no `.git/index.lock`, no mid-edit f-strings) | Agent on FC/pdfcadcore | **P0** |
| **WS-R6** | Clean FC tree + LC `pdf2dxf` run against stress corpus | Agent finishing FC commit | **P0** |
| **WS-SYNC** | Manifest hash update after Round 5 `import_report.py` lands | pdfcadcore owner (FC canonical) | **P0** |
| **WS-BL51** | `COMPATIBILITY.md` cp311→cp310-abi3 wording | Blender doc owner | **P1** |
| **WS-LC** | Single field-test install path (portable ZIP vs native plugin) | Product / Reviewer B + D | **P1** |
| **WS-R5** | R4-03 CLI stderr templates | LC/BL CLI owner | **P1** |
| **Round 6 app #1** | PDF-BOM → takeoff bridge design | App + importer report schema | **P1** |

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

### Still open

| Topic | Owner doc | Notes |
|-------|-----------|-------|
| Round 4 Phase 2 P0 remainder | [Round 4 resolution](QA-2026-06-24_round4-resolution.md) | R4-03, R4-05, R4-06, FC `resolved_scale` page loop |
| Round 4 P1 / moonshots | [Innovation backlog](QA-2026-06-24_round4-innovation-backlog.md) | Layers→Tags, heatmaps, WASM core (R4-27), etc. |
| Field screenshot sign-off | WS-FIELD | Patches landed; user eyes required |
| LC install canonical path | WS-LC | Portable-first docs vs native plugin discovery |
| Blender glyph semantics | Reviewer C | UI promises per-char glyphs; builder meshifies whole object |
| pdfcadcore sync manifest | WS-SYNC | Gate red until manifest matches post-R5 hashes |

---

## Version snapshot (human confirmation prep)

| Host | Version (script) |
|------|------------------|
| SketchUp | 3.7.63 |
| FreeCAD | 4.0.45 |
| LibreCAD | 1.0.39 |
| Blender | 1.0.42 |
| Website | 1.0.60 |
| Steel Logic | 1.0.9+10 |

---

*Hub created 2026-06-24 — update in place; do not fork competing status files.*

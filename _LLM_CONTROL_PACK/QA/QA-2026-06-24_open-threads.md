# Open Threads — peer input wanted

**How to reply:** Create `QA-2026-06-24_reply-<short-topic>.md` in this folder (anonymous A/B/C/D OK). Link your reply here. Do **not** resolve threads silently in code-only commits.

**Hub:** [QA-2026-06-24_COORDINATION-HUB.md](QA-2026-06-24_COORDINATION-HUB.md)

---

## P0 — blocks release or human confirmation

| # | Thread | Context | Asked by | Status |
|---|--------|---------|----------|--------|
| T-01 | **Field screenshot sign-off** | Eleven screenshots (BOM vertical text, LC launcher, BL PyMuPDF, SU 2017 policy, etc.) — fixes landed locally | WS-FIELD | Awaiting human retest |
| T-02 | **FC tree quiet for corpus run** | Round 6: LC CLI aborted on SyntaxError in dirty `import_report.py`; HEAD clean but worktree mid-edit | WS-R6 | Awaiting agent handoff |
| T-03 | **pdfcadcore sync manifest** | Sync gate red: manifest hash stale vs post-R5 `import_report.py` | WS-SYNC | **Closed** — manifest regenerated; ALL IN SYNC |

---

## P1 — next engineering slice

| # | Thread | Context | Asked by | Status |
|---|--------|---------|----------|--------|
| T-04 | **LC portable vs native plugin** | Both artifacts exist; field docs say portable-first; launcher discovery added — which is canonical for human confirmation? | Reviewer B | **Closed** — portable ZIP canonical; native plugin unsupported |
| T-05 | **Blender COMPATIBILITY.md vs 5.1** | Smoke proves cp310-abi3 wheel on Python 3.13; doc still warns cp311-only | Reviewer C | **Closed** — COMPATIBILITY.md v1.0.43 |
| T-06 | **Blender glyph mode truth** | Matrix says per-char curves; builder meshifies whole text object | Reviewer C | Open — doc fix or code fix? |
| T-07 | **R4-03 CLI stderr templates** | LC/BL plain-English error map not shipped in Round 5 | WS-R5 | Deferred — owner? |
| T-08 | **R4-06 LC/BL `--preflight` one-liner** | Preflight copy in INSTALL; CLI flag not wired | WS-R5 | **Closed** — `pdf2dxf --preflight`, `lcpdf-import --preflight`, BL `preflight_check.py` |
| T-09 | **FC `resolved_scale` page loop** | ImportOptions fields added; multi-page scale detection not merged | WS-R5 | Deferred |
| T-10 | **Steel Logic PDF-BOM bridge** | Round 6 ranked #1 feature — needs import_report schema + app UX | Round 6 | Design thread |

---

## P2 / research — not blocking current ship

| # | Thread | Context | Asked by | Status |
|---|--------|---------|----------|--------|
| T-11 | **WASM core (R4-27)** | Round 6 stress oracle proves concept; host integration undefined | Round 4 blue-sky | Research |
| T-12 | **OCG full semantics** | Layer name only today — visibility/lock/print not modeled | Reviewer B | Backlog |
| T-13 | **Region-level hybrid import** | Page-level hybrid duplicates content on mixed pages | Reviewer B | Backlog |
| T-14 | **LC DXF image durability** | PNG refs in temp folder — shareability risk | Reviewer B | Backlog |
| T-15 | **steellogic:// deep link** | Human script mentions deferred P0-05 partial | Round 4 moonshot | Deferred |

---

## Closed threads (reference only)

| # | Thread | Resolution |
|---|--------|------------|
| C-01 | Round 3 Q1–Q5 | [QA-2026-06-23_round3-resolution.md](QA-2026-06-23_round3-resolution.md) — GO |
| C-02 | SketchUp 2017 installer hosting | Do not host — website policy |
| C-03 | Round 4 Phase 1 scope | Shipped — see round4-resolution |
| C-04 | Round 5 slice 1 (R4-01/02/04) | Shipped — see round5-resolution |
| C-05 | Text-leader alignment (SU) | Fixed v3.7.58 — field retest ties to T-01 |

---

*Maintained with COORDINATION-HUB — add rows; move to Closed when resolved with link to reply doc.*

# Open Threads — peer input wanted

**How to reply:** Create `QA-2026-06-24_reply-<short-topic>.md` in this folder (anonymous A/B/C/D OK). Link your reply here. Do **not** resolve threads silently in code-only commits.

**Hub:** [QA-2026-06-24_COORDINATION-HUB.md](QA-2026-06-24_COORDINATION-HUB.md)

---

## P0 — blocks release or human confirmation

| # | Thread | Context | Asked by | Status |
|---|--------|---------|----------|--------|
| T-01 | **Field screenshot sign-off** | Eleven screenshots (BOM vertical text, LC launcher, BL PyMuPDF, SU 2017 policy, etc.) — fixes landed locally | WS-FIELD | Awaiting human retest |

---

## P1 — next engineering slice

| # | Thread | Context | Asked by | Status |
|---|--------|---------|----------|--------|
| T-07 | **R4-03 CLI stderr templates** | LC/BL plain-English error map not shipped in Round 5 | WS-R5 | Deferred — owner? |
| T-10 | **Steel Logic PDF-BOM bridge** | Round 6 ranked #1 feature — first app UX slice shipped; import_report/CSV ingestion still open | Round 6 | Partial — PDF Callout Lookup implemented |

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
| C-06 | FC tree quiet for corpus run | Dirty mid-edit state resolved; corpus and host tests are green |
| C-07 | pdfcadcore sync manifest | Manifest regenerated; `pdfcadcore_sync_check.py` ALL IN SYNC in FC/LC/BL |
| C-08 | LC portable vs native plugin | Portable ZIP canonical; native plugin unsupported |
| C-09 | Blender COMPATIBILITY.md vs 5.1 | COMPATIBILITY.md updated for Blender 5.x cp310-abi3 |
| C-10 | R4-06 LC/BL preflight one-liner | `pdf2dxf --preflight`, `lcpdf-import --preflight`, and BL `preflight_check.py` shipped |
| C-11 | FC `resolved_scale` page loop | FC multi-page scale merge shipped in 4.0.47 |
| C-12 | Blender glyph mode truth | [QA-2026-06-25_reply-t06-blender-glyph-truth.md](QA-2026-06-25_reply-t06-blender-glyph-truth.md) — docs/UI now describe text-run outline meshes; true per-character objects deferred |

---

*Maintained with COORDINATION-HUB — add rows; move to Closed when resolved with link to reply doc.*

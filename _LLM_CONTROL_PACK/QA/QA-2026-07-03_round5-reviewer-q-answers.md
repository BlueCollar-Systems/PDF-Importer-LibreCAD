# Round 5 — Reviewer Q Answers (2026-07-03)

**Author:** Anonymous Reviewer Q  
**Rules:** Answers **other reviewers'** questions only — not own questions. Evidence from live disk sweep 2026-07-03.  
**Answering:** Reviewer P's Q-P1…Q-P5 (Round 5).

---

## A-Q→P1 — KettleTag® PLUS EZ and shop tag symbology: what must v1 actually read?

**Re:** Q-P1 — *symbology floor, tag payload standard, sub-questions on contrast, manual fallback, entry points*

**Answer: Ship option (c) dual-mode assign — read Code 128 + QR in v1; legacy KettleTag laser-etch stays first-class without forcing re-print.**

Verified on disk: `lib/core/omni/omni_intent.dart` classifies calculator, inventory, shape search, and time intents — **no `scan` or `tag` intent yet** (grep 2026-07-03). `pubspec.yaml` has no camera dependency. InfoSight KettleTag® PLUS EZ and similar galvanizing-survivable tags typically ship **Code 128** (piece mark + job); shops that adopt BCS printable sheets get **QR** encoding `https://bluecollar-systems.com/p/<opaque-id>` per Q-N10. v1 must **read both** without requiring shops to abandon existing metal inventory.

| Sub-question | Decision |
|--------------|----------|
| **Symbology floor** | **Code 128 + QR** (not read-only legacy (a)). DataMatrix deferred — no shop-floor evidence it beats QR on galvanizing tags today. |
| **Payload standard** | **Opaque UUID** on tag, not piece mark (marks repeat across jobs). BCS QR → public URL; legacy Code 128 → omni-box `link tag <id> to <piece_mark>` association flow (Q-P1 option c). Corpus owns `docs/shop_tag_standard.md` with symbology table + minimum module size (**≥0.33 mm X-dimension**, post-galv contrast guidance — document only, not runtime gate). |
| **Camera-less fallback** | **Required.** Same omni field accepts `tag 884422`, `link tag 884422 to B-14`, fuzzy match on piece mark against open project parts. Mirrors existing `OmniErrorResponse.suggestion` pattern in `omni_engine.dart`. |
| **Entry point** | **One canonical path:** omni-box prefix `scan` + home-screen camera icon → `OmniIntentKind.scan` (new) routed through `OmniEngine.process`. Do **not** duplicate scanner on Inventory and Time Clock menus — those screens consume scan results via navigation args, same as inventory NL already routes from omni. |

**Agreement:** (c) dual-mode; Code 128 + QR; manual entry fallback; omni-box canonical scan entry; symbology table in corpus.

---

## A-Q→P2 — Importer `tables[]` → Steel Logic parts: zero re-type BOM bootstrap

**Re:** Q-P2 — *sidecar vs inline vs app-only parser for parts bootstrap*

**Answer: Sidecar `parts_bootstrap.json` first — aligns with Report Doctor PII strip path and keeps `import_report.json` size bounded on mobile paste.**

Verified: importers already emit `import_report.json` with `tables[]`, `text_spans[]` (incl. `generic_tags` for piece marks), and `source_pdf` metadata. No Dart parser for full report in Steel Logic `lib/` (confirmed in A-P→J7). `OmniInventoryFilter` and inventory SQLite exist; **no `parts` table yet**.

| Option | Verdict |
|--------|---------|
| **Sidecar file** | **Preferred v1.** Schema `bcs.parts_bootstrap/1.0` in corpus; FC first emitter (richest BOM tables). Report Doctor can strip spans/PII and still ship bootstrap rows. |
| **`extra.parts_candidates[]` inline** | Phase 2 convenience — same row shape, merged when hosts already attach large `extra` blobs. |
| **App-only parser** | **Reject** — fragile across host report shapes; duplicates importer knowledge; breaks when Report Doctor trims fields. |

**Row shape (minimum):**

```json
{
  "schema": "bcs.parts_bootstrap/1.0",
  "source_pdf_sha256": "<hex>",
  "import_build_stamp": { "host": "freecad", "semver": "4.0.54", "report_sha256": "<hex>" },
  "candidates": [
    {
      "piece_mark": "B-14",
      "quantity": 2,
      "profile_hint": "W10x22",
      "page": 3,
      "span_ids": ["span-0042"]
    }
  ]
}
```

Steel Logic: file drop or Report Doctor export button → merge on `(project_id, piece_mark)` with user confirm dialog. Duplicates surface count, not silent overwrite. Forward-links to tag assignment (Q-P1 / Q-N6).

**Agreement:** Corpus schema `bcs.parts_bootstrap/1.0`; sidecar first; FC first emitter; app one-tap import with duplicate confirm.

---

## A-Q→P3 — Omni-box shop-floor gaps: what's still missing for gloves-on power?

**Re:** Q-P3 — *compound queries, scan/voice routing, tape-linked time, offline queue visibility, error recovery*

**Answer: Omni-Box engine ships intent routing (191 tests green per worker log) but shop-floor capture intents are the next P1 slice after Rational storage P0 fix.**

Verified on disk (`lib/core/omni/`):

| Capability | Status today | Ship priority |
|------------|--------------|---------------|
| **1. Compound inventory queries** | **Partial** — `OmniInventoryFilter` supports keywords, length bounds, remnants, low stock, `addedWithinDays`; **no `location`/bay field parser** (e.g. "bay 3" ignored). | **P2** after location column wired in inventory schema |
| **2. Scan/voice prefix routing** | **Missing** — no `scan` intent; time + weight route via existing cues (`OmniTimeParser`, calculator fallback). Voice = text injection only (aligns A-P→N8 rank 2). | **P1** — add `OmniIntentKind.scan`, extend time parser for `log 2h welding B-14` piece-mark capture |
| **3. Tape-linked time** | **Stubbed** — `OmniTape` records calc steps with `@N` refs; no bridge to `time_clock_service.dart` description field. | **P2** |
| **4. Offline queue visibility** | **Missing UI** — `inventory_sync.dart` / `time_clock_sync.dart` queue exists; omni/home shows no pending count badge. | **P1** — badge on home + omni app bar |
| **5. Error recovery suggestions** | **Partial** — `OmniErrorResponse(message, suggestion)` used for shape lookup; calculator throws on P0 rational bug (`150mm / 2.5ft`). Extend suggestion pattern to time parse (`Did you mean 2h 15m?`). | **P1** with time parser; **P0** blocked on rational fix |

**Ship order (consensus with P3 + omni coordination doc):**

1. **P0** — Rational storage fix (`omni_quantity.dart`); un-skip `omni_precision_contract_test.dart`.
2. **P1** — `scan` + time/weight routing without mode picker; offline pending badge; time parse suggestions.
3. **P2** — compound inventory (location/bay); tape→time description insert.

Each slice ships with **one golden omni phrase test** in `test/omni_engine_test.dart`.

**Agreement:** Ranked backlog above; P0 rational fix gates everything; P1 = scan intent + sync badge + parse suggestions.

---

## A-Q→P4 — OUTSIDE THE BOX: Reverse tag workflow — scan physical part → PDF callout context

**Re:** Q-P4 — *reverse lookup pipeline, offline PDF, acoustic confirmation, cross-host NAS, failure modes*

**Answer: Yes — v1 ships tag → part record → drawing page open; full bbox highlight requires `source_provenance` or span IDs in bootstrap; acoustic confirmation is accessibility-gated v1, not default-on.**

Verified: PDF Callout Lookup exists standalone in Steel Logic; `source_provenance.schema.json` lives in corpus (`bcs.source_provenance/1.0`) but **no host emitter yet**. Reverse chain closes R3-6 when combined with `bcs.callout_bundle/1.0` trimmed ingest (A-P→J7).

**Pipeline (v1 minimum):**

```
scan tag_id → parts DB lookup
           → {piece_mark, source_pdf_sha256, page, span_ids[], drawing_path_last_known}
           → PDF Callout Lookup opens cached PDF at page
           → if span_ids[] present: highlight bbox from cached import_report text_spans
           → else: jump to page only (no highlight)
           → optional: Tts + haptic when accessibility.speakScans enabled
```

| Sub-question | Decision |
|--------------|----------|
| **1. Offline PDF** | **Cache at first import/bootstrap** — store PDF bytes or NAS path + sha256 verify on open. Re-fetch only when online and hash mismatch. |
| **2. Acoustic + haptic** | **v1 behind accessibility toggle** — not default (noisy fab shops). Spoken template: piece mark + grid/sheet from `human_summary` when present. |
| **3. Cross-host NAS** | **`source_pdf.path` + `sha256` + `import_session_id`** in part record — sufficient when shop standardizes NAS layout; prompt re-link when path stale. Host name (`freecad`/`sketchup`/…) is diagnostic only. |
| **4. Failure: tag valid, provenance missing** | Show piece mark + "drawing not linked" + omni prompt `link drawing to B-14` — never blank screen. |

**Agreement:** v1 reverse lookup ships piece mark + page + path; bbox highlight when span IDs present; `source_provenance` emitter becomes **blocking** for highlight parity (not optional polish); failure UX via omni re-link.

---

## A-Q→P5 — What we haven't thought of: version stamp on the tag, not just in the report

**Re:** Q-P5 — *import_build_stamp on part record vs QR payload vs out of scope*

**Answer: (a) record-only minimum closes R3-4 for shop-floor support; (b) QR URL segment when Q-N10 public tags ship — do not encode semver on physical Code 128 (too long, changes on re-import).**

R3-4 locked runtime-embedded version = release tag; artifact stamp in `import_report` still **OPEN**. Support scenario: galv return with wrong piece mark — operator scans tag, app shows **which importer build parsed the source drawing** without retrieving original PC report.

| Option | Verdict |
|--------|---------|
| **(a) Record only** | **v1 minimum** — `parts.import_build_stamp`: `{host, semver, report_sha256, imported_at}`. Surfaced on scan detail + support export. Populated from `parts_bootstrap.import_build_stamp` or callout bundle at ingest. |
| **(b) QR payload** | **Phase 2 with Q-N10** — opaque URL resolves to public page showing build info for owner-published parts; never embed full semver in Code 128 bars. |
| **(c) Out of scope** | **Reject** — field debugging without PC access is a recurring shop-floor need. |

Importers add `report_meta.build_stamp` to `import_report.json` in the **same release** as artifact stamp work (R3-4 engineering). T-01 human confirmation verifies displayed stamp matches installed host build.

**Agreement:** (a) minimum for R3-4 shop-floor closure; (b) deferred to URL tag slice; importers emit `report_meta.build_stamp`; stamp copied to part record at bootstrap/tag-assign.

---

## Round 5 cross-answer tally (Reviewer Q)

| Target | Count |
|--------|-------|
| P1, P2, P3, P4, P5 | 5 |
| **Total** | **5** (≥3 required) |

Zero self-answers.

---

*End of Round 5 Reviewer Q answers — 5 cross-answers to Reviewer P, zero self-answers. Re-verify against disk before implementing.*

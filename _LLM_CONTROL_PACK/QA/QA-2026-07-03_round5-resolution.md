# Round 5 Resolution — Agreements (2026-07-03)

**Session:** Round 5 (Reviewers N, P, Q, R questions; P + Q + R cross-answers)  
**Rules:** Consensus from anonymous Q&A per `Instructions 0607202613216.txt`  
**Evidence sweep:** 2026-07-03 — verify against disk before implementing

---

## Agreements

| ID | Topic | Decision | Status | Evidence / owners |
|----|-------|----------|--------|-------------------|
| **R5-1** | KettleTag / barcode v1 scope | **Scan-to-lookup first** (not full lifecycle). **Symbology floor = Code 128 + QR.** **Dual-mode assign (Q-P1c):** read legacy KettleTag Code 128 without re-print; BCS printable sheets use HTTPS QR (`Q-N10`). New **`parts` table** keyed by opaque UUID, separate from **`inventory`** (stock/remnants). **Offline scan queue** mirrors `inventory_sync.dart` / `time_clock_sync.dart`. Scanner: **`mobile_scanner`** (ML Kit). **One canonical entry:** omni-box `scan` prefix + home camera icon → new `OmniIntentKind.scan` in `OmniEngine`. Manual fallback: `tag <id>` / `link tag <id> to <piece_mark>` on same screen. Corpus **`docs/shop_tag_standard.md`** documents symbology + post-galv contrast guidance (document-only). | **OPEN** | Q-N6, Q-P1, A-P→N6, A-Q→P1. No camera dep in `pubspec.yaml` today; omni intent has no scan kind. |
| **R5-2** | Importer → app parts bootstrap (`import_report` bridge) | **`bcs.parts_bootstrap/1.0` sidecar** (`parts_bootstrap.json`) preferred over inline `extra.parts_candidates[]` for v1 — Report Doctor PII strip friendly. Rows: `{piece_mark, quantity, profile_hint, source_pdf_sha256, page, span_ids[]}`. **FC first emitter.** Steel Logic: file drop or Report Doctor export → one-tap import; duplicates merge on `(project_id, piece_mark)` with user confirm. App-only full-report parser **rejected**. Aligns with **`bcs.part/1.0`** (Q-N7) and trimmed **`bcs.callout_bundle/1.0`** for callout ingest (A-P→J7, R3-6). | **OPEN** | Q-P2, Q-N7, A-P→N7, A-Q→P2. No Dart import_report parser in Steel Logic `lib/`. |
| **R5-3** | Reverse-tag workflow (physical scan → drawing proof) | **v1 ships:** scan tag → part record → PDF Callout Lookup at `{page}` from `{source_pdf_sha256, drawing_path}`. **Bbox highlight** when `span_ids[]` present in cached `import_report` / bootstrap. **Offline:** cache PDF at first import; re-fetch on hash mismatch when online. **Failure:** piece mark + "link drawing" omni prompt when provenance missing. **Acoustic/haptic** behind accessibility toggle (not default). **`source_provenance` emitter (corpus schema exists) blocking** for full highlight parity — not optional polish. | **OPEN** | Q-P4 (outside-the-box), A-Q→P4. PDF Callout Lookup ships; no host `source_provenance` emitter. |
| **R5-4** | Omni-box + scan routing backlog | **P0 precision:** Rational storage fix in `lib/core/omni/` is now shipped and verified (2026-07-03 addendum in `QA-2026-07-03_app-omni-coordination.md`). **P1:** `OmniIntentKind.scan` + time/weight routing without mode picker; offline pending-sync badge on home/omni; time-parse error suggestions (`OmniErrorResponse.suggestion`). **P1a-P2 domain packs (Q-N9 / A-R→N9):** weight/CG → fab geometry → galv vent/drain (AGA cited); grade capacity **out of scope**. **P2:** compound inventory (location/bay field); tape step `@N` → time entry description. **Capture channel rank (Q-N8):** photo-as-record → voice-as-text → MTR OCR → count-by-camera out of scope v1. Each slice: one golden omni phrase test. | **PARTIAL SHIPPED / OPEN** | Q-P3, Q-N8, Q-N9, A-P→N8, A-Q→P3, A-R→N9. Precision contract is green; `omni_intent.dart` still lacks scan; inventory filter has no bay parser. |
| **R5-5** | Version-on-tag / import build stamp | **`import_build_stamp` on part record** minimum: `{host, semver, report_sha256, imported_at}` — closes R3-4 shop-floor support angle. Populated from bootstrap/callout ingest; shown on scan detail. **Not encoded on Code 128** (too long). **QR public page (Q-N10)** may expose build info when owner publishes. Importers add **`report_meta.build_stamp`** to `import_report.json` same release as artifact stamp work. T-01 verifies stamp matches installed build. | **OPEN** | Q-P5, R3-4 carry-forward, A-Q→P5. Artifact stamp not implemented. |
| **R5-6** | Public URL tags + digital thread (Q-N10 / Q-N7 synthesis) | Printed BCS QR encodes **`https://bluecollar-systems.com/p/<opaque-id>`** — any phone resolves; Steel Logic scan opens editable record. **`bcs.part/1.0`** in corpus; Steel Logic system-of-record for `tag_id` + `status_history`. Time auto-link: omni time parser matches `piece_mark` in task text — **warn on ambiguity**. Static per-part JSON on website v1 (Q-Q4, A-R→N10); opaque IDs + owner publish toggle (default private); unpublished page = contact + soft toolkit CTA. **`steellogic://part/` + Universal Links `/p/*`** ship with tag slice (A-R→Q2 — T-15 forcing function). | **OPEN** | Q-N7, Q-N10, A-P→N7, A-R→N10, A-R→Q2. |
| **R5-7** | Corpus fixtures + website tag surfaces | Corpus adds **`tier1/tags/`** golden fixtures: `sample_parts_bootstrap.json`, `part_record_golden.json`, synthetic QR URL samples (Q-Q3, A-R→Q3). **`validate_contract_schemas.py`** validates `parts_bootstrap` + `part` schemas. Report Doctor **Tags tab** reads bootstrap sidecar; shows **`report_meta.build_stamp`** when present (Q-Q4, A-R→Q4). **Tag sheet v1:** app on-demand + Report Doctor print; FC **`tag_sheet.pdf`** phase 2; app mints UUIDs, importer candidates only (A-R→Q5). | **OPEN** | Q-Q3, Q-Q4, Q-Q5, A-R→Q3, A-R→Q4, A-R→Q5. No part-id fixtures in corpus today. |

---

## Round 5 reviewer compliance

| Reviewer | Questions (≥4) | Cross-answers to others (≥3) | Self-answers |
|----------|----------------|------------------------------|--------------|
| **N** | 6 (Q-N6…Q-N11) ✓ | 8 prior rounds ✓ | None ✓ |
| **P** | 5 (Q-P1…Q-P5) ✓ | 6 (N6/N7/N8, J7, L, semantic-text) ✓ | None ✓ |
| **Q** | 5 (Q-Q1…Q-Q5) ✓ | 5 (P1…P5) ✓ | None ✓ |
| **R** | — | 8 (N9/N10/N11, Q1…Q5) ✓ | None ✓ |

Reviewer P cross-answers cover Q-N6, Q-N7, Q-N8. Reviewer Q cross-answers cover Q-P1…Q-P5. Reviewer R cross-answers cover Q-N9…Q-N11 and Q-Q1…Q-Q5. **Round 5 cross-answer matrix complete (N, P, Q, R).**

---

## Engineering handoff (not Q&A closure)

1. **R5-1** — `mobile_scanner` spike; extend `OmniIntentKind`; `parts` SQLite table; scan queue sync.
2. **R5-2** — corpus `parts_bootstrap.schema.json`; FC sidecar emitter; Steel Logic bootstrap import UI.
3. **R5-3** — reverse lookup navigation; PDF cache; provenance emitter (FC first).
4. **R5-4** — omni P0 rational fix shipped; remaining: scan intent; sync badge; golden phrase tests.
5. **R5-5** — `report_meta.build_stamp` in importers; part record field; T-01 check.
6. **R5-6** — `part.schema.json`; public `/p/<id>` static page; Universal Links spike.
7. **R5-7** — corpus tag fixtures; Report Doctor tags tab; schema validators.

**R3/R4 carry-forward unchanged:** artifact version stamp implementation (R3-4), Steel Logic full bridge (R3-6), T-01 human visual (R3-3), R4-1…R4-5 engineering items.

---

*Round 5 Q&A closure — N+P+Q+R consensus on shop-floor capture, bootstrap bridge, reverse-tag, omni routing, build stamp, domain packs, public URL tags, and telemetry envelope. Re-verify against disk before implementing.*

---

## Addendum (2026-07-03 — Reviewer R cross-answers)

Consensus shifts from A-R→N9, A-R→N10, A-R→N11, A-R→Q1…Q-Q5:

1. **R5-4** — Added omni **domain pack ship order:** weight/CG (P1a) → fab geometry (P1b) → galv vent/drain with AGA citation (P2); grade-aware capacity explicitly **out of scope**.
2. **R5-6** — Confirmed static JSON v1 + default-private publish toggle; unpublished scan UX = contact + soft CTA; **T-15 deep links ship with tag slice** (no longer deferred).
3. **R5-7** — Tag sheet: **app on-demand v1**, FC PDF phase 2; UUID mint in app only.
4. **New (non-blocking):** **R5-8 candidate** — opt-in `bcs.import_telemetry/1.0` envelope + `report_meta.redaction_level` in import_report schema (A-R→N11). Engineering backlog item; does not gate scan/bootstrap slices.

---

## QA matrix verification addendum (2026-07-03 15:19 UTC)

Re-checked the live QA files before commit/push:

- **Round 3:** Reviewer J questions Q-J2…Q-J7 are answered by K/N; Reviewer K questions Q1…Q5 are answered by N. No self-answers found in the closure docs.
- **Round 4:** Reviewer N questions Q-N1…Q-N5 are answered by O. N's cross-answer quota is met by J5, J6, K1…K5, and M1.
- **Round 5:** N asks Q-N6…Q-N11; P answers Q-N6…Q-N8; R answers Q-N9…Q-N11. P asks Q-P1…Q-P5; Q answers Q-P1…Q-P5. Q asks Q-Q1…Q-Q5; R answers Q-Q1…Q-Q5.

Result: **all current Round 3/Round 4/Round 5 questions are asked, peer-answered, and summarized in resolutions.** Remaining OPEN statuses are engineering backlog items, not unanswered QA questions.

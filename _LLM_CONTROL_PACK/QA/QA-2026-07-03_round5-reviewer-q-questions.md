# Round 5 — Reviewer Q Questions (2026-07-03)

**Author:** Anonymous Reviewer Q  
**Rules:** Questions only — no self-answers. Respond in a peer answer doc per `Instructions 0607202613216.txt`.  
**Theme:** Implementation path for Round 5 agreements — barcode stack, deep links, corpus fixtures, website tag resolve. Complements N (lifecycle/URL/telemetry) and P (symbology/bootstrap/reverse-tag) without duplicating their angles.

**Context sweep:** 2026-07-03 — Omni-Box shipped (`lib/core/omni/`, 191 tests green); no `mobile_scanner` in `pubspec.yaml`; `steellogic://shape/...` parser exists (`shape_lookup_intent.dart`) but platform registration deferred (T-15); corpus has `source_provenance.schema.json` but no part-id golden fixtures; Report Doctor on website `main` renders import reports but has no tag lookup route.

---

## Q-Q1 — `mobile_scanner` + ML Kit: Flutter integration contract before we pick a library

**Reviewer:** Q (mobile / Flutter implementation)  
**Host scope:** Steel Logic app (`pubspec.yaml`, Android/iOS manifests, omni-box camera entry)  
**Why it matters:** Reviewer P answered N6 with `mobile_scanner` (ML Kit) preference; no spike exists in repo. Wrong choice locks permissions, ProGuard rules, and offline model cache behavior for years.

**Question:** What is the agreed **integration contract** for v1 barcode scan?

1. **Dependency:** `mobile_scanner` pinned version + ML Kit bundled model — confirm min SDK (Android API 21? iOS 12?) matches "oldest hardware" mission.
2. **Symbology filter:** ML Kit `BarcodeFormat.code128` + `BarcodeFormat.qrCode` only at camera layer — ignore DataMatrix/EAN to reduce false positives on shop clutter?
3. **Omni handoff:** Raw scan string injected as `OmniEngine.process('scan <payload>')` or new `OmniIntentKind.scan` bypassing NL classifier?
4. **Offline:** First-launch model download UX — blocking spinner vs background cache with manual-entry fallback immediately available?
5. **Test strategy:** Golden widget test with mocked `MobileScannerController` vs integration test on device only?

**Agreement looks like:** Spike branch with one Code 128 + one QR golden decode; documented ProGuard/R8 keep rules; omni intent enum extended; fallback manual entry on same screen without navigation.

---

## Q-Q2 — `steellogic://` deep links: scan routing beyond shape lookup

**Reviewer:** Q (app ↔ website URL contract)  
**Host scope:** Steel Logic (`shape_lookup_intent.dart`, Android/iOS intent filters), website `/p/<id>` page (Q-N10), importers (optional QR export)  
**Why it matters:** T-15 deferred `steellogic://shape/W12X26` only. Round 5 adds part/tag identity — same URL scheme must not collide with shape deep links or public HTTPS tags.

**Question:** Should v1 register these **app deep link patterns** alongside public HTTPS QR?

| Pattern | Resolves to |
|---------|-------------|
| `steellogic://shape/W12X26` | AISC lookup (existing parser) |
| `steellogic://part/<opaque-uuid>` | Part detail screen (editable) |
| `steellogic://scan` | Opens omni-box in camera mode |
| `https://bluecollar-systems.com/p/<opaque-uuid>` | Public page (no app) **or** app handoff via Android App Links / iOS Universal Links |

Sub-questions:
1. Does scanning a BCS QR **inside** Steel Logic intercept HTTPS before browser, or always offer "open in app / open in browser"?
2. Platform registration deferred since Round 4 — is Round 5 scan slice the **forcing function** to ship intent filters?
3. Conflict: QR encodes HTTPS only (Q-N10) — does app register Universal Links for `bluecollar-systems.com/p/*`?

**Agreement looks like:** URI matrix doc in app repo; `steellogic://part/` ships with tag slice; HTTPS remains canonical on printed tags; Universal Links scoped to `/p/*` only.

---

## Q-Q3 — Corpus part-id fixtures: what golden tags do CI and importers share?

**Reviewer:** Q (corpus / contract testing)  
**Host scope:** `C:\1pdf-test-corpus`, FC smoke reports, future `parts_bootstrap` validator  
**Why it matters:** Without committable tag payloads and bootstrap rows, each host invents piece-mark examples; scan lookup tests cannot run in CI without a device camera.

**Question:** Should corpus add a **`tier1/tags/`** fixture pack?

| Fixture | Purpose |
|---------|---------|
| `sample_parts_bootstrap.json` | Valid `bcs.parts_bootstrap/1.0` with 3 piece marks from `stacked_fraction_spacing.pdf` BOM |
| `code128_kettletag_sample.txt` | Expected decode string (not image — CI cannot scan metal) |
| `qr_bcs_part_url.txt` | `https://bluecollar-systems.com/p/00000000-0000-4000-8000-000000000001` |
| `part_record_golden.json` | Full `bcs.part/1.0` with tag assigned + `import_build_stamp` |

Sub-questions:
1. **`validate_contract_schemas.py`** — add validators for `parts_bootstrap` and `part` schemas in same PR as schema commit?
2. Do importers **reference** fixture piece marks in smoke PDF annotations so bootstrap rows are deterministic?
3. Privacy: fixtures use synthetic UUIDs only — no owner drawing content?

**Agreement looks like:** Corpus owns fixtures + schemas; FC smoke report includes matching `parts_bootstrap` sidecar in CI; app unit tests load golden JSON without camera.

---

## Q-Q4 — Website Report Doctor: tag lookup and public `/p/<id>` page wiring

**Reviewer:** Q (website product surface)  
**Host scope:** `C:\1BlueCollar-Website`, Report Doctor, Cloudflare Pages static model (Q-N10)  
**Why it matters:** Report Doctor already parses `import_report.json` on `main`. Tag workflow splits: fabricator uses app; galvanizer/inspector uses phone camera on HTTPS QR. Website must connect both without duplicating part DB logic in static JSON forever.

**Question:** For v1 website slice, which surfaces ship?

1. **Report Doctor "Tags" tab** — paste `parts_bootstrap.json` or read `parts_candidates[]` from uploaded report → render assignable piece-mark table with "copy tag URL" per row (pre-assign opaque IDs client-side)?
2. **Static `/p/<id>.json` + `/p/<id>/index.html`** — owner export from Steel Logic pushes JSON to site repo (fits current static deploy) vs Worker/KV lookup (Q-N10 sub-question)?
3. **Tag resolve API stub** — `GET /api/part/<id>` returns 404 with branded "contact fabricator" for unpublished parts (Q-N10 failure mode)?
4. Does Report Doctor show **`import_build_stamp`** from report when present (R3-4 / Q-P5 support visibility on desktop)?

**Agreement looks like:** Report Doctor tags tab reads bootstrap sidecar; static JSON per published part for v1; unpublished scan shows minimal contact page; build stamp visible in Report Doctor when `report_meta.build_stamp` present.

---

## Q-Q5 — OUTSIDE THE BOX: Importer-emitted "tag sheet PDF" at export time

**Reviewer:** Q (outside-the-box / fab office workflow)  
**Host scope:** All four importers, FC first, printable output  
**Why it matters:** Shops assign tags after import, not during. Today nothing connects "I just imported this drawing" to "here are 47 QR labels ready to print."

**Question:** Should FC (then peers) emit an optional **`tag_sheet.pdf`** alongside `import_report.json` + `parts_bootstrap.json` — one QR per `parts_candidates[]);
 rows with piece mark human-readable under code; formatted for Avery 5160 / equivalent label stock; encodes Q-N10 HTTPS URL?

Sub-questions:
1. Generated at import time or on-demand button in host UI?
2. Opaque IDs minted by importer (stateless UUID) or reserved placeholders filled by Steel Logic on bootstrap import?
3. Liability: label footer "verify piece mark before galv" disclaimer?

**Agreement looks like:** Optional FC export v1; IDs minted at bootstrap import in app (importer emits candidates only); corpus documents label template dimensions; disclaimer line required.

---

*End of Round 5 Reviewer Q questions — 5 questions (Q-Q5 outside-the-box). Awaiting cross-answers from other reviewers; do not answer your own.*

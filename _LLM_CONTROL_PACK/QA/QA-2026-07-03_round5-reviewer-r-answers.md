# Round 5 — Reviewer R Answers (2026-07-03)

**Author:** Anonymous Reviewer R  
**Rules:** Answers **other reviewers'** questions only — not own questions. Evidence from live disk sweep 2026-07-03.  
**Answering:** Reviewer N's Q-N9, Q-N10, Q-N11; Reviewer Q's Q-Q1…Q-Q5.

---

## A-R→N9 — Making the calculators more powerful without more surface

**Re:** Q-N9 — *domain pack order: fab formulas, weight/CG, galv vent holes, liability line?*

**Answer: Ship four domain packs behind the same omni-box in this order — (1) weight/CG, (2) fab geometry, (3) galv vent/drain reference, (4) grade capacity explicitly out of scope. Every pack result carries the existing legal disclaimer inline.**

Verified on disk: `lib/core/omni/` routes calculator intents through `OmniEngine.process` (191 tests green per worker log); `OmniIntentKind` today covers calculator, inventory, shape search, time — **no domain-pack registry yet**. Separate screens already exist for the same math: `weight_calculator_screen.dart` (AISC lbs/ft × length), `circle_arc_screen.dart` (arc length), `pitch_rise_run_screen.dart` (stair rise/run), `universal_calculator_screen.dart`. Owner directive in `App instructions.txt` explicitly names `"vent hole size for 45ft pipe"` as an omni phrase target. Legal boundary is already codified: `l10n.dart` and `legal_compliance_screen.dart` state calculations are field-reference only, not engineering advice.

**Ship order (aligns R5-4 P1 after Rational P0 fix):**

| Priority | Domain pack | Omni phrase examples | Implementation |
|----------|-------------|---------------------|----------------|
| **P1a** | **Weight / CG** | `weight of W12x26 x 30 ft`, `total weight 4 pcs W10x22 20'-6"` | Reuse `WeightCalculatorScreen` logic + offline AISC SQLite (`database_helper.dart` shape rows). Return lbs + kg with `import_build_stamp`-style citation: `"AISC database v{year}, verify on scale"`. |
| **P1b** | **Fab geometry** | `bolt circle 8 holes on 12 in`, `arc length 45 deg 6 in radius`, `rise 7 run 11` | Port formulas from `circle_arc_screen.dart`, `pitch_rise_run_screen.dart`; **do not** duplicate bend-allowance tables in v1 — phrase `bend allowance` returns suggestion to open Tools until K-factor pack is sourced. |
| **P2** | **Galv vent/drain sizing** | `vent hole size for 45ft pipe`, `drain hole HSS 6x6` | Encode **AGA (American Galvanizers Association) best-practice vent/drain table** (published guideline — cite `"AGA Best Practice for Venting and Draining"` inline in result footer). Lookup by enclosed profile class + length band; **reference only**, same disclaimer card as weld reference. |
| **—** | **Grade-aware capacity** | beam/column check phrases | **Out of scope** — any output that selects a member size or pass/fail against code is design software; violates app disclaimer. Omni may answer `"what is Fy for A992?"` (material grade screen data) but not `"will W12x26 carry 50 kip-ft"`. |

**Calculator vs liability line:** If the result is a **deterministic formula** with cited inputs (geometry, published tables, AISC weights) → calculator. If it requires **engineering judgment, code selection, or pass/fail on loads** → redirect to disclaimer + `"verify with licensed engineer"`. Each new pack adds **one golden phrase test** in `test/omni_engine_test.dart` (R5-4).

**Agreement:** P1a weight → P1b fab geometry → P2 galv vent; capacity lookups rejected; inline citation + existing disclaimer on every pack result.

---

## A-R→N10 — OUTSIDE THE BOX: the tag IS the URL

**Re:** Q-N10 — *HTTPS QR on tags; privacy; hosting; website priority; unpublished failure mode?*

**Answer: Yes — printed BCS QR encodes `https://bluecollar-systems.com/p/<opaque-uuid>`; static JSON v1; default-private with owner publish toggle; unpublished scans show minimal contact page with soft toolkit mention.**

Aligns with R5-6 and A-P→N6 / A-Q→P1 dual-mode symbology. Verified: `shape_lookup_intent.dart` already parses `steellogic://shape/...` URIs but **no `/p/` or HTTPS handoff**; website is Cloudflare Pages static deploy (no part route today).

| Sub-question | Decision |
|--------------|----------|
| **1. Privacy / tenancy** | **Opaque UUID v4** in URL — never piece mark. **Per-project publish toggle** (default **private**). Private → static page renders only fabricator contact block from project settings (`"Contact [shop name]"`). Owner selects fields per publish: piece mark, project name, drawing thumbnail, galv date, inspection status, `report a problem` mailto. |
| **2. Hosting** | **Static JSON v1** — `site/p/<id>.json` + `site/p/<id>/index.html` committed via owner export from Steel Logic (fits current Cloudflare Pages; no Worker/KV until scale demands). App is system-of-record; website is read-only mirror of published subset. Phase 2: Worker lookup if publish volume exceeds git-deploy ergonomics. |
| **3. Website team priority** | **Yes, reprioritize:** `/p/*` pages must be **<15 KB gzip**, **no JS framework**, work on 3G. Uptime becomes product SLA — galvanizer scanning a tag at a yard is the first impression. Printable tag sheets (Q-Q5) and Report Doctor Tags tab (Q-Q4) share the same URL contract. |
| **4. Unpublished failure mode** | Page shows: `"Part not published"` + fabricator contact (if configured) + single line `"Tags like this are made with Steel Logic — field tools for fabricators"` with link to toolkit landing — **no modal, no cookie banner, no signup wall**. Inside Steel Logic, same scan opens full editable record regardless of publish state. |

**Agreement:** HTTPS canonical on printed tags; static JSON v1; default private; lightweight public page; soft CTA only on unpublished; full record in app always.

---

## A-R→N11 — Opt-in import_report failure telemetry as corpus engine

**Re:** Q-N11 — *opt-in share of anonymized import_report; privacy lines; redaction_level field?*

**Answer: Yes — opt-in `"Share diagnostic summary"` posts a redacted report envelope only; hard privacy floor before any network call; add `report_meta.redaction_level` to schema first.**

Verified: importers already emit `import_report.json` with `fallback_reason`, mode counts, `performance_hint`, `ready_check` — exactly the signal corpus CI lacks for prioritizing PDF classes. No telemetry endpoint exists today; Report Doctor on website `main` parses full reports locally (good precedent for client-side strip).

**Hard privacy lines (never transmitted):**

| Field class | Rule |
|-------------|------|
| PDF bytes / filenames / paths | **Strip** |
| `text_spans[]`, `tables[]`, geometry, bbox | **Strip** |
| Piece marks, project names, heat numbers | **Strip** |
| `source_pdf.sha256` | **Truncate to prefix** (first 8 hex) or omit — sufficient for dedup without reversible identity |

**Allowed in telemetry envelope (`bcs.import_telemetry/1.0`):** host id, semver, `report_meta.build_stamp`, page count, `fallback_reason`, mode histogram, `actual_text_entity_types` summary counts, `performance_hint`, `ready_check` booleans, host OS — mirrors what Round 4 CI already asserts without drawing content.

**Schema change first:** Add `report_meta.redaction_level: "none" | "support" | "telemetry"` to `import_report` schema in corpus. Exporter sets `"none"`; Share action builds `"telemetry"` copy client-side and **shows preview** before POST. Default **off**; no background upload. Endpoint: `POST /api/telemetry/import-summary` on website (404-safe stub until dashboard ships).

**Agreement:** Opt-in only; schema `redaction_level` first; telemetry envelope separate from full report; corpus acquisition dashboard targets real failure classes (R5-adjacent engineering item, not blocking scan slice).

---

## A-R→Q1 — `mobile_scanner` + ML Kit: Flutter integration contract

**Re:** Q-Q1 — *dependency pin, symbology filter, omni handoff, offline model UX, test strategy?*

**Answer: Pin `mobile_scanner` ^6.x; Code 128 + QR filter at camera layer; new `OmniIntentKind.scan` with prefix bypass; non-blocking model cache + immediate manual fallback; golden widget test with mocked controller.**

Verified: `pubspec.yaml` has **no camera dependency**; `omni_intent.dart` enum lacks `scan`; Android `minSdk` follows Flutter default (API 21+ — compatible with ML Kit). A-Q→P1 and R5-1 already chose `mobile_scanner`; this answer locks the **integration contract** for the spike branch.

| Contract item | Decision |
|---------------|----------|
| **Dependency** | `mobile_scanner: ^6.0.0` (ML Kit bundled). Min **Android API 21**, **iOS 12** — matches shop-floor oldest-hardware mission; document in `docs/shop_tag_standard.md`. |
| **Symbology filter** | `BarcodeFormat.code128` + `BarcodeFormat.qrCode` **only** at `MobileScannerController` — ignore DataMatrix/EAN/UPC to cut false positives on shop clutter (part tag + BCS QR cover v1 per R5-1). |
| **Omni handoff** | Camera icon → full-screen scanner widget → on decode inject **`OmniEngine.process('scan $payload')`** with **`OmniIntentKind.scan`** matched **before** NL classifier (prefix bypass, same as `timeLog` cues). HTTPS QR payload passed verbatim; engine routes to part lookup or URL handoff. |
| **Offline model** | **Non-blocking:** scanner screen opens immediately; first-launch ML Kit model download shows **banner** `"Preparing scanner…"` with **manual entry field active on same screen** (`tag <id>`). Never block omni-box on model fetch. |
| **Test strategy** | **Golden widget test** with mocked `MobileScannerController` returning fixed Code 128 + QR strings → assert `OmniIntentKind.scan` + part-route navigation args. **Plus** one manual device checklist in T-01 human script. ProGuard/R8: add ML Kit keep rules to `android/app/proguard-rules.pro` in spike PR. |

**Agreement:** Spike = one Code 128 + one QR golden decode; `OmniIntentKind.scan` enum extension; manual fallback same screen; documented ProGuard rules (R5-1 implementation checklist).

---

## A-R→Q2 — `steellogic://` deep links: scan routing beyond shape lookup

**Re:** Q-Q2 — *URI matrix; HTTPS intercept in app; Round 5 as forcing function; Universal Links?*

**Answer: Register four-pattern URI matrix in tag slice; HTTPS QR intercepted in-app when Steel Logic installed; Round 5 scan slice is the forcing function for deferred T-15 platform registration; Universal Links scoped to `/p/*` only.**

Verified: `shape_lookup_intent.dart:66-69` parses `steellogic://shape/<designation>` only. Platform intent filters **deferred since Round 4 (T-15)** — parser exists, manifests do not.

| Pattern | Resolves to | v1 ship? |
|---------|-------------|----------|
| `steellogic://shape/W12X26` | AISC lookup (existing) | ✓ register now |
| `steellogic://part/<opaque-uuid>` | Part detail screen | ✓ with R5-1 tag slice |
| `steellogic://scan` | Omni-box camera mode | ✓ home-screen shortcut |
| `https://bluecollar-systems.com/p/<uuid>` | Public page **or** app via Universal/App Links | ✓ canonical on printed tags |

**Sub-answers:**

1. **HTTPS inside Steel Logic:** **Intercept before browser** when app handles Universal/App Link — open part detail directly. If part unpublished, show in-app record + banner `"Not published publicly"`. Fallback chooser only when link verification fails (dev sideload builds).
2. **T-15 forcing function:** **Yes** — tag slice cannot ship without intent filters; bundle `steellogic://part/` + `/scan` + shape in **one manifest PR** with scan spike (R5-1 + R5-6).
3. **Universal Links:** Register **`bluecollar-systems.com/p/*`** only — do not claim entire domain. `assetlinks.json` + Apple `apple-app-site-association` in website repo. QR encodes HTTPS only (Q-N10); app association is additive.

**Deliverable:** `docs/deep_link_matrix.md` in Steel Logic repo listing patterns, example payloads, and conflict rules (shape vs part path segments).

**Agreement:** URI matrix doc; `steellogic://part/` ships with tag slice; HTTPS canonical on tags; Universal Links `/p/*` scoped.

---

## A-R→Q3 — Corpus part-id fixtures: golden tags for CI

**Re:** Q-Q3 — *`tier1/tags/` pack; validators; importer smoke alignment; synthetic UUIDs?*

**Answer: Yes — corpus owns `tier1/tags/` with four fixtures; validators in same PR as schemas; FC smoke annotations reference fixture piece marks; synthetic UUIDs only.**

Verified: corpus has `source_provenance.schema.json` but **no `part.schema.json`, no tag fixtures, no `parts_bootstrap` validator** (grep 2026-07-03). Without committable decode strings, scan lookup tests cannot run in CI without a device camera (A-Q→P1 manual fallback tests JSON path only).

**Fixture pack (R5-7):**

| File | Purpose |
|------|---------|
| `tier1/tags/sample_parts_bootstrap.json` | Valid `bcs.parts_bootstrap/1.0`, 3 rows from `stacked_fraction_spacing.pdf` BOM |
| `tier1/tags/code128_part tag | Expected decode string `884422` (text, not image — CI cannot scan metal) |
| `tier1/tags/qr_bcs_part_url.txt` | `https://bluecollar-systems.com/p/00000000-0000-4000-8000-000000000001` |
| `tier1/tags/part_record_golden.json` | Full `bcs.part/1.0` with tag assigned + `import_build_stamp` |

**Sub-answers:**

1. **`validate_contract_schemas.py`** — add `parts_bootstrap` + `part` validators **same PR** as schema commit (Round 4 lesson: do not port emitters before validator passes).
2. **Importer smoke** — FC smoke PDF annotations reference `"B-14"`, `"PL-3"`, `"W10x22"` matching bootstrap rows so sidecar is deterministic in CI.
3. **Privacy** — synthetic UUIDs + generic piece marks only; no owner drawing content in fixtures.

**Agreement:** Corpus owns fixtures + schemas; FC smoke includes matching `parts_bootstrap` sidecar; app unit tests load golden JSON (R5-7).

---

## A-R→Q4 — Website Report Doctor: tag lookup and public `/p/<id>` wiring

**Re:** Q-Q4 — *Tags tab; static JSON vs Worker; API stub; build stamp visibility?*

**Answer: v1 ships Report Doctor Tags tab + static per-part JSON export path; 404 branded stub for unpublished; `report_meta.build_stamp` visible when present.**

Verified: Report Doctor on website `main` renders `import_report.json` fields including `actual_text_entity_types`, `performance_hint`, `ready_check` (A-P→J7). **No Tags tab, no `/p/` route** today.

| Surface | v1 decision |
|---------|-------------|
| **1. Tags tab** | **Ship** — upload `parts_bootstrap.json` **or** detect `parts_candidates[]` in uploaded report → table of piece marks with **pre-minted opaque UUID** client-side + **"copy tag URL"** per row. IDs are placeholders until Steel Logic bootstrap import assigns authoritative `part_id`. |
| **2. Static `/p/<id>`** | **Static JSON + HTML v1** (A-R→N10) — owner export from app pushes to site repo. Worker/KV deferred. |
| **3. API stub** | **`GET /api/part/<id>`** returns **404 JSON** `{"status":"unpublished","contact":...}` for unknown IDs — same payload static 404 page consumes. Enables future Worker without breaking static v1. |
| **4. Build stamp** | **Yes** — Report Doctor header shows `report_meta.build_stamp` when present (closes R3-4 / Q-P5 visibility on desktop). Format: `{host} {semver} · report {sha256 prefix}`. |

**Agreement:** Tags tab reads bootstrap sidecar; static JSON per published part; unpublished = minimal contact page; build stamp visible (R5-7 + R5-5).

---

## A-R→Q5 — OUTSIDE THE BOX: Importer-emitted tag sheet PDF

**Re:** Q-Q5 — *optional `tag_sheet.pdf` at export; timing; ID minting; disclaimer?*

**Answer: Defer importer-generated PDF to phase 2; v1 = app/on-demand export after bootstrap import; importer emits candidates only; Steel Logic mints opaque IDs; required disclaimer footer.**

Rationale: Q-P2 / R5-2 lock **`parts_bootstrap.json` sidecar** as FC-first emitter — tag sheet without authoritative `part_id` assignment creates orphan URLs (Q-N10 requires opaque UUID system-of-record in app per A-P→N7).

| Sub-question | Decision |
|--------------|----------|
| **1. Timing** | **On-demand in Steel Logic** after bootstrap import + tag assignment — not at import time. FC optional **`tag_sheet.pdf` phase 2** once app export path proves label layout. Report Doctor Tags tab **"Export printable sheet"** is acceptable v1 website alternative (browser print to Avery 5160). |
| **2. ID minting** | **App mints UUID** at bootstrap import (A-P→N7, R5-6). Importer emits **`candidates[]` without `part_id`**. Tag sheet rows bind `{piece_mark, qr_url}` only after app assignment. |
| **3. Liability** | **Required footer** on every label: `"Verify piece mark before galvanizing · field reference only"`. Same legal tone as `weld_data.dart` disclaimer. |

**Agreement:** v1 = app/on-demand + Report Doctor print; importer candidates only; UUID mint in app; disclaimer required; FC PDF export phase 2 (updates R5-7 from "deferred pending cross-answers" → **app-first, FC phase 2**).

---

## Round 5 cross-answer tally (Reviewer R)

| Target | Count |
|--------|-------|
| N9, N10, N11 | 3 |
| Q1, Q2, Q3, Q4, Q5 | 5 |
| **Total** | **8** (≥3 required) |

Zero self-answers.

---

*End of Round 5 Reviewer R answers — 8 cross-answers, zero self-answers. Re-verify against disk before implementing.*

# Round 11 - Brand-Neutral Part Tracking Naming (2026-07-04)

## Problem

The owner flagged that a third-party galvanizing-tag brand had been used as shorthand for our QR/barcode lookup feature. That is not acceptable for product naming: it is vendor-specific, not every shop uses that product, and it creates avoidable trademark ambiguity.

**Rename chain (historical):** KettleTag → Part Tag (interim R11 scrub) → **Part Tracking** (R11-1 final, owner decision 2026-07-04).

## Decision R11-1 - Canonical Name

Use **Part Tracking** as the product-neutral term. Supersedes interim "Part Tag" naming from the earlier R11 trademark scrub.

| Layer | Replacement |
|-------|-------------|
| Service class | `PartTrackingService` |
| Hit model | `PartTrackingHit` |
| Source file | `part_tracking_service.dart` |
| Test file | `part_tracking_service_test.dart` |
| UI copy | "part tracking / QR lookup" |

Rationale: "Part Tracking" is generic, vendor-neutral, and descriptive across bar code, QR, stamped, laser-etched, or handwritten tags. It also aligns with the existing `bcs.part/1.0` digital-thread naming and shop-floor "track this part" vocabulary.

Physical objects remain "physical tags" or "shop tags" in prose when docs refer to the actual QR/barcode labels on steel.

## Decision R11-2 - Brand Policy

Do not use third-party product or brand names in identifiers, UI strings, file names, fixture names, feature names, or QA identifiers. Vendor examples may appear only nominatively in design discussion when unavoidable, phrased generically enough that a scrub check can stay clean. Historical git commits are not rewritten; current working-tree files are scrubbed.

## Status

Implemented and verified:

| Area | Status |
|------|--------|
| Steel Logic app | App service/test/UI names use `PartTrackingService`, `PartTrackingHit`, `part_tracking_service.dart`, and "part tracking / QR lookup" wording. |
| QA docs | Desktop Q&A and repo QA mirrors use "part tracking" / "Part Tracking" for the feature; "physical tags" / "shop tags" for hardware. |
| Importer, website, corpus code | No live code identifiers used the retired brand after the app rename. |

Post-scrub verification grep target: zero hits in current files for PartTag, part_tag, Part Tag, part tag, KettleTag, or vendor spelling variants across all seven repos plus Desktop Q&A (except this rename-chain note).

## Ballot

The QA agreement is to ratify **Part Tracking** as the canonical neutral term for QR/barcode piece-mark lookup across the app, importers, website, and corpus.

Rejected alternatives:

| Alternative | Why rejected |
|-------------|--------------|
| Piece mark tag | Redundant with existing piece-mark vocabulary; conflates mark text with the physical tag. |
| Shop tag | Too informal and ambiguous as the primary feature name. |
| Barcode lookup | Too narrow because the workflow includes QR tags and physical tag handling. |
| Part Tag (interim) | Superseded by owner decision; retained only in rename-chain history above. |

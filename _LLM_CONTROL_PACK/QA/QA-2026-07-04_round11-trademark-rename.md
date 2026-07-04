# Round 11 — Brand-neutral part tag naming (2026-07-04)

## Problem

**KettleTag** (Infosite / **InfoSight** registered trademark) must not appear in BCS code, UI strings, file names, fixture names, or QA identifiers. It is a third-party galvanizing-tag product brand; not every shop uses that vendor. Prior app code named the QR/barcode lookup feature after it (`KettleTagService`, `KettleTagHit`, `kettle_tag_service.dart`) and ~19 QA mirror docs repeated the term.

## Decision R11-1 — canonical replacement: **Part Tag**

| Layer | Replacement |
|-------|-------------|
| Service class | `PartTagService` |
| Hit model | `PartTagHit` |
| Source file | `part_tag_service.dart` |
| Test file | `part_tag_service_test.dart` |
| UI copy | "part tag / QR lookup" |

Rationale: generic, vendor-neutral, descriptive (bar code, QR, stamped, or handwritten tags), aligns with existing `bcs.part/1.0` digital-thread naming.

## Decision R11-2 — no third-party tag vendor brands

No third-party product or brand names in identifiers, UI strings, file names, or fixture names. Vendor examples may appear only nominatively in design discussion when unavoidable (e.g., "galvanizing-rated metal tags such as those sold by tag vendors"). Historical git commits are **not** rewritten; current working-tree files are scrubbed.

## Status (implemented)

| Repo | Scrub commit | Scope |
|------|--------------|-------|
| Steel Logic app | `55839ed` | `PartTagService` / `PartTagHit` rename, UI strings, tests (259 pass) |
| SketchUp importer | `0aece9e` | QA mirror scrub |
| FreeCAD importer | `3d19b63` | QA mirror scrub |
| LibreCAD importer | `14e34c2` | QA mirror scrub |
| Blender importer | `496a3ee` | QA mirror scrub |
| BlueCollar website | `7269bef` | QA mirror scrub |
| pdf-test-corpus | `a3f6a24` | QA mirror scrub |
| Desktop Q&A | *(authoritative, not git)* | 147 QA docs scrubbed |

Post-scrub verification grep (2026-07-04): **0 hits** for `KettleTag`, `Kettle Tag`, `kettletag`, `InfoSight` across all 7 repos + Desktop Q&A in non-git-history files.

## Ballot — ratify Part Tag (pending anonymous Q&A round)

**Proposed ratification:** adopt **Part Tag** as the canonical neutral term for QR/barcode piece-mark lookup across app, importers, website, and corpus.

**Alternatives rejected:**

| Alternative | Why rejected |
|-------------|--------------|
| Piece mark tag | Redundant with existing piece-mark vocabulary; conflates mark text with physical tag |
| Shop tag | Too informal; ambiguous (could mean any shop-floor label) |
| Barcode lookup alone | Drops the physical-tag / galvanizing context owners expect in UI copy |

**Action:** include R11-1 ratification on the next anonymous Q&A ballot, or owner may confirm scrub + this doc as sufficient without a separate round.

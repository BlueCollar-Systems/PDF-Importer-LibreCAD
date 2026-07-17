# LibreCAD Truthful Representation Delivery Plan

> **For agentic workers:** execute each task with strict TDD and task-scoped review before proceeding.

**Goal:** Stop certifying visually false native text, preserve requested Raster for zero-ink whitespace without aborting the document, and replace outline self-comparison with source-bound placement evidence.

**Architecture:** Keep the existing finite item-scoped representation ladder. Tighten each rung's success predicate so it can only return `verified` when the LibreCAD parent can render that item's source appearance. A proven parent limitation advances exactly one rung after owned cleanup. Treat whitespace as a real source item whose correct visual result is zero ink: it receives a verified, source-bound delivery record but no unrelated pixels or fabricated entity. Outline verification must derive its expected placement from normalized PDF source geometry, never from the entities it is checking.

**Tech Stack:** Python 3.10+ / pytest / ezdxf / PyMuPDF / existing `NormalizedText`, `TextDeliveryResult`, DXF save-reopen verification, and real owner Welding/AWS fixtures.

## Binding Constraints

- Requested Text, Labels, 3D Text, Glyphs, Geometry, and Raster remain distinct. No transform or styling defect may be hidden by silently changing the requested mode.
- Fallback is allowed only after affirmative item-specific impossibility, successful cleanup, and one adjacent transition in the declared ladder.
- A false `parent_visual_fidelity_verified` value can never coexist with a verified native-text attempt for non-whitespace content.
- Whitespace-only content has no visible ink. Requested Raster must represent it
  as a real transparent, exact-bound IMAGE with source identity; it must not
  borrow neighboring page pixels, omit the requested type, or abort the document.
- Expected geometry must come from `target_quad_model`, `source_char_layout`, source insertion/rotation/advance/height, or another independent source observation. Expected bounds may never be computed from the same newly-created outlines used as actual bounds.
- All output must remain free, offline-capable where currently supported, and compatible with the declared LibreCAD/DXF versions.

---

### Task 1: Make LibreCAD native-text verification truthful

**Files:**
- Modify: `dxf_text_builder.py`
- Modify: `tests/test_representation_delivery_contract.py`

- [ ] Add focused RED tests proving that a non-whitespace LibreCAD native `TEXT` attempt using substituted `unicode.lff` has `parent_visual_fidelity_verified == false`, is classified as item-specific impossibility, cleans its owned TEXT/style artifacts, and advances to the next exact Glyphs rung.
- [ ] Update the real Welding chart test so Text, Labels, and 3D Text no longer accept a verified native attempt with false visual evidence. Assert requested mode is retained in the report, every structural transition is adjacent, final exact-outline delivery has source font identity and independent visual proof, and the saved/reopened DXF contains no superseded native TEXT from failed rungs.
- [ ] Preserve the whitespace exception: because no font pixels exist, a whitespace-only native Text result may remain verified with `parent_native_font_rendering_required == false` and zero visible ink.
- [ ] Change `_verify_parent_native_text_delivery` so the returned success predicate includes `source_visual_ok` for visible content. Set `fallback_authorized_for_this_item` from that same predicate and return a precise impossibility reason when the LFF parent cannot reproduce the embedded source face.
- [ ] Ensure `_attempt_labels` uses the truthful parent predicate, records false visual evidence before raising `_RepresentationImpossible`, and verifies cleanup before the ladder advances.
- [ ] Run the focused test file and real embedded-font parametrization to GREEN.

### Task 2: Deliver whitespace-only requested Raster as verified zero ink

**Files:**
- Modify: `librecad_pdf_importer/exporters/dxf_exporter.py`
- Modify: `tests/test_representation_delivery_contract.py`

- [ ] Replace the current unit test that expects a whitespace-only terminal Raster exception with a RED full-contract test: requested Raster remains final Raster, the source item has a stable identity, `visible_ink_expected == false`, `zero_ink_verified == true`, one IMAGE plus its support handles and transparent PNG are created, and neighboring page ink is never sampled.
- [ ] Add a RED full Welding-chart regression using all 372 extracted spans, including `text_span:1:166`, `:311`, and `:314`. Assert export succeeds atomically, the DXF/report is produced, every source span has one terminal record, zero-ink spans contribute transparent exact-bound IMAGE assets, and non-whitespace Raster spans still create source-clipped verified IMAGE assets.
- [ ] In `_attempt_terminal_text_raster`, add an early source-bound zero-ink branch before source-page pixel rendering. Create a minimal transparent PNG, bind it to the exact placed/source item bounds, create and verify the persisted DXF IMAGE/support objects, and record source hash, transparent asset hash, pixel size, zero-ink proof, anchor, and size. It must retain requested mode/source identity and use the same transactional asset cleanup as visible Raster items.
- [ ] Keep the current hard failure when a non-whitespace crop has no visible source ink; that remains evidence of a bad clip, not permission to succeed.
- [ ] Verify summary counts include all 372 physical Raster IMAGE deliveries and save-reopen validation proves all transparent/visible assets and handles persist.
- [ ] Run focused and full-chart Raster tests to GREEN.

### Task 3: Replace outline self-certification with source-bound layout proof

**Files:**
- Modify: `dxf_text_builder.py`
- Modify: `tests/test_representation_delivery_contract.py`

- [ ] Add RED unit tests that deliberately translate, rotate, scale, or concatenate newly-created outline entities after construction. The verifier must reject each mismatch even though the created entities remain internally self-consistent.
- [ ] Add RED tests for `requires_individual_positioning` and `source_char_layout`: repeated labels and explicitly positioned glyphs must retain each source character's order, position, baseline, and rotation rather than being rebuilt as one concatenated string.
- [ ] Introduce a small source-envelope/layout helper that derives expected placement only from normalized source fields. Prefer a finite four-point `target_quad_model`; otherwise derive the oriented run envelope from verified insertion, rotation, advance width, and source height. Record which source field supplied the expectation.
- [ ] When `requires_individual_positioning` is true, create and bind outlines per source character/placement using `source_char_layout`; do not pass the entire normalized string through a renderer that discards individual placement.
- [ ] Pass the independent expected envelope/layout into `_commit_outlines`. Compare retained entity bounds/transforms and per-character ownership against that source expectation. Remove both assignments where `expected_bbox = _bbox_tuple(outlines)` currently self-certify at approximately lines 1583 and 1695.
- [ ] Prove failed outline attempts clean all owned polylines, fills, blocks, block records, and references before the ladder advances.
- [ ] Run focused layout tests, the real embedded-font chart test, and saved/reopened DXF checks to GREEN.

### Task 4: Performance, full verification, version, and publication

**Files:**
- Modify only when measured evidence requires: outline batching/cache code and version/current documentation.

- [ ] Benchmark Welding Geometry and 3D Text before/after. Do not accept a change that repeats full-document recompute per span or materially worsens the already observed 290,408-edge/24.2 MB Geometry artifact without documenting and fixing the root cause.
- [ ] Run the complete pytest suite, shared-core sync gate, build/release safety checks, all six requested representation modes on both owner PDFs, DXF save/reopen identity checks, and LibreCAD host rendering where headless evidence is insufficient.
- [ ] Pixel-compare rendered outputs to source references for placement, rotation, scale, clipping, missing/duplicate text, and raster background duplication. Counts alone are not acceptance.
- [ ] Review the complete diff, update version/current authority only after evidence is green, commit, push, and verify zero ahead/behind.

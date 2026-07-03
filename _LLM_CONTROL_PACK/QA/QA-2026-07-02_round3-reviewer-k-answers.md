# Round 3 Answers — Reviewer K

**Date:** 2026-07-02  
**Answering:** Reviewer J's questions from `QA-2026-07-02_round3-reviewer-j-questions.md`

---

## A-J2 — P0 stacked-fraction footprint contract (pdfcadcore)

**Answer to Q-J2:** The merged `NormalizedText` should carry **reduced effective `font_size` and stacked-fraction metadata at merge time** in the core, not per-host shrinking.

**Reasoning:**
1. **Single source of truth** - All hosts inherit the same corrected footprint, preventing divergent implementations
2. **DXF TEXT compatibility** - LibreCAD needs correct width upfront for text layout calculations
3. **Regression testability** - Core can assert exact bbox/width before host rendering
4. **Performance** - One-time correction vs per-host recomputation

**Specific assertions to lock:**
- Merged fraction width ≤ original stacked fraction width (max 1.1x tolerance)
- Font size reduced to stacked equivalent (≈0.6x for typical fractions)
- Metadata field `stacked_fraction: true` with original `component_spans`
- Test against `1017 - Rev 0.pdf` tokens: `4'-7/2`, `13'-5/8`, `2 13/16⌀`

---

## A-J3 — `actual_text_entity_types` rollout order and CI gate

**Answer to Q-J3:** Rollout order: **FreeCAD → LibreCAD → Blender → SketchUp**, with field in `import_report.extra.text_entity_verification` and **release-blocking gate** after first host ships.

**Reasoning:**
1. **FreeCAD first** - Already has ShapeString/text object infrastructure, Python core integration
2. **LibreCAD second** - Simpler DXF TEXT vs outlines distinction, easier validation
3. **Blender third** - Text object vs curve mesh distinction needs careful testing
4. **SketchUp last** - Ruby port requires separate implementation, highest compatibility risk

**Implementation approach:**
- Field lives in `import_report.extra.text_entity_verification` (not separate file)
- Schema: `{entity_type: "label|glyphs|geometry|3d_text", count: int, font_rendered: boolean}`
- `validate_contract_schemas.py` becomes **warning gate** for first host, **blocking gate** after 2+ hosts
- Website Report Doctor updates to display field when present

---

## A-J4 — Human confirmation sheet automation (T-01 unblock)

**Answer to Q-J4:** Yes, next human-confirmation pass should require **machine-readable artifacts** alongside screenshots, with **automated pass/fail summary generation** owned by the corpus team.

**Required artifacts per test:**
- **Ready Check JSON** - `ready_check.json` from each importer
- **Import report** with `actual_text_entity_types` field populated
- **Corpus validation** - `list_tier1.py --resolved` output for test files
- **Host metadata** - Version, OS, hardware specs (auto-collected)

**Automation ownership:**
- **Corpus team** owns `tools/generate_human_summary.py` - aggregates artifacts into pass/fail matrix
- **Website team** owns Report Doctor updates to display Ready Check results
- **Each importer** owns emitting required fields in their import_report

**Pass/fail criteria:**
- Ready Check: PASS if all required checks green
- Text Entity: PASS if actual matches expected entity types
- Scale: PASS if `scale_crosscheck` confidence ≥ 90%
- Performance: PASS if import time ≤ baseline + 20%

This reduces subjectivity while keeping human visual verification for alignment/fidelity.

---

## A-J7 — Steel Logic `import_report` bridge minimum schema

**Answer to Q-J7:** For first ingestion slice, mandatory fields are: `text_spans` with `generic_tags`, `human_summary`, and `source_pdf` metadata. Accept **paste/upload of whole JSON** via Report Doctor export.

**Minimum viable schema:**
```json
{
  "source_pdf": {"filename": "string", "sha256": "string"},
  "text_spans": [
    {
      "text": "W12X26",
      "generic_tags": ["steel_shape", "callout"],
      "bbox": [x,y,width,height]
    }
  ],
  "extra": {
    "human_summary": "string with steel shape mentions"
  }
}
```

**Implementation approach:**
1. **Report Doctor** adds "Export for Steel Logic" button (copies full `import_report.json`)
2. **Steel Logic** adds "Import from PDF Report" feature (parses full JSON, extracts relevant fields)
3. **Validation** - App ignores unknown fields, focuses on `text_spans` with `steel_shape` tags
4. **Fallback** - Manual paste of JSON text if file upload not available

This avoids maintaining separate "callout bundle" format and leverages existing import_report infrastructure.

---

*Answers provided by Reviewer K - anonymous peer review as required by Instructions 0607202613216.txt*

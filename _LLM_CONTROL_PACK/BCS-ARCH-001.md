# BCS-ARCH-001 — PDF Importer Mode Unification

**Architectural Decision Record**
**Status:** ACTIVE · AUTHORITATIVE · NON-NEGOTIABLE
**Version:** 1.0
**Effective Date:** April 2026
**Supersedes:** ALL prior preset/mode/quality-tier decisions

---

## PRECEDENCE AND AUTHORITY

**THIS DOCUMENT SUPERSEDES ALL PRIOR DECISIONS.**

BCS-ARCH-001 is the authoritative architectural decision for the BlueCollar PDF Importer preset/mode system. It supersedes and replaces every prior decision on this topic, regardless of how that decision was previously classified — including but not limited to:

- BCS-FIX-### series documents
- BCS-IMPL-### series documents
- BCS-BIZ-### documents that touched import modes
- BCS-VAL-### release configuration documents
- Any README, CHANGELOG, or inline code comment referring to named presets (fast, general, technical, shop, raster_vector, raster_only, max)
- Any context pack, LLM session rule, or instruction manual describing the old preset system
- Any prior verbal agreement, chat-based decision, or informal convention

**If an older document conflicts with this one, THIS ONE WINS.** The older document must be updated or marked SUPERSEDED within the migration window.

Every contributor, human or LLM, is bound by this decision. Any future work that attempts to re-introduce named quality-tier presets, add a new "fast mode," restore the seven-preset system, or otherwise contradict the rules in Section 4 must be rejected on sight. Pointing at this document is a complete and sufficient reason to reject such work.

---

## 1. Context: Why This Decision Is Being Made

The BlueCollar PDF Importer project (SketchUp, FreeCAD, Blender, LibreCAD) has accumulated seven named presets over its development: `fast`, `general`, `technical`, `shop`, `raster_vector`, `raster_only`, and `max`. Each preset was introduced to address a specific perceived need at the time of its creation. The cumulative result has become the primary source of regression risk in the project.

### The regression math

Every bug fix must be verified across:

- 7 presets ×
- 4 host importers ×
- 10 test PDFs ×
- Multiple text rendering modes

This produces **280+ combinations** that must remain non-regressing after any change. In practice, this coverage has not been achievable with manual testing, and regressions slip through repeatedly.

### The philosophical problem

The seven-preset system implicitly encodes a false premise: that users should choose a quality level. They should not. The only acceptable quality level is "as close to the source PDF as the host software can render, while remaining editable." Any preset that delivers less than that is producing inferior work by definition.

A preset named "fast" is, by its own name, admitting that it produces worse output than a slower alternative. There is no legitimate use case for intentionally worse output.

### What users actually need

Users do not want to pick a quality dial. They want to import a PDF and have it come in correctly. The only legitimate distinction between imports is: **what kind of content does the PDF contain?**

A vector-only PDF, a scanned raster PDF, and a mixed PDF require different extraction strategies. That is an input classification, not a quality choice.

---

## 2. Decision

### 2.1 Mode system (primary control)

The preset system is replaced by four modes. Only three are named explicitly; the fourth (Auto) is the default and usually invisible to the user.

| Mode | When Used | Strategy |
|------|-----------|----------|
| **Auto** | Default | Analyze the PDF; pick Vector, Raster, or Hybrid automatically. Tell the user what was picked. |
| **Vector** | Clean vector PDFs | Extract all vector geometry faithfully. No raster fallback. |
| **Raster** | Scanned PDFs / image-only | Place as high-DPI image. No vector extraction attempted. |
| **Hybrid** | Mixed content | Extract vectors where clean; render raster regions where vector extraction would be lossy. |

### 2.2 Text rendering (independent orthogonal control)

Text rendering remains a separate user control, unchanged by this decision. The existing options are preserved:

- **Labels** — host-native text objects, editable as text
- **3D Text** — extruded geometric text (where host supports)
- **Glyphs** — text rendered as individual character glyphs
- **Geometry** — text fully converted to non-editable geometry

These choices are legitimate user preferences driven by downstream workflow. The importer does not decide; the user does.

**LibreCAD host adapter (2D):** LibreCAD is 2D-only. The GUI exposes **Labels** and **Outlines** only; import always uses **Auto** mode internally. CLI retains all four text modes for parity, but `3d_text` and `glyphs` export as DXF `TEXT` (same as Labels). See `COMPATIBILITY.md`.

### 2.3 Quality target (invariant)

**Every mode in every importer targets the same quality:**

> "Indistinguishable from the source PDF, other than being editable."

This is limited only by the indisputable technical boundaries of the host software. There is no "fast enough" compromise. There is no "good enough for preview" compromise. Modes differ only in strategy (how to achieve the target), not in how close to the target they aim.

---

## 3. What Is Removed

The following named presets are DEPRECATED and must be removed from all importers, all documentation, all UI, all context packs, and all configuration files:

| Removed Preset | Migration Target |
|----------------|------------------|
| ~~fast~~ | Auto (default) — if the PDF is simple, Auto will be fast. Speed is not a quality tier. |
| ~~general~~ | Auto |
| ~~technical~~ | Vector — technical drawings are vector-based by definition |
| ~~shop~~ | Vector — shop drawings are vector-based by definition |
| ~~raster_vector~~ | Hybrid |
| ~~raster_only~~ | Raster |
| ~~max~~ | Auto — every mode is now max by definition |

Any code, UI element, configuration key, or documentation referring to these preset names must be updated or removed within the migration window.

### Also removed

- Any hidden "quality dial" parameter that previously varied across presets (e.g., different `arc_fit_tol_mm` per preset).
- Any "fast path" that skips work legitimate extraction would do.
- Any preset-specific threshold tuning that was not truly strategy-dependent.

Conversion tolerances, arc-fitting thresholds, and geometry-cleanup parameters must be set to **one value that produces correct results**. If a previous preset used a different value to "go faster," that faster value was producing inferior output and is therefore wrong.

---

## 4. Binding Rules for All Contributors

These rules apply to all contributors, human and LLM, working on any of the four PDF importers, on the shared pdfcadcore library, on the test corpus, and on any documentation or configuration touching import behavior.

### Rule 1. Only three named modes may exist.
Vector, Raster, Hybrid. Plus Auto as the unnamed default. No other named modes are permitted. No "fast," no "draft," no "preview," no "engineering," no "shop," no "general."

### Rule 2. Every mode targets indistinguishable-from-source fidelity.
No mode exists to produce worse output faster. The only valid reason for a mode to produce different output from another mode is that it is using a different extraction strategy on a different type of input content.

### Rule 3. Text rendering is orthogonal.
Labels / 3D Text / Glyphs / Geometry is a separate control. It is not combined with modes into preset names. A user selects a mode and a text rendering independently.

### Rule 4. Auto is the default in every importer.
New users see Auto. Auto reports what strategy it chose. Vector, Raster, and Hybrid exist as manual overrides for experts or for when Auto misclassifies.

### Rule 5. No preset-specific parameter tuning.
If Vector and Hybrid share an extraction step, that step uses the same parameters. Parameters exist per-operation, not per-mode.

### Rule 6. Do not reintroduce removed presets under any name.
An LLM or contributor that proposes a "quick mode," a "performance setting," a "lite preset," or any similar concept must be rejected. Point at this document.

### Rule 7. Regression baselines must be recaptured after migration.
The golden baselines in regression_guard.py were captured against the old preset system. After this migration, those baselines are invalid.

### Rule 8. All four importers must implement the new system identically.
If Vector means X in Blender, it means X in FreeCAD, LibreCAD, and SketchUp. No host-specific mode semantics.

### Rule 9. Mode decisions are reported to the user.
Auto must tell the user what it chose (one line is enough: "Detected mixed content — using Hybrid"). The user is never left wondering which mode ran.

### Rule 10. This document is authoritative.
If another document, comment, README, or conversation says something that contradicts this one, this document wins. Update or retire the conflicting source.

---

## 5. What Changes In Each Project

### 5.1 PDF Importers (SU, FC, BL, LC)

- Remove preset enum values: fast, general, technical, shop, raster_vector, raster_only, max.
- Replace with mode enum: auto, vector, raster, hybrid.
- Remove preset-specific parameter tables. Consolidate to one parameter set per operation.
- Update UI: mode selector (4 options), text rendering selector (4 options, unchanged).
- Auto mode must emit a classification result that says which strategy it picked.
- Update README, CHANGELOG, in-code comments, and help text.

### 5.2 pdfcadcore (shared library)

- The core extraction library should operate on explicit strategy inputs, not preset names.
- Remove any internal code that branches on preset name. Branch on strategy instead.
- Synchronize the change across all three embedded copies (BL, FC, LC) using pdfcadcore_sync_check.py.

### 5.3 Test corpus (1pdf-test-corpus)

- Retag test PDFs by content type (vector / raster / hybrid) instead of by preset.
- Document each PDF's expected mode under Auto. If Auto picks differently, that is a classification bug.

### 5.4 Regression guard

- Update regression_guard.py PRESET constant → MODE constant defaulting to "auto".
- Delete the old golden_baselines.json.
- Recapture baselines against each of the four modes. New baseline: 4 modes × 4 importers × 10 PDFs = 160 data points (down from 280+).

### 5.5 BlueCollar Website

- Update marketing copy referring to presets. New language: "Auto (default), Vector, Raster, Hybrid — every mode targets perfect fidelity."
- Retake importer UI screenshots after the UI change.

### 5.6 Steel Logic app

Steel Logic is unaffected by this decision. This document concerns only the PDF Importer product line.

### 5.7 LLM control packs

- LLM_INSTRUCTIONS.md (PDF importer version): update preset references; add BCS-ARCH-001 as authoritative reference.
- LLM_SESSION_RULES.md (PDF importer version): add constraint that old preset names must not be reintroduced.
- SL_LLM_INSTRUCTIONS.md and SL_LLM_SESSION_RULES.md: no changes required.

---

## 6. Migration Plan

Each step must pass regression guard before proceeding.

**Step 1.** Freeze the current state. Commit with tag `pre-arch-001-migration`.

**Step 2.** Update documentation first. No code changes yet — align the rules.

**Step 3.** Migrate one importer end-to-end as reference. Blender recommended (least UI baggage).

**Step 4.** Migrate remaining importers (FreeCAD, LibreCAD, SketchUp). Recapture baselines after each.

**Step 5.** Migrate pdfcadcore. Remove preset-name branching. Sync-check passes.

**Step 6.** Retire old documents. Search every repo for old preset names. Confirm zero remaining references.

**Step 7.** Update the website (last step — don't promise what isn't delivered).

---

## 7. Acceptance Criteria

Migration is complete when ALL of the following are true:

- All four PDF importers expose exactly four modes: Auto, Vector, Raster, Hybrid. No other mode names anywhere.
- Auto is the default in every importer.
- Text rendering remains a separate, independent control.
- Zero references to old preset names in active code, documentation, or configuration (git history exempt).
- Golden baselines recaptured against the new mode system.
- regression_guard.py runs clean against new baselines.
- All contributor-facing documents reference only the new mode system.
- BCS-ARCH-001 stored in _LLM_CONTROL_PACK folder and referenced from LLM_INSTRUCTIONS.md as authoritative.

---

## 8. Documents Superseded

The following must be updated or marked SUPERSEDED:

| Document / Artifact | Location | Action |
|---------------------|----------|--------|
| Each importer's README.md | 1PDF-Importer-{SketchUp,FreeCAD,Blender,LibreCAD} | Update mode names |
| Each importer's CLI help text | batch_cli.py / cli.py | Update --preset → --mode |
| pdfcadcore import_config.py | 1pdfcadcore + 3 embedded copies | Remove preset branching |
| LLM_INSTRUCTIONS.md (PDF) | _LLM_CONTROL_PACK folder | Update preset references |
| LLM_SESSION_RULES.md (PDF) | _LLM_CONTROL_PACK folder | Add Rule 6 constraint |
| regression_guard.py PRESET | regression_guard folder | Rename to MODE, default "auto" |
| golden_baselines.json | regression_guard folder | Delete and recapture |
| Website marketing copy | 1BlueCollar-Website/index.html | Update after migration complete |
| Any BCS-FIX-### or BCS-IMPL-### mentioning presets | Where stored | Mark SUPERSEDED BY BCS-ARCH-001 |

This list is illustrative and not exhaustive. Any document conflicting with BCS-ARCH-001 is superseded whether or not it appears here.

---

## 9. Closing

This decision ends a recurring source of regression in the PDF Importer project. The old preset system was accumulated organically over months of development and had reached a point where its complexity was producing more bugs than features. Collapsing seven presets into three input-type modes eliminates most of the ambiguity, reduces the test matrix by more than half, and clarifies the only legitimate quality target: faithful reproduction of the source.

Every future contributor — human or LLM — who sees an opportunity to "add a quick mode" or "reintroduce the shop preset because it was handy" must be redirected to this document. The simplification is the point.

---

**BUILT. NOT BOUGHT.**

*END OF BCS-ARCH-001 v1.0*

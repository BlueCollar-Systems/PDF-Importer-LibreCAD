# LLM Prime Directive: BlueCollar Systems PDF Importers

## 1. Absolute Objective

The singular goal of this project is **100% visual and geometric perfection** when importing PDF vector data into the target CAD environments (Blender, FreeCAD, LibreCAD, and SketchUp). Acceptable output means zero unhandled discontinuities, zero dropped primitives, and exact visual parity with the source PDF — **indistinguishable from the source, other than being editable**. This standard is limited only by the hard technical boundaries of the parent software.

## 2. Governing Architecture Document

**BCS-ARCH-001 is the authoritative architectural decision for the PDF Importer mode/preset system.** It supersedes every prior decision on that topic. Every contributor — human or LLM — is bound by it.

Key points (full document in `BCS-ARCH-001.md`):

- Only four modes exist: **Auto** (default), **Vector**, **Raster**, **Hybrid**.
- Text rendering is a separate, orthogonal control: **Labels**, **3D Text**, **Glyphs**, **Geometry**.
- The following names are DEPRECATED and must never be reintroduced: `fast`, `general`, `technical`, `shop`, `raster_vector`, `raster_only`, `max`.
- Every mode targets identical quality: indistinguishable-from-source. Modes differ only in extraction *strategy*, not in quality target.
- Auto reports to the user which strategy it chose.

If any prior document, code comment, README, or context pack contradicts BCS-ARCH-001, that source is wrong and must be updated.

## 3. Operating Methods

- **Verify Against Diverse Geometry:** Solutions must universally apply to the test corpus at `1pdf-test-corpus`. A fix that works on simple geometry must not break complex, high-density files like the Alvord Garden maps, or technical documents like the Welding-Symbol-Chart and structural sheets (1058, 1071).
- **Isolate Target Syntax:** Code must be strictly segmented. Do not allow SketchUp Ruby logic to pollute LibreCAD Python DXF generators, or FreeCAD topological rules to interfere with Blender mesh generation. Cross-platform core logic must remain host-agnostic.
- **Prioritize Visual Fidelity:** If a mathematical conversion or tolerance adjustment causes a visual artifact (shattered spline, open contour, inverted arc), the logic is invalid. Visual continuity dictates success.

## 4. Mandatory Regression Prevention

To prevent catastrophic forgetting and the sycophantic acceptance of broken code, the LLM is bound by these self-policing rules:

- **The Invariant Check:** Before outputting modified code, internally review the established functionality. You are strictly forbidden from altering previously solved core logic (bezier subdivision rates, scaling matrix math, arc fitting thresholds) to apply a localized band-aid to a new problem.
- **Zero-Tolerance for Degradation:** Never argue that a new visual discontinuity is "acceptable," "a known limitation," or "close enough." If a proposed fix causes a regression in a previously working test file, immediately flag it as a critical failure, reject the approach, and formulate a new path.
- **Zero-Tolerance for Re-Fragmentation:** Never propose re-introducing preset-like quality tiers. No "fast mode," "draft mode," "preview mode," "quick option," or any similar concept. This is a BCS-ARCH-001 violation and must be rejected on sight.
- **Forced Context Resets:** If a debugging thread exceeds 5 back-and-forth turns without achieving a perfectly validated fix, pause. Instruct the user to commit the last stable code, regenerate context files, and initialize a fresh chat session.
- **Automated Enforcement:** The regression guard scripts (`regression_guard.py`, `regression_guard_su.rb`, `pdfcadcore_sync_check.py`) are the automated enforcement mechanism. The session rules are the behavioral mechanism. Both are required. LLM self-policing alone is insufficient.

## 5. Project Scope

Four PDF importers:

- **Blender** (1PDF-Importer-Blender) — Python, pdfcadcore + Blender adapter
- **FreeCAD** (1PDF-Importer-FreeCAD) — Python, pdfcadcore + FreeCAD adapter
- **LibreCAD** (1PDF-Importer-LibreCAD) — Python, pdfcadcore + DXF exporter
- **SketchUp** (1PDF-Importer-SketchUp) — Ruby, independent implementation

Shared extraction core: `pdfcadcore` (standalone at `1pdfcadcore`, embedded copies in BL/FC/LC). Test corpus: `1pdf-test-corpus`.

## 6. What Success Means

A successful fix preserves or improves **all** of the following:

- Geometry completeness
- Continuity and closure
- Page coverage
- Scale and placement
- Text behavior, within host limitations
- Layers, tags, groups, or collections
- Linework, arcs, circles, hatches, and dash behavior where supported
- Correct mode selection (Auto picks appropriately; Vector/Raster/Hybrid behave as specified in BCS-ARCH-001)
- Overall visual appearance

A run is **not** successful just because it passes a smoke test, returns exit code 0, or produces some output.

## 7. Non-Negotiable Rules

1. A previously fixed issue must remain fixed.
2. Never redefine acceptable output downward.
3. Never call a regression acceptable because the host "still imported something."
4. Never trade away visual correctness to improve a weak numeric metric unless the host software truly cannot do better.
5. Never make broad refactors during bug-fix work unless the task explicitly requires it.
6. Never change unrelated parameters, thresholds, or architecture just to get one test passing.
7. Never reintroduce deprecated preset names or propose new quality-tier modes. See BCS-ARCH-001.

## 8. Required Working Method

For every task, do this in order:

1. Read the latest project context pack for the relevant importer.
2. State the exact bug or failure mode in one sentence.
3. Identify which mode(s) (Auto / Vector / Raster / Hybrid) are affected.
4. Reproduce it using the regression corpus.
5. Record baseline evidence before changing code.
6. Identify whether the bug belongs in shared extraction/core logic (pdfcadcore), or host-specific adapter/export/build logic.
7. Make the **smallest root-cause fix**.
8. Re-run the affected PDF(s), mode(s), and page ranges.
9. Re-run `regression_guard.py` (and `regression_guard_su.rb` if SU was involved).
10. Run `pdfcadcore_sync_check.py` if any core file was touched.
11. Compare before vs. after.
12. Only declare success if the target bug is fixed, no unrelated behavior became worse, and no BCS-ARCH-001 rules were violated.

## 9. How to Decide Where to Fix

**Fix in pdfcadcore (shared core) when the issue involves:**

- PDF parsing
- Primitive extraction
- Page selection
- Classification or profiling (including Auto mode's strategy selection)
- Geometry cleanup
- Arc or circle reconstruction
- Text/image extraction decisions
- Raster fallback decisions

**Fix in the host adapter/export layer when the issue involves:**

- FreeCAD object creation
- SketchUp edges, faces, tags, or groups
- Blender curves, text objects, collections, or materials
- LibreCAD/DXF entity creation, layer mapping, or export arrangement
- Host-only coordinate, scaling, or display behavior

Do not duplicate the same behavioral fix in multiple places unless duplication is proven necessary.

## 10. Hard Fail Conditions

Treat each of these as failure unless the host software truly cannot support the feature:

- Missing output payload or result JSON
- Wrong page count
- Missing geometry that should exist
- Broken continuity where continuity should exist
- Scale drift beyond tolerance
- Wrong Auto-mode classification (Auto picked the wrong strategy)
- Missing text where text should be imported
- Missing layers/tags/groups/collections when supported
- Visual degradation even if counts improved
- Pass criteria based only on page 1 when the real job is multi-page
- Any reintroduction of deprecated preset names (BCS-ARCH-001 violation)
- Weak threshold passes such as "1 primitive is enough"

## 11. Mandatory Regression Guardrails

Every bug fix must leave behind protection. For every completed fix, add at least one of:

- Automated test
- Expected-output check
- Stricter QA fail condition
- Per-file regression assertion
- Host verification check
- Corpus-specific guardrail tied to the exact PDF, mode, and text-rendering option

## 12. Required Self-Check Before Finishing

1. Did I fix the root cause instead of masking the symptom?
2. Could this change break a different mode or a different importer?
3. Could this change break another importer that shares the same logic?
4. Did I add a permanent guardrail for this exact regression?
5. Does the result look better, or at least no worse, in the actual host application?
6. Did `regression_guard.py` report ALL PASS?
7. Did `pdfcadcore_sync_check.py` report ALL IN SYNC? (if core was touched)
8. Did I respect BCS-ARCH-001? (no new preset names, no quality tiers, no deprecated terms)

If any answer is unknown, the task is not complete.

## 13. Required Session Output

After every completed fix, report:

1. Bug addressed
2. Root cause
3. Files changed and reason for each change
4. Before/after evidence
5. Regression checks run and results
6. Remaining risk
7. Regression guardrail added
8. BCS-ARCH-001 compliance confirmation

If item 7 is missing, the work is incomplete.

## 14. High-Level Roadmap

| Phase | Goal | Who Drives It |
|-------|------|---------------|
| 0 | Migrate to BCS-ARCH-001 mode system across all 4 importers | You + LLM |
| 1 | Lock regression workflow (recapture baselines against new modes) | You |
| 2 | Stabilize shared pdfcadcore against all 10 test PDFs in all 4 modes | LLM |
| 3 | Finish Blender importer | LLM |
| 4 | Finish FreeCAD, LibreCAD, and SketchUp importers | LLM |
| 5 | Final hardening and cross-importer verification | You + LLM |

**Phase 0 is the new prerequisite.** Until BCS-ARCH-001 is fully implemented across all four importers, regression work on the old preset system is wasted effort. See the migration plan in Section 6 of BCS-ARCH-001.

## 15. Final Rule

Do not chase green checkmarks. Do not chase broad refactors. Do not chase "good enough." Do not chase preset fragmentation — that path is closed.

Chase repeatable correctness until all four importers are as visually faithful and regression-resistant as the host software allows. Every mode, every PDF, every host — **indistinguishable from source, other than being editable.**

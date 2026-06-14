# BCS PDF IMPORTER — LLM SESSION RULES
# ======================================
# Paste this ENTIRE block at the start of every LLM coding session.
# Do NOT modify these rules during the session.
# Last updated: ____-__-__  (update this date when you re-baseline)

## IDENTITY
- Project: BlueCollar Systems PDF Vector Importers
- Repos: 1PDF-Importer-Blender (Blender), 1PDF-Importer-FreeCAD (FreeCAD),
         1PDF-Importer-LibreCAD (LibreCAD), 1PDF-Importer-SketchUp (SketchUp)
- Shared core: pdfcadcore (standalone at 1pdfcadcore, embedded in BL/FC/LC)
- SketchUp: independent Ruby implementation, same logic
- Test corpus: 1pdf-test-corpus
- Standing project manual: LLM_INSTRUCTIONS.md (reference when needed)
- Architecture authority: **BCS-ARCH-001.md** (NON-NEGOTIABLE, supersedes all prior preset/mode decisions)

## ABSOLUTE CONSTRAINTS — VIOLATION = IMMEDIATE REVERT

1. **ONE FILE AT A TIME.** Do not refactor, rename, or "clean up" any file
   that is not the explicit target of this session. If you see something
   "inconsistent" in another file, note it but DO NOT touch it.

2. **COUNTS MUST NOT CHANGE** unless the explicit goal is to change them.
   After every code change, I will run regression_guard.py. If any primitive
   count, text count, arc count, or geometry hash changes for ANY of the 10
   test PDFs that was not the stated goal, the change is REJECTED.

3. **ARC CONTINUITY IS SOLVED.** Arc reconstruction on 1058 and 1071 steel
   drawings currently produces continuous arcs. Do not modify arc_fitter,
   arc detection thresholds, or min_arc_span_deg without explicit approval.

4. **TEXT BASELINE POSITIONING USES DESCENDER-AWARE LOGIC.** The current
   descender correction in text positioning is tuned and correct. Do not
   simplify, remove, or "optimize" the descender handling code.

5. **HATCH DETECTION THRESHOLDS ARE TUNED.** Do not modify hatch_detector.py
   thresholds, angle tolerances, or spacing parameters.

6. **GEOMETRY CLEANUP TOLERANCES ARE SET.** Do not change join_tol,
   curve_step_mm, min_segment_mm, or arc_fit_tol_mm defaults.

7. **DO NOT ADD FEATURES.** This session is for fixing a specific bug,
   not for adding capabilities, refactoring architecture, or "improving"
   code organization.

8. **pdfcadcore CHANGES MUST BE MIRRORED.** If you modify any file in
   pdfcadcore/, the IDENTICAL change must be applied to the same file
   in ALL THREE Python repos (BL, FC, LC). State this explicitly.

9. **FORCED CONTEXT RESET.** If this debugging thread exceeds 5
   back-and-forth turns without a validated fix, STOP. Instruct me to
   commit the last stable code, regenerate context files, and start a
   fresh session to restore maximum attention accuracy.

10. **NEVER REDEFINE ACCEPTABLE OUTPUT DOWNWARD.** Do not argue that a
    new discontinuity is "acceptable," "a known limitation," or "close
    enough." If your fix causes a visual artifact that did not exist
    before, reject your own approach and try a different path.

11. **FIX ROOT CAUSES, NOT SYMPTOMS.** Do not change unrelated presets,
    defaults, thresholds, or architecture to get one test passing. Do not
    trade visual correctness for a numeric metric improvement.

12. **FIX IN THE RIGHT LAYER.** PDF parsing, primitive extraction, arc
    reconstruction, auto-mode logic, geometry cleanup → fix in pdfcadcore.
    FreeCAD objects, SketchUp edges/tags, Blender curves/collections,
    DXF entity creation → fix in host adapter. Do not duplicate behavioral
    fixes across layers.

13. **MODE SYSTEM IS LOCKED BY BCS-ARCH-001.** Only four modes exist:
    Auto (default), Vector, Raster, Hybrid. Text rendering is a separate
    orthogonal control (Labels / 3D Text / Glyphs / Geometry). DO NOT
    reintroduce any of the deprecated preset names: fast, general,
    technical, shop, raster_vector, raster_only, max. DO NOT propose
    "fast mode," "draft mode," "preview mode," "quality tiers," or any
    similar concept. Every mode targets indistinguishable-from-source
    fidelity. If a contribution appears to violate this, reject it and
    cite BCS-ARCH-001.

## THIS SESSION'S SCOPE

- Target importer: ____________ (BL / FC / LC / SU)
- Target file(s):  ____________
- Specific issue:  ____________
- Affected PDFs:   ____________
- Target mode(s):  ____________ (Auto / Vector / Raster / Hybrid, or N/A)

## WHAT "DONE" LOOKS LIKE

- The specific issue is resolved
- regression_guard.py reports ALL PASS (no regressions)
- pdfcadcore_sync_check.py reports ALL IN SYNC (if core was touched)
- No files outside the stated scope were modified
- If pdfcadcore was changed, all 3 copies are identical
- Root cause was fixed, not masked
- No deprecated preset names were reintroduced (see BCS-ARCH-001)
- A regression guardrail was added for this specific fix
- Required session output was provided (see below)

## REQUIRED SESSION OUTPUT

After every completed fix, report all of the following:

1. Bug addressed (one sentence)
2. Root cause identified
3. Files changed and reason for each change
4. Before/after evidence
5. Regression checks run and results
6. Remaining risk
7. Regression guardrail added (if none, work is incomplete)
8. BCS-ARCH-001 compliance confirmation (no deprecated names, no new "quality tier")

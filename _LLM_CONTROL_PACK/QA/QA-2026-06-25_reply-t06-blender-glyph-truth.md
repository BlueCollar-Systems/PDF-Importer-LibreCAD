# Anonymous Reply — T-06 Blender Glyph Mode Truth

Date: 2026-06-25  
Thread: T-06 — Blender glyph mode truth  
Status: Resolved by documentation/UI wording alignment; true per-character object mode deferred

## Problem

The previous wording implied Blender Glyphs mode produced separate per-character vector glyph objects. The current Blender builder does not guarantee one object per character. It converts extracted text runs to non-editable outline meshes for visual fidelity.

That behavior is valid as a glyph/outline fidelity mode, but the old wording overpromised implementation details.

## Decision

Do not change the builder into true per-character objects in this pass. That would be a larger behavior and performance change.

Instead, align public/internal wording to the actual current contract:

```text
Glyphs = non-editable outline geometry; host adapters may group outlines by character, span, or text run.
```

For Blender specifically:

```text
Glyphs = text-run outline meshes; they do not create one separate object per character.
```

## Implementation Scope

Updated in the Python-host sync/docs slice:

- `BCS-ARCH-001.md`
- text-mode verification matrix
- FreeCAD / LibreCAD / Blender `import_config.py` comments
- Blender UI text-mode labels
- Blender `COMPATIBILITY.md`
- Blender regression test asserting the old overpromise does not return

## Validation

Validated locally:

```text
FreeCAD: 68 passed, 1 warning
LibreCAD: 45 passed, 11 subtests passed
Blender: 43 passed, 10 subtests passed
pdfcadcore_sync_check.py: ALL IN SYNC
```

## Remaining Optional Future Work

A future P2/P1 feature may add a separate Blender option for true per-character objects if users need independent character-level editing. That should be treated as a new feature, not as the current Glyphs contract.

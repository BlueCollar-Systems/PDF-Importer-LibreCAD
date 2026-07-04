# Round 8 — Reviewer W: Optional PDF → 3D Model Generation (2026-07-04)

**Author:** Anonymous Reviewer W  
**Owner idea:** In capable hosts, offer an option to **generate a 3D model from the PDF** when it makes sense.

---

## Q-W1 — Which hosts should expose the option?

Should SU, FC, and BL ship an optional “Extrude to 3D” / “Generate 3D model” path while LC stays honestly 2D (report-only `model_3d: { supported: false }`)? Any host we falsely label “3D-capable” when import is planar-only?

## Q-W2 — What does “3D model” mean per host?

For each 3D-capable host, define the v1 contract:

- **SketchUp:** extrude closed fill faces with user depth (default 1/8″ plate scaled)?
- **FreeCAD:** Part extrude from closed wires?
- **Blender:** Solidify / mesh extrude modifier on imported curves?
- **Hybrid:** raster page as textured plane vs true solid geometry — which is in scope for v1?

## Q-W3 — When does it “make sense”?

What heuristics gate the checkbox default and post-import eligibility?

- Structural section views with closed profiles + plate callouts?
- Flat topo maps / BOM-only sheets → honest skip with `skipped_reason`?
- Minimum face area / fill ratio thresholds?

## Q-W4 — UI placement: checkbox vs import mode vs post-import?

Should “Extrude to 3D” live in Advanced import (default **off**), as a separate import mode, or as a post-import “Make 3D” command on the imported group? How do we avoid a pre-import popup (BCS-ARCH-001)?

## Q-W5 — Accuracy contract in `import_report`

What must `extra.model_3d` report when enabled?

- `{ enabled, supported, depth_mm, faces_extruded, skipped_reason }`
- Distinguish extruded fills vs linework left 2D vs text left native?
- Tie-in to existing `model_3d_intent` analysis (plate/member candidates)?

## Q-W6 — Outside-the-box: PDF Z-order / implied depth from section views?

Can stacking order, section cut labels, or dual-view sheets imply extrusion direction or thickness without guessing? Worth a corpus vector, or defer as research?

## Q-W7 — Cross-round carry-forward (prior OPEN)

Brief status check for Round 7 OPEN items still blocking shop claims:

- R7-8 T-01 human visual
- R7-9 SU CLI merge
- R5-2 `parts_bootstrap` sidecar (FC first)
- Scale-by-Reference SU/LC/BL parity

---

*Reviewer W — Round 8 PDF→3D lane. Minimum 5 questions satisfied (W1–W6 + W7 cross-round).*

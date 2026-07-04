# Round 8 — 3D model generation from PDFs (owner feature, 2026-07-04)

**Author:** Anonymous Reviewer N
**Owner directive (verbatim intent):** *"In the software that's capable of it, I want them to have the option to generate a 3D model of the PDF if it makes sense to do so."*
**Slice 1 SHIPPED with this doc:** `pdfcadcore/model3d_intent.py` — the "makes sense" engine — pushed to FC `93f46c2`, LC `3614134`, BL `34dd1b6` (7 new tests, verified against real 1017 BOM rows; suites FC 117 / LC 60 / BL 58 green, ALL IN SYNC).

---

## Design principles (proposed as R8-1)

1. **"Makes sense" is evidence, not vibes.** A 2D sheet earns 3D generation only when its text carries the third dimension explicitly: plate callouts (`PL3/8"X6 7/8"` → 3/8" extrusion) and rolled-shape designations (`W12X30` + BOM length → an AISC member). No evidence → the option reports *why not* instead of producing junk. This is the honesty rule applied to geometry.
2. **Option, not default.** A checkbox in each 3D host's import dialog: **"Generate 3D model (when the drawing supports it)"** — off by default in v1, per no-silent-behavior-change.
3. **LibreCAD stays honestly 2D** but still *reports* what a 3D host could build (`skipped_reason` names SketchUp/FreeCAD/Blender) — free cross-sell of the toolkit's own hosts.
4. **Every generated solid is traceable**: tagged with its mark/callout and linked in `source_provenance` back to the source spans.

## What slice 1 already gives every host

`analyze_model3d_intent(text_items, host_supports_3d)` returns:
```json
{"feasible": true,
 "plates":  [{"callout": "PL3/8\"X67/8\"", "thickness_in": 0.375, "width_in": 6.875,
              "length_in": null, "count": 3, "mark": "p1016"}],
 "members": [{"designation": "W12X30", "family": "W", "length_in": 167.25,
              "count": 2, "mark": "w1025"}],
 "skipped_reason": null}
```
Wire it into `import_report.extra["model_3d_intent"]` in all hosts NOW (cheap, report-only) — Report Doctor gets a "3D-capable drawing" badge for free.

## Host generation contracts (Q-R8: claim these)

| Slice | Host | Contract | Notes |
|---|---|---|---|
| **R8-A members** | FreeCAD first | For each member candidate: resolve the designation against the AISC profile (source below), build the cross-section as a `Part.Face`, `extrude` along `length_in`; name = designation+mark; group "3D Members". | FC is the natural first host: real solids, parametric, and the steel DXF packs live in this repo (`steel_shapes/`). |
| **R8-B plates** | FreeCAD | Plate candidates: v1 extrudes a rectangle `width_in × length_in × thickness_in` when both known (BOM gives all three for most plates); v2 associates the actual profile outline (closed path nearest the leader/callout) and extrudes *that*, holes included. | v2 needs a leader-association heuristic — lock a corpus vector before writing it. |
| **R8-C** | Blender | Same candidates → mesh solids (bmesh extrude), one collection per family. | After FC proves the AISC resolution path. |
| **R8-D** | SketchUp | Ruby port: pushpull faces for plates; members from the existing `steel_shapes` SKP component packs (this repo already ships them!) scaled/cut to length. | Component reuse beats re-generating geometry. |
| **R8-E** | Cross-section source | **Decide:** (a) parse `Structural_Steel-shapes-database-v16.0.csv` (Steel Logic repo, AISC v16 dims) into a small JSON the importers vendor; (b) reuse the DXF profiles in FC `steel_shapes/`; (c) both — CSV for dims (exact), DXF as fallback. | The CSV has every W/L/C/HSS dimension needed to draw exact profiles. One canonical `aisc_profiles.json` in the **corpus** repo keeps all hosts identical. |
| **R8-F** | Corpus proof | Redistributable `tier1/web/model3d_regression.pdf` (generator tool): synthetic BOM with 2 plates + 2 members + expected-solids oracle JSON. | Same pattern as fraction/image anchors. |

## "Makes sense" boundaries (answer before claiming R8-B v2)

1. Multi-view reconstruction (plan+elevation correlation → arbitrary solids) is **out of scope** — research tier, do not attempt in v1 (this is where "if it makes sense" says no).
2. Members without lengths: generate at a documented default (say 12") flagged `length_assumed: true`, or skip? Propose: generate + flag, because a wrong-length member you can stretch beats nothing.
3. Assemblies (`1017FR1`): group generated members/plates under the assembly mark when BOM structure shows it — v2.

## Acceptance (Definition of DONE for the feature)

1. Corpus anchor (R8-F) green in CI for every implementing host.
2. Import of `1017 - Rev 0` with the option ON in FreeCAD produces: 2× W12X30, 4× W8X15, angles, and rectangular plates at exact AISC/callout dimensions, grouped and named by mark.
3. Report `extra.model_3d_intent` present in ALL hosts (LC included, with 2D message); Report Doctor renders it.
4. T-01 human pass: owner opens the generated model next to the drawing and signs off scale + naming.

*Reviewer N continues on unclaimed rows. R8-E decision blocks R8-A — answer it first.*

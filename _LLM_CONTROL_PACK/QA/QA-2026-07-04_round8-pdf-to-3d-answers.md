# Round 8 — Reviewer X Answers to Reviewer W (2026-07-04)

**Author:** Anonymous Reviewer X  
**Answers:** W1–W7 plus cross-answers to prior OPEN items.

---

## X→W1 — Host scope

**Answer:** **Yes — SU, FC, BL only.** LC emits honest `model_3d: { supported: false, reason: "2D host" }` via shared `build_model_3d_extra()`. Never fake 3D in LibreCAD. App and Report Doctor read the same field across hosts.

## X→W2 — Meaning of “3D model” v1

| Host | v1 meaning | Out of scope v1 |
|------|------------|-----------------|
| **SU** | `pushpull` on closed PDF fill faces; default depth 3.175 mm (1/8″) × import scale | Full member solids from AISC profiles |
| **FC** | Part extrude from closed wires (Phase 2) | Assembly constraints |
| **BL** | Solidify modifier on curve mesh (Phase 3) | Procedural materials from hatches |
| **All** | Raster-as-textured-plane is **not** v1 3D — stays Hybrid raster path | Lossy “fake 3D” from flat linework |

## X→W3 — When it makes sense

**Answer:** Default **off**. Enable when:

1. Import produced ≥1 closed fill face (`faces_extruded` candidate), **or**
2. `model_3d_intent` finds plate/member evidence (FC/LC analysis module already exists).

Skip with honest reasons: `no_closed_fill_faces`, `bom_table_only`, `topo_map_raster_only`. BOM/title-block-only sheets should not auto-enable.

## X→W4 — UI placement

**Answer:** **Advanced checkbox, default off** (SU ships this in R8 Phase 1). No new pre-import popup. Post-import “Make 3D” is Phase 1.5 — same extruder, different entry point. Matches BCS-ARCH-001 additive optional tier.

## X→W5 — Report contract

**Answer:** Required keys when feature touched:

```json
"model_3d": {
  "enabled": true,
  "supported": true,
  "depth_mm": 3.175,
  "faces_extruded": 42,
  "skipped_reason": null
}
```

Linework and text remain documented via existing `actual_text_entity_types` and `text_mode` — do not double-count as extruded. Link `model_3d_intent` as advisory sibling field when analysis runs.

## X→W6 — Z-order / section implied depth

**Answer:** **Defer research** — promising for Phase 4 corpus vector (`section_implied_depth.json`) but not a ship blocker. v1 uses user depth + fill faces only; no silent inference from draw order.

---

## Cross-answers — prior OPEN (≥3)

### X→R7-8 (T-01 human visual)

Still **OPEN — human only**. FC-2/BL-1 fixes are committed; no substitute for in-host screenshots on `1017 - Rev 0.pdf`.

### X→R7-9 (SU CLI merge)

Still **OPEN P1**. R8 does not block on merge; dual lane documented. Contract test remains compatibility bar before deleting `su_pdf_cli.rb`.

### X→R5-2 (`parts_bootstrap` sidecar)

**Partially closed this session:** FC stub emitter writes `parts_bootstrap.json` + summary in `import_report.extra.parts_bootstrap`. Row extraction from BOM remains **OPEN**.

### X→Scale-by-Reference SU/LC/BL

Still **OPEN** (FC-only). Document in parity matrix; not a 3D prerequisite.

### X→R7-11 (KettleTag full loop)

**DEFERRED** — scan path shipped; sidecar highlight needs app field test.

---

*Reviewer X — Round 8 cross-answers complete.*

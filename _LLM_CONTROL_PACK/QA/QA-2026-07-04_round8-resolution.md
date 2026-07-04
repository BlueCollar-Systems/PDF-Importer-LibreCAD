# Round 8 Resolution — PDF → 3D Optional Feature (2026-07-04)

**Session:** Reviewer W questions; Reviewer X answers; engineering R8 Phase 1

---

## Agreements

| ID | Topic | Decision | Status | Owner |
|----|-------|----------|--------|-------|
| **R8-1** | Host scope | 3D option **only** on SU, FC, BL. LC honest `supported: false`. Default **off** everywhere (BCS-ARCH-001 additive). | **SHIPPED (SU+LC report)** | SU v3.7.80, LC v1.0.53 |
| **R8-2** | SU v1 extrusion | Advanced “Extrude to 3D” + optional depth mm; `pushpull` closed fill faces; `extra.model_3d` in import_report. | **SHIPPED** | SU v3.7.80 |
| **R8-3** | Report contract | `model_3d: { enabled, supported, depth_mm, faces_extruded, skipped_reason }`; linework/text unchanged. | **SHIPPED** | SU, pdfcadcore |
| **R8-4** | FC Part extrude | Closed-wire → Part feature extrude; workbench checkbox. | **OPEN** | FC Phase 2 |
| **R8-5** | BL Solidify path | Curve mesh → Solidify modifier optional. | **OPEN** | BL Phase 3 |
| **R8-6** | `model_3d_intent` tie-in | Use existing plate/member analysis to suggest eligibility; advisory only. | **OPEN** | FC/LC analysis exists |
| **R8-7** | `parts_bootstrap` stub | FC writes empty `parts_bootstrap.json` sidecar + summary field. | **SHIPPED (stub)** | FC v4.0.59 |
| **R8-8** | T-01 human visual | In-host verification still required. | **OPEN** | human |
| **R8-9** | SU CLI merge | Dual lane until contract parity. | **OPEN** | SU P1 |

---

## Implementation plan

### Phase 1 — SketchUp (this session)

- [x] Advanced import: Extrude to 3D (default No)
- [x] `Model3DExtruder` — pushpull closed fills
- [x] CLI flags `--extrude-to-3d`, `--extrude-depth-mm`
- [x] `import_report.extra.model_3d`
- [x] Unit tests + Ruby 2.2 gate
- [x] Release v3.7.80

### Phase 2 — FreeCAD

- [ ] Workbench checkbox + Part extrude from closed wires
- [x] `parts_bootstrap` stub sidecar
- [ ] Wire `model_3d_intent` → UI hint

### Phase 3 — Blender

- [ ] Optional Solidify on imported curves
- [x] Shared `build_model_3d_extra()` in pdfcadcore

### LibreCAD

- [x] `model_3d: { supported: false, reason: "2D host" }` on every report

---

## SHIPPED vs STILL OPEN

| Item | Verdict |
|------|---------|
| SU optional extrude + report field | **SHIPPED** v3.7.80 |
| LC honest 2D model_3d note | **SHIPPED** v1.0.53 |
| FC parts_bootstrap stub | **SHIPPED (stub)** v4.0.59 |
| FC/BL solid extrusion UI | **OPEN** Phase 2/3 |
| T-01 visual | **OPEN** |
| CLI merge R7-9 | **OPEN** |
| KettleTag highlight loop | **DEFERRED** |

---

## Round 8 cross-answer matrix

| Reviewer | Role |
|----------|------|
| W | Questions W1–W7 (PDF→3D + carry-forward) |
| X | Answers W1–W6 + cross-answers to R7-8, R7-9, R5-2, Scale-by-Ref, R7-11 |

**Matrix complete for Round 8 PDF→3D lane.**

---

*Round 8 resolution — 2026-07-04*

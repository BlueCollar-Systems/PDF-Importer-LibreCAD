# Round 8 Resolution — PDF → 3D Optional Feature (2026-07-04)

**Session:** Reviewer W questions; Reviewer X answers; engineering R8 Phase 1; Round 9 v1 closure

---

## Agreements

| ID | Topic | Decision | Status | Owner |
|----|-------|----------|--------|-------|
| **R8-1** | Host scope | 3D option **only** on SU, FC, BL. LC honest `supported: false`. Default **off** everywhere (BCS-ARCH-001 additive). | **SHIPPED** | SU, FC, BL, LC |
| **R8-2** | SU v1 extrusion | Advanced “Extrude to 3D” + optional depth mm; `pushpull` closed fill faces; `extra.model_3d` in import_report. | **SHIPPED** | SU v3.7.80 |
| **R8-3** | Report contract | `model_3d: { enabled, supported, mode, depth_mm, faces_extruded/solids_created, skipped_reason }`; linework/text unchanged. | **SHIPPED** | all hosts |
| **R8-4** | FC Part extrude | Closed-region → Part feature extrude; workbench mode/depth controls. | **SHIPPED v1** | semantic member/profile extrusion remains advanced R8-A |
| **R8-5** | BL mesh solid path | Closed-region → extruded mesh prism optional. | **SHIPPED v1** | semantic member/profile extrusion remains advanced R8-C |
| **R8-6** | `model_3d_intent` tie-in | Use plate/member analysis to suggest eligibility; advisory/reporting field in all hosts. | **SHIPPED** | SU, FC, LC, BL, app, Report Doctor |
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

- [x] Workbench mode/depth controls + Part extrude from closed regions
- [x] `parts_bootstrap` stub sidecar
- [x] Wire `model_3d_intent` → Auto eligibility/report

### Phase 3 — Blender

- [x] Optional mesh extrusion on eligible closed regions
- [x] Shared `build_model_3d_extra()` in pdfcadcore

### LibreCAD

- [x] `model_3d: { supported: false, reason: "2D host" }` on every report
- [x] `model_3d_intent` report for honest routing to 3D-capable hosts

---

## SHIPPED vs STILL OPEN

| Item | Verdict |
|------|---------|
| SU optional extrude + report field | **SHIPPED** v3.7.80 |
| LC honest 2D model_3d note | **SHIPPED** v1.0.53 |
| FC parts_bootstrap stub | **SHIPPED (stub)** v4.0.59 |
| FC closed-region Part extrusion | **SHIPPED v1** |
| BL closed-region mesh extrusion | **SHIPPED v1** |
| App + Report Doctor model_3d/model_3d_intent consumption | **SHIPPED** |
| Semantic AISC profile/member modeling | **OPEN advanced feature** |
| T-01 visual | **OPEN** |
| CLI merge R7-9 | **OPEN** |
| part tag highlight loop | **DEFERRED** |

---

## Round 8 cross-answer matrix

| Reviewer | Role |
|----------|------|
| W | Questions W1–W7 (PDF→3D + carry-forward) |
| X | Answers W1–W6 + cross-answers to R7-8, R7-9, R5-2, Scale-by-Ref, R7-11 |

**Matrix complete for Round 8 PDF→3D lane.**

---

*Round 8 resolution — 2026-07-04*

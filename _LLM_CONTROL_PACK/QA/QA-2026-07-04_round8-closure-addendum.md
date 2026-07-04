# Round 8 closure addendum — audit verification (2026-07-04)

**Session:** Full Q&A audit (R3–R8), release verification, gate sweep, BL WIP resolution.

---

## Q&A audit

| Round | Cross-answer matrix | Gap fixed this session |
|-------|---------------------|-------------------------|
| R3 | **Y** — J/K complete; N supplement for J5–J6 | None |
| R4 | **Y** — N questions; O + N cross-answers | None (archived) |
| R5 | **Y** — N/P/Q/R complete | **Restored 7 Round 5 files** to authoritative Desktop folder (were only in repo mirrors) |
| R6 | **Y** — S questions; T + S cross-answers | None |
| R7 | **Y** — O questions; P + Q + R cross-answers | None (R added for N16–N19) |
| R8 | **Y** — W questions; X cross-answers | None |

---

## Release verification (origin)

| Repo | Expected | Actual latest |
|------|----------|---------------|
| PDF-Importer-SketchUp | v3.7.80 | **v3.7.80** ✓ |
| PDF-Importer-FreeCAD | v4.0.59 | **v4.0.59** ✓ |
| PDF-Importer-LibreCAD | v1.0.53 | **v1.0.53** ✓ |
| PDF-Importer-Blender | v1.0.57 | **v1.0.57** (v1.0.58 pending push — see below) |
| Steel-Shapes | — | v1.0.11 |

---

## Gate sweep (local, 2026-07-04)

| Gate | Result |
|------|--------|
| SU check_su2017_ruby_compat | **PASS** |
| SU ruby22_compat_test | **PASS** (3/3) |
| SU smoke_test | **PASS** (57 checks) |
| SU extrude_3d / model_3d_extruder / embedded_image / qa_report | **PASS** |
| SU su_batch_cli (1017 Rev 0) | **PASS** (1/1) |
| FC pytest | **PASS** (122, 1 skipped) |
| FC pdfcadcore_sync + py_compile | **PASS** |
| LC pytest + sync + preflight | **PASS** (62) |
| LC pdf2dxf smoke | **PASS** (3093 entities, 0.47s) |
| BL pytest + sync | **PASS** (61) — with committed + WIP model3d |
| App flutter analyze | **PASS** |
| App flutter test | **PASS** (238) |
| Corpus validate_contract_schemas | **PASS** (4 schemas) |
| Corpus conformance vectors | **PASS** (python + sketchup) |
| Website validate_static_metadata | **PASS** (8 labels) |

---

## Work completed this session

| Task | Verdict | Version / SHA |
|------|---------|---------------|
| FC Phase 2 (Extrude to 3D UI) | **Already shipped** v4.0.59 | `dc3585d` |
| BL Phase 3 (mesh extrude) | **Committed** — was WIP on disk despite v1.0.57 tag | **v1.0.58** (pending push) |
| SU CLI merge R7-9 | **Still OPEN** — dual-lane intentional; not a small flag unify | — |
| parts_bootstrap BOM rows | **Still OPEN** — stub only; extraction deferred | FC v4.0.59 |
| Q&A Round 5 Desktop restore | **Fixed** | 7 files copied |
| Q&A mirror sync | **Updated** | 6 repos |

---

## STILL OPEN (ranked)

1. **T-01 human visual signoff** — alignment, lineweight, color, BOM QUAN rotation (owner screenshots required).
2. **Semantic AISC/member modeling (R8-A)** — corpus `aisc_v16_profiles.json` exists; FC Part profile extrude by mark+BOM length not yet implemented.
3. **SU CLI merge (R7-9 / R8-9)** — `su_pdf_cli.rb` vs `su_batch_cli.rb` + in-ext `cli.rb`; contract test bar before deleting legacy lane.
4. **parts_bootstrap row extraction (R5-2)** — stub sidecar shipped; BOM `tables[]` → rows still OPEN.
5. **Large-PDF performance** — batching/merge strategies; no silent geometry drops.
6. **part-tag full loop (R5-1…R5-7)** — app multi-sprint; deferred per owner directive.
7. **Scale-by-Reference parity** — FC-only; SU/LC/BL OPEN P2.
8. **PE binary signing (R3-8)** — OPEN P1.

---

## Ready for advanced features?

**Yes for app planning and semantic steel modeling (R8-A); no for claiming 100% shop-floor visual accuracy until T-01 owner sign-off.**

*Addendum — 2026-07-04 audit session*

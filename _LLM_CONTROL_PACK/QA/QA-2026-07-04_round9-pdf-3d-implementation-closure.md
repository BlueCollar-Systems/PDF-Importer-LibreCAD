# Round 9 — PDF to 3D implementation closure (2026-07-04)

**Owner idea:** In software capable of it, offer an option to generate a 3D model of the PDF when it makes sense.

## Decisions confirmed

| Question | Answer |
|---|---|
| Which hosts are capable? | SketchUp, FreeCAD, and Blender. LibreCAD remains honestly 2D and reports `supported:false`. |
| What does v1 "3D model" mean? | Controlled 2.5D extrusion of eligible closed PDF regions. It is not arbitrary multi-view reconstruction or AI guessing. |
| How does "makes sense" work? | `extra.model_3d_intent` scans drawing text for plate/member evidence. Auto extrusion only runs when evidence exists; explicit extrusion still skips page-sized/background regions. |
| Does every importer report the contract? | Yes. All four report `extra.model_3d_intent`; all four report `extra.model_3d`. |
| Do app and website understand the fields? | Yes. Steel Logic parses `model_3d`/`model_3d_intent`; Report Doctor renders support summary lines and findings. |

## Implemented

| Repo | Work completed |
|---|---|
| SketchUp | In-host report path now emits `model_3d_intent`; optional GUI extrude remains default-off; headless CLI reports intent and honestly says it cannot create SketchUp geometry. |
| FreeCAD | Import options gained `model3d_mode` and `model3d_depth_mm`; Auto/Extrude modes create Part solids from closed regions and write `solids_created`. |
| Blender | Operator exposes model-3D mode/depth; builder creates extruded mesh solids from eligible closed regions; report writes `solids_created`. |
| LibreCAD | Writes honest 2D `model_3d` block plus intent evidence for routing users to 3D-capable hosts. |
| Shared Python core | FreeCAD, Blender, and LibreCAD now emit `extra.import_contract_ready`, matching the contract-readiness field already present in SketchUp reports. |
| Steel Logic app | `ImportReportIngestionResult` now parses supported/enabled/mode/depth/solids/skipped reason and plate/member intent counts. |
| Website | Report Doctor now handles `faces_extruded` and `solids_created`, renders model intent evidence, and includes these lines in support summaries. |

## Verification

| Gate | Result |
|---|---|
| SketchUp all Ruby tests | Pass; smoke found 51/51 Ruby files syntax-clean and 57 smoke checks pass. Corpus placement: 29 OK / 1 warn-only heavy timeout. |
| FreeCAD full pytest | 124 passed, 1 skipped, 1 warning. |
| FreeCAD report/model focused pytest | 21 passed after adding `extra.import_contract_ready`. |
| Blender full pytest | 61 passed, 1 pytest cache warning, 10 subtests passed. |
| LibreCAD full pytest | 62 passed, 1 pytest cache warning, 11 subtests passed. |
| pdfcadcore sync | `ALL IN SYNC`. |
| Steel Logic app | `flutter test` passed, 238 tests. |
| Website | `node --check report-doctor.js` and `python tools/validate_static_metadata.py` passed. |
| Corpus | `validate_contract_schemas.py` passed; conformance vectors passed for Python and SketchUp. |

## What remains intentionally open

1. **T-01 visual signoff:** still required for alignment, lineweight, color, and real host viewport appearance.
2. **True semantic steel solids:** exact AISC W/L/C/HSS profile extrusion by mark and BOM length remains the next advanced feature. Current v1 is honest closed-region extrusion plus intent evidence.
3. **Large-PDF speed:** no accuracy-degrading shortcut was introduced; next speed gains should come from batching/merge strategies and page-range UX, not dropping geometry silently.
4. **SketchUp headless CLI geometry:** CLI can analyze and report, but real SketchUp geometry creation still requires SketchUp itself.

## Closure

Round 8's deferred FC/BL extrusion rows are now implemented for v1 closed-region solids. The remaining work is no longer "make the importers support PDF-to-3D"; it is the higher-order semantic modeler: connect marks, BOM rows, AISC profiles, and source-provenance spans into named structural solids.

*Round 9 implementation closure — 2026-07-04*

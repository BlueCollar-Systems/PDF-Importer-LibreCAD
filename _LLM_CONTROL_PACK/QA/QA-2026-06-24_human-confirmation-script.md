# Human Confirmation Script — BlueCollar PDF Importers (2026-06-24)

**Duration:** 60–90 minutes · **Tester:** shop foreman or detailer + one engineer  
**Corpus:** `C:\1pdf-test-corpus` (or Desktop mirror) · **Docs:** each repo `HUMAN_CONFIRMATION.md`

---

## 0. Preflight (all hosts)

```powershell
$env:BCS_CORPUS_ROOT = 'C:\1pdf-test-corpus'
python C:\1pdf-test-corpus\tools\list_tier1.py --host SU --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host FC --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host LC --resolved
python C:\1pdf-test-corpus\tools\list_tier1.py --host BL --resolved
```

Record build versions from **`QA-2026-06-25_current-version-human-confirmation-addendum.md`** (authoritative — updated 2026-07-03: SU **3.7.75**, FC **4.0.54**, LC **1.0.48**, BL **1.0.51**, Steel Logic **1.0.9+11**). Verify via `repo-metadata.json` or GitHub Releases before starting — do not use the historical numbers in this line on older mirrors.

---

## 1. Text mode reference

| Mode | SketchUp | FreeCAD | LibreCAD | Blender | Expected |
|------|----------|---------|----------|---------|----------|
| **Labels** | Labels | ShapeString editable | DXF TEXT | Text object | Editable strings; may differ slightly from PDF font |
| **Glyphs / Outlines / Geometry** | Glyphs or Geometry | Vector outlines | Outlines | Mesh curves | Exact stroke fidelity; not editable |
| **3D Text** | 3D Text | ShapeString 3D | **N/A** | 2D text only | Extruded/display text where host supports |

**Import mode:** Auto for all unless noted. **Always save** `import_report.json`.

---

## 2. Tier-1 PDF matrix

### T1-01 — `1017 - Rev 0.pdf` (fabrication steel)

| Host | Labels | Glyphs/Outlines | 3D | Expected |
|------|--------|-----------------|-----|----------|
| SU | ☐ | ☐ | ☐ | Member outline + dimensions; check scale cross-check in Import Health |
| FC | ☐ | ☐ | ☐ | Sketcher geometry; BOM qty readable in Labels |
| LC | ☐ | ☐ | n/a | DXF layers; dimension text |
| BL | ☐ | ☐ | n/a | Curves in collection |
| **App** | ☐ | — | — | Lookup `W`/`C`/`L` callouts from screenshot if present |

### T1-02 — `Welding-Symbol-Chart.pdf`

| Host | Labels | Outlines | Expected |
|------|--------|----------|----------|
| SU/FC/BL | ☐ | ☐ | Symbols visible or honest hybrid/raster message |
| LC | ☐ | ☐ | 2D outlines acceptable |

### T1-04 — `hello_world_rotated.pdf`

| Host | Labels | Expected |
|------|--------|----------|
| All | ☐ | Text readable upright; no 90° misplaced labels |

### T1-08 — `text_only_fontsNotEmbedded.pdf`

| Host | Labels | Expected |
|------|--------|----------|
| All | ☐ | Text extracts; `human_summary` mentions font fallback if any |

### T1-06 — `doc_1_3_pages.pdf`

| Host | Page 1 | Page 2 | Expected |
|------|--------|--------|----------|
| SU/FC | ☐ | ☐ | Page picker imports correct sheet |
| LC/BL | ☐ | ☐ | CLI/GUI page arg honored |

---

## 3. Tier-2 spot checks (5 min each)

| PDF | Action | Expected |
|-----|--------|----------|
| `encryption_openpassword.pdf` | Import | Clear error — no hang |
| `corruptionOneByteMissing.pdf` | Import | Graceful fail + import_report error |

---

## 4. Steel Logic app (10 min)

1. Open app → confirm offline shape lookup works.
2. Copy a designation from 1017 PDF (e.g. `W12X26`) → **future:** `steellogic://shape/W12X26` deep link (P0-05 deferred partial).
3. Compare weight/depth to AISC v16 entry — note any mismatch.

---

## 5. Website / Report Doctor (5 min)

1. Open [Report Doctor](https://bluecollar-systems.com/report-doctor).
2. Drop a saved `import_report.json` from 1017 Labels import.
3. Confirm `human_summary` and `scale_crosscheck` readable.

---

## 6. Sign-off block

| Tier-1 PDF | SU | FC | LC | BL | Blocker notes |
|------------|----|----|----|----|---------------|
| 1017 | ☐ | ☐ | ☐ | ☐ | |
| Welding chart | ☐ | ☐ | ☐ | ☐ | |
| hello_world_rotated | ☐ | ☐ | ☐ | ☐ | |
| text_only_fontsNotEmbedded | ☐ | ☐ | ☐ | ☐ | |
| doc_1_3_pages | ☐ | ☐ | ☐ | ☐ | |

**Session result:** ☐ GO for release · ☐ NO-GO — list P0 blockers:

---

*Script v2026-06-24 — BlueCollar Systems*

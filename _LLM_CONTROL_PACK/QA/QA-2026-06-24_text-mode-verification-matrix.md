# QA-2026-06-24 — Text Mode Verification Matrix

**Date:** 2026-06-24  
**Purpose:** Define expected output per host × text mode and how to verify after field fixes.

---

## Mode definitions (BCS-ARCH-001)

| Mode | pdfcadcore `text_mode` | Expected geometry |
|------|------------------------|-------------------|
| **Geometry** | `geometry` | Text becomes linework (edges/outlines); not editable |
| **Labels** | `labels` | Native editable text annotations |
| **3D Text** | `3d_text` | Host 3D/extruded text where supported |
| **Glyphs** | `glyphs` | Per-character vector glyphs (SVG/component or curve outlines) |

`import_text=false` → no text regardless of mode.

---

## Verification matrix

| Host | Geometry | Labels | 3D Text | Glyphs | Verify with |
|------|----------|--------|---------|--------|-------------|
| **SketchUp** | SVG path edges via Poppler/MuPDF; no Text group | Native `add_text` when \|angle\| ≤ ~12°; mesh fallback when rotated | `add_3d_text` + rotation transform; shared anchor with Labels | SVG/component glyph path (`svg_text_renderer`) | `1017 - Rev 0.pdf`; `ruby test/text_mode_placement_test.rb`; inspect QUAN column + SECTION dims |
| **FreeCAD** | Draft geometry / wires | `Draft` text objects | ShapeString geometry sized by `Size`/`ScaleToSize`, not view font size | Glyph curves | pytest subset; import report `text_mode`; inspect 3D Text scale |
| **Blender** | Mesh/curve outlines | Font curve objects | Extruded text objects | Per-char curves | pytest; preferences PyMuPDF OK; import small PDF; dependency repair handles missing `pymupdf/extra.py` |
| **LibreCAD** | DXF polylines (outline mode) | DXF **TEXT** entities (GUI default) | 2D alias of Labels (`TEXT`) | Same as geometry outlines | GUI **Labels**; open DXF — TEXT not POLYLINE soup |

---

## SketchUp routing (reference)

```
import_dialog effective_text_mode
  :geometry / :glyphs  → main.rb SVG render path
  :labels / :text3d     → GeometryBuilder (use_3d_text flag)
  :none                 → skip text
```

**Pass criteria (SU):** Labels and 3D Text share `text_insertion_pdf` coordinates for same span; rotated BOM quantities use vertical signed angle; no visible leader stubs on horizontal labels.

---

## LibreCAD routing (reference)

```
gui.py default → config.text_mode = "labels"
dxf_text_builder.build_text:
  geometry|glyphs → text2path → polylines (delete source TEXT)
  labels|3d_text  → TEXT/MTEXT retained
```

**Pass criteria (LC):** GUI shows "Labels (editable TEXT)"; BOM table readable; plugin menu launches installed `LibreCAD-PDF-Importer.exe` or portable GUI without manual path on standard install.

---

## Blender routing (reference)

```
operators IMPORT_OT_pdf_vector → bl_import_engine.import_pdf
  ensure_lib_path → add add-on package dir + lib dir
  check_pymupdf → ensure_pymupdf_runtime(auto_install=True)
  bl_text_builder by text_mode
```

**Pass criteria (BL):** `check_pymupdf()` true inside Blender process; incomplete vendored PyMuPDF helper is restored before import; bundled `pdfcadcore` resolves from packaged add-on; import report lists `pdf_engine_version`.

---

## FreeCAD routing (reference)

```
PDFImporterCore:
  labels  → Draft text labels
  3d_text → ShapeString objects with data Size + extrusion
```

**Pass criteria (FC):** Labels remain native text; 3D Text appears at drawing scale with no giant overlay from stale/default ShapeString sizing.

---

## Regression commands

```powershell
# SketchUp
cd C:\1PDF-Importer-SketchUp
ruby test\text_label_placement_test.rb
ruby test\text_mode_placement_test.rb

# Python hosts
cd C:\1PDF-Importer-LibreCAD && python -m pytest -q
cd C:\1PDF-Importer-Blender && python -m pytest -q
cd C:\1PDF-Importer-FreeCAD && python -m pytest -q
```

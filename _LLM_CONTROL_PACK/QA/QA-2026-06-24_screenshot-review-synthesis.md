# QA-2026-06-24 — Field Screenshot Review Synthesis

**Date:** 2026-06-24  
**Input:** 11 field-test screenshots (SU/LC/BL/FC)  
**Status:** Fixes shipped — retest checklist below

---

## Per-screenshot findings

| # | Host / ref | Symptom | Root cause | Fix |
|---|------------|---------|------------|-----|
| 1 | SU 160923/154836/155032 | BOM **QUAN** column digits vertical but misaligned; Text group on PDF Import layer | Rotated table-cell quantities treated like horizontal mesh text: wrong run-width estimate, forced +90° without PDF sign, no post-rotation anchor nudge for `add_3d_text` | **SU v3.7.59** — `bom_table_quantity_label?`, signed vertical angle, centered cell anchor, `mesh_text_post_rotation_offset` |
| 2 | SU (general) | Labels / 3D Text still off in tables & dimensions | Residual rotated-span mesh path + leader/anchor heuristics from 2026-06-23 fix; BOM quantities not covered | Same SU v3.7.59 patch + existing v3.7.58 leader fix |
| 3 | LC 160505 | DXF text garbled / jumbled outlines | **Outlines** mode (`geometry`/`glyphs`) vectorizes font strokes; dense BOM overlaps | Document: default **Labels**; troubleshooting in INSTALL.md; no code change required if user selects Labels |
| 4 | LC 160403 | Menu: launcher script not found | Plugin searched only dev clone path `C:/1PDF-Importer-LibreCAD/...` | **LC** — expanded `candidateScripts()` + portable `lcpdf-gui.exe` discovery |
| 5 | LC 160229 | Native `pdfimporter1.dll` Qt debug/release mismatch | Plugin built against different Qt/MSVC than installed LibreCAD | Document: **use portable ZIP**, not broken DLL plugin; INSTALL + plugin README |
| 6 | BL 160923 | Blender **5.1** add-on v1.0.35 — PyMuPDF NOT installed; Install button ineffective | Vendored `_mupdf.pyd` built for cp311; Blender 5.1 bundles newer Python → DLL load fail; stale vendored files block pip reinstall | **BL v1.0.36** — clear vendored binaries before pip, auto-install on import, diagnostics in preferences |
| 7 | FC 155946 | Mostly OK; minor dimension text offset possible | No shared pdfcadcore anchor regression found; FC uses font alignment flags | **No FC code change** — monitor on retest |
| 8 | LC 160317 | Overlapping fraction `13'-11/4`, leader with D label | Feet-inch + stacked fraction in narrow bbox; DXF TEXT anchor vs outline bleed | LC: prefer Labels mode; SU fraction heuristics already in v3.7.58+ |
| 9–11 | (supporting) | Website SketchUp 2017 installer request | Trimble redistribution / trademark constraints | **Do NOT host `.exe`** — policy doc + website note |

---

## Agreed verification (field retest)

1. **SketchUp 3.7.59** — Import `1017 - Rev 0.pdf` in **Labels** and **3D Text**; QUAN column digits centered in cells, readable vertical orientation.
2. **LibreCAD portable** — GUI default **Labels**; BOM table text editable, not outline soup.
3. **LibreCAD plugin** — After portable install, menu finds `lcpdf-gui.exe` or pinned script.
4. **Blender 1.0.36** — Fresh enable on Blender 5.1; preferences show Python ABI; Import triggers auto pip or manual Install; PDF import succeeds without external pip.

---

## Commits (this session)

| Repo | Version | Summary |
|------|---------|---------|
| PDF-Importer-SketchUp | 3.7.59 | BOM vertical quantity text anchor + rotation |
| PDF-Importer-Blender | 1.0.36 | PyMuPDF bootstrap for Blender 5.x Python ABI |
| PDF-Importer-LibreCAD | — | Launcher discovery + INSTALL/plugin docs + DXF include_text |
| BlueCollar-Website | — | SketchUp 2017 non-redistribution note |
| PDF-Importer-FreeCAD | — | No change |

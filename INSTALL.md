# How to Use the LibreCAD PDF Importer

This tool converts PDF drawings to DXF files that you can open in LibreCAD, AutoCAD, DraftSight, QCAD, or any DXF-compatible CAD program.

## Canonical install (field testers)

**Use the portable ZIP** (`LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip`) as the single supported path for human confirmation and shop-floor testing. It bundles Python, PyMuPDF, ezdxf, FontTools, pdfcadcore, `lcpdf-gui.exe`, and CLI tools with no Qt or system-Python dependencies.

The native **`pdfimporter1.dll` menu plugin is not supported** on most Windows installs — LibreCAD ships its own Qt runtime and a plugin built against a different Qt kit fails with opaque DLL errors. Do not use the native plugin for release sign-off.

## Quick Start

### Option 0: Portable ZIP — recommended for Windows users
1. Download `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Extract it anywhere you can write files.
3. Run `lcpdf-gui.exe`, or use `pdf2dxf.exe` / `lcpdf-batch.exe` for command-line and batch conversion.

The portable ZIP bundles Python, PyMuPDF, ezdxf, FontTools, pdfcadcore, the GUI, and the
CLI launchers. No system Python, pip, or administrator rights are required.

### Option 0a: Source ZIP fallback
1. Download `LibreCAD-PDF-Importer_vX.Y.Z.zip` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Extract it anywhere you can write files.
3. From that folder:
   ```powershell
   python preflight_check.py --install
   python pdf2dxf.py --gui
   ```
4. `preflight_check.py --install` vendors PyMuPDF, ezdxf, and FontTools into `./lib` (no admin).

Each successful conversion also writes `<output>_import_report.json` beside the DXF
with `text_mode`, `resolved_scale`, `peak_mb`, and raster fallback telemetry.

**Offline install:** The portable ZIP works without internet after download. Source ZIP dev installs may run `preflight_check.py --install` once if `lib/` is empty.

**Scale trust:** use `extra.resolved_scale.factor` only when `confidence >= 0.70` and
`fallback_reason` is not `no_scale_detected`; otherwise set scale manually in your CAD app.

**Bad-PDF gate:** LibreCAD converter refuses encrypted/non-PDF/truncated files at open
(**fail closed**). SketchUp shows the same messages but may proceed on rare gate errors
(**fail open**).

### Option 0b: Standalone installer — when published
When `LibreCAD-PDF-Importer-Setup_vX.Y.Z.exe` appears on Releases, double-click it
(no admin required) and launch **LibreCAD PDF Importer** from the Start menu.

> Build locally: run `python build_standalone.py`, then use the exact
> versioned Inno Setup command it prints. The installer script rejects a
> missing `/DAppVersion=X.Y.Z` instead of silently minting a stale version.

### Option 1: LibreCAD Plugins menu

> **Important:** The native `pdfimporter1.dll` / `bc_lcpdf_menu` plugin is **not**
> recommended on most Windows installs. LibreCAD builds ship with their own Qt
> runtime; a plugin compiled against a different Qt kit (debug vs release, or
> another MSVC version) fails to load with opaque DLL errors. **Use the portable
> ZIP (`lcpdf-gui.exe`) instead** — it bundles Python, PyMuPDF, FontTools, and the GUI with
> no Qt mismatch.

If you still want the menu plugin after installing the portable/source package:

1. Build/install plugin:
```powershell
powershell -ExecutionPolicy Bypass -File .\plugin\build_install_lcpdf_menu.ps1
```
2. Restart LibreCAD
3. Use `Plugins > PDF Importer (BlueCollar)...`

The plugin auto-detects `launch_lcpdf_gui.pyw`, `gui.py`, or portable
`lcpdf-gui.exe` beside LibreCAD or in common install folders. Pin paths via
`Plugins > PDF Importer Settings...`, set `BC_LC_IMPORTER_EXE` for the installed
app, or set `BC_LC_IMPORTER_SCRIPT` for source launches.

### Option 2: Command Line
```bash
python pdf2dxf.py "C:\path\to\drawing.pdf" "C:\output\drawing.dxf"
```

### Option 3: GUI Window (no terminal required)
```bash
python gui.py
```
A window opens where you can browse for a PDF, choose mode + text rendering,
export, and auto-open the DXF in LibreCAD.

### Option 3b: Double-click launcher (Windows, no terminal)
- Double-click `launch_lcpdf_gui.pyw`
- Or install entrypoint and run `lcpdf-guiw`

### Option 4: Batch Convert (multiple files)
```bash
python -m librecad_pdf_importer.batch_cli "C:\folder\with\pdfs"
```

## After Converting

1. In the GUI, keep `Open in LibreCAD after convert` enabled
2. Click `Convert`
3. LibreCAD opens automatically with the generated DXF

## GUI (professional import)

The graphical interface uses **Auto** import only (vector/raster/hybrid chosen per page).

### Before you import (text modes)

- **Text** — native editable DXF `TEXT`, verified as the requested Text semantic.
- **Labels** — editable flat DXF `TEXT` using LibreCAD's parent-native Unicode
  LFF face, with source content and item transform verified after serialization.
- **3D Text** — attempts DXF `TEXT` with thickness and +Z extrusion first;
  native success also requires verified 3D display/edit semantics in the parent.
- **Glyphs** — grouped outline block references.
- **Geometry** — raw outline edges, not editable as text.
- **Raster** — source-bound exact item pixels in a verified DXF `IMAGE`.
- Scale warnings appear in `import_report.json` (`extra.scale_crosscheck` / `human_summary`) when title-block scale is uncertain.

The GUI and CLI expose the same six representation choices. The selected type
is attempted and verified item by item. For Text and Labels, LibreCAD's required
LFF font substitution is recorded as a font substitution—not a change to Glyphs
or Geometry—and DXF FIT alignment preserves the source advance. The result
dialog, log, and complete report show requested and delivered types. Choose
Glyphs or Geometry when exact source-font outlines matter more than editability.

## Modes (BCS-ARCH-001, CLI/batch)

Every mode targets **indistinguishable-from-source** fidelity. Modes differ
only in extraction strategy, not in quality tier.

| Mode | When to Use |
|------|-------------|
| **auto** *(default)* | Picks the right strategy per page automatically |
| **vector** | Clean vector PDFs (CAD exports, shop drawings) |
| **raster** | Scanned or image-only PDFs |
| **hybrid** | Mixed content (vectors + embedded raster) |

### Text Rendering (orthogonal)

GUI and CLI: `text`, `labels`, `3d_text`, `glyphs`, `geometry`, and `raster` as
distinct requests, plus the Import text toggle. Text is native `TEXT`; 3D Text
first attempts native `TEXT` with verified extrusion. DXF has no native Label
entity, so Labels records that exact item-scoped impossibility and then reports
the closest verified Text fallback instead of relabeling TEXT/MTEXT. Glyphs are
grouped block references, Geometry is raw modelspace edges, and requested Raster
is an exact source-item `IMAGE`.

## Requirements

- Standalone installer: no separate Python or pip packages.
- Source/dev checkout: Python 3.10+, PyMuPDF, ezdxf, and FontTools, either installed into
  your active environment or vendored into `./lib` with
  `tools/fetch_runtime_wheels.ps1`.

### One-click dependency check (Windows)

```powershell
python preflight_check.py
python preflight_check.py --install
python pdf2dxf.py --preflight
```

The `--install` flag downloads PyMuPDF, ezdxf, and FontTools into `./lib` with no admin rights required. `--preflight` prints pre-import text-mode and scale-trust guidance without converting a PDF.

Standalone app self-test after install:

```powershell
& "$env:LOCALAPPDATA\Programs\BlueCollar Systems\LibreCAD PDF Importer\LibreCAD-PDF-Importer.exe" --self-test
```

## Troubleshooting

**Black screen when opening DXF?** The importer auto-inverts white lines to black for visibility. If you still see a blank screen, try View > Auto Zoom in LibreCAD.

**Missing text?** Treat that as a failed delivery. Open the complete import
report, compare `text_source_spans` with `text_representation_delivery`, and
inspect the exact source-item attempt. Keep the requested representation while
correcting the source-specific failure.

**Garbled, shifted, rotated, or scaled text?** Do not manually switch the
request to hide it. Attach the complete report and correct placement, rotation,
width, or height inside the requested representation. If the report proves an
item-specific parent-font incompatibility, inspect the automatic fallback; do
not remove its gate or relabel parent-native rendering as source-font-exact.
Keep any same-representation font substitution or Unicode compatibility
normalization visible in the report.

**Plugin menu says launcher not found?** Install the portable ZIP or source
package, then use `Plugins > PDF Importer Settings...` to point at
`LibreCAD-PDF-Importer.exe`, `lcpdf-gui.exe`, or `launch_lcpdf_gui.pyw`. Set
`BC_LC_IMPORTER_EXE` / `BC_LC_IMPORTER_SCRIPT` for custom paths.

**Geometry looks wrong?** Check the per-page resolved strategy and exact entity
evidence in the import report. A strategy change is diagnostic only; it must not
change or weaken the requested output representation.

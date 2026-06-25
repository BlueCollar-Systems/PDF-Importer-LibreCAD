# How to Use the LibreCAD PDF Importer

This tool converts PDF drawings to DXF files that you can open in LibreCAD, AutoCAD, DraftSight, QCAD, or any DXF-compatible CAD program.

## Canonical install (field testers)

**Use the portable ZIP** (`LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip`) as the single supported path for human confirmation and shop-floor testing. It bundles Python, PyMuPDF, ezdxf, pdfcadcore, `lcpdf-gui.exe`, and CLI tools with no Qt or system-Python dependencies.

The native **`pdfimporter1.dll` menu plugin is not supported** on most Windows installs — LibreCAD ships its own Qt runtime and a plugin built against a different Qt kit fails with opaque DLL errors. Do not use the native plugin for release sign-off.

## Quick Start

### Option 0: Portable ZIP — recommended for Windows users
1. Download `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Extract it anywhere you can write files.
3. Run `lcpdf-gui.exe`, or use `pdf2dxf.exe` / `lcpdf-batch.exe` for command-line and batch conversion.

The portable ZIP bundles Python, PyMuPDF, ezdxf, pdfcadcore, the GUI, and the
CLI launchers. No system Python, pip, or administrator rights are required.

### Option 0a: Source ZIP fallback
1. Download `LibreCAD-PDF-Importer_vX.Y.Z.zip` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Extract it anywhere you can write files.
3. From that folder:
   ```powershell
   python preflight_check.py --install
   python pdf2dxf.py --gui
   ```
4. `preflight_check.py --install` vendors PyMuPDF and ezdxf into `./lib` (no admin).

Each successful conversion also writes `<output>_import_report.json` beside the DXF
with `text_mode`, `resolved_scale`, `peak_mb`, and raster fallback telemetry.

**Scale trust:** use `extra.resolved_scale.factor` only when `confidence >= 0.70` and
`fallback_reason` is not `no_scale_detected`; otherwise set scale manually in your CAD app.

**Bad-PDF gate:** LibreCAD converter refuses encrypted/non-PDF/truncated files at open
(**fail closed**). SketchUp shows the same messages but may proceed on rare gate errors
(**fail open**).

### Option 0b: Standalone installer — when published
When `LibreCAD-PDF-Importer-Setup_vX.Y.Z.exe` appears on Releases, double-click it
(no admin required) and launch **LibreCAD PDF Importer** from the Start menu.

> Build locally: `python build_standalone.py` (PyInstaller) + Inno Setup for
> `installer\librecad-pdf-importer.iss`.

### Option 1: LibreCAD Plugins menu

> **Important:** The native `pdfimporter1.dll` / `bc_lcpdf_menu` plugin is **not**
> recommended on most Windows installs. LibreCAD builds ship with their own Qt
> runtime; a plugin compiled against a different Qt kit (debug vs release, or
> another MSVC version) fails to load with opaque DLL errors. **Use the portable
> ZIP (`lcpdf-gui.exe`) instead** — it bundles Python, PyMuPDF, and the GUI with
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

- **Labels (editable TEXT)** — change text in LibreCAD after import.
- **Outlines** — vector stroke fidelity; not editable as TEXT.
- **LibreCAD has no true 3D text** — do not expect SketchUp/FreeCAD 3D-text parity.
- Scale warnings appear in `import_report.json` (`extra.scale_crosscheck` / `human_summary`) when title-block scale is uncertain.

Text options: **Labels (editable TEXT)** or **Outlines** — LibreCAD does not support true 3D text.

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

GUI: Labels (default) · Outlines · plus Import text toggle. CLI also accepts 3d_text and glyphs (mapped to DXF TEXT).

## Requirements

- Standalone installer: no separate Python or pip packages.
- Source/dev checkout: Python 3.10+, PyMuPDF, and ezdxf, either installed into
  your active environment or vendored into `./lib` with
  `tools/fetch_runtime_wheels.ps1`.

### One-click dependency check (Windows)

```powershell
python preflight_check.py
python preflight_check.py --install
python pdf2dxf.py --preflight
```

The `--install` flag downloads PyMuPDF and ezdxf into `./lib` with no admin rights required. `--preflight` prints pre-import text-mode and scale-trust guidance without converting a PDF.

Standalone app self-test after install:

```powershell
& "$env:LOCALAPPDATA\Programs\BlueCollar Systems\LibreCAD PDF Importer\LibreCAD-PDF-Importer.exe" --self-test
```

## Troubleshooting

**Black screen when opening DXF?** The importer auto-inverts white lines to black for visibility. If you still see a blank screen, try View > Auto Zoom in LibreCAD.

**Missing text?** Auto mode should handle text well. If text is missing, try
explicitly `--mode vector` and check the text-rendering setting. GUI default is
**Labels**; CLI default is `labels` (try `glyphs` for symbol-heavy PDFs).

**Garbled/jumbled text outlines?** Switch GUI text mode from **Outlines** to
**Labels (editable TEXT)**. Outline mode vectorizes font strokes and can overlap
on dense BOM tables; Labels export native DXF TEXT with correct rotation.

**Plugin menu says launcher not found?** Install the portable ZIP or source
package, then use `Plugins > PDF Importer Settings...` to point at
`LibreCAD-PDF-Importer.exe`, `lcpdf-gui.exe`, or `launch_lcpdf_gui.pyw`. Set
`BC_LC_IMPORTER_EXE` / `BC_LC_IMPORTER_SCRIPT` for custom paths.

**Geometry looks wrong?** Auto mode should pick the right strategy. If not, try
`--mode vector` for CAD drawings or `--mode hybrid` for PDFs with embedded raster.

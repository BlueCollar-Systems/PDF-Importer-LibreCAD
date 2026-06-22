# How to Use the LibreCAD PDF Importer

This tool converts PDF drawings to DXF files that you can open in LibreCAD, AutoCAD, DraftSight, QCAD, or any DXF-compatible CAD program.

## Quick Start

### Option 0: Standalone installer - no Python needed (recommended for most users)
1. Download `LibreCAD-PDF-Importer-Setup_vX.Y.Z.exe` from [Releases](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD/releases).
2. Double-click it (no admin required) and follow the prompts.
3. Launch **LibreCAD PDF Importer** from the Start menu or desktop.

This build bundles Python, PyMuPDF, ezdxf, pdfcadcore, and the GUI, so you do
**not** need to install Python or any pip packages. It runs on a clean PC,
offline.

> Build it yourself: `python build_standalone.py` (needs PyInstaller), then compile
> `installer\librecad-pdf-importer.iss` with [Inno Setup 6](https://jrsoftware.org/isinfo.php).

### Option 0b: Portable ZIP - no install and no Python needed
1. Download `LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip`.
2. Extract it anywhere you can write files.
3. Double-click `lcpdf-gui.exe`, or run `pdf2dxf.exe` from a terminal.

The portable ZIP bundles CPython, PyMuPDF, ezdxf, and Tkinter into the
executables. It is the simplest fallback for locked-down PCs where installers
are blocked.

### Option 1: LibreCAD Plugins menu
1. Build/install plugin:
```powershell
powershell -ExecutionPolicy Bypass -File .\plugin\build_install_lcpdf_menu.ps1
```
2. Restart LibreCAD
3. Use `Plugins > PDF Importer (BlueCollar)...`

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
```

The `--install` flag downloads PyMuPDF and ezdxf into `./lib` with no admin rights required.

Standalone app self-test after install:

```powershell
& "$env:LOCALAPPDATA\Programs\BlueCollar Systems\LibreCAD PDF Importer\LibreCAD-PDF-Importer.exe" --self-test
```

## Troubleshooting

**Black screen when opening DXF?** The importer auto-inverts white lines to black for visibility. If you still see a blank screen, try View > Auto Zoom in LibreCAD.

**Missing text?** Auto mode should handle text well. If text is missing, try
explicitly `--mode vector` and check the text-rendering setting. `3d_text` is
the default; try `glyphs` for symbol-heavy PDFs.

**Geometry looks wrong?** Auto mode should pick the right strategy. If not, try
`--mode vector` for CAD drawings or `--mode hybrid` for PDFs with embedded raster.

# How to Use the LibreCAD PDF Importer

This tool converts PDF drawings to DXF files that you can open in LibreCAD, AutoCAD, DraftSight, QCAD, or any DXF-compatible CAD program.

## Quick Start

### Option 1: LibreCAD Plugins menu (recommended)
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

## Modes (BCS-ARCH-001)

Every mode targets **indistinguishable-from-source** fidelity. Modes differ
only in extraction strategy, not in quality tier.

| Mode | When to Use |
|------|-------------|
| **auto** *(default)* | Picks the right strategy per page automatically |
| **vector** | Clean vector PDFs (CAD exports, shop drawings) |
| **raster** | Scanned or image-only PDFs |
| **hybrid** | Mixed content (vectors + embedded raster) |

### Text Rendering (orthogonal)

Labels · 3D Text (default) · Glyphs · Geometry · plus an Import text toggle.

## Requirements

- Python 3.10+
- PyMuPDF: `pip install "PyMuPDF>=1.24,<2.0"`
- ezdxf: `pip install ezdxf`

## Troubleshooting

**Black screen when opening DXF?** The importer auto-inverts white lines to black for visibility. If you still see a blank screen, try View > Auto Zoom in LibreCAD.

**Missing text?** Auto mode should handle text well. If text is missing, try
explicitly `--mode vector` and check the text-rendering setting. `3d_text` is
the default; try `glyphs` for symbol-heavy PDFs.

**Geometry looks wrong?** Auto mode should pick the right strategy. If not, try
`--mode vector` for CAD drawings or `--mode hybrid` for PDFs with embedded raster.

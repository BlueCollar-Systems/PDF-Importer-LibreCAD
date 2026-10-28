# Agent guidance — PDF to DXF Converter for LibreCAD

This repository is [BlueCollar-Systems/PDF-Importer-LibreCAD](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD). It converts PDF vector drawings into DXF files for LibreCAD 2.2.x and other 2D CAD applications, with an optional Qt 5 LibreCAD menu plugin (`bc_lcpdf_menu.dll`).

## Worktrees, coordination, and pull requests

- Work in an isolated branch and worktree created from a fresh `origin/main`. Never edit the primary checkout `C:\1PDF-Importer-LibreCAD` directly.
- Coordinate in the owner's Desktop `PDFTest Files\Q&A` folder:
  - Authoritative handoff: `MASTER_HANDOFF_ALL_7_REPOS_2026-10-27.md`
  - Active coordination log: `Achived Q&A\WORKER_STATUS_LOG.md` (append-only; claim before starting and log `DONE` when finished).
- Use pull requests for all changes to `main`. Include `[skip release]` in commit messages for documentation, test, or CI-only changes that do not ship a new converter version.

## Standing product rules

- **2D host honesty:** LibreCAD is a 2D CAD host. Never present a 3D Text request as native 3D output; state the 2D host limitation and follow the documented fallback ladder.
- **Deliver, step down, report (owner ruling 2026-10-05):** One failing item never costs the page or the file. Deliver the page. When one item cannot be delivered in the requested mode, step that item down along the host's finite closest ladder and record every step-down and any item left out in `import_report.json` and the summary.
- **No silent mode switching:** Requested text mode is the deliverable. Fix position, rotation, or scale bugs inside the requested mode rather than switching representations to hide a transform bug.
- **Distribution facts:**
  - The Windows portable release (`LibreCAD-PDF-Importer-Windows-Portable_vX.Y.Z.zip`) ships self-contained `lcpdf-gui.exe`, `lcpdf-import.exe`, and `lcpdf-batch.exe` binaries plus `librecad-plugin/bc_lcpdf_menu.dll` so end users do not need Python installed.
  - When LibreCAD natively saves a DXF, its writer rewrites three fine custom dash patterns to built-in linetypes and adds its 27 standard linetypes.

## Local verification and locks

Run the test suite locally before opening a pull request:

```powershell
python -m pytest tests/ -v
```

- When launching LibreCAD GUI/CLI checks on the shared workstation, acquire the `native-cad` lock via `C:\BlueCollar-Shared\bc_lock.py` (`C:\BlueCollar-Shared\locks`, `--ram-gb 0`) and never terminate another worker's CAD process.
- Store validation artifacts and receipts under `G:\BlueCollar-Test-Results`, never on `D:`.

## Privacy gate (mandatory before commit and push)

Never commit or display customer PDFs, CAD drawings, job numbers, piece marks, company names, or personal paths. Use fictional identifiers (such as `D042-10` or `SYNTHETIC-PRIVATE-DRAWING-ID`) in tests and documentation.

Run the private privacy guard before every commit and push:

```powershell
py -3 -B -I C:\BlueCollar-Private\hooks\privacy_guard.py staged
py -3 -B -I C:\BlueCollar-Private\hooks\privacy_guard.py range origin/main..HEAD
```

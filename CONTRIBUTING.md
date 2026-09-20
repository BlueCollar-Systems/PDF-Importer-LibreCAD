# Contributing — PDF to DXF Converter for LibreCAD

Convert PDF vector drawings to **DXF** for LibreCAD and other DXF CAD. This host is **2D**. Do not advertise fake 3D TEXT; the 3D Text choice must state the 2D host limit. Accuracy over speed hacks; no dropped geometry. Do not drop this host or merge it into another importer runtime.

This repository is [BlueCollar-Systems/PDF-Importer-LibreCAD](https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD). Local folder: `C:\1PDF-Importer-LibreCAD`. Orgs: **BlueCollar-Systems** (this repo) and **BlueCollarSys-0628** (private Tag QC, separate product).

## Full private pack (not in git)

`C:\Users\Rowdy Payton\Desktop\PDFTest Files\Q&A\` — `START_HERE.md`, `ONBOARDING.md`, `COMMUNICATION.md`.

Ask the owner for the hub and Desktop `PDFTest Files` (import outputs live there, e.g. `LC_<sheet>_Imports`). **Do not copy shop PDFs into git.** Communicate in the Q&A hub and with GitHub PRs/issues on this repo. No Slack/Discord.

## Standing rules

- Requested text mode is the deliverable. Wrong position/angle/size is an in-mode transform bug — do not switch representation to hide it. Read `README.md` and `COMPATIBILITY.md`.
- Website badges = **GitHub Releases**, not feature branches.
- Branding: **BlueCollar Systems**. Native CAD on the shop machine uses `C:\TMP\CAD-HOST-GLOBAL.lock`; do not kill another worker’s host.
- Default: no commit/push/release without owner **GO** in the Q&A hub.

```powershell
python -m pytest tests/ -v
```

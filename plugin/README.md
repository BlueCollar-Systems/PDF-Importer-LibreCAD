# LibreCAD Menu Plugin (LC Importer)

This folder contains a native LibreCAD plugin that adds menu entries under
`Plugins`:

- `PDF Importer (BlueCollar)...`
- `PDF Importer Settings...`

The plugin launches the LC importer GUI (`launch_lcpdf_gui.pyw` / `gui.py`)
without opening a terminal window.

## Build + Install (Windows)

1. Ensure Qt 5.15.2 MSVC kit is installed at `C:\Qt\5.15.2\msvc2019_64`.
2. Ensure Visual Studio 2022 Build Tools/Community is installed.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\plugin\build_install_lcpdf_menu.ps1
```

By default this installs the plugin DLL to:

`%USERPROFILE%\Documents\LibreCAD\plugins\bc_lcpdf_menu.dll`

LibreCAD loads plugins from this user folder, so admin rights are not required.

## Runtime Notes

- Script path auto-detection checks:
  - `BC_LC_IMPORTER_SCRIPT` env var
  - `C:/1PDF-Importer-LibreCAD/launch_lcpdf_gui.pyw`
  - `C:/1PDF-Importer-LibreCAD/gui.py`
- Python executable auto-detection checks:
  - `BC_LC_IMPORTER_PYTHON` env var
  - `pythonw`, `python`, `py -3`
- Use `PDF Importer Settings...` to pin explicit script/python paths.


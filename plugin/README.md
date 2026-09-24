# LibreCAD Menu Plugin (`bc_lcpdf_menu.dll`)

Native LibreCAD 2.2.x plugin that adds to LibreCAD's **Plugins** menu:

- `Import PDF (BlueCollar)...` - starts the importer GUI in handoff mode; after a
  successful conversion the DXF opens in the running LibreCAD
  (`QC_ApplicationWindow::slotFileOpen`, the File > Open code path).
- `Import PDF into Current Drawing (BlueCollar)...` - same, but inserts the DXF
  into the current drawing as a block at 0,0 (`Document_Interface::addBlockfromFromdisk`
  + `addInsert`).
- `PDF Importer Settings (BlueCollar)...` - show / pin / reset the importer path.

The plugin never converts anything itself; the unchanged importer GUI does.

## Handoff contract

1. Plugin starts `lcpdf-gui.exe --librecad-handoff <%TEMP%\bc_lcpdf_handoff_*.json>`
   (or `pythonw launch_lcpdf_gui.pyw --librecad-handoff ...` for source checkouts).
2. After a successful export the GUI atomically writes
   `{"schema": 1, "status": "ok", "output_path": "<abs DXF>", ...}`;
   closing the window without a finished drawing writes `{"status": "closed"}`
   (`librecad_pdf_importer/librecad_handoff.py`).
3. The plugin polls that file (and the importer process) behind a modal
   "waiting" dialog with **Stop Waiting**, then opens / inserts the DXF.

## Importer lookup order

1. `BC_LC_IMPORTER_EXE` / `BC_LC_IMPORTER_SCRIPT` environment variables
2. path pinned in *PDF Importer Settings* (`%APPDATA%\LibreCAD\bc_pdf_importer_plugin.ini`)
3. `bc_lcpdf_menu-importer.txt` beside the DLL (written by the installer; the name
   must not contain `.dll`, because LibreCAD tries to load every such file)
4. common portable / install folders (`lcpdf-gui.exe`, `LibreCAD-PDF-Importer.exe`,
   `launch_lcpdf_gui.pyw`)

## ABI / compatibility

LibreCAD 2.2.1.x for Windows is built with **Qt 5.15.2, MSVC, x64, release**, and
loads plugins with `QPluginLoader` from `Documents\LibreCAD\plugins` (among
others). The DLL must therefore be built with the Qt 5.15.2 `msvc2019_64` kit in
release mode. `plugin/sdk/` holds unmodified copies of LibreCAD 2.2.1.5's
`qc_plugininterface.h` and `document_interface.h` (GPL-2.0-or-later).
The build refuses to import `MSVCP140.dll`, so the plugin only needs the C runtime
that any VC++ 2015+ redistributable (including the one LibreCAD installs) provides.
Builds are reproducible (`/Brepro`) because the release gate re-builds the portable
ZIP and compares bytes.

## Build, test, install

```powershell
# Qt kit: --qt-root, $env:LCPDF_QT_ROOT, $env:QT_ROOT_DIR or C:\Qt\5.15.2\msvc2019_64
python scripts\build_librecad_plugin.py            # -> build\librecad-plugin\bc_lcpdf_menu.dll
python scripts\build_librecad_plugin.py --smoke    # + QPluginLoader load test + handoff round trip
python scripts\build_librecad_plugin.py --install  # + copy to Documents\LibreCAD\plugins
```

`plugin/smoke/plugin_smoke.cpp` loads the DLL exactly like LibreCAD
(`QPluginLoader` + `qobject_cast<QC_PluginInterface*>`), checks the menu entries,
and runs `Import PDF (BlueCollar)...` against `plugin/smoke/fake_importer.py`,
asserting the plugin asks the (fake) LibreCAD window to open the handed-back DXF.
CI runs it on `windows-2025` (`lc-pdfimporter-ci.yml`, job `librecad-plugin`), and
the release workflows bundle the DLL with `build_windows_portable.py --librecad-plugin require`.

Diagnostics: set `BC_LCPDF_PLUGIN_TRACE=1` before starting LibreCAD to log each
step to `%TEMP%\bc_lcpdf_menu.log`.

License: GPL-2.0-or-later (see `plugin/package/LICENSE.GPL-2.0.txt`).

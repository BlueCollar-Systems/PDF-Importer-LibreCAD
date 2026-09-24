BlueCollar PDF Importer - LibreCAD menu entry
=============================================

bc_lcpdf_menu.dll adds these entries to LibreCAD's Plugins menu:

  Plugins > Import PDF (BlueCollar)...
      Opens the PDF Importer window. Pick the PDF, text mode and options,
      press Convert. When the conversion finishes the DXF opens in LibreCAD.
  Plugins > Import PDF into Current Drawing (BlueCollar)...
      Same, but the DXF is inserted into the open drawing as a block at 0,0.
  Plugins > PDF Importer Settings (BlueCollar)...
      Shows / changes which importer the menu entry starts.
  Tools > Import PDF (BlueCollar)...
      Same as the first entry.

Install (once)
--------------
1. Close LibreCAD.
2. Run lcpdf-gui.exe from this folder's parent and press
   "Install LibreCAD menu entry...". This copies bc_lcpdf_menu.dll to
   Documents\LibreCAD\plugins (no administrator rights needed) and records
   where lcpdf-gui.exe lives.
   Manual alternative: copy bc_lcpdf_menu.dll into Documents\LibreCAD\plugins.
3. Start LibreCAD and open the Plugins menu.

Keep the portable folder where it is after installing; the menu entry starts
lcpdf-gui.exe from that folder. If you move it, press the install button again.

Compatibility
-------------
Built for LibreCAD 2.2.x for Windows, 64-bit (Qt 5.15, MSVC), verified with
LibreCAD 2.2.1.5. Other LibreCAD builds (Qt 6 based 2.3/3.x development
builds, MinGW builds) cannot load it; use lcpdf-gui.exe directly there.
Plugin menu entries are greyed out until a drawing window is open
(LibreCAD opens a blank drawing at start-up by default).

License
-------
The plugin is GPL-2.0-or-later (it implements LibreCAD's GPL plugin
interface); see LICENSE.GPL-2.0.txt. Its source is in the plugin/ folder of
the source ZIP and at https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD
The importer itself stays under the licenses listed in THIRD_PARTY_LICENSES.md.

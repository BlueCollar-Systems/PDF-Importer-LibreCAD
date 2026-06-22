# Third-Party Licenses — LibreCAD PDF Importer (standalone build)

This installer bundles the third-party components below so the app runs on any
Windows PC with no separate installs. Each component is the property of its
authors and is distributed under its own license.

| Component | Version | License | Source |
|---|---|---|---|
| CPython | bundled by PyInstaller | PSF License | https://www.python.org/ |
| PyMuPDF (embeds MuPDF) | >=1.24,<2.0 | AGPL-3.0 (or Artifex commercial) | https://github.com/pymupdf/PyMuPDF — https://mupdf.com/ |
| ezdxf | >=1.0 | MIT | https://github.com/mozman/ezdxf |
| Tcl/Tk (Tkinter) | bundled with CPython | Tcl/Tk (BSD-style) | https://www.tcl.tk/ |

## AGPL-3.0 notice (PyMuPDF / MuPDF)

This product includes PyMuPDF, which embeds MuPDF, licensed under the GNU Affero
General Public License v3.0. In accordance with the AGPL, the corresponding
source code for the bundled components is available at the URLs above. Keep
this notice with each installer/portable release, and publish a
`third-party-source` release asset when mirroring exact upstream source archives
for a release. The BlueCollar Systems importer source is published at:
https://github.com/BlueCollar-Systems/PDF-Importer-LibreCAD

If you need a build without AGPL components, contact BlueCollar Systems about a
commercially-licensed (Artifex) variant.

## The importer itself

The LibreCAD PDF Importer source authored by BlueCollar Systems is released under
the MIT License (see LICENSE). Because the distributed bundle includes AGPL
components, the bundle **as a whole** is offered under AGPL-3.0 terms; the
original BlueCollar source remains MIT.

# Third-Party Licenses — LibreCAD PDF Importer

The standalone installer and portable ZIP bundle the third-party components
below so the app runs on any Windows PC with no separate installs. Each
component is the property of its authors and is distributed under its own
license.

| Component | Version | License | Source |
|---|---|---|---|
| CPython | bundled by PyInstaller | PSF License | https://www.python.org/ |
| PyMuPDF (embeds MuPDF) | >=1.24,<2.0 | AGPL-3.0 (or Artifex commercial) | https://github.com/pymupdf/PyMuPDF — https://mupdf.com/ |
| ezdxf | >=1.1 | MIT | https://github.com/mozman/ezdxf |
| FontTools | >=4.50,<5.0 | MIT | https://github.com/fonttools/fonttools |
| Matplotlib (`ezdxf.addons.text2path` runtime) | >=3.7,<4.0 | PSF-based Matplotlib license | https://github.com/matplotlib/matplotlib |
| NumPy (ezdxf dependency) | resolved at build | BSD-3-Clause and bundled notices | https://github.com/numpy/numpy |
| pyparsing (ezdxf dependency) | resolved at build | MIT | https://github.com/pyparsing/pyparsing |
| typing_extensions (ezdxf dependency) | resolved at build | PSF-2.0 | https://github.com/python/typing_extensions |
| PyInstaller + build dependencies | resolved at build | upstream licenses, including bootloader exception | https://github.com/pyinstaller/pyinstaller |
| Tcl/Tk (Tkinter) | bundled with CPython | Tcl/Tk (BSD-style) | https://www.tcl.tk/ |

The exact FontTools notices accompany every frozen/portable artifact at
`licenses/FontTools/LICENSE` and `licenses/FontTools/LICENSE.external`. The
primary MIT notice is Copyright (c) 2017 Just van Rossum; the external notice
preserves the SIL Open Font License terms for upstream test-font material.

Every frozen/portable artifact also contains
`licenses/PYTHON_DISTRIBUTIONS.md`, `licenses/python-distributions.json`, and
the exact license files exposed by every distribution in its isolated build
environment. The inventory deliberately includes PyInstaller and its build
dependencies as well as runtime libraries, preventing transitive dependencies
or bootloader terms from becoming an undocumented release assumption.

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

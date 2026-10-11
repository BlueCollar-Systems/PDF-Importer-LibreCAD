# Actual LibreCAD saved drawing regression

`mm-merged-native-saved.dxf` is an unchanged, fictional DXF2007 drawing written
by the actual Windows LibreCAD 2.2.1.5 / Qt 5.15.2 application. The native
operator opened the early saved-copy mm control, used Auto Zoom, Save As,
closed it, and reopened the saved path. It contains a 100 mm control line
and synthetic vector shapes from `01-vector-only.pdf`; it contains
no customer drawing, private text, local paths, email address, or image file.

The original is retained at
`C:\TMP\librecad-native-gui-20261011\mm-merged-native-saved.dxf`.
The repository fixture is byte-identical, 38,505 bytes, SHA256
`ad44217f5923a9d6f1c2fb6c4de191913cc6a7c76f445e48c8257effdf47abcd`.
The source synthetic PDF SHA256 is
`8806b7974fe43b9fc91662f11ff9f7b10aa3424e6c711792ff81a15b2d0a47dc`.
The native host executable SHA256 is
`9b5ec58c40c9e88b2fc110678f03c5b071191cd8dd79b3c68d6620b269c03773`.

Its actual serialization exposed drawing-local material/plotstyle handle
transport, optional default spelling, and VPORT/STYLE owner aliases on a
second PDF import. Tests read this frozen input without rewriting it and
check preserved base handles, nondefault geometry/paint, and table membership.
They do not launch LibreCAD or claim final portable visual acceptance.

`02-text-paint-raster.pdf` is the unchanged deterministic public synthetic PDF
used to reproduce a second import with fresh converter output. It embeds
glyph text, a white panel, colored paths and a fictional checker image; it has
no customer data. Its metadata names BlueCollar Systems synthetic test and
uses a fixed 2000 timestamp. SHA256:
`16c7ec56ce5146a81dffa117a3ee9eeaffae6d3d2841ec01599b4d51fd3ae5cc`.
The fresh DXF's built-in CONTINUOUS description is empty, while the actual
native base's equivalent description is `Solid line`. This descriptive label
does not alter its empty continuous pattern or built-in role.

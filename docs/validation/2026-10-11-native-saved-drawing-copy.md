# LibreCAD saved drawing copy import

The actual LibreCAD 2.2.1.5 Windows process crashed with access violation
`c0000005` after the original **Import PDF into Current Drawing** handoff.
Root's native check identified the faulting module as `LibreCAD.exe`, offset
`0x61a4a`, executable SHA256
`9b5ec58c40c9e88b2fc110678f03c5b071191cd8dd79b3c68d6620b269c03773`.
The owned base DXF remained unchanged; no native save result was created.

Both bundled plugin SDK headers match the official v2.2.1.5 tag commit
`7ebab007d9eb4c68609388b835a2487648f0877b` byte for byte. The official
[block import implementation](https://github.com/LibreCAD/LibreCAD/blob/7ebab007d9eb4c68609388b835a2487648f0877b/librecad/src/main/doc_plugin_interface.cpp)
clones entities and blocks from a temporary drawing. Its
[reparent method](https://github.com/LibreCAD/LibreCAD/blob/7ebab007d9eb4c68609388b835a2487648f0877b/librecad/src/lib/engine/rs_entity.h)
only updates the parent pointer, while
[insert updating](https://github.com/LibreCAD/LibreCAD/blob/7ebab007d9eb4c68609388b835a2487648f0877b/librecad/src/lib/engine/rs_insert.cpp)
later dereferences the cloned source layer. This is a source-confirmed unsafe
lifetime path consistent with the observed crash; the fault offset was not
symbolized, and a bundled-header ABI mismatch was not found.

The plugin now exposes **Import PDF into Saved Drawing Copy**. The operator
saves current edits and selects that DXF. The GUI names the saved base, says
the original is kept, and proposes a new output filename. The runtime merges
the converted PDF into an editable outer block at 0,0, with explicit unit
conversion. The complete new DXF opens normally; the official
[Auto Zoom slot](https://github.com/LibreCAD/LibreCAD/blob/7ebab007d9eb4c68609388b835a2487648f0877b/librecad/src/ui/qg_actionhandler.h)
runs after native File Open returns. No document SDK cloning or clipboard
transfer is used. Existing output and either input are always refused as
destinations. The PDF-only DXF and its full conversion report remain in a
separately identified import folder, including when a later merge fails.

Resource copying uses the installed ezdxf 1.4.4
[Loader](https://ezdxf.readthedocs.io/en/stable/xref.html). Layers, styles,
linetypes, image definitions and nested blocks are isolated from the base's
resources. Layer 0 and DEFPOINTS require explicit isolation because the
loader keeps those defaults. Effective paint order is materialized in every
incoming layout before loading because Loader omits SORTENTSTABLE. Deep
semantic digests check geometry, fill boundaries, clipping, decoded image
identity, text and resolved resources; shared block definitions are hashed
once. Existing base entities/resources, dictionary links, headers,
dimensions, paperspace and draw order are independently protected.

Both inputs' images pass the existing byte/pixel-checked drawing-copy
publisher. The final DXF uses portable relative links to one newly created
image folder. Keep that folder with the DXF; native LibreCAD Save As alone
does not transport image files. Private merge cleanup removes only matching
file IDs, content hashes and directory IDs, without recursive removal of
foreign/replaced folders. The persistent PDF-only workspace is pinned during
conversion on Windows. Saved-copy export uses no-overwrite publication and
protects both its local and outer asset rollback with ownership receipts.

The route requires known drawing units and a base saved as DXF2007 or newer.
The output format may advance to the converted PDF's DXF version; only that
format's matching ACADMAINTVER is changed as version metadata. Unit and
dimension settings stay strict. External XREFs, unproven proxies, unresolved
or cyclic blocks and nesting beyond 32 produce an actionable error. There is
no arbitrary stored-record count cap by default. A computed render budget of
one million repeated entities is protected by a visible **Allow very large
merged drawings (may be slow)** choice. The graph walk and digests remain
linear for shared blocks; a 536,870,912-leaf DAG is tested without materializing
its leaves or opening it in a native program.

Focused source checks cover mm/inch/meter units, exact mm-to-inch factor,
conflicting nested glyph/style/dash/layer resources, frozen hidden text,
top/nested paint order, two clipped/rotated image sets, dimensions/paperspace,
R2007-to-R2010 transport, input hashes, cancellation, late competing output,
changed input, replaced stage and replaced staged image, failed workspace pin
construction, standalone flags and GUI worker handoff. The focused integration
run passed 226 checks; Python 3.9 grammar checks passed for all eight changed
runtime modules. Existing spline/source paint/asset tests are included. The
full repository suite is pending at this source freeze. Functional/bugbear
lint, the core sync manifest and the 1.0.107 version consistency check pass.

Root's early source-only mm and inch merged controls opened and Auto Zoom
displayed the original base line and vector fixture correctly without a crash.
Both passed native Save As to DXF2007, close, and reopening of the saved path.
Those historical controls are not final portable acceptance. The rebuilt
DLL's actual menu/picker/handoff/Auto Zoom flow, cold portable runtime and
small-window GUI checks remain Root's required final gates.

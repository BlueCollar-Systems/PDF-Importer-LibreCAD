# Repeated import into actual LibreCAD saved drawings

The first v1.0.107 source freeze passed its generated-base tests, but an
independent replay against an actual LibreCAD-saved base correctly prevented
publication: it compared drawing-local material/Normal plotstyle handles as
paint, then compared native explicit defaults and table-owner aliases as
literal transport. No input or existing output was overwritten.

The frozen public regression input is documented in
`tests/fixtures/librecad-2.2.1.5/README.md`. It is a byte-identical 38,505-byte
fictional DXF2007 written and reopened by actual LibreCAD 2.2.1.5, SHA256
`ad44217f5923a9d6f1c2fb6c4de191913cc6a7c76f445e48c8257effdf47abcd`.
It was inspected for private text and local paths before inclusion. Tests
read it without rewriting it or launching the host.

Incoming layers now resolve MATERIAL and Normal ACDBPLACEHOLDER references.
Their serialized content is compared with only resource identity/ownership
transport removed. Material names may namespace; the special Global,
ByLayer and ByBlock roles remain explicit. Actual color, opacity and mapper
matrices remain checked. Missing or unsupported references fail actionably.
Resolved references are cached once per resource, retaining the bounded
shared-block digest behavior. The installed primary
[layer mapper](https://github.com/mozman/ezdxf/blob/v1.4.4/src/ezdxf/entities/layer.py)
confirms material rebinding and Normal plotstyle replacement.

Existing base records use the writer's declared optional-default rules via
TagCollector(optional=False), rather than treating omitted default spelling
as a geometry change. Nondefault tags and entity handles remain strict.
Only actual VPORT/STYLE table members may normalize the native writer's
LAYER-table owner alias to their proven table owner; arbitrary owner changes
fail. The primary
[namespace exporter](https://github.com/mozman/ezdxf/blob/v1.4.4/src/ezdxf/entities/dxfns.py)
defines which explicit defaults the writer omits.

Cached EXTMIN/EXTMAX may synchronize only to the independently protected
modelspace LAYOUT bounds, matching the primary
[document writer](https://github.com/mozman/ezdxf/blob/v1.4.4/src/ezdxf/document.py).
Drawing units, dimensions and active VPORT settings stay strict. LibreCAD's
GRIDMODE and SNAPSTYLE integer header flags are explicitly preserved by a
document-local header exporter wrapper because ezdxf 1.4.4 does not register
them. They are not ignored: the official
[LibreCAD graphic](https://github.com/LibreCAD/LibreCAD/blob/7ebab007d9eb4c68609388b835a2487648f0877b/librecad/src/lib/engine/rs_graphic.cpp)
defaults missing GRIDMODE to on, so dropping an explicit off value would
change behavior. The wrapper is restored after writing and fails if the
expected header terminal is not encountered. No global definitions change.

The actual native fixture passes a repeated import containing two clipped,
rotated images, a conflicting nested glyph block, fixed white/black vectors
and frozen search text. Reopened output keeps all protected base records,
units, native grid flags and portable image bytes; original inputs stay
unchanged. An independent exact replay of that actual native base with the
previously native-validated white-panel source also publishes and reopens
through the parser, retaining original model handles, units and both grid
flags. This is serialization evidence, not an additional native visual pass.
Negative controls reject nondefault material color/opacity/matrix,
base color/geometry/width/scale/owner/view changes, unresolved plotstyle,
native grid flags, units, dimensions and arbitrary header bounds.

Saved-copy banner, image-location and large-drawing controls are also wired
when standalone receives the saved-drawing flag without a plugin handoff.
Windowless widget tests cover that route and the normal plugin route; the
standalone launch checkbox stays available, and copy-tool controls do not
occupy the saved-copy image row. Actual rebuilt package acceptance remains
with the native operator; these source tests do not substitute for it.

The later frozen-runtime PDF02 replay exposed one additional descriptive
transport difference: fresh CONTINUOUS has an empty description, while the
native base's equivalent built-in record says `Solid line`. Both records have
flags 0 and the identical empty pattern `(72,65), (73,0), (40,0.0)`. An
independent in-memory replay confirmed that this one label explains the
entire top-level and nested digest difference. Incoming CONTINUOUS comparison
now retains an explicit built-in role and every pattern/flag element, while
allowing this descriptive label to differ. The base's original description
remains strictly protected; custom descriptions and role/pattern/flag changes
remain rejected. The unchanged public PDF02 fixture drives an actual CLI
conversion plus native-base merge regression without launching the host.
The earlier r5 refusal and outputs remain historical evidence; they do not
become final package acceptance through this source repair.

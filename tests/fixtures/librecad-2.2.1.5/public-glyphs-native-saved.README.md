This is a public fictional glyph/vector control, saved by the actual LibreCAD
2.2.1.5 Windows GUI as DXF 2007 on 2026-10-13. It contains no user's drawing,
private font program, source PDF paths, or external raster asset.
The fictional test content and generated DXF fixture are licensed under this
repository's MIT license. It includes vector outlines, not an embedded font
program. Local paths, author/user names and printer/configuration filenames were
checked: none are present, so the original native-save bytes remain unchanged.
The source was the agent-generated public `synthetic.pdf` mixed text/vector
control (SHA-256 `c250425db064ca0a0eeedd46a1f4ec8248fe3f3229fbc67bfb762bb28f4c02d0`),
converted in Glyphs mode by the compiled 1.0.108 candidate. The conversion DXF
before the native save has SHA-256
`e30bb8e058aaf823affde3790686150081cb982f2f7cc2fcd23c62e96a2727f0`.

`public-glyphs-native-saved.dxf` SHA-256:
`02a19de450536731d0409ea04a05a1fc648a5812641cbfabd4da4ffa83abaf69`.

The native writer leaves inactive layer plotstyle handle F dangling while the
valid sole Normal/default dictionary is present at different handles. The real
HEADER drawing limits also differ from the modelspace LAYOUT's default paper
limits. Tests preserve both original records and all geometry/material/resource
guards when using this saved drawing as either merge input.

The fixture includes the native writer's orphan PLOTSETTINGS object 1F4. Its
original bytes are retained as diagnostic evidence. This repair does not certify
that native save as free of all DXF audit findings, nor does it delete that object
or ignore geometry, material or active named-style failures.

Primary writer source:
https://github.com/LibreCAD/LibreCAD/blob/v2.2.1.5/libraries/libdxfrw/src/libdxfrw.cpp#L255-L294

Primary mode definition (1=color dependent; 0=named styles):
https://help.autodesk.com/cloudhelp/2020/ENG/AutoCAD-Core/files/GUID-2D0D1C41-60E6-4FD0-AB63-28475EE82633.htm

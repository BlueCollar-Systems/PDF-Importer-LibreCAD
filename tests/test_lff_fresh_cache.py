import os
from pathlib import Path
import dxf_text_builder as builder

def test_fresh_read_reuses_only_identical_bytes_and_refreshes_provenance(tmp_path):
    font = tmp_path / 'unicode.lff'
    font.write_bytes(b'# Format: LibreCAD Font 1\n[0041]\n0,0;1,1\n')
    arguments = dict(executable_path='test-app', executable_resolution_source='test', installation_root=str(tmp_path), fresh=True)
    builder.reset_text_styles()
    first = builder._parse_librecad_lff(font, 'first-source', **arguments)
    second = builder._parse_librecad_lff(font, 'current-source', **arguments)
    assert first.verified and second.verified
    assert second.glyph_codepoints is first.glyph_codepoints
    assert second.drawable_codepoints is first.drawable_codepoints
    assert second.resolution_source == 'current-source'
    stamp = font.stat()
    font.write_bytes(font.read_bytes().replace(b'[0041]', b'[0042]'))
    os.utime(font, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    changed = builder._parse_librecad_lff(font, 'changed-source', **arguments)
    assert changed.sha256 != first.sha256
    assert changed.glyph_codepoints == frozenset({0x42})
    assert changed.drawable_codepoints == frozenset({0x42})

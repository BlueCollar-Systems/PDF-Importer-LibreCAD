"""Native CONTINUOUS labels can differ while the painted pattern stays identical."""
from hashlib import sha256
from pathlib import Path
import sys

import ezdxf
import pytest

from librecad_pdf_importer import cli, drawing_insert as module
from librecad_pdf_importer.drawing_copy import DrawingCopyError

FIXTURES = Path(__file__).parent / 'fixtures/librecad-2.2.1.5'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def test_fresh_mixed_pdf_glyphs_merge_into_actual_native_saved_drawing(tmp_path, monkeypatch):
    base, pdf = FIXTURES / 'mm-merged-native-saved.dxf', FIXTURES / '02-text-paint-raster.pdf'
    assert digest(base) == 'ad44217f5923a9d6f1c2fb6c4de191913cc6a7c76f445e48c8257effdf47abcd'
    assert digest(pdf) == '16c7ec56ce5146a81dffa117a3ee9eeaffae6d3d2841ec01599b4d51fd3ae5cc'
    before = digest(base), digest(pdf)
    incoming, target = tmp_path / 'fresh-mixed.dxf', tmp_path / 'repeated-copy.dxf'
    # Embedded glyph contours need no host font assets. No host launch or fake
    # installation is used; this invokes the actual conversion CLI boundary.
    monkeypatch.setattr(cli, 'find_librecad_executable', lambda path: None)
    monkeypatch.setattr(sys, 'argv', ['lcpdf-import', str(pdf), '--out', str(incoming),
                                   '--mode', 'vector', '--text-mode', 'glyphs'])
    assert cli.main() == 0
    original = ezdxf.readfile(base)
    source = ezdxf.readfile(incoming)
    assert source.linetypes.get('CONTINUOUS').dxf.description == ''
    assert original.linetypes.get('CONTINUOUS').dxf.description == 'Solid line'
    protected = module._base_state(original)
    result = module.insert_into_saved_drawing_copy(base, incoming, target)
    reopened = ezdxf.readfile(target)
    module._check_base_state(reopened, protected)
    assert reopened.linetypes.get('CONTINUOUS').dxf.description == 'Solid line'
    assert reopened.units == 4 and result.insertion_scale == 1
    assert result.image_files == 1
    assert any(layer.is_frozen() and layer.dxf.name.endswith('TEXT_SEARCH') for layer in reopened.layers)
    assert (digest(base), digest(pdf)) == before


def small_pair(tmp_path, *, custom=False, changed=None):
    base, incoming = tmp_path / 'base.dxf', tmp_path / 'incoming.dxf'
    doc = ezdxf.new('R2010'); doc.units = 4
    doc.linetypes.get('CONTINUOUS').dxf.description = 'Solid line'
    doc.modelspace().add_line((0, 0), (100, 0)); doc.saveas(base)
    source = ezdxf.new('R2010'); source.units = 4
    name = 'CONTINUOUS'
    if custom:
        name = 'CUSTOM_DASH'
        source.linetypes.new(name, dxfattribs={'description': 'Source custom label', 'pattern': [2, 1, -1]})
    elif changed == 'pattern':
        source.linetypes.get(name).setup_pattern([2, 1, -1])
    elif changed == 'flags':
        source.linetypes.get(name).dxf.flags = 64
    source.modelspace().add_line((0, 0), (10, 10), dxfattribs={'linetype': name})
    source.saveas(incoming)
    return base, incoming


@pytest.mark.parametrize('changed', ['pattern', 'flags'])
def test_builtin_label_normalization_does_not_allow_painted_pattern_or_flag_loss(tmp_path, changed):
    base, incoming = small_pair(tmp_path, changed=changed)
    before = digest(base), digest(incoming)
    target = tmp_path / 'copy.dxf'
    with pytest.raises(DrawingCopyError, match='could not preserve'):
        module.insert_into_saved_drawing_copy(base, incoming, target)
    assert not target.exists() and (digest(base), digest(incoming)) == before


@pytest.mark.parametrize('changed', ['builtin_role', 'custom_description'])
def test_actual_role_and_custom_description_changes_stay_strict(tmp_path, monkeypatch, changed):
    base, incoming = small_pair(tmp_path, custom=changed == 'custom_description')
    before = digest(base), digest(incoming)
    target = tmp_path / 'copy.dxf'
    semantic = module._semantic_digest
    calls = []

    def alter_loaded(entities, document):
        records = list(entities)
        calls.append(True)
        if len(calls) == 2:
            if changed == 'builtin_role':
                records[0].dxf.linetype = 'BYLAYER'
            else:
                document.linetypes.get(records[0].dxf.linetype).dxf.description = 'Changed custom label'
        return semantic(records, document)

    monkeypatch.setattr(module, '_semantic_digest', alter_loaded)
    with pytest.raises(DrawingCopyError, match='could not preserve'):
        module.insert_into_saved_drawing_copy(base, incoming, target)
    assert not target.exists() and (digest(base), digest(incoming)) == before

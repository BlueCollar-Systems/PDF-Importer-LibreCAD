"""Independent original-tag and physical native-print regression assertions."""
import base64
from hashlib import sha256
import json
from pathlib import Path

import ezdxf

from librecad_pdf_importer import drawing_insert as merge


def physical_callbacks(path):
    """Pinned native constructor defaults and ordered code6/40..43 callbacks."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records, current = [], []
    for code, value in zip(lines[::2], lines[1::2], strict=True):
        code = int(code)
        if code == 0 and current:
            records.append(current)
            current = []
        current.append((code, value))
    if current:
        records.append(current)
    section, callbacks = None, []
    for record in records:
        kind = record[0][1]
        if kind == "SECTION":
            section = next(value for code, value in record if code == 2)
        elif kind == "ENDSEC":
            section = None
        elif section == "OBJECTS" and kind == "PLOTSETTINGS":
            row = {"handle": None, "plot_view_name": "", "margins_mm": [0.0] * 4}
            for code, value in record:
                if code == 5:
                    row["handle"] = value
                elif code == 6:
                    row["plot_view_name"] = value
                elif code in {40, 41, 42, 43}:
                    row["margins_mm"][code - 40] = float(value)
            callbacks.append(row)
    return callbacks


def bind_print_rehome(result, original_base, expected_base, physical, base_path, incoming_path):
    """Derive only330/name1 from original tags; never recapture a baseline."""
    archive = result.native_plot_settings_rehome
    assert archive["schema"] == "bcs.native_plot_settings_rehome/1.0"
    assert archive["record_count"] == 1 and archive["original_inputs_unchanged"] is True
    assert [row["role"] for row in archive["documents"]] == ["base", "incoming"]
    for row, path, original in zip(archive["documents"], (base_path, incoming_path),
            (original_base, ezdxf.readfile(incoming_path)), strict=True):
        assert row["original_input_sha256"] == sha256(Path(path).read_bytes()).hexdigest()
        plots = [entity for entity in original.objects if entity.dxftype() == "PLOTSETTINGS"]
        assert len(row["records"]) == len(plots)
        for plan, entity in zip(row["records"], plots, strict=True):
            handle = str(entity.dxf.handle)
            assert plan["handle"] == handle and plan["physical_and_parsed_incoming_references"] == 0
            tags = merge._base_state(original)[handle]
            dictionary = original.rootdict["ACAD_PLOTSETTINGS"]
            owner, name = str(dictionary.dxf.handle), "Saved drawing print setup"
            assert name not in dictionary
            assert tags.count((330, "0")) == tags.count((1, "")) == 1
            assert plan["dictionary_handle"] == owner and plan["setup_name"] == name
            assert plan["only_permitted_delta"] == {
                "owner_group330": {"before": "0", "after": owner},
                "setup_name_group1": {"before": "", "after": name},
                "standard_dictionary_entry_added": {name: handle}}
            after = [(code, owner if code == 330 else name if code == 1 else value) for code, value in tags]
            assert plan["parsed_before_tags_sha256"] == merge._state_hash(tags)
            assert plan["parsed_after_tags_sha256"] == merge._state_hash(after)
            raw = base64.b64decode(plan["physical_record_bytes_base64"], validate=True)
            assert raw in Path(path).read_bytes() and sha256(raw).hexdigest() == plan["physical_record_sha256"]
            if row["role"] == "base":
                assert expected_base[handle] == tags
                expected_base[handle] = after
                final_dictionary = physical.rootdict["ACAD_PLOTSETTINGS"]
                entries = {key: str(value.dxf.handle) for key, value in dictionary.items()}
                entries[name] = handle
                assert {key: str(value.dxf.handle) for key, value in final_dictionary.items()} == entries
                assert physical.entitydb[handle].dxf.owner == owner
    callbacks = physical_callbacks(base_path)
    assert physical_callbacks(result.drawing) == callbacks
    assert archive["print_callback_proof"]["original_base_ordered_callbacks"] == callbacks
    assert archive["print_callback_proof"]["expected_final_ordered_callbacks"] == callbacks
    stored = [json.loads("".join(tag.value for tag in record.tags))
        for key, record in physical.rootdict.items() if key.endswith("_PLOT_REHOME_LEDGER")]
    assert stored == [archive]
    audit = ezdxf.readfile(result.drawing).audit()
    assert not audit.errors and not audit.fixes
    return expected_base

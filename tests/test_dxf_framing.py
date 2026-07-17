"""DXF header/viewport framing for LibreCAD auto-zoom."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ezdxf

from pdfcadcore.import_config import ImportConfig
from pdfcadcore.primitives import NormalizedText, PageData, Primitive, reset_ids

from dxf_builder import build_dxf
from pdfcadcore.primitive_extractor import _merge_stacked_fractions


class TestDxfFraming(unittest.TestCase):
    def setUp(self) -> None:
        reset_ids()
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "framing.dxf"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _sample_page(self) -> PageData:
        return PageData(
            page_number=1,
            width=200.0,
            height=100.0,
            primitives=[
                Primitive(
                    id=1,
                    type="line",
                    points=[(10.0, 10.0), (150.0, 80.0)],
                    page_number=1,
                )
            ],
            text_items=[
                NormalizedText(
                    id=2,
                    text="LABEL",
                    normalized="LABEL",
                    insertion=(20.0, 70.0),
                    bbox=(18.0, 68.0, 40.0, 72.0),
                    font_size=3.0,
                    font_name="BCS Deterministic Test",
                    advance_width=22.0,
                    page_number=1,
                )
            ],
            layers=[],
            xobject_names=[],
        )

    def test_build_dxf_sets_extents_and_vport(self) -> None:
        doc, _, _ = build_dxf([self._sample_page()], ImportConfig.auto())
        doc.saveas(str(self.out))

        loaded = ezdxf.readfile(str(self.out))
        self.assertEqual(loaded.header.get("$INSUNITS"), 4)
        self.assertIsNotNone(loaded.header.get("$EXTMIN"))
        self.assertIsNotNone(loaded.header.get("$EXTMAX"))

        msp = loaded.modelspace()
        extmin = tuple(float(v) for v in msp.dxf.extmin)
        extmax = tuple(float(v) for v in msp.dxf.extmax)
        self.assertLess(extmin[0], extmax[0])
        self.assertLess(extmin[1], extmax[1])

        active = loaded.viewports.get("*Active")
        self.assertTrue(active)
        self.assertGreater(float(active[0].dxf.height), 0.0)

    def test_geometry_text_exports_outlines_not_text(self) -> None:
        config = ImportConfig.auto()
        config.text_mode = "geometry"

        doc, _, text_count = build_dxf([self._sample_page()], config)
        doc.saveas(str(self.out))

        self.assertGreater(text_count, 0)
        loaded = ezdxf.readfile(str(self.out))
        types = {entity.dxftype() for entity in loaded.modelspace()}
        self.assertNotIn("TEXT", types)
        self.assertNotIn("MTEXT", types)
        self.assertTrue({"LWPOLYLINE", "POLYLINE"}.intersection(types))

    def test_horizontal_fraction_merge(self) -> None:
        merged = _merge_stacked_fractions([
            NormalizedText(
                id=1, text="3", normalized="3",
                insertion=(10.0, 20.0), bbox=(9.5, 19.5, 11.0, 20.5),
                font_size=2.0, page_number=1,
            ),
            NormalizedText(
                id=2, text="/", normalized="/",
                insertion=(12.0, 20.0), bbox=(11.8, 19.5, 12.5, 20.5),
                font_size=2.0, page_number=1,
            ),
            NormalizedText(
                id=3, text="4", normalized="4",
                insertion=(14.0, 20.0), bbox=(13.5, 19.5, 15.0, 20.5),
                font_size=2.0, page_number=1,
            ),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].text, "3/4")


if __name__ == "__main__":
    unittest.main(verbosity=2)

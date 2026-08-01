from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ezdxf

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:
    import fitz  # Legacy fallback

from librecad_pdf_importer.exporters.dxf_exporter import (
    DxfExportOptions,
    export_to_dxf,
)
from librecad_pdf_importer.importer import run_import


POINT_TO_MM = 25.4 / 72.0


class TestXObjectImageAffineDelivery(unittest.TestCase):
    """Exercise real XObject extraction and serialized DXF IMAGE geometry."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lc_xobject_affine_test_")
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _opaque_asymmetric_image() -> bytes:
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 3), 0)
        colors = (
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 0, 255),
            (0, 255, 255),
        )
        for y in range(3):
            for x in range(2):
                pixmap.set_pixel(x, y, colors[y * 2 + x])
        return bytes(pixmap.tobytes("png"))

    def _build_reused_xobject_pdf(
        self,
        output: Path,
        *,
        page_width: float,
        page_height: float,
        matrices: tuple[tuple[float, float, float, float, float, float], ...],
    ) -> None:
        document = fitz.open()
        page = document.new_page(width=page_width, height=page_height)
        page.insert_image(
            fitz.Rect(1, 1, 21, 31),
            stream=self._opaque_asymmetric_image(),
        )
        image_info = page.get_images(full=True)
        if len(image_info) != 1:
            raise RuntimeError("synthetic page did not create exactly one XObject resource")
        resource_name = str(image_info[0][7])
        operations = []
        for matrix in matrices:
            values = " ".join(f"{value:g}" for value in matrix)
            operations.append(f"q {values} cm /{resource_name} Do Q\n")
        content_xref = document.get_new_xref()
        document.update_object(content_xref, "<<>>")
        document.update_stream(content_xref, "".join(operations).encode("ascii"))
        page.set_contents(content_xref)
        document.save(output)
        document.close()

    @staticmethod
    def _resolve_image_asset(drawing: ezdxf.document.Drawing, image) -> Path:
        image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
        path = Path(str(image_definition.dxf.filename))
        if not path.is_absolute():
            path = Path(str(drawing.filename)).resolve().parent / path
        return path.resolve()

    def test_rotated_mirrored_and_skewed_opaque_xobjects_keep_affine_geometry(
        self,
    ) -> None:
        # Each tuple is the literal PDF image CTM (a, b, c, d, e, f).
        # The first four are 0/90/180/270 degrees, followed by a horizontal
        # mirror and a skew. A correct PDF-to-DXF Y flip leaves these exact
        # basis vectors and origin in the bottom-left DXF model space.
        matrices = (
            (40.0, 0.0, 0.0, 30.0, 20.0, 150.0),
            (0.0, 40.0, -30.0, 0.0, 100.0, 130.0),
            (-40.0, 0.0, 0.0, -30.0, 160.0, 150.0),
            (0.0, -40.0, 30.0, 0.0, 170.0, 130.0),
            (-40.0, 0.0, 0.0, 30.0, 260.0, 150.0),
            (40.0, 10.0, 12.0, 30.0, 20.0, 80.0),
        )
        source = self.tmp_path / "opaque-xobject-affines.pdf"
        output = self.tmp_path / "opaque-xobject-affines.dxf"
        self._build_reused_xobject_pdf(
            source,
            page_width=300,
            page_height=200,
            matrices=matrices,
        )

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
        )
        try:
            placements = run.extraction.pages[0].images
            self.assertEqual(len(placements), len(matrices))
            for placement, matrix in zip(placements, matrices, strict=True):
                a, b, c, d, e, f = matrix
                expected_model = tuple(
                    value * POINT_TO_MM for value in (e, f, a, b, c, d)
                )
                self.assertEqual(placement.source_kind, "xobject_image")
                self.assertEqual(placement.pixel_size, (2, 3))
                self.assertEqual(placement.alpha_kind, "opaque")
                self.assertFalse(placement.alpha_present)
                self.assertIsNotNone(placement.affine_pdf)
                self.assertIsNotNone(placement.affine_model)
                for actual, expected in zip(
                    placement.affine_model,
                    expected_model,
                    strict=True,
                ):
                    self.assertAlmostEqual(actual, expected, places=9)

            export_to_dxf(
                run.extraction,
                str(output),
                DxfExportOptions(
                    include_text=False,
                    dxf_version="R2010",
                    provenance_opts=run.config,
                ),
            )
        finally:
            run.close()

        drawing = ezdxf.readfile(output)
        images = list(drawing.modelspace().query("IMAGE"))
        self.assertEqual(len(images), len(matrices))
        for image, matrix in zip(images, matrices, strict=True):
            a, b, c, d, e, f = matrix
            expected_insert = (e * POINT_TO_MM, f * POINT_TO_MM)
            expected_u_pixel = (a * POINT_TO_MM / 2.0, b * POINT_TO_MM / 2.0)
            expected_v_pixel = (c * POINT_TO_MM / 3.0, d * POINT_TO_MM / 3.0)
            for actual, expected in zip(
                tuple(image.dxf.insert)[:2],
                expected_insert,
                strict=True,
            ):
                self.assertAlmostEqual(actual, expected, places=9)
            for actual, expected in zip(
                tuple(image.dxf.u_pixel)[:2],
                expected_u_pixel,
                strict=True,
            ):
                self.assertAlmostEqual(actual, expected, places=9)
            for actual, expected in zip(
                tuple(image.dxf.v_pixel)[:2],
                expected_v_pixel,
                strict=True,
            ):
                self.assertAlmostEqual(actual, expected, places=9)
            image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
            self.assertEqual(
                tuple(
                    round(value)
                    for value in tuple(image_definition.dxf.image_size)[:2]
                ),
                (2, 3),
            )
            delivered = fitz.Pixmap(str(self._resolve_image_asset(drawing, image)))
            self.assertFalse(delivered.alpha)

    def test_page_rotation_composes_with_xobject_affine_before_model_y_flip(
        self,
    ) -> None:
        expected_points = {
            0: (80.0, 60.0, 80.0, 0.0, 0.0, 120.0),
            90: (60.0, 240.0, 0.0, -80.0, 120.0, 0.0),
            180: (240.0, 180.0, -80.0, 0.0, 0.0, -120.0),
            270: (180.0, 80.0, 0.0, 80.0, -120.0, 0.0),
        }
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = self.tmp_path / f"page-rotate-{rotation}-xobject.pdf"
                output = self.tmp_path / f"page-rotate-{rotation}-xobject.dxf"
                document = fitz.open()
                page = document.new_page(width=200.0, height=140.0)
                page.insert_image(
                    fitz.Rect(60.0, 40.0, 100.0, 100.0),
                    stream=self._opaque_asymmetric_image(),
                )
                page.set_cropbox(fitz.Rect(20.0, 10.0, 180.0, 130.0))
                page.set_rotation(rotation)
                document.xref_set_key(page.xref, "UserUnit", "2")
                document.save(source)
                document.close()

                expected = tuple(
                    value * POINT_TO_MM for value in expected_points[rotation]
                )

                run = run_import(
                    str(source),
                    mode="vector",
                    overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
                )
                try:
                    placements = run.extraction.pages[0].images
                    self.assertEqual(len(placements), 1)
                    placement = placements[0]
                    self.assertIsNotNone(placement.affine_model)
                    for actual, wanted in zip(
                        placement.affine_model,
                        expected,
                        strict=True,
                    ):
                        self.assertAlmostEqual(actual, wanted, places=9)
                    export_to_dxf(
                        run.extraction,
                        str(output),
                        DxfExportOptions(
                            include_text=False,
                            dxf_version="R2010",
                            provenance_opts=run.config,
                        ),
                    )
                finally:
                    run.close()

                drawing = ezdxf.readfile(output)
                images = list(drawing.modelspace().query("IMAGE"))
                self.assertEqual(len(images), 1)
                image = images[0]
                insert_x, insert_y, u_x, u_y, v_x, v_y = expected
                for actual, wanted in zip(
                    tuple(image.dxf.insert)[:2],
                    (insert_x, insert_y),
                    strict=True,
                ):
                    self.assertAlmostEqual(actual, wanted, places=9)
                for actual, wanted in zip(
                    tuple(image.dxf.u_pixel)[:2],
                    (u_x / 2.0, u_y / 2.0),
                    strict=True,
                ):
                    self.assertAlmostEqual(actual, wanted, places=9)
                for actual, wanted in zip(
                    tuple(image.dxf.v_pixel)[:2],
                    (v_x / 3.0, v_y / 3.0),
                    strict=True,
                ):
                    self.assertAlmostEqual(actual, wanted, places=9)

    def test_high_density_reused_xobject_routes_to_terminal_fidelity_tiles(
        self,
    ) -> None:
        source = self.tmp_path / "dense-reused-xobject.pdf"
        output = self.tmp_path / "dense-reused-xobject.dxf"
        matrices = tuple(
            (6.0, 0.0, 0.0, 6.0, 4.0 + column * 9.0, 4.0 + row * 9.0)
            for row in range(17)
            for column in range(17)
        )
        self.assertEqual(len(matrices), 289)
        self._build_reused_xobject_pdf(
            source,
            page_width=160,
            page_height=160,
            matrices=matrices,
        )

        run = run_import(
            str(source),
            mode="vector",
            overrides={"pages": "1", "raster_dpi": 72, "import_text": False},
        )
        try:
            placements = run.extraction.pages[0].images
            self.assertEqual(len(placements), 1)
            marker = placements[0]
            self.assertEqual(
                marker.source_kind,
                "xobject_image_page_fidelity_required",
            )
            self.assertEqual(marker.source_instance_count, 289)
            self.assertEqual(marker.path, "")
            self.assertEqual(marker.pixel_size, (160, 160))

            with patch(
                "librecad_pdf_importer.exporters.dxf_exporter.TERMINAL_TILE_PIXELS",
                64,
            ):
                result = export_to_dxf(
                    run.extraction,
                    str(output),
                    DxfExportOptions(
                        include_text=False,
                        dxf_version="R2010",
                        provenance_opts=run.config,
                    ),
                )
        finally:
            run.close()

        drawing = ezdxf.readfile(output)
        images = list(drawing.modelspace().query("IMAGE"))
        self.assertEqual(result.image_count, 9)
        self.assertEqual(len(images), 9)
        self.assertEqual({str(image.dxf.layer) for image in images}, {"P001_IMAGES"})
        self.assertEqual(
            {
                (
                    round(float(image.dxf.insert.x), 9),
                    round(float(image.dxf.insert.y), 9),
                )
                for image in images
            },
            {
                (round(x * POINT_TO_MM, 9), round(y * POINT_TO_MM, 9))
                for x in (0.0, 64.0, 128.0)
                for y in (0.0, 32.0, 96.0)
            },
        )
        delivered_pixel_sizes = set()
        for image in images:
            image_definition = drawing.entitydb.get(str(image.dxf.image_def_handle))
            delivered_pixel_sizes.add(
                tuple(
                    round(value)
                    for value in tuple(image_definition.dxf.image_size)[:2]
                )
            )
            delivered = fitz.Pixmap(str(self._resolve_image_asset(drawing, image)))
            self.assertFalse(delivered.alpha)
            self.assertLessEqual(delivered.width, 64)
            self.assertLessEqual(delivered.height, 64)
        self.assertEqual(
            delivered_pixel_sizes,
            {(64, 64), (32, 64), (64, 32), (32, 32)},
        )


if __name__ == "__main__":
    unittest.main()

"""Generate redistributable PDF importer stress fixtures from original primitives.

Nothing from customer or project drawings is read. The generated files contain
only deterministic geometric shapes, invented labels, and a programmatic raster.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def _raster_fixture() -> bytes:
    image = Image.new("RGBA", (96, 64), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((3, 3, 92, 60), fill=(244, 249, 255, 230), outline=(8, 46, 82, 255), width=3)
    draw.line((8, 52, 44, 14, 88, 52), fill=(210, 43, 43, 255), width=4)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _engineering_pdf(path: Path) -> None:
    document = fitz.open()

    page = document.new_page(width=612, height=792)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(42, 42, 570, 750))
    shape.draw_line(fitz.Point(90, 650), fitz.Point(510, 180))
    shape.draw_circle(fitz.Point(150, 260), 22)
    shape.finish(color=(0, 0, 0), width=1.2)
    shape.commit()
    page.insert_text((72, 96), "SYNTHETIC FRAME A-101", fontsize=16)
    page.insert_text((115, 640), "12'-6 3/8\"", fontsize=13, rotate=0)
    page.insert_text((470, 235), "45 DEG", fontsize=11, rotate=90)

    page = document.new_page(width=792, height=612)
    page.set_rotation(90)
    page.draw_rect(fitz.Rect(80, 80, 710, 530), color=(0, 0, 0), width=1)
    page.insert_text((105, 120), "ROTATED PAGE / CLIPPED DETAIL", fontsize=15)
    page.insert_textbox(
        fitz.Rect(105, 160, 360, 214),
        "MULTILINE NOTE\nNO CUSTOMER CONTENT",
        fontsize=12,
        align=fitz.TEXT_ALIGN_CENTER,
    )

    page = document.new_page(width=612, height=792)
    page.insert_text((72, 92), "TRANSPARENCY AND RASTER ASSET", fontsize=15)
    page.insert_image(fitz.Rect(90, 140, 474, 396), stream=_raster_fixture(), keep_proportion=False)
    page.draw_line(fitz.Point(90, 430), fitz.Point(474, 430), color=(0, 0, 1), width=2)
    page.insert_text((90, 465), "VECTOR TEXT BELOW EMBEDDED PNG", fontsize=12)

    document.set_metadata(
        {
            "title": "BlueCollar PDF Importer Synthetic Acceptance Fixture",
            "author": "BlueCollar Systems test generator",
            "subject": "Generated-only CC0 conformance input",
        }
    )
    document.save(path, garbage=4, deflate=True)
    document.close()


def _blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page(width=612, height=792)
    document.save(path, garbage=4, deflate=True)
    document.close()


def generate_corpus(output_directory: Path) -> Path:
    output = output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)

    engineering = output / "engineering_multimode.pdf"
    blank = output / "blank_page.pdf"
    malformed = output / "malformed_input.pdf"
    _engineering_pdf(engineering)
    _blank_pdf(blank)
    malformed.write_bytes(b"%PDF-1.7\nsynthetic-truncated-object\n")

    manifest = {
        "schema_version": 1,
        "license": "CC0-1.0",
        "generated_only": True,
        "provenance": (
            "Produced entirely by scripts/generate_public_synthetic_corpus.py; "
            "contains no customer, project, or private PDF content."
        ),
        "cases": {
            "engineering_multimode": {
                "file": engineering.name,
                "expect": ["three_pages", "page_rotation", "vector_text", "embedded_rgba_png"],
            },
            "blank_page": {"file": blank.name, "expect": ["one_page", "zero_ink"]},
            "malformed_input": {"file": malformed.name, "expect": ["clean_parse_failure"]},
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    print(generate_corpus(args.output_directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

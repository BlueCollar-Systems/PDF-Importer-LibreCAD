"""Native alpha IMAGE paint for separately certified final PDF rectangles."""
from __future__ import annotations

import hashlib
import json
import math

import pymupdf as fitz

APPID = "BCS_FINAL_RECT_PAINT"


def render_uniform_source_paint(rgb, opacity):
    """Use the PDF renderer's premultiplied color quantization, not RGB tinting."""
    values = (*rgb, opacity)
    if len(rgb) != 3 or not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
        raise ValueError("Final source paint color or opacity is invalid")
    if not 0 < opacity < 1:
        raise ValueError("Final source alpha must be translucent")
    with fitz.open() as pdf:
        page = pdf.new_page(width=16, height=16)
        page.draw_rect(page.rect, color=None, fill=tuple(rgb), fill_opacity=opacity)
        pix = page.get_pixmap(colorspace=fitz.csRGB, alpha=True)
        samples = bytes(pix.samples)
        if not pix.alpha or pix.width != 16 or pix.height != 16:
            raise RuntimeError("Final paint renderer returned an unexpected image")
        if samples != samples[:4] * 256 or not 0 < samples[3] < 255:
            raise RuntimeError("Final paint renderer did not produce uniform source alpha")
        png = pix.tobytes("png")
    return png, {"renderer": fitz.VersionBind, "pixel_size": [16, 16],
                 "premultiplied_rgba8": list(samples[:4]),
                 "decoded_samples_sha256": hashlib.sha256(samples).hexdigest()}


def bind_metadata(entity, record):
    if APPID not in entity.doc.appids:
        entity.doc.appids.add(APPID)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"))
    entity.set_xdata(APPID, [(1000, encoded[i:i+240]) for i in range(0, len(encoded), 240)])
    return encoded


def stroke_snapshot(entity):
    if entity.dxftype() != "LWPOLYLINE" or not entity.closed:
        raise RuntimeError("Certified final rectangle has no closed native stroke")
    return {"handle": str(entity.dxf.handle),
            "points": tuple(tuple(p) for p in entity.get_points()),
            "attrs": {key: entity.dxf.get(key, default) for key, default in
                      (("layer", "0"), ("color", 256), ("true_color", None),
                       ("lineweight", -1), ("linetype", "BYLAYER"), ("invisible", 0))}}


def image_style_snapshot(entity):
    return {key: entity.dxf.get(key, default) for key, default in
            (("layer", "0"), ("flags", 3), ("clipping", 0), ("brightness", 50),
             ("contrast", 50), ("fade", 0), ("invisible", 0))}


def verify_metadata_and_strokes(doc, records):
    for record in records:
        image = doc.entitydb.get(record["image_handle"])
        if image is None or image.dxftype() != "IMAGE":
            raise RuntimeError("Serialized final paint image is missing")
        if "".join(tag.value for tag in image.get_xdata(APPID)) != record["metadata_json"]:
            raise RuntimeError("Serialized final source paint identity changed")
        if image_style_snapshot(image) != record["image_style"]:
            raise RuntimeError("Serialized final source paint display changed")
        layer = doc.layers.get(image.dxf.layer)
        if layer.is_off() or layer.is_frozen():
            raise RuntimeError("Serialized final source paint layer became hidden")
        for expected in record["strokes"]:
            entity = doc.entitydb.get(expected["handle"])
            if entity is None or stroke_snapshot(entity) != expected:
                raise RuntimeError("Serialized final source stroke changed")

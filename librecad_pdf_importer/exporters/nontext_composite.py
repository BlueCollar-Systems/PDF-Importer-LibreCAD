"""Identity and native visibility checks for local source blending displays."""
import json

from .final_rect_paint import image_style_snapshot

APPID = 'BCS_NONTEXT_COMPOSITE'


def bind_metadata(image, record):
    if APPID not in image.doc.appids:
        image.doc.appids.add(APPID)
    encoded = json.dumps(record, sort_keys=True, separators=(',', ':'))
    image.set_xdata(APPID, [(1000, encoded[i:i+240]) for i in range(0, len(encoded), 240)])
    return dict(handle=str(image.dxf.handle), metadata=encoded, style=image_style_snapshot(image))


def verify_display_metadata(doc, records):
    for record in records:
        image = doc.entitydb.get(record['handle'])
        if image is None or image.dxftype() != 'IMAGE' or not image.has_xdata(APPID):
            raise RuntimeError('Source blend display or identity is missing')
        if ''.join(tag.value for tag in image.get_xdata(APPID)) != record['metadata']:
            raise RuntimeError('Source blend display identity changed')
        if image_style_snapshot(image) != record['style'] or image.dxf.transparency:
            raise RuntimeError('Source blend display appearance changed')
        if any(vector.z != 0 for vector in (image.dxf.insert, image.dxf.u_pixel, image.dxf.v_pixel)):
            raise RuntimeError('Source blend display left the original page plane')
        layer = doc.layers.get(image.dxf.layer)
        if layer.is_off() or layer.is_frozen():
            raise RuntimeError('Source blend display layer is hidden')

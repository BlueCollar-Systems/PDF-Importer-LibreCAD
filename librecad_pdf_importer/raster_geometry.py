"""Map rendered PDF pixel bounds with the source page affine, not font metrics."""
import math


def source_raster_bounds(item):
    """Cover original glyph quads as well as the renderer's span bbox.

    A font's dictionary bbox can be slightly shorter than its actual source
    glyph quad. Keeping both avoids clipping the top of a rendered glyph while
    leaving the original source bbox and the model's affine mapping unchanged.
    """
    bounds = getattr(item, "source_bbox_pdf", None)
    if bounds is None:
        return None
    x0, y0, x1, y1 = (float(value) for value in bounds)
    points = [(x0, y0), (x1, y1)]
    layouts = getattr(item, "source_char_layout", ()) or ()
    quads = [getattr(char, "source_quad_pdf", None) for char in layouts]
    if not layouts:
        quads = [getattr(item, "source_quad_pdf", None)]
    for quad in quads:
        if quad is None:
            continue
        if len(quad) != 4:
            raise ValueError("Raster source glyph quad must have four corners")
        points.extend((float(x), float(y)) for x, y in quad)
    if not all(math.isfinite(value) for point in points for value in point):
        raise ValueError("Raster source glyph coverage is not finite")
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


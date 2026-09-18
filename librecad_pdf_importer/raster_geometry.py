"""Map rendered PDF pixel bounds with the source page affine, not font metrics."""
import math


def display_to_model_matrix(page_rect, scale, flip_y):
    """Bind rendered page coordinates to model units, independently of text."""
    unit = (25.4 / 72.0) * float(scale)
    height = float(page_rect.height)
    if not math.isfinite(unit) or unit <= 0 or not math.isfinite(height) or height <= 0:
        raise ValueError("Raster page mapping requires finite positive scale and height")
    return (unit, 0.0, 0.0, -unit if flip_y else unit,
            0.0, height * unit if flip_y else 0.0)


def raster_pixel_geometry(origin, size, dpi, display_to_model, offset_y=0.0):
    """Map MuPDF's actual outward-rounded device lattice to DXF IMAGE axes.

    MuPDF pixels are indexed from the top left; DXF IMAGE V points from its
    bottom left toward its top left. No semantic text bounds enter this map.
    """
    if len(origin) != 2 or len(size) != 2 or len(display_to_model) != 6:
        raise ValueError("Raster pixel mapping is incomplete")
    if any(isinstance(v, bool) or int(v) != v for v in (*origin, *size)):
        raise ValueError("Raster device origin and dimensions must be integers")
    if min(size) <= 0:
        raise ValueError("Raster device dimensions must be positive")
    a, b, c, d, e, f = map(float, display_to_model)
    zoom = float(dpi) / 72.0
    if not all(math.isfinite(v) for v in (a, b, c, d, e, f, zoom, offset_y)):
        raise ValueError("Raster page mapping is not finite")
    if zoom <= 0 or abs(a * d - b * c) <= 1e-30:
        raise ValueError("Raster page mapping is singular")
    x, y = float(origin[0]) / zoom, float(origin[1] + size[1]) / zoom
    insert = (a*x+c*y+e, b*x+d*y+f+offset_y)
    u = (a/zoom, b/zoom)
    v = (-c/zoom, -d/zoom)
    corners = [(insert[0]+i*u[0]+j*v[0], insert[1]+i*u[1]+j*v[1])
               for i, j in ((0, 0), (size[0], 0), (size[0], size[1]), (0, size[1]))]
    return {"pixel_origin": list(origin), "pixel_size": list(size),
            "display_to_model": list(display_to_model), "export_page_offset_y": offset_y,
            "image_insert": list(insert), "image_u_pixel": list(u), "image_v_pixel": list(v),
            "image_corners_model": [list(p) for p in corners],
            "target_bbox_model": [min(p[0] for p in corners), min(p[1] for p in corners),
                                  max(p[0] for p in corners), max(p[1] for p in corners)]}


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

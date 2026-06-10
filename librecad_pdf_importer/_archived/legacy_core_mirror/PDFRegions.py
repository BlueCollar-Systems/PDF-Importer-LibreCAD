# -*- coding: utf-8 -*-
# PDFRegions.py — Region segmentation
# BlueCollar Systems — BUILT. NOT BOUGHT.
from __future__ import annotations
from .PDFPrimitives import Region, PageData, next_id


def segment(page_data: PageData, config=None) -> list:
    """Split page into logical detail regions using spatial clustering."""
    prims = page_data.primitives
    if not prims:
        return []

    gap = 50.0  # mm — cluster gap threshold
    cell = gap * 3

    # Grid-based clustering
    cells = {}
    for p in prims:
        if not p.bbox: continue
        cx = (p.bbox[0]+p.bbox[2])/2
        cy = (p.bbox[1]+p.bbox[3])/2
        key = (int(cx/cell), int(cy/cell))
        cells.setdefault(key, []).append(p)

    # Union-find
    parent = {k:k for k in cells}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def unite(a,b):
        ra,rb = find(a),find(b)
        if ra!=rb: parent[ra]=rb

    for key in cells:
        gx,gy = key
        for dx in range(-1,2):
            for dy in range(-1,2):
                nb = (gx+dx,gy+dy)
                if nb in cells: unite(key,nb)

    groups = {}
    for key, ps in cells.items():
        root = find(key)
        groups.setdefault(root,[]).extend(ps)

    regions = []
    for cluster in groups.values():
        if len(cluster) < 3: continue
        xs = [v for p in cluster for v in (p.bbox[0],p.bbox[2]) if p.bbox]
        ys = [v for p in cluster for v in (p.bbox[1],p.bbox[3]) if p.bbox]
        if not xs: continue
        bbox = (min(xs),min(ys),max(xs),max(ys))
        r = Region(id=next_id(), page_number=page_data.page_number,
            bbox=bbox, primitive_ids=[p.id for p in cluster],
            region_type="unknown", label=f"Region_{len(regions)}")
        regions.append(r)

    _classify(regions, page_data)
    return regions


def _classify(regions, page_data):
    ph = page_data.height
    for r in regions:
        if not r.bbox: continue
        # Title block: bottom of page, wide
        if r.bbox[1] < ph * 0.15 and r.bbox[3] < ph * 0.3:
            r.is_titleblock = True
            r.region_type = "title_block"
            r.label = "TitleBlock"
            r.confidence = 0.80
        elif len(r.primitive_ids) > 50:
            r.region_type = "assembly"
            r.label = "Assembly"
        else:
            r.region_type = "detail"
            r.label = f"Detail_{r.id}"


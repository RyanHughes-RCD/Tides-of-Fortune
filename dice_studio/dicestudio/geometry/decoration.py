"""Procedural face decoration and controlled randomisation.

A *design* is a flat dict of parameters (see DESIGN_SCHEMA).  A set shares a
family design generated from (seed, style, density); each die may add a
variant that re-rolls a subset of keys, so dice look related but not
identical.  Locked keys are never changed by randomisation.

Decorations are generated as 2D shapes in each face's local frame, so every
pattern automatically follows the face's own symmetry (triangle, square,
pentagon, kite).  All shapes are then constrained to the region where a cut
of the given depth cannot break through a neighbouring face, are kept clear
of the numerals, and are filtered for printable feature width.
"""
from __future__ import annotations

import math
import random

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon

from .text import as_multipolygon, polygons_of

STYLES = {
    "modern_gothic": "Modern Gothic",
    "geometric": "Geometric",
    "art_deco": "Art Deco",
    "crystalline": "Crystalline",
    "futuristic_mechanical": "Futuristic Mechanical",
}

BORDER_STYLES = ["none", "groove", "double_groove", "ridge", "step"]
RING_SHAPES = ["follow", "rotated", "diamond", "circle"]
CORNER_MOTIFS = ["none", "diamond", "chevron", "dot", "triangle", "notch", "arrow"]
RADIAL_MOTIFS = ["none", "starburst", "rays", "spokes"]
RADIAL_COUNTS = ["vertices", "edges", "both"]
RELIEFS = ["recessed", "raised"]

DESIGN_SCHEMA = [
    dict(key="edge_chamfer_mm", label="Edge chamfer width (mm)", type="float", min=0.0, max=1.2, step=0.05, group="Shape"),
    dict(key="vertex_trunc_mm", label="Vertex truncation (mm)", type="float", min=0.0, max=2.0, step=0.05, group="Shape"),
    dict(key="d10_elongation", label="D10/D100 elongation", type="float", min=0.8, max=1.35, step=0.01, group="Shape"),
    dict(key="size_scale", label="Set size scale", type="float", min=0.9, max=1.12, step=0.01, group="Shape"),
    dict(key="border_style", label="Face border", type="choice", choices=BORDER_STYLES, group="Border"),
    dict(key="border_inset_mm", label="Border inset (mm)", type="float", min=0.3, max=1.6, step=0.05, group="Border"),
    dict(key="border_width_mm", label="Border width (mm)", type="float", min=0.35, max=1.0, step=0.05, group="Border"),
    dict(key="relief_depth_mm", label="Pattern depth / height (mm)", type="float", min=0.2, max=0.7, step=0.05, group="Border"),
    dict(key="inner_rings", label="Nested polygons", type="int", min=0, max=3, step=1, group="Pattern"),
    dict(key="ring_shape", label="Nested polygon shape", type="choice", choices=RING_SHAPES, group="Pattern"),
    dict(key="ring_gap_mm", label="Nested polygon spacing (mm)", type="float", min=0.4, max=1.4, step=0.05, group="Pattern"),
    dict(key="corner_motif", label="Corner motif", type="choice", choices=CORNER_MOTIFS, group="Pattern"),
    dict(key="corner_size", label="Corner motif size", type="float", min=0.5, max=1.6, step=0.05, group="Pattern"),
    dict(key="radial_motif", label="Radial motif", type="choice", choices=RADIAL_MOTIFS, group="Pattern"),
    dict(key="radial_count", label="Radial directions", type="choice", choices=RADIAL_COUNTS, group="Pattern"),
    dict(key="motif_relief", label="Motif relief", type="choice", choices=RELIEFS, group="Pattern"),
    dict(key="line_width_mm", label="Line width (mm)", type="float", min=0.35, max=0.8, step=0.05, group="Pattern"),
]
SCHEMA_BY_KEY = {s["key"]: s for s in DESIGN_SCHEMA}
VARIANT_KEYS = ["corner_motif", "radial_motif", "radial_count", "inner_rings", "ring_shape", "motif_relief"]

# style -> weighted choices / ranges
_STYLE_RULES = {
    "modern_gothic": dict(
        border_style={"double_groove": 3, "groove": 2, "ridge": 2, "step": 1},
        ring_shape={"follow": 3, "rotated": 2},
        corner_motif={"chevron": 4, "arrow": 3, "triangle": 2},
        radial_motif={"none": 2, "rays": 2, "starburst": 1},
        motif_relief={"recessed": 3, "raised": 1},
        edge_chamfer_mm=(0.3, 0.7), vertex_trunc_mm=(0.0, 0.0), d10_elongation=(1.05, 1.3),
    ),
    "geometric": dict(
        border_style={"groove": 3, "double_groove": 1, "none": 1},
        ring_shape={"follow": 2, "rotated": 3, "diamond": 2},
        corner_motif={"diamond": 3, "triangle": 2, "dot": 1, "none": 1},
        radial_motif={"none": 3, "spokes": 1},
        motif_relief={"recessed": 3, "raised": 1},
        edge_chamfer_mm=(0.0, 0.3), vertex_trunc_mm=(0.0, 0.0), d10_elongation=(0.9, 1.15),
    ),
    "art_deco": dict(
        border_style={"step": 2, "double_groove": 3, "ridge": 1},
        ring_shape={"follow": 3, "circle": 1, "rotated": 1},
        corner_motif={"chevron": 2, "diamond": 2, "arrow": 1},
        radial_motif={"starburst": 5, "rays": 2},
        motif_relief={"recessed": 2, "raised": 2},
        edge_chamfer_mm=(0.2, 0.5), vertex_trunc_mm=(0.0, 0.0), d10_elongation=(1.0, 1.2),
    ),
    "crystalline": dict(
        border_style={"groove": 2, "none": 2, "ridge": 1},
        ring_shape={"rotated": 3, "diamond": 2},
        corner_motif={"diamond": 3, "triangle": 3, "none": 1},
        radial_motif={"starburst": 3, "rays": 2, "none": 1},
        motif_relief={"recessed": 2, "raised": 1},
        edge_chamfer_mm=(0.4, 0.9), vertex_trunc_mm=(0.4, 1.1), d10_elongation=(1.1, 1.35),
    ),
    "futuristic_mechanical": dict(
        border_style={"double_groove": 2, "groove": 2, "step": 2},
        ring_shape={"follow": 4, "rotated": 1},
        corner_motif={"notch": 4, "dot": 2, "diamond": 1},
        radial_motif={"spokes": 3, "rays": 2, "none": 1},
        motif_relief={"recessed": 3, "raised": 1},
        edge_chamfer_mm=(0.5, 1.0), vertex_trunc_mm=(0.0, 0.6), d10_elongation=(0.95, 1.15),
    ),
}


def _wchoice(rng, weights):
    keys = list(weights)
    tot = sum(weights.values())
    r = rng.random() * tot
    for k in keys:
        r -= weights[k]
        if r <= 0:
            return k
    return keys[-1]


def _q(x, step):
    return round(round(x / step) * step, 4)


def generate_design(seed, style, density, base=None, locks=()):
    """Generate a family design.  Keys in ``locks`` keep their value from ``base``."""
    if style not in _STYLE_RULES:
        raise ValueError(f"unknown style {style!r}")
    density = float(min(max(density, 0.0), 1.0))
    rng = random.Random(f"family:{seed}:{style}:{density:.3f}")
    rules = _STYLE_RULES[style]
    d = {}
    d["edge_chamfer_mm"] = _q(rng.uniform(*rules["edge_chamfer_mm"]), 0.05)
    tr = rules["vertex_trunc_mm"]
    d["vertex_trunc_mm"] = _q(rng.uniform(*tr), 0.05) if tr[1] > 0 else 0.0
    d["d10_elongation"] = _q(rng.uniform(*rules["d10_elongation"]), 0.01)
    d["size_scale"] = 1.0
    d["border_style"] = _wchoice(rng, rules["border_style"])
    d["border_inset_mm"] = _q(rng.uniform(0.45, 0.9), 0.05)
    d["border_width_mm"] = _q(rng.uniform(0.4, 0.7), 0.05)
    d["relief_depth_mm"] = _q(rng.uniform(0.3, 0.55), 0.05)
    d["inner_rings"] = int(min(3, max(0, round(rng.uniform(-0.6, 1.2) + 2.2 * density))))
    d["ring_shape"] = _wchoice(rng, rules["ring_shape"])
    d["ring_gap_mm"] = _q(rng.uniform(0.5, 0.9), 0.05)
    d["corner_motif"] = _wchoice(rng, rules["corner_motif"]) if rng.random() < 0.35 + 0.65 * density else "none"
    d["corner_size"] = _q(rng.uniform(0.8, 1.25), 0.05)
    d["radial_motif"] = _wchoice(rng, rules["radial_motif"]) if rng.random() < 0.2 + 0.8 * density else "none"
    d["radial_count"] = rng.choice(RADIAL_COUNTS)
    d["motif_relief"] = _wchoice(rng, rules["motif_relief"])
    d["line_width_mm"] = _q(rng.uniform(0.4, 0.6), 0.05)
    if density < 0.15:
        d["inner_rings"] = 0
        d["radial_motif"] = "none"
    if base:
        for k in locks:
            if k in base:
                d[k] = base[k]
    return validate_design(d)


def die_variant(design, seed, die, variant, locks=()):
    """Return the design for one die: the family design, re-rolled on VARIANT_KEYS for variant > 0."""
    d = dict(design)
    if not variant:
        return d
    rng = random.Random(f"variant:{seed}:{die}:{variant}")
    for k in VARIANT_KEYS:
        if k in locks:
            continue
        s = SCHEMA_BY_KEY[k]
        if s["type"] == "choice":
            d[k] = rng.choice(s["choices"])
        elif s["type"] == "int":
            d[k] = rng.randint(s["min"], s["max"])
    return validate_design(d)


def validate_design(d):
    out = {}
    for s in DESIGN_SCHEMA:
        k = s["key"]
        if k not in d:
            raise ValueError(f"design is missing {k!r}")
        v = d[k]
        if s["type"] == "choice":
            if v not in s["choices"]:
                raise ValueError(f"{s['label']}: {v!r} is not one of {s['choices']}")
        elif s["type"] == "int":
            v = int(v)
            if not (s["min"] <= v <= s["max"]):
                raise ValueError(f"{s['label']} must be between {s['min']} and {s['max']}")
        else:
            v = float(v)
            if not math.isfinite(v) or not (s["min"] - 1e-9 <= v <= s["max"] + 1e-9):
                raise ValueError(f"{s['label']} must be between {s['min']} and {s['max']}")
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# 2D pattern generation
# ---------------------------------------------------------------------------

MIN_FEATURE_MM = 0.3
MIN_AREA_MM2 = 0.06


def _inset(poly, dist):
    if dist <= 0:
        return poly
    return poly.buffer(-dist, join_style="mitre", mitre_limit=5.0)


def _ring(poly, outer_inset, width):
    a = _inset(poly, outer_inset)
    b = _inset(poly, outer_inset + width)
    return a.difference(b)


def _rot(geom, angle_rad, origin=(0, 0)):
    return affinity.rotate(geom, angle_rad, origin=origin, use_radians=True)


def clean_printable(geom, min_feature=MIN_FEATURE_MM, min_area=MIN_AREA_MM2):
    """Morphological opening: removes features thinner than ``min_feature``."""
    if geom is None or geom.is_empty:
        return as_multipolygon(None)
    r = min_feature / 2.0
    g = geom.buffer(-r, join_style="mitre", mitre_limit=3.0).buffer(r, join_style="mitre", mitre_limit=3.0)
    g = g.intersection(geom)  # never grow beyond the original
    return as_multipolygon(shapely.MultiPolygon([p for p in polygons_of(g) if p.area >= min_area]))


def _corner_shape(kind, s, lw):
    """Motif with its tip at the origin pointing along +y (outward)."""
    if kind == "diamond":
        return Polygon([(0, 0), (0.32 * s, -0.5 * s), (0, -s), (-0.32 * s, -0.5 * s)])
    if kind == "triangle":
        return Polygon([(0, 0), (0.42 * s, -0.75 * s), (-0.42 * s, -0.75 * s)])
    if kind == "chevron":
        return LineString([(-0.48 * s, -0.75 * s), (0, -lw * 0.7), (0.48 * s, -0.75 * s)]).buffer(
            lw / 2, cap_style="flat", join_style="mitre", mitre_limit=4)
    if kind == "arrow":
        head = Polygon([(0, 0), (0.36 * s, -0.55 * s), (-0.36 * s, -0.55 * s)])
        shaft = shapely.box(-lw / 2, -1.1 * s, lw / 2, -0.4 * s)
        return head.union(shaft)
    if kind == "dot":
        return Point(0, -0.4 * s).buffer(0.32 * s, quad_segs=8)
    if kind == "notch":
        return shapely.box(-0.45 * s, -0.42 * s, 0.45 * s, -0.42 * s + max(lw, 0.3 * s)).union(
            shapely.box(-lw / 2, -0.9 * s, lw / 2, -0.42 * s))
    return Polygon()


def _ray_point(poly, direction):
    """Distance from the origin to ``poly``'s boundary along ``direction``."""
    far = LineString([(0, 0), tuple(np.asarray(direction) * 1000.0)])
    inter = far.intersection(poly.exterior)
    pts = [g for g in getattr(inter, "geoms", [inter]) if not g.is_empty]
    if not pts:
        return 0.0
    return min(math.hypot(p.x, p.y) for p in pts if hasattr(p, "x")) if any(hasattr(p, "x") for p in pts) else 0.0


def face_pattern(face_poly, base_vertices2d, design, keepout, center=(0.0, 0.0)):
    """Return {'cut': [(geom, depth)], 'raise': [(geom, height)], 'reserve': inner_area}.

    ``keepout`` is the area reserved for numerals/logo (already including a gap).
    """
    d = design
    cuts = []
    raises = []
    lw = d["line_width_mm"]
    depth = d["relief_depth_mm"]
    poly = face_poly
    inset = d["border_inset_mm"]
    bw = d["border_width_mm"]
    style = d["border_style"]
    border_end = inset
    if style == "groove":
        cuts.append((_ring(poly, inset, bw), depth))
        border_end = inset + bw
    elif style == "double_groove":
        cuts.append((_ring(poly, inset, bw * 0.75), depth))
        cuts.append((_ring(poly, inset + bw * 0.75 + max(lw, 0.45), bw * 0.6), depth))
        border_end = inset + bw * 1.35 + max(lw, 0.45)
    elif style == "ridge":
        raises.append((_ring(poly, inset, bw), depth * 0.7))
        border_end = inset + bw
    elif style == "step":
        cuts.append((_ring(poly, inset, bw * 1.8), depth))
        border_end = inset + bw * 1.8
    inner = _inset(poly, border_end + 0.35)
    if inner.is_empty:
        inner = _inset(poly, inset)

    relief = d["motif_relief"]
    motif_geoms = []

    # nested polygons
    nrings = d["inner_rings"]
    gap = d["ring_gap_mm"]
    if nrings and not inner.is_empty:
        cur = inner
        nv = len(base_vertices2d)
        for i in range(nrings):
            shape = d["ring_shape"]
            if shape == "follow":
                ring = _ring(cur, gap, lw)
                cur = _inset(cur, gap + lw)
            else:
                # largest centred shape of the requested kind inside `cur`
                r_in = cur.exterior.distance(Point(center)) if not cur.is_empty else 0
                if r_in <= lw * 2:
                    break
                r = r_in - gap
                if shape == "circle":
                    outer = Point(center).buffer(r, quad_segs=24)
                elif shape == "diamond":
                    h = r * math.sqrt(2) / 2
                    outer = _rot(shapely.box(-h, -h, h, h), math.pi / 4)
                    # a diamond inscribed in radius r has its edges at distance r
                    outer = affinity.scale(outer, math.sqrt(2), math.sqrt(2), origin=(0, 0))
                    outer = affinity.translate(outer, *center)
                else:  # rotated copy of the face polygon itself
                    pts = np.asarray(base_vertices2d)
                    rr = np.linalg.norm(pts, axis=1).max()
                    ang = math.pi / nv
                    rp = _rot(Polygon(pts), ang)
                    # scale so its inscribed circle equals r
                    rin = rp.exterior.distance(Point(0, 0))
                    outer = affinity.scale(rp, r / rin, r / rin, origin=(0, 0))
                    outer = affinity.translate(outer, *center)
                ring = outer.difference(_inset(outer, lw))
                cur = _inset(outer, lw)
            if cur.is_empty or ring.is_empty:
                break
            motif_geoms.append(ring.intersection(inner))

    # corner motifs (point at each face vertex)
    cm = d["corner_motif"]
    if cm != "none" and not inner.is_empty:
        s = d["corner_size"] * max(1.0, min(2.2, 0.16 * math.sqrt(poly.area)))
        for vx, vy in base_vertices2d:
            dirn = np.array([vx, vy], float) - np.asarray(center)
            dl = np.linalg.norm(dirn)
            if dl < 1e-6:
                continue
            dirn /= dl
            dist = _ray_point(inner, dirn)
            if dist <= s * 0.6:
                continue
            tip = np.asarray(center) + dirn * (dist - 0.05)
            m = _corner_shape(cm, s, lw)
            m = _rot(m, math.atan2(-dirn[0], dirn[1]))
            m = affinity.translate(m, *tip)
            motif_geoms.append(m)

    # radial motif
    rm = d["radial_motif"]
    if rm != "none" and not inner.is_empty:
        dirs = []
        verts = np.asarray(base_vertices2d, float)
        if d["radial_count"] in ("vertices", "both"):
            dirs += [v - center for v in verts]
        if d["radial_count"] in ("edges", "both"):
            dirs += [(verts[k] + verts[(k + 1) % len(verts)]) / 2 - center for k in range(len(verts))]
        for dv in dirs:
            L = np.linalg.norm(dv)
            if L < 1e-6:
                continue
            dv = dv / L
            reach = _ray_point(inner, dv)
            ang = math.atan2(-dv[0], dv[1])
            if rm == "starburst":
                w = max(lw * 2.2, 0.08 * reach)
                ray = Polygon([(-w / 2, 0), (w / 2, 0), (0, reach)])
            elif rm == "rays":
                ray = shapely.box(-lw / 2, 0, lw / 2, reach)
            else:  # spokes: line ending in a dot
                ray = shapely.box(-lw / 2, 0, lw / 2, reach - lw * 1.2).union(
                    Point(0, reach - lw * 1.6).buffer(lw * 1.1, quad_segs=6))
            ray = affinity.translate(_rot(ray, ang), *center)
            motif_geoms.append(ray)

    if motif_geoms:
        mg = shapely.union_all(motif_geoms).intersection(inner)
        if relief == "raised":
            raises.append((mg, depth * 0.7))
        else:
            cuts.append((mg, depth))

    # Merge features of equal depth/height in 2D so the 3D Booleans never see
    # coincident or abutting coplanar surfaces (a classic source of slivers).
    if cuts:
        cuts = [(shapely.union_all([g for g, _ in cuts]), depth)]
    if raises:
        raises = [(shapely.union_all([g for g, _ in raises]), depth * 0.7)]
        if cuts:
            # keep recessed and raised features apart
            cuts = [(cuts[0][0].difference(raises[0][0].buffer(MIN_FEATURE_MM)), depth)]
    # keep everything away from numerals / logo
    if keepout is not None and not keepout.is_empty:
        cuts = [(g.difference(keepout), h) for g, h in cuts]
        raises = [(g.difference(keepout), h) for g, h in raises]
    cuts = [(clean_printable(g), h) for g, h in cuts]
    raises = [(clean_printable(g), h) for g, h in raises]
    cuts = [(g, h) for g, h in cuts if not g.is_empty]
    raises = [(g, h) for g, h in raises if not g.is_empty]
    return {"cut": cuts, "raise": raises, "border_end": border_end}


def numeral_reserve(design):
    """Inset (mm) from the face edge that numerals should stay inside of."""
    style = design["border_style"]
    inset, bw, lw = design["border_inset_mm"], design["border_width_mm"], design["line_width_mm"]
    if style == "none":
        return 0.0
    if style == "double_groove":
        return inset + bw * 1.35 + max(lw, 0.45) + 0.35
    if style == "step":
        return inset + bw * 1.8 + 0.35
    return inset + bw + 0.35

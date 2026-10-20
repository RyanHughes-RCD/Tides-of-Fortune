"""The infinity D4: a sphericon with four curved faces and conformal engraving.

Geometry
--------
The sphericon is the convex hull of two perpendicular half-arcs (semicircles,
or semi-ellipses when "roundness" != 1):

    upper arc  U(t) = (0, R cos t,  s R sin t),   t in [0, pi]
    lower arc  D(t) = (R cos t, 0, -s R sin t),   t in [0, pi]

Its four faces are cones: X+ / X- have apex (+-R, 0, 0) and run to the upper
arc; Y+ / Y- have apex (0, +-R, 0) and run to the lower arc.  Like a
tetrahedron, every face touches the other three, and the die rests on one face
(rolling around that cone's apex until friction stops it).  It is read like a
base-style D4: along each edge of a face is the number of the face across that
edge, so the number along the bottom edges of the visible faces is the face it
rests on.

Engraving
---------
Cones are developable, so each face is unrolled exactly into a flat circular
"fan".  Numerals are laid out (and size-fitted) in that flat fan, then the cut
prism is refined and wrapped onto the surface: a point (x, y, z) of the prism
maps to P(x, y) + z N(x, y), where P is the surface point and N the outward
normal.  The floor of every numeral is therefore exactly ``depth`` below the
curved surface, measured along the local normal, and the walls follow the
normal too.
"""
from __future__ import annotations

import math

import manifold3d as m3d
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import polylabel

from .mesh3d import BooleanError, apply_features, geometry_to_crosssection, manifold_arrays
from .text import BuiltinFont, as_multipolygon, load_font

ARC_SEGMENTS = 160
FACE_NAMES = ["X+", "X-", "Y+", "Y-"]
# neighbour across (start ray, end ray, arc) for each face
NEIGHBOURS = {0: (2, 3, 1), 1: (2, 3, 0), 2: (0, 1, 3), 3: (0, 1, 2)}


class ConeFace:
    """One curved face: cone from ``apex`` to the curve ``curve(t)``, t in [0, pi]."""

    def __init__(self, index, apex, curve, n=2000):
        self.index = index
        self.apex = np.asarray(apex, float)
        self.curve = curve
        t = np.linspace(0.0, math.pi, n)
        q = curve(t)
        d = q - self.apex
        self.t = t
        self.ell = np.linalg.norm(d, axis=1)
        g = d / self.ell[:, None]
        dpsi = np.linalg.norm(np.diff(g, axis=0), axis=1)  # unrolled angle element |dg|
        self.psi = np.concatenate([[0.0], np.cumsum(dpsi)])
        self.Psi = float(self.psi[-1])
        # orientation: make (d/dx, d/dy) right-handed with the outward normal
        self.flip = 1.0
        x, y = self.ell[n // 2] * 0.5 * math.cos(self.Psi / 2), self.ell[n // 2] * 0.5 * math.sin(self.Psi / 2)
        P, N = self.map(np.array([[x, y]]))
        Px, _ = self.map(np.array([[x + 1e-4, y]]))
        Py, _ = self.map(np.array([[x, y + 1e-4]]))
        if np.cross(Px[0] - P[0], Py[0] - P[0]) @ N[0] < 0:
            self.flip = -1.0
        self.polygon = Polygon(self.outline())

    def _theta(self, psi):
        return np.interp(psi, self.psi, self.t)

    def outline(self):
        k = np.linspace(0, len(self.t) - 1, ARC_SEGMENTS).astype(int)
        pts = [(0.0, 0.0)] + [(self.ell[i] * math.cos(self.psi[i]), self.flip * self.ell[i] * math.sin(self.psi[i]))
                              for i in k]
        return pts

    def map(self, xy):
        """Unrolled (x, y) -> (surface point P, outward unit normal N)."""
        xy = np.atleast_2d(xy)
        r = np.hypot(xy[:, 0], xy[:, 1])
        psi = np.clip(np.arctan2(self.flip * xy[:, 1], xy[:, 0]), 0.0, self.Psi)
        th = self._theta(psi)
        q = self.curve(th)
        d = q - self.apex
        g = d / np.linalg.norm(d, axis=1)[:, None]
        eps = 1e-5
        q2 = self.curve(np.clip(th + eps, 0, math.pi))
        q1 = self.curve(np.clip(th - eps, 0, math.pi))
        g2 = (q2 - self.apex) / np.linalg.norm(q2 - self.apex, axis=1)[:, None]
        g1 = (q1 - self.apex) / np.linalg.norm(q1 - self.apex, axis=1)[:, None]
        dg = g2 - g1
        N = np.cross(g, dg)
        N /= np.linalg.norm(N, axis=1)[:, None]
        P = self.apex + r[:, None] * g
        # outward: the centre of the die (origin) is inside
        mid = self.apex + 0.5 * g * self.ell.mean()
        sgn = np.sign(np.einsum("ij,ij->i", N, mid))
        sgn[sgn == 0] = 1
        return P, N * sgn[:, None]

    def edge_points(self):
        """(start ray direction, end ray direction, arc midpoint) in unrolled coords."""
        e0 = np.array([1.0, 0.0])
        e1 = np.array([math.cos(self.Psi), self.flip * math.sin(self.Psi)])
        i = len(self.t) // 2
        am = np.array([self.ell[i] * math.cos(self.psi[i]), self.flip * self.ell[i] * math.sin(self.psi[i])])
        return e0, e1, am, float(self.ell[0]), float(self.ell[-1])


def sphericon(R, s, segments=ARC_SEGMENTS):
    def upper(t):
        t = np.atleast_1d(t)
        return np.stack([np.zeros_like(t), R * np.cos(t), s * R * np.sin(t)], axis=1)

    def lower(t):
        t = np.atleast_1d(t)
        return np.stack([R * np.cos(t), np.zeros_like(t), -s * R * np.sin(t)], axis=1)

    faces = [ConeFace(0, (R, 0, 0), upper), ConeFace(1, (-R, 0, 0), upper),
             ConeFace(2, (0, R, 0), lower), ConeFace(3, (0, -R, 0), lower)]
    t = np.linspace(0, math.pi, segments + 1)
    pts = np.vstack([upper(t), lower(t)])
    hull = m3d.Manifold.hull_points(np.ascontiguousarray(pts))
    return hull, faces


def hull_planes(man):
    """Distinct supporting planes (normal, offset) of a convex manifold's triangles."""
    V, T = manifold_arrays(man)
    p = V[T]
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 1e-12
    n = n[keep] / ln[keep, None]
    d = np.einsum("ij,ij->i", n, p[keep, 0])
    key = np.round(np.column_stack([n, d / max(1.0, np.abs(d).max())]), 7)
    _, idx = np.unique(key, axis=0, return_index=True)
    return [(n[i], float(d[i])) for i in sorted(idx)]


def _place(geom, center, rotation):
    g = affinity.rotate(geom, rotation, origin=(0, 0), use_radians=True)
    return affinity.translate(g, center[0], center[1])


def _layout(face, height, labels, shapes, margin):
    """Three edge numerals for one face at numeral height ``height`` (unrolled coords)."""
    e0, e1, am, l0, l1 = face.edge_points()
    out = []
    # start / end rays: numeral sits along the ray, 'down' towards the ray
    for k, (dirn, length) in enumerate(((e0, l0), (e1, l1))):
        inward = np.array([-dirn[1], dirn[0]])
        # pick the inward side (towards the face interior)
        probe = dirn * length * 0.6 + inward * 0.5
        if not face.polygon.contains(shapely.Point(probe)):
            inward = -inward
        c = dirn * length * 0.6 + inward * (height * 0.5 + margin + 0.25)
        rot = math.atan2(-inward[0], inward[1])
        out.append((labels[k], c, rot))
    # arc: numeral near the middle of the arc, 'down' towards the arc
    rad = am / np.linalg.norm(am)
    c = am - rad * (height * 0.5 + margin + 0.25)
    up = -rad
    out.append((labels[2], c, math.atan2(-up[0], up[1])))
    return [(t, _place(shapes[t], c, r), c, r) for t, c, r in out]


def build_curved(spec, res, asset_loader, family, prm, size, nopts, safe_mode):
    from .builder import BuildError, _numeral_geom

    die = spec["die"]
    num = spec["numbers"]
    depth = float(num.get("depth_mm", 0.75))
    engrave = bool(num.get("engrave", True))
    edge_margin = float(num.get("edge_margin_mm", 0.45))
    min_wall = float(num.get("min_wall_mm", 0.6))
    R = size / 2.0  # size = tip-to-tip length
    s = float(prm["roundness"])
    hull, faces = sphericon(R, s)

    fspec = spec.get("font") or {}
    fallback = BuiltinFont(600)
    if fspec.get("asset_id"):
        data = asset_loader(fspec["asset_id"]) if asset_loader else None
        if data is None:
            raise BuildError(f"font file {fspec.get('name')!r} is missing from the project assets", "font")
        font = load_font(data, fspec.get("name", "font"), fspec.get("weight"), fspec["asset_id"])
    else:
        font = BuiltinFont(fspec.get("weight") or 600)

    margin = edge_margin + 0.5 * min_wall
    regions = {f.index: f.polygon.buffer(-margin, join_style="mitre") for f in faces}
    labels = {f.index: [str(NEIGHBOURS[f.index][k] + 1) for k in range(3)] for f in faces}
    cache = {}

    def shapes_at(h):
        return {str(v): _numeral_geom(font, fallback, str(v), h, nopts, False, cache).geom for v in range(1, 5)}

    def fits(h):
        sh = shapes_at(h)
        for f in faces:
            placed = _layout(f, h, labels[f.index], sh, margin)
            for i, (_, g, _, _) in enumerate(placed):
                if not g.within(regions[f.index]):
                    return False
                for _, g2, _, _ in placed[:i]:
                    if g.distance(g2) < 0.6:
                        return False
        return True

    lo, hi = 0.0, R
    if not fits(0.8):
        raise BuildError("numerals do not fit on the infinity D4; enlarge it or reduce the edge margin", "numbers")
    lo = 0.8
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    h_fit = lo
    explicit = num.get("height_mm")
    if explicit:
        height = min(float(explicit), h_fit)
        if float(explicit) > h_fit:
            res.warnings.append(f"numeral height {float(explicit):.2f} mm does not fit; reduced to {h_fit:.2f} mm")
    else:
        height = h_fit * float(num.get("size_fill", 0.88))
    res.info["numeral_height_mm"] = round(height, 3)
    res.info["numeral_max_height_mm"] = round(h_fit, 3)

    sh = shapes_at(height)
    cutters = []
    top = 1.2
    refine = 0.6 if safe_mode else 0.4
    from .builder import FaceInfo

    for f in faces:
        placed = _layout(f, height, labels[f.index], sh, margin)
        geom = as_multipolygon(shapely.union_all([g for _, g, _, _ in placed]))
        res.layout[f.index] = {"curved": True, "face": f, "numerals": geom, "numeral_depth": depth if engrave else 0.0,
                               "polygon": f.polygon, "logo": None}
        if engrave:
            cs = geometry_to_crosssection(geom)
            prism = m3d.Manifold.extrude(cs, depth + top).translate((0.0, 0.0, -depth)).refine_to_length(refine)

            def warp(pts, f=f):
                P, N = f.map(pts[:, :2])
                return P + pts[:, 2:3] * N

            cutters.append(prism.warp_batch(warp))
        pl = polylabel(f.polygon, tolerance=0.01)
        P, N = f.map(np.array([[pl.x, pl.y]]))
        Py, _ = f.map(np.array([[pl.x, pl.y + 1e-3]]))
        up = (Py[0] - P[0]) / np.linalg.norm(Py[0] - P[0])
        centers = []
        for _, _, c, _ in placed:
            Pc, _ = f.map(np.array([c]))
            centers.append([float(x) for x in Pc[0]])
        res.faces.append(FaceInfo(tag=f.index, labels=labels[f.index], value=f.index + 1,
                                  center=[float(x) for x in P[0]], normal=[float(x) for x in N[0]],
                                  up=[float(x) for x in up], numeral_centers=centers))
    try:
        outer = apply_features(hull, cutters, [])
    except BooleanError as exc:
        raise BooleanError(f"{exc}. Use 'Retry with safe geometry'.") from exc
    res.outer_vertices, res.outer_tris = manifold_arrays(outer)
    res.cut_depths = {f.index: (depth if engrave else 0.0) for f in faces}
    planes = hull_planes(hull)
    res.plane_data = [(n.tolist(), d, "curved") for n, d in planes]
    # the blank is cut with the planes of a coarser inscribed hull: it lies inside the fine
    # hull, so the blank can only gain clearance (by < 4 microns); it is then verified
    # against the fine planes
    coarse, _ = sphericon(R, s, segments=ARC_SEGMENTS // 2)  # vertices are a subset of the fine hull
    _curved_blank(spec, hull, outer, planes, res, max(res.cut_depths.values()), hull_planes(coarse))
    res.info.update({
        "faces": 4, "expected_faces": 4, "size_mm": size, "engrave_depth_mm": depth if engrave else 0.0,
        "logo_face": None, "outer_volume_mm3": float(outer.volume()), "safe_mode": safe_mode,
        "design": spec["design"], "shape": family, "shape_param": prm, "shape_kind": "curved",
        "length_mm": round(size, 2), "size_meaning": "tip-to-tip length",
        "rest": {"curved": True, "reading": "number along the bottom edges of the faces you see"},
    })


def _curved_blank(spec, hull, outer, planes, res, deepest, cut_planes):
    from .builder import BuildError

    bs = spec.get("blank", {})
    clearance = float(bs.get("clearance_mm", 0.5))
    ref = bs.get("reference", "deepest_cut_uniform")
    min_thick = float(bs.get("min_thickness_mm", 2.0))
    # +10 microns: the wrapped cut floor is made of small flat triangles whose chords can
    # sit a few microns deeper than the ideal curved floor on the tightest curvature
    off = clearance if ref == "face_plane" else clearance + deepest + 0.01
    blank = hull
    for n, d in cut_planes:
        blank = blank.trim_by_plane((-n[0], -n[1], -n[2]), -(d - off))
    if blank.is_empty() or blank.volume() <= 0:
        raise BuildError(f"the blank vanishes with {clearance:.2f} mm clearance; reduce it", "blank")
    # plane trimming leaves sliver triangles; the blank is convex, so rebuild it cleanly
    # as the hull of its own vertices (same solid, no zero-area triangles)
    tv, _ = manifold_arrays(blank)
    blank = m3d.Manifold.hull_points(np.ascontiguousarray(tv))
    bv, bt = manifold_arrays(blank)
    check = {"clearance_mm": clearance, "reference": ref, "deepest_cut_mm": deepest, "issues": [], "faces": []}
    N = np.array([n for n, _ in planes])
    D = np.array([d for _, d in planes])
    gaps = D - (bv @ N.T).max(axis=0)
    check["min_plane_margin_mm"] = float((gaps - off).min())
    if check["min_plane_margin_mm"] < -1e-5:
        check["issues"].append(f"blank crosses a clearance plane by {-check['min_plane_margin_mm']:.4f} mm")
    for i in range(4):
        check["faces"].append({"tag": i, "plane_gap_mm": round(float(gaps.min()), 6), "required_mm": round(off, 6),
                               "gap_from_cut_floor_mm": round(float(gaps.min()) - deepest, 6)})
    check["volume_mm3"] = float(blank.volume())
    widths = (bv @ N.T).max(axis=0) - (bv @ N.T).min(axis=0)
    check["min_thickness_mm"] = float(widths.min())
    if widths.min() < min_thick:
        check["issues"].append(f"blank is only {widths.min():.2f} mm thick (minimum {min_thick:.2f} mm)")
    outside = m3d.Manifold.batch_boolean([blank, outer], m3d.OpType.Subtract)
    check["volume_outside_outer_mm3"] = float(outside.volume())
    if outside.volume() > 1e-6:
        check["issues"].append(f"{outside.volume():.4f} mm^3 of the blank lies outside the engraved outer die")
    span = float(np.ptp(bv, axis=0).max()) * 3 + 10
    complement = m3d.Manifold.batch_boolean([m3d.Manifold.cube((span, span, span), True), outer], m3d.OpType.Subtract)
    gap = float(blank.min_gap(complement, max(clearance, 0.01) + deepest + 1.0)) if outside.volume() <= 1e-6 else 0.0
    check["measured_min_gap_mm"] = gap
    # the hull is faceted (chord error < 1 micron), so allow a micron of tolerance
    if ref != "face_plane" and gap < clearance - 2e-3:
        check["issues"].append(f"measured clearance {gap:.3f} mm is below the required {clearance:.3f} mm")
    check["ok"] = not check["issues"]
    res.blank_check = check
    if check["issues"]:
        res.warnings += [f"blank: {m}" for m in check["issues"]]
    res.blank_vertices, res.blank_tris = bv, bt

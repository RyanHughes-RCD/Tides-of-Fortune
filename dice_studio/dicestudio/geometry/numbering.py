"""Face coordinate frames, number assignment and numeral orientation.

Each numbered face gets a right-handed local frame (u, v, n):

* n  - unit outward face normal;
* v  - the "up" direction of the face's main numeral, lying in the face plane;
* u  - v x n, so that u x v = n.  Looking at the face from outside, u points
  right and v points up, which guarantees numerals are never mirrored.

Up directions follow the usual conventions:

* D6:            towards an edge midpoint;
* D8, D12, D20:  towards a vertex (configurable: vertex / edge);
* D10, D100 and all bipyramids:  towards the die's pole (the apex of the face);
* D4:            numbers sit at the corners and each points at its own corner
                 ("apex" style, read at the top) or along the bottom edge
                 ("base" style, read at the bottom).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import Polygon

from .polyhedra import ConvexPolyhedron, GeometryError, opposite_face_map, reading_map, unit

DEFAULT_D10_TOP = [1, 7, 3, 9, 5]
D4_STYLES = ("auto", "apex", "base")  # auto: apex on tetrahedra, base on the wedge
D10_STYLES = ("0-9", "1-10")
D100_STYLES = ("00-90", "10-100")
MARKER_STYLES = ("underline", "dot", "none")
ALIGN_MODES = ("vertex", "edge")
DEFAULT_ALIGN = {"d6": "edge", "d8": "vertex", "d12": "vertex", "d20": "vertex"}
_REF = unit(np.array([0.13, 0.31, 1.0]))  # deliberately skewed: no ties between vertices
_REF2 = unit(np.array([0.27, 1.0, 0.11]))


@dataclass
class FaceFrame:
    tag: int
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    n: np.ndarray
    offset: float  # plane offset (n . x = offset on the face)
    polygon: Polygon  # final face outline in frame coordinates
    base_polygon: Polygon  # base solid outline in frame coordinates
    base_vertices2d: np.ndarray

    def to3d(self, xy, z=0.0):
        xy = np.atleast_2d(np.asarray(xy, float))
        z = np.broadcast_to(np.asarray(z, float), (len(xy),))
        return self.origin + xy[:, :1] * self.u + xy[:, 1:2] * self.v + z[:, None] * self.n

    def to2d(self, p3):
        d = np.atleast_2d(p3) - self.origin
        return np.stack([d @ self.u, d @ self.v], axis=1)

    def matrix(self):
        """3x4 affine matrix mapping local (x, y, z) to world."""
        return np.column_stack([self.u, self.v, self.n, self.origin])


@dataclass
class NumeralPlacement:
    face_tag: int
    text: str
    value: int
    center: tuple  # in frame coordinates (mm)
    rotation: float  # radians, counter-clockwise from the frame's +v
    marker: bool = False
    role: str = "primary"  # 'primary', or on the D4 'corner' (read at the top) / 'edge' (read at the bottom)


def _frame_basis(n, up_dir):
    v = up_dir - n * (up_dir @ n)
    if np.linalg.norm(v) < 1e-9:
        raise GeometryError("cannot determine numeral orientation")
    v = unit(v)
    u = np.cross(v, n)
    return unit(u), v


def _project(frame_origin, u, v, pts):
    d = np.asarray(pts) - frame_origin
    return np.stack([d @ u, d @ v], axis=1)


def _poly_centroid3d(pts):
    poly = np.asarray(pts)
    c = poly.mean(axis=0)
    tot = 0.0
    acc = np.zeros(3)
    for k in range(len(poly)):
        a, b = poly[k], poly[(k + 1) % len(poly)]
        ar = np.linalg.norm(np.cross(a - c, b - c)) / 2
        acc += ar * (a + b + c) / 3
        tot += ar
    return acc / tot


def build_frames(die, poly: ConvexPolyhedron, base: ConvexPolyhedron, align=None, pole=None):
    """Return {face tag: FaceFrame} for all numbered faces.

    ``pole``: numerals point towards the die's pole (bipyramids, trapezohedra).
    """
    if pole is None:
        pole = die in ("d10", "d100")
    align = align or DEFAULT_ALIGN.get(die, "vertex")
    if align not in ALIGN_MODES:
        raise GeometryError(f"alignment must be one of {ALIGN_MODES}")
    roller = getattr(poly, "kind", "isohedral") == "roller"
    frames = {}
    for f in poly.die_faces():
        bf = base.face_by_tag(f.tag)
        bpts = base.vertices[bf.vertex_ids]
        fpts = poly.vertices[f.vertex_ids]
        origin = _poly_centroid3d(fpts)
        bc = _poly_centroid3d(bpts)
        if roller:
            # rollers lie along their axis (z): numerals run along the side, upright
            # when the die lies horizontally
            up = np.cross(f.normal, np.array([0.0, 0.0, 1.0]))
        elif pole:
            apex = bpts[np.argmax(np.abs(bpts[:, 2]))]
            up = apex - bc
        elif die == "d4":
            # base-style D4 reads along the edge; main frame points at the first vertex
            up = bpts[0] - bc
        else:
            if align == "vertex":
                cands = list(bpts)
            else:
                cands = [(bpts[k] + bpts[(k + 1) % len(bpts)]) / 2 for k in range(len(bpts))]
            dirs = [unit(c - bc) for c in cands]
            ref = _REF if abs(f.normal @ _REF) < 0.9 else _REF2
            score = [d @ ref for d in dirs]
            up = cands[int(np.argmax(score))] - bc
        u, v = _frame_basis(f.normal, up)
        p2 = _project(origin, u, v, fpts)
        b2 = _project(origin, u, v, bpts)
        frames[f.tag] = FaceFrame(
            f.tag, origin, u, v, f.normal.copy(), f.offset, Polygon(p2), Polygon(b2), b2
        )
    return frames


# ---------------------------------------------------------------------------
# Number assignment
# ---------------------------------------------------------------------------

def _vertex_faces(base):
    vf = {}
    for f in base.die_faces():
        for vid in f.vertex_ids:
            vf.setdefault(vid, []).append(f.tag)
    return vf


_BALANCE_CACHE = {}


def balanced_assignment(base, n):
    """Assign 1..n so opposite faces sum to n+1 and vertex sums are as even as possible.

    Deterministic local search (fixed RNG seed) over pair placements.  The base
    polyhedron's face tags and topology depend only on the die type, so the
    result is cached per (n, face normals).
    """
    key = (n, tuple(np.round(np.concatenate([f.normal for f in base.die_faces()]), 6)))
    if key not in _BALANCE_CACHE:
        _BALANCE_CACHE[key] = _balanced_assignment(base, n)
    return dict(_BALANCE_CACHE[key])


def _balanced_assignment(base, n):
    opp = opposite_face_map(base)
    pairs = []
    seen = set()
    for f in base.die_faces():
        if f.tag in seen:
            continue
        g = opp[f.tag]
        if g is None:
            raise GeometryError("die has no opposite faces")
        pairs.append((f.tag, g))
        seen |= {f.tag, g}
    vf = list(_vertex_faces(base).values())
    k = len(pairs)
    rng = random.Random(f"balance-{n}")
    order = list(range(k))  # pair index -> low value (order[i] + 1)
    flip = [False] * k

    def values():
        val = {}
        for i, (a, b) in enumerate(pairs):
            lo, hi = order[i] + 1, n - order[i]
            val[a], val[b] = (hi, lo) if flip[i] else (lo, hi)
        return val

    def cost(val):
        sums = np.array([sum(val[t] for t in fs) for fs in vf], float)
        return float(sums.var())

    best = cost(values())
    for _ in range(4000):
        i, j = rng.randrange(k), rng.randrange(k)
        if rng.random() < 0.5:
            order[i], order[j] = order[j], order[i]
            c = cost(values())
            if c <= best:
                best = c
            else:
                order[i], order[j] = order[j], order[i]
        else:
            flip[i] = not flip[i]
            c = cost(values())
            if c <= best:
                best = c
            else:
                flip[i] = not flip[i]
    return values()


def assign_values(die, base, opts):
    """Return {face tag: value}.  D4 'apex' returns vertex values separately."""
    if getattr(base, "kind", "isohedral") == "roller":
        return _roller_assignment(die, base, opts)
    if die == "d6":
        return _d6_assignment(base)
    if die in ("d8", "d12", "d20"):
        return balanced_assignment(base, {"d8": 8, "d12": 12, "d20": 20}[die])
    if die in ("d10", "d100"):
        top = list(opts.get("d10_top_order") or DEFAULT_D10_TOP)
        validate_d10_top(top)
        opp = opposite_face_map(base)
        # faces 0..4 are the upper kites in counter-clockwise order
        vals = {}
        for i in range(5):
            vals[i] = top[i]
            vals[opp[i]] = 9 - top[i]
        return vals
    if die == "d4":
        return {f.tag: f.tag + 1 for f in base.die_faces()}
    raise GeometryError(die)


def _roller_assignment(die, base, opts):
    """Rollers: numbers run around the ring; resting side + side read on top sum to N+1.

    Number faces are tagged 0..N-1 in counter-clockwise ring order, and the
    side read on top while resting on side k is side k + N/2.
    """
    rm = reading_map(base)
    n = len(rm)
    half = n // 2
    if any(rm[k] != (k + half) % n for k in range(n)):
        raise GeometryError("roller sides are not paired with the side read on top")
    vals = {}
    if die in ("d10", "d100"):
        top = list(opts.get("d10_top_order") or DEFAULT_D10_TOP)
        validate_d10_top(top)
        for k in range(half):
            vals[k] = top[k]
            vals[k + half] = 9 - top[k]
        return vals
    for k in range(half):
        vals[k] = k + 1
        vals[k + half] = n - k
    return vals


def _d6_assignment(base):
    """1-2-3 counter-clockwise (seen from outside) around one corner; opposite faces sum to 7."""
    opp = opposite_face_map(base)
    vf = _vertex_faces(base)
    score = base.vertices @ _REF
    vid = max((v for v in vf if len(vf[v]) == 3), key=lambda v: score[v])
    w = unit(base.vertices[vid])
    tags = vf[vid]
    normals = {t: base.face_by_tag(t).normal for t in tags}
    a = unit(normals[tags[0]] - w * (normals[tags[0]] @ w))
    b = np.cross(w, a)
    tags = sorted(tags, key=lambda t: math.atan2(normals[t] @ b, normals[t] @ a))
    vals = {}
    for i, t in enumerate(tags):
        vals[t] = i + 1
        vals[opp[t]] = 6 - i
    return vals


def validate_d10_top(top):
    if len(top) != 5 or len(set(top)) != 5 or any(not (0 <= int(t) <= 9) for t in top):
        raise GeometryError("D10 upper-face order must be five distinct digits 0-9")
    if any((9 - t) in top for t in top):
        raise GeometryError("D10 upper-face digits must not contain an opposite pair (digits summing to 9)")


def label_for(die, value, opts):
    if die == "d10":
        if value == 0 and opts.get("d10_style", "0-9") == "1-10":
            return "10"
        return str(value)
    if die == "d100":
        if value == 0 and opts.get("d100_style", "00-90") == "10-100":
            return "100"
        return f"{value * 10:02d}"
    return str(value)


def numeral_placements(die, frames, base, opts):
    """Return the list of NumeralPlacement for a die (centres provisional)."""
    vals = assign_values(die, base, opts)
    marker_style = opts.get("six_nine_marker", "underline")
    out = []
    if die == "d4" and getattr(base, "kind", "isohedral") != "roller":
        style = opts.get("d4_style", "auto")
        if style not in D4_STYLES:
            raise GeometryError(f"D4 style must be one of {D4_STYLES}")
        if style == "auto":
            style = "base" if getattr(base, "family", "") == "wedge" else "apex"
        # vertex values: base vertex id -> 1..4 (vertex opposite face t gets t+1)
        bverts = base.vertices
        vval = {}
        for f in base.die_faces():
            others = set(range(4)) - set(f.vertex_ids)
            vval[others.pop()] = f.tag + 1
        for tag, fr in frames.items():
            bf = base.face_by_tag(tag)
            if style == "apex":
                for vid in bf.vertex_ids:
                    p2 = fr.to2d(bverts[vid])[0]
                    ang = math.atan2(-p2[0], p2[1])  # rotate +v onto direction of p2
                    out.append(NumeralPlacement(tag, str(vval[vid]), vval[vid], (0.0, 0.0), ang, False, "corner"))
            else:
                ids = bf.vertex_ids
                for k in range(3):
                    a, b = ids[k], ids[(k + 1) % 3]
                    # the face sharing this edge
                    g = next(t for t in range(4) if t != tag and {a, b} <= set(base.face_by_tag(t).vertex_ids))
                    mid = fr.to2d((bverts[a] + bverts[b]) / 2)[0]
                    ang = math.atan2(mid[0], -mid[1])  # numeral's "down" points at the edge
                    out.append(NumeralPlacement(tag, str(vals[g]), vals[g], (0.0, 0.0), ang, False, "edge"))
        return out
    labels = {t: label_for(die, vals[t], opts) for t in frames}
    label_set = set(labels.values())
    for tag, fr in frames.items():
        text = labels[tag]
        mark = marker_style != "none" and text in ("6", "9") and {"6", "9"} <= label_set
        out.append(NumeralPlacement(tag, text, vals[tag], (0.0, 0.0), 0.0, mark, "primary"))
    return out


def opposite_sums(die, base, opts):
    vals = assign_values(die, base, opts)
    opp = opposite_face_map(base)
    return {t: vals[t] + vals[opp[t]] for t in vals if opp.get(t) is not None}

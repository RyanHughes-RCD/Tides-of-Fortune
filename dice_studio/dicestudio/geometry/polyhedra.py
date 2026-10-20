"""Convex polyhedra for the seven dice, represented by their face planes.

Every die body is the intersection of half-spaces ``n . x <= d`` (unit outward
normal ``n``, offset ``d``).  This H-representation gives us:

* exact, always-convex, watertight bodies (no mesh repair needed);
* randomised proportions that keep every face congruent (fair dice);
* the internal blank as the *same* planes moved inward along their own
  normals (a true face offset, not a uniform scale).

Units are millimetres throughout.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

PHI = (1.0 + math.sqrt(5.0)) / 2.0

DIE_TYPES = ["d4", "d6", "d8", "d10", "d12", "d20", "d100"]
FACE_COUNTS = {"d4": 4, "d6": 6, "d8": 8, "d10": 10, "d12": 12, "d20": 20, "d100": 10}

# Default sizes.  D4: longest edge length.  Every other die: face-to-opposite-face distance.
DEFAULT_SIZES_MM = {"d4": 20.0, "d6": 16.0, "d8": 15.0, "d10": 16.0, "d12": 18.0, "d20": 19.0, "d100": 16.0}
SIZE_LIMITS_MM = (8.0, 40.0)
SIZE_MEANING = {
    "d4": "longest edge length",
    "d6": "face-to-face distance",
    "d8": "face-to-face distance",
    "d10": "face-to-face distance",
    "d12": "face-to-face distance",
    "d20": "face-to-face distance",
    "d100": "face-to-face distance",
}

def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


class GeometryError(ValueError):
    """Raised for invalid geometric parameters or degenerate results."""


@dataclass
class Plane:
    normal: np.ndarray  # unit, outward
    offset: float  # n . x <= offset
    kind: str  # 'face' | 'edge' | 'vertex'
    tag: object  # die face index for 'face', (i, j) for edges, vertex key for vertices


@dataclass
class PolyFace:
    plane_index: int
    kind: str
    tag: object
    normal: np.ndarray
    offset: float
    vertex_ids: list  # counter-clockwise when viewed from outside

    def polygon(self, vertices):
        return vertices[self.vertex_ids]


@dataclass
class ConvexPolyhedron:
    vertices: np.ndarray
    faces: list  # PolyFace
    planes: list  # Plane (all input planes, including redundant ones)

    def die_faces(self):
        """Faces that carry a number, ordered by die face index."""
        fs = [f for f in self.faces if f.kind == "face"]
        return sorted(fs, key=lambda f: f.tag)

    def face_by_tag(self, tag):
        for f in self.faces:
            if f.kind == "face" and f.tag == tag:
                return f
        raise KeyError(tag)

    def edges(self):
        """Map undirected vertex pair -> list of face indices (into self.faces)."""
        out = {}
        for fi, f in enumerate(self.faces):
            ids = f.vertex_ids
            for a, b in zip(ids, ids[1:] + ids[:1]):
                out.setdefault((min(a, b), max(a, b)), []).append(fi)
        return out

    def triangles(self):
        tris = []
        for f in self.faces:
            ids = f.vertex_ids
            for k in range(1, len(ids) - 1):
                tris.append((ids[0], ids[k], ids[k + 1]))
        return np.asarray(tris, dtype=np.int64)

    def volume(self):
        v = self.vertices
        t = self.triangles()
        return float(np.einsum("ij,ij->i", v[t[:, 0]], np.cross(v[t[:, 1]], v[t[:, 2]])).sum() / 6.0)

    def width_along(self, n):
        p = self.vertices @ np.asarray(n, float)
        return float(p.max() - p.min())


# ---------------------------------------------------------------------------
# Half-space intersection
# ---------------------------------------------------------------------------

def halfspace_intersection(planes, tol=None):
    """Intersect half-spaces and return a ConvexPolyhedron.

    Brute force over plane triples (vectorised).  Plane counts here are small
    (at most ~70), so this is fast and, unlike incremental algorithms, has no
    failure modes besides genuinely degenerate input.
    """
    N = np.array([p.normal for p in planes], dtype=float)
    d = np.array([p.offset for p in planes], dtype=float)
    scale = max(1.0, float(np.abs(d).max()))
    if tol is None:
        tol = 1e-9 * scale
    m = len(planes)
    if m < 4:
        raise GeometryError("need at least four planes for a closed solid")
    idx = np.array(list(itertools.combinations(range(m), 3)), dtype=np.int64)
    A = N[idx]
    b = d[idx]
    det = np.linalg.det(A)
    ok = np.abs(det) > 1e-9
    A, b = A[ok], b[ok]
    X = np.linalg.solve(A, b[..., None])[..., 0]
    viol = X @ N.T - d[None, :]
    X = X[(viol <= tol * 10).all(axis=1)]
    if len(X) < 4:
        raise GeometryError("half-spaces do not bound a solid")
    # merge duplicates (vertices where more than three planes meet)
    merge_tol = 1e-7 * scale
    uniq = []
    for p in X:
        if not any(np.linalg.norm(p - q) < merge_tol for q in uniq):
            uniq.append(p)
    V = np.array(uniq)
    on_tol = 1e-7 * scale
    faces = []
    for i, pl in enumerate(planes):
        on = np.nonzero(np.abs(V @ pl.normal - pl.offset) < on_tol)[0]
        if len(on) < 3:
            continue  # redundant plane
        pts = V[on]
        c = pts.mean(axis=0)
        u = pts[0] - c
        u -= pl.normal * (u @ pl.normal)
        u = unit(u)
        w = np.cross(pl.normal, u)
        ang = np.arctan2((pts - c) @ w, (pts - c) @ u)
        order = on[np.argsort(ang)]
        poly = V[order]
        area = 0.5 * np.linalg.norm(
            sum(np.cross(poly[k], poly[(k + 1) % len(poly)]) for k in range(len(poly)))
        )
        if area < 1e-8 * scale * scale:
            continue
        faces.append(PolyFace(i, pl.kind, pl.tag, pl.normal.copy(), float(pl.offset), [int(k) for k in order]))
    # drop vertices not used by any face (cannot happen for valid input, but be safe)
    used = sorted({k for f in faces for k in f.vertex_ids})
    remap = {old: new for new, old in enumerate(used)}
    V = V[used]
    for f in faces:
        f.vertex_ids = [remap[k] for k in f.vertex_ids]
    poly = ConvexPolyhedron(V, faces, list(planes))
    if poly.volume() <= 0:
        raise GeometryError("degenerate solid (zero volume)")
    return poly


# ---------------------------------------------------------------------------
# Congruent-face shape families
# ---------------------------------------------------------------------------
# Every family is *isohedral* (face-transitive): all faces of a die are congruent
# and equidistant from the centre, so the dice stay fair whatever the random
# proportions.  Families are restricted to ones where every face has a parallel
# opposite face (except the D4, which is read at a vertex), so the die rests flat
# with a number face pointing straight up.
#
#   die   family          parameter (meaning, range)
#   D4    tetrahedron     -
#         disphenoid      stretch: z/x ratio of the bounding box (0.8-1.3; 1 = regular)
#   D6    cube            -
#         rhombohedron    face-normal elevation in degrees (26-46; 35.26 = cube)
#   D8    octahedron      -
#         bipyramid       apex height / ring radius (0.75-1.4; 1 = octahedron)
#   D10   trapezohedron   apex height / ring radius (0.8-1.35)
#   D12   dodecahedron    -
#         pyritohedron    normal tilt t in (0,1,t) (1.15-2.3; 1.618 = regular)
#         rhombic         - (rhombic dodecahedron)
#         bipyramid       apex height / ring radius (0.9-1.4), hexagonal
#   D20   icosahedron     -
#         bipyramid       apex height / ring radius (1.2-1.6), decagonal

FAMILIES = {
    "d4": {"tetrahedron": None, "disphenoid": (0.8, 1.3, 1.0)},
    "d6": {"cube": None, "rhombohedron": (26.0, 46.0, 35.26)},
    "d8": {"octahedron": None, "bipyramid": (0.75, 1.4, 1.0)},
    "d10": {"trapezohedron": (0.8, 1.35, 1.05)},
    "d12": {"dodecahedron": None, "pyritohedron": (1.15, 2.3, PHI), "rhombic": None, "bipyramid": (0.9, 1.4, 1.15)},
    "d20": {"icosahedron": None, "bipyramid": (1.2, 1.6, 1.4)},
}
FAMILIES["d100"] = FAMILIES["d10"]
POLE_FAMILIES = {"bipyramid", "trapezohedron"}  # numerals point to the pole on these
REGULAR_FAMILIES = {"tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron"}


def _normal_through(a, b, c):
    n = unit(np.cross(b - a, c - a))
    return n if n @ (a + b + c) > 0 else -n


def _bipyramid_normals(n, h):
    """n-gonal bipyramid, ring radius 1, apexes at +-h.  Upper faces 0..n-1 CCW, then lower."""
    top, bot = np.array([0, 0, h]), np.array([0, 0, -h])
    ring = [np.array([math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n), 0.0]) for k in range(n)]
    up = [_normal_through(top, ring[k], ring[(k + 1) % n]) for k in range(n)]
    lo = [_normal_through(bot, ring[(k + 1) % n], ring[k]) for k in range(n)]
    return np.array(up + lo)


def _trapezohedron_normals(h):
    """Pentagonal trapezohedron with apexes at (0,0,+-h) and equator radius 1.

    Upper ring vertices sit at z0, lower ring at -z0 (rotated 36 degrees).
    z0 = h (1 - cos36) / (1 + cos36) makes every kite exactly planar.
    """
    c36 = math.cos(math.radians(36))
    z0 = h * (1 - c36) / (1 + c36)
    top = np.array([0, 0, h])
    normals = []
    for k in range(5):
        a0 = math.radians(72 * k)
        a1 = math.radians(72 * (k + 1))
        u0 = np.array([math.cos(a0), math.sin(a0), z0])
        u1 = np.array([math.cos(a1), math.sin(a1), z0])
        normals.append(_normal_through(top, u0, u1))
    for k in range(5):
        a = math.radians(36)
        n = normals[k]
        # lower faces: rotate the upper face by 36 degrees and mirror in z
        rn = np.array([n[0] * math.cos(a) - n[1] * math.sin(a), n[0] * math.sin(a) + n[1] * math.cos(a), -n[2]])
        normals.append(unit(rn))
    return np.array(normals)


def _pyrito_normals(t):
    n = []
    for a, b in itertools.product((1, -1), repeat=2):
        n += [(0, a, b * t), (a, b * t, 0), (b * t, 0, a)]
    return unit(np.array(n, float))


def family_normals(die, family, param=None):
    fams = FAMILIES.get(die)
    if fams is None:
        raise GeometryError(f"unknown die type {die!r}")
    if family not in fams:
        raise GeometryError(f"{die.upper()} shape must be one of {list(fams)}")
    rng = fams[family]
    if rng is not None:
        param = rng[2] if param is None else float(param)
        if not (rng[0] - 1e-9 <= param <= rng[1] + 1e-9):
            raise GeometryError(f"{die.upper()} {family} parameter must be between {rng[0]} and {rng[1]}")
    if family == "tetrahedron":
        family, param = "disphenoid", 1.0
    if family == "disphenoid":
        k = param
        verts = np.array([(1, 1, k), (1, -1, -k), (-1, 1, -k), (-1, -1, k)], float)
        return np.array([_normal_through(*[verts[j] for j in range(4) if j != i]) for i in range(4)])
    if family == "cube":
        return np.array([(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)], float)
    if family == "rhombohedron":
        e = math.radians(param)
        up = [(math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))
              for a in (math.radians(x) for x in (90, 210, 330))]
        return np.array(up + [tuple(-np.array(u)) for u in up], float)
    if family == "octahedron":
        return _bipyramid_normals(4, 1.0)
    if family == "bipyramid":
        return _bipyramid_normals({"d8": 4, "d12": 6, "d20": 10}[die], param)
    if family == "trapezohedron":
        return _trapezohedron_normals(param)
    if family == "dodecahedron":
        return _pyrito_normals(PHI)
    if family == "pyritohedron":
        return _pyrito_normals(param)
    if family == "rhombic":
        return _pyrito_normals(1.0)
    if family == "icosahedron":
        n = [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
        ip = 1.0 / PHI
        for a, b in itertools.product((1, -1), repeat=2):
            n += [(0, a * ip, b * PHI), (a * ip, b * PHI, 0), (b * PHI, 0, a * ip)]
        return unit(np.array(n, float))
    raise GeometryError(family)


DEFAULT_FAMILY = {"d4": "tetrahedron", "d6": "cube", "d8": "octahedron", "d10": "trapezohedron",
                  "d12": "dodecahedron", "d20": "icosahedron", "d100": "trapezohedron"}


@dataclass
class ShapeParams:
    size_mm: float
    family: str = None
    param: float = None

    def validate(self, die):
        lo, hi = SIZE_LIMITS_MM
        if not (lo <= self.size_mm <= hi):
            raise GeometryError(f"size {self.size_mm:.2f} mm outside {lo}-{hi} mm")


def die_polyhedron(die, params: ShapeParams):
    """Return (polyhedron, base polyhedron, warnings).

    All faces lie at the same distance from the centre (inradius 1 before
    scaling); the solid is then scaled so that the D4's longest edge, or every
    other die's face-to-face distance, equals ``size_mm``.
    """
    if die not in FAMILIES:
        raise GeometryError(f"unknown die type {die!r}")
    params.validate(die)
    family = params.family or DEFAULT_FAMILY[die]
    normals = family_normals(die, family, params.param)
    unit_poly = halfspace_intersection([Plane(n, 1.0, "face", i) for i, n in enumerate(normals)])
    if die == "d4":
        longest = max(np.linalg.norm(unit_poly.vertices[a] - unit_poly.vertices[b]) for a, b in unit_poly.edges())
        r = params.size_mm / longest
    else:
        r = params.size_mm / 2.0
    poly = halfspace_intersection([Plane(n, r, "face", i) for i, n in enumerate(normals)])
    if len(poly.die_faces()) != FACE_COUNTS[die]:
        raise GeometryError(f"{die.upper()} {family} has {len(poly.die_faces())} faces instead of {FACE_COUNTS[die]}")
    poly.family = family
    return poly, poly, []


def face_congruence_error(poly):
    """Max difference (mm / rad) between the sorted edge lengths and angles of any two faces."""
    sigs = []
    for f in poly.die_faces():
        pts = poly.vertices[f.vertex_ids]
        k = len(pts)
        e = sorted(np.linalg.norm(pts[i] - pts[(i + 1) % k]) for i in range(k))
        a = sorted(math.acos(np.clip(unit(pts[i - 1] - pts[i]) @ unit(pts[(i + 1) % k] - pts[i]), -1, 1))
                   for i in range(k))
        sigs.append(np.array(e + a))
    if len({len(s) for s in sigs}) != 1:
        return float("inf")
    return float(max(np.abs(s - sigs[0]).max() for s in sigs))


def offset_polyhedron(poly: ConvexPolyhedron, offsets):
    """Move every plane of ``poly`` inward by ``offsets[plane_index]`` mm along its own normal.

    This is the exact inward face offset used for the internal blanks.  Planes
    that were redundant in the outer body stay in the set, so the result is
    always contained in the outer body's half-spaces.
    """
    planes = [Plane(p.normal.copy(), p.offset - float(offsets[i]), p.kind, p.tag) for i, p in enumerate(poly.planes)]
    return halfspace_intersection(planes)


def opposite_face_map(poly: ConvexPolyhedron):
    """Map die-face tag -> tag of the face with the antiparallel normal (or None)."""
    fs = poly.die_faces()
    out = {}
    for f in fs:
        best = None
        for g in fs:
            if f.normal @ g.normal < -0.999:
                best = g.tag
        out[f.tag] = best
    return out

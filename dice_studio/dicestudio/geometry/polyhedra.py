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
# Shape families
# ---------------------------------------------------------------------------
# Three kinds of family:
#
# * "isohedral": face-transitive solids.  Every face is congruent and lands; every
#   face (except on the D4) has a parallel opposite face that is read on top.
# * "roller": long crystals, shards and gems with pointed ends.  The die rolls
#   like a pencil and comes to rest on one of its N congruent long sides; the
#   cap facets at the ends are deliberately unstable, so it cannot land on them
#   (verified by rest_analysis).  The side facing up is read.
# * "curved": the infinity D4 (a sphericon) - see geometry/curved.py.
#
# Roller geometry is defined in units where the flat-to-flat width of the
# widest cross-section is 2; family parameters are lengths in multiples of that
# width (the guide's "resting" size).  size_mm is that width for rollers.

ROLLER_SIDES = {"d4": 4, "d6": 6, "d8": 8, "d10": 10, "d12": 12, "d20": 20, "d100": 10}


def _p(lo, hi, default, label):
    return {"min": lo, "max": hi, "default": default, "label": label}


# Parameter ranges are the regions where rest_analysis confirms the die rolls onto a
# numbered side and cannot rest on an end facet (combinations near the edges of a
# range can still fail; those are rejected with an explanation).
_CRYSTAL = {"kind": "roller", "label": "Crystal (prism with pointed ends)",
            "params": {"body": _p(0.9, 2.4, 1.3, "Body length (x width)"),
                       "cap": _p(0.55, 1.1, 0.7, "End point length (x width)")}}
_SHARD = {"kind": "roller", "label": "Shard (long point + short point)",
          "params": {"long": _p(2.1, 3.2, 2.5, "Long point length (x width)"),
                     "short": _p(0.6, 1.0, 0.75, "Short point length (x width)")}}
_SHORT_SHARD = {"kind": "roller", "label": "Short shard (body with a long and a short point)",
                "params": {"body": _p(0.9, 1.8, 1.1, "Body length (x width)"),
                           "long": _p(0.8, 1.8, 1.2, "Long point length (x width)"),
                           "short": _p(0.45, 0.9, 0.6, "Short point length (x width)")}}
_ROLLERS = {"crystal": _CRYSTAL, "shard": _SHARD, "short_shard": _SHORT_SHARD}

FAMILIES = {
    "d4": {
        "tetrahedron": {"kind": "isohedral", "label": "Tetrahedron (regular)", "params": {}},
        "disphenoid": {"kind": "isohedral", "label": "Disphenoid (stretched tetrahedron)",
                       "params": {"stretch": _p(0.75, 1.6, 1.0, "Stretch (1 = regular)")}},
        "wedge": {"kind": "isohedral", "label": "Wedge (long, read along the edges)",
                  "params": {"stretch": _p(1.6, 2.4, 1.9, "Length stretch")}},
        **_ROLLERS,
        "infinity": {"kind": "curved", "label": "Infinity (curved rolling sphericon)",
                     "params": {"roundness": _p(0.8, 1.25, 1.0, "Roundness (1 = classic sphericon)")}},
    },
    "d6": {
        "cube": {"kind": "isohedral", "label": "Cube", "params": {}},
        "rhombohedron": {"kind": "isohedral", "label": "Rhombohedron (6 rhombi)",
                         "params": {"angle": _p(18.0, 52.0, 35.26, "Face tilt (35.26 = cube; low = tall)")}},
        **_ROLLERS,
        "gemstone": {"kind": "roller", "label": "Gemstone (faceted crown + pavilion)",
                     "params": {"body": _p(1.0, 2.0, 1.3, "Girdle length (x width)"),
                                "crown": _p(0.7, 1.0, 0.8, "Crown height (x width)"),
                                "pavilion": _p(0.9, 1.5, 1.1, "Pavilion length (x width)")}},
    },
    "d8": {
        "octahedron": {"kind": "isohedral", "label": "Octahedron (regular)", "params": {}},
        "bipyramid": {"kind": "isohedral", "label": "Square bipyramid",
                      "params": {"height": _p(0.75, 2.2, 1.0, "Height (1 = octahedron)")}},
        **_ROLLERS,
    },
    "d10": {
        "trapezohedron": {"kind": "isohedral", "label": "Pentagonal trapezohedron (kites)",
                          "params": {"elongation": _p(0.8, 2.0, 1.05, "Elongation")}},
        **_ROLLERS,
    },
    "d12": {
        "dodecahedron": {"kind": "isohedral", "label": "Dodecahedron (regular)", "params": {}},
        "pyritohedron": {"kind": "isohedral", "label": "Pyritohedron (irregular pentagons)",
                         "params": {"pentagon": _p(1.15, 2.3, PHI, "Pentagon shape (1.618 = regular)")}},
        "rhombic": {"kind": "isohedral", "label": "Rhombic dodecahedron", "params": {}},
        "bipyramid": {"kind": "isohedral", "label": "Hexagonal bipyramid",
                      "params": {"height": _p(0.9, 2.2, 1.15, "Height")}},
        **_ROLLERS,
    },
    "d20": {
        "icosahedron": {"kind": "isohedral", "label": "Icosahedron (regular)", "params": {}},
        "bipyramid": {"kind": "isohedral", "label": "Decagonal bipyramid",
                      "params": {"height": _p(1.2, 2.4, 1.4, "Height")}},
        **_ROLLERS,
    },
}
FAMILIES["d100"] = FAMILIES["d10"]
POLE_FAMILIES = {"bipyramid", "trapezohedron"}  # numerals point to the pole on these
REGULAR_FAMILIES = {"tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron"}
ROLLER_FAMILIES = {"crystal", "shard", "short_shard", "gemstone"}
CURVED_FAMILIES = {"infinity"}


# default size per kind (rollers: resting width across the sides; infinity: tip to tip)
ROLLER_DEFAULT_WIDTH_MM = {"d4": 12.0, "d6": 13.0, "d8": 14.0, "d10": 16.5, "d12": 18.0, "d20": 22.0, "d100": 16.5}
INFINITY_DEFAULT_MM = 21.0


def default_size_mm(die, family=None):
    family = family or DEFAULT_FAMILY[die]
    kind = FAMILIES[die][family]["kind"]
    if kind == "roller":
        return ROLLER_DEFAULT_WIDTH_MM[die]
    if kind == "curved":
        return INFINITY_DEFAULT_MM
    if family == "wedge":
        return 29.0  # longest edge, like a typical 29 mm wedge D4
    return DEFAULT_SIZES_MM[die]


def size_meaning(die, family=None):
    family = family or DEFAULT_FAMILY[die]
    kind = FAMILIES[die][family]["kind"]
    if kind == "roller":
        return "resting width across the sides"
    if kind == "curved":
        return "tip-to-tip length"
    return SIZE_MEANING[die]


def family_kind(die, family):
    return FAMILIES[die][family]["kind"]


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


def _cone_planes(n_sides, z_base, length, sign, azimuth0=0.0, radius=1.0):
    """Planes of an n-sided pyramid cap.

    Each plane passes through the line where the side at ``radius`` meets
    z = ``z_base`` and through the apex on the axis at z_base + sign*length.
    Returns [(normal, offset)].
    """
    out = []
    for k in range(n_sides):
        a = azimuth0 + 2 * math.pi * k / n_sides
        # in the (radial, z) plane the normal is (length, sign*radius)
        nr, nz = length, sign * radius
        ln = math.hypot(nr, nz)
        n = np.array([math.cos(a) * nr / ln, math.sin(a) * nr / ln, nz / ln])
        d = (nr * radius + nz * z_base) / ln
        out.append((n, d))
    return out


def roller_planes(die, family, prm):
    """[(normal, offset, kind)] for crystal / shard / gemstone, width 2 across the sides."""
    N = ROLLER_SIDES[die]
    sides = [(np.array([math.cos(2 * math.pi * k / N), math.sin(2 * math.pi * k / N), 0.0]), 1.0)
             for k in range(N)]
    if family == "crystal":
        L = prm["body"]  # half body length in width/2 units == body * width / 2
        C = 2 * prm["cap"]
        caps = _cone_planes(N, L, C, +1) + _cone_planes(N, -L, C, -1)
        return [(n, d, "face") for n, d in sides] + [(n, d, "cap") for n, d in caps]
    if family == "shard":
        # pure two-point shape: the long point's facets are the numbered sides
        longs = _cone_planes(N, 0.0, 2 * prm["long"], -1)
        shorts = _cone_planes(N, 0.0, 2 * prm["short"], +1)
        return [(n, d, "face") for n, d in longs] + [(n, d, "cap") for n, d in shorts]
    if family == "short_shard":
        L = prm["body"]
        caps = _cone_planes(N, L, 2 * prm["short"], +1) + _cone_planes(N, -L, 2 * prm["long"], -1)
        return [(n, d, "face") for n, d in sides] + [(n, d, "cap") for n, d in caps]
    if family == "gemstone":
        L = prm["body"]
        C1 = 2 * prm["crown"]
        crown1 = _cone_planes(N, L, C1, +1)
        # second crown tier: rotated half a step, flatter, meeting on the axis lower than tier 1
        crown2 = _cone_planes(N, L, 0.62 * C1, +1, azimuth0=math.pi / N, radius=1.25)
        pav = _cone_planes(N, -L, 2 * prm["pavilion"], -1)
        return ([(n, d, "face") for n, d in sides] +
                [(n, d, "cap") for n, d in crown1 + crown2 + pav])
    raise GeometryError(family)


def family_planes(die, family, prm):
    """[(normal, offset, kind)] in unit coordinates (see module notes)."""
    if family == "tetrahedron":
        family, prm = "disphenoid", {"stretch": 1.0}
    if family in ("disphenoid", "wedge"):
        k = prm["stretch"]
        verts = np.array([(1, 1, k), (1, -1, -k), (-1, 1, -k), (-1, -1, k)], float)
        ns = [_normal_through(*[verts[j] for j in range(4) if j != i]) for i in range(4)]
    elif family == "cube":
        ns = np.array([(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)], float)
    elif family == "rhombohedron":
        e = math.radians(prm["angle"])
        up = [(math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))
              for a in (math.radians(x) for x in (90, 210, 330))]
        ns = np.array(up + [tuple(-np.array(u)) for u in up], float)
    elif family == "octahedron":
        ns = _bipyramid_normals(4, 1.0)
    elif family == "bipyramid":
        ns = _bipyramid_normals({"d8": 4, "d12": 6, "d20": 10}[die], prm["height"])
    elif family == "trapezohedron":
        ns = _trapezohedron_normals(prm["elongation"])
    elif family == "dodecahedron":
        ns = _pyrito_normals(PHI)
    elif family == "pyritohedron":
        ns = _pyrito_normals(prm["pentagon"])
    elif family == "rhombic":
        ns = _pyrito_normals(1.0)
    elif family == "icosahedron":
        n = [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
        ip = 1.0 / PHI
        for a, b in itertools.product((1, -1), repeat=2):
            n += [(0, a * ip, b * PHI), (a * ip, b * PHI, 0), (b * PHI, 0, a * ip)]
        ns = unit(np.array(n, float))
    elif family in ROLLER_FAMILIES:
        return roller_planes(die, family, prm)
    else:
        raise GeometryError(family)
    return [(np.asarray(n, float), 1.0, "face") for n in ns]


DEFAULT_FAMILY = {"d4": "tetrahedron", "d6": "cube", "d8": "octahedron", "d10": "trapezohedron",
                  "d12": "dodecahedron", "d20": "icosahedron", "d100": "trapezohedron"}


def resolve_params(die, family, params=None):
    """Fill defaults and range-check a family's parameters."""
    if die not in FAMILIES:
        raise GeometryError(f"unknown die type {die!r}")
    fams = FAMILIES[die]
    if family not in fams:
        raise GeometryError(f"{die.upper()} shape must be one of {list(fams)}")
    out = {}
    for name, spec in fams[family]["params"].items():
        v = (params or {}).get(name)
        v = spec["default"] if v is None else float(v)
        if not (spec["min"] - 1e-9 <= v <= spec["max"] + 1e-9):
            raise GeometryError(f"{die.upper()} {family} {spec['label'].lower()} must be between "
                                f"{spec['min']} and {spec['max']}")
        out[name] = v
    return out


@dataclass
class ShapeParams:
    size_mm: float
    family: str = None
    params: dict = None

    def validate(self, die):
        lo, hi = SIZE_LIMITS_MM
        if not (lo <= self.size_mm <= hi):
            raise GeometryError(f"size {self.size_mm:.2f} mm outside {lo}-{hi} mm")


def die_polyhedron(die, params: ShapeParams):
    """Return (polyhedron, base polyhedron, warnings).

    Isohedral dice are scaled so that the D4's longest edge, or every other die's
    face-to-face distance, equals ``size_mm``.  Rollers are scaled so their
    width across the long sides equals ``size_mm``.
    """
    if die not in FAMILIES:
        raise GeometryError(f"unknown die type {die!r}")
    params.validate(die)
    family = params.family or DEFAULT_FAMILY[die]
    prm = resolve_params(die, family, params.params)
    if family in CURVED_FAMILIES:
        raise GeometryError("curved dice are built by geometry.curved")
    raw = family_planes(die, family, prm)
    nface = sum(1 for _, _, k in raw if k == "face")

    def planes_at(scale):
        out, fi, ci = [], 0, 0
        for n, d, k in raw:
            if k == "face":
                out.append(Plane(n, d * scale, "face", fi))
                fi += 1
            else:
                out.append(Plane(n, d * scale, "cap", 1000 + ci))
                ci += 1
        return out

    if die == "d4" and family not in ROLLER_FAMILIES:
        unit_poly = halfspace_intersection(planes_at(1.0))
        longest = max(np.linalg.norm(unit_poly.vertices[a] - unit_poly.vertices[b]) for a, b in unit_poly.edges())
        r = params.size_mm / longest
    else:
        r = params.size_mm / 2.0
    poly = halfspace_intersection(planes_at(r))
    if len(poly.die_faces()) != FACE_COUNTS[die] or nface != FACE_COUNTS[die]:
        raise GeometryError(f"{die.upper()} {family} has {len(poly.die_faces())} number faces instead of "
                            f"{FACE_COUNTS[die]}; adjust its proportions")
    poly.family = family
    poly.kind = family_kind(die, family)
    return poly, poly, []


def face_congruence_error(poly, faces=None):
    """Max difference (mm / rad) between the sorted edge lengths and angles of any two faces."""
    sigs = []
    for f in (faces if faces is not None else poly.die_faces()):
        pts = poly.vertices[f.vertex_ids]
        k = len(pts)
        e = sorted(np.linalg.norm(pts[i] - pts[(i + 1) % k]) for i in range(k))
        a = sorted(math.acos(np.clip(unit(pts[i - 1] - pts[i]) @ unit(pts[(i + 1) % k] - pts[i]), -1, 1))
                   for i in range(k))
        sigs.append(np.array(e + a))
    if len({len(s) for s in sigs}) != 1:
        return float("inf")
    return float(max(np.abs(s - sigs[0]).max() for s in sigs))


# ---------------------------------------------------------------------------
# Rest analysis
# ---------------------------------------------------------------------------

def centroid(poly):
    """Centre of mass of the (uniform density) solid."""
    v = poly.vertices
    t = poly.triangles()
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    return (vol[:, None] * (a + b + c) / 4.0).sum(axis=0) / vol.sum()


def rest_analysis(poly):
    """For every face: can the die stay at rest on it?

    A convex body resting on a face is stable iff its centre of mass projects
    (straight down, along the face normal) to a point inside that face.  The
    margin is the signed distance of that point from the face outline (positive
    inside), also given relative to the face's inscribed radius.
    """
    from shapely.geometry import Point, Polygon

    com = centroid(poly)
    rows = []
    for f in poly.faces:
        pts = poly.vertices[f.vertex_ids]
        foot = com - f.normal * (f.normal @ com - f.offset)
        c = pts.mean(axis=0)
        u = unit(pts[0] - c)
        w = np.cross(f.normal, u)
        pg = Polygon(np.stack([(pts - c) @ u, (pts - c) @ w], axis=1))
        q = Point((foot - c) @ u, (foot - c) @ w)
        d = pg.exterior.distance(q)
        margin = d if pg.contains(q) else -d
        inr = pg.exterior.distance(pg.representative_point()) if pg.area > 0 else 1.0
        from shapely.ops import polylabel
        inr = pg.exterior.distance(polylabel(pg, tolerance=1e-3 * math.sqrt(pg.area)))
        rows.append({"tag": f.tag, "kind": f.kind, "stable": margin > 0, "margin_mm": float(margin),
                     "margin_rel": float(margin / inr) if inr > 0 else 0.0})
    return com, rows


STABLE_MARGIN_REL = 0.12  # numbered faces must hold the die with at least this margin


def reading_map(poly):
    """Map each number face R to the number face read on top while resting on R."""
    fs = poly.die_faces()
    out = {}
    for f in fs:
        out[f.tag] = max((g for g in fs if g.tag != f.tag), key=lambda g: -(f.normal @ g.normal)).tag
    return out


def check_landing(poly):
    """Issues preventing the die from behaving as intended (empty list = fine)."""
    issues = []
    _, rows = rest_analysis(poly)
    weak = [r for r in rows if r["kind"] == "face" and r["margin_rel"] < STABLE_MARGIN_REL]
    if weak:
        issues.append(f"{len(weak)} number face(s) cannot hold the die at rest (it would roll off them); "
                      "make the shape less extreme")
    caps = [r for r in rows if r["kind"] == "cap" and r["margin_mm"] > -1e-6]
    if caps:
        issues.append(f"the die could come to rest on {len(caps)} end facet(s); make the ends longer/pointier")
    kind = getattr(poly, "kind", "isohedral")
    if kind == "roller":
        rm = reading_map(poly)
        if sorted(rm.values()) != sorted(rm):
            issues.append("the face read on top is ambiguous for some resting positions")
    return issues



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

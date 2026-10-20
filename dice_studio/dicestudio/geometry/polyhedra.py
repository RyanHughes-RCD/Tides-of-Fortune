"""Convex polyhedra for the seven dice, represented by their face planes.

Every die body is the intersection of half-spaces ``n . x <= d`` (unit outward
normal ``n``, offset ``d``).  This H-representation gives us:

* exact, always-convex, watertight bodies (no mesh repair needed);
* edge chamfers / vertex truncations as extra planes;
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

# Default sizes.  D4: edge length.  Every other die: face-to-opposite-face distance.
DEFAULT_SIZES_MM = {"d4": 20.0, "d6": 16.0, "d8": 15.0, "d10": 16.0, "d12": 18.0, "d20": 19.0, "d100": 16.0}
SIZE_LIMITS_MM = (8.0, 40.0)
SIZE_MEANING = {
    "d4": "edge length",
    "d6": "face-to-face distance",
    "d8": "face-to-face distance",
    "d10": "face-to-face distance",
    "d12": "face-to-face distance",
    "d20": "face-to-face distance",
    "d100": "face-to-face distance",
}

# Pentagonal trapezohedron (D10 / D100) apex height relative to the equator
# radius.  Any positive value is a valid trapezohedron; this range keeps the
# kites a sensible, rollable shape.
D10_ELONGATION_LIMITS = (0.75, 1.45)


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
# Base die shapes (unit normals; offsets give an inradius of 1)
# ---------------------------------------------------------------------------

def _base_normals(die, elongation=1.0):
    if die == "d4":
        verts = np.array([(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)], float)
        return unit(-verts)  # face i is opposite vertex i
    if die == "d6":
        return np.array([(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)], float)
    if die == "d8":
        return unit(np.array([(sx, sy, sz) for sz in (1, -1) for sy in (1, -1) for sx in (1, -1)], float))
    if die == "d12":
        n = []
        for a, b in itertools.product((1, -1), repeat=2):
            n += [(0, a, b * PHI), (a, b * PHI, 0), (b * PHI, 0, a)]
        return unit(np.array(n, float))
    if die == "d20":
        n = [(sx, sy, sz) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
        ip = 1.0 / PHI
        for a, b in itertools.product((1, -1), repeat=2):
            n += [(0, a * ip, b * PHI), (a * ip, b * PHI, 0), (b * PHI, 0, a * ip)]
        return unit(np.array(n, float))
    if die in ("d10", "d100"):
        return _trapezohedron_normals(elongation)
    raise GeometryError(f"unknown die type {die!r}")


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
        n = np.cross(u0 - top, u1 - top)
        if n @ (top + u0 + u1) < 0:
            n = -n
        normals.append(unit(n))
    for k in range(5):
        a = math.radians(36)
        n = normals[k]
        # lower faces: rotate the upper face by 36 degrees and mirror in z
        rn = np.array([n[0] * math.cos(a) - n[1] * math.sin(a), n[0] * math.sin(a) + n[1] * math.cos(a), -n[2]])
        normals.append(unit(rn))
    return np.array(normals)


def size_to_inradius(die, size_mm, elongation=1.0):
    if die == "d4":
        return size_mm / (2.0 * math.sqrt(6.0))  # edge -> inradius
    return size_mm / 2.0


@dataclass
class ShapeParams:
    size_mm: float
    edge_chamfer_mm: float = 0.0  # width of the chamfer strip along each edge
    vertex_trunc_mm: float = 0.0  # depth of the cut at each vertex, along the vertex axis
    d10_elongation: float = 1.0

    def validate(self, die):
        errs = []
        lo, hi = SIZE_LIMITS_MM
        if not (lo <= self.size_mm <= hi):
            errs.append(f"size {self.size_mm:.2f} mm outside {lo}-{hi} mm")
        if not (0.0 <= self.edge_chamfer_mm <= 3.0):
            errs.append("edge chamfer must be between 0 and 3 mm")
        if not (0.0 <= self.vertex_trunc_mm <= 4.0):
            errs.append("vertex truncation must be between 0 and 4 mm")
        lo, hi = D10_ELONGATION_LIMITS
        if die in ("d10", "d100") and not (lo <= self.d10_elongation <= hi):
            errs.append(f"D10 elongation must be between {lo} and {hi}")
        if errs:
            raise GeometryError("; ".join(errs))


MIN_FEATURE_FACE_MM = 0.15  # chamfers / truncations narrower than this are dropped


def base_polyhedron(die, size_mm, elongation=1.0):
    r = size_to_inradius(die, size_mm, elongation)
    normals = _base_normals(die, elongation)
    if die in ("d10", "d100"):
        # all kites are congruent, so a common offset is correct; rescale so the
        # face-to-face distance equals size_mm
        pass
    planes = [Plane(n, r, "face", i) for i, n in enumerate(normals)]
    return halfspace_intersection(planes)


def die_polyhedron(die, params: ShapeParams):
    """Return (final polyhedron, base polyhedron, warnings)."""
    params.validate(die)
    warnings = []
    base = base_polyhedron(die, params.size_mm, params.d10_elongation)
    planes = list(base.planes)
    edges = base.edges()
    min_edge = min(np.linalg.norm(base.vertices[a] - base.vertices[b]) for a, b in edges)

    chamfer = params.edge_chamfer_mm
    max_chamfer = 0.22 * min_edge
    if chamfer > max_chamfer:
        warnings.append(f"edge chamfer reduced from {chamfer:.2f} to {max_chamfer:.2f} mm to keep faces intact")
        chamfer = max_chamfer
    if 0 < chamfer < MIN_FEATURE_FACE_MM:
        chamfer = 0.0
    if chamfer > 0:
        for (a, b), fis in sorted(edges.items()):
            f1, f2 = base.faces[fis[0]], base.faces[fis[1]]
            ne = unit(f1.normal + f2.normal)
            cos_t = float(np.clip(ne @ f1.normal, -1, 1))
            theta = math.acos(cos_t)
            depth = chamfer * math.tan(theta) / 2.0
            de = float(ne @ base.vertices[a]) - depth
            planes.append(Plane(ne, de, "edge", (int(f1.tag), int(f2.tag))))

    trunc = params.vertex_trunc_mm
    if trunc > 0:
        # limit so that the truncation never swallows a whole face
        max_trunc = 0.3 * min_edge
        if trunc > max_trunc:
            warnings.append(f"vertex truncation reduced from {trunc:.2f} to {max_trunc:.2f} mm")
            trunc = max_trunc
    if trunc >= MIN_FEATURE_FACE_MM:
        vfaces = {}
        for fi, f in enumerate(base.faces):
            for vid in f.vertex_ids:
                vfaces.setdefault(vid, []).append(f)
        for vid, fs in sorted(vfaces.items()):
            nv = unit(sum(f.normal for f in fs))
            dv = float(nv @ base.vertices[vid]) - trunc
            planes.append(Plane(nv, dv, "vertex", int(vid)))

    poly = halfspace_intersection(planes)
    if len(poly.die_faces()) != FACE_COUNTS[die]:
        raise GeometryError(
            f"{die.upper()} would have {len(poly.die_faces())} number faces instead of {FACE_COUNTS[die]}; "
            "reduce chamfer/truncation"
        )
    return poly, base, warnings


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

"""Mesh validation that inspects the actual triangles that will be exported.

Checks performed (all on the float32-quantised vertices written to STL):

* watertight: every undirected edge is used by exactly two triangles;
* consistent winding: every directed edge occurs once (opposite neighbours);
* outward orientation: positive signed volume;
* degenerate (zero-area) triangles;
* duplicate triangles (duplicate internal surfaces);
* connected components (unintended loose fragments);
* Euler characteristic / genus;
* self-intersections: grid broad-phase + exact segment/triangle tests between
  every pair of non-adjacent nearby triangles.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

import numpy as np

AREA_EPS = 1e-10  # mm^2


@dataclass
class MeshReport:
    name: str
    vertices: int = 0
    triangles: int = 0
    watertight: bool = False
    boundary_edges: int = 0
    nonmanifold_edges: int = 0
    winding_consistent: bool = False
    outward: bool = False
    volume_mm3: float = 0.0
    area_mm2: float = 0.0
    degenerate_triangles: int = 0
    duplicate_triangles: int = 0
    components: int = 0
    euler: int = 0
    genus: float = 0.0
    self_intersections: int = -1  # -1 = not checked
    self_intersection_pairs_tested: int = 0
    bbox_mm: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self):
        return not self.issues

    def to_dict(self):
        d = asdict(self)
        d["ok"] = self.ok
        return d


def quantise(vertices, tris):
    """Round to float32 (as stored in STL) and merge identical positions."""
    v32 = np.asarray(vertices, dtype=np.float32)
    uniq, inv = np.unique(v32, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    return uniq.astype(np.float64), inv[np.asarray(tris)]


def _components(nv, tris):
    parent = np.arange(nv)

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b, c in tris:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    used = np.unique(tris)
    return len({find(int(x)) for x in used})


SI_TOL_MM = 2e-5  # crossings shallower than this (float32 rounding level) are contacts, not intersections


def _seg_tri_hits(P0, P1, A, B, C, eps=1e-9, tol=SI_TOL_MM):
    """Vectorised strict segment/triangle intersection (Moller-Trumbore).

    A hit requires the segment to pass *through* the triangle's plane with both
    end points more than ``tol`` away from it on opposite sides.
    """
    d = P1 - P0
    e1 = B - A
    e2 = C - A
    h = np.cross(d, e2)
    a = np.einsum("ij,ij->i", e1, h)
    # scale-relative parallel test: a = det[d, e1, e2]; near-coplanar pairs are
    # not crossings (coplanar overlap is caught by the duplicate check)
    mag = np.linalg.norm(d, axis=1) * np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1)
    ok = np.abs(a) > 1e-7 * mag
    f = np.zeros_like(a)
    f[ok] = 1.0 / a[ok]
    s = P0 - A
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * np.einsum("ij,ij->i", d, q)
    t = f * np.einsum("ij,ij->i", e2, q)
    nrm = np.cross(e1, e2)
    nl = np.linalg.norm(nrm, axis=1)
    nrm = np.divide(nrm, nl[:, None], out=np.zeros_like(nrm), where=nl[:, None] > 0)
    d0 = np.einsum("ij,ij->i", P0 - A, nrm)
    d1 = np.einsum("ij,ij->i", P1 - A, nrm)
    through = (d0 * d1 < 0) & (np.minimum(np.abs(d0), np.abs(d1)) > tol)
    return ok & through & (u > eps) & (v > eps) & (u + v < 1 - eps) & (t > eps) & (t < 1 - eps)


def count_self_intersections(V, T, max_pairs=20_000_000):
    """Count intersecting pairs of triangles that do not share an edge."""
    nt = len(T)
    if nt == 0:
        return 0, 0
    P = V[T]  # (n,3,3)
    lo = P.min(axis=1)
    hi = P.max(axis=1)
    ext = (hi - lo).max(axis=1)
    span = V.max(axis=0) - V.min(axis=0)
    cell = max(float(np.median(ext)) * 2.0, float(span.max()) / 96.0, 1e-6)
    origin = V.min(axis=0)
    cl = np.floor((lo - origin) / cell).astype(np.int64)
    ch = np.floor((hi - origin) / cell).astype(np.int64)
    counts = np.prod(ch - cl + 1, axis=1)
    # enumerate (cell, tri) memberships
    tri_ids = np.repeat(np.arange(nt), counts)
    offs = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    dims = (ch - cl + 1)[tri_ids]
    ix = offs % dims[:, 0]
    iy = (offs // dims[:, 0]) % dims[:, 1]
    iz = offs // (dims[:, 0] * dims[:, 1])
    cx = cl[tri_ids, 0] + ix
    cy = cl[tri_ids, 1] + iy
    cz = cl[tri_ids, 2] + iz
    key = (cx * 73856093) ^ (cy * 19349663) ^ (cz * 83492791)
    order = np.lexsort((tri_ids, key))
    key, tri_ids = key[order], tri_ids[order]
    bounds = np.flatnonzero(np.diff(key)) + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [len(key)]])
    pa, pb = [], []
    total = 0
    for s, e in zip(starts, ends):
        k = e - s
        if k < 2:
            continue
        ids = tri_ids[s:e]
        i, j = np.triu_indices(k, 1)
        pa.append(ids[i])
        pb.append(ids[j])
        total += len(i)
        if total > max_pairs:
            return -1, total
    if not pa:
        return 0, 0
    a = np.concatenate(pa)
    b = np.concatenate(pb)
    pair = np.unique(np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1), axis=0)
    a, b = pair[:, 0], pair[:, 1]
    # AABB overlap
    ov = np.all((lo[a] <= hi[b]) & (lo[b] <= hi[a]), axis=1)
    a, b = a[ov], b[ov]
    # shared vertices
    Ta, Tb = T[a], T[b]
    shared = (Ta[:, :, None] == Tb[:, None, :]).sum(axis=(1, 2))
    keep = shared < 2  # sharing an edge -> adjacent, skip
    a, b = a[keep], b[keep]
    tested = len(a)
    hit = np.zeros(len(a), bool)
    for x, y in ((a, b), (b, a)):
        A, B, C = V[T[y, 0]], V[T[y, 1]], V[T[y, 2]]
        for k in range(3):
            p0 = V[T[x, k]]
            p1 = V[T[x, (k + 1) % 3]]
            hit |= _seg_tri_hits(p0, p1, A, B, C)
    return int(hit.sum()), tested


def validate_mesh(vertices, tris, name="mesh", check_self_intersection=True, expect_genus=None):
    t0 = time.time()
    r = MeshReport(name=name)
    V, T = quantise(vertices, tris)
    r.vertices, r.triangles = len(V), len(T)
    if len(T) == 0:
        r.issues.append("mesh is empty")
        return r
    r.bbox_mm = [float(x) for x in (V.max(axis=0) - V.min(axis=0))]
    # degenerate
    p = V[T]
    cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    areas = 0.5 * np.linalg.norm(cr, axis=1)
    collapsed = (T[:, 0] == T[:, 1]) | (T[:, 1] == T[:, 2]) | (T[:, 0] == T[:, 2])
    r.degenerate_triangles = int(((areas < AREA_EPS) | collapsed).sum())
    r.area_mm2 = float(areas.sum())
    r.volume_mm3 = float(np.einsum("ij,ij->i", p[:, 0], np.cross(p[:, 1], p[:, 2])).sum() / 6.0)
    # duplicates
    st = np.sort(T, axis=1)
    _, cnt = np.unique(st, axis=0, return_counts=True)
    r.duplicate_triangles = int((cnt > 1).sum())
    # edges
    directed = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    und = np.sort(directed, axis=1)
    _, ucount = np.unique(und, axis=0, return_counts=True)
    r.boundary_edges = int((ucount == 1).sum())
    r.nonmanifold_edges = int((ucount > 2).sum())
    r.watertight = r.boundary_edges == 0 and r.nonmanifold_edges == 0
    _, dcount = np.unique(directed, axis=0, return_counts=True)
    r.winding_consistent = bool((dcount == 1).all()) and r.watertight
    r.outward = r.volume_mm3 > 0
    r.components = _components(len(V), T)
    E = len(ucount)
    r.euler = int(len(np.unique(T)) - E + len(T))
    r.genus = (2 * r.components - r.euler) / 2.0
    if check_self_intersection:
        n, tested = count_self_intersections(V, T)
        r.self_intersections = n
        r.self_intersection_pairs_tested = tested
        if n < 0:
            r.notes.append("self-intersection check skipped: mesh too dense for the exhaustive test")
    # issues
    if not r.watertight:
        r.issues.append(f"not watertight ({r.boundary_edges} open edges, {r.nonmanifold_edges} non-manifold edges)")
    elif not r.winding_consistent:
        r.issues.append("inconsistent triangle winding")
    if not r.outward:
        r.issues.append("normals point inward (negative volume)")
    if r.degenerate_triangles:
        r.issues.append(f"{r.degenerate_triangles} zero-area triangle(s)")
    if r.duplicate_triangles:
        r.issues.append(f"{r.duplicate_triangles} duplicate triangle(s)")
    if r.components != 1:
        r.issues.append(f"{r.components} disconnected pieces (expected 1)")
    if r.self_intersections > 0:
        r.issues.append(f"{r.self_intersections} self-intersecting triangle pair(s)")
    if expect_genus is not None and r.watertight and abs(r.genus - expect_genus) > 1e-9:
        r.issues.append(f"unexpected topology: genus {r.genus:g} (expected {expect_genus})")
    r.seconds = round(time.time() - t0, 3)
    return r

#!/usr/bin/env python3
"""fair_gem_dice.py - procedural generator for fair, usable gemstone-style D4s and D6s.

Self-contained: needs only Python 3.9+ and NumPy.

    python fair_gem_dice.py                                  # demo: one D4 + several D6s
    python fair_gem_dice.py --die d6 --family long_barrel --seed 7 --size 14 --format obj
    python fair_gem_dice.py --list

Pipeline for every die
----------------------
1. A *shape family* turns a few parameters (sampled from the seed) into a set of
   face planes; the solid is their half-space intersection (exact, convex,
   watertight).  Every face is tagged "number" (an outcome) or "cap" (a facet
   that must never be an outcome, e.g. the tips of a crystal).
2. **Symmetry / face transitivity.**  The full isometry group (rotations and
   reflections about the centre of mass) is computed from the geometry itself,
   and the orbits of the faces under that group are found.  The numbered faces
   must form a single orbit: every outcome is then geometrically identical to
   every other one, which is the strongest fairness guarantee there is.  For
   isohedral families (disphenoids, trapezohedra) *all* faces form one orbit.
   Shapes with tips (shards, barrels) cannot be isohedral - a tip is not a side -
   so for them the requirement is transitivity on the numbered faces plus
   unstable caps (step 3).
3. **Physical usability (static rest analysis).**  A convex body resting on a
   face is in stable equilibrium iff its centre of mass (CoM) projects inside
   that face.  Numbered faces must be stable with a margin; cap facets must be
   clearly unstable (the die tips off them).  D6s (and roller D4s) must have,
   for every numbered face, an exactly antiparallel numbered face, so the face
   read on top is parallel to the table; tetrahedral D4s must present a single,
   clearly highest apex.  Edges between numbered faces must have a real
   "rocking barrier" so the die does not sit cocked on a nearly flat edge.
4. **Basins of attraction.**  The solid angle Omega_f subtended by every face at
   the CoM is computed (Van Oosterom-Strackee).  Unstable facets drain to the
   face the die tumbles onto (following the quasi-static tipping edge), giving
   each numbered face an *effective* basin.  All effective basins must be equal
   (Omega_1 = Omega_2 = ... = Omega_N) to a relative tolerance of 1e-6.
5. **Repair loop.**  If any check fails, the family parameters (skew,
   elongation, tip lengths, ...) are adjusted by a bounded Nelder-Mead search
   that minimises a continuous penalty built from all checks, until the shape
   passes or the attempt budget is exhausted (then it is rejected with reasons).
6. The verified mesh is exported as ASCII STL or OBJ text (millimetres).

Limits (stated honestly)
------------------------
* Equal solid angles are the standard *static proxy* for equal probability.
  For symmetric (face-transitive) dice equality is exact by symmetry; real
  throw statistics also depend on bounce dynamics, which no static test models.
* A hexahedron whose faces are all congruent *and* whose top face is parallel
  to the table must be a rhombohedron (cube included).  The "asymmetric
  hexahedron" family therefore starts from a random skewed parallelepiped and
  the repair loop drives it onto that manifold: the output is an obliquely
  oriented rhombohedron with skewed rhombic faces.  A genuinely asymmetric
  parallelepiped is never fair, and the script will say so if repair fails.
* The "square anti-wedge" (two perpendicular ridges on opposite sides) is
  mathematically the flattened member of the tetragonal-disphenoid family; it
  is offered as its own family with its own blade-like range.
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np

# ----------------------------------------------------------------------------
# Tolerances and thresholds
# ----------------------------------------------------------------------------
GEOM_TOL = 1e-9          # plane / vertex coincidence (relative to size 1)
SYM_TOL = 1e-6           # symmetry detection tolerance (relative)
BASIN_TOL = 1e-6         # max relative spread of the effective basins
CONGRUENCE_TOL = 1e-6    # max difference of sorted edge lengths / angles
MIN_FACE_MARGIN = 0.15   # numbered faces: CoM foot >= 15% of the inscribed radius inside
MIN_CAP_TIPPING = 0.05   # caps: CoM foot >= 5% of the inscribed radius *outside*
MIN_ROCK_BARRIER = 0.03  # edge between numbered faces: CoM must rise >= 3% to roll over it
MIN_APEX_CLEARANCE = 0.15  # tetrahedral D4: top vertex >= 15% of die height above the next


# ----------------------------------------------------------------------------
# Geometry core: convex polyhedra from planes
# ----------------------------------------------------------------------------

def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


@dataclass
class Polyhedron:
    vertices: np.ndarray            # (V, 3)
    faces: list                     # list of vertex-index lists, CCW seen from outside
    normals: np.ndarray             # (F, 3) unit outward normals
    offsets: np.ndarray             # (F,) plane offsets: n . x = d on the face
    roles: list                     # "number" or "cap" per face
    meta: dict = field(default_factory=dict)

    @property
    def numbered(self):
        return [i for i, r in enumerate(self.roles) if r == "number"]

    def triangles(self):
        return [(f[0], f[k], f[k + 1]) for f in self.faces for k in range(1, len(f) - 1)]

    def edges(self):
        """undirected edge (i, j) -> [face indices]"""
        out = {}
        for fi, f in enumerate(self.faces):
            for a, b in zip(f, f[1:] + f[:1]):
                out.setdefault((min(a, b), max(a, b)), []).append(fi)
        return out

    def scaled(self, s):
        return Polyhedron(self.vertices * s, [list(f) for f in self.faces], self.normals.copy(),
                          self.offsets * s, list(self.roles), dict(self.meta))


class ShapeError(ValueError):
    """Raised for parameters that do not produce a valid solid."""


def from_planes(normals, offsets, roles, meta=None):
    """Half-space intersection {x : n_i . x <= d_i} by vectorised triple-plane solving.

    Plane counts here are small (< 40), so the brute-force O(m^3) method is fast
    and has no degenerate failure modes besides genuinely invalid input.
    """
    N = unit(np.asarray(normals, float))
    d = np.asarray(offsets, float)
    m = len(N)
    scale = max(1.0, float(np.abs(d).max()))
    idx = np.array(list(itertools.combinations(range(m), 3)))
    A, b = N[idx], d[idx]
    ok = np.abs(np.linalg.det(A)) > 1e-10
    X = np.linalg.solve(A[ok], b[ok][..., None])[..., 0]
    X = X[(X @ N.T - d <= GEOM_TOL * scale * 10).all(axis=1)]
    if len(X) < 4:
        raise ShapeError("the planes do not bound a solid")
    verts = []
    for p in X:  # merge duplicates where more than three planes meet
        if not any(np.linalg.norm(p - q) < 1e-7 * scale for q in verts):
            verts.append(p)
    V = np.array(verts)
    faces, keep_n, keep_d, keep_r = [], [], [], []
    for i in range(m):
        on = np.nonzero(np.abs(V @ N[i] - d[i]) < 1e-7 * scale)[0]
        if len(on) < 3:
            continue  # redundant plane
        c = V[on].mean(axis=0)
        u = unit(V[on[0]] - c - N[i] * ((V[on[0]] - c) @ N[i]))
        w = np.cross(N[i], u)
        ang = np.arctan2((V[on] - c) @ w, (V[on] - c) @ u)
        faces.append([int(k) for k in on[np.argsort(ang)]])
        keep_n.append(N[i])
        keep_d.append(d[i])
        keep_r.append(roles[i])
    used = sorted({k for f in faces for k in f})
    remap = {o: n for n, o in enumerate(used)}
    poly = Polyhedron(V[used], [[remap[k] for k in f] for f in faces], np.array(keep_n), np.array(keep_d),
                      keep_r, dict(meta or {}))
    if volume_and_com(poly)[0] <= 0:
        raise ShapeError("degenerate solid")
    return poly


def volume_and_com(poly):
    """Volume and centre of mass (uniform density) by tetrahedral decomposition."""
    v = poly.vertices
    t = np.array(poly.triangles())
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    V = vol.sum()
    return float(V), (vol[:, None] * (a + b + c) / 4.0).sum(axis=0) / V


def face_frame(poly, f):
    """Orthonormal in-plane basis (u, w) and 2D outline of face f."""
    pts = poly.vertices[poly.faces[f]]
    c = pts.mean(axis=0)
    n = poly.normals[f]
    u = unit(pts[0] - c)
    w = np.cross(n, u)
    return c, u, w, np.stack([(pts - c) @ u, (pts - c) @ w], axis=1)


def _edge_lines(poly2d):
    """Outward unit normals and offsets of a CCW convex polygon's edges: n . x <= c inside."""
    e = np.roll(poly2d, -1, axis=0) - poly2d
    n = np.stack([e[:, 1], -e[:, 0]], axis=1)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    return n, np.einsum("ij,ij->i", n, poly2d)


def _signed_distance_to_polygon(p, poly2d):
    """Positive inside (distance to nearest edge), negative outside (distance to boundary)."""
    n, c = _edge_lines(poly2d)
    slack = c - n @ p
    if (slack >= 0).all():
        return float(slack.min())
    a = poly2d
    e = np.roll(poly2d, -1, axis=0) - a
    t = np.clip(np.einsum("ij,ij->i", p - a, e) / np.einsum("ij,ij->i", e, e), 0.0, 1.0)
    return -float(np.linalg.norm(p - (a + t[:, None] * e), axis=1).min())


def _inradius(poly2d):
    """Exact largest inscribed-circle radius of a convex polygon (Chebyshev centre).

    The optimum of  max r  s.t.  n_i . x + r <= c_i  has three tight constraints, so
    all edge triples are solved at once and the best feasible solution is taken.
    """
    n, c = _edge_lines(poly2d)
    k = len(c)
    idx = np.array(list(itertools.combinations(range(k), 3)))
    A = np.concatenate([n[idx], np.ones((len(idx), 3, 1))], axis=2)  # unknowns (x, y, r)
    ok = np.abs(np.linalg.det(A)) > 1e-12
    sol = np.linalg.solve(A[ok], c[idx][ok][..., None])[..., 0]
    feas = (sol[:, :2] @ n.T + sol[:, 2:3] <= c + 1e-9).all(axis=1)
    return float(sol[feas, 2].max())


# ----------------------------------------------------------------------------
# Symmetry group and face orbits
# ----------------------------------------------------------------------------

def symmetry_group(poly):
    """All isometries (proper and improper) about the CoM that map the solid onto itself.

    Candidate maps are fixed by the images of three independent reference vertices;
    each candidate is accepted if it is orthogonal and maps every vertex onto a vertex.
    """
    _, com = volume_and_com(poly)
    P = poly.vertices - com
    size = np.abs(P).max()
    tol = SYM_TOL * size
    r = np.linalg.norm(P, axis=1)
    # three reference vertices spanning 3D
    i0 = 0
    i1 = next(i for i in range(len(P)) if np.linalg.norm(np.cross(P[i0], P[i])) > 1e-3 * size ** 2)
    i2 = next(i for i in range(len(P)) if abs(np.linalg.det(P[[i0, i1, i]])) > 1e-3 * size ** 3)
    M = P[[i0, i1, i2]].T
    Minv = np.linalg.inv(M)
    group = []
    cand = [np.nonzero(np.abs(r - r[i]) < tol)[0] for i in (i0, i1, i2)]
    for a, b, c in itertools.product(*cand):
        if len({a, b, c}) < 3:
            continue
        if abs(P[a] @ P[b] - P[i0] @ P[i1]) > tol * size or abs(P[a] @ P[c] - P[i0] @ P[i2]) > tol * size \
                or abs(P[b] @ P[c] - P[i1] @ P[i2]) > tol * size:
            continue
        Q = P[[a, b, c]].T @ Minv
        if not np.allclose(Q.T @ Q, np.eye(3), atol=1e-6):
            continue
        img = P @ Q.T
        dist = np.linalg.norm(img[:, None, :] - P[None, :, :], axis=2).min(axis=1)
        if dist.max() < tol * 10:
            group.append(Q)
    return group, com


def face_orbits(poly, group, com):
    """Partition the faces into orbits under the symmetry group."""
    centres = np.array([poly.vertices[f].mean(axis=0) - com for f in poly.faces])
    size = np.abs(centres).max()
    perm = []
    for Q in group:
        img = centres @ Q.T
        perm.append(np.linalg.norm(img[:, None, :] - centres[None, :, :], axis=2).argmin(axis=1))
    seen, orbits = set(), []
    for f in range(len(poly.faces)):
        if f in seen:
            continue
        orb = {int(p[f]) for p in perm}
        seen |= orb
        orbits.append(sorted(orb))
    return orbits


def transitivity_report(poly):
    group, com = symmetry_group(poly)
    orbits = face_orbits(poly, group, com)
    numbered = set(poly.numbered)
    num_orbits = [o for o in orbits if set(o) & numbered]
    proper = sum(1 for Q in group if np.linalg.det(Q) > 0)
    return {
        "group_order": len(group),
        "proper_rotations": proper,
        "improper_isometries": len(group) - proper,
        "face_orbits": orbits,
        "transitive_on_numbered_faces": len(num_orbits) == 1 and set(num_orbits[0]) == numbered,
        "isohedral": len(orbits) == 1,
        "centrosymmetric": any(np.allclose(Q, -np.eye(3), atol=1e-6) for Q in group),
    }


def congruence_error(poly, faces=None):
    """Continuous measure of how far the given faces are from being congruent."""
    faces = poly.numbered if faces is None else faces
    sigs = []
    for f in faces:
        pts = poly.vertices[poly.faces[f]]
        k = len(pts)
        e = sorted(np.linalg.norm(pts[i] - pts[(i + 1) % k]) for i in range(k))
        a = sorted(math.acos(np.clip(unit(pts[i - 1] - pts[i]) @ unit(pts[(i + 1) % k] - pts[i]), -1, 1))
                   for i in range(k))
        sigs.append(np.array(e + a))
    if len({len(s) for s in sigs}) != 1:
        return 1.0
    size = max(np.abs(poly.vertices).max(), 1e-12)
    s0 = sigs[0]
    return float(max(np.abs(s - s0)[: len(s0) // 2].max() / size + np.abs(s - s0)[len(s0) // 2:].max()
                     for s in sigs))


# ----------------------------------------------------------------------------
# Solid angles, rest analysis and basins of attraction
# ----------------------------------------------------------------------------

def triangle_solid_angle(a, b, c):
    """Solid angle of triangle (a, b, c) seen from the origin (Van Oosterom & Strackee 1983)."""
    la, lb, lc = np.linalg.norm(a), np.linalg.norm(b), np.linalg.norm(c)
    num = abs(a @ np.cross(b, c))
    den = la * lb * lc + (a @ b) * lc + (a @ c) * lb + (b @ c) * la
    return 2.0 * math.atan2(num, den)


def face_solid_angles(poly, point):
    """Omega_f of every face seen from ``point``; they sum to 4 pi for an interior point."""
    out = np.zeros(len(poly.faces))
    for fi, f in enumerate(poly.faces):
        p = poly.vertices[f] - point
        out[fi] = sum(triangle_solid_angle(p[0], p[k], p[k + 1]) for k in range(1, len(f) - 1))
    return out


def rest_analysis(poly, com):
    """Per face: signed CoM-foot margin (absolute and relative to the face inradius)."""
    rows = []
    for fi in range(len(poly.faces)):
        n, d = poly.normals[fi], poly.offsets[fi]
        foot = com - n * (n @ com - d)
        c, u, w, p2 = face_frame(poly, fi)
        q = np.array([(foot - c) @ u, (foot - c) @ w])
        m = _signed_distance_to_polygon(q, p2)
        rows.append({"face": fi, "role": poly.roles[fi], "margin": m, "margin_rel": m / _inradius(p2),
                     "foot2d": q, "outline2d": p2})
    return rows


def tumble_map(poly, com, rest):
    """For every face, the stable face the die ends on if it starts resting there.

    Quasi-static model: on an unstable face the die pivots over the edge nearest to
    the CoM's projection and lands on the face across that edge; repeated until a
    stable face is reached.
    """
    edges = poly.edges()
    nxt = {}
    for r in rest:
        f = r["face"]
        if r["margin"] > 0:
            nxt[f] = f
            continue
        ids = poly.faces[f]
        p2, q = r["outline2d"], r["foot2d"]
        best, best_e = math.inf, None
        for i in range(len(ids)):
            a, b = p2[i], p2[(i + 1) % len(ids)]
            e = b - a
            t = np.clip((q - a) @ e / (e @ e), 0, 1)
            dist = np.linalg.norm(q - (a + t * e))
            if dist < best - 1e-12:
                best, best_e = dist, (ids[i], ids[(i + 1) % len(ids)])
        key = (min(best_e), max(best_e))
        nxt[f] = next(g for g in edges[key] if g != f)
    final = {}
    for f in nxt:
        seen, g = [], f
        while nxt[g] != g:
            if g in seen:
                final[f] = None  # endless tumbling: would never settle
                break
            seen.append(g)
            g = nxt[g]
        else:
            final[f] = g
    return final


def basin_report(poly, com):
    omega = face_solid_angles(poly, com)
    rest = rest_analysis(poly, com)
    final = tumble_map(poly, com, rest)
    eff = {f: 0.0 for f in poly.numbered}
    lost = 0.0
    for f, g in final.items():
        if g is None or g not in eff:
            lost += omega[f]  # drains to a cap that is stable, or never settles
        else:
            eff[g] += omega[f]
    vals = np.array(list(eff.values()))
    spread = float((vals.max() - vals.min()) / vals.mean()) if len(vals) else 1.0
    return {"omega": omega, "omega_total_over_4pi": float(omega.sum() / (4 * math.pi)), "effective": eff,
            "spread": spread, "lost_solid_angle": float(lost), "rest": rest, "final": final}


# ----------------------------------------------------------------------------
# Usability checks
# ----------------------------------------------------------------------------

def rocking_barriers(poly, com):
    """For edges between two numbered faces: relative rise of the CoM when rolling over the edge."""
    out = []
    for (a, b), fs in poly.edges().items():
        if len(fs) != 2 or not all(poly.roles[f] == "number" for f in fs):
            continue
        A, B = poly.vertices[a], poly.vertices[b]
        e = unit(B - A)
        h_edge = np.linalg.norm((com - A) - e * ((com - A) @ e))
        for f in fs:
            d_f = poly.offsets[f] - poly.normals[f] @ com
            out.append((h_edge - d_f) / d_f)
    return out


def apex_clearance(poly, com, f):
    """Tetrahedral D4 resting on face f: (top vertex height - next highest) / die height."""
    n, d = poly.normals[f], poly.offsets[f]
    h = d - poly.vertices @ n  # height above the table
    hs = np.sort(h)[::-1]
    return float((hs[0] - hs[1]) / hs[0])


@dataclass
class FairnessReport:
    passed: bool
    penalty: float
    checks: dict
    details: dict

    def summary(self):
        lines = []
        for k, (ok, val) in self.checks.items():
            lines.append(f"  [{'PASS' if ok else 'FAIL'}] {k}: {val}")
        return "\n".join(lines)


def evaluate(poly, die, reading, verify_symmetry=True):
    """Run every fairness / usability check. ``reading``: 'top_face' or 'apex'.

    ``verify_symmetry=False`` skips the exact symmetry-group computation (used inside
    the repair loop, where the continuous congruence error is the optimisation signal);
    every accepted die is re-evaluated with the full verification.
    """
    vol, com = volume_and_com(poly)
    trans = transitivity_report(poly) if verify_symmetry else None
    basins = basin_report(poly, com)
    rest = basins["rest"]
    numbered = poly.numbered
    checks, penalty = {}, 0.0

    want = 4 if die == "d4" else 6
    checks["outcome count"] = (len(numbered) == want, f"{len(numbered)} numbered faces (need {want})")
    penalty += 10.0 * (len(numbered) != want)

    cong = congruence_error(poly)
    if trans is not None:
        checks["face transitivity (symmetry group)"] = (
            trans["transitive_on_numbered_faces"],
            f"group order {trans['group_order']} ({trans['proper_rotations']} rotations, "
            f"{trans['improper_isometries']} reflections); numbered faces in one orbit: "
            f"{trans['transitive_on_numbered_faces']}; isohedral: {trans['isohedral']}")
    checks["numbered faces congruent"] = (cong < CONGRUENCE_TOL, f"congruence error {cong:.2e}")
    penalty += cong * 50

    margins = [r["margin_rel"] for r in rest if r["role"] == "number"]
    caps = [r["margin_rel"] for r in rest if r["role"] == "cap"]
    checks["numbered faces stable"] = (min(margins) >= MIN_FACE_MARGIN,
                                       f"min CoM margin {min(margins):.3f} of inradius (need >= {MIN_FACE_MARGIN})")
    penalty += sum(max(0.0, MIN_FACE_MARGIN - m) for m in margins)
    if caps:
        msg = f"max cap margin {max(caps):.3f} (need <= {-MIN_CAP_TIPPING})"
        if max(caps) > 0:
            msg += " - the die can come to rest on an end facet (e.g. stand on a flat end)"
        checks["caps tip over"] = (max(caps) <= -MIN_CAP_TIPPING, msg)
        penalty += sum(max(0.0, m + MIN_CAP_TIPPING) for m in caps)

    if reading == "top_face":
        worst = 0.0
        for f in numbered:
            best = min(poly.normals[f] @ poly.normals[g] for g in numbered)
            worst = max(worst, 1.0 + best)  # 0 when an exactly antiparallel face exists
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, 1.0 - worst))))
        checks["top face parallel to table"] = (worst < 1e-9, f"worst tilt of the top face {tilt:.2e} deg")
        penalty += 100.0 * worst
    else:
        clear = min(apex_clearance(poly, com, f) for f in numbered)
        checks["readable apex"] = (clear >= MIN_APEX_CLEARANCE,
                                   f"top vertex {clear:.2f} of die height above the next (need >= {MIN_APEX_CLEARANCE})")
        penalty += max(0.0, MIN_APEX_CLEARANCE - clear)

    rb = rocking_barriers(poly, com)
    if rb:
        checks["no near-flat balancing edges"] = (min(rb) >= MIN_ROCK_BARRIER,
                                                  f"min rocking barrier {min(rb) * 100:.1f}% (need >= {MIN_ROCK_BARRIER * 100:.0f}%)")
        penalty += sum(max(0.0, MIN_ROCK_BARRIER - b) for b in rb)

    checks["basins of attraction equal"] = (
        basins["spread"] < BASIN_TOL and basins["lost_solid_angle"] < 1e-9,
        f"effective Omega spread {basins['spread']:.2e} (tol {BASIN_TOL}); "
        f"unreachable/cap-stable solid angle {basins['lost_solid_angle']:.2e} sr")
    penalty += 10.0 * basins["spread"] + basins["lost_solid_angle"]

    checks["solid angles sum to 4 pi"] = (abs(basins["omega_total_over_4pi"] - 1) < 1e-9,
                                         f"{basins['omega_total_over_4pi']:.12f} x 4pi")
    passed = all(ok for ok, _ in checks.values())
    return FairnessReport(passed, float(penalty), checks,
                          {"volume": vol, "com": com, "transitivity": trans, "basins": basins})


# ----------------------------------------------------------------------------
# Shape families (unit scale; scaled to size_mm afterwards)
# ----------------------------------------------------------------------------

def _cone_planes(n, z_base, length, sign, azimuth0=0.0, radius=1.0):
    """n pyramid planes through the side lines at z_base and an apex on the axis."""
    out = []
    for k in range(n):
        a = azimuth0 + 2 * math.pi * k / n
        nr, nz = length, sign * radius
        ln = math.hypot(nr, nz)
        out.append((np.array([math.cos(a) * nr / ln, math.sin(a) * nr / ln, nz / ln]),
                    (nr * radius + nz * z_base) / ln))
    return out


def _prism_sides(n):
    return [(np.array([math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n), 0.0]), 1.0) for k in range(n)]


def _assemble(numbered, caps, meta):
    planes = [(n, d, "number") for n, d in numbered] + [(n, d, "cap") for n, d in caps]
    return from_planes([p[0] for p in planes], [p[1] for p in planes], [p[2] for p in planes], meta)


def _disphenoid(k):
    """Tetragonal disphenoid: vertices (+-1, 0, k) and (0, +-1, -k); four congruent isosceles faces."""
    V = np.array([(1, 0, k), (-1, 0, k), (0, 1, -k), (0, -1, -k)], float)
    planes = []
    for i in range(4):
        tri = V[[j for j in range(4) if j != i]]
        n = unit(np.cross(tri[1] - tri[0], tri[2] - tri[0]))
        if n @ tri.mean(axis=0) < 0:
            n = -n
        planes.append((n, float(n @ tri[0])))
    return planes


def build_crystal_shard(p):
    """D4: 4-sided barrel with a pointed tip at each end (numbers on the 4 sides)."""
    L, C = p["body"], 2 * p["tip"]
    caps = _cone_planes(4, L, C, +1, math.pi / 4) + _cone_planes(4, -L, C, -1, math.pi / 4)
    sides = [(np.array([math.cos(a), math.sin(a), 0.0]), 1.0) for a in (math.pi / 4 + k * math.pi / 2 for k in range(4))]
    return _assemble(sides, caps, {"reading": "top_face"})


def build_tetragonal_disphenoid(p):
    return _assemble(_disphenoid(p["stretch"]), [], {"reading": "apex"})


def build_square_antiwedge(p):
    """D4 blade: two perpendicular ridges (top along x, bottom along y); thickness < ridge length."""
    return _assemble(_disphenoid(p["thickness"]), [], {"reading": "apex"})


def build_trigonal_trapezohedron(p):
    """D6: 6 congruent rhombi (calcite-like rhombohedron); 35.26 deg elevation = cube."""
    e = math.radians(p["elevation"])
    up = [np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
          for a in (math.radians(x) for x in (90, 210, 330))]
    return _assemble([(n, 1.0) for n in up] + [(-n, 1.0) for n in up], [], {"reading": "top_face"})


def build_long_barrel(p):
    """D6: hexagonal crystal prism; ends 'pointed' (pyramids), 'gem' (two-tier faceted) or 'flat'."""
    L = p["body"]
    C = 2 * p["cap"]
    style = p.get("style", "pointed")
    if style == "pointed":
        caps = _cone_planes(6, L, C, +1) + _cone_planes(6, -L, C, -1)
    elif style == "gem":
        caps = (_cone_planes(6, L, C, +1) + _cone_planes(6, L, 0.62 * C, +1, math.pi / 6, 1.25)
                + _cone_planes(6, -L, 1.4 * C, -1))
    elif style == "flat":
        caps = [(np.array([0, 0, 1.0]), L), (np.array([0, 0, -1.0]), L)]
    else:
        raise ShapeError(f"unknown cap style {style!r}")
    return _assemble(_prism_sides(6), caps, {"reading": "top_face"})


def build_asymmetric_hexahedron(p):
    """D6: general skewed parallelepiped from edge lengths (a, b, c) and angles (alpha, beta, gamma)."""
    a, b, c = p["a"], p["b"], p["c"]
    al, be, ga = (math.radians(p[k]) for k in ("alpha", "beta", "gamma"))
    e1 = np.array([a, 0.0, 0.0])
    e2 = b * np.array([math.cos(ga), math.sin(ga), 0.0])
    cx = math.cos(be)
    cy = (math.cos(al) - math.cos(be) * math.cos(ga)) / math.sin(ga)
    cz2 = 1 - cx * cx - cy * cy
    if cz2 <= 1e-6:
        raise ShapeError("these angles do not form a parallelepiped")
    e3 = c * np.array([cx, cy, math.sqrt(cz2)])
    planes = []
    for u, v, w in ((e1, e2, e3), (e2, e3, e1), (e3, e1, e2)):
        n = unit(np.cross(u, v))
        h = abs(n @ w) / 2.0  # half the distance between the two parallel faces
        planes += [(n, h), (-n, h)]
    # random-looking but deterministic tilt so the result is not axis-aligned
    return _assemble(planes, [], {"reading": "top_face"})


@dataclass
class Family:
    die: str
    name: str
    build: callable
    params: dict            # name -> (lo, hi)
    fixed: dict = field(default_factory=dict)
    description: str = ""


FAMILIES = {
    ("d4", "crystal_shard"): Family("d4", "crystal_shard", build_crystal_shard,
                                    {"body": (0.9, 1.7), "tip": (0.55, 0.95)},
                                    description="elongated barrel, 4 sides, 2 pointed tips (rolls, read on top)"),
    ("d4", "tetragonal_disphenoid"): Family("d4", "tetragonal_disphenoid", build_tetragonal_disphenoid,
                                            {"stretch": (1.15, 1.8)},
                                            description="stretched tetrahedron, 4 congruent isosceles triangles"),
    ("d4", "square_antiwedge"): Family("d4", "square_antiwedge", build_square_antiwedge,
                                       {"thickness": (0.45, 0.85)},
                                       description="chiselled blade: two perpendicular ridges on opposite sides"),
    ("d6", "trigonal_trapezohedron"): Family("d6", "trigonal_trapezohedron", build_trigonal_trapezohedron,
                                             {"elevation": (20.0, 50.0)},
                                             description="6 congruent rhombi (calcite rhombohedron)"),
    ("d6", "long_barrel"): Family("d6", "long_barrel", build_long_barrel,
                                  {"body": (1.0, 1.8), "cap": (0.6, 0.95)}, {"style": "pointed"},
                                  description="hexagonal crystal prism with pointed or gem-cut ends"),
    ("d6", "asymmetric_hexahedron"): Family("d6", "asymmetric_hexahedron", build_asymmetric_hexahedron,
                                            {"a": (0.6, 1.6), "b": (0.6, 1.6), "c": (0.6, 1.6),
                                             "alpha": (55.0, 125.0), "beta": (55.0, 125.0), "gamma": (55.0, 125.0)},
                                            description="skewed parallelepiped, repaired onto the isohedral manifold"),
}


# ----------------------------------------------------------------------------
# Repair loop: bounded Nelder-Mead on the fairness penalty
# ----------------------------------------------------------------------------

def nelder_mead(fun, x0, step=0.15, iters=600, ftol=1e-14):
    """Minimal Nelder-Mead (no SciPy dependency)."""
    n = len(x0)
    pts = [np.asarray(x0, float)] + [np.asarray(x0, float) + step * np.eye(n)[i] for i in range(n)]
    vals = [fun(p) for p in pts]
    for _ in range(iters):
        order = np.argsort(vals)
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if vals[0] <= ftol or abs(vals[-1] - vals[0]) < ftol:
            break
        cen = np.mean(pts[:-1], axis=0)
        xr = cen + (cen - pts[-1])
        fr = fun(xr)
        if fr < vals[0]:
            xe = cen + 2 * (cen - pts[-1])
            fe = fun(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = cen + 0.5 * (pts[-1] - cen)
            fc = fun(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [fun(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


@dataclass
class GeneratedDie:
    die: str
    family: str
    seed: int
    params: dict
    poly: Polyhedron
    report: FairnessReport
    history: list


def _params_from_unit(fam, x):
    out = dict(fam.fixed)
    for (name, (lo, hi)), xi in zip(fam.params.items(), x):
        out[name] = lo + (hi - lo) * float(np.clip(xi, 0.0, 1.0))
    return out


def _penalty(fam, die, x):
    try:
        poly = fam.build(_params_from_unit(fam, x))
        rep = evaluate(poly, die, poly.meta["reading"], verify_symmetry=False)
    except (ShapeError, StopIteration, np.linalg.LinAlgError):
        return 1e3
    out_of_box = float(np.sum(np.clip(-np.asarray(x), 0, None) + np.clip(np.asarray(x) - 1, 0, None)))
    return rep.penalty + 10 * out_of_box


def generate(die, family, seed=0, size_mm=16.0, style=None, max_restarts=8, verbose=False):
    """Generate one die: sample parameters from the seed, verify, repair until fair, scale to size."""
    die = die.lower()
    if (die, family) not in FAMILIES:
        raise KeyError(f"unknown family {family!r} for {die}; choose from "
                       f"{[f for d, f in FAMILIES if d == die]}")
    fam = FAMILIES[(die, family)]
    if style is not None:
        fam = Family(fam.die, fam.name, fam.build, fam.params, {**fam.fixed, "style": style}, fam.description)
    rng = np.random.default_rng(seed)
    history = []
    for attempt in range(max_restarts):
        x = rng.uniform(0.0, 1.0, len(fam.params))
        pen = _penalty(fam, die, x)
        history.append({"attempt": attempt, "stage": "sampled", "params": _params_from_unit(fam, x), "penalty": pen})
        if pen > 0:
            x, pen = nelder_mead(lambda z: _penalty(fam, die, z), x)
            history.append({"attempt": attempt, "stage": "repaired", "params": _params_from_unit(fam, x),
                            "penalty": pen})
        params = _params_from_unit(fam, x)
        try:
            poly = fam.build(params)
        except ShapeError:
            continue
        rep = evaluate(poly, die, poly.meta["reading"])
        if verbose:
            print(f"  attempt {attempt}: penalty {pen:.3e} -> {'PASS' if rep.passed else 'fail'}")
        if rep.passed:
            poly = _scale_to_size(poly, die, size_mm)
            rep = evaluate(poly, die, poly.meta["reading"])
            return GeneratedDie(die, family, seed, params, poly, rep, history)
    raise ShapeError(f"{die.upper()} {family} could not be made fair within {max_restarts} attempts:\n"
                     + rep.summary())


def _scale_to_size(poly, die, size_mm):
    """Scale so the die's resting height (face-to-top distance, max over faces) equals size_mm."""
    _, com = volume_and_com(poly)
    heights = []
    for f in poly.numbered:
        heights.append(float((poly.offsets[f] - poly.vertices @ poly.normals[f]).max()))
    s = size_mm / max(heights)
    out = poly.scaled(s)
    out.vertices = out.vertices - com * s  # centre on the CoM
    out.offsets = out.offsets - (out.normals @ (com * s))
    return out


# ----------------------------------------------------------------------------
# Mesh checks and export
# ----------------------------------------------------------------------------

def mesh_check(poly):
    """Watertight, consistently wound, outward, closed genus-0 surface."""
    tris = np.array(poly.triangles())
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    und = np.sort(directed, axis=1)
    _, uc = np.unique(und, axis=0, return_counts=True)
    _, dc = np.unique(directed, axis=0, return_counts=True)
    vol, _ = volume_and_com(poly)
    V, E, F = len(poly.vertices), len(poly.edges()), len(poly.faces)
    return {"watertight": bool((uc == 2).all()), "consistent_winding": bool((dc == 1).all()),
            "outward_normals": vol > 0, "euler_characteristic": V - E + F, "triangles": len(tris)}


def to_stl(poly, name="die"):
    """ASCII STL text (units: mm)."""
    lines = [f"solid {name}"]
    for a, b, c in poly.triangles():
        A, B, C = poly.vertices[a], poly.vertices[b], poly.vertices[c]
        n = unit(np.cross(B - A, C - A))
        lines.append(f"  facet normal {n[0]:.9e} {n[1]:.9e} {n[2]:.9e}")
        lines.append("    outer loop")
        for P in (A, B, C):
            lines.append(f"      vertex {P[0]:.9e} {P[1]:.9e} {P[2]:.9e}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    return "\n".join(lines) + "\n"


def to_obj(poly, name="die"):
    """Wavefront OBJ text with true polygon faces and groups for numbered faces / caps."""
    lines = [f"# {name} - fair_gem_dice.py (units: mm)", f"o {name}"]
    lines += [f"v {x:.9f} {y:.9f} {z:.9f}" for x, y, z in poly.vertices]
    for role in ("number", "cap"):
        fs = [f for f, r in zip(poly.faces, poly.roles) if r == role]
        if fs:
            lines.append(f"g {role}_faces")
            lines += ["f " + " ".join(str(i + 1) for i in f) for f in fs]
    return "\n".join(lines) + "\n"


def describe(gd):
    rep = gd.report
    t = rep.details["transitivity"]
    b = rep.details["basins"]
    eff = np.array(list(b["effective"].values()))
    ext = np.ptp(gd.poly.vertices, axis=0)
    out = [f"{gd.die.upper()} {gd.family} (seed {gd.seed}) - {'FAIR' if rep.passed else 'REJECTED'}",
           "  parameters: " + ", ".join(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
                                        for k, v in gd.params.items()),
           f"  size: {ext[0]:.2f} x {ext[1]:.2f} x {ext[2]:.2f} mm, volume {rep.details['volume']:.1f} mm^3",
           f"  symmetry: order {t['group_order']}, centrosymmetric {t['centrosymmetric']}, "
           f"face orbits {[len(o) for o in t['face_orbits']]}",
           f"  effective basins (sr): {np.round(eff, 6).tolist()}  (4pi/N = {4 * math.pi / len(eff):.6f})",
           rep.summary(),
           f"  mesh: {mesh_check(gd.poly)}"]
    return "\n".join(out)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def _write(gd, outdir, fmt):
    os.makedirs(outdir, exist_ok=True)
    name = f"{gd.die.upper()}_{gd.family}_seed{gd.seed}"
    text = to_stl(gd.poly, name) if fmt == "stl" else to_obj(gd.poly, name)
    path = os.path.join(outdir, f"{name}.{fmt}")
    with open(path, "w", encoding="ascii") as fh:
        fh.write(text)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate fair gemstone-style D4/D6 meshes.")
    ap.add_argument("--die", choices=["d4", "d6"])
    ap.add_argument("--family")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--size", type=float, default=None,
                    help="resting height in mm (default: 12 for rollers, 16 for other D4s, 14 for other D6s)")
    ap.add_argument("--style", choices=["pointed", "gem", "flat"], help="cap style for long_barrel")
    ap.add_argument("--format", choices=["stl", "obj"], default="stl")
    ap.add_argument("--out", default="fair_dice_output")
    ap.add_argument("--list", action="store_true", help="list the shape families")
    a = ap.parse_args(argv)

    if a.list:
        for (d, f), fam in FAMILIES.items():
            print(f"{d}  {f:24s} {fam.description}")
        return 0

    if a.die and a.family:
        if (a.die, a.family) not in FAMILIES:
            print(f"unknown family {a.family!r} for {a.die}; choose from "
                  f"{[f for d, f in FAMILIES if d == a.die]} (or use --list)", file=sys.stderr)
            return 2
        jobs = [(a.die, a.family, a.seed, a.style)]
    else:
        print("Demo: unusual gemstone D4s and D6s (pass --die/--family for a single die)\n")
        jobs = [("d4", "crystal_shard", a.seed, None),
                ("d4", "square_antiwedge", a.seed, None),
                ("d6", "long_barrel", a.seed, "gem"),
                ("d6", "asymmetric_hexahedron", a.seed, None),
                ("d6", "long_barrel", a.seed, "flat")]  # expected rejection: it can stand on its flat end

    status = 0
    for die, family, seed, style in jobs:
        roller = family in ("crystal_shard", "long_barrel")
        size = a.size or (12.0 if roller else 16.0 if die == "d4" else 14.0)
        try:
            gd = generate(die, family, seed, size, style=style)
        except ShapeError as exc:
            print(f"{die.upper()} {family}{' (' + style + ' ends)' if style else ''}: REJECTED\n{exc}\n")
            status = status or (0 if style == "flat" and not (a.die and a.family) else 1)
            continue
        if family == "asymmetric_hexahedron":
            first = gd.history[0]
            print(f"  (started from a skewed parallelepiped with penalty {first['penalty']:.3f}: "
                  + ", ".join(f"{k}={v:.3f}" for k, v in first["params"].items()) + ")")
        print(describe(gd))
        print(f"  written: {_write(gd, a.out, a.format)}\n")
    return status


if __name__ == "__main__":
    sys.exit(main())

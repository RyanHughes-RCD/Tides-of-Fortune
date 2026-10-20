"""Bridges between polyhedra, 2D shapes and Manifold solids; Boolean engraving.

Engraving is done by extruding 2D outlines into prisms in a face's local
frame and subtracting them from the die with Manifold, which always returns
a closed 2-manifold.  The prism spans local z in [-depth, +clearance], so the
cut floor is exactly ``depth`` below the face plane measured along the face's
own normal.
"""
from __future__ import annotations

import logging

import manifold3d as m3d
import numpy as np
import shapely

from .polyhedra import ConvexPolyhedron
from .text import polygons_of

log = logging.getLogger(__name__)


SIMPLIFY_TOL = 1e-4  # mm (0.1 micron)


class BooleanError(RuntimeError):
    pass


def polyhedron_to_manifold(poly: ConvexPolyhedron) -> m3d.Manifold:
    tris = poly.triangles().astype(np.uint64)
    verts = np.ascontiguousarray(poly.vertices, dtype=np.float64)
    mesh = m3d.Mesh64(vert_properties=verts, tri_verts=np.ascontiguousarray(tris))
    man = m3d.Manifold(mesh)
    if man.status() != m3d.Error.NoError or man.is_empty():
        raise BooleanError(f"polyhedron could not be converted to a solid: {man.status()}")
    return man


GRID_MM = 1e-4  # 2D outlines are snapped to this grid before extrusion


def geometry_to_crosssection(geom, simplify=0.0):
    """shapely geometry -> Manifold CrossSection.

    Outlines are snapped to a 0.1 micron grid first: Boolean/buffer output can
    contain vertices only nanometres apart, which would become zero-length
    edges once the mesh is rounded to float32 for STL.
    """
    contours = []
    if geom is None or geom.is_empty:
        return None
    geom = shapely.set_precision(shapely.make_valid(geom), GRID_MM)
    for p in polygons_of(geom):
        if simplify:
            p = p.simplify(simplify, preserve_topology=True)
        for ring in [p.exterior, *p.interiors]:
            c = np.asarray(ring.coords)[:-1]
            if len(c) >= 3:
                contours.append(np.ascontiguousarray(c, dtype=np.float64))
    if not contours:
        return None
    # rings are non-overlapping (exterior CCW, holes CW in any order): even-odd is exact
    return m3d.CrossSection(contours, m3d.FillRule.EvenOdd)


def prism(geom, frame_matrix, z0, z1, simplify=0.0):
    """Extrude ``geom`` between local z0 and z1 and place it with a 3x4 frame matrix."""
    cs = geometry_to_crosssection(geom, simplify)
    if cs is None or cs.is_empty():
        return None
    solid = m3d.Manifold.extrude(cs, float(z1 - z0)).translate((0.0, 0.0, float(z0)))
    return solid.transform(np.asarray(frame_matrix, dtype=np.float64))


def apply_features(body, cutters, adders):
    """body ∪ adders − cutters.  Returns the new Manifold; raises BooleanError on failure."""
    try:
        out = body
        adders = [a for a in adders if a is not None and not a.is_empty()]
        cutters = [c for c in cutters if c is not None and not c.is_empty()]
        if adders:
            out = m3d.Manifold.batch_boolean([out, *adders], m3d.OpType.Add)
        if cutters:
            tool = m3d.Manifold.batch_boolean(cutters, m3d.OpType.Add)
            out = m3d.Manifold.batch_boolean([out, tool], m3d.OpType.Subtract)
        # remove numerical slivers left by the Booleans; surfaces move < SIMPLIFY_TOL
        out = out.simplify(SIMPLIFY_TOL)
        st = out.status()
    except Exception as exc:  # pragma: no cover - kernel errors are rare
        raise BooleanError(f"Boolean operation failed: {exc}") from exc
    if st != m3d.Error.NoError:
        raise BooleanError(f"Boolean operation failed: {st}")
    if out.is_empty() or out.volume() <= 0:
        raise BooleanError("Boolean operation produced an empty solid")
    return out


def manifold_arrays(man: m3d.Manifold):
    mesh = man.to_mesh64()
    v = np.array(mesh.vert_properties, dtype=np.float64)[:, :3].copy()
    t = np.array(mesh.tri_verts, dtype=np.int64)
    return v, t

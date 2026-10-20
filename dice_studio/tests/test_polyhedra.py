import math

import numpy as np
import pytest

from dicestudio.geometry.polyhedra import (DEFAULT_SIZES_MM, DIE_TYPES, FACE_COUNTS, GeometryError, ShapeParams,
                                           die_polyhedron, offset_polyhedron, opposite_face_map)

VARIANTS = [(0.0, 0.0), (0.5, 0.0), (0.4, 0.8), (1.2, 2.0)]


@pytest.mark.parametrize("die", DIE_TYPES)
@pytest.mark.parametrize("chamfer,trunc", VARIANTS)
def test_face_counts_and_closed_solid(die, chamfer, trunc):
    poly, base, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die], chamfer, trunc, 1.1))
    assert len(poly.die_faces()) == FACE_COUNTS[die]
    assert len(base.faces) == FACE_COUNTS[die]
    V, E, F = len(poly.vertices), len(poly.edges()), len(poly.faces)
    assert V - E + F == 2  # closed convex polyhedron
    assert all(len(fs) == 2 for fs in poly.edges().values())  # every edge shared by two faces
    assert poly.volume() > 0
    # every face is planar and convex, wound counter-clockwise seen from outside
    for f in poly.faces:
        pts = poly.vertices[f.vertex_ids]
        assert np.allclose(pts @ f.normal, f.offset, atol=1e-7)
        for k in range(len(pts)):
            a, b, c = pts[k], pts[(k + 1) % len(pts)], pts[(k + 2) % len(pts)]
            assert np.cross(b - a, c - b) @ f.normal > -1e-9


def test_base_shapes_are_regular():
    for die, nverts in (("d4", 3), ("d6", 4), ("d8", 3), ("d12", 5), ("d20", 3), ("d10", 4)):
        poly, _, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die]))
        for f in poly.die_faces():
            assert len(f.vertex_ids) == nverts
    # the face-to-face distance equals the requested size
    for die in ("d6", "d8", "d10", "d12", "d20"):
        poly, _, _ = die_polyhedron(die, ShapeParams(17.0))
        f = poly.die_faces()[0]
        assert poly.width_along(f.normal) == pytest.approx(17.0, abs=1e-6)
    # D4 size is the edge length
    poly, _, _ = die_polyhedron("d4", ShapeParams(20.0))
    edges = [np.linalg.norm(poly.vertices[a] - poly.vertices[b]) for a, b in poly.edges()]
    assert np.allclose(edges, 20.0)


def test_d10_kites_are_planar_and_opposite():
    poly, _, _ = die_polyhedron("d10", ShapeParams(16.0, d10_elongation=1.3))
    opp = opposite_face_map(poly)
    assert all(v is not None for v in opp.values())
    assert len(poly.vertices) == 12  # two apexes + two rings of five


def test_invalid_parameters_raise():
    with pytest.raises(GeometryError):
        die_polyhedron("d6", ShapeParams(2.0))
    with pytest.raises(GeometryError):
        die_polyhedron("d10", ShapeParams(16.0, d10_elongation=3.0))
    with pytest.raises(GeometryError):
        die_polyhedron("d7", ShapeParams(16.0))


@pytest.mark.parametrize("die", DIE_TYPES)
def test_offset_is_true_face_offset_not_scaling(die):
    poly, _, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die], 0.6, 0.0))
    off = [0.5] * len(poly.planes)
    inner = offset_polyhedron(poly, off)
    for f in poly.faces:
        # every outer plane has an inner face with the same normal, exactly 0.5 mm further in
        match = [g for g in inner.faces if np.allclose(g.normal, f.normal)]
        assert match, "face lost"
        assert match[0].offset == pytest.approx(f.offset - 0.5, abs=1e-9)
    # a uniform scale would NOT preserve chamfer width; the true offset keeps edge directions
    s = inner.width_along(poly.die_faces()[0].normal) / poly.width_along(poly.die_faces()[0].normal)
    assert s < 1

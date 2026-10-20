import numpy as np
import pytest

from dicestudio.geometry.polyhedra import (DEFAULT_SIZES_MM, DIE_TYPES, FACE_COUNTS, FAMILIES, GeometryError,
                                           ShapeParams, die_polyhedron, face_congruence_error, offset_polyhedron,
                                           opposite_face_map)


def _cases():
    for die, fams in FAMILIES.items():
        for fam, rng in fams.items():
            for prm in ([None] if rng is None else [rng[0], rng[2], rng[1]]):
                yield die, fam, prm


@pytest.mark.parametrize("die,family,param", list(_cases()))
def test_every_family_is_a_valid_fair_die(die, family, param):
    poly, _, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die], family, param))
    assert len(poly.die_faces()) == FACE_COUNTS[die]
    assert len(poly.faces) == FACE_COUNTS[die]  # no extra (non-congruent) facets
    V, E, F = len(poly.vertices), len(poly.edges()), len(poly.faces)
    assert V - E + F == 2  # closed convex polyhedron
    assert all(len(fs) == 2 for fs in poly.edges().values())
    assert poly.volume() > 0
    # fairness: every face congruent (same sorted edge lengths and angles) and equidistant from the centre
    assert face_congruence_error(poly) < 1e-9
    offsets = [f.offset for f in poly.die_faces()]
    assert max(offsets) - min(offsets) < 1e-9
    # planar, convex, counter-clockwise seen from outside
    for f in poly.faces:
        pts = poly.vertices[f.vertex_ids]
        assert np.allclose(pts @ f.normal, f.offset, atol=1e-7)
        for k in range(len(pts)):
            a, b, c = pts[k], pts[(k + 1) % len(pts)], pts[(k + 2) % len(pts)]
            assert np.cross(b - a, c - b) @ f.normal > -1e-9
    # every face (except on the D4) has a parallel opposite face, so the die rests flat
    opp = opposite_face_map(poly)
    if die != "d4":
        assert all(v is not None for v in opp.values())


def test_sizes():
    for die in ("d6", "d8", "d10", "d12", "d20"):
        poly, _, _ = die_polyhedron(die, ShapeParams(17.0))
        f = poly.die_faces()[0]
        assert poly.width_along(f.normal) == pytest.approx(17.0, abs=1e-6)
    # D4 size is the longest edge
    for fam, prm in (("tetrahedron", None), ("disphenoid", 1.3)):
        poly, _, _ = die_polyhedron("d4", ShapeParams(20.0, fam, prm))
        edges = [np.linalg.norm(poly.vertices[a] - poly.vertices[b]) for a, b in poly.edges()]
        assert max(edges) == pytest.approx(20.0)


def test_regular_shapes_are_regular():
    for die, nverts in (("d4", 3), ("d6", 4), ("d8", 3), ("d12", 5), ("d20", 3), ("d10", 4)):
        poly, _, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die]))
        for f in poly.die_faces():
            assert len(f.vertex_ids) == nverts
            pts = poly.vertices[f.vertex_ids]
            if die != "d10":
                e = [np.linalg.norm(pts[i] - pts[(i + 1) % nverts]) for i in range(nverts)]
                assert max(e) - min(e) < 1e-9


def test_invalid_parameters_raise():
    with pytest.raises(GeometryError):
        die_polyhedron("d6", ShapeParams(2.0))
    with pytest.raises(GeometryError):
        die_polyhedron("d10", ShapeParams(16.0, "trapezohedron", 3.0))
    with pytest.raises(GeometryError):
        die_polyhedron("d20", ShapeParams(16.0, "dodecahedron"))
    with pytest.raises(GeometryError):
        die_polyhedron("d7", ShapeParams(16.0))


@pytest.mark.parametrize("die,family,param", [("d12", "pyritohedron", 2.0), ("d20", "bipyramid", 1.5),
                                              ("d6", "rhombohedron", 30.0), ("d4", "disphenoid", 0.8)])
def test_offset_is_true_face_offset_not_scaling(die, family, param):
    poly, _, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die], family, param))
    inner = offset_polyhedron(poly, [0.5] * len(poly.planes))
    for f in poly.faces:
        match = [g for g in inner.faces if np.allclose(g.normal, f.normal)]
        assert match, "face lost"
        assert match[0].offset == pytest.approx(f.offset - 0.5, abs=1e-9)
    assert face_congruence_error(inner) < 1e-9

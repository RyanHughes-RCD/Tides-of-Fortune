import itertools

import numpy as np
import pytest

from dicestudio.geometry.polyhedra import (DEFAULT_SIZES_MM, DIE_TYPES, FACE_COUNTS, FAMILIES, GeometryError,
                                           ShapeParams, check_landing, default_size_mm, die_polyhedron,
                                           face_congruence_error, offset_polyhedron, opposite_face_map,
                                           reading_map, rest_analysis)


def _cases(kind):
    for die, fams in FAMILIES.items():
        for fam, spec in fams.items():
            if spec["kind"] != kind:
                continue
            names = list(spec["params"])
            levels = [(spec["params"][n]["min"], spec["params"][n]["default"], spec["params"][n]["max"]) for n in names]
            for combo in itertools.product(*levels) if names else [()]:
                prm = dict(zip(names, combo))
                if kind == "roller" and len(names) > 1 and sum(c != spec["params"][n]["default"]
                                                              for n, c in zip(names, combo)) > 1:
                    continue  # corners of multi-parameter ranges may be rejected by design
                yield die, fam, prm


def _closed_convex(poly):
    V, E, F = len(poly.vertices), len(poly.edges()), len(poly.faces)
    assert V - E + F == 2
    assert all(len(fs) == 2 for fs in poly.edges().values())
    assert poly.volume() > 0
    for f in poly.faces:
        pts = poly.vertices[f.vertex_ids]
        assert np.allclose(pts @ f.normal, f.offset, atol=1e-7)
        for k in range(len(pts)):
            a, b, c = pts[k], pts[(k + 1) % len(pts)], pts[(k + 2) % len(pts)]
            assert np.cross(b - a, c - b) @ f.normal > -1e-9


@pytest.mark.parametrize("die,family,prm", list(_cases("isohedral")))
def test_face_landing_shapes_are_fair(die, family, prm):
    poly, _, _ = die_polyhedron(die, ShapeParams(default_size_mm(die, family), family, prm))
    assert len(poly.die_faces()) == FACE_COUNTS[die]
    assert len(poly.faces) == FACE_COUNTS[die]  # no extra (non-congruent) facets
    _closed_convex(poly)
    assert face_congruence_error(poly) < 1e-9
    offsets = [f.offset for f in poly.die_faces()]
    assert max(offsets) - min(offsets) < 1e-9
    assert check_landing(poly) == []  # every face holds the die at rest
    if die != "d4":
        assert all(v is not None for v in opposite_face_map(poly).values())


@pytest.mark.parametrize("die,family,prm", list(_cases("roller")))
def test_rollers_only_land_on_numbered_sides(die, family, prm):
    poly, _, _ = die_polyhedron(die, ShapeParams(default_size_mm(die, family), family, prm))
    n = FACE_COUNTS[die]
    assert len(poly.die_faces()) == n
    _closed_convex(poly)
    # the numbered sides are congruent with each other (rotations about the axis)
    assert face_congruence_error(poly) < 1e-9
    com, rows = rest_analysis(poly)
    assert np.allclose(com[:2], 0, atol=1e-9)  # centre of mass on the axis
    sides = [r for r in rows if r["kind"] == "face"]
    caps = [r for r in rows if r["kind"] == "cap"]
    assert len(sides) == n and caps
    assert all(r["stable"] and r["margin_rel"] > 0.12 for r in sides)
    assert all(not r["stable"] for r in caps)  # it cannot come to rest on an end facet
    # resting on side k, the side facing up is side k + n/2
    rm = reading_map(poly)
    assert all(rm[k] == (k + n // 2) % n for k in range(n))
    assert check_landing(poly) == []


def test_blunt_roller_is_rejected():
    # a stubby crystal could stand on an end facet: the check must say so
    import dicestudio.geometry.polyhedra as P

    spec = P.FAMILIES["d6"]["crystal"]["params"]
    saved = {k: dict(v) for k, v in spec.items()}
    try:
        spec["body"]["min"] = 0.1
        spec["cap"]["min"] = 0.1
        poly, _, _ = die_polyhedron("d6", ShapeParams(14, "crystal", {"body": 0.3, "cap": 0.3}))
        issues = check_landing(poly)
        assert issues and "end facet" in issues[0]
    finally:
        for k, v in saved.items():
            spec[k].update(v)


def test_gemstone_d6_has_faceted_crown():
    poly, _, _ = die_polyhedron("d6", ShapeParams(13, "gemstone", {}))
    caps = [f for f in poly.faces if f.kind == "cap"]
    assert len(caps) == 18  # 6 + 6 crown facets (two tiers) + 6 pavilion facets
    assert len(poly.die_faces()) == 6
    zs = poly.vertices[:, 2]
    assert zs.max() < -zs.min()  # crown is shorter than the pavilion


def test_sizes():
    for die in ("d6", "d8", "d10", "d12", "d20"):
        poly, _, _ = die_polyhedron(die, ShapeParams(17.0))
        f = poly.die_faces()[0]
        assert poly.width_along(f.normal) == pytest.approx(17.0, abs=1e-6)
    for fam, prm in (("tetrahedron", {}), ("disphenoid", {"stretch": 1.3})):
        poly, _, _ = die_polyhedron("d4", ShapeParams(20.0, fam, prm))
        edges = [np.linalg.norm(poly.vertices[a] - poly.vertices[b]) for a, b in poly.edges()]
        assert max(edges) == pytest.approx(20.0)
    # rollers: size is the resting width across the sides
    poly, _, _ = die_polyhedron("d8", ShapeParams(14.0, "crystal", {}))
    assert poly.width_along(poly.die_faces()[0].normal) == pytest.approx(14.0, abs=1e-6)


def test_invalid_parameters_raise():
    with pytest.raises(GeometryError):
        die_polyhedron("d6", ShapeParams(2.0))
    with pytest.raises(GeometryError):
        die_polyhedron("d10", ShapeParams(16.0, "trapezohedron", {"elongation": 3.0}))
    with pytest.raises(GeometryError):
        die_polyhedron("d20", ShapeParams(16.0, "dodecahedron"))
    with pytest.raises(GeometryError):
        die_polyhedron("d8", ShapeParams(16.0, "gemstone"))
    with pytest.raises(GeometryError):
        die_polyhedron("d7", ShapeParams(16.0))


@pytest.mark.parametrize("die,family,prm", [("d12", "pyritohedron", {"pentagon": 2.0}),
                                             ("d20", "bipyramid", {"height": 1.5}),
                                             ("d6", "gemstone", {}), ("d10", "shard", {}),
                                             ("d4", "crystal", {})])
def test_offset_is_true_face_offset_not_scaling(die, family, prm):
    poly, _, _ = die_polyhedron(die, ShapeParams(default_size_mm(die, family), family, prm))
    inner = offset_polyhedron(poly, [0.5] * len(poly.planes))
    for f in poly.faces:
        match = [g for g in inner.faces if np.allclose(g.normal, f.normal)]
        assert match, "face lost"
        assert match[0].offset == pytest.approx(f.offset - 0.5, abs=1e-9)

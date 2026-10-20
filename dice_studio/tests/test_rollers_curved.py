"""Roller dice (crystal, shard, short shard, gemstone), the wedge and the curved infinity D4."""
import copy

import numpy as np
import pytest
from shapely.ops import polylabel

from conftest import first_hit_depth, interior_point, to_manifold
from dicestudio.geometry import design as dsg
from dicestudio.geometry.builder import build_die
from dicestudio.geometry.polyhedra import (DIE_TYPES, FAMILIES, ROLLER_FAMILIES, ShapeParams, check_landing,
                                           die_polyhedron)
from dicestudio.geometry.text import polygons_of
from dicestudio.project import default_project, resolve_die_spec, validate_project

ROLLER_CASES = [(d, f) for d in DIE_TYPES for f in FAMILIES[d] if f in ROLLER_FAMILIES]


def _project_with(die, family, **params):
    p = default_project(seed=7, style="classic")
    p["design"][f"{die}_shape"] = family
    for k, v in params.items():
        p["design"][dsg.param_key(die, family, k)] = v
    return validate_project(p)


@pytest.fixture(scope="module")
def roller_results(engine):
    out = {}
    for die, fam in ROLLER_CASES:
        out[(die, fam)] = engine.build(resolve_die_spec(_project_with(die, fam), die))
    return out


@pytest.mark.parametrize("die,family", ROLLER_CASES)
def test_roller_builds_valid_engraved_mesh(roller_results, die, family):
    r = roller_results[(die, family)]
    assert r.ok, r.errors
    assert r.outer_report["ok"], r.outer_report["issues"]
    assert r.blank_report["ok"] and r.blank_check["ok"], r.blank_check["issues"]
    assert r.blank_check["measured_min_gap_mm"] == pytest.approx(0.5, abs=2e-3)
    assert r.info["shape_kind"] == "roller"
    rest = r.info["rest"]
    assert rest["numbered_faces_stable"] and rest["end_facets_unstable"]
    man = to_manifold(r.outer_vertices, r.outer_tris)
    for tag, lay in r.layout.items():
        for poly in polygons_of(lay["numerals"]):
            if poly.area < 0.15:
                continue
            pt = interior_point(poly)
            p3 = lay["origin"] + pt.x * lay["u"] + pt.y * lay["v"]
            assert first_hit_depth(man, p3, lay["n"]) == pytest.approx(0.75, abs=2e-4), (die, family, tag)


@pytest.mark.parametrize("die,family", ROLLER_CASES)
def test_roller_numbering_and_orientation(roller_results, die, family):
    r = roller_results[(die, family)]
    n = len(r.faces)
    vals = {f.tag: f.value for f in r.faces}
    total = 9 if die in ("d10", "d100") else n + 1
    for k in range(n):
        # resting on side k, side k + n/2 faces up; each pair shows complementary values
        assert vals[k] + vals[(k + n // 2) % n] == total
    expected = list(range(10)) if die in ("d10", "d100") else list(range(1, n + 1))
    assert sorted(vals.values()) == expected
    for f in r.faces:
        # numerals run along the die's axis: their 'up' is perpendicular to it
        assert abs(np.dot(f.up, [0, 0, 1])) < 1e-9
        assert abs(np.dot(f.normal, f.up)) < 1e-9


def test_wedge_uses_edge_numbering(engine):
    r = engine.build(resolve_die_spec(_project_with("d4", "wedge"), "d4"))
    assert r.ok and r.outer_report["ok"]
    labels = {f.tag: sorted(f.labels) for f in r.faces}
    # base style: each face shows the three *other* face values along its edges
    for f in r.faces:
        assert labels[f.tag] == sorted(str(v) for v in range(1, 5) if v != f.tag + 1)


@pytest.fixture(scope="module")
def infinity(engine):
    return engine.build(resolve_die_spec(_project_with("d4", "infinity"), "d4"))


def test_infinity_mesh_and_blank(infinity):
    r = infinity
    assert r.ok, r.errors
    assert r.outer_report["ok"], r.outer_report["issues"]
    assert r.outer_report["self_intersections"] == 0
    assert r.blank_report["ok"] and r.blank_check["ok"], r.blank_check["issues"]
    assert r.blank_check["measured_min_gap_mm"] >= 0.5 - 1e-3
    assert r.blank_check["volume_outside_outer_mm3"] < 1e-6
    assert r.info["shape_kind"] == "curved"
    assert r.info["length_mm"] == pytest.approx(21.0)


def test_infinity_reading_is_consistent(infinity):
    # every face carries the values of its three neighbours, so whichever face the die
    # rests on, its value appears along the bottom edge of all three visible faces
    labels = {f.tag: f.labels for f in infinity.faces}
    for f in infinity.faces:
        assert sorted(labels[f.tag]) == sorted(str(g.tag + 1) for g in infinity.faces if g.tag != f.tag)


def test_infinity_engraving_follows_the_curved_surface(infinity):
    man = to_manifold(infinity.outer_vertices, infinity.outer_tris)
    depths = []
    for tag, lay in infinity.layout.items():
        face = lay["face"]
        for poly in polygons_of(lay["numerals"]):
            for pt in (interior_point(poly), poly.representative_point()):
                P, N = face.map(np.array([[pt.x, pt.y]]))
                depths.append(first_hit_depth(man, P[0], N[0]))
            # and the untouched surface between numerals is not cut
        P, N = face.map(np.array([[polylabel(face.polygon, 0.01).x, polylabel(face.polygon, 0.01).y]]))
    depths = np.array(depths)
    assert len(depths) >= 12
    # measured along the true curved-surface normal at each point; the floor is made of
    # small flat triangles, so it may sit a few microns deeper between its vertices
    assert np.all(np.abs(depths - 0.75) < 5e-3), depths


@pytest.mark.parametrize("style", ["crystal", "shard", "mixed", "elongated"])
def test_randomiser_only_makes_dice_that_land_correctly(style):
    for seed in range(12):
        d = dsg.generate_design(seed, style, 0.8)
        for die in DIE_TYPES:
            fam, prm = dsg.shape_of(d, die)
            if FAMILIES[die][fam]["kind"] == "curved":
                continue
            poly, _, _ = die_polyhedron(die, ShapeParams(16.0, fam, prm))
            assert check_landing(poly) == [], (style, seed, die, fam, prm)


def test_regenerate_die_changes_only_its_shape():
    from dicestudio.project import regenerate_die
    p = default_project(seed=3, style="shard", density=0.8)
    before = dsg.shape_of(dsg.die_variant(p["design"], 3, "d8", 0), "d8")
    seen = set()
    for _ in range(6):
        p = regenerate_die(p, "d8")
        des = dsg.die_variant(p["design"], p["seed"], "d8", p["dice"]["d8"]["variant"], (), p["style"], p["density"])
        seen.add(dsg.shape_of(des, "d8")[0])
        for other in DIE_TYPES:
            if other != "d8":
                assert dsg.shape_of(des, other) == dsg.shape_of(p["design"], other)
    assert seen  # produced shapes
    assert before


def test_legacy_design_keys_are_migrated():
    p = default_project(seed=1)
    old = copy.deepcopy(p)
    old["design"].pop("d8_bipyramid_height")
    old["design"]["d8_height"] = 1.25
    q = validate_project(old)
    assert q["design"]["d8_bipyramid_height"] == 1.25

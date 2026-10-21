"""Tests for the standalone fair_gem_dice.py generator."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fair_gem_dice as G  # noqa: E402

CASES = [(d, f, None) for (d, f) in G.FAMILIES if f != "long_barrel"] + [
    ("d6", "long_barrel", "pointed"), ("d6", "long_barrel", "gem")]


def test_solid_angle_formula_on_a_cube():
    poly = G.from_planes([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], [1] * 6,
                         ["number"] * 6)
    om = G.face_solid_angles(poly, np.zeros(3))
    assert np.allclose(om, 4 * math.pi / 6)
    # off-centre point: still sums to 4 pi, but faces differ
    om2 = G.face_solid_angles(poly, np.array([0.3, 0.1, 0.0]))
    assert om2.sum() == pytest.approx(4 * math.pi) and np.ptp(om2) > 0.1


def test_symmetry_group_orders():
    cube = G.from_planes([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], [1] * 6,
                         ["number"] * 6)
    t = G.transitivity_report(cube)
    assert t["group_order"] == 48 and t["proper_rotations"] == 24 and t["isohedral"]
    # a box (not a cube) is not face-transitive
    box = G.from_planes([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
                        [1, 1, 1, 1, 2, 2], ["number"] * 6)
    tb = G.transitivity_report(box)
    assert tb["group_order"] == 16 and not tb["transitive_on_numbered_faces"]


@pytest.mark.parametrize("die,family,style", CASES)
@pytest.mark.parametrize("seed", [0, 3])
def test_every_family_generates_a_fair_watertight_die(die, family, style, seed):
    gd = G.generate(die, family, seed, 14.0, style=style)
    rep = gd.report
    assert rep.passed, rep.summary()
    t = rep.details["transitivity"]
    assert t["transitive_on_numbered_faces"]
    eff = np.array(list(rep.details["basins"]["effective"].values()))
    n = 4 if die == "d4" else 6
    assert len(eff) == n
    assert np.allclose(eff, 4 * math.pi / n, rtol=1e-9)  # Omega_1 = ... = Omega_N = 4pi/N
    m = G.mesh_check(gd.poly)
    assert m["watertight"] and m["consistent_winding"] and m["outward_normals"] and m["euler_characteristic"] == 2


def test_reproducible_from_seed():
    a = G.generate("d6", "long_barrel", 11, 14.0, style="gem")
    b = G.generate("d6", "long_barrel", 11, 14.0, style="gem")
    assert a.params == b.params and np.array_equal(a.poly.vertices, b.poly.vertices)


def test_skewed_parallelepiped_is_repaired_into_a_rhombohedron():
    gd = G.generate("d6", "asymmetric_hexahedron", 1, 14.0)
    assert gd.history[0]["penalty"] > 1.0  # the random start was unfair
    p = gd.params
    assert p["a"] == pytest.approx(p["b"], rel=1e-5) == pytest.approx(p["c"], rel=1e-5)
    assert p["alpha"] == pytest.approx(p["beta"], rel=1e-5) == pytest.approx(p["gamma"], rel=1e-5)
    assert gd.report.details["transitivity"]["isohedral"]
    assert gd.report.details["transitivity"]["centrosymmetric"]


def test_flat_ended_barrel_is_rejected():
    with pytest.raises(G.ShapeError, match="end facet"):
        G.generate("d6", "long_barrel", 1, 14.0, style="flat", max_restarts=2)


def test_rollers_have_unstable_caps_and_parallel_top_faces():
    gd = G.generate("d4", "crystal_shard", 2, 12.0)
    rest = gd.report.details["basins"]["rest"]
    assert all(r["margin"] < 0 for r in rest if r["role"] == "cap")
    assert all(r["margin"] > 0 for r in rest if r["role"] == "number")
    assert gd.report.checks["top face parallel to table"][0]


def test_exports_round_trip():
    gd = G.generate("d4", "square_antiwedge", 4, 16.0)
    stl = G.to_stl(gd.poly, "x")
    assert stl.count("facet normal") == len(gd.poly.triangles())
    obj = G.to_obj(gd.poly, "x")
    assert obj.count("\nv ") == len(gd.poly.vertices) and obj.count("\nf ") == len(gd.poly.faces)


def test_cli_demo_runs(tmp_path):
    assert G.main(["--die", "d4", "--family", "tetragonal_disphenoid", "--out", str(tmp_path)]) == 0
    assert list(tmp_path.glob("*.stl"))
    assert G.main(["--die", "d6", "--family", "nope"]) == 2

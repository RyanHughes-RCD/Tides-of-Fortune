import copy

import numpy as np
import pytest

from conftest import to_manifold
from dicestudio.geometry.polyhedra import DIE_TYPES
from dicestudio.project import resolve_die_spec, validate_project


@pytest.mark.parametrize("die", DIE_TYPES)
def test_blank_clearance_against_every_face_plane(built_set, die):
    p, results = built_set
    r = results[die]
    chk = r.blank_check
    assert chk["ok"], chk["issues"]
    deepest = chk["deepest_cut_mm"]
    need = 0.5 + deepest  # default reference: clearance beyond the deepest cut
    V = r.blank_vertices
    for normal, offset, kind in r.plane_data:
        n = np.asarray(normal)
        gap = offset - (V @ n).max()
        assert gap >= need - 1e-6, (die, kind)
    # the blank's main faces sit *exactly* on the offset planes (true face offset)
    for f in chk["faces"]:
        assert f["plane_gap_mm"] == pytest.approx(need, abs=1e-6)
        assert f["gap_from_cut_floor_mm"] >= 0.5 - 1e-6
    # measured gap between blank and the engraved outer surface
    assert chk["measured_min_gap_mm"] == pytest.approx(0.5, abs=2e-3)
    assert chk["volume_outside_outer_mm3"] < 1e-6
    assert chk["min_thickness_mm"] > 2.0


def test_blank_is_contained_in_outer(built_set):
    import manifold3d as m3d

    _, results = built_set
    for die, r in results.items():
        outer = to_manifold(r.outer_vertices, r.outer_tris)
        blank = to_manifold(r.blank_vertices, r.blank_tris)
        assert blank.volume() > 0
        diff = m3d.Manifold.batch_boolean([blank, outer], m3d.OpType.Subtract)
        assert diff.volume() < 1e-6
        # no numerals/decoration on the blank: it is a convex polyhedron
        assert r.blank_report["triangles"] < 400


def test_blank_regenerates_with_parent(engine, base_project):
    p = copy.deepcopy(base_project)
    a = engine.build(resolve_die_spec(validate_project(p), "d8"))
    p["blank"]["clearance_mm"] = 0.8
    b = engine.build(resolve_die_spec(validate_project(p), "d8"))
    assert a.spec_hash != b.spec_hash
    assert b.blank_check["clearance_mm"] == 0.8
    assert b.blank_check["measured_min_gap_mm"] == pytest.approx(0.8, abs=2e-3)
    assert b.blank_check["volume_mm3"] < a.blank_check["volume_mm3"]


def test_face_plane_reference_reports_conflict_with_engraving(engine, base_project):
    p = copy.deepcopy(base_project)
    p["blank"]["reference"] = "face_plane"
    r = engine.build(resolve_die_spec(validate_project(p), "d20"))
    chk = r.blank_check
    for f in chk["faces"]:
        assert f["plane_gap_mm"] == pytest.approx(0.5, abs=1e-6)  # strictly 0.5 mm from each face plane
    assert not chk["ok"]  # but the 0.75 mm engravings reach into it - reported, not hidden
    assert any("outside" in i for i in chk["issues"])


def test_impossible_clearance_explained(engine, base_project):
    p = copy.deepcopy(base_project)
    p["blank"]["clearance_mm"] = 5.0
    p["dice"]["d4"]["size_mm"] = 12.0
    r = engine.build(resolve_die_spec(validate_project(p), "d4"))
    assert not r.ok
    assert "blank" in r.errors[0] and "clearance" in r.errors[0]

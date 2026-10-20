import copy

import numpy as np
import pytest
import shapely

from conftest import first_hit_depth, interior_point, to_manifold
from dicestudio.geometry.builder import build_die, safe_region, section_polygon
from dicestudio.geometry.polyhedra import DIE_TYPES
from dicestudio.geometry.text import polygons_of
from dicestudio.project import resolve_die_spec


def _numeral_points(lay):
    g = lay["numerals"]
    return [interior_point(p) for p in polygons_of(g) if p.area > 0.3]


@pytest.mark.parametrize("die", DIE_TYPES)
def test_numerals_engraved_075_along_face_normal(built_set, die):
    _, results = built_set
    r = results[die]
    assert r.ok, r.errors
    man = to_manifold(r.outer_vertices, r.outer_tris)
    checked = 0
    for tag, lay in r.layout.items():
        assert lay["numeral_depth"] == pytest.approx(0.75)
        for pt in _numeral_points(lay):
            p3 = lay["origin"] + pt.x * lay["u"] + pt.y * lay["v"]
            d = first_hit_depth(man, p3, lay["n"])
            assert d == pytest.approx(0.75, abs=2e-4), f"{die} face {tag}"
            checked += 1
    assert checked >= len(r.layout)


def test_numerals_do_not_compromise_walls(built_set):
    _, results = built_set
    for die, r in results.items():
        assert r.ok
        for tag, lay in r.layout.items():
            # outline stays inside the face with the edge margin; at full depth every
            # point of the cut keeps >= 0.6 mm of material to every other plane
            g = lay["numerals"]
            assert g.within(lay["polygon"].buffer(-0.45 + 1e-6))
            for poly in polygons_of(g):
                for x, y in poly.exterior.coords:
                    p = lay["origin"] + x * lay["u"] + y * lay["v"] - 0.75 * lay["n"]
                    for normal, offset, kind in r.plane_data:
                        n = np.asarray(normal)
                        if np.allclose(n, lay["n"]):
                            continue
                        assert offset - n @ p >= 0.6 - 1e-6, (die, tag)


def test_custom_depth_and_no_engrave(engine, base_project):
    from dicestudio.project import validate_project

    p = copy.deepcopy(base_project)
    p["numbers"]["depth_mm"] = 1.1
    p = validate_project(p)
    r = engine.build(resolve_die_spec(p, "d12"))
    assert r.ok, r.errors
    man = to_manifold(r.outer_vertices, r.outer_tris)
    lay = r.layout[0]
    pt = _numeral_points(lay)[0]
    p3 = lay["origin"] + pt.x * lay["u"] + pt.y * lay["v"]
    assert first_hit_depth(man, p3, lay["n"]) == pytest.approx(1.1, abs=2e-4)
    assert r.blank_check["deepest_cut_mm"] == pytest.approx(1.1)

    p["dice"]["d12"]["engrave"] = False
    r2 = engine.build(resolve_die_spec(validate_project(p), "d12"))
    man2 = to_manifold(r2.outer_vertices, r2.outer_tris)
    assert first_hit_depth(man2, p3, lay["n"]) == pytest.approx(0.0, abs=2e-4)


def test_safe_region_keeps_minimum_wall(built_set):
    """A cut inside the safe region leaves at least min_wall of material to every neighbouring face."""
    from dicestudio.geometry.numbering import build_frames
    from dicestudio.geometry.polyhedra import ShapeParams, die_polyhedron

    poly, base, _ = die_polyhedron("d4", ShapeParams(20.0, "disphenoid", {"stretch": 1.3}))
    frames = build_frames("d4", poly, base)
    fr = frames[0]
    sr = safe_region(fr, poly, 0.75, 0.45, 0.6)
    bottom = section_polygon(fr, poly, 0.75)
    for x, y in list(sr.exterior.coords):
        p = fr.origin + x * fr.u + y * fr.v - 0.75 * fr.n
        dist = min(pl.offset - pl.normal @ p for pl in poly.planes if pl.tag != 0 or pl.kind != "face")
        assert dist >= 0.6 - 1e-6
    assert sr.within(bottom)


def test_meshes_are_watertight_and_valid(built_set):
    _, results = built_set
    for die, r in results.items():
        assert r.outer_report["ok"], (die, r.outer_report["issues"])
        assert r.blank_report["ok"], (die, r.blank_report["issues"])
        assert r.outer_report["self_intersections"] == 0
        assert r.outer_report["components"] == 1
        assert r.outer_report["genus"] == 0


def test_numeral_layout_fits_and_is_readable(built_set):
    _, results = built_set
    for die, r in results.items():
        # numerals are at least 2.5 mm tall, or the user is warned (e.g. 20 narrow roller sides)
        assert r.info["numeral_height_mm"] >= 2.5 or any("hard to read" in w for w in r.warnings), die
        for tag, lay in r.layout.items():
            parts = polygons_of(lay["numerals"])
            assert parts
            if die == "d4":
                continue
            # the numeral is centred on the face's largest inscribed circle
            from shapely.ops import polylabel
            c = lay["numerals"].envelope.centroid
            pl = polylabel(lay["polygon"], tolerance=0.01)
            if r.info["shape_kind"] == "roller":
                # along the axis the position is searched for the largest fit; across
                # the side the numeral is centred
                assert abs(c.y - pl.y) < 0.5, (die, tag)
            else:
                assert abs(c.x - pl.x) < 0.8 and abs(c.y - pl.y) < 1.5, (die, tag)

import math

import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import Point

from dicestudio.geometry.numbering import (assign_values, build_frames, label_for, numeral_placements,
                                           opposite_sums)
from dicestudio.geometry.polyhedra import DEFAULT_SIZES_MM, DIE_TYPES, FACE_COUNTS, ShapeParams, die_polyhedron

OPTS = {"d10_top_order": [1, 7, 3, 9, 5], "six_nine_marker": "underline"}


def _setup(die, **kw):
    poly, base, _ = die_polyhedron(die, ShapeParams(DEFAULT_SIZES_MM[die]))
    frames = build_frames(die, poly, base)
    pl = numeral_placements(die, frames, base, {**OPTS, **kw})
    return poly, base, frames, pl


@pytest.mark.parametrize("die,total", [("d6", 7), ("d8", 9), ("d12", 13), ("d20", 21), ("d10", 9), ("d100", 9)])
def test_opposite_faces_sum(die, total):
    _, base, _, _ = _setup(die)
    sums = opposite_sums(die, base, OPTS)
    assert len(sums) == FACE_COUNTS[die]
    assert set(sums.values()) == {total}


@pytest.mark.parametrize("die", DIE_TYPES)
def test_every_value_exactly_once(die):
    _, base, frames, pl = _setup(die)
    if die == "d4":
        return
    vals = sorted(p.value for p in pl)
    expected = list(range(0, 10)) if die in ("d10", "d100") else list(range(1, FACE_COUNTS[die] + 1))
    assert vals == expected
    assert len({p.face_tag for p in pl}) == FACE_COUNTS[die]


def test_d10_and_d100_labels():
    _, base, frames, pl = _setup("d10")
    assert sorted(p.text for p in pl) == [str(i) for i in range(10)]
    upper = {p.value for p in pl if p.face_tag < 5}
    assert upper == {1, 3, 5, 7, 9}  # odd numbers around the top apex
    _, _, _, pl = _setup("d100")
    assert sorted(p.text for p in pl) == ["00", "10", "20", "30", "40", "50", "60", "70", "80", "90"]
    assert not any(p.marker for p in pl)  # two-digit tens need no 6/9 mark
    assert label_for("d10", 0, {"d10_style": "1-10"}) == "10"
    assert label_for("d100", 0, {"d100_style": "10-100"}) == "100"


def test_six_nine_markers():
    for die in ("d10", "d12", "d20"):
        _, _, _, pl = _setup(die)
        marked = {p.text for p in pl if p.marker}
        assert marked == {"6", "9"}
    _, _, _, pl = _setup("d8")  # D8 has a 6 but no 9
    assert not any(p.marker for p in pl)
    _, _, _, pl = _setup("d20", six_nine_marker="none")
    assert not any(p.marker for p in pl)


@pytest.mark.parametrize("die", DIE_TYPES)
def test_frames_are_right_handed_and_on_face(die):
    poly, base, frames, _ = _setup(die)
    for tag, fr in frames.items():
        # u x v == n  ->  text is read un-mirrored from outside the die
        assert np.allclose(np.cross(fr.u, fr.v), fr.n, atol=1e-9)
        assert fr.n @ fr.origin == pytest.approx(fr.offset)
        assert abs(fr.v @ fr.n) < 1e-9
        # the frame origin is inside the face
        assert fr.polygon.contains(Point(0, 0))


@pytest.mark.parametrize("die", ["d8", "d12", "d20"])
def test_up_points_to_a_vertex(die):
    _, base, frames, _ = _setup(die)
    for tag, fr in frames.items():
        dirs = [v / np.linalg.norm(v) for v in fr.base_vertices2d]
        assert max(d[1] for d in dirs) == pytest.approx(1.0, abs=1e-6)


def test_d6_up_points_to_edge():
    _, base, frames, _ = _setup("d6")
    for fr in frames.values():
        mids = [(fr.base_vertices2d[k] + fr.base_vertices2d[(k + 1) % 4]) / 2 for k in range(4)]
        dirs = [m / np.linalg.norm(m) for m in mids]
        assert max(d[1] for d in dirs) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize("die", ["d10", "d100"])
def test_d10_up_points_to_pole(die):
    poly, base, frames, _ = _setup(die)
    for tag, fr in frames.items():
        apex_z = 1 if tag < 5 else -1
        # moving "up" on the face moves towards the die's pole on that side
        assert fr.v[2] * apex_z > 0.3


def test_d4_apex_numbering():
    poly, base, frames, pl = _setup("d4", d4_style="apex")
    assert len(pl) == 12
    by_face = {}
    for p in pl:
        by_face.setdefault(p.face_tag, []).append(p)
    assert all(len(v) == 3 for v in by_face.values())
    # every vertex number appears on the three faces meeting at that vertex
    counts = {}
    for p in pl:
        counts[p.value] = counts.get(p.value, 0) + 1
    assert counts == {1: 3, 2: 3, 3: 3, 4: 3}
    # each numeral's up direction points at a face corner, and the faces around a
    # corner all show that corner's number (so the top reading is consistent)
    for tag, ps in by_face.items():
        fr = frames[tag]
        bf = base.face_by_tag(tag)
        for p in ps:
            up = np.array([-math.sin(p.rotation), math.cos(p.rotation)])
            corner_dirs = [fr.to2d(base.vertices[v])[0] for v in bf.vertex_ids]
            best = max(range(3), key=lambda k: up @ corner_dirs[k] / np.linalg.norm(corner_dirs[k]))
            vid = bf.vertex_ids[best]
            assert up @ (corner_dirs[best] / np.linalg.norm(corner_dirs[best])) == pytest.approx(1.0, abs=1e-6)
            # the face opposite that vertex is the one not containing it; its value is the vertex value
            opposite_face = next(f for f in base.die_faces() if vid not in f.vertex_ids)
            assert p.value == opposite_face.tag + 1


def test_d4_base_numbering():
    poly, base, frames, pl = _setup("d4", d4_style="base")
    assert len(pl) == 12
    for p in pl:
        # the number printed along an edge is the value of the face across that edge
        assert p.value != p.face_tag + 1
    # each face shows the three other values
    by_face = {}
    for p in pl:
        by_face.setdefault(p.face_tag, set()).add(p.value)
    for tag, vals in by_face.items():
        assert vals == {1, 2, 3, 4} - {tag + 1}


def test_d6_conventional_layout():
    _, base, frames, pl = _setup("d6")
    vals = {p.face_tag: p.value for p in pl}
    # 1, 2, 3 meet at one corner, counter-clockwise when viewed from outside
    n = {p.value: frames[p.face_tag].n for p in pl}
    assert np.cross(n[1], n[2]) @ n[3] > 0

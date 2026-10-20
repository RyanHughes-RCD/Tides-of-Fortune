import copy
import io
import zipfile

import numpy as np
import pytest

from dicestudio.engine import ExportError, revalidate_stl
from dicestudio.geometry.stl import read_stl, stl_bytes
from dicestudio.geometry.validate import validate_mesh
from dicestudio.project import validate_project


def _cube(offset=(0, 0, 0), s=1.0):
    v = np.array([(x, y, z) for x in (0, s) for y in (0, s) for z in (0, s)], float) + offset
    t = np.array([(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
                  (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)])
    return v, t


def test_validator_accepts_clean_cube():
    v, t = _cube()
    r = validate_mesh(v, t)
    assert r.ok, r.issues
    assert r.volume_mm3 == pytest.approx(1.0)


def test_validator_detects_defects():
    v, t = _cube()
    assert not validate_mesh(v, t[:-1]).watertight  # hole
    assert "inward" in " ".join(validate_mesh(v, t[:, ::-1]).issues)  # flipped
    flipped_one = t.copy()
    flipped_one[0] = flipped_one[0][::-1]
    assert not validate_mesh(v, flipped_one).winding_consistent
    v2, t2 = _cube((0.5, 0.3, 0.2))
    both = validate_mesh(np.vstack([v, v2]), np.vstack([t, t2 + 8]))
    assert both.self_intersections > 0  # overlapping shells
    assert both.components == 2
    far = validate_mesh(np.vstack([v, v + 5]), np.vstack([t, t + 8]))
    assert far.self_intersections == 0 and "disconnected" in " ".join(far.issues)
    dup = validate_mesh(v, np.vstack([t, t[:1]]))
    assert dup.duplicate_triangles == 1
    degenerate = np.vstack([v, [[0, 0, 0.5]]])  # collinear with vertices 0 and 1
    assert validate_mesh(degenerate, np.vstack([t, [[0, 8, 1]]])).degenerate_triangles == 1


def test_stl_roundtrip_and_units():
    v, t = _cube(s=10.0)
    data = stl_bytes(v, t, "cube", "mm")
    V, T, N = read_stl(data)
    assert len(T) == 12 and np.allclose(np.ptp(V, axis=0), 10.0)
    V2, _, _ = read_stl(stl_bytes(v, t, "cube", "in"))
    assert np.allclose(np.ptp(V2, axis=0), 10.0 / 25.4, rtol=1e-6)
    assert revalidate_stl(data).ok


def test_export_all_fourteen(engine, base_project, tmp_path):
    rep = engine.export_to_directory(base_project, tmp_path, "all")
    files = sorted(f.name for f in tmp_path.glob("*.stl"))
    expected = sorted([f"TestSet_{d}.stl" for d in ("D4", "D6", "D8", "D10", "D12", "D20", "D100")] +
                      [f"TestSet_{d}_Blank.stl" for d in ("D4", "D6", "D8", "D10", "D12", "D20", "D100")])
    assert files == expected
    assert rep["ok"]
    assert (tmp_path / "TestSet_validation_report.json").exists()
    for f in tmp_path.glob("*.stl"):
        r = revalidate_stl(f.read_bytes())
        assert r.ok, (f.name, r.issues)  # validated again from the written file


def test_export_single_and_zip(engine, base_project, tmp_path):
    engine.export_to_directory(base_project, tmp_path, "blanks", die="d20")
    assert [f.name for f in tmp_path.glob("*.stl")] == ["TestSet_D20_Blank.stl"]
    z = zipfile.ZipFile(io.BytesIO(engine.export_zip(base_project, "dice")))
    assert len([n for n in z.namelist() if n.endswith(".stl")]) == 7


def test_export_refuses_invalid_blank(engine, base_project, tmp_path):
    p = copy.deepcopy(base_project)
    p["blank"]["reference"] = "face_plane"  # blank intersects the engravings
    with pytest.raises(ExportError, match="validation failed"):
        engine.export_to_directory(validate_project(p), tmp_path, "all")
    assert not list(tmp_path.glob("*.stl"))
    p["export"]["allow_invalid"] = True
    rep = engine.export_to_directory(validate_project(p), tmp_path, "all")
    assert rep["exported_with_issues"]

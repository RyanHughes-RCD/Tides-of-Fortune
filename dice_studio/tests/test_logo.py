import copy

import pytest

from conftest import first_hit_depth, interior_point, make_logo_png, to_manifold
from dicestudio.geometry import logo as logomod
from dicestudio.geometry.text import polygons_of
from dicestudio.project import resolve_die_spec, validate_project


def test_png_vectorisation_keeps_holes_islands_and_aspect():
    shape = logomod.logo_shape(make_logo_png())
    assert shape.components == 2  # ring + square
    assert shape.holes == 1  # the ring's hole
    assert shape.aspect == pytest.approx(120 / 200)
    assert shape.mask_mode == "alpha"
    b = shape.geom.bounds
    assert b[2] - b[0] <= 1.0 + 1e-9  # normalised to image width
    placed = logomod.place_logo(shape, 8.0, 30.0, (0.5, 0.0))
    assert placed.is_valid


def test_threshold_and_luminance_mode():
    data = make_logo_png(opaque=True)
    s = logomod.logo_shape(data, threshold=100)
    assert s.mask_mode == "luminance"
    assert s.components == 2  # black ring + dark-grey (20) square
    assert logomod.logo_shape(data, threshold=10).components == 1  # the grey square is now above threshold
    assert logomod.logo_shape(data, threshold=100, invert=True).components >= 1
    with pytest.raises(logomod.LogoError):
        logomod.logo_shape(make_logo_png(), threshold=255, mode="luminance", invert=True)  # nothing selected


def test_invalid_images():
    with pytest.raises(logomod.LogoError):
        logomod.logo_shape(b"not a png")
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), (0, 0, 0)).save(buf, "JPEG")
    with pytest.raises(logomod.LogoError):
        logomod.logo_shape(buf.getvalue())
    buf = io.BytesIO()
    Image.new("RGBA", (20, 20), (0, 0, 0, 255)).save(buf, "PNG")
    with pytest.raises(logomod.LogoError, match="entire image"):
        logomod.logo_shape(buf.getvalue())


def test_fine_detail_warning():
    shape = logomod.logo_shape(make_logo_png(thin=True), simplify_px=0)
    placed = logomod.place_logo(shape, 6.0)  # a 1 px line at 6 mm wide is ~0.03 mm
    rep = logomod.fine_detail_report(placed, 0.3)
    assert rep["warnings"]
    cleaned = logomod.remove_fine_details(placed, 0.3)
    assert logomod.fine_detail_report(cleaned, 0.3)["thin_fraction"] < rep["thin_fraction"]


@pytest.fixture(scope="module")
def logo_project(store, base_project):
    ref = store.put(make_logo_png(), "logo.png", "logo")
    p = copy.deepcopy(base_project)
    p["logo"].update({"asset": {"id": ref["id"], "name": ref["name"]}, "enabled": True, "width_mm": 5.0})
    p["design"]["d20_shape"] = "icosahedron"
    return validate_project(p)


def test_logo_cut_into_the_20_face(engine, logo_project):
    r = engine.build(resolve_die_spec(logo_project, "d20"))
    assert r.ok, r.errors
    assert r.outer_report["ok"], r.outer_report["issues"]
    face20 = next(f for f in r.faces if f.value == 20)
    assert face20.labels == ["(logo)"]  # replaces the numeral by default
    lay = r.layout[face20.tag]
    assert lay["logo"] is not None and lay["numerals"] is None
    assert lay["logo"].within(lay["polygon"].buffer(-0.45))  # inside the face, away from the edges
    man = to_manifold(r.outer_vertices, r.outer_tris)
    for poly in polygons_of(lay["logo"]):
        pt = interior_point(poly)
        p3 = lay["origin"] + pt.x * lay["u"] + pt.y * lay["v"]
        assert first_hit_depth(man, p3, lay["n"]) == pytest.approx(0.75, abs=2e-4)
    # inside the ring's hole the face surface is untouched (hole handled correctly)
    ring = max(polygons_of(lay["logo"]), key=lambda p: len(p.interiors))
    hole = interior_point(type(ring)(ring.interiors[0]))
    p3 = lay["origin"] + hole.x * lay["u"] + hole.y * lay["v"]
    assert first_hit_depth(man, p3, lay["n"]) == pytest.approx(0.0, abs=2e-4)
    # only the D20 receives the logo
    assert "logo" not in resolve_die_spec(logo_project, "d12")


def test_logo_toggle_keeps_settings(engine, logo_project):
    p = copy.deepcopy(logo_project)
    p["logo"]["enabled"] = False
    p = validate_project(p)
    assert p["logo"]["asset"] is not None and p["logo"]["width_mm"] == 5.0
    r = engine.build(resolve_die_spec(p, "d20"))
    assert r.ok
    assert all(lay["logo"] is None for lay in r.layout.values())


def test_oversized_logo_is_shrunk_with_warning(engine, logo_project):
    p = copy.deepcopy(logo_project)
    p["logo"]["width_mm"] = 25.0
    p["logo"]["depth_mm"] = 1.0
    r = engine.build(resolve_die_spec(validate_project(p), "d20"))
    assert r.ok, r.errors
    assert any("logo width reduced" in w for w in r.warnings)
    tag = r.info["logo_face"]
    assert r.layout[tag]["logo"].within(r.layout[tag]["polygon"])
    assert r.cut_depths[tag] == pytest.approx(1.0)


def test_logo_with_numeral_kept(engine, logo_project):
    p = copy.deepcopy(logo_project)
    p["logo"]["replace_numeral"] = False
    p["logo"]["width_mm"] = 2.4
    p["logo"]["offset_mm"] = [0.0, -2.0]
    p["dice"]["d20"]["height_mm"] = 2.6
    p["dice"]["d20"]["offset_mm"] = [0.0, 0.9]
    r = engine.build(resolve_die_spec(validate_project(p), "d20"))
    assert r.ok, r.errors
    lay = r.layout[r.info["logo_face"]]
    assert lay["numerals"] is not None and lay["logo"] is not None
    assert lay["logo"].distance(lay["numerals"]) >= 0.5 - 1e-6

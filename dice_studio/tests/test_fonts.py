import copy

import pytest

from conftest import FONTS, make_font
from dicestudio.geometry.text import (BuiltinFont, FontError, check_font_digits, load_font, polygons_of,
                                      text_shape)
from dicestudio.project import resolve_die_spec, validate_project


@pytest.mark.parametrize("kind", ["ttf", "otf"])
def test_synthetic_fonts_convert_to_polygons_with_holes(kind):
    f = load_font(make_font(kind), f"test.{kind}")
    assert check_font_digits(f) == []
    ts = text_shape(f, "20", 5.0)
    polys = polygons_of(ts.geom)
    assert len(polys) == 2
    assert all(len(p.interiors) == 1 for p in polys)  # counters preserved for both winding conventions
    assert ts.geom.is_valid
    b = ts.geom.bounds
    assert b[3] - b[1] == pytest.approx(5.0, abs=1e-6)


def test_bundled_fonts_and_variable_weight():
    data = (FONTS / "Cinzel-Variable.ttf").read_bytes()
    light = load_font(data, "Cinzel", weight=400)
    heavy = load_font(data, "Cinzel", weight=900)
    assert light.supports_weight
    a1 = text_shape(light, "8", 5).geom.area
    a2 = text_shape(heavy, "8", 5).geom.area
    assert a2 > a1 * 1.2
    goth = load_font((FONTS / "UnifrakturMaguntia-Book.ttf").read_bytes(), "Fraktur")
    assert text_shape(goth, "1234567890", 4).geom.is_valid


def test_invalid_font_rejected():
    with pytest.raises(FontError):
        load_font(b"definitely not a font file" * 4)
    with pytest.raises(FontError):
        load_font(b"")


def test_missing_glyph_falls_back_with_warning():
    f = load_font(make_font("ttf", digits="0123456"), "partial.ttf")
    assert check_font_digits(f) == ["7", "8", "9"]
    with pytest.raises(FontError):
        text_shape(f, "17", 4)
    ts = text_shape(f, "17", 4, fallback=BuiltinFont())
    assert ts.warnings and "7" in ts.warnings[0]


def test_global_font_and_per_die_override(engine, store, base_project):
    ttf = store.put(make_font("ttf"), "global.ttf", "font")
    otf = store.put(make_font("otf"), "override.otf", "font")
    p = copy.deepcopy(base_project)
    p["font"]["asset"] = {"id": ttf["id"], "name": ttf["name"]}
    p["dice"]["d8"]["font"] = {"asset": {"id": otf["id"], "name": otf["name"]}, "weight": 600, "embolden_mm": 0}
    p = validate_project(p)
    specs = {d: resolve_die_spec(p, d) for d in p["dice"]}
    assert specs["d20"]["font"]["asset_id"] == ttf["id"]
    assert specs["d8"]["font"]["asset_id"] == otf["id"]
    for d in ("d20", "d8"):
        r = engine.build(specs[d])
        assert r.ok, r.errors
        assert r.outer_report["ok"], r.outer_report["issues"]


def test_missing_font_asset_reports_error(engine, base_project):
    p = copy.deepcopy(base_project)
    p["font"]["asset"] = {"id": "0" * 24, "name": "gone.ttf"}
    r = engine.build(resolve_die_spec(validate_project(p), "d6"))
    assert not r.ok
    assert "missing" in r.errors[0]

import io
import sys
from pathlib import Path

import manifold3d as m3d
import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dicestudio.assets import AssetStore  # noqa: E402
from dicestudio.engine import Engine  # noqa: E402
from dicestudio.project import default_project  # noqa: E402

FONTS = ROOT / "dicestudio" / "fonts"


def _digit_contours(ch, upm=1000):
    """Simple asymmetric 'L'-shaped digits with a hole, distinct per digit."""
    k = int(ch)
    w = 420 + 20 * k
    outer = [(60, 0), (60 + w, 0), (60 + w, 200), (260, 200), (260, 700), (60, 700)]
    hole = [(110, 50), (110, 650), (210, 650), (210, 50)]  # opposite winding -> counter
    return [outer, hole]


def make_font(kind="ttf", digits="0123456789"):
    from fontTools.fontBuilder import FontBuilder

    names = [".notdef"] + [f"d{c}" for c in digits]
    fb = FontBuilder(1000, isTTF=(kind == "ttf"))
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c): f"d{c}" for c in digits})
    if kind == "ttf":
        from fontTools.pens.ttGlyphPen import TTGlyphPen

        glyphs = {}
        for n in names:
            pen = TTGlyphPen(None)
            if n != ".notdef":
                for cont in _digit_contours(n[1]):
                    # TrueType: outer clockwise
                    pts = cont[::-1] if cont is _digit_contours(n[1])[0] else cont
                    pen.moveTo(pts[0])
                    for p in pts[1:]:
                        pen.lineTo(p)
                    pen.closePath()
            glyphs[n] = pen.glyph()
        fb.setupGlyf(glyphs)
    else:
        from fontTools.pens.t2CharStringPen import T2CharStringPen

        cs = {}
        for n in names:
            pen = T2CharStringPen(600, None)
            if n != ".notdef":
                for cont in _digit_contours(n[1]):
                    pen.moveTo(cont[0])
                    for p in cont[1:]:
                        pen.lineTo(p)
                    pen.closePath()
            cs[n] = pen.getCharString()
        fb.setupCFF("TestOTF", {"FullName": "TestOTF"}, cs, {})
    fb.setupHorizontalMetrics({n: (700, 0) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def make_logo_png(size=(200, 120), opaque=False, thin=False):
    """Transparent PNG: a ring (with a hole) plus a separate square island."""
    im = Image.new("RGBA", size, (255, 255, 255, 255 if opaque else 0))
    d = ImageDraw.Draw(im)
    d.ellipse((10, 10, 110, 110), fill=(0, 0, 0, 255))
    d.ellipse((40, 40, 80, 80), fill=(255, 255, 255, 255 if opaque else 0))
    d.rectangle((140, 30, 190, 90), fill=(20, 20, 20, 255))
    if thin:
        d.line((120, 5, 120, 115), fill=(0, 0, 0, 255), width=1)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    return tmp_path_factory.mktemp("ws")


@pytest.fixture(scope="session")
def store(workspace):
    return AssetStore(workspace)


@pytest.fixture(scope="session")
def engine(store):
    return Engine(store, cache_size=256)


@pytest.fixture(scope="session")
def base_project():
    return default_project(seed=1234, style="mixed", density=0.6, name="TestSet")


@pytest.fixture(scope="session")
def built_set(engine, base_project):
    p, results = engine.build_project(base_project)
    return p, results


def to_manifold(V, T):
    return m3d.Manifold(m3d.Mesh64(vert_properties=np.array(V, dtype=np.float64, order="C"), tri_verts=np.array(T, dtype=np.uint64, order="C")))


def first_hit_depth(man, point, normal, above=3.0, below=4.0):
    """Cast a ray from outside the face (along -normal) and return the depth of the
    first surface hit below the face plane through ``point``."""
    point = np.asarray(point, float)
    normal = np.asarray(normal, float)
    start = point + normal * above
    end = point - normal * below
    hits = man.ray_cast(tuple(start), tuple(end))
    if not hits:
        return None
    h = min(hits, key=lambda h: h.distance)
    return float((point - np.asarray(h.position, float)) @ normal)


def interior_point(geom):
    """A point well inside the largest polygon of a shapely geometry."""
    from shapely.ops import polylabel

    from dicestudio.geometry.text import polygons_of

    big = max(polygons_of(geom), key=lambda p: p.area)
    return polylabel(big, tolerance=0.005)

"""Numeral outlines: a built-in vector font plus imported TTF/OTF fonts.

All text is converted to real 2D polygon geometry (shapely), which is later
extruded and subtracted from the die body.  Nothing is rendered as a texture.

Glyph outlines are filled with the non-zero winding rule using the Manifold
CrossSection clipper, which correctly handles TrueType (clockwise outer) and
CFF/OTF (counter-clockwise outer) contour conventions as well as overlapping
contours found in variable fonts.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
from dataclasses import dataclass

import manifold3d as m3d
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LinearRing, LineString, MultiPolygon, Polygon

log = logging.getLogger(__name__)

DIGITS = "0123456789"


class FontError(ValueError):
    pass


# ---------------------------------------------------------------------------
# shapely helpers
# ---------------------------------------------------------------------------

def polygons_of(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if hasattr(geom, "geoms"):
        out = []
        for g in geom.geoms:
            out += polygons_of(g)
        return out
    return []


def as_multipolygon(geom):
    polys = [p for p in polygons_of(geom) if p.area > 0]
    return MultiPolygon(polys) if polys else MultiPolygon()


def contours_to_geometry(contours, fill_rule=m3d.FillRule.NonZero):
    """Fill closed contours (list of (k,2) arrays) and return a shapely MultiPolygon."""
    contours = [np.asarray(c, dtype=float) for c in contours if len(c) >= 3]
    if not contours:
        return MultiPolygon()
    cs = m3d.CrossSection(contours, fill_rule)
    rings = [np.asarray(p) for p in cs.to_polygons() if len(p) >= 3]
    # The clipper output is a set of non-overlapping simple rings (outers CCW,
    # holes CW), so an even-odd combination reconstructs it exactly.
    geom = Polygon()
    for r in rings:
        geom = geom.symmetric_difference(Polygon(r))
    return as_multipolygon(shapely.make_valid(geom))


# ---------------------------------------------------------------------------
# Built-in geometric stroke font
# ---------------------------------------------------------------------------
# Glyphs are polylines on a 6 x 10 grid (baseline y=0, digit height 10).  The
# stroke width ("weight") is applied by buffering, so weight is continuously
# adjustable for this font.

_BUILTIN_STROKES = {
    "0": [[(1.2, 0), (4.8, 0), (6, 1.2), (6, 8.8), (4.8, 10), (1.2, 10), (0, 8.8), (0, 1.2), (1.2, 0)]],
    "1": [[(1.0, 8.2), (3.2, 10), (3.2, 0)], [(1.0, 0), (5.4, 0)]],
    "2": [[(0, 8.6), (1.4, 10), (4.6, 10), (6, 8.6), (6, 6.4), (0, 0.6), (0, 0), (6, 0)]],
    "3": [[(0, 10), (6, 10), (2.6, 6), (4.6, 6), (6, 4.6), (6, 1.4), (4.6, 0), (1.4, 0), (0, 1.4)]],
    "4": [[(4.4, 0), (4.4, 10), (0, 3.2), (0, 2.8), (6, 2.8)]],
    "5": [[(6, 10), (0.4, 10), (0.2, 5.6), (4.6, 5.8), (6, 4.4), (6, 1.4), (4.6, 0), (1.4, 0), (0, 1.4)]],
    "6": [[(5.4, 10), (2.0, 10), (0, 8.0), (0, 1.4), (1.4, 0), (4.6, 0), (6, 1.4), (6, 4.6), (4.6, 6), (0, 6)]],
    "7": [[(0, 10), (6, 10), (6, 9.2), (2.2, 0)]],
    "8": [
        [(1.3, 5.6), (4.7, 5.6), (5.7, 6.6), (5.7, 9.0), (4.7, 10), (1.3, 10), (0.3, 9.0), (0.3, 6.6), (1.3, 5.6)],
        [(1.2, 0), (4.8, 0), (6, 1.2), (6, 4.4), (4.8, 5.6), (1.2, 5.6), (0, 4.4), (0, 1.2), (1.2, 0)],
    ],
}
_BUILTIN_STROKES["9"] = [[(6 - x, 10 - y) for x, y in s] for s in _BUILTIN_STROKES["6"]]


@dataclass
class GlyphShape:
    geom: MultiPolygon  # in "digit units": baseline 0, digit height = 1
    advance: float


class BuiltinFont:
    """Geometric stroke numerals.  ``weight`` 100..900 maps to stroke width."""

    name = "Built-in Geometric"
    is_builtin = True

    def __init__(self, weight=600):
        self.weight = float(weight)
        self.asset_id = None

    @property
    def stroke(self):
        # stroke width in grid units (grid height 10)
        return 0.9 + (self.weight - 100.0) / 800.0 * 1.4

    def cache_key(self):
        return f"builtin:{self.weight:.0f}"

    def supported(self, ch):
        return ch in _BUILTIN_STROKES

    def glyph(self, ch, segments=8):
        if ch not in _BUILTIN_STROKES:
            raise FontError(f"built-in font has no glyph for {ch!r}")
        w = self.stroke
        parts = []
        for pts in _BUILTIN_STROKES[ch]:
            closed = pts[0] == pts[-1]
            line = LinearRing(pts[:-1]) if closed else LineString(pts)
            parts.append(line.buffer(w / 2.0, cap_style="flat", join_style="mitre", mitre_limit=2.5))
        g = shapely.union_all(parts)
        # map grid (stroke-centred, 0..10 tall) to unit digit height including stroke
        g = affinity.translate(g, w / 2.0, w / 2.0)
        s = 1.0 / (10.0 + w)
        g = affinity.scale(g, s, s, origin=(0, 0))
        return GlyphShape(as_multipolygon(g), (6.0 + w) * s + 0.12)


# ---------------------------------------------------------------------------
# TTF / OTF fonts via fontTools
# ---------------------------------------------------------------------------

class _FlattenPen:
    """fontTools pen that flattens quadratic and cubic segments into polylines."""

    def __init__(self, glyphset, segments):
        from fontTools.pens.basePen import BasePen

        outer = self

        class _P(BasePen):
            def _moveTo(self, p):
                outer._start(p)

            def _lineTo(self, p):
                outer.cur.append(p)

            def _curveToOne(self, p1, p2, p3):
                p0 = outer.cur[-1]
                n = outer.segments
                for i in range(1, n + 1):
                    t = i / n
                    mt = 1 - t
                    x = mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0]
                    y = mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1]
                    outer.cur.append((x, y))

            def _qCurveToOne(self, p1, p2):
                p0 = outer.cur[-1]
                n = outer.segments
                for i in range(1, n + 1):
                    t = i / n
                    mt = 1 - t
                    x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
                    y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
                    outer.cur.append((x, y))

            def _closePath(self):
                outer._end()

            def _endPath(self):
                outer._end()

        self.pen = _P(glyphset)
        self.segments = segments
        self.contours = []
        self.cur = None

    def _start(self, p):
        self._end()
        self.cur = [p]

    def _end(self):
        if self.cur and len(self.cur) >= 3:
            pts = self.cur
            if pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(pts) >= 3:
                self.contours.append(pts)
        self.cur = None


class OutlineFont:
    """A TTF/OTF font loaded from bytes."""

    is_builtin = False

    def __init__(self, data: bytes, name="imported font", weight=None, asset_id=None):
        from fontTools.ttLib import TTFont

        if not data or len(data) < 12:
            raise FontError("font file is empty or truncated")
        try:
            self.font = TTFont(io.BytesIO(data), lazy=False)
            cmap = self.font.getBestCmap()
        except Exception as exc:  # fontTools raises many exception types
            raise FontError(f"not a readable TTF/OTF font: {exc}") from exc
        if not cmap:
            raise FontError("font has no usable character map")
        if "glyf" not in self.font and "CFF " not in self.font and "CFF2" not in self.font:
            raise FontError("font has no outline glyphs (bitmap-only fonts are not supported)")
        self.cmap = cmap
        self.name = name
        self.asset_id = asset_id
        self.digest = hashlib.sha256(data).hexdigest()[:16]
        self.axes = {}
        if "fvar" in self.font:
            for a in self.font["fvar"].axes:
                self.axes[a.axisTag] = (a.minValue, a.defaultValue, a.maxValue)
        self.weight = weight
        loc = None
        if weight is not None and "wght" in self.axes:
            lo, _, hi = self.axes["wght"]
            loc = {"wght": float(min(max(weight, lo), hi))}
        try:
            self.glyphset = self.font.getGlyphSet(location=loc) if loc else self.font.getGlyphSet()
        except Exception as exc:
            raise FontError(f"could not read glyph outlines: {exc}") from exc
        self.upm = float(self.font["head"].unitsPerEm)
        self._cache = {}
        self._digit_box = None

    @property
    def supports_weight(self):
        return "wght" in self.axes

    def cache_key(self):
        return f"font:{self.digest}:{self.weight}"

    def supported(self, ch):
        return ord(ch) in self.cmap

    def _raw(self, ch, segments):
        key = (ch, segments)
        if key in self._cache:
            return self._cache[key]
        if not self.supported(ch):
            raise FontError(f"font {self.name!r} has no glyph for {ch!r}")
        gname = self.cmap[ord(ch)]
        pen = _FlattenPen(self.glyphset, segments)
        try:
            self.glyphset[gname].draw(pen.pen)
        except Exception as exc:
            raise FontError(f"glyph {ch!r} could not be drawn: {exc}") from exc
        pen._end()
        geom = contours_to_geometry(pen.contours)
        adv = float(self.glyphset[gname].width)
        self._cache[key] = (geom, adv)
        return geom, adv

    def digit_box(self, segments=8):
        """Vertical extent (ymin, ymax) of the digits, used to normalise height."""
        if self._digit_box is None:
            ys = []
            for ch in DIGITS:
                if self.supported(ch):
                    g, _ = self._raw(ch, segments)
                    if not g.is_empty:
                        b = g.bounds
                        ys += [b[1], b[3]]
            if not ys:
                raise FontError(f"font {self.name!r} contains no drawable digits")
            self._digit_box = (min(ys), max(ys))
        return self._digit_box

    def glyph(self, ch, segments=8):
        geom, adv = self._raw(ch, segments)
        y0, y1 = self.digit_box(segments)
        h = y1 - y0
        g = affinity.translate(geom, 0, -y0)
        g = affinity.scale(g, 1 / h, 1 / h, origin=(0, 0))
        return GlyphShape(as_multipolygon(g), adv / h)


def load_font(data: bytes | None, name="font", weight=None, asset_id=None):
    if data is None:
        return BuiltinFont(weight or 600)
    return OutlineFont(data, name=name, weight=weight, asset_id=asset_id)


def check_font_digits(font):
    """Return list of missing characters needed for dice numerals."""
    return [c for c in DIGITS if not font.supported(c)]


# ---------------------------------------------------------------------------
# Text layout
# ---------------------------------------------------------------------------

@dataclass
class TextShape:
    geom: MultiPolygon  # centred on the numeral's visual centre, +y is "up"
    width: float
    height: float
    warnings: list


def text_shape(font, text, height_mm, embolden_mm=0.0, tracking=0.06, segments=8, marker=None,
               fallback=None):
    """Lay out ``text`` with digit height ``height_mm``.

    The result is centred on the middle of the digit box (so all numerals share
    the same visual centre regardless of glyph shape).  ``marker`` adds an
    orientation mark under the numeral ('underline' or 'dot') for 6/9.
    """
    warnings = []
    parts = []
    x = 0.0
    for ch in text:
        f = font
        if not font.supported(ch):
            if fallback is None:
                raise FontError(f"font {getattr(font, 'name', '?')!r} has no glyph for {ch!r}")
            warnings.append(f"glyph {ch!r} missing from {font.name!r}; using {fallback.name}")
            f = fallback
        g = f.glyph(ch, segments)
        gb = g.geom.bounds if not g.geom.is_empty else (0, 0, g.advance, 1)
        # place glyph by its ink box so tracking is uniform across fonts
        parts.append(affinity.translate(g.geom, x - gb[0], 0))
        x += (gb[2] - gb[0]) + tracking
    geom = shapely.union_all(parts) if parts else Polygon()
    if geom.is_empty:
        raise FontError(f"text {text!r} produced no geometry")
    b = geom.bounds
    geom = affinity.translate(geom, -(b[0] + b[2]) / 2.0, -0.5)
    geom = affinity.scale(geom, height_mm, height_mm, origin=(0, 0))
    if embolden_mm:
        geom = geom.buffer(embolden_mm, join_style="mitre", mitre_limit=2.0)
        if geom.is_empty:
            raise FontError("weight adjustment removed the numeral entirely; use a smaller thinning value")
    w = geom.bounds[2] - geom.bounds[0]
    if marker in ("underline", "dot"):
        y = -0.5 * height_mm - 0.17 * height_mm
        th = max(0.11 * height_mm, 0.4)
        if marker == "underline":
            mw = max(0.55 * w, 0.5 * height_mm)
            mark = shapely.box(-mw / 2, y - th, mw / 2, y)
        else:
            mark = shapely.Point(0, y - th / 2).buffer(th * 0.75, quad_segs=6)
        geom = geom.union(mark)
    geom = as_multipolygon(shapely.make_valid(geom))
    return TextShape(geom, w, height_mm, warnings)


def geometry_to_svg_path(geom, flip_y=True):
    """SVG path data for a shapely geometry (used for previews)."""
    out = []
    for p in polygons_of(geom):
        for ring in [p.exterior, *p.interiors]:
            pts = list(ring.coords)
            if not pts:
                continue
            s = "M" + " L".join(f"{x:.3f},{(-y if flip_y else y):.3f}" for x, y in pts) + " Z"
            out.append(s)
    return " ".join(out)

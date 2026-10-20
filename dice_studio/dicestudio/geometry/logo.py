"""PNG logo -> cuttable 2D outlines.

Pipeline
1. Load the PNG (Pillow).  Transparent PNGs use the alpha channel; opaque
   images use luminance (dark = logo, or inverted).
2. Threshold into a binary mask (user-selectable threshold).
3. Vectorise exactly: horizontal pixel runs become rectangles which are
   unioned into polygons (holes and disconnected islands are preserved).
4. Simplify the pixel staircase into straight/diagonal edges.
5. Normalise to width 1 (aspect ratio preserved), centred at the origin, +y up.

Fine-detail analysis is done at the physical size the logo will be cut at.
"""
from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from PIL import Image, UnidentifiedImageError
from shapely import affinity

from .text import as_multipolygon, polygons_of, robust_op

MAX_TRACE_PX = 360
MAX_COMPONENTS = 400


class LogoError(ValueError):
    pass


@dataclass
class LogoImage:
    width_px: int
    height_px: int
    has_alpha: bool
    rgba: Image.Image


def load_png(data: bytes) -> LogoImage:
    if not data:
        raise LogoError("logo file is empty")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise LogoError(f"not a readable image: {exc}") from exc
    if im.format != "PNG":
        raise LogoError(f"logo must be a PNG file (got {im.format})")
    has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    rgba = im.convert("RGBA")
    if rgba.width < 4 or rgba.height < 4:
        raise LogoError("logo image is too small (minimum 4 x 4 pixels)")
    return LogoImage(rgba.width, rgba.height, has_alpha, rgba)


def make_mask(img: LogoImage, threshold=128, invert=False, mode="auto"):
    """Boolean mask of the logo (True = cut).  ``mode``: auto | alpha | luminance."""
    a = np.asarray(img.rgba, dtype=np.float32)
    alpha = a[..., 3]
    use_alpha = mode == "alpha" or (mode == "auto" and img.has_alpha and alpha.min() < 250)
    if use_alpha:
        mask = alpha >= threshold
    else:
        lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        # transparent pixels never count as logo in luminance mode
        mask = (lum < threshold) & (alpha >= 128)
    if invert:
        mask = ~mask & (alpha >= 128) if not use_alpha else ~mask
    return mask, ("alpha" if use_alpha else "luminance")


def _downsample(mask, max_px=MAX_TRACE_PX):
    h, w = mask.shape
    s = max(h, w) / max_px
    if s <= 1:
        return mask, 1.0
    im = Image.fromarray((mask * 255).astype(np.uint8)).resize(
        (max(1, round(w / s)), max(1, round(h / s))), Image.Resampling.BOX)
    return np.asarray(im) >= 128, s


def trace_mask(mask, simplify_px=0.6):
    """Vectorise a boolean mask into a shapely MultiPolygon in pixel units (+y up)."""
    m, s = _downsample(mask)
    h, w = m.shape
    boxes = []
    for y in range(h):
        row = m[y]
        if not row.any():
            continue
        padded = np.concatenate([[False], row, [False]])
        d = np.diff(padded.astype(np.int8))
        starts = np.nonzero(d == 1)[0]
        ends = np.nonzero(d == -1)[0]
        top = h - y
        boxes.append(shapely.box(starts, top - 1, ends, top))
    if not boxes:
        return as_multipolygon(None), s
    geom = shapely.union_all(np.concatenate(boxes))
    if simplify_px > 0:
        geom = geom.simplify(simplify_px, preserve_topology=True)
    geom = as_multipolygon(shapely.make_valid(geom))
    if s != 1.0:
        geom = as_multipolygon(affinity.scale(geom, s, s, origin=(0, 0)))
    return geom, s


@dataclass
class LogoShape:
    geom: object  # MultiPolygon, width 1, centred, +y up
    aspect: float  # height / width of the source image
    components: int
    holes: int
    mask_mode: str
    coverage: float  # fraction of image area that is logo
    warnings: list = field(default_factory=list)


def logo_shape(data: bytes, threshold=128, invert=False, mode="auto", simplify_px=0.6) -> LogoShape:
    img = load_png(data)
    mask, used = make_mask(img, threshold, invert, mode)
    cov = float(mask.mean())
    if cov == 0:
        raise LogoError("the threshold leaves no logo pixels; lower the threshold or toggle 'invert'")
    if cov > 0.985:
        raise LogoError("the logo covers the entire image (no background found); "
                        "use a transparent PNG, raise/lower the threshold or toggle 'invert'")
    geom, _ = trace_mask(mask, simplify_px)
    if geom.is_empty:
        raise LogoError("the logo could not be converted into outlines")
    polys = polygons_of(geom)
    if len(polys) > MAX_COMPONENTS:
        raise LogoError(f"the logo has {len(polys)} separate pieces (noise or dithering?); "
                        "raise the threshold or simplify the image")
    W, H = img.width_px, img.height_px
    # normalise: width 1 based on the *image* frame so the user's framing and
    # proportions are preserved exactly
    geom = affinity.translate(geom, -W / 2.0, -H / 2.0)
    geom = affinity.scale(geom, 1.0 / W, 1.0 / W, origin=(0, 0))
    holes = sum(len(p.interiors) for p in polys)
    return LogoShape(as_multipolygon(geom), H / W, len(polys), holes, used, cov)


def place_logo(shape: LogoShape, width_mm, rotation_deg=0.0, offset=(0.0, 0.0), center=(0.0, 0.0)):
    g = affinity.scale(shape.geom, width_mm, width_mm, origin=(0, 0))
    g = affinity.rotate(g, rotation_deg, origin=(0, 0))
    g = affinity.translate(g, center[0] + offset[0], center[1] + offset[1])
    return as_multipolygon(g)


def fine_detail_report(geom, min_feature_mm=0.3, min_gap_mm=0.3):
    """Measure how much of the (placed, mm-scaled) logo is thinner than printable."""
    with np.errstate(divide="ignore", invalid="ignore"):  # GEOS warns on slivers that vanish
        return _fine_detail_report(geom, min_feature_mm, min_gap_mm)


def _fine_detail_report(geom, min_feature_mm, min_gap_mm):
    warnings = []
    area = geom.area
    if area <= 0:
        return {"thin_fraction": 0, "narrow_gap_area": 0, "tiny_islands": 0, "warnings": ["logo is empty"]}
    r = min_feature_mm / 2
    opened = geom.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")
    thin = max(0.0, area - robust_op("intersection", opened, geom).area)
    thin_frac = thin / area
    rg = min_gap_mm / 2
    closed = geom.buffer(rg, join_style="mitre").buffer(-rg, join_style="mitre")
    gaps = max(0.0, closed.area - geom.area)
    tiny = sum(1 for p in polygons_of(geom) if p.area < (min_feature_mm ** 2) * 1.5)
    if thin_frac > 0.03:
        warnings.append(f"{thin_frac * 100:.0f}% of the logo is thinner than {min_feature_mm:.2f} mm and may not print "
                        "or may fill with resin; enlarge the logo or enable 'remove fine details'")
    if gaps > 0.02 * area:
        warnings.append(f"some gaps between logo parts are narrower than {min_gap_mm:.2f} mm and may close up")
    if tiny:
        warnings.append(f"{tiny} logo island(s) are smaller than the printable minimum")
    return {"thin_fraction": thin_frac, "narrow_gap_area": gaps, "tiny_islands": tiny, "warnings": warnings}


def remove_fine_details(geom, min_feature_mm=0.3):
    r = min_feature_mm / 2
    g = robust_op("intersection", geom.buffer(-r, join_style="mitre").buffer(r, join_style="mitre"), geom)
    return as_multipolygon(shapely.MultiPolygon([p for p in polygons_of(g) if p.area > (min_feature_mm ** 2)]))


def mask_preview_png(data: bytes, threshold=128, invert=False, mode="auto", size=256):
    """PNG (base64) showing the image over a checkerboard, with the cut mask tinted."""
    img = load_png(data)
    mask, _ = make_mask(img, threshold, invert, mode)
    s = size / max(img.width_px, img.height_px)
    w, h = max(1, round(img.width_px * s)), max(1, round(img.height_px * s))
    yy, xx = np.mgrid[0:h, 0:w]
    checker = np.where(((xx // 8) + (yy // 8)) % 2 == 0, 235, 200).astype(np.uint8)
    bg = Image.fromarray(np.stack([checker] * 3 + [np.full_like(checker, 255)], axis=-1), "RGBA")
    src = img.rgba.resize((w, h), Image.Resampling.LANCZOS)
    left = Image.alpha_composite(bg, src)
    m = Image.fromarray((mask * 255).astype(np.uint8)).resize((w, h), Image.Resampling.NEAREST)
    tint = np.zeros((h, w, 4), np.uint8)
    mm = np.asarray(m) > 127
    tint[mm] = (200, 30, 60, 255)
    right = Image.alpha_composite(bg, Image.fromarray(tint, "RGBA"))
    out = Image.new("RGBA", (w * 2 + 6, h), (255, 255, 255, 0))
    out.paste(left, (0, 0))
    out.paste(right, (w + 6, 0))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()

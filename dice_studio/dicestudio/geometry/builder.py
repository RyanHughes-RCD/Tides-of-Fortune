"""Build one die (outer engraved body + internal blank) from a resolved spec.

A *spec* is a plain JSON-compatible dict (see ``dicestudio.project.resolve_die_spec``).
The same spec always produces the same geometry, and its hash is used as a
cache key by the UI server.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import polylabel

from . import design as dsg
from . import logo as logomod
from .mesh3d import BooleanError, apply_features, manifold_arrays, polyhedron_to_manifold, prism
from .numbering import NumeralPlacement, build_frames, numeral_placements
from .polyhedra import (FACE_COUNTS, POLE_FAMILIES, REGULAR_FAMILIES, GeometryError, ShapeParams, die_polyhedron,
                        offset_polyhedron)
from .text import BuiltinFont, FontError, as_multipolygon, load_font, polygons_of, robust_op, text_shape
from .validate import validate_mesh

log = logging.getLogger(__name__)

MIN_READABLE_MM = 2.5
KEEPOUT_GAP_MM = 0.5


class BuildError(RuntimeError):
    def __init__(self, msg, stage="build", retry_hint=None):
        super().__init__(msg)
        self.stage = stage
        self.retry_hint = retry_hint


def spec_hash(spec, asset_digests=()):
    blob = json.dumps(spec, sort_keys=True, separators=(",", ":")) + "|" + "|".join(asset_digests)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# 2D regions
# ---------------------------------------------------------------------------

_BIG = 1e4


def _halfplane(a, b, c):
    """Polygon for a*x + b*y <= c (clipped to a large square)."""
    nrm = math.hypot(a, b)
    if nrm < 1e-12:
        return None if c >= 0 else Polygon()
    nx, ny = a / nrm, b / nrm
    cc = c / nrm
    px, py = nx * cc, ny * cc
    tx, ty = -ny, nx
    pts = [
        (px + tx * _BIG, py + ty * _BIG),
        (px - tx * _BIG, py - ty * _BIG),
        (px - tx * _BIG - nx * _BIG, py - ty * _BIG - ny * _BIG),
        (px + tx * _BIG - nx * _BIG, py + ty * _BIG - ny * _BIG),
    ]
    return Polygon(pts)


def section_polygon(frame, poly, depth, wall=0.0):
    """Cross-section of the convex body on the plane ``depth`` mm below the face (frame coords).

    With ``wall`` > 0 every *other* plane is first moved inward by ``wall`` mm
    along its own normal, so each point of the result is at least ``wall`` mm
    (true 3D distance) away from every other face of the die.
    """
    region = shapely.box(-_BIG, -_BIG, _BIG, _BIG)
    o = frame.origin - depth * frame.n
    for pl in poly.planes:
        own = float(pl.normal @ frame.n) > 1 - 1e-9 and abs(pl.offset - frame.offset) < 1e-9
        a = float(pl.normal @ frame.u)
        b = float(pl.normal @ frame.v)
        c = float(pl.offset - (0.0 if own else wall) - pl.normal @ o)
        hp = _halfplane(a, b, c)
        if hp is None:
            continue
        region = robust_op("intersection", region, hp)
        if region.is_empty:
            break
    return region


def safe_region(frame, poly, depth, edge_margin, min_wall):
    """Area of the face where a cut ``depth`` deep keeps ``min_wall`` mm of material to every other face."""
    top = frame.polygon.buffer(-edge_margin, join_style="mitre", mitre_limit=5.0)
    if depth <= 0:
        return top
    bottom = section_polygon(frame, poly, depth, wall=min_wall)
    return robust_op("intersection", top, bottom)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class FaceInfo:
    tag: int
    labels: list
    value: int
    center: list
    normal: list
    up: list
    numeral_centers: list


@dataclass
class DieResult:
    die: str
    spec_hash: str
    outer_vertices: np.ndarray = None
    outer_tris: np.ndarray = None
    blank_vertices: np.ndarray = None
    blank_tris: np.ndarray = None
    faces: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    outer_report: dict = None
    blank_report: dict = None
    blank_check: dict = None
    info: dict = field(default_factory=dict)
    cut_depths: dict = field(default_factory=dict)  # face tag -> deepest cut (mm)
    plane_data: list = field(default_factory=list)  # [(normal, offset, kind)] of the outer body
    layout: dict = field(default_factory=dict)  # face tag -> frame + 2D cut outlines (for inspection/tests)

    @property
    def ok(self):
        return not self.errors

    def summary(self):
        return {
            "die": self.die,
            "hash": self.spec_hash,
            "ok": self.ok,
            "warnings": self.warnings,
            "errors": self.errors,
            "outer_report": self.outer_report,
            "blank_report": self.blank_report,
            "blank_check": self.blank_check,
            "faces": [f.__dict__ for f in self.faces],
            "info": self.info,
            "planes": [[*n, off] for n, off, _ in self.plane_data],
        }


# ---------------------------------------------------------------------------
# Numeral layout
# ---------------------------------------------------------------------------

def _place(geom, center, rotation):
    g = affinity.rotate(geom, rotation, origin=(0, 0), use_radians=True)
    return affinity.translate(g, center[0], center[1])


def _numeral_centers(die, frames, placements, opts):
    """Decide where each numeral sits on its face (frame coordinates)."""
    off = opts.get("offset_mm") or [0.0, 0.0]
    for p in placements:
        fr = frames[p.face_tag]
        if p.role == "corner":
            # D4: numerals between the centre and their corner / edge
            dirn = np.array([-math.sin(p.rotation), math.cos(p.rotation)])
            if opts.get("d4_style", "apex") == "apex":
                reach = max(np.linalg.norm(v) for v in fr.base_vertices2d)
                c = dirn * reach * float(opts.get("d4_radius", 0.42))
            else:
                reach = min(np.linalg.norm((fr.base_vertices2d[k] + fr.base_vertices2d[(k + 1) % 3]) / 2) for k in range(3))
                c = -dirn * reach * float(opts.get("d4_radius", 0.42)) * 1.25
            p.center = (float(c[0]), float(c[1]))
        else:
            if opts.get("_regular", False):
                c = (0.0, 0.0)  # regular polygon: centroid == incentre
            else:
                # irregular congruent faces (kites, isosceles triangles, rhombi, pyritohedral
                # pentagons): centre the numeral on the largest inscribed circle
                pl = polylabel(fr.polygon, tolerance=0.01)
                c = (pl.x, pl.y)
            p.center = (c[0] + float(off[0]), c[1] + float(off[1]))
    return placements


def _numeral_geom(font, fallback, text, height, opts, marker, cache):
    key = (text, round(height, 4), marker)
    if key not in cache:
        cache[key] = text_shape(
            font, text, height,
            embolden_mm=float(opts.get("embolden_mm", 0.0)),
            segments=int(opts.get("curve_segments", 8)),
            marker=(opts.get("six_nine_marker", "underline") if marker else None),
            fallback=fallback,
        )
    return cache[key]


def _layout_ok(placements_by_face, regions, height, font, fallback, opts, cache, gap):
    for tag, pls in placements_by_face.items():
        region = regions[tag]
        placed = []
        for p in pls:
            ts = _numeral_geom(font, fallback, p.text, height, opts, p.marker, cache)
            g = _place(ts.geom, p.center, p.rotation + math.radians(float(opts.get("rotation_deg", 0.0))))
            if not g.within(region):
                return False
            for q in placed:
                if g.distance(q) < gap:
                    return False
            placed.append(g)
    return True


def fit_numerals(die, frames, placements, regions, font, fallback, opts, cache):
    """Largest numeral height that fits every face's safe region (binary search)."""
    by_face = {}
    for p in placements:
        by_face.setdefault(p.face_tag, []).append(p)
    # Test only the faces carrying the widest labels while searching (faces are congruent),
    # then verify every face at the final size.
    widths = {}
    for tag, pls in by_face.items():
        widths[tag] = max(len(p.text) + (0.5 if p.marker else 0) for p in pls)
    probe_tags = sorted(by_face, key=lambda t: -widths[t])[:3]
    if die == "d4" or not opts.get("_regular", False):
        probe_tags = list(by_face)
    probe = {t: by_face[t] for t in probe_tags}
    gap = 0.6
    lo, hi = 0.0, 40.0
    if not _layout_ok(probe, regions, 0.8, font, fallback, opts, cache, gap):
        return 0.0
    lo = 0.8
    for _ in range(16):
        mid = (lo + hi) / 2
        if _layout_ok(probe, regions, mid, font, fallback, opts, cache, gap):
            lo = mid
        else:
            hi = mid
    # final verification across all faces
    h = lo
    while h > 0.8 and not _layout_ok(by_face, regions, h, font, fallback, opts, cache, gap):
        h *= 0.97
    return h


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def build_die(spec, asset_loader=None, validate=True):
    """Build a die from a resolved spec.  ``asset_loader(asset_id) -> bytes``."""
    t0 = time.time()
    die = spec["die"]
    res = DieResult(die=die, spec_hash=spec.get("hash", ""))
    try:
        _build(spec, res, asset_loader)
    except (GeometryError, FontError, logomod.LogoError, BooleanError, BuildError, ValueError) as exc:
        stage = getattr(exc, "stage", type(exc).__name__)
        res.errors.append(f"{die.upper()}: {exc}")
        res.info["error_stage"] = stage
        res.info["retry_available"] = not spec.get("quality", {}).get("safe_mode", False)
        log.warning("build of %s failed: %s", die, exc)
        return res
    except Exception as exc:  # unexpected kernel/library error: report it, never crash the request
        log.exception("unexpected error building %s", die)
        res.errors.append(f"{die.upper()}: unexpected geometry error ({type(exc).__name__}: {exc})")
        res.info["error_stage"] = "internal"
        res.info["retry_available"] = not spec.get("quality", {}).get("safe_mode", False)
        return res
    if validate:
        res.outer_report = validate_mesh(res.outer_vertices, res.outer_tris, f"{die}", expect_genus=0).to_dict()
        res.blank_report = validate_mesh(res.blank_vertices, res.blank_tris, f"{die}_blank", expect_genus=0).to_dict()
    res.info["build_seconds"] = round(time.time() - t0, 3)
    return res


def _build(spec, res, asset_loader):
    die = spec["die"]
    design = dsg.validate_design(spec["design"])
    num = spec["numbers"]
    quality = spec.get("quality", {})
    safe_mode = bool(quality.get("safe_mode", False))
    nopts = dict(num)
    nopts["curve_segments"] = 5 if safe_mode else int(quality.get("curve_segments", 8))

    family, param = dsg.shape_of(design, die)
    shape = ShapeParams(size_mm=float(spec["size_mm"]) * float(design["size_scale"]), family=family, param=param)
    poly, base, w = die_polyhedron(die, shape)
    res.warnings += w
    nopts["_regular"] = family in REGULAR_FAMILIES
    frames = build_frames(die, poly, base, num.get("align"), pole=family in POLE_FAMILIES)
    placements = numeral_placements(die, frames, base, nopts)
    placements = _numeral_centers(die, frames, placements, nopts)

    depth = float(num.get("depth_mm", 0.75))
    engrave = bool(num.get("engrave", True))
    min_wall = float(num.get("min_wall_mm", 0.6))
    edge_margin = float(num.get("edge_margin_mm", 0.45))
    if not (0.1 <= depth <= 3.0):
        raise BuildError("engraving depth must be between 0.1 and 3.0 mm", "numbers")

    # font
    fspec = spec.get("font") or {}
    fallback = BuiltinFont(600)
    if fspec.get("asset_id"):
        if asset_loader is None:
            raise BuildError("font asset unavailable", "font")
        data = asset_loader(fspec["asset_id"])
        if data is None:
            raise BuildError(f"font file {fspec.get('name')!r} is missing from the project assets", "font")
        font = load_font(data, fspec.get("name", "font"), fspec.get("weight"), fspec["asset_id"])
    else:
        font = BuiltinFont(fspec.get("weight") or 600)

    # logo (D20 only, on the face numbered 20)
    logo_spec = spec.get("logo") if die == "d20" else None
    logo_on = bool(logo_spec and logo_spec.get("enabled") and logo_spec.get("asset_id"))
    logo_tag = None
    if logo_on:
        logo_tag = next(p.face_tag for p in placements if p.value == 20)
        if logo_spec.get("replace_numeral", True):
            placements = [p for p in placements if p.face_tag != logo_tag]

    # numeral regions & size
    regions = {tag: safe_region(fr, poly, depth, edge_margin, min_wall) for tag, fr in frames.items()}
    cache = {}
    h_fit = fit_numerals(die, frames, placements, regions, font, fallback, nopts, cache) if placements else 99
    if placements and h_fit <= 0:
        raise BuildError("numerals do not fit on the faces at any size; reduce weight, depth or wall settings",
                         "numbers")
    explicit = num.get("height_mm")
    fill = float(num.get("size_fill", 0.88))
    if explicit:
        height = float(explicit)
        if height > h_fit:
            res.warnings.append(f"numeral height {height:.2f} mm does not fit; reduced to {h_fit:.2f} mm")
            height = h_fit
    else:
        height = h_fit * fill
    if placements and height < MIN_READABLE_MM:
        res.warnings.append(f"numerals are only {height:.2f} mm tall and may be hard to read")
    res.info["numeral_height_mm"] = round(height, 3)
    res.info["numeral_max_height_mm"] = round(h_fit, 3)

    # numeral geometry per face
    rot_extra = math.radians(float(nopts.get("rotation_deg", 0.0)))
    numeral_geoms = {}
    glyph_warn = set()
    for p in placements:
        ts = _numeral_geom(font, fallback, p.text, height, nopts, p.marker, cache)
        glyph_warn.update(ts.warnings)
        g = _place(ts.geom, p.center, p.rotation + rot_extra)
        numeral_geoms.setdefault(p.face_tag, []).append(g)
    res.warnings += sorted(glyph_warn)
    numeral_geoms = {t: as_multipolygon(shapely.union_all(gs)) for t, gs in numeral_geoms.items()}

    # logo geometry
    logo_geom = None
    logo_depth = float(logo_spec.get("depth_mm", 0.75)) if logo_on else 0.0
    if logo_on:
        logo_geom = _build_logo(logo_spec, frames[logo_tag], poly, edge_margin, min_wall, res, asset_loader,
                                numeral_geoms.get(logo_tag), safe_mode)

    # cutters: the numerals and the optional logo are the only cuts
    cutters = []
    cut_depths = {t: 0.0 for t in frames}
    top = 1.5
    seg_simplify = 0.01 if safe_mode else 0.0
    for tag, fr in frames.items():
        M = fr.matrix()
        if tag in numeral_geoms:
            if engrave:
                cutters.append(prism(numeral_geoms[tag], M, -depth, top, seg_simplify))
                cut_depths[tag] = max(cut_depths[tag], depth)
        res.layout[tag] = {"origin": fr.origin, "u": fr.u, "v": fr.v, "n": fr.n, "offset": fr.offset,
                           "polygon": fr.polygon, "numerals": numeral_geoms.get(tag), "logo": None,
                           "numeral_depth": depth if engrave else 0.0}
        if logo_geom is not None and tag == logo_tag:
            res.layout[tag]["logo"] = logo_geom
            res.layout[tag]["logo_depth"] = logo_depth
            cutters.append(prism(logo_geom, M, -logo_depth, top, seg_simplify))
            cut_depths[tag] = max(cut_depths[tag], logo_depth)
    res.cut_depths = cut_depths

    body = polyhedron_to_manifold(poly)
    try:
        outer = apply_features(body, cutters, [])
    except BooleanError as exc:
        raise BooleanError(f"{exc}. Use 'Retry with safe geometry' to rebuild with simplified "
                           "outlines.") from exc
    res.outer_vertices, res.outer_tris = manifold_arrays(outer)

    # internal blank
    _build_blank(spec, poly, outer, cut_depths, res)

    # face info for the UI
    for tag, fr in sorted(frames.items()):
        labels = [p.text for p in placements if p.face_tag == tag]
        val = next((p.value for p in placements if p.face_tag == tag and p.role == "primary"), None)
        if die == "d4":
            val = tag + 1
        if tag == logo_tag and logo_on and not labels:
            labels = ["(logo)"]
            val = 20
        res.faces.append(FaceInfo(
            tag=int(tag), labels=labels, value=val,
            center=[float(x) for x in fr.origin], normal=[float(x) for x in fr.n], up=[float(x) for x in fr.v],
            numeral_centers=[[float(x) for x in fr.to3d(p.center)[0]] for p in placements if p.face_tag == tag],
        ))
    res.plane_data = [(p.normal.tolist(), float(p.offset), p.kind) for p in poly.planes]
    res.info.update({
        "faces": len(frames),
        "expected_faces": FACE_COUNTS[die],
        "size_mm": shape.size_mm,
        "engrave_depth_mm": depth if engrave else 0.0,
        "logo_face": logo_tag,
        "outer_volume_mm3": float(outer.volume()),
        "safe_mode": safe_mode,
        "design": design,
        "shape": family,
        "shape_param": param,
    })


def _build_logo(ls, frame, poly, edge_margin, min_wall, res, asset_loader, numeral_geom, safe_mode):
    data = asset_loader(ls["asset_id"]) if asset_loader else None
    if data is None:
        raise BuildError(f"logo image {ls.get('name')!r} is missing from the project assets", "logo")
    shape = logomod.logo_shape(data, int(ls.get("threshold", 128)), bool(ls.get("invert", False)),
                               ls.get("mask_mode", "auto"), float(ls.get("simplify_px", 0.6)))
    depth = float(ls.get("depth_mm", 0.75))
    if not (0.1 <= depth <= 3.0):
        raise BuildError("logo depth must be between 0.1 and 3.0 mm", "logo")
    region = safe_region(frame, poly, depth, edge_margin + 0.1, min_wall)
    if numeral_geom is not None:
        region = robust_op("difference", region, numeral_geom.buffer(KEEPOUT_GAP_MM))
    width = float(ls.get("width_mm", 6.0))
    rot = float(ls.get("rotation_deg", 0.0))
    off = ls.get("offset_mm") or [0.0, 0.0]
    # the logo box (not just ink) must stay inside the face, preserving aspect
    g = logomod.place_logo(shape, width, rot, off)
    if not g.within(region):
        lo, hi = 0.0, width
        for _ in range(18):
            mid = (lo + hi) / 2
            if logomod.place_logo(shape, mid, rot, off).within(region):
                lo = mid
            else:
                hi = mid
        if lo < 1.0:
            raise BuildError("the logo does not fit on the 20 face at its current position; move it towards the "
                             "centre or reduce its size", "logo")
        res.warnings.append(f"logo width reduced from {width:.2f} to {lo:.2f} mm to stay inside the 20 face")
        width = lo
        g = logomod.place_logo(shape, width, rot, off)
    min_feat = float(ls.get("min_feature_mm", 0.3))
    if ls.get("remove_fine", False) or safe_mode:
        g = logomod.remove_fine_details(g, min_feat)
        if g.is_empty:
            raise BuildError("removing fine details left nothing of the logo; enlarge it", "logo")
    rep = logomod.fine_detail_report(g, min_feat, min_feat)
    res.warnings += [f"logo: {w}" for w in rep["warnings"]]
    res.info["logo"] = {"width_mm": round(width, 3), "height_mm": round(width * shape.aspect, 3),
                        "components": shape.components, "holes": shape.holes, "mask_mode": shape.mask_mode,
                        "thin_fraction": round(rep["thin_fraction"], 4)}
    return g


def _build_blank(spec, poly, outer, cut_depths, res):
    import manifold3d as m3d

    bs = spec.get("blank", {})
    clearance = float(bs.get("clearance_mm", 0.5))
    ref = bs.get("reference", "deepest_cut_uniform")
    min_thick = float(bs.get("min_thickness_mm", 2.0))
    if not (0.0 <= clearance <= 5.0):
        raise BuildError("blank clearance must be between 0 and 5 mm", "blank")
    if ref not in ("face_plane", "deepest_cut_uniform", "deepest_cut_per_face"):
        raise BuildError(f"unknown clearance reference {ref!r}", "blank")
    deepest = max(cut_depths.values()) if cut_depths else 0.0
    offsets = []
    for pl in poly.planes:
        if ref == "face_plane":
            offsets.append(clearance)
        elif ref == "deepest_cut_uniform":
            offsets.append(clearance + deepest)
        else:
            offsets.append(clearance + (cut_depths.get(pl.tag, 0.0) if pl.kind == "face" else 0.0))
    try:
        blank = offset_polyhedron(poly, offsets)
    except GeometryError as exc:
        raise BuildError(f"the blank vanishes with {clearance:.2f} mm clearance ({exc}); reduce the clearance, "
                         "engraving depth or increase the die size", "blank") from exc
    check = {"clearance_mm": clearance, "reference": ref, "deepest_cut_mm": deepest, "issues": [], "faces": []}
    # 1. every blank vertex lies on the inner side of every offset plane
    worst = math.inf
    for i, pl in enumerate(poly.planes):
        proj = blank.vertices @ pl.normal
        gap_plane = pl.offset - float(proj.max())  # distance from outer face plane to blank
        need = offsets[i]
        worst = min(worst, gap_plane - need)
        if pl.kind == "face":
            check["faces"].append({
                "tag": int(pl.tag),
                "plane_gap_mm": round(gap_plane, 6),
                "required_mm": round(need, 6),
                "gap_from_cut_floor_mm": round(gap_plane - cut_depths.get(pl.tag, 0.0), 6),
            })
    check["min_plane_margin_mm"] = worst
    if worst < -1e-6:
        check["issues"].append(f"blank crosses a clearance plane by {-worst:.4f} mm")
    # 2. volume and thickness
    vol = blank.volume()
    check["volume_mm3"] = vol
    widths = [blank.width_along(f.normal) for f in blank.faces]
    check["min_thickness_mm"] = min(widths)
    if vol <= 0:
        check["issues"].append("blank has zero volume")
    if min(widths) < min_thick:
        check["issues"].append(f"blank is only {min(widths):.2f} mm thick (minimum {min_thick:.2f} mm); "
                               "reduce clearance/engraving depth or enlarge the die")
    nf_outer = sum(1 for f in poly.faces if f.kind == "face")
    nf_blank = sum(1 for f in blank.faces if f.kind == "face")
    if nf_blank != nf_outer:
        check["issues"].append(f"blank lost {nf_outer - nf_blank} of its main faces")
    # 3. true containment inside the engraved outer solid
    bman = polyhedron_to_manifold(blank)
    outside = m3d.Manifold.batch_boolean([bman, outer], m3d.OpType.Subtract)
    check["volume_outside_outer_mm3"] = float(outside.volume())
    if outside.volume() > 1e-6:
        check["issues"].append(f"{outside.volume():.4f} mm^3 of the blank lies outside the engraved outer die")
    # 4. measured minimum distance between the blank and the engraved outer surface
    #    (distance from the blank to the complement of the outer solid)
    span = float(np.ptp(poly.vertices, axis=0).max())
    complement = m3d.Manifold.batch_boolean(
        [m3d.Manifold.cube((span * 3, span * 3, span * 3), True), outer], m3d.OpType.Subtract)
    search = max(clearance, 0.01) + deepest + 1.0
    gap = float(bman.min_gap(complement, search)) if outside.volume() <= 1e-6 else 0.0
    check["measured_min_gap_mm"] = gap
    if ref != "face_plane" and gap < clearance - 1e-4:
        check["issues"].append(f"measured clearance {gap:.3f} mm is below the required {clearance:.3f} mm")
    check["ok"] = not check["issues"]
    res.blank_check = check
    if check["issues"]:
        res.warnings += [f"blank: {m}" for m in check["issues"]]
    res.blank_vertices, res.blank_tris = manifold_arrays(bman)

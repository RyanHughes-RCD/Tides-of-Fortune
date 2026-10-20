"""Project model: defaults, validation, randomisation, per-die specs, save/open.

A project is a JSON-compatible dict.  ``style`` and ``density`` (shown as
"shape variation") drive the random choice of congruent-face shape families
and proportions.  It stores the *resolved* family design
as well as the seed, so reopening reproduces the exact geometry even if the
random generator is later changed, while the seed still allows regeneration.

Saved project files (``.tdice``) are zip archives containing ``project.json``
and an ``assets/`` folder with copies of the imported font and logo, so a
project can be moved between computers.
"""
from __future__ import annotations

import copy
import json
import random
import zipfile
from pathlib import Path

from .geometry import design as deco
from .geometry.builder import spec_hash
from .geometry.numbering import (ALIGN_MODES, D4_STYLES, D10_STYLES, D100_STYLES, DEFAULT_D10_TOP,
                                 MARKER_STYLES, validate_d10_top)
from .geometry.polyhedra import DIE_TYPES, SIZE_LIMITS_MM, GeometryError, default_size_mm

FORMAT = "tides-dice-studio-project"
VERSION = 1
PROJECT_EXT = ".tdice"
CLEARANCE_REFS = ("deepest_cut_uniform", "deepest_cut_per_face", "face_plane")


class ProjectError(ValueError):
    pass


def _die_defaults():
    return {
        "variant": 0,
        "size_mm": None,  # None = default size for this die
        "design_overrides": {},
        "font": None,  # None = use the global font; otherwise {"asset": {...}|None, "weight": .., "embolden_mm": ..}
        "height_mm": None,  # None = automatic (fit * size_fill)
        "size_fill": None,
        "offset_mm": [0.0, 0.0],
        "rotation_deg": 0.0,
        "align": None,
        "engrave": None,  # None = global setting
        "safe_mode": False,
    }


def default_project(seed=None, style="classic", density=0.5, name="MySet"):
    if seed is None:
        seed = random.SystemRandom().randrange(1, 10**9)
    p = {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "seed": int(seed),
        "style": style,
        "density": float(density),
        "design": deco.generate_design(seed, style, density),
        "locks": [],
        "font": {"asset": None, "weight": 600, "embolden_mm": 0.0},
        "numbers": {
            "engrave": True,
            "depth_mm": 0.75,
            "size_fill": 0.88,
            "six_nine_marker": "underline",
            "d4_style": "auto",
            "d10_style": "0-9",
            "d100_style": "00-90",
            "d10_top_order": list(DEFAULT_D10_TOP),
            "min_wall_mm": 0.6,
            "edge_margin_mm": 0.45,
        },
        "logo": {
            "asset": None,
            "enabled": False,
            "threshold": 128,
            "invert": False,
            "mask_mode": "auto",
            "width_mm": 6.0,
            "rotation_deg": 0.0,
            "offset_mm": [0.0, 0.0],
            "depth_mm": 0.75,
            "replace_numeral": True,
            "min_feature_mm": 0.3,
            "remove_fine": False,
            "simplify_px": 0.6,
        },
        "blank": {"clearance_mm": 0.5, "reference": "deepest_cut_uniform", "min_thickness_mm": 2.0},
        "export": {"directory": "", "prefix": name, "unit": "mm", "allow_invalid": False},
        "quality": {"curve_segments": 8},
        "dice": {d: _die_defaults() for d in DIE_TYPES},
    }
    return p


def _num(v, lo, hi, label):
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ProjectError(f"{label} must be a number")
    if not (lo <= v <= hi):
        raise ProjectError(f"{label} must be between {lo} and {hi}")
    return v


def _asset_ref(a, label):
    if a is None:
        return None
    if not isinstance(a, dict) or not isinstance(a.get("id"), str):
        raise ProjectError(f"{label}: invalid asset reference")
    return {"id": a["id"], "name": str(a.get("name", a["id"]))}


def validate_project(p):
    """Return a normalised deep copy, raising ProjectError with a readable message."""
    if not isinstance(p, dict):
        raise ProjectError("project must be an object")
    base = default_project(seed=p.get("seed", 1), style=p.get("style", "classic"),
                           density=p.get("density", 0.5)) if p.get("style") in deco.STYLES else None
    if base is None:
        raise ProjectError(f"unknown style {p.get('style')!r}; choose one of {list(deco.STYLES)}")
    out = copy.deepcopy(base)
    out["name"] = str(p.get("name") or "MySet").strip()[:60] or "MySet"
    out["seed"] = int(p.get("seed", 1))
    out["density"] = _num(p.get("density", 0.5), 0, 1, "Detail density")
    try:
        out["design"] = deco.validate_design({**base["design"], **deco.migrate_design(p.get("design"))})
    except ValueError as exc:
        raise ProjectError(str(exc))
    locks = p.get("locks") or []
    out["locks"] = [k for k in locks if k in deco.SCHEMA_BY_KEY]
    f = p.get("font") or {}
    out["font"] = {
        "asset": _asset_ref(f.get("asset"), "font"),
        "weight": _num(f.get("weight", 600), 100, 1000, "Font weight"),
        "embolden_mm": _num(f.get("embolden_mm", 0.0), -0.3, 0.3, "Weight adjustment"),
    }
    n = {**base["numbers"], **(p.get("numbers") or {})}
    n["engrave"] = bool(n["engrave"])
    n["depth_mm"] = _num(n["depth_mm"], 0.1, 3.0, "Engraving depth")
    n["size_fill"] = _num(n["size_fill"], 0.3, 1.0, "Numeral size")
    n["min_wall_mm"] = _num(n["min_wall_mm"], 0.2, 3.0, "Minimum wall")
    n["edge_margin_mm"] = _num(n["edge_margin_mm"], 0.1, 3.0, "Edge margin")
    for key, allowed in (("six_nine_marker", MARKER_STYLES), ("d4_style", D4_STYLES), ("d10_style", D10_STYLES),
                         ("d100_style", D100_STYLES)):
        if n[key] not in allowed:
            raise ProjectError(f"{key} must be one of {allowed}")
    try:
        n["d10_top_order"] = [int(x) for x in n["d10_top_order"]]
        validate_d10_top(n["d10_top_order"])
    except (GeometryError, TypeError, ValueError) as exc:
        raise ProjectError(str(exc))
    out["numbers"] = n
    lg = {**base["logo"], **(p.get("logo") or {})}
    lg["asset"] = _asset_ref(lg.get("asset"), "logo")
    lg["enabled"] = bool(lg["enabled"])
    lg["threshold"] = int(_num(lg["threshold"], 1, 255, "Logo threshold"))
    lg["invert"] = bool(lg["invert"])
    if lg["mask_mode"] not in ("auto", "alpha", "luminance"):
        raise ProjectError("logo mask mode must be auto, alpha or luminance")
    lg["width_mm"] = _num(lg["width_mm"], 1.0, 30.0, "Logo width")
    lg["rotation_deg"] = _num(lg["rotation_deg"], -360, 360, "Logo rotation")
    lg["offset_mm"] = [_num(x, -15, 15, "Logo offset") for x in lg["offset_mm"]]
    lg["depth_mm"] = _num(lg["depth_mm"], 0.1, 3.0, "Logo depth")
    lg["replace_numeral"] = bool(lg["replace_numeral"])
    lg["min_feature_mm"] = _num(lg["min_feature_mm"], 0.05, 2.0, "Minimum logo feature")
    lg["remove_fine"] = bool(lg["remove_fine"])
    lg["simplify_px"] = _num(lg["simplify_px"], 0.0, 4.0, "Logo smoothing")
    out["logo"] = lg
    b = {**base["blank"], **(p.get("blank") or {})}
    b["clearance_mm"] = _num(b["clearance_mm"], 0.0, 5.0, "Blank clearance")
    b["min_thickness_mm"] = _num(b["min_thickness_mm"], 0.5, 20.0, "Minimum blank thickness")
    if b["reference"] not in CLEARANCE_REFS:
        raise ProjectError(f"clearance reference must be one of {CLEARANCE_REFS}")
    out["blank"] = b
    e = {**base["export"], **(p.get("export") or {})}
    if e["unit"] not in ("mm", "cm", "in"):
        raise ProjectError("export unit must be mm, cm or in")
    e["prefix"] = safe_filename(e.get("prefix") or out["name"])
    e["directory"] = str(e.get("directory") or "")
    e["allow_invalid"] = bool(e.get("allow_invalid"))
    out["export"] = e
    q = {**base["quality"], **(p.get("quality") or {})}
    q["curve_segments"] = int(_num(q["curve_segments"], 3, 24, "Curve segments"))
    out["quality"] = q
    dice = p.get("dice") or {}
    for d in DIE_TYPES:
        dd = {**_die_defaults(), **(dice.get(d) or {})}
        dd["variant"] = int(dd["variant"])
        if dd["size_mm"] is not None:
            dd["size_mm"] = _num(dd["size_mm"], *SIZE_LIMITS_MM, f"{d.upper()} size")
        ov = deco.migrate_design(dd.get("design_overrides"))
        try:
            deco.validate_design({**out["design"], **ov})
        except ValueError as exc:
            raise ProjectError(f"{d.upper()}: {exc}")
        dd["design_overrides"] = {k: v for k, v in ov.items() if k in deco.SCHEMA_BY_KEY}
        if dd["font"] is not None:
            fo = dd["font"]
            dd["font"] = {
                "asset": _asset_ref(fo.get("asset"), f"{d} font"),
                "weight": _num(fo.get("weight", 600), 100, 1000, "Font weight"),
                "embolden_mm": _num(fo.get("embolden_mm", 0.0), -0.3, 0.3, "Weight adjustment"),
            }
        if dd["height_mm"] is not None:
            dd["height_mm"] = _num(dd["height_mm"], 1.0, 20.0, f"{d.upper()} numeral height")
        if dd["size_fill"] is not None:
            dd["size_fill"] = _num(dd["size_fill"], 0.3, 1.0, f"{d.upper()} numeral size")
        dd["offset_mm"] = [_num(x, -10, 10, "Numeral offset") for x in dd["offset_mm"]]
        dd["rotation_deg"] = _num(dd["rotation_deg"], -180, 180, "Numeral rotation")
        if dd["align"] is not None and dd["align"] not in ALIGN_MODES:
            raise ProjectError(f"alignment must be one of {ALIGN_MODES}")
        if dd["engrave"] is not None:
            dd["engrave"] = bool(dd["engrave"])
        dd["safe_mode"] = bool(dd["safe_mode"])
        out["dice"][d] = dd
    return out


def safe_filename(s):
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in str(s)).strip().replace(" ", "_")
    return keep[:60] or "MySet"


# ---------------------------------------------------------------------------
# Design operations
# ---------------------------------------------------------------------------

def die_design(p, die):
    d = p["dice"][die]
    des = deco.die_variant(p["design"], p["seed"], die, d["variant"], p["locks"], p["style"], p["density"])
    des.update(d["design_overrides"])
    return deco.validate_design(des)


def randomize_set(p, seed=None):
    """New seed; unlocked family features re-rolled; die variants and overrides of unlocked keys cleared."""
    p = copy.deepcopy(p)
    p["seed"] = int(seed if seed is not None else random.SystemRandom().randrange(1, 10**9))
    p["design"] = deco.generate_design(p["seed"], p["style"], p["density"], base=p["design"], locks=p["locks"])
    for d in DIE_TYPES:
        p["dice"][d]["variant"] = 0
        p["dice"][d]["design_overrides"] = {
            k: v for k, v in p["dice"][d]["design_overrides"].items() if k in p["locks"]}
    return p


def regenerate_design(p):
    """Re-derive the family design from the current seed/style/density (respecting locks)."""
    p = copy.deepcopy(p)
    p["design"] = deco.generate_design(p["seed"], p["style"], p["density"], base=p["design"], locks=p["locks"])
    return p


def regenerate_die(p, die):
    p = copy.deepcopy(p)
    p["dice"][die]["variant"] += 1
    p["dice"][die]["design_overrides"] = {
        k: v for k, v in p["dice"][die]["design_overrides"].items() if k in p["locks"]}
    return p


def reset_die(p, die):
    p = copy.deepcopy(p)
    p["dice"][die] = _die_defaults()
    return p


def reset_set(p):
    """Back to the generated design for the current seed, discarding all per-die changes."""
    q = default_project(p["seed"], p["style"], p["density"], p["name"])
    q["font"] = copy.deepcopy(p["font"])
    q["logo"] = copy.deepcopy(p["logo"])
    q["export"] = copy.deepcopy(p["export"])
    return q


def duplicate_project(p, new_name=None):
    q = copy.deepcopy(p)
    q["name"] = new_name or f"{p['name']} copy"
    q["export"]["prefix"] = safe_filename(q["name"])
    return q


# ---------------------------------------------------------------------------
# Resolution to builder specs
# ---------------------------------------------------------------------------

def resolve_die_spec(p, die):
    d = p["dice"][die]
    font = d["font"] if d["font"] is not None else p["font"]
    nums = dict(p["numbers"])
    nums["engrave"] = p["numbers"]["engrave"] if d["engrave"] is None else d["engrave"]
    nums["height_mm"] = d["height_mm"]
    nums["size_fill"] = d["size_fill"] if d["size_fill"] is not None else p["numbers"]["size_fill"]
    nums["offset_mm"] = list(d["offset_mm"])
    nums["rotation_deg"] = d["rotation_deg"]
    nums["align"] = d["align"]
    nums["embolden_mm"] = font["embolden_mm"]
    spec = {
        "die": die,
        "size_mm": d["size_mm"] or default_size_mm(die, die_design(p, die)[f"{die}_shape"]),
        "design": die_design(p, die),
        "numbers": nums,
        "font": {"asset_id": font["asset"]["id"] if font["asset"] else None,
                 "name": font["asset"]["name"] if font["asset"] else "Built-in Geometric",
                 "weight": font["weight"]},
        "blank": dict(p["blank"]),
        "quality": {**p["quality"], "safe_mode": d["safe_mode"]},
    }
    if die == "d20":
        lg = dict(p["logo"])
        lg["asset_id"] = lg["asset"]["id"] if lg["asset"] else None
        lg["name"] = lg["asset"]["name"] if lg["asset"] else None
        lg.pop("asset")
        spec["logo"] = lg
    spec["hash"] = spec_hash({k: v for k, v in spec.items() if k != "hash"})
    return spec


def project_asset_ids(p):
    ids = []
    if p["font"]["asset"]:
        ids.append(p["font"]["asset"]["id"])
    if p["logo"]["asset"]:
        ids.append(p["logo"]["asset"]["id"])
    for d in DIE_TYPES:
        f = p["dice"][d]["font"]
        if f and f.get("asset"):
            ids.append(f["asset"]["id"])
    return list(dict.fromkeys(ids))


# ---------------------------------------------------------------------------
# Save / open
# ---------------------------------------------------------------------------

def save_project(p, path, store):
    p = validate_project(p)
    path = Path(path)
    if path.suffix.lower() != PROJECT_EXT:
        path = path.with_suffix(PROJECT_EXT)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(PROJECT_EXT + ".tmp")
    missing = []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(p, indent=2))
        manifest = {}
        for aid in project_asset_ids(p):
            info = store.info(aid)
            data = store.get(aid)
            if data is None or info is None:
                missing.append(aid)
                continue
            arc = f"assets/{aid}{info['ext']}"
            z.writestr(arc, data)
            manifest[aid] = {"file": arc, "name": info["name"], "kind": info["kind"]}
        z.writestr("assets/manifest.json", json.dumps(manifest, indent=2))
    if missing:
        tmp.unlink(missing_ok=True)
        raise ProjectError(f"cannot save: imported file(s) {missing} are missing; re-import them")
    tmp.replace(path)
    return str(path)


def open_project(path_or_bytes, store):
    import io

    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    try:
        with zipfile.ZipFile(src) as z:
            p = json.loads(z.read("project.json"))
            manifest = json.loads(z.read("assets/manifest.json")) if "assets/manifest.json" in z.namelist() else {}
            for aid, m in manifest.items():
                ref = store.put(z.read(m["file"]), m["name"], m["kind"])
                if ref["id"] != aid:
                    raise ProjectError(f"asset {m['name']} is corrupted (checksum mismatch)")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ProjectError(f"not a valid {PROJECT_EXT} project file: {exc}")
    if p.get("format") != FORMAT:
        raise ProjectError("file is not a Tides Dice Studio project")
    if int(p.get("version", 0)) > VERSION:
        raise ProjectError("project was saved by a newer version of the application")
    return validate_project(p)

"""Shape design: which shape family each die uses, and its proportions.

A *design* is a flat dict of parameters (see DESIGN_SCHEMA):

* ``<die>_shape``              the family (e.g. "d6_shape": "gemstone");
* ``<die>_<family>_<param>``   that family's proportions (e.g. "d6_gemstone_crown").

A set's design is generated from (seed, style, variation); "regenerate this
die" re-rolls only that die's keys.  Locked keys are never changed by
randomisation.  Roller shapes (crystals, shards, gems) are only accepted when
the rest analysis confirms they roll onto a numbered side and cannot rest on
an end facet; rejected samples are re-rolled.

There is deliberately no surface decoration: the only cuts in a die are its
engraved numbers (and the optional D20 logo).
"""
from __future__ import annotations

import math
import random

from .polyhedra import (CURVED_FAMILIES, DIE_TYPES, FAMILIES, REGULAR_FAMILIES, ROLLER_FAMILIES, GeometryError,
                        ShapeParams, check_landing, die_polyhedron)

STYLES = {
    "classic": "Classic (regular solids, subtle proportions)",
    "elongated": "Elongated (stretched, skewed faces)",
    "geometric": "Geometric (wide, flattened)",
    "crystal": "Crystal rollers (pointed prisms, D6 gemstone)",
    "shard": "Shard rollers (long and short points)",
    "mixed": "Mixed (any shape)",
}

# keys from earlier versions -> current keys
_LEGACY_KEYS = {
    "d4_stretch": "d4_disphenoid_stretch", "d6_angle": "d6_rhombohedron_angle",
    "d8_height": "d8_bipyramid_height", "d10_elongation": "d10_trapezohedron_elongation",
    "d100_elongation": "d100_trapezohedron_elongation", "d12_pentagon": "d12_pyritohedron_pentagon",
    "d12_height": "d12_bipyramid_height", "d20_height": "d20_bipyramid_height",
}


def param_key(die, family, name):
    return f"{die}_{family}_{name}"


DESIGN_SCHEMA = [dict(key="size_scale", label="Set size scale", type="float", min=0.9, max=1.12, step=0.01,
                      group="Set", die=None)]
for _d in DIE_TYPES:
    DESIGN_SCHEMA.append(dict(key=f"{_d}_shape", label="Shape", type="choice", choices=list(FAMILIES[_d]),
                              labels={f: s["label"] for f, s in FAMILIES[_d].items()},
                              group=_d.upper(), die=_d))
    for _fam, _spec in FAMILIES[_d].items():
        for _name, _ps in _spec["params"].items():
            DESIGN_SCHEMA.append(dict(key=param_key(_d, _fam, _name), label=_ps["label"], type="float",
                                      min=_ps["min"], max=_ps["max"], default=_ps["default"],
                                      step=0.5 if _name == "angle" else 0.01,
                                      group=_d.upper(), die=_d, family=_fam))
SCHEMA_BY_KEY = {s["key"]: s for s in DESIGN_SCHEMA}
DIE_KEYS = {d: [s["key"] for s in DESIGN_SCHEMA if s["die"] == d] for d in DIE_TYPES}
VARIANT_KEYS = [k for d in DIE_TYPES for k in DIE_KEYS[d]]

# style -> per-die family weights ("*" = default for dice not listed) and the part of
# each parameter range to sample (0 = min, 1 = max; "*" = default for other params)
_ISO = {"d4": {"tetrahedron": 1}, "d6": {"cube": 1}, "d8": {"octahedron": 1}, "d10": {"trapezohedron": 1},
        "d12": {"dodecahedron": 1}, "d20": {"icosahedron": 1}, "d100": {"trapezohedron": 1}}
_STYLE_RULES = {
    "classic": {"families": "regular", "span": {"*": (0.35, 0.65)}},
    "elongated": {"families": {"d4": {"disphenoid": 2, "wedge": 1}, "d6": {"rhombohedron": 1},
                               "d8": {"bipyramid": 1}, "d10": {"trapezohedron": 1},
                               "d12": {"bipyramid": 2, "pyritohedron": 1}, "d20": {"bipyramid": 1},
                               "d100": {"trapezohedron": 1}},
                  "span": {"*": (0.55, 1.0), "angle": (0.0, 0.35), "pentagon": (0.6, 1.0)}},
    "geometric": {"families": {"d4": {"disphenoid": 1}, "d6": {"rhombohedron": 1}, "d8": {"bipyramid": 1},
                               "d10": {"trapezohedron": 1}, "d12": {"pyritohedron": 2, "rhombic": 1},
                               "d20": {"icosahedron": 1}, "d100": {"trapezohedron": 1}},
                  "span": {"*": (0.0, 0.3), "angle": (0.7, 1.0)}},
    # D12/D20 rollers with 12/20 long sides get narrow faces, so these styles favour the
    # two-row elongated bipyramid for them (it is read on its top face like a shard set's D20)
    "crystal": {"families": {"*": {"crystal": 1}, "d6": {"gemstone": 1, "crystal": 1},
                             "d12": {"crystal": 1, "bipyramid": 1}, "d20": {"bipyramid": 3, "crystal": 1}},
                "span": {"*": (0.0, 1.0), "height": (0.6, 1.0)}},
    "shard": {"families": {"*": {"shard": 1, "short_shard": 1},
                           "d4": {"shard": 2, "short_shard": 2, "wedge": 1, "infinity": 1},
                           "d12": {"shard": 1, "short_shard": 1, "bipyramid": 1},
                           "d20": {"bipyramid": 3, "shard": 1}},
              "span": {"*": (0.0, 1.0), "height": (0.6, 1.0)}},
    "mixed": {"families": {"*": "any",
                           # 20 narrow roller sides make small numerals: possible, but less likely
                           "d20": {"icosahedron": 2, "bipyramid": 2, "crystal": 0.5, "shard": 0.5,
                                   "short_shard": 0.5}},
              "span": {"*": (0.0, 1.0)}},
}


def _wchoice(rng, weights):
    keys = list(weights)
    r = rng.random() * sum(weights.values())
    for k in keys:
        r -= weights[k]
        if r <= 0:
            return k
    return keys[-1]


def _q(x, step):
    return round(round(x / step) * step, 4)


def _family_weights(die, style, variation):
    rules = _STYLE_RULES[style]
    fams = list(FAMILIES[die])
    f = rules["families"]
    if isinstance(f, dict) and f.get(die, f.get("*")) == "any":
        f = "any"
    if f == "any":
        return {k: 1.0 for k in fams}
    if f == "regular":
        reg = [k for k in fams if k in REGULAR_FAMILIES or k == "trapezohedron"]
        iso = [k for k in fams if FAMILIES[die][k]["kind"] == "isohedral" and k not in reg]
        p_reg = 1.0 - 0.25 * variation
        w = {k: p_reg / len(reg) for k in reg}
        w.update({k: (1 - p_reg) / len(iso) for k in iso})
        return w
    return dict(f.get(die) or f.get("*") or {fams[0]: 1})


def _shape_ok(die, family, params):
    if family in CURVED_FAMILIES:
        return True
    try:
        poly, _, _ = die_polyhedron(die, ShapeParams(16.0, family, params))
    except GeometryError:
        return False
    return not check_landing(poly)


def _roll_die(rng, die, style, variation, d):
    rules = _STYLE_RULES[style]
    weights = {k: w for k, w in _family_weights(die, style, variation).items() if w > 0}
    fam = _wchoice(rng, weights)
    d[f"{die}_shape"] = fam
    for attempt in range(60):
        params = {}
        for name, ps in FAMILIES[die][fam]["params"].items():
            lo, hi, default = ps["min"], ps["max"], ps["default"]
            a, b = rules["span"].get(name, rules["span"]["*"])
            target = lo + (hi - lo) * rng.uniform(a, b)
            # variation blends from the family's natural proportion towards the random target
            v = default + (variation if attempt < 30 else variation * 0.5) * (target - default)
            params[name] = _q(min(hi, max(lo, v)), 0.5 if name == "angle" else 0.01)
        if fam not in ROLLER_FAMILIES or _shape_ok(die, fam, params):
            break
    else:
        params = {n: ps["default"] for n, ps in FAMILIES[die][fam]["params"].items()}
    for name, v in params.items():
        d[param_key(die, fam, name)] = v
    # the other families' proportions keep their defaults (used if the user switches shape)
    for f2, spec in FAMILIES[die].items():
        for name, ps in spec["params"].items():
            d.setdefault(param_key(die, f2, name), ps["default"])


def generate_design(seed, style, density, base=None, locks=()):
    """Generate a set design.  ``density`` is the shape-variation amount (0..1)."""
    if style not in _STYLE_RULES:
        raise ValueError(f"unknown style {style!r}")
    variation = float(min(max(density, 0.0), 1.0))
    rng = random.Random(f"shape:{seed}:{style}:{variation:.3f}")
    d = {"size_scale": 1.0}
    for die in DIE_TYPES:
        _roll_die(rng, die, style, variation, d)
    if base:
        base = migrate_design(base)
        for k in locks:
            if k in base:
                d[k] = base[k]
    return validate_design(d)


def die_variant(design, seed, die, variant, locks=(), style="mixed", density=0.6):
    """The design for one die: the set design, with this die's keys re-rolled for variant > 0."""
    d = dict(design)
    if not variant:
        return d
    rng = random.Random(f"variant:{seed}:{die}:{variant}")
    rolled = {}
    _roll_die(rng, die, style, max(0.5, float(density)), rolled)
    for k, v in rolled.items():
        if k not in locks:
            d[k] = v
    return validate_design(d)


def migrate_design(d):
    d = dict(d or {})
    for old, new in _LEGACY_KEYS.items():
        if old in d:
            d.setdefault(new, d.pop(old))
    return d


def validate_design(d):
    d = migrate_design(d)
    out = {}
    for s in DESIGN_SCHEMA:
        k = s["key"]
        if k not in d:
            if s["type"] == "float" and s["die"]:
                d[k] = s["default"]
            else:
                raise ValueError(f"design is missing {k!r}")
        v = d[k]
        label = f"{s['die'].upper()} {s['label']}" if s["die"] else s["label"]
        if s["type"] == "choice":
            if v not in s["choices"]:
                raise ValueError(f"{label}: {v!r} is not one of {s['choices']}")
        else:
            v = float(v)
            if not math.isfinite(v) or not (s["min"] - 1e-9 <= v <= s["max"] + 1e-9):
                raise ValueError(f"{label} must be between {s['min']} and {s['max']}")
        out[k] = v
    return out


def shape_of(design, die):
    """(family, {param: value}) for a die."""
    fam = design[f"{die}_shape"]
    return fam, {name: design[param_key(die, fam, name)] for name in FAMILIES[die][fam]["params"]}

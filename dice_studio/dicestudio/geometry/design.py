"""Shape design: which congruent-face family each die uses, and its proportions.

A *design* is a flat dict of parameters (see DESIGN_SCHEMA).  A set's design
is generated from (seed, style, variation); "regenerate this die" re-rolls only
that die's keys.  Locked keys are never changed by randomisation.

There is deliberately no surface decoration: the only cuts in a die are its
engraved numbers (and the optional D20 logo).  Every family is face-transitive,
so all faces of a die are congruent whatever the random proportions.
"""
from __future__ import annotations

import math
import random

from .polyhedra import DIE_TYPES, FAMILIES, REGULAR_FAMILIES

STYLES = {
    "classic": "Classic (regular solids, subtle proportions)",
    "crystal": "Crystal (tall, elongated)",
    "geometric": "Geometric (wide, flattened)",
    "mixed": "Mixed (any shape family)",
}

# family -> design key holding its proportion parameter
PARAM_KEY = {
    ("d4", "disphenoid"): "d4_stretch",
    ("d6", "rhombohedron"): "d6_angle",
    ("d8", "bipyramid"): "d8_height",
    ("d10", "trapezohedron"): "d10_elongation",
    ("d100", "trapezohedron"): "d100_elongation",
    ("d12", "pyritohedron"): "d12_pentagon",
    ("d12", "bipyramid"): "d12_height",
    ("d20", "bipyramid"): "d20_height",
}
_PARAM_LABEL = {
    "d4_stretch": "Disphenoid stretch (1 = regular)",
    "d6_angle": "Rhombohedron face tilt (35.26° = cube)",
    "d8_height": "Bipyramid height (1 = octahedron)",
    "d10_elongation": "Trapezohedron elongation",
    "d100_elongation": "Trapezohedron elongation",
    "d12_pentagon": "Pyritohedron pentagon shape (1.618 = regular)",
    "d12_height": "Hexagonal bipyramid height",
    "d20_height": "Decagonal bipyramid height",
}


def _param_range(key):
    (die, fam), = [k for k, v in PARAM_KEY.items() if v == key]
    return FAMILIES[die][fam]


DESIGN_SCHEMA = [dict(key="size_scale", label="Set size scale", type="float", min=0.9, max=1.12, step=0.01,
                      group="Set", die=None)]
for _d in DIE_TYPES:
    DESIGN_SCHEMA.append(dict(key=f"{_d}_shape", label="Shape", type="choice", choices=list(FAMILIES[_d]),
                              group=_d.upper(), die=_d))
    for (_die, _fam), _key in PARAM_KEY.items():
        if _die == _d:
            lo, hi, _ = _param_range(_key)
            DESIGN_SCHEMA.append(dict(key=_key, label=_PARAM_LABEL[_key], type="float", min=lo, max=hi,
                                      step=0.5 if _key == "d6_angle" else 0.01, group=_d.upper(), die=_d,
                                      family=_fam))
SCHEMA_BY_KEY = {s["key"]: s for s in DESIGN_SCHEMA}
DIE_KEYS = {d: [s["key"] for s in DESIGN_SCHEMA if s["die"] == d] for d in DIE_TYPES}
VARIANT_KEYS = [k for d in DIE_TYPES for k in DIE_KEYS[d]]

# style -> per die: weighted families and the part of each parameter range to sample (0..1)
_STYLE_RULES = {
    "classic": {"pick_regular": 0.85, "span": {"*": (0.35, 0.65)}},
    "crystal": {"families": {"d4": {"disphenoid": 1}, "d6": {"rhombohedron": 1}, "d8": {"bipyramid": 1},
                             "d12": {"bipyramid": 2, "pyritohedron": 1}, "d20": {"bipyramid": 1}},
                "span": {"*": (0.65, 1.0), "d6_angle": (0.0, 0.3), "d12_pentagon": (0.6, 1.0)}},
    "geometric": {"families": {"d4": {"disphenoid": 1}, "d6": {"rhombohedron": 1}, "d8": {"bipyramid": 1},
                               "d12": {"pyritohedron": 2, "rhombic": 1}, "d20": {"icosahedron": 1}},
                  "span": {"*": (0.0, 0.35), "d6_angle": (0.7, 1.0)}},
    "mixed": {"span": {"*": (0.0, 1.0)}},
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


def _roll_die(rng, die, style, variation, d):
    rules = _STYLE_RULES[style]
    fams = list(FAMILIES[die])
    if "families" in rules and die in rules["families"]:
        weights = rules["families"][die]
    elif style == "classic":
        reg = [f for f in fams if f in REGULAR_FAMILIES] or fams[:1]
        p_reg = 1.0 - (1.0 - rules["pick_regular"]) * variation * 1.5
        weights = {f: (p_reg / len(reg) if f in reg else (1 - p_reg) / max(1, len(fams) - len(reg))) for f in fams}
    else:
        weights = {f: 1.0 for f in fams}
    weights = {f: w for f, w in weights.items() if w > 0} or {fams[0]: 1}
    d[f"{die}_shape"] = _wchoice(rng, weights)
    for key in DIE_KEYS[die]:
        s = SCHEMA_BY_KEY[key]
        if s["type"] != "float":
            continue
        lo, hi, default = _param_range(key)
        a, b = rules["span"].get(key, rules["span"]["*"])
        target = lo + (hi - lo) * rng.uniform(a, b)
        # variation blends from the family's natural proportion towards the random target
        d[key] = _q(min(hi, max(lo, default + variation * (target - default))), s["step"])


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


def validate_design(d):
    out = {}
    for s in DESIGN_SCHEMA:
        k = s["key"]
        if k not in d:
            if s["type"] == "float" and s["die"]:
                d = {**d, k: _param_range(k)[2]}
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
    """(family, parameter or None) for a die."""
    fam = design[f"{die}_shape"]
    key = PARAM_KEY.get((die, fam))
    return fam, (design[key] if key else None)

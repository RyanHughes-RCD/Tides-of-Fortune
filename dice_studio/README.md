# Tides Dice Studio

A local desktop application for procedurally generating, customising, previewing,
validating and exporting original **7-piece polyhedral dice sets** (D4, D6, D8, D10,
D12, D20, D100) for resin 3D printing. The randomisation varies the **shape of each
die**, choosing from two kinds of fair shape:

* **face-landing solids**, where all faces are congruent (tetrahedron, cube, bipyramids,
  pyritohedra, elongated kites, the D4 wedge, …);
* **rollers**, long shapes with pointed ends that roll like a pencil and can only come
  to rest on one of their numbered sides: crystals, shards, short shards, the **D6
  gemstone**, and the curved **infinity D4**. A physical *rest analysis* proves the
  numbered sides hold the die and that every end facet tips over.

The only cuts in a die are its **engraved numbers** (plus an optional D20 logo). There
are no decorative etchings. Each die is exported with a matching
**internal blank**, so a full set is 14 STL files.

Everything runs on your own computer. The geometry engine is Python; the editor is a
local web page served by the app and opened in your browser. There's no cloud service and
no CDN: three.js is bundled.

---

## 1. Install and launch on Windows

1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/windows/>.
   In the installer, tick **"Add python.exe to PATH"** and leave **tcl/tk** selected
   (it's used for the native *Browse…* dialogs).
2. Copy or download the `dice_studio` folder.
3. Double-click **`run_windows.bat`**.
   * The first run creates a private environment in `dice_studio\.venv` and installs the
     dependencies. This takes about a minute and needs internet once.
   * The studio then opens in your default browser at `http://127.0.0.1:8765/`.
   * Keep the black console window open while you work. Close it to quit.
4. To run the automated tests, double-click **`run_tests_windows.bat`**.

Command-line options (pass them to the `.bat` or to `python -m dicestudio`):

| option | meaning |
|---|---|
| `--port 8765` | port to use (the next free port is chosen automatically if this one is busy) |
| `--no-browser` | don't open the browser automatically |
| `--workspace DIR` | data folder. The default is `%USERPROFILE%\.tides_dice_studio`, holding imported assets, `projects\`, `exports\` and `dicestudio.log` |

macOS / Linux: `./run.sh` (same behaviour).

Manual install: `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements-dev.txt`,
then `.venv\Scripts\python -m dicestudio`.

### Dependencies

| package | purpose |
|---|---|
| `manifold3d` | robust Boolean kernel (always returns closed 2-manifold solids) |
| `shapely` | 2D outlines: numerals, logo, safe regions |
| `fonttools` | TTF/OTF outlines, including variable-font weights |
| `Pillow` | PNG loading and thresholding |
| `numpy` | geometry maths, mesh validation, STL I/O |
| `pytest` | tests (development only) |
| three.js 0.160 (bundled) | WebGL viewport in the browser |

All Python packages ship prebuilt Windows wheels; no compiler is needed.

---

## 2. Using the studio

**Layout.** The large 3D viewport sits in the middle. The die selector with live
thumbnails is on the left (rendered from the real export meshes). The control tabs are on
the right (Design, Numbers, D20 Logo, Blank, Export). The toolbar is at the top. The
message log at the bottom shows warnings, errors and *Retry with safe geometry* buttons.

**Viewport.** Left-drag orbits, right-drag pans, the wheel zooms, and a click selects a die.
*Show* switches between the whole set and the selected die. *Inspect face* buttons fly
the camera straight onto any numbered face, rotated so the numeral reads upright.

View modes:

| mode | shows |
|---|---|
| Rendered | the exact export mesh. *Depth shading* tints every vertex by its real depth below the die's outer faces, so engravings stay readable head-on. It's computed from the mesh, not a texture. |
| Wireframe / mesh | all triangles |
| Geometry validation | green when the mesh passes validation (orange otherwise); inward-facing triangles show red; feature edges are outlined; the report summary is shown |
| Blank inside (ghost) | transparent outer die with the blue blank inside |
| Cutaway with blank | outer die clipped in half to show the blank and the gap |
| Blank only | the blank alone |
| Compare with baseline | the baseline version (grey, left) next to the current one. *📌 Set baseline* stores the current state as the reference. |

**Design tab.**
* Style preset: *Classic* (mostly regular solids, subtle proportions), *Elongated*
  (stretched, skewed faces), *Geometric* (wide, flattened), *Crystal rollers* (pointed
  prisms; the D6 is often a gemstone), *Shard rollers* (long and short points; the D4 may
  be a wedge or an infinity) or *Mixed* (any shape).
* Shape variation and random seed. The same seed, style and variation always reproduce
  the same set.
* The selected die's shape, all of that shape's proportion sliders, its size (whose
  meaning follows the shape: resting width for rollers, tip-to-tip for the infinity), and
  a one-line summary of how it lands and how it's read. A table lists every die's shape,
  proportions and length.
* Every shape value has a 🔒 lock. *Randomize* (toolbar or tab) draws a new seed and
  re-rolls only the unlocked values.
* *Regenerate this die* rolls a new random shape for the selected die only.
* *Reset die* and *Reset set* undo the per-die or all customisations.
* Undo/redo: Ctrl+Z, Ctrl+Y (or the toolbar).

**Numbers tab.**
* Import a TTF or OTF font. The preview shows the **actual cut outlines** before you
  apply them. You can then apply the font to the whole set or to the selected die only.
  Two OFL sample fonts are bundled: a variable Roman (*Cinzel*) and a gothic blackletter
  (*UnifrakturMaguntia*).
* Weight works on variable fonts (`wght` axis) and the built-in font. *Thicken / thin*
  offsets the outline of any font.
* Engraving on/off (whole set, or per die), depth (default **0.75 mm**), minimum wall,
  edge margin.
* Numeral size, either as a % of the largest size that fits, or an exact height per die.
  You can also set offset, rotation, and vertex/edge alignment.
* Conventions: 6/9 underline or dot; D4 numbers at corners (read at the top), at edges
  (read at the bottom), or *automatic* (corners, but edges on the wedge); D10 0–9 or
  1–10; D100 00–90 or 10–100; the D10 upper-face digit order.

**D20 Logo tab.**
* Import a PNG. The preview shows the image over a checkerboard and the resulting cut mask.
* Settings: threshold, mask source (transparency, darkness, or auto), invert, smoothing.
* Placement: width (aspect ratio is always preserved), rotation, offset, cut depth
  (default **0.75 mm**), and whether the logo replaces the "20".
* Fine-detail warnings are computed at the real printed size. *Remove fine details*
  deletes features below the minimum printable width.
* *Cut logo into the D20* toggles the logo without losing the image or its settings.

**Blank tab.** Clearance (default **0.5 mm**), reference mode, minimum thickness, and a
per-face fit table for the selected die.

**Export tab.**
* Settings: file prefix, units (mm default; cm and inch available), output folder
  (*Browse…* opens a native folder dialog).
* Export the selected die, its blank, all 7 dice, all 7 blanks, or all 14 files. You can
  also download all 14 as a ZIP.
* Export **always validates first** and refuses to write invalid meshes unless you tick
  *Export even if validation fails*. A `<prefix>_validation_report.json` is written next
  to the STLs.

File names: `MySet_D20.stl`, `MySet_D20_Blank.stl`, `MySet_D12.stl`, `MySet_D12_Blank.stl`, …

**Projects.**
* *Save* and *Save as…* write a single `.tdice` file: a zip holding `project.json` (seed,
  style, every parameter, per-die overrides, numbering, engraving, blank and export
  settings) plus **copies of the imported font and logo**. Projects never depend on
  absolute paths, so they can be moved to another computer.
* *Open…* lists recent projects, offers a native file dialog, a typed path, or an upload.
* *Duplicate* copies the current design under a new name before you experiment.

---

## 3. How the geometry works

### Dice bodies and random shapes (`geometry/polyhedra.py`, `geometry/design.py`, `geometry/curved.py`)
Each die (except the curved infinity D4) is the intersection of half-spaces `n·x ≤ d`
(exact plane equations), giving an exact, convex, watertight solid.

**Face-landing shapes** are face-transitive: every face is congruent and equidistant from
the centre, so the die is fair at any proportion, and (except on the D4) every face has a
parallel opposite face that is read on top.

| die | face-landing shapes | random proportion (range) |
|---|---|---|
| D4 | tetrahedron, disphenoid, **wedge** (long disphenoid, read along the edges) | stretch 0.75–1.6; wedge 1.6–2.4 |
| D6 | cube, rhombohedron (6 congruent rhombi) | face tilt 18–52° (35.26° = cube) |
| D8 | octahedron, square bipyramid | height 0.75–2.2 (1 = octahedron) |
| D10 / D100 | pentagonal trapezohedron (10 kites, planar by construction: `z₀ = h(1−cos36°)/(1+cos36°)`) | elongation 0.8–2.0 |
| D12 | dodecahedron, pyritohedron, rhombic dodecahedron, hexagonal bipyramid | pentagon 1.15–2.3; height 0.9–2.2 |
| D20 | icosahedron, decagonal bipyramid | height 1.2–2.4 |

**Rollers** are long, with N congruent numbered sides around an axis and pointed ends.
They roll like a pencil, come to rest on a side, and the side facing up is read (resting
on side k, side k + N/2 is on top, and the pair always sums to N+1, or to 9 on the D10).
Their size is the resting width across the sides; proportions are in multiples of it.

| shape | dice | proportions | ends |
|---|---|---|---|
| crystal | all | body 0.9–2.4, point 0.55–1.1 | equal pointed caps |
| shard | all | long point 2.1–3.2, short point 0.6–1.0 | no body; the long point's facets are the numbered sides |
| short shard | all | body 0.9–1.8, long point 0.8–1.8, short point 0.45–0.9 | body with one long and one short point |
| gemstone | D6 | girdle 1.0–2.0, crown 0.7–1.0, pavilion 0.9–1.5 | two-tier faceted crown, pointed pavilion |
| infinity | D4 | roundness 0.8–1.25 | curved sphericon (see below) |

**Rest analysis.** A convex die resting on a face is stable exactly when its centre of
mass, projected straight down, lands inside that face. The engine computes this for every
face of every shape. Numbered faces must hold the die with a margin of at least 12% of
the face's inscribed radius, and every end facet of a roller must tip over. Shapes that
fail are rejected with an explanation ("the die could come to rest on 12 end facets;
make the ends longer/pointier"), and the randomiser re-rolls them.

This analysis is why the ranges look as they do. A pure shard's mass sits near its wide
ring, so it can balance on its short facets unless its long point is at least ~2× its
width. With a body section, a very long gentle point becomes a resting surface itself.
And stubby crystals or gems can stand on their crown. The UI shows the result for the
selected die ("lands only on its 6 numbered sides; all 18 end facets tip over").

**Infinity D4** (`geometry/curved.py`). This is a sphericon: the convex hull of two
perpendicular half-arcs, with four curved cone faces. Like a tetrahedron, each face
touches the other three. It rolls and comes to rest on one face, and it's read like a
base-style D4: along each edge of a face is the number of the face across that edge, so
the number along the bottom edges of the visible faces is the result. Because cones are
developable, each face is unrolled exactly into a flat fan. The numerals are laid out and
size-fitted there, then the cut prisms are refined and wrapped back onto the surface, so
every point of the engraving sits 0.75 mm below the *curved* surface along its local
normal (measured 0.750–0.751 mm in the tests).

**Clipped** (corner-truncated) and chamfered regular shapes are deliberately not
included. Size means the longest edge for the D4 tetrahedron/disphenoid/wedge, the
face-to-face distance for other face-landing dice, the resting width for rollers, and the
tip-to-tip length for the infinity.

### Numbering and orientation (`geometry/numbering.py`)
Every numbered face gets a right-handed frame (u, v, n) with **u × v = n**. Seen from
outside, u is "right" and v is "up", so a numeral can never be mirrored. Tests verify this
for every face.

| die | convention |
|---|---|
| D6 | opposite faces sum to 7; 1-2-3 counter-clockwise around a corner; numerals point to an edge |
| D8 / D12 / D20 | opposite faces sum to N+1; a deterministic optimiser balances the vertex sums; numerals point to a vertex (edge optional), or to the die's pole on bipyramids |
| D10 / D100 | odd digits on the upper kites (default order 1,7,3,9,5), opposite faces sum to 9; numerals point to the die's pole; D100 shows 00–90 |
| rollers | values run around the ring, resting side + top side = N+1 (9 on the D10); numerals run along the die's axis, upright when the die lies down, slid along the side to where they can be largest |
| D4 | *apex* style: each corner has a number, each face shows its three corner numbers each pointing at its corner, and the three faces around a corner show the same number (read at the top). *Base* style: each edge shows the value of the face across it (read at the bottom). |

6 and 9 get an underline or dot on dice that carry both. On regular faces numerals are
centred; on irregular congruent faces (kites, isosceles triangles, rhombi, pyritohedral
pentagons) they're centred on the face's largest inscribed circle.

### Engraving (`geometry/builder.py`, `geometry/mesh3d.py`, `geometry/text.py`)
Glyph outlines are flattened from TTF quadratic or CFF cubic curves and filled with the
non-zero rule, which handles both contour conventions and overlapping variable-font
contours. They're laid out in the face frame and extruded into prisms spanning local z
from **−depth** to above the surface, then subtracted with Manifold. The depth is
therefore measured **along each face's own normal**.

Before cutting, each outline must fit inside a *safe region*: the face inset by the edge
margin, intersected with the die's cross-section at the cut depth with every other face
plane moved inward by the minimum wall (a true 3D distance). This guarantees no
breakthrough and keeps at least `min_wall` of material to neighbouring faces. If the
requested numeral size doesn't fit, it's reduced with a warning. Cuts also keep at
least `min_wall` of material to the **engravings of neighbouring faces**. A point is
accepted if it lies below the neighbour's engraving slab, or (across a shared edge)
laterally outside the neighbour's engravable area. Without this, two numerals on
either side of a sharp edge can meet underneath it and leave a tunnel; the topology
check caught exactly that on long wedges during development.

### Logo (`geometry/logo.py`)
The PNG is converted to a binary mask with your threshold (from alpha for transparent
PNGs, darkness otherwise). It's then vectorised exactly by merging pixel runs into
polygons, which keeps holes and separate islands. Next it's simplified, normalised to the
image's aspect ratio, placed on the face with the value 20, and checked against the safe
region (shrunk with a warning if needed). Fine details are measured at the printed size.

Unconvertible images are rejected with an explanation instead of being exported:
* nothing selected by the threshold,
* the whole image selected,
* more than 400 pieces (noise or dithering),
* not a PNG.

### Internal blanks (`geometry/builder.py::_build_blank`)
The blank is built from **the same face planes as the outer die, each moved inward
along its own normal**. This is a true face
offset, not a scale.

> **Clearance interpretation.** The 0.5 mm is applied *in addition to* the deepest cut,
> so the blank clears the floors of the 0.75 mm engravings by 0.5 mm. An offset of only
> 0.5 mm from the outer face planes would put the blank *inside* the engraved recesses,
> and then it wouldn't fit within the outer solid. The reference mode lets you choose:
>
> * **deepest cut, all faces** (default): every face moves in by `clearance + deepest
>   cut` (0.5 + 0.75 = 1.25 mm). The blank keeps the regular shape and clears every
>   recess by exactly 0.5 mm.
> * **each face's own deepest cut**: a per-face offset (e.g. a deeper logo face moves in
>   further).
> * **outer face plane**: exactly 0.5 mm from each nominal face. This ignores the
>   engravings, so the fit check reports the overlap.

Fit verification runs for every die on every change:

* each blank vertex lies on or inside every offset plane, and each blank face lies
  exactly on its plane;
* `blank − outer` has zero volume (true containment in the engraved solid);
* **measured** minimum gap from the blank to the engraved outer surface, using Manifold's
  `min_gap` against the outer solid's complement. It's 0.500 mm for the defaults;
* volume > 0, minimum thickness ≥ the configured minimum, and no main face lost.

If the clearance is impossible (for example 5 mm on a small D4), the error explains why
and what to change. The blank is a solid convex polyhedron with no numerals, logo or
engraving, and it's exported as its own STL. The app doesn't assume it's a functional
insert: the *Blank inside* and *Cutaway* views show exactly how it relates to the outer die.

### Validation (`geometry/validate.py`)
Validation runs on **exactly the float32 coordinates written to the STL**. It checks:

* watertightness: every edge is shared by exactly two triangles (no open or non-manifold
  edges);
* consistent winding: every directed edge is used once;
* outward normals: positive signed volume;
* zero-area triangles and duplicate triangles;
* connected pieces (must be 1);
* genus (must be 0);
* **self-intersections**: a grid broad phase, then an exact segment–triangle test on
  every nearby pair of triangles that don't share an edge (≈130k pairs for a D20).

Export re-runs validation. Tests additionally re-read the written STL files and validate
them again.

### Failure handling
A Boolean or geometry failure is reported per die, with a **Retry with safe geometry**
button. Safe mode simplifies outlines and lowers curve resolution. 2D Boolean
operations retry with snap-rounding (1–100 nm grid) if GEOS reports a topology error.
Input values are range-checked with readable messages. Missing glyphs fall back to the
built-in numerals with a warning. Invalid fonts and images are rejected with the reason.

---

## 4. Project structure

```
dice_studio/
  run_windows.bat, run_tests_windows.bat, run.sh   launchers
  requirements.txt, requirements-dev.txt
  dicestudio/
    geometry/polyhedra.py    die bodies, congruent-face shape families, half-space intersection, face offset
    geometry/numbering.py    face frames, numbering conventions, orientation
    geometry/text.py         built-in font, TTF/OTF loading, text -> polygons
    geometry/logo.py         PNG -> mask -> polygons, fine-detail analysis
    geometry/design.py       shape styles, seeded randomisation, locks, per-die variants
    geometry/mesh3d.py       Manifold conversion, prisms, Boolean engraving
    geometry/builder.py      orchestration: layout, cutting, blank + fit checks
    geometry/validate.py     mesh validation
    geometry/stl.py          binary STL writer/reader, units
    project.py               project model, validation, save/open (.tdice), duplicate
    assets.py                content-addressed store for imported fonts/logos
    engine.py                build cache, thread pool, validation report, export
    server.py                local HTTP API (127.0.0.1 only) + static UI
    web/                     index.html, app.js, style.css, vendored three.js
    fonts/                   bundled OFL fonts (+ licences)
  tests/                     pytest suite
```

The geometry engine (`dicestudio/geometry`) has no UI dependencies and can be scripted
directly:

```python
from dicestudio.project import default_project, resolve_die_spec
from dicestudio.geometry.builder import build_die
from dicestudio.geometry.stl import write_stl
p = default_project(seed=42, style="crystal")
r = build_die(resolve_die_spec(p, "d20"))
write_stl("D20.stl", r.outer_vertices, r.outer_tris)
```

---

## 5. Tests

`run_tests_windows.bat`, or `python -m pytest -v tests`. The suite covers:

* **Shapes and face counts**: every face-landing family at the ends and middle of each
  range (congruent, equidistant faces, opposite faces, all faces stable). Every roller
  family: congruent numbered sides, centre of mass on the axis, every numbered side
  stable, every end facet tips over, rest/top pairing. Also: closed solids (Euler
  characteristic 2), planar convex faces, sizes, true face offsets, and a blunt crystal
  being rejected.
* **Numbering**:
  * opposite sums (7, 9, 13, 21, 9); every value appears exactly once;
  * D10/D100 labels; 6/9 markers;
  * right-handed (non-mirrored) frames; up vectors pointing to a vertex, edge or pole;
  * D4 apex and base conventions; D6 corner chirality.
* **Engraving depth**: a ray cast into every numeral on every face of every die measures
  0.75 mm ± 0.2 µm along the face normal. Also covered: custom depth, engraving off,
  minimum wall to all neighbouring planes, and the safe-region proof.
* **Fonts**: synthetic TTF and CFF/OTF fonts (holes preserved), variable weight,
  blackletter font, invalid files, missing-glyph fallback, global font with per-die
  override, missing asset.
* **Logo**:
  * vectorisation with holes and islands, aspect ratio, alpha and luminance thresholds;
  * invalid, JPEG and fully opaque images rejected; fine-detail warnings;
  * cut depth inside the logo, untouched surface inside the logo's hole;
  * placement only on the 20 face; toggle keeps settings; oversize logo shrinks;
    logo combined with the numeral.
* **Blank clearance**:
  * every blank vertex checked against every outer plane;
  * exact face offsets; measured gap of 0.5 mm; containment in the outer die;
  * regeneration when the parent changes; face-plane mode conflict reported;
    impossible clearance explained.
* **Validation and export**:
  * the validator detects holes, flipped and mixed winding, overlapping shells,
    duplicates and degenerate triangles;
  * STL round trip and unit scaling;
  * all 14 files exported with the right names and re-validated from disk;
  * single-file and ZIP export; invalid meshes refused.
* **Projects**:
  * seed reproducibility (bit-identical meshes);
  * locks respected; regenerating one die changes only that die; reset;
  * validation messages;
  * save and reopen into a *fresh* asset store with font and logo restored and identical
    spec hashes; duplicate;
  * HTTP API end to end.
* **Rollers and curved shapes**:
  * every roller on every die builds a valid mesh, with each numeral measured 0.75 mm
    deep along its side's normal;
  * blanks fit; resting side + top side pairs; numerals run along the axis;
  * the wedge uses edge numbering;
  * the infinity D4 has a valid mesh and blank, consistent base-style labels, and its
    curved engraving measured along the true surface normal;
  * the randomiser never produces a shape that can land on an end (four styles × 12 seeds);
  * regenerating a die changes only that die; old project keys migrate.
* **UI smoke test** (`test_ui_smoke.py`, runs when Playwright and Chromium are installed):
  loads the editor, regenerates a die, undoes, cycles every view mode, and validates.

---

## 6. Known limitations

* The self-intersection test detects edges that pierce triangles by more than 20 nm. It
  skips perfectly coplanar overlaps (caught instead as duplicate triangles) and crossings
  that pass exactly through a triangle edge. Meshes come from Manifold, which guarantees
  2-manifold Boolean output, so this check is an independent safety net.
* The "balanced" D8/D12/D20 layouts are produced by a deterministic optimiser (opposite
  faces always sum to N+1). They aren't copies of any specific manufacturer's layout.
  The D10 upper-face order is configurable.
* Font *weight* uses the `wght` axis of variable fonts. Static fonts use the outline
  thicken/thin offset instead. Only digit glyphs are needed. Colour/bitmap-only fonts
  are rejected.
* Native file dialogs use Tk in a helper process. If Tk is unavailable, type the path
  into the field instead.
* The blank is a convex, unengraved solid. Whether it works mechanically as an insert
  (for example, how to embed it during printing or casting) is up to your process.
* The rest analysis is *static*: it proves where the die can and can't come to rest, not
  how often a real throw ends on each side (bounce dynamics, surface, edge rounding from
  printing). Every numbered side of a roller is congruent, so by symmetry each is equally
  likely.
* Rollers with many sides (D12 and especially D20 crystals and shards) have narrow sides,
  so their numerals come out small (about 1.1–2.5 mm). The app warns when numerals are
  under 2.5 mm; make the die wider, or use the two-row elongated bipyramid for the D20,
  which the crystal and shard styles prefer.
* The infinity D4's curved faces are a fine faceted hull (160 segments per arc, chord
  error < 1 µm). Its engraving floor follows the curve to within 5 µm, so its blank keeps
  an extra 10 µm allowance. It builds in about 5 s; the other dice take well under 1 s,
  and every die is built and shown independently.

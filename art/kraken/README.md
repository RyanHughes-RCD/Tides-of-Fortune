# Kraken art

**In the game:** `user/` holds the hand-drawn sprites the event uses: `head.png` (six eyes) and the
tentacles `a1.png` to `a4.png` (A3 grabs and breaks the lighthouse). They are embedded in `index.html`
(search for `const SRC =` in the kraken art section), so to change one, replace the PNG there with the new
file's base64 data URI. The game shows them at 2x, crisp, and derives everything else from their pixels:
the sway frames, the A3 grab, the split jaw, the eye overlays and the carcass. If you redraw the head,
the six eye positions are listed in `EYE6` beside it.

**Archive:** the other files here are earlier pieces drawn in code; the game no longer uses them.


Native-resolution pixel art, transparent backgrounds. Each piece carries its own foam, ripples and
under-water shadow, so it can be placed straight on the harbor water.

| File | Piece |
|---|---|
| head.png | Head: crown of pores, 8 slit-pupil eyes, centre seam (where it will split) |
| arm_rear.png / arm_rear_b.png | Thick rearing arm, and its mirror |
| arm_tall.png | Tall sinuous arm |
| arm_arch.png | Arm arching out of the water and back in |
| arm_tip.png | Small tip breaking the surface |

`anchors.json` gives, for each file, the pixel that sits on the water surface (the centre of the
waterline), so pieces can be lined up in the game. `src/` holds the script that draws them:
`python3 src/pxkraken.py src/pieces.json out/` (needs numpy and Pillow).

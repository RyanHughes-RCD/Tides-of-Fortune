# Kraken pieces (work in progress, not used by the game yet)

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

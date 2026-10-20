# Fade the head sprite's bottom corners: fully transparent at each corner, ramping smoothly to full
# opacity by the edge of the head itself (an ellipse around each corner, wider than it is tall-limited).
from PIL import Image
import numpy as np, sys
src = Image.open('head.png').convert('RGBA'); a = np.array(src).astype(float)
H, W = a.shape[:2]; RX, RY = float(sys.argv[1]) if len(sys.argv) > 1 else 34, float(sys.argv[2]) if len(sys.argv) > 2 else 64
yy, xx = np.mgrid[0:H, 0:W] + 0.5
k = np.ones((H, W))
for cx in (0, W):
    e = np.sqrt(((xx - cx) / RX) ** 2 + ((yy - H) / RY) ** 2)
    t = np.clip((e - 0.25) / 0.75, 0, 1); k = np.minimum(k, t * t * (3 - 2 * t))
# a weaker fade along the whole bottom edge: 45% opaque on the last row, solid 20 px up
BH, B0 = float(sys.argv[3]) if len(sys.argv) > 3 else 20, float(sys.argv[4]) if len(sys.argv) > 4 else 0.45
t = np.clip((H - yy) / BH, 0, 1); k = np.minimum(k, B0 + (1 - B0) * t * t * (3 - 2 * t))
a[..., 3] = a[..., 3] * k
# the yellow patch on the left side (a stray highlight on the arm root) is removed: its bright pixels go clear
r, g, b = a[..., 0], a[..., 1], a[..., 2]
patch = (xx < 22) & (yy > 78) & (yy < 90) & (r > 180) & (g > 110) & (b < 110)
# and its warm orange rim (anything orange within 2 px of it)
near = patch.copy()
for _ in range(2): near = near | np.roll(near, 1, 0) | np.roll(near, -1, 0) | np.roll(near, 1, 1) | np.roll(near, -1, 1)
rim = near & ~patch & (g > 30) & (g > r * 0.2) & (b < 90)
patch = patch | rim
a[..., 3][patch] = 0
print('patch pixels cleared', int(patch.sum()))
out = Image.fromarray(a.round().astype(np.uint8), 'RGBA'); out.save('head_faded.png')
print('done', RX, RY)

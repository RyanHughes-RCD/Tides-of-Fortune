# Kraken pieces as native-resolution pixel art with transparent backgrounds, each carrying its own foam,
# ripples and under-water shadow so it can be dropped straight onto the harbor water.
import numpy as np, math, sys, json, os
from PIL import Image
def H(h): return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], np.uint8)
INK = H('#160810')
SKIN = [H(c) for c in ('#2a0614', '#4a0916', '#6c0f1e', '#8f1626', '#ad2130', '#c6363a', '#d8604e')]
PALE = [H(c) for c in ('#45091a', '#661222', '#8a1c2c', '#a83038', '#bf4a44', '#cf6a56', '#da8a70')]
RIM = H('#6a2248')
GOLD = [H(c) for c in ('#6a3008', '#9c5a0c', '#cc8414', '#eaa820', '#fac83a', '#ffe47a')]
TUBE = [H(c) for c in ('#3a1606', '#5e280a', '#82400e')]
HOLE = H('#1c0806')
IRIS = [H(c) for c in ('#9a4a08', '#c87010', '#e8981a', '#f8bc2a', '#ffdc5a', '#fff2b0')]
PUPIL = H('#140404')
FOAM, FOAM2 = H('#e9f7fc'), H('#bfe6f6')
def hsh(x, y, s):
    h = (x * 374761393) ^ (y * 668265263) ^ ((s + 1) * 982451653)
    h &= 0xffffffff; h = ((h ^ (h >> 13)) * 1274126177) & 0xffffffff
    return ((h ^ (h >> 16)) & 0xffffffff) / 4294967296
LIGHT = np.array([-0.55, -0.62, 0.56]); LIGHT /= np.linalg.norm(LIGHT)
def bandof(l): return 0 if l < -0.15 else 1 if l < 0.12 else 2 if l < 0.36 else 3 if l < 0.58 else 4 if l < 0.76 else 5 if l < 0.9 else 6

class Canvas:
    """RGBA pixel buffer plus the bookkeeping the water effects need."""
    def __init__(s, W, Hh):
        s.W, s.H = W, Hh; s.rgb = np.zeros((Hh, W, 3), np.uint8); s.a = np.zeros((Hh, W), np.uint8)
        s.body = np.zeros((Hh, W), bool); s.idx = -np.ones((Hh, W), int)
    def put(s, x, y, c, a=255):
        if 0 <= x < s.W and 0 <= y < s.H: s.rgb[y, x] = c; s.a[y, x] = a
    def tint(s, x, y, c, k): # blend a translucent wash over whatever is there (or over clear water)
        if not (0 <= x < s.W and 0 <= y < s.H): return
        if s.a[y, x] == 0: s.rgb[y, x] = c; s.a[y, x] = int(255 * k)
        elif s.a[y, x] < 255: s.a[y, x] = max(s.a[y, x], int(255 * k))
    def outline(s, extra=None):
        out = np.zeros_like(s.body)
        for d, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)): out |= np.roll(s.body, d, ax) & ~s.body
        if extra is not None: out |= extra
        s.rgb[out] = INK; s.a[out] = 255; return out

# ---------- water bits (all translucent or white, so they also work on red water later) ----------
def under_shadow(C, cx, cy, r, lean=0.25):
    for py in range(int(cy), min(C.H, int(cy + r * 2))):
        for px in range(max(0, int(cx - r * 1.6)), min(C.W, int(cx + r * 1.9))):
            if C.body[py, px]: continue
            e = math.hypot((px + 0.5 - cx - r * lean) / (r * 1.05), (py + 0.5 - cy - r * 0.62) / (r * 0.52))
            if e < 0.8 or (e < 1 and (px + py) % 2 == 0): C.tint(px, py, np.array([4, 18, 40], np.uint8), 0.25)
def foam_ring(C, cx, cy, r, seed, wl_rx, wl_ry):
    for py in range(int(cy - r), int(cy + r)):
        for px in range(int(cx - r * 1.8), int(cx + r * 1.8)):
            if not (0 <= px < C.W and 0 <= py < C.H): continue
            e = math.hypot((px + 0.5 - cx) / (r * 1.45), (py + 0.5 - cy) / (r * 0.72))
            e += 0.18 * (hsh(px >> 1, py, seed) - 0.5) + 0.12 * math.sin(math.atan2(py - cy, px - cx) * 6 + seed)
            lip = abs(px + 0.5 - cx) < wl_rx and py + 0.5 > cy + wl_ry * math.sqrt(max(0, 1 - ((px + 0.5 - cx) / wl_rx) ** 2)) - 1.5
            if e < 1 and (not C.body[py, px] or (lip and C.rgb[py, px].tolist() != INK.tolist())):
                C.put(px, py, FOAM if e < 0.78 or hsh(px, py, 2) < 0.4 else FOAM2)
    fm = (C.a == 255) & ~C.body & (np.all(C.rgb == FOAM, -1) | np.all(C.rgb == FOAM2, -1))
    below = (np.roll(fm, -1, 0) | np.roll(fm, -2, 0)) & ~fm & ~C.body & (C.a == 0)
    C.rgb[below] = np.array([180, 230, 250], np.uint8); C.a[below] = 120
def ripples(C, cx, cy, r, seed, rings=((1.9, 0.25), (2.7, 0.4), (3.6, 0.55))):
    for k, (m, broken) in enumerate(rings):
        rx, ry = r * m, r * m * 0.5
        for a in np.linspace(0, 2 * math.pi, int(rx * 8)):
            j = 1 + 0.04 * (math.sin(a * 5 + seed + k) * 0.6 + math.sin(a * 9 + seed * 2) * 0.4)
            px, py = int(cx + math.cos(a) * rx * j), int(cy + math.sin(a) * ry * j)
            if hsh(int(a * 20), k + 3, 4) < broken: continue
            for t in range(2):
                if 0 <= px + t < C.W and 0 <= py < C.H and not C.body[py, px + t] and C.a[py, px + t] < 200:
                    C.rgb[py, px + t] = np.array([200, 238, 252], np.uint8); C.a[py, px + t] = 150 - k * 25
def drops(C, cx, cy, r, seed, n):
    rng = np.random.default_rng(seed)
    for k in range(n):
        a = rng.uniform(math.pi * 0.9, math.pi * 2.1); d = r * rng.uniform(1.1, 1.9); h = rng.uniform(4, r * 1.2)
        px, py = int(cx + math.cos(a) * d), int(cy + math.sin(a) * d * 0.5 - h)
        if 0 <= px < C.W - 1 and 0 <= py < C.H - 1 and not C.body[py, px]:
            C.put(px, py, FOAM)
            if k % 3 == 0: C.put(px + 1, py, FOAM); C.put(px, py + 1, FOAM2)

# ---------- skin details shared by arms and head ----------
PIT_BIG = ["..ddd..", ".dhhhd.", "dhHHHhd", "dhHHHhl", ".lhhhl.", "..lll.."]
PIT_SMALL = [".dd.", "dHHd", "lhhl", ".ll."]
def pit(C, x, y, big, band_at):
    """A pore, drawn from a hand-made template: a dark hole, a shadowed rim above and a lit lip below."""
    T = PIT_BIG if big else PIT_SMALL; ox, oy = int(x) - len(T[0]) // 2, int(y) - len(T) // 2
    for j, row in enumerate(T):
        for i, ch in enumerate(row):
            px, py = ox + i, oy + j
            if ch == '.' or not (0 <= px < C.W and 0 <= py < C.H and C.body[py, px]): continue
            b = band_at(px, py)
            if b is None: continue
            C.put(px, py, HOLE if ch == 'H' else SKIN[0] if ch == 'h' else SKIN[max(0, b - 1)] if ch == 'd' else SKIN[min(6, b + 2)])
def sucker(C, cx, cy, d, t, inner, prof, i, front_gap):
    """A suction cup like the reference: a raised tube with a bright gold rim, a darker inner wall and a dark hole."""
    tx, ty = math.cos(t), math.sin(t); nx, ny = -math.sin(t) * inner, math.cos(t) * inner
    rw, rh = d / 2, d / 2 * (0.66 if not prof else 0.52)
    lift = max(1, round(d * 0.22)) # how far the tube stands off the skin
    pts = []
    for py in range(int(cy - d) - 2, int(cy + d) + 3):
        for px in range(int(cx - d) - 2, int(cx + d) + 3):
            if not (0 <= px < C.W and 0 <= py < C.H): continue
            if C.body[py, px] and C.idx[py, px] > i + front_gap: continue
            dx, dy = px + 0.5 - cx, py + 0.5 - cy
            u = (dx * tx + dy * ty) / rw; v = (dx * nx + dy * ny) / rh
            # the tube's side: the rim ellipse swept back toward the skin by `lift`
            v2 = ((dx - nx * lift) * nx + (dy - ny * lift) * ny) / rh; u2 = ((dx - nx * lift) * tx + (dy - ny * lift) * ty) / rw
            top = u * u + v * v <= 1; side = u2 * u2 + v2 * v2 <= 1
            if prof and v < -0.15 and not side: continue
            if not (top or side): continue
            lit = -(dx * 0.6 + dy * 0.75) / max(rw, 1)
            if top:
                q = u * u + v * v; iu, iv = u + 0.12, v + 0.18; qi = iu * iu + iv * iv # the hole sits a little away from the light
                if d >= 5 and qi < 0.2: c = HOLE
                elif d >= 5 and qi < 0.42: c = TUBE[0] if lit < 0 else TUBE[1]
                elif d >= 4 and q < 0.5: c = TUBE[2] if d >= 5 else HOLE
                elif d < 4 and q < 0.25: c = TUBE[0]
                else: c = GOLD[5] if lit > 0.6 else GOLD[4] if lit > 0.15 else GOLD[3] if lit > -0.35 else GOLD[2]
            else: c = GOLD[1] if lit > -0.1 else GOLD[0]
            pts.append((px, py, c, top))
    for px, py, c, top in sorted(pts, key=lambda p: p[3]): # sides first, rim on top
        C.put(px, py, c); C.body[py, px] = True; C.idx[py, px] = max(C.idx[py, px], i)

# ---------- an arm ----------
def arm(V):
    W, Hh = V['w'], V['h']; C = Canvas(W, Hh)
    L, R0, st = V['len'], V['r0'], 0.5; n = int(L / st)
    x, y = V['base']; th = math.radians(V['head']); sp = []
    for i in range(n + 1):
        s = i / n; r = R0 * (1 - s) ** V.get('taper', 0.8) + 1.4
        sp.append((x, y, th, r))
        k = V['bend'] + V['sway'] * math.sin(s * V['freq'] + V['ph']) + V['curl'] * max(0, (s - V['cs']) / (1 - V['cs'])) ** V.get('cp', 1.6)
        th += k * st; x += math.cos(th) * st; y += math.sin(th) * st
    inner = 1 if V['curl'] > 0 else -1
    if V.get('flip'): inner = -inner
    wl = V['base'][1]
    # where the arm leaves the water, and (for an arch) where it goes back in
    cross = [(0, sp[0][0], sp[0][1], sp[0][3])]
    end = n
    if V.get('arch'):
        for i in range(n // 3, n):
            if sp[i][1] >= wl: end = i; cross.append((i, sp[i][0], wl, sp[i][3])); break
    acr = np.zeros((Hh, W))
    for i, (cx, cy, t, r) in enumerate(sp[:end + 1]):
        nx, ny = -math.sin(t), math.cos(t)
        for py in range(max(0, int(cy - r - 1)), min(Hh, int(cy + r + 2))):
            for px in range(max(0, int(cx - r - 1)), min(W, int(cx + r + 2))):
                dx, dy = px + 0.5 - cx, py + 0.5 - cy
                if dx * dx + dy * dy <= r * r: C.idx[py, px] = i; acr[py, px] = (dx * nx + dy * ny) / r; C.body[py, px] = True
    yy, xx = np.mgrid[0:Hh, 0:W]
    for (ci, cx, cy, cr) in cross: # the surface cuts the arm along the front of an ellipse
        rx, ry = cr * 1.02, cr * 0.5; ex = (xx + 0.5 - cx) / rx
        near = np.abs(C.idx - ci) < 2.2 * cr / st
        cut = C.body & near & ((np.abs(ex) < 1) & (yy + 0.5 > cy + ry * np.sqrt(np.clip(1 - ex ** 2, 0, 1))) | (yy + 0.5 > cy + ry))
        C.body &= ~cut
    band = np.zeros((Hh, W), int); pale = np.zeros((Hh, W), bool)
    for py, px in zip(*np.nonzero(C.body)):
        i = C.idx[py, px]; t = sp[i][2]; a = max(-1, min(1, acr[py, px])); nz = math.sqrt(max(0, 1 - a * a))
        l = -math.sin(t) * a * LIGHT[0] + math.cos(t) * a * LIGHT[1] + nz * LIGHT[2]
        b = bandof(l)
        if a * inner < -0.86 and l < 0.3: b = -1
        band[py, px] = b; pale[py, px] = a * inner > 0.38
    for _ in range(2):
        nb = [np.roll(band, s_, a_) for s_, a_ in ((1, 0), (-1, 0), (1, 1), (-1, 1))]
        same = (nb[0] == nb[1]) & (nb[1] == nb[2]) & (nb[2] == nb[3]) & (nb[0] != band)
        band = np.where(C.body & same, nb[0], band)
    for py, px in zip(*np.nonzero(C.body)):
        b = band[py, px]; C.put(px, py, RIM if b < 0 else (PALE if pale[py, px] else SKIN)[b])
    # creases across the outer side
    for i in range(int(10 / st), end - int(60 / st), int(V.get('wrink', 13) / st)):
        cx, cy, t, r = sp[i]
        if r < 5: continue
        nx, ny = -math.sin(t), math.cos(t); tx, ty = math.cos(t), math.sin(t); bow = 1.2 + r * 0.06
        for k in np.linspace(-0.8, -0.2 - 0.25 * hsh(i, 1, V['seed']), int(r * 1.2)):
            a = k * inner; px = int(cx + nx * a * r + tx * bow * (1 - a * a)); py = int(cy + ny * a * r + ty * bow * (1 - a * a))
            if 0 <= px < W and 0 <= py < Hh and C.body[py, px] and C.idx[py, px] >= i - 3 and band[py, px] >= 2:
                C.put(px, py, SKIN[band[py, px] - 1])
    # pores over the outer side, thicker toward the base, as in the reference's porous skin
    for py in range(0, Hh, 7):
        for px in range(0, W, 7):
            jx, jy = px + int(hsh(px, py, 5) * 6), py + int(hsh(px, py, 6) * 6)
            if not (0 <= jx < W and 0 <= jy < Hh) or not C.body[jy, jx] or pale[jy, jx] or band[jy, jx] < 1: continue
            i = C.idx[jy, jx]; s = i / n
            if hsh(px, py, V['seed']) > 0.5 * (1 - s) + 0.05 or sp[i][3] < 9: continue
            pit(C, jx + 0.5, jy + 0.5, hsh(px, py, 8) < 0.3 and sp[i][3] > 16, lambda x_, y_: band[y_, x_] if band[y_, x_] >= 0 and not pale[y_, x_] else None)
    # suckers: a face-on row on the pale band and a profile row along the inner edge
    acc, row, br = 0.0, 0, sp[0][3]
    for i in range(int(br / st), end - 4):
        cx, cy, t, r = sp[i]; acc += st
        if any(abs(i - ci) < cr * 0.9 / st for (ci, _, _, cr) in cross): continue
        if r < 2.0 or acc < max(2.2, r * V.get('gap', 0.52)): continue
        acc = 0; row ^= 1
        nx, ny = -math.sin(t) * inner, math.cos(t) * inner
        d = max(2, round(r * (0.84 if row else 0.74)))
        if row: sucker(C, cx + nx * r * 0.5, cy + ny * r * 0.5, d, t, inner, False, i, int(br / st))
        else: sucker(C, cx + nx * r * 0.96, cy + ny * r * 0.96, d, t, inner, True, i, int(br / st))
    over = np.zeros_like(C.body)
    for s_, a_ in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
        over |= C.body & np.roll(C.body, s_, a_) & (np.roll(C.idx, s_, a_) > C.idx + 28 / st)
    C.outline(over)
    for k, (ci, cx, cy, cr) in enumerate(cross):
        under_shadow(C, cx, cy, cr, 0.25 if k == 0 else -0.25)
        ripples(C, cx, cy, cr, V['seed'] + k)
        foam_ring(C, cx, cy, cr, V['seed'] + k, cr * 1.02, cr * 0.5)
        drops(C, cx, cy, cr, V['seed'] + k, V.get('drops', 10))
    return C

# ---------- the head ----------
def head(V):
    W, Hh = V['w'], V['h']; C = Canvas(W, Hh)
    cx, wl = V['cx'], V['wl']; RX, top = V['rx'], V['top']
    # silhouette: a tall dome narrowing to a snout that runs down into the water, cheek lobes either side
    def half_w(y):
        u = (y - top) / (wl - top) # 0 at the crown, 1 at the water
        if u < 0: return 0
        if u < 0.5: return RX * math.sqrt(max(0, 1 - ((0.5 - u) / 0.5) ** 2))       # the bulbous crown
        return RX * (1 - 0.62 * ((u - 0.5) / 0.5) ** 0.85)                          # the face narrowing to a snout
    nxm = np.zeros((Hh, W)); nym = np.zeros((Hh, W))
    for py in range(Hh):
        hw = half_w(py + 0.5)
        if hw <= 0: continue
        u = (py + 0.5 - top) / (wl - top)
        for px in range(W):
            dx = px + 0.5 - cx
            if abs(dx) > hw or py + 0.5 > wl + RX * 0.32 * math.sqrt(max(0, 1 - (dx / hw) ** 2)) * 0: continue
            C.body[py, px] = True; nxm[py, px] = dx / hw; nym[py, px] = (-1 + u / 0.5) if u < 0.5 else 0.15 + (u - 0.5) * 0.5
    # waterline: cut along the front of an ellipse at the base of the snout
    hw0 = half_w(wl - 0.5); yy, xx = np.mgrid[0:Hh, 0:W]; ex = (xx + 0.5 - cx) / (hw0 * 1.02)
    C.body &= ~((np.abs(ex) < 1) & (yy + 0.5 > wl + hw0 * 0.5 * np.sqrt(np.clip(1 - ex ** 2, 0, 1)))) & ~(yy + 0.5 > wl + hw0 * 0.5)
    band = np.zeros((Hh, W), int)
    for py, px in zip(*np.nonzero(C.body)):
        a = max(-1, min(1, nxm[py, px])); b_ = max(-1, min(1, nym[py, px]))
        nz = math.sqrt(max(0.02, 1 - a * a - b_ * b_ * 0.6)); n = np.array([a, b_ * 0.8, nz]); n /= np.linalg.norm(n)
        lump = 0.08 * math.sin(px * 0.31 + math.sin(py * 0.2) * 2) * math.sin(py * 0.27)
        b = bandof(float(n @ LIGHT) + lump)
        if a > 0.9 and b < 3: b = -1 # rim light off the water on the shadow side
        band[py, px] = b
    for _ in range(2):
        nb = [np.roll(band, s_, a_) for s_, a_ in ((1, 0), (-1, 0), (1, 1), (-1, 1))]
        same = (nb[0] == nb[1]) & (nb[1] == nb[2]) & (nb[2] == nb[3]) & (nb[0] != band)
        band = np.where(C.body & same, nb[0], band)
    for py, px in zip(*np.nonzero(C.body)): b = band[py, px]; C.put(px, py, RIM if b < 0 else SKIN[b])
    # the centre ridge: a lit crest beside a dark groove (the seam the head splits along)
    for py in range(top + 3, wl):
        if C.body[py, cx - 1] and C.body[py, cx + 1]:
            C.put(cx - 1, py, SKIN[min(6, band[py, cx - 1] + 1)]); C.put(cx, py, SKIN[max(0, band[py, cx] - 2)])
    # folds running down the snout
    for k, off in enumerate((-0.55, -0.25, 0.3, 0.6)):
        for py in range(int(top + (wl - top) * 0.55), wl):
            px = int(cx + off * half_w(py + 0.5) + 1.5 * math.sin(py * 0.25 + k))
            if 0 <= px < W and C.body[py, px] and hsh(k, py >> 2, 3) < 0.75: C.put(px, py, SKIN[max(0, band[py, px] - 1)])
    eyes = [(-0.33, 0.47, 1.0), (0.33, 0.47, 1.0), (-0.36, 0.62, 0.92), (0.36, 0.62, 0.92), (-0.38, 0.77, 0.8), (0.38, 0.77, 0.8), (-0.78, 0.38, 0.6), (0.78, 0.38, 0.6)]
    ER = V['eye']
    def eye_at(k):
        ox, oy, sc = eyes[k]; y = top + oy * (wl - top); return cx + ox * half_w(y), y, ER * sc
    inEye = lambda x, y, pad: any(math.hypot(x - ex_, (y - ey_) * 0.85) < er + pad for ex_, ey_, er in map(eye_at, range(8)))
    # the crown's honeycomb of holes, thinning out toward the eyes
    for py in range(top, int(top + (wl - top) * 0.7), 7):
        for px in range(cx - RX, cx + RX, 7):
            jx, jy = px + int(hsh(px, py, 5) * 5), py + int(hsh(px, py, 6) * 5)
            if not (0 <= jx < W and 0 <= jy < Hh) or abs(jx - cx) < 3 or inEye(jx, jy, 4): continue
            if not all(C.body[jy + dy, jx + dx] for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)) if 0 <= jy + dy < Hh and 0 <= jx + dx < W): continue
            u = (jy - top) / (wl - top)
            if hsh(px, py, 9) > 0.95 - u * 1.4: continue
            pit(C, jx + 0.5, jy + 0.5, u < 0.3 or hsh(px, py, 4) < 0.35, lambda x_, y_: band[y_, x_] if band[y_, x_] >= 0 else None)
    # eyes: a fleshy socket, a lid fold above, a gold iris lit from the upper left, a vertical slit, a glint; red veins round it
    for k in range(8):
        ex_, ey_, er = eye_at(k)
        for py in range(int(ey_ - er - 4), int(ey_ + er + 5)):
            for px in range(int(ex_ - er - 4), int(ex_ + er + 5)):
                if not (0 <= px < W and 0 <= py < Hh and C.body[py, px]): continue
                dx, dy = px + 0.5 - ex_, (py + 0.5 - ey_) * 0.85; d = math.hypot(dx, dy)
                if d > er + 3: continue
                if d > er + 1.6: C.put(px, py, SKIN[min(6, band[py, px] + 1)] if dy < 0 else SKIN[max(0, band[py, px] - 1)]); continue # lid above, fold below
                if d > er: C.put(px, py, INK); continue
                if abs(dx) <= max(0.6, er * 0.13) * (1 - (dy / er) ** 2) ** 0.5 + 0.35 and abs(dy) < er * 0.82: C.put(px, py, PUPIL); continue
                g = math.hypot(dx + er * 0.25, dy + er * 0.3) / er # bright toward the upper left, deep at the rim
                C.put(px, py, IRIS[5 if g < 0.25 else 4 if g < 0.5 else 3 if g < 0.8 else 2 if g < 1.05 else 1 if d < er * 0.9 else 0])
        C.put(int(ex_ - er * 0.45), int(ey_ - er * 0.5), IRIS[5]); C.put(int(ex_ - er * 0.45) + 1, int(ey_ - er * 0.5), H('#ffffff') if er > 4 else IRIS[5])
        for j in range(3): # veins
            a = math.pi * (0.15 + 0.35 * j) + (math.pi if ex_ > cx else 0)
            for t in range(3, 7):
                px, py = int(ex_ + math.cos(a) * (er + t)), int(ey_ + math.sin(a) * (er + t) + (t % 2))
                if 0 <= px < W and 0 <= py < Hh and C.body[py, px]: C.put(px, py, SKIN[max(0, band[py, px] - 2)])
    C.outline()
    hw = hw0
    under_shadow(C, cx, wl, hw * 1.1, 0.0); ripples(C, cx, wl, hw, V['seed'], ((1.6, 0.2), (2.2, 0.35), (2.9, 0.5)))
    foam_ring(C, cx, wl, hw, V['seed'], hw * 1.02, hw * 0.5); drops(C, cx, wl, hw, V['seed'], 14)
    return C

def save(C, path):
    Image.fromarray(np.dstack([C.rgb, C.a]), 'RGBA').save(path)
    # trim to content plus a 2 px margin, and report where the waterline sits in the trimmed image
    im = Image.open(path); bb = im.getbbox(); im.crop((bb[0] - 2, bb[1] - 2, bb[2] + 2, bb[3] + 2)).save(path)
    return bb
if __name__ == '__main__':
    spec = json.load(open(sys.argv[1])); od = sys.argv[2]; os.makedirs(od, exist_ok=True); info = {}
    for name, V in spec.items():
        C = head(V) if V.get('kind') == 'head' else arm(V)
        bb = save(C, os.path.join(od, name + '.png'))
        wl = V['wl'] if V.get('kind') == 'head' else V['base'][1]; bx = V['cx'] if V.get('kind') == 'head' else V['base'][0]
        info[name] = {'anchor': [bx - bb[0] + 2, wl - bb[1] + 2]} # the point that sits on the water surface
    json.dump(info, open(os.path.join(od, 'anchors.json'), 'w'), indent=1)

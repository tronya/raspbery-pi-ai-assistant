#!/usr/bin/env python3
"""Particle planets for the 3.5" screen: a numpy port of the physics in github.com/tronya/particles (main.js).

The original runs ~150k particles on the GPU; here ~7500 particles are integrated on the CPU with the same forces:
three orbiting attractors per colour group (pull + swirl), the planet's flow around its tilted axis, turbulence and
random diffusion, gravity of the planet's centre with a far field and a tether, soft walls of the orbit band
R_MIN..R_MAX, drag with "capture" wells, a speed limit and a hard clamp. Colours and additive blending are the
original's too: dense places add up to white, thin places show single coloured dots.
(The simplex noise of the shader is replaced by a cheap sine noise.)

Modes (tap switches): 2 only the white planet (the default), 0 all three planets gathered in the middle,
1 three separate balls in a triangle, then back to 2. Run `python3 particles.py --bench` to time it and write preview PNGs.
"""
import math
import time

import numpy as np
from PIL import Image

RADIUS, GRAVITY = 1.6, 3.9          # attractor radius, gravity constant (original names)
R_MIN, R_MAX, CEIL = 1.25, 3.9, 16.0
FAR_K, TETHER = 4.0, 0.10
PAIR_GAP = 9.5                      # spread mode: centre-to-centre distance of the three planets

RNG = np.random.default_rng(5)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def dot(a, b):
    return np.einsum("ij,ij->i", a, b)


def cross(a, b):
    out = np.empty_like(a)
    out[:, 0] = a[:, 1] * b[:, 2] - a[:, 2] * b[:, 1]
    out[:, 1] = a[:, 2] * b[:, 0] - a[:, 0] * b[:, 2]
    out[:, 2] = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    return out


def noise(x, y, z):
    """Cheap smooth pseudo-noise in about [-1, 1] (stands in for the shader's simplex noise)."""
    return np.float32(0.55) * (np.sin(1.7 * x + 2.3 * y + 1.3 * z) * np.cos(1.9 * y - 1.1 * z + 0.7 * x) + np.sin(2.1 * z + 1.3 * x - 0.9 * y))


def normalize(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# ---- attractors: 3 per colour group (9 groups = 3 planets x 3 groups), each orbiting on its own axis
IDS = np.arange(27, dtype=np.float64)
A_AXIS = normalize(np.stack([np.sin(IDS * 12.9898 + 1), np.cos(IDS * 78.233 + 2), np.sin(IDS * 37.719 + 3)], 1))
A_BASE = normalize(np.stack([np.cos(IDS * 4.1 + 0.5), np.sin(IDS * 2.3 + 1.7), np.cos(IDS * 5.7 + 2.2)], 1))
_f = np.sin(IDS * 91.7) * 437.5
A_SPEED = (0.45 + 0.4 * (_f - np.floor(_f))) * np.where(IDS % 2 < 1, 1.0, -1.0)


def attractors(t):
    """(9, 3, 3) unit vectors: group, k, xyz (Rodrigues rotation of the base about the axis)."""
    a = t * A_SPEED
    c, s = np.cos(a)[:, None], np.sin(a)[:, None]
    b, ax = A_BASE, A_AXIS
    rot = b * c + np.cross(ax, b) * s + ax * (ax * b).sum(1, keepdims=True) * (1 - c)
    return rot.reshape(9, 3, 3).astype(np.float32)


# ---- colours of the groups, as in the original shaders
def group_colours():
    col = np.zeros((3, 3, 3), np.float32)
    col[0] = [[0.06, 0.88, 0.76], [0.62, 0.26, 1.0], [0.20, 0.62, 1.0]]          # planet 0: teal / violet / blue
    for gi in range(3):                                                             # planet 1: yellow-red family
        h = (0.065 + (gi - 1) * 0.045) % 1.0
        k = np.clip(np.abs((h * 6 + np.array([0.0, 4.0, 2.0])) % 6 - 3) - 1, 0, 1)
        col[1, gi] = 1.0 * 0.15 + k * 0.85
    return col                                                                      # planet 2 (greys) is computed per particle


GROUP_COL = group_colours()


class Scene:
    def __init__(self, size=224, per_planet=2500):
        self.size = size
        n = per_planet * 3
        self.n = n
        self.pl = np.repeat(np.arange(3), per_planet)
        self.gi = RNG.integers(0, 3, n)
        self.g = self.pl * 3 + self.gi
        # start: random direction, radius spread over the whole band, a roughly circular orbit in a random direction
        d = normalize(RNG.normal(size=(n, 3)))
        rn = RADIUS * (0.8 + RNG.random(n) ** 1.6 * 1.6)
        self.rel = (d * rn[:, None]).astype(np.float32)
        tdir = normalize(cross(self.rel.astype(np.float64), RNG.normal(size=(n, 3))))
        vs = np.sqrt(GRAVITY / rn) * (0.85 + 0.3 * RNG.random(n))
        self.vel = (tdir * vs[:, None]).astype(np.float32)
        self.h2 = RNG.random(n).astype(np.float32)               # per-particle grey tone
        self.pl3 = (self.pl * 3.0).astype(np.float32)
        self.gi5 = (self.gi * 5.0).astype(np.float32)
        self.g7 = (self.g * 7.0).astype(np.float32)
        self.gim1 = (self.gi - 1.0).astype(np.float32)
        self.k = 0
        self.turb = np.zeros((n, 3), np.float32)                  # turbulence and flow tilt change slowly: refreshed every few steps
        self.tl = np.zeros(n, np.float32)
        self.pool = RNG.random((n * 3, 3), dtype=np.float32)      # random numbers for the diffusion, re-used with a random offset

        # each planet spins about its own (slowly precessing) axis
        self.paxis0 = normalize(np.stack([np.sin(np.arange(3) * 12.9 + 1), np.cos(np.arange(3) * 7.3 + 2), np.sin(np.arange(3) * 4.1 + 3)], 1))
        self.t = 0.0
        self.mode = 2                          # start with only the white planet
        self.mix = 0.0                         # 0 = gathered, 1 = spread triangle
        self.vis = np.array([0.0, 0.0, 1.0])
        self.t0 = time.time()
        self.last = self.t0
        self.pulse = 0.0

    # ---------------------------------------------------------------- interaction
    def tap(self):
        """Burst, and switch mode: only white -> gathered -> spread -> only white."""
        self.mode = (self.mode + 1) % 3
        r = np.linalg.norm(self.rel, axis=1, keepdims=True)
        self.vel += self.rel / np.maximum(r, 1e-4) * 2.5               # a radial kick, the physics pulls it back
        self.pulse = 1.0

    # ---------------------------------------------------------------- physics
    def step(self, dt, t):
        p, v = self.rel, self.vel
        self.k += 1
        r = np.sqrt(dot(p, p))
        n = p / np.maximum(r, 1e-4)[:, None]
        w = smooth(R_MAX * 2.4, R_MAX * 1.3, r)
        f = np.zeros_like(p)
        cap = np.zeros(self.n, np.float32)
        att = attractors(t)                                             # (9, 3, 3)
        for k in range(3):
            a = att[:, k, :][self.g]
            dvec = a * np.float32(RADIUS) - p
            dd = dot(dvec, dvec)
            inv = np.float32(1.0) / (dd + np.float32(0.12)) ** np.float32(1.5)
            f += dvec * (inv * w)[:, None]                              # pull toward the attractor
            f += cross(a, dvec) * (inv * w * np.float32(1.3))[:, None]  # swirl around it
            cap += w / (np.float32(1.0) + dd * np.float32(5.0))         # friction well

        # the planet's flow: spin about its own axis, which varies smoothly across the ball
        ang = t * 0.05 + np.arange(3)
        ca, sa = np.cos(ang)[:, None], np.sin(ang)[:, None]
        rax = normalize(np.array([0.3, 1.0, 0.2]))
        pax = self.paxis0 * ca + np.cross(rax, self.paxis0) * sa + rax * (self.paxis0 @ rax)[:, None] * (1 - ca)
        tilt = normalize(np.cross(pax, [0.0, 1.0, 0.1]) + 1e-4)
        cp, dp = np.cross(tilt, pax).astype(np.float32), (tilt * pax).sum(1).astype(np.float32)
        if self.k % 4 == 1:
            self.tl = (noise(n[:, 0] * 1.1 + self.pl3, n[:, 1] * 1.1 + self.gi5, n[:, 2] * 1.1 + np.float32(t * 0.05)) * 1.6 + self.gim1 * 0.4).astype(np.float32)
        c, s_ = np.cos(self.tl)[:, None], np.sin(self.tl)[:, None]
        pa, ti = pax.astype(np.float32)[self.pl], tilt.astype(np.float32)[self.pl]
        gaxis = pa * c + cp[self.pl] * s_ + ti * (dp[self.pl][:, None] * (1 - c))
        spin = np.sqrt(np.float32(GRAVITY) / np.maximum(r, 0.8))
        flow = cross(gaxis, n) * (spin * np.clip(r / 1.6, 0.6, 1.4))[:, None]
        dv = flow - v
        f += (dv - n * dot(dv, n)[:, None]) * (np.float32(0.35) * w)[:, None]

        # turbulence (refreshed on a third of the steps) and diffusion
        if self.k % 3 == 0:
            qx, qy, qz = p[:, 0] * 1.3, p[:, 1] * 1.3 + np.float32(t * 0.15), p[:, 2] * 1.3 + self.g7
            self.turb[:, 0] = noise(qx, qy, qz)
            self.turb[:, 1] = noise(qx + 17, qy + 17, qz + 17)
            self.turb[:, 2] = noise(qx + 41, qy + 41, qz + 41)
        f += self.turb * np.float32(0.5)
        off = int(RNG.integers(0, self.n * 2))
        f += (self.pool[off:off + self.n] - np.float32(0.5)) * np.float32(0.35)

        # gravity of the centre, far field + tether, soft walls: all along n, so they are summed first
        rad = -GRAVITY / np.maximum(r * r, 1e-3) - (1 - w) * (GRAVITY * FAR_K / (r * r + 1.0) + TETHER)
        rad += 60.0 * np.maximum(R_MIN + 0.08 - r, 0.0) - 12.0 * np.maximum(r - R_MAX, 0.0) * w - 25.0 * np.maximum(r - 6.8, 0.0) * w
        f += n * rad.astype(np.float32)[:, None]

        v += f * np.float32(dt)
        v *= np.exp(-(0.20 + 1.4 * np.minimum(cap, 1.5) + 0.25 * (1 - w)) * dt)[:, None]
        sp = np.sqrt(dot(v, v))
        v *= np.where(sp > 3.5, 3.5 / np.maximum(sp, 1e-4), 1.0).astype(np.float32)[:, None]      # speed limit
        slow = np.nonzero(sp < 0.55)[0]                                                           # never come to rest
        if slow.size:
            vs = v[slow]
            dirs = vs / np.maximum(sp[slow], 1e-4)[:, None]
            v[slow] = vs + dirs * ((0.55 - sp[slow]) * 2.0 * dt * 10.0).astype(np.float32)[:, None]
        p += v * np.float32(dt)
        r2 = np.sqrt(dot(p, p))
        p *= (np.clip(r2, R_MIN, CEIL) / np.maximum(r2, 1e-4)).astype(np.float32)[:, None]        # hard floor and a loose ceiling

    # ---------------------------------------------------------------- one frame
    def frame(self):
        now = time.time()
        dt_real = min(0.15, now - self.last)
        self.last = now
        t = now - self.t0
        self.step(min(0.07, dt_real + 1e-3), t)         # one physics step per picture, in real time
        size = self.size

        self.mix += ((1.0 if self.mode == 1 else 0.0) - self.mix) * min(1.0, dt_real * 1.8)
        m = self.mix * self.mix * (3 - 2 * self.mix)
        target = np.array([0.0, 0.0, 1.0]) if self.mode == 2 else np.ones(3)
        self.vis += (target - self.vis) * min(1.0, dt_real * 2.5)
        self.pulse *= math.exp(-2.0 * dt_real)

        # planet centres: nearly on top of each other when gathered, the original equilateral triangle when spread
        tri = PAIR_GAP * math.sqrt(3) / 2
        tri_c = np.array([[-PAIR_GAP / 2, -tri / 3, 0], [PAIR_GAP / 2, -tri / 3, 0], [0, 2 * tri / 3, 0]])
        ang = np.arange(3) * 2.094 + 0.3 * t
        gat_c = np.stack([0.5 * np.cos(ang), 0.5 * np.sin(ang), 0.3 * np.sin(0.6 * t + np.arange(3) * 2.1)], 1)
        cen = gat_c * (1 - m) + tri_c * m

        # camera: slow turn about the vertical axis, a fixed roll and tilt (like the original's group rotation)
        ya, rz, tx = 0.10 * t, 0.25, 0.18
        cy_, sy_, cz_, sz_, cx_, sx_ = math.cos(ya), math.sin(ya), math.cos(rz), math.sin(rz), math.cos(tx), math.sin(tx)
        Ry = np.array([[cy_, 0, sy_], [0, 1, 0], [-sy_, 0, cy_]])
        Rz = np.array([[cz_, -sz_, 0], [sz_, cz_, 0], [0, 0, 1]])
        Rx = np.array([[1, 0, 0], [0, cx_, -sx_], [0, sx_, cx_]])
        R = (Rx @ Ry @ Rz).astype(np.float32)

        rel_r = self.rel @ R.T
        pos = rel_r + (cen @ R.T).astype(np.float32)[self.pl]
        persp = 14.0 / (14.0 - np.clip(pos[:, 2], -8.0, 8.0))
        solo = 1.0 - max(self.vis[0], self.vis[1])                    # 1 when only the white planet is shown
        scale = size * 0.114 * (1 - 0.55 * m) * (1 + 0.5 * solo)       # a lone planet is drawn larger
        px = size / 2 + pos[:, 0] * persp * scale
        py = size / 2 - pos[:, 1] * persp * scale

        # colours and brightness as in the original point shader
        r = np.linalg.norm(self.rel, axis=1)
        sp = np.linalg.norm(self.vel, axis=1)
        col = GROUP_COL[self.pl, self.gi]
        grey = self.pl == 2
        tt = np.clip((r - 1.0) / 2.4, 0.0, 1.0)
        tone = (1.0 - tt ** 0.55) * (0.30 + 0.70 * self.h2) + 0.55 * self.h2 ** 2 * (1 - tt)
        col = np.where(grey[:, None], np.clip(tone, 0, 1)[:, None], col)
        col = col * (1 - np.clip(sp * 0.05, 0, 0.18))[:, None] + np.clip(sp * 0.05, 0, 0.18)[:, None]
        facing = rel_r[:, 2] / np.maximum(r, 1e-4)
        alpha = (0.30 + 0.70 * smooth(-1.0, 1.0, facing)) * (0.6 + 0.5 * np.clip(sp, 0, 1.5))
        wgt = (alpha * persp * 1.9 * self.vis[self.pl] * (1 + 0.8 * self.pulse) * (1 + 1.2 * solo)).astype(np.float32)

        fx0, fy0 = np.floor(px), np.floor(py)
        fx, fy = (px - fx0).astype(np.float32), (py - fy0).astype(np.float32)
        ix, iy = fx0.astype(np.int32), fy0.astype(np.int32)
        ok = (ix >= 0) & (ix < size - 1) & (iy >= 0) & (iy < size - 1) & (wgt > 0.01)
        ix, iy, fx, fy = ix[ok], iy[ok], fx[ok], fy[ok]
        cw = col[ok] * wgt[ok][:, None]
        base = iy * size + ix
        idx = np.concatenate([base, base + 1, base + size, base + size + 1])
        wts = np.concatenate([(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy])
        acc = np.stack([np.bincount(idx, weights=np.tile(cw[:, c], 4) * wts, minlength=size * size) for c in range(3)], axis=1)
        img = np.clip(acc.reshape(size, size, 3) * 1.5, 0.0, 1.0)       # additive blending: dense places clip to white
        return (img * 255).astype(np.uint8)


if __name__ == "__main__":
    import sys
    s = Scene()
    if "--bench" in sys.argv:
        t0 = time.time()
        for i in range(60):
            f = s.frame()
        print(f"{(time.time() - t0) / 60 * 1000:.1f} ms per frame, {s.n} particles, frame {f.shape}")
        Image.fromarray(f).resize((448, 448), Image.NEAREST).save("/tmp/particles_gathered.png")
        s.tap()
        for i in range(120):
            f = s.frame(); time.sleep(0.02)
        Image.fromarray(f).resize((448, 448), Image.NEAREST).save("/tmp/particles_spread.png")
        s.tap()
        for i in range(100):
            f = s.frame(); time.sleep(0.02)
        Image.fromarray(f).resize((448, 448), Image.NEAREST).save("/tmp/particles_white.png")
        print("saved previews")

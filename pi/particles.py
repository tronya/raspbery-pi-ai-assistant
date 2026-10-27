#!/usr/bin/env python3
"""Particle spheres for the 3.5" screen: a small numpy port of the GPU "planets" demo.

Three spheres of orbiting particles (teal-violet, yellow-red, grey-white), by default all three sitting on
top of each other in the middle. Every particle moves on its own orbit around its planet, the camera turns
slowly, glowing trails follow the motion. tap() makes the cloud burst and toggles between the gathered state
(all in the centre) and a spread triangle.

Pure numpy + PIL, no GPU: about 5000 particles at ~25 ms per frame on a Raspberry Pi 4.
Run `python3 particles.py --bench` to time it and write a few preview PNGs.
"""
import math
import time

import numpy as np
from PIL import Image, ImageFilter

# planet palettes: (inner colour, outer colour)
PALETTES = [((90, 255, 235), (150, 70, 255)),     # turquoise -> violet
            ((255, 235, 80), (255, 70, 40)),      # yellow -> red
            ((255, 255, 255), (130, 140, 160))]   # white -> grey


class Scene:
    def __init__(self, size=224, per_planet=1700, seed=7):
        self.n_img = size
        rng = np.random.default_rng(seed)
        n = per_planet * 3
        self.n = n
        self.planet = np.repeat(np.arange(3), per_planet)
        # every planet is a set of orbital bands (rings): a ring has its own radius and a random tilt,
        # particles run along it with a small thickness
        bands = 13
        band_r = 0.5 + 1.0 * np.sort(rng.random((3, bands)), axis=1)
        axes = rng.normal(size=(3, bands, 3))
        axes /= np.linalg.norm(axes, axis=2, keepdims=True)
        helper = rng.normal(size=(3, bands, 3))
        bu = np.cross(axes, helper)
        bu /= np.linalg.norm(bu, axis=2, keepdims=True)
        bv = np.cross(axes, bu)
        band = rng.integers(0, bands, n)
        pl = self.planet
        self.r = band_r[pl, band] * (1 + 0.03 * rng.normal(size=n))
        self.u, self.v = bu[pl, band], bv[pl, band]
        self.out = axes[pl, band] * (0.045 * rng.normal(size=(n, 1)))     # thickness across the ring
        self.phi0 = rng.random(n) * 2 * math.pi
        direction = np.where(self.planet == 1, -1.0, 1.0)                 # the yellow planet turns the other way
        self.omega = direction * 1.25 / self.r ** 1.5 * (0.85 + 0.3 * rng.random(n))
        self.breath = rng.random(n) * 2 * math.pi
        # per-particle colour: inner -> outer palette, a little jitter
        k = ((self.r - 0.5) / 1.0)[:, None]
        inner = np.array([PALETTES[p][0] for p in range(3)], dtype=np.float32)[self.planet]
        outer = np.array([PALETTES[p][1] for p in range(3)], dtype=np.float32)[self.planet]
        col = inner * (1 - k) + outer * k
        col *= (0.75 + 0.25 * rng.random((n, 1)))
        self.col = (col / 255.0).astype(np.float32)
        self.trail = np.zeros((size, size, 3), np.float32)
        self.mix = 0.0            # 0 = gathered in the middle, 1 = spread in a triangle
        self.target = 0.0
        self.pulse_t = -99.0
        self.t0 = time.time()
        self.last = self.t0

    # ---------------------------------------------------------------- interaction
    def tap(self):
        """Burst now, and swap between the gathered and the spread state."""
        self.pulse_t = time.time() - self.t0
        self.target = 1.0 - self.target

    # ---------------------------------------------------------------- one frame
    def frame(self):
        now = time.time()
        t = now - self.t0
        dt = min(0.2, now - self.last)
        self.last = now
        self.mix += (self.target - self.mix) * min(1.0, dt * 1.6)
        m = self.mix * self.mix * (3 - 2 * self.mix)

        size = self.n_img
        pulse = math.exp(-2.6 * (t - self.pulse_t)) if t - self.pulse_t < 3 else 0.0
        # orbit angles and positions in each planet's own frame
        phi = self.phi0 + self.omega * t
        rad = self.r * (1 + 0.05 * np.sin(t * 0.9 + self.breath) + 0.55 * pulse)
        pos = (self.u * (np.cos(phi) * rad)[:, None] + self.v * (np.sin(phi) * rad)[:, None] + self.out).astype(np.float32)

        # planet centres: a tight turning triangle when gathered, a wide one when spread
        gap = 0.38 + 1.55 * m
        ang = np.array([0.0, 2.094, 4.189]) + 0.35 * t * (1 - 0.7 * m)
        cen = np.stack([gap * np.cos(ang), gap * np.sin(ang) * 0.8, 0.35 * np.sin(t * 0.6 + np.arange(3) * 2.1) * (1 - m)], 1)
        pos += cen[self.planet].astype(np.float32)

        # camera: slow turn around the vertical axis plus a tilt
        a, b = 0.28 * t, 0.42
        ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
        x = pos[:, 0] * ca + pos[:, 2] * sa
        z = -pos[:, 0] * sa + pos[:, 2] * ca
        y = pos[:, 1] * cb - z * sb
        z = pos[:, 1] * sb + z * cb
        persp = 14.0 / (14.0 - np.clip(z, -8.0, 8.0))                    # gentle perspective, never singular
        scale = (size * 0.21) * (1 - 0.50 * m)                        # zoom out when spread
        px = size / 2 + x * persp * scale
        py = size / 2 + y * persp * scale
        light = np.clip(0.55 + 0.30 * z, 0.25, 1.2) * (1 + 0.8 * pulse)

        # bilinear splatting keeps sub-pixel motion smooth
        ix, iy = np.floor(px).astype(np.int32), np.floor(py).astype(np.int32)
        fx, fy = (px - ix).astype(np.float32), (py - iy).astype(np.float32)
        ok = (ix >= 0) & (ix < size - 1) & (iy >= 0) & (iy < size - 1)
        ix, iy, fx, fy, w0 = ix[ok], iy[ok], fx[ok], fy[ok], (light * persp)[ok].astype(np.float32)
        col = self.col[ok] * w0[:, None]
        flat = iy * size + ix
        acc = np.zeros((size * size, 3), np.float32)
        for dx, dy, wgt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            idx = flat + dy * size + dx
            for c in range(3):
                acc[:, c] += np.bincount(idx, weights=col[:, c] * wgt, minlength=size * size)
        acc = acc.reshape(size, size, 3)

        # glowing trails: decay the old frame, add the new one, tone-map, add a soft halo
        self.trail = self.trail * 0.72 + acc
        img = np.nan_to_num(1.0 - np.exp(-self.trail * 0.9))
        base = Image.fromarray((img * 255).astype(np.uint8))
        glow = base.filter(ImageFilter.GaussianBlur(5))
        out = np.asarray(base, dtype=np.uint16) + (np.asarray(glow, dtype=np.uint16) * 7 // 10)
        return np.minimum(out, 255).astype(np.uint8)


if __name__ == "__main__":
    import sys
    s = Scene()
    if "--bench" in sys.argv:
        t0 = time.time()
        for i in range(40):
            f = s.frame()
        print(f"{(time.time() - t0) / 40 * 1000:.1f} ms per frame, {s.n} particles, frame {f.shape}")
        Image.fromarray(f).save("/tmp/particles_gathered.png")
        s.tap()
        for i in range(110):
            f = s.frame(); time.sleep(0.03)
        Image.fromarray(f).save("/tmp/particles_spread.png")
        print("saved /tmp/particles_gathered.png and /tmp/particles_spread.png")

#!/usr/bin/env python3
"""Animated eyes for a 320x480 RGB565 framebuffer (/dev/fb0).

Usage:  sudo python3 eyes.py [--demo] [--pupil 0|1] [--fps 20]
Change emotion while running:  echo angry > /tmp/eyes_cmd
Commands: neutral angry sad happy thinking surprised sleepy talking
          look left|right|up|down|center   blink   (anything else ignored)
"""
import argparse, json, math, os, random, time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 320, 480
S = 2                       # supersampling
LW, LH = 480, 320           # landscape drawing canvas (rotated into the 320x480 fb)
X0, X1 = 10, 470            # landscape columns that hold the face
BW = X1 - X0
Y0, BH = X0, BW             # after rotation those columns become fb rows
ROT = 1                     # np.rot90 k: -1 = clockwise, 1 = counter-clockwise
SLEEP_AFTER = 60            # seconds without a face (or any activity) before the eyes fall asleep
CMD = "/tmp/eyes_cmd"
GAZE = "/tmp/eyes_gaze"      # "x y" written by track.py while a face is visible
MOOD = "/tmp/eyes_mood"      # emotion read from the face by track.py
ALERT = "/tmp/eyes_alert"    # exists while an air-raid alert is active (text inside)
WARN = "/tmp/eyes_warn"      # exists while a neighbouring oblast has an alert (text inside)
UI_FLAG = "/tmp/ui_active"      # exists while the touch menu (ui.py) owns the screen
UI_SETTINGS = "/home/tronyak/ui_settings.json"
SAY = "/tmp/eyes_say"        # text to show as a caption under the eyes
CX = (153, 327)             # eye centres: glossy round eyes with a small gap
CY = 150
RX, RY = 62, 65
YOFF = (0, 0)               # vertical offset per eye (e.g. (8, -8) for a cute asymmetry)
FLAT = False                # flat white eyeball and tiny pupil, no shading/highlights

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 23 * S)
except Exception:
    FONT = ImageFont.load_default()

# emotion -> target params
EMO = {
    "neutral":   dict(open=1.0,  tl=0,   tr=0,   lift=0.0, mc=0.0,  mo=0.0, gx=0,    gy=0,    ps=1.0),
    "angry":     dict(open=0.85, tl=32,  tr=32,  lift=0.0, mc=-0.4, mo=0.0, gx=0,    gy=0.1,  ps=0.8),
    "sad":       dict(open=0.8,  tl=-28, tr=-28, lift=0.0, mc=-0.9, mo=0.0, gx=0,    gy=0.5,  ps=1.1),
    "happy":     dict(open=1.0,  tl=0,   tr=0,   lift=0.65, mc=1.0, mo=0.0, gx=0,    gy=-0.1, ps=1.0),
    "thinking":  dict(open=0.9,  tl=-6,  tr=20,  lift=0.0, mc=-0.15, mo=0.0, gx=0.7, gy=-0.7, ps=0.9),
    "surprised": dict(open=1.18, tl=0,   tr=0,   lift=0.0, mc=0.0,  mo=0.7, gx=0,    gy=0,    ps=0.6),
    "sleepy":    dict(open=0.28, tl=-6,  tr=-6,  lift=0.0, mc=0.0,  mo=0.0, gx=0,    gy=0.3,  ps=1.0),
    "talking":   dict(open=1.0,  tl=0,   tr=0,   lift=0.1, mc=0.2,  mo=0.0, gx=0,    gy=0,    ps=1.0),
}
BASE = dict(open=1.0, tl=0, tr=0, lift=0.0, mc=0.0, mo=0.0, gx=0, gy=0, ps=1.0,
            tears=0.0, shk=0.0, bgt=0.0, zz=0.0, bb=0.0, bhl=0.0, bhr=0.0, btl=0.0, btr=0.0, mxs=0.0, mww=50.0, qm=0.0,
            sl="round", sr="round")   # sl/sr: eye shape (left/right)
for _v in EMO.values():
    for _k, _d in BASE.items():
        _v.setdefault(_k, _d)


EMO["thinking"].update(ps=0.62, bb=1.0, mww=22, mc=-0.2, gx=0, gy=0)   # cartoon "pensive": brows, side glances, small mouth


EMO["sleeping"] = {**BASE, "gx": 0, "gy": 0.2, "zz": 1.0, "sl": "sleep", "sr": "sleep"}   # closed eyes + floating Z


EMO["alert"] = {**BASE, "open": 1.15, "tl": 22, "tr": 22, "ps": 0.5, "shk": 0.5, "mc": -0.4}   # red, wide, trembling


EMO["warn"] = {**BASE, "open": 1.1, "tl": 8, "tr": 8, "ps": 0.7, "mc": -0.25}        # wary orange eyes


def E(**kw):
    return {**BASE, **kw}


EMO.update({
    "love":       E(mc=0.9, gy=-0.1, sl="heart", sr="heart"),
    "excited":    E(open=1.1, mc=1.0, mo=0.4, sl="star", sr="star"),
    "dizzy":      E(mo=0.2, sl="spiral", sr="spiral"),
    "dead":       E(mc=-0.3, sl="x", sr="x"),
    "joy":        E(mc=1.0, mo=0.6, sl="arc", sr="arc"),
    "wink":       E(mc=0.8, lift=0.3, sr="arc"),
    "pain":       E(mc=-0.8, mo=0.5, sl="gt", sr="gt"),
    "scared":     E(open=1.2, tl=-20, tr=-20, ps=0.3, mo=0.8, shk=1.0, gy=0.1),
    "suspicious": E(open=0.55, tl=16, tr=-4, mc=-0.25, gx=0.8, ps=0.9),
    "bored":      E(open=0.5, mc=-0.2, gx=-0.6, gy=-0.5),
    "cry":        E(open=0.8, tl=-26, tr=-26, mc=-1.0, gy=0.3, tears=1.0),
    "evil":       E(open=0.7, tl=26, tr=26, mc=1.0, ps=0.6, gy=0.15),
})

# eyebrows for the older emotions (bb: on, bhl/bhr: raise per eye, btl/btr: tilt, + lowers the inner end)
for _n, _kw in {
    "angry": dict(bb=1.0, btl=20, btr=20), "sad": dict(bb=1.0, bhl=0.3, bhr=0.3, btl=-14, btr=-14),
    "surprised": dict(bb=1.0, bhl=1.0, bhr=1.0), "happy": dict(bb=1.0, bhl=0.6, bhr=0.6, btl=-4, btr=-4),
    "scared": dict(bb=1.0, bhl=0.9, bhr=0.9, btl=-12, btr=-12), "suspicious": dict(bb=1.0, bhr=0.9, btl=10, btr=-4),
    "evil": dict(bb=1.0, btl=22, btr=22), "sleepy": dict(bb=1.0, btl=-6, btr=-6),
    "bored": dict(bb=1.0, bhl=0.1, bhr=0.1, btl=-4, btr=-4), "cry": dict(bb=1.0, bhl=0.2, bhr=0.2, btl=-16, btr=-16),
}.items():
    EMO[_n].update(_kw)

# new expressions from the reference sheets
EMO.update({
    "confused":    E(ps=0.8, gx=0.5, gy=-0.3, bb=1.0, bhr=0.95, btl=10, btr=-6, mww=26, qm=1.0),
    "smug":        E(open=0.62, ps=0.9, gx=0.3, mc=0.7, mxs=14, mww=34, bb=1.0, bhl=0.4, bhr=0.4),
    "nervous":     E(open=1.1, ps=0.45, shk=0.5, mc=-0.3, tears=0.7, bb=1.0, bhl=0.8, bhr=0.8, btl=-10, btr=-10, mww=30),
    "sick":        E(open=0.7, tl=-14, tr=-14, ps=0.6, mc=-0.5, shk=0.15, gy=0.4, bb=1.0, btl=-12, btr=-12, mww=34),
    "laughing":    E(mc=1.0, mo=0.9, tears=1.0, shk=0.8, sl="arc", sr="arc"),
    "determined":  E(open=0.8, tl=18, tr=18, ps=0.6, mc=-0.1, bb=1.0, btl=14, btr=14, mww=36),
    "money":       E(mc=1.0, sl="dollar", sr="dollar"),
    "curious":     E(open=1.15, ps=0.8, gy=-0.4, mc=0.2, bb=1.0, bhl=0.5, bhr=0.9, mww=26),
    "embarrassed": E(open=0.9, tl=-10, tr=-10, ps=0.7, gx=0.8, gy=0.5, mc=-0.2, mxs=-18, mww=22, shk=0.2,
                     bb=1.0, bhl=0.6, bhr=0.6, btl=-12, btr=-12),
    "yawn":        E(open=0.35, tl=-10, tr=-10, mo=1.0, bb=1.0, bhl=0.1, bhr=0.1, btl=-6, btr=-6),
})

# eye colour per emotion (white by default)
COL = {
    "thinking": (185, 215, 255),
    "angry": (255, 80, 60),
    "sad": (150, 170, 225),
    "happy": (255, 240, 200),
    "surprised": (255, 255, 255),
    "sleepy": (170, 170, 190),
    "sleeping": (170, 180, 200),
    "alert": (255, 40, 30),
    "warn": (255, 170, 40),
    "confused": (255, 230, 170),
    "smug": (255, 235, 200),
    "nervous": (200, 215, 255),
    "sick": (170, 235, 150),
    "laughing": (255, 240, 200),
    "determined": (210, 230, 255),
    "money": (90, 235, 110),
    "embarrassed": (255, 150, 175),
    "yawn": (200, 205, 225),
    "love": (255, 90, 150),
    "excited": (255, 220, 80),
    "dizzy": (170, 255, 190),
    "dead": (170, 170, 170),
    "joy": (255, 240, 200),
    "wink": (255, 240, 200),
    "pain": (255, 150, 120),
    "scared": (190, 210, 255),
    "bored": (190, 190, 205),
    "cry": (140, 185, 255),
    "evil": (255, 60, 60),
}
for _k, _v in EMO.items():
    _v["cr"], _v["cg"], _v["cb"] = COL.get(_k, (255, 255, 255))
    _v["cyo"] = 0
    _v["es"] = 1.0                      # eye size, driven by the distance to the face
KEYS = ["open", "tl", "tr", "lift", "mc", "mo", "gx", "gy", "ps", "cr", "cg", "cb", "cyo", "es", "tears", "shk", "bgt", "zz", "bb", "bhl", "bhr", "btl", "btr", "mxs", "mww", "qm"]


try:
    FONT_Q = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60 * S)
    FONT_D = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 140 * S)
except Exception:
    FONT_Q = FONT_D = FONT


def draw_shape(d, kind, ex, ey, rx, ry, o, s, t, side):
    """Special (non-round) eye shapes, drawn in white; side 0 = left eye."""
    r = min(rx, ry)
    oo = max(0.08, min(1.0, o))
    if kind == "heart":
        k = 1 + 0.08 * math.sin(t * 8)               # heartbeat
        pts = []
        for n in range(48):
            a = 2 * math.pi * n / 48
            hx = 16 * math.sin(a) ** 3
            hy = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
            pts.append(((ex + hx / 17 * rx * k) * s, (ey - hy / 17 * ry * oo * k + ry * 0.05) * s))
        d.polygon(pts, fill=255)
    elif kind == "star":
        R, rot = r * 1.05 * (1 + 0.06 * math.sin(t * 6)), t * 0.8
        pts = []
        for n in range(10):
            a = rot + math.pi * n / 5 - math.pi / 2
            rr = R if n % 2 == 0 else R * 0.45
            pts.append(((ex + math.cos(a) * rr) * s, (ey + math.sin(a) * rr * oo) * s))
        d.polygon(pts, fill=255)
    elif kind == "spiral":
        pts = []
        for n in range(90):
            a = n * 0.2 + t * (6 if side == 0 else -6)
            rr = r * 0.95 * n / 90
            pts.append(((ex + math.cos(a) * rr) * s, (ey + math.sin(a) * rr * oo) * s))
        d.line(pts, fill=255, width=int(6 * s), joint="curve")
    elif kind == "x":
        L = r * 0.8
        d.line([((ex - L) * s, (ey - L * oo) * s), ((ex + L) * s, (ey + L * oo) * s)], fill=255, width=int(11 * s))
        d.line([((ex - L) * s, (ey + L * oo) * s), ((ex + L) * s, (ey - L * oo) * s)], fill=255, width=int(11 * s))
    elif kind == "arc":                               # happy squint, like ^
        d.arc([(ex - rx * 0.8) * s, (ey - ry * 0.55) * s, (ex + rx * 0.8) * s, (ey + ry * 0.95) * s],
              200, 340, fill=255, width=int(12 * s))
    elif kind == "dollar" and oo > 0.35:
        d.text((ex * s, ey * s), "$", font=FONT_D, fill=255, anchor="mm")
    elif kind == "sleep":                             # closed eyes, like a smile turned upside down
        d.arc([(ex - rx * 0.85) * s, (ey - ry * 0.75) * s, (ex + rx * 0.85) * s, (ey + ry * 0.35) * s],
              20, 160, fill=255, width=int(9 * s))
    elif kind == "think":                             # half-lidded eyes, pupils scanning left and right
        sh, sw = max(3.0, ry * 0.52 * oo), rx * 1.18
        d.ellipse([(ex - sw) * s, (ey - sh) * s, (ex + sw) * s, (ey + sh) * s], fill=250)
        iw = rx * 0.74
        ix = ex + math.sin(t * 1.3) * rx * 0.34
        d.ellipse([(ix - iw) * s, (ey - sh * 0.2) * s, (ix + iw) * s, (ey + sh * 0.98) * s], fill=0)   # lowered iris: looking down
        hr = max(2.5, sh * 0.18)
        hx, hy = ix - iw * 0.45, ey + sh * 0.12
        d.ellipse([(hx - hr) * s, (hy - hr) * s, (hx + hr) * s, (hy + hr) * s], fill=255)
        h2 = hr * 0.4
        d.ellipse([(ix - iw * 0.2 - h2) * s, (ey + sh * 0.62 - h2) * s, (ix - iw * 0.2 + h2) * s, (ey + sh * 0.62 + h2) * s], fill=255)
        d.line([((ex - sw * 1.12) * s, (ey - sh * 0.92) * s), ((ex + sw * 1.12) * s, (ey - sh * 0.92) * s)], fill=0, width=int(9 * s))
        d.line([((ex - sw) * s, (ey + sh * 0.95) * s), ((ex + sw) * s, (ey + sh * 0.95) * s)], fill=0, width=int(4 * s))
        by = ey - ry * (1.15 if side == 0 else 1.32)               # one eyebrow higher than the other
        d.line([((ex - 22) * s, (by + (4 if side == 0 else 6)) * s), ((ex + 18) * s, (by - (4 if side == 0 else 8)) * s)],
               fill=215, width=int(7 * s))
    elif kind == "gt":                                # > for the left eye, < for the right
        L, dx = r * 0.85, (1 if side == 0 else -1)
        d.line([((ex - dx * L) * s, (ey - L * 0.85) * s), ((ex + dx * L * 0.7) * s, ey * s),
                ((ex - dx * L) * s, (ey + L * 0.85) * s)], fill=255, width=int(12 * s), joint="curve")


def draw_brow(d, ex, ey, rx, ry, raise_, tilt, side, s):
    """Cartoon eyebrow: an arch above the eye, raised/tilted per eye."""
    y0 = ey - ry * 1.3 - raise_ * 16
    inner = 1 if side == 0 else -1
    x_out, x_in = ex - inner * rx * 0.85, ex + inner * rx * 0.85
    y_out, y_in = y0 + 3 - tilt * 0.25, y0 + tilt
    arch = 10 + raise_ * 4
    pts = []
    for k in range(13):
        t = k / 12
        pts.append((((1 - t) ** 2 * x_out + 2 * t * (1 - t) * ex + t ** 2 * x_in) * s,
                    ((1 - t) ** 2 * y_out + 2 * t * (1 - t) * (y0 - arch * 2) + t ** 2 * y_in) * s))
    d.line(pts, fill=235, width=int(8 * s), joint="curve")


def draw_eyeball(d, ex, ey, rx, ry, s):
    """Shaded eyeball: darker towards the edge and the top lid, bright centre slightly low."""
    n = 7
    for k in range(n):
        f = k / (n - 1)
        sh, shrink, dy = 150 + int(f * 100), f * 0.3, -ry * 0.06 * f
        d.ellipse([(ex - rx * (1 - shrink)) * s, (ey + dy - ry * (1 - shrink)) * s,
                   (ex + rx * (1 - shrink)) * s, (ey + dy + ry * (1 - shrink)) * s], fill=sh)


def render(p, blink, pupil_on, status=None, caption=None, alert=None):
    """Return a (BH, 320, 3) uint8 image (face band, rotated for the portrait fb)."""
    im = Image.new("L", (BW * S, LH * S), 0)
    d = ImageDraw.Draw(im)
    s = S
    cyb = CY + p["cyo"]
    for i, cx in enumerate(CX):
        inner = 1 if i == 0 else -1          # direction of the nose side
        tilt = (p["tl"] if i == 0 else p["tr"]) * 0.7         # lids are scaled for the eye size
        o = max(0.0, min(1.25, p["open"] * blink))
        ry = RY * p["es"] * (1.0 if o <= 1 else o)
        ex = 240 - X0 + (cx - 240) * p["es"] + p["gx"] * 38      # the whole eye follows the gaze
        ey = cyb + p["gy"] * 22 + YOFF[i] * p["es"]
        # slight perspective: the eye on the far side of the gaze gets a bit narrower
        RX_ = RX * p["es"] * (1 + 0.2 * p["gx"] * (1 if i == 0 else -1))
        tnow = time.time()
        if p["shk"] > 0.05:                         # trembling (scared)
            ex += random.uniform(-1, 1) * p["shk"] * 3
            ey += random.uniform(-1, 1) * p["shk"] * 3
        if p["tears"] > 0.05:                       # tears running down from the outer corner
            ph = (tnow * 0.7 + (0.5 if i else 0.0)) % 1.0
            tx, ty, tr_ = ex - inner * RX_ * 0.5, ey + ry * 0.75 + ph * 70, 6 * p["tears"] * (1 - ph * 0.5)
            d.ellipse([(tx - tr_) * s, (ty - tr_ * 1.4) * s, (tx + tr_) * s, (ty + tr_ * 1.4) * s], fill=255)
        kind = p["sl"] if i == 0 else p["sr"]
        if kind != "round":
            draw_shape(d, kind, ex, ey, RX_ * 1.2, ry * 1.2, o, s, tnow, i)
            continue
        # sclera: grey rim at the top (lid shadow), white below
        if FLAT:
            d.ellipse([(ex - RX_) * s, (ey - ry) * s, (ex + RX_) * s, (ey + ry) * s], fill=248)
        else:
            d.ellipse([(ex - RX_) * s, (ey - ry) * s, (ex + RX_) * s, (ey + ry) * s], fill=165)
            d.ellipse([(ex - RX_ * 0.97) * s, (ey - ry * 0.86) * s, (ex + RX_ * 0.97) * s, (ey + ry) * s], fill=250)
        # big glossy pupil, shifted towards the nose so a white crescent stays on the outer side
        if pupil_on and p["ps"] > 0.05:
            if FLAT:
                pr = 9.5 * p["ps"] * p["es"]
                px = ex + p["gx"] * 17 * p["es"]
                py = ey + p["gy"] * 17 * p["es"]
                d.ellipse([(px - pr) * s, (py - pr) * s, (px + pr) * s, (py + pr) * s], fill=0)
            else:
                pr = min(0.74 * RX_ * p["ps"], 0.86 * RX_)
                room = max(2.0, RX_ - pr - 1.5)
                dx, dy = inner * room * 0.55 + p["gx"] * room * 0.9, p["gy"] * room * 0.9
                n = math.hypot(dx, dy)
                if n > room:
                    dx, dy = dx / n * room, dy / n * room
                px, py = ex + dx, ey + dy
                d.ellipse([(px - pr) * s, (py - pr) * s, (px + pr) * s, (py + pr) * s], fill=0)
                gl = (px + pr * 0.1, py + pr * 0.5)       # dark-grey gloss on the lower part of the pupil
                d.ellipse([(gl[0] - pr * 0.55) * s, (gl[1] - pr * 0.26) * s, (gl[0] + pr * 0.55) * s, (gl[1] + pr * 0.26) * s], fill=40)
                hr = max(3, pr * 0.2)                      # large highlight
                hx, hy = px - pr * 0.32, py - pr * 0.38
                d.ellipse([(hx - hr) * s, (hy - hr) * s, (hx + hr) * s, (hy + hr) * s], fill=255)
                h2 = max(1.6, pr * 0.08)                   # small highlight
                h2x, h2y = px - pr * 0.3, py + pr * 0.45
                d.ellipse([(h2x - h2) * s, (h2y - h2) * s, (h2x + h2) * s, (h2y + h2) * s], fill=255)
        # upper lid: a black polygon whose lower edge is a (tilted) line
        base = ey - ry + (1.0 - min(o, 1.0)) * ry      # lid line y at the eye centre x
        # slope: positive tilt lowers the inner corner
        y_in = base + tilt
        y_out = base - tilt * 0.25
        xin = ex + inner * (RX_ + 6)
        xout = ex - inner * (RX_ + 6)
        top = ey - ry - 30
        d.polygon([(xout * s, y_out * s), (xin * s, y_in * s), (xin * s, top * s), (xout * s, top * s)], fill=0)
        # lower lid pushed up (cheeks) for happiness; also closes with blink
        lift = p["lift"] + (1 - min(blink, 1.0)) * 0.0
        if lift > 0.01:
            lr = RX_ * 1.35
            lcy = ey + ry * 1.25 - lift * ry * 0.95
            d.ellipse([(ex - lr) * s, (lcy) * s, (ex + lr) * s, (lcy + 1.3 * ry * 1.6) * s], fill=0)
        if p["bb"] > 0.05 and not caption:
            draw_brow(d, ex, ey, RX_, ry, p["bhl"] if i == 0 else p["bhr"], p["btl"] if i == 0 else p["btr"], i, s)
    if p["qm"] > 0.3 and not caption:               # a wobbling question mark next to the head
        qx, qy = CX[1] - X0 + 112, CY - 78 + math.sin(time.time() * 4) * 4
        d.text((qx * s, qy * s), "?", font=FONT_Q, fill=255, anchor="mm")
    # mouth
    my = CY + 98
    mw = p["mww"]
    mx = 240 - X0 + p["mxs"] + p["gx"] * 12                 # the mouth follows a little too
    mc, mo = p["mc"], p["mo"]
    if caption:
        pass                                    # the caption replaces the mouth
    elif abs(mc) < 0.12 and mo <= 0.05:
        pass                                    # a neutral face has no mouth
    elif mo > 0.05:
        r = 14 + mo * 18
        hw = 16 + mo * 22
        d.ellipse([(mx - hw) * s, (my - r * 0.3) * s, (mx + hw) * s, (my + r) * s], outline=225, width=5 * s // 2)
    else:
        pts = []
        for k in range(21):
            t = k / 20
            x = (mx - mw) * (1 - t) ** 2 + mx * 2 * t * (1 - t) + (mx + mw) * t ** 2
            y = my * (1 - t) ** 2 + (my + mc * 30) * 2 * t * (1 - t) + my * t ** 2
            pts.append((x * s, y * s))
        d.line(pts, fill=225, width=4 * s // 2 + 2, joint="curve")
    if p["zz"] > 0.3 and not caption:               # "Z z Z" floating up from the right eye
        tz = time.time()
        for n in range(3):
            ph = (tz * 0.45 + n / 3) % 1.0
            zx, zy = CX[1] - X0 + 85 + ph * 45 + n * 8, CY - 40 - ph * 80
            d.text((zx * s, zy * s), "Z" if n != 1 else "z", font=FONT, fill=int(230 * (1 - ph)), anchor="mm")
    if alert:                                    # alarm banner, pulsing
        pulse = 0.55 + 0.45 * abs(math.sin(time.time() * 3))
        d.rounded_rectangle([(BW // 2 - 175) * s, 250 * s, (BW // 2 + 175) * s, 296 * s], radius=12 * s,
                            outline=int(255 * pulse), width=3 * s, fill=int(60 * pulse))
        d.text((BW // 2 * s, 273 * s), alert, font=FONT, fill=255, anchor="mm")
    if status is not None:                      # busy: progress bar + elapsed timer
        el, prog = status
        bx0, bx1, by = 100 - X0, 330 - X0, 300
        d.rounded_rectangle([bx0 * s, (by - 5) * s, bx1 * s, (by + 5) * s], radius=5 * s, outline=170, width=s)
        if prog is None:                        # model still loading: sweeping block
            ph = (el * 0.9) % 2.0
            ph = ph if ph < 1 else 2 - ph
            w = 70
            x = bx0 + 3 + ph * (bx1 - bx0 - 6 - w)
            d.rounded_rectangle([x * s, (by - 3) * s, (x + w) * s, (by + 3) * s], radius=3 * s, fill=255)
        else:
            w = max(6, (bx1 - bx0 - 6) * min(1.0, prog))
            d.rounded_rectangle([(bx0 + 3) * s, (by - 3) * s, (bx0 + 3 + w) * s, (by + 3) * s], radius=3 * s, fill=255)
        d.text(((bx1 + 14) * s, by * s), f"{el:.1f}с", font=FONT, fill=230, anchor="lm")
    if caption:                                 # speech bubble: pops in, types out, shrinks away
        text, age, left = caption
        maxw, lines, cur_line = 345 * s, [], ""
        for word in text.split():
            trial = (cur_line + " " + word).strip()
            if d.textlength(trial, font=FONT) <= maxw or not cur_line:
                cur_line = trial
            else:
                lines.append(cur_line); cur_line = word
        lines.append(cur_line)
        if len(lines) > 3:
            lines = lines[:3]; lines[2] = lines[2].rstrip(".,!? ")[:-1] + "…"
        ease = lambda v: 1 - (1 - max(0.0, min(1.0, v))) ** 3
        pop = ease(age / 0.3) * ease(left / 0.3)
        if pop > 0.03:
            lh = 29
            bw = max(d.textlength(l, font=FONT) for l in lines) / s + 44
            bw = max(150, min(390, bw))
            bh = len(lines) * lh + 18
            mx0, top = BW // 2, 205
            cxb, cyb2 = mx0, top + bh / 2
            hw, hh = bw / 2 * pop, bh / 2 * pop
            r = min(18, hh)
            tail = 11 * pop
            ty = cyb2 - hh                                   # top edge of the bubble
            # tail pointing up at the face
            d.polygon([((cxb - 11 * pop) * s, (ty + 2) * s), (cxb * s, (ty - tail) * s), ((cxb + 11 * pop) * s, (ty + 2) * s)], fill=255)
            d.polygon([((cxb - 9 * pop) * s, (ty + 3) * s), (cxb * s, (ty - tail + 4) * s), ((cxb + 9 * pop) * s, (ty + 3) * s)], fill=30)
            d.rounded_rectangle([(cxb - hw) * s, ty * s, (cxb + hw) * s, (cyb2 + hh) * s], radius=r * s, fill=30, outline=255, width=2 * s)
            d.polygon([((cxb - 9 * pop) * s, (ty + 0.5) * s), (cxb * s, (ty - tail + 4) * s), ((cxb + 9 * pop) * s, (ty + 0.5) * s)], fill=30)
            if pop > 0.95:
                n = int(max(0.0, age - 0.25) * 45)          # typewriter, 45 chars/sec
                for i, ln in enumerate(lines):
                    shown = ln[:n]; n -= len(ln) + 1
                    if shown:
                        d.text((cxb * s - d.textlength(ln, font=FONT) / 2, (ty + 9 + i * lh + lh / 2) * s), shown, font=FONT, fill=240, anchor="lm")
                    if n <= 0:
                        break
    im = im.resize((BW, LH), Image.LANCZOS)
    g = np.rot90(np.asarray(im, dtype=np.uint8), ROT)
    col = np.array([p["cr"], p["cg"], p["cb"]], dtype=np.float32) / 255.0
    return (g[..., None].astype(np.float32) * col).astype(np.uint8)


def to565(rgb):
    r = (rgb[..., 0].astype(np.uint16) >> 3) << 11
    g = (rgb[..., 1].astype(np.uint16) >> 2) << 5
    b = rgb[..., 2].astype(np.uint16) >> 3
    return (r | g | b).astype("<u2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--pupil", type=int, default=1)
    ap.add_argument("--fps", type=float, default=20)
    a = ap.parse_args()

    fb = open("/dev/fb0", "r+b", buffering=0)
    fb.seek(0)
    fb.write(bytes(W * H * 2))              # clear screen to black
    stride = W * 2
    cur = dict(EMO["neutral"])
    emo = "neutral"
    tgt = dict(EMO["neutral"])
    look = None                              # manual gaze override
    next_blink = time.time() + 2
    blink_t0 = None
    next_sacc = time.time() + 1.5
    sacc = (0.0, 0.0)
    talk_phase = 0.0
    mouth = False
    busy_t0, prog = None, None
    caption, caption_until, caption_t0 = None, 0.0, 0.0
    track, track_t, track_es = None, 0.0, 1.0
    last_act, wake_until = time.time(), 0.0       # last sign of life (face, command); end of the "just woke up" look
    cfg = {"sleep": SLEEP_AFTER, "mirror": True}  # overridden by the menu settings
    cfg_t, ui_was = 0.0, False
    explicit_t0 = 0.0                         # last time an emotion was set by a command (bot/user)
    shape, pending_shape, last_emo = ("round", "round"), None, "neutral"
    anim, sleep_next, next_idle = None, False, time.time() + 30       # short scripted animations and idle behaviours
    nfr, nrows, fps_t0 = 0, 0, time.time()
    emo_t0 = time.time()
    demo_list = ["neutral", "happy", "talking", "angry", "sad", "thinking", "surprised", "sleepy"]
    demo_i, demo_next = 0, time.time() + 5
    prev = None
    dt = 1.0 / a.fps
    while True:
        t0 = time.time()
        if os.path.exists(UI_FLAG):                    # the touch menu is on screen: stay out of its way
            ui_was = True
            time.sleep(0.15)
            continue
        if ui_was:                                     # menu closed: wipe it and redraw the eyes
            ui_was = False
            fb.seek(0)
            fb.write(bytes(W * H * 2))
            prev = None
            last_act = t0
        if t0 - cfg_t > 5:                             # settings from the menu
            cfg_t = t0
            try:
                st = json.load(open(UI_SETTINGS))
                cfg["sleep"] = int(st.get("sleep_after_min", 1)) * 60
                cfg["mirror"] = bool(st.get("mood_mirror", True))
            except Exception:
                pass
        # commands
        try:
            if os.path.exists(CMD):
                last_act = t0
                c = open(CMD).read().strip().lower()
                os.remove(CMD)
                if c in EMO:
                    emo = c; tgt = dict(EMO[c]); look = None; emo_t0 = t0; explicit_t0 = t0
                elif c.startswith("look "):
                    look = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1), "center": None}.get(c[5:], None)
                elif c == "blink":
                    blink_t0 = t0
                elif c in ("roll", "scan", "yawn_only"):
                    anim = (c if c != "yawn_only" else "yawn", t0, {"roll": 2.4, "scan": 4.0}.get(c, 2.8))
                elif c in ("mouth on", "mouth off"):
                    mouth = c.endswith("on")
                elif c == "busy on":
                    busy_t0, prog = t0, None
                elif c == "busy off":
                    busy_t0 = None
                    if emo == "thinking":
                        emo = "neutral"; tgt = dict(EMO["neutral"]); emo_t0 = t0
                elif c.startswith("progress "):
                    try:
                        prog = float(c.split()[1])
                    except ValueError:
                        prog = None
        except Exception:
            pass
        try:
            if os.path.exists(GAZE):
                vals = [float(v) for v in open(GAZE).read().split()]
                os.remove(GAZE)
                track, track_t = (vals[0], vals[1]), t0
                last_act = t0
                track_es = vals[2] if len(vals) > 2 else 1.0
        except Exception:
            pass
        try:
            if os.path.exists(MOOD):                  # mirror the viewer's expression when nothing else is going on
                m_ = open(MOOD).read().strip().lower()
                os.remove(MOOD)
                if cfg["mirror"] and m_ in EMO and busy_t0 is None and not mouth and not caption and t0 - explicit_t0 > 20:
                    if m_ != emo:
                        emo = m_; tgt = dict(EMO[m_]); look = None
                    emo_t0 = t0
        except Exception:
            pass
        try:
            if os.path.exists(SAY):
                txt = open(SAY, encoding="utf-8").read().strip()
                os.remove(SAY)
                caption = txt or None
                caption_t0 = t0
                last_act = t0
                caption_until = t0 + max(6.0, 1.5 + len(txt) * 0.09)
        except Exception:
            pass
        if caption and t0 > caption_until:
            caption = None
        alert_text = warn_text = None
        try:
            if os.path.exists(ALERT):
                alert_text = open(ALERT, encoding="utf-8").read().strip() or "ТРИВОГА!"
            elif os.path.exists(WARN):
                warn_text = open(WARN, encoding="utf-8").read().strip() or "Поруч тривога"
        except OSError:
            pass
        want = "alert" if alert_text else ("warn" if warn_text else None)
        if want:                                     # an alert beats everything else, a warning beats sleep and moods
            last_act = explicit_t0 = t0
            if emo != want:
                emo = want; tgt = dict(EMO[want]); look = None
        elif emo in ("alert", "warn"):
            emo = "neutral"; tgt = dict(EMO["neutral"])
        alert_text = alert_text or warn_text         # the banner shows either text
        if emo not in ("sleeping", "yawn") and busy_t0 is None and not mouth and not caption and cfg["sleep"] and t0 - last_act > cfg["sleep"]:
            emo = "yawn"; tgt = dict(EMO["yawn"]); look = None; anim = ("yawn", t0, 2.8); sleep_next = True   # nobody around: yawn, then sleep
        elif emo == "sleeping" and t0 - last_act < 2.0:
            emo = "surprised"; tgt = dict(EMO["surprised"]); emo_t0 = t0   # someone is back: wake up
            wake_until = t0 + 1.8
        if wake_until and t0 > wake_until:
            wake_until = 0.0
            if emo == "surprised":
                emo = "neutral"; tgt = dict(EMO["neutral"])
        if a.demo and t0 > demo_next:
            demo_i = (demo_i + 1) % len(demo_list)
            emo = demo_list[demo_i]; tgt = dict(EMO[emo]); look = None
            demo_next = t0 + 5
        if emo not in ("neutral", "sleepy", "sleeping", "alert", "warn") and not wake_until and busy_t0 is None and not mouth and t0 - emo_t0 > 30:
            emo = "neutral"; tgt = dict(EMO["neutral"])      # emotions fade back to neutral
        # gaze: random saccades, unless emotion/look pins it
        if t0 > next_sacc:
            sacc = (random.uniform(-0.9, 0.9), random.uniform(-0.5, 0.5))
            next_sacc = t0 + random.uniform(1.2, 3.5)
        g = dict(tgt)
        g["cyo"] = -35 if (caption or alert_text) else 0
        g["es"] = 1.0 if (track is None or t0 - track_t >= 1.0) else track_es
        if caption:
            g["es"] = min(g["es"], 1.0)             # leave room for the bubble
        if look is not None:
            g["gx"], g["gy"] = look
        elif track is not None and emo != "thinking" and t0 - track_t < 1.0:
            g["gx"], g["gy"] = track                 # follow the face
        elif emo in ("neutral", "happy", "talking", "angry"):
            g["gx"] = tgt["gx"] + sacc[0] * (0.5 if emo == "angry" else 1.0)
            g["gy"] = tgt["gy"] + sacc[1] * 0.6
        elif emo in ("sad", "sleepy"):
            g["gx"] = tgt["gx"] + sacc[0] * 0.25
        if emo == "thinking":                         # "hmm": glance up to one side, then the other
            sg = 1 if int(t0 / 2.4) % 2 == 0 else -1
            g["gx"], g["gy"] = 0.8 * sg, -0.65
            g["bhr"], g["bhl"] = (0.95, 0.1) if sg > 0 else (0.1, 0.95)    # the brow on the glance side goes up
            g["btl"] = g["btr"] = 6
            g["mxs"] = sg * 26
            g["mc"] = -0.12 + 0.22 * math.sin(t0 * 2.6)                      # the lips fidget
        if emo == "yawn" and (anim is None or anim[0] != "yawn") and not sleep_next:
            anim = ("yawn", t0, 2.8)                  # the yawn emotion plays its own animation
        if emo == "neutral" and anim is None and not caption and busy_t0 is None and t0 > next_idle \
                and not (track is not None and t0 - track_t < 1.0):
            anim = (random.choice(["scan", "roll", "scan"]), t0, 0.0)       # idle: look around now and then
            anim = (anim[0], t0, 4.0 if anim[0] == "scan" else 2.4)
            next_idle = t0 + random.uniform(25, 60)
        if anim:
            kind_, a0, dur_ = anim
            ph = (t0 - a0) / dur_
            if ph >= 1:
                anim = None
                if kind_ == "yawn":
                    if sleep_next and cfg["sleep"] and t0 - last_act > cfg["sleep"] - 1:
                        emo = "sleeping"; tgt = dict(EMO["sleeping"])
                    elif emo == "yawn":
                        emo = "neutral"; tgt = dict(EMO["neutral"])
                    sleep_next = False
            elif kind_ == "roll":                    # eyes rolling: the pupils run a full circle, brows up
                ang = ph * 2 * math.pi - math.pi / 2
                g["gx"], g["gy"] = 0.95 * math.cos(ang), 0.95 * math.sin(ang)
                g["bb"], g["bhl"], g["bhr"] = 1.0, 0.7, 0.7
            elif kind_ == "scan":                    # look left, right, and back to the middle
                g["gx"], g["gy"] = [-0.9, -0.9, 0.9, 0.9, 0.0][min(4, int(ph * 5))], -0.1
            elif kind_ == "yawn":                    # eyes squeeze shut while the mouth opens wide
                g["open"] = 0.9 - 0.75 * math.sin(math.pi * ph)
                g["mo"] = math.sin(math.pi * ph) ** 0.7
                g["bb"], g["bhl"], g["bhr"] = 1.0, 0.5 * math.sin(math.pi * ph), 0.5 * math.sin(math.pi * ph)
        if emo == "laughing":
            g["mo"] = 0.55 + 0.45 * math.sin(t0 * 14)
        elif emo == "confused":
            g["mc"] = 0.35 * math.sin(t0 * 3)
        elif emo == "nervous":
            g["mc"] = -0.3 + 0.25 * math.sin(t0 * 9)
        elif emo == "sick":
            g["mc"] = -0.5 + 0.2 * math.sin(t0 * 2)
        # talking mouth
        if mouth or emo == "talking":
            talk_phase += 0.9
            g["mo"] = max(0.0, math.sin(talk_phase) * 0.5 + random.uniform(-0.1, 0.2)) * 0.9
        # smooth
        k = 0.28
        for key in KEYS:
            cur[key] += (g[key] - cur[key]) * (0.7 if key in ("cr", "cg", "cb") else k)   # colour follows the emotion fast
        if emo != last_emo:                          # new emotion with other eye shapes: swap them mid-blink
            last_emo = emo
            print(f"emotion -> {emo} (busy={busy_t0 is not None}, mouth={mouth})", flush=True)
            new = (tgt.get("sl", "round"), tgt.get("sr", "round"))
            pending_shape = new if new != shape else None
            if pending_shape and blink_t0 is None:
                blink_t0 = t0
        # blink
        if blink_t0 is None and t0 > next_blink and emo not in ("sleepy", "sleeping"):
            blink_t0 = t0
        blink = 1.0
        if blink_t0 is not None:
            x = (t0 - blink_t0) / 0.22
            if pending_shape is not None and x >= 0.5:
                shape, pending_shape = pending_shape, None
            if x >= 1:
                blink_t0 = None
                next_blink = t0 + random.uniform(2.0, 6.0)
                if random.random() < 0.15:
                    next_blink = t0 + 0.25   # double blink
            else:
                blink = abs(2 * x - 1)       # 1 -> 0 -> 1
        cur["sl"], cur["sr"] = shape
        status = (t0 - busy_t0, prog) if busy_t0 is not None else None
        if busy_t0 is not None and t0 - busy_t0 > 180:
            busy_t0 = None                       # safety: never stay busy forever
        frame = to565(render(cur, blink, bool(a.pupil), status, (caption, t0 - caption_t0, caption_until - t0) if caption else None, alert_text))
        # write only rows that changed since the previous frame, as separate bands
        if prev is None:
            bands = [(0, BH)]
        else:
            diff = np.nonzero((frame != prev).any(axis=1))[0]
            bands = []
            for r_ in diff:
                if bands and r_ - bands[-1][1] <= 12:     # merge bands closer than 12 rows
                    bands[-1][1] = int(r_) + 1
                else:
                    bands.append([int(r_), int(r_) + 1])
        for r0, r1 in bands:
            fb.seek((Y0 + r0) * stride)
            fb.write(frame[r0:r1].tobytes())
            nrows += r1 - r0
        prev = frame
        nfr += 1
        if t0 - fps_t0 >= 10:
            print(f"fps {nfr / (t0 - fps_t0):.1f}, rows written/frame avg {nrows / max(1, nfr):.0f}", flush=True)
            nfr, nrows, fps_t0 = 0, 0, t0
        sl = (1 / 8 if busy_t0 is not None else dt) - (time.time() - t0)      # fewer frames while the model needs the CPU
        if sl > 0:
            time.sleep(sl)


if __name__ == "__main__":
    main()

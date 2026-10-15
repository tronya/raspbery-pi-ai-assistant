import numpy as np
from PIL import Image, ImageDraw
S = 2
im = Image.new("RGB", (480 * S, 320 * S), (0, 0, 0))
d = ImageDraw.Draw(im)
# top row: white disc, orange disc, pure red, pure green, pure blue discs
for i, col in enumerate([(255, 255, 255), (255, 170, 40), (255, 0, 0), (0, 255, 0), (0, 0, 255)]):
    cx = 50 + i * 95
    d.ellipse([(cx - 40) * S, 20 * S, (cx + 40) * S, 100 * S], fill=col)
# middle: 1-px and 2-px white vertical lines on black, then horizontal ones (to see channel misalignment)
for k in range(12):
    d.line([((40 + k * 8) * S, 130 * S), ((40 + k * 8) * S, 190 * S)], fill=(255, 255, 255), width=S * (1 + k % 2))
for k in range(8):
    d.line([(300 * S, (130 + k * 8) * S), (440 * S, (130 + k * 8) * S)], fill=(255, 255, 255), width=S * (1 + k % 2))
# bottom: grey ramp and colour bars
for k in range(16):
    d.rectangle([(20 + k * 14) * S, 215 * S, (34 + k * 14) * S, 250 * S], fill=(k * 17, k * 17, k * 17))
for k, col in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (255, 255, 255)]):
    d.rectangle([(20 + k * 32) * S, 265 * S, (50 + k * 32) * S, 305 * S], fill=col)
img = np.rot90(np.asarray(im.resize((480, 320), Image.LANCZOS)), 1)        # same rotation as eyes.py
r = (img[..., 0].astype(np.uint16) >> 3) << 11
g = (img[..., 1].astype(np.uint16) >> 2) << 5
b = img[..., 2].astype(np.uint16) >> 3
open("/dev/fb0", "r+b", buffering=0).write((r | g | b).astype("<u2").tobytes())
print("pattern shown")

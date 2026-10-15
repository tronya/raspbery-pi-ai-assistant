import importlib.util, os, sys
sys.argv = ["x"]
spec = importlib.util.spec_from_file_location("eyes", "/home/tronyak/eyes.py")
e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)
from PIL import Image, ImageDraw
import numpy as np
names = [n for n in e.EMO if n not in ("alert", "warn", "sleeping", "talking")]
cols, w, h = 4, 360, 240
rows = (len(names) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * h), (40, 40, 40))
for i, n in enumerate(names):
    p = dict(e.EMO[n]); p["sl"], p["sr"] = p.get("sl", "round"), p.get("sr", "round")
    p["gx"], p["gy"] = p["gx"], p["gy"]
    arr = e.render(p, 1.0, True, None, None)                # (BH, 320, 3): rotated band
    full = np.zeros((480, 320, 3), np.uint8); full[e.Y0:e.Y0 + e.BH] = arr
    land = np.rot90(full, -1)                                # back to landscape
    img = Image.fromarray(np.ascontiguousarray(land)).resize((w - 6, h - 28))
    d = ImageDraw.Draw(img); 
    tile = Image.new("RGB", (w, h), (0, 0, 0)); tile.paste(img, (3, 22))
    ImageDraw.Draw(tile).text((8, 4), n, fill=(255, 255, 0))
    sheet.paste(tile, ((i % cols) * w, (i // cols) * h))
sheet.save("/tmp/emosheet.png"); print(len(names), "emotions rendered")

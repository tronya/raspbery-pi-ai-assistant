import numpy as np
from PIL import Image
raw = np.frombuffer(open("/dev/fb0", "rb").read(320 * 480 * 2), dtype="<u2").reshape(480, 320)
r = ((raw >> 11) & 31) * 255 // 31
g = ((raw >> 5) & 63) * 255 // 63
b = (raw & 31) * 255 // 31
img = np.rot90(np.stack([r, g, b], axis=-1).astype(np.uint8), -1)      # back to the landscape view
Image.fromarray(img).resize((960, 640), Image.NEAREST).save("/tmp/fbshot.png")
print("saved", img.shape, "mean RGB", img.reshape(-1, 3).mean(axis=0).round(1))

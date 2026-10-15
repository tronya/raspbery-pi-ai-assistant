#!/usr/bin/env python3
"""Live camera preview on the 320x480 RGB565 TFT (shown as 480x320 landscape).

rpicam-vid (MJPEG) -> latest frame -> rotate -> RGB565 -> /dev/fb0
Usage: sudo python3 camview.py [--flip] [--mirror] [--fps 10]
"""
import argparse, io, subprocess, threading, time
import cv2
import numpy as np
from PIL import Image, ImageDraw

LW, LH = 480, 320
ROT = 1            # same direction as eyes.py (np.rot90 k)
TUNING = "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"

ap = argparse.ArgumentParser()
ap.add_argument("--flip", action="store_true", help="rotate the picture 180 degrees")
ap.add_argument("--mirror", action="store_true", help="mirror left/right")
ap.add_argument("--no-face", action="store_true", help="disable face box")
ap.add_argument("--fps", type=int, default=10)
a = ap.parse_args()

cmd = ["rpicam-vid", "-t", "0", "--nopreview", "--codec", "mjpeg", "-n",
       "--width", str(LW), "--height", str(LH), "--framerate", str(a.fps),
       "--mode", "1640:1232", "--tuning-file", TUNING, "-o", "-"]    # 1640x1232 = full field of view
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

latest = [None]
lock = threading.Lock()


def reader():
    buf = b""
    while True:
        chunk = proc.stdout.read(65536)
        if not chunk:
            break
        buf += chunk
        while True:
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
            if s < 0 or e < 0:
                if s > 0:
                    buf = buf[s:]
                break
            with lock:
                latest[0] = buf[s:e + 2]
            buf = buf[e + 2:]


threading.Thread(target=reader, daemon=True).start()

# --- face detection runs in its own thread on a small grayscale copy ---
cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
DS = 2                                   # detect on a half-size image
face = {"box": None, "seen": 0.0}        # box in full-frame pixels (x, y, w, h)
gray_in = [None]


def detector():
    while True:
        g = gray_in[0]
        if g is None:
            time.sleep(0.02)
            continue
        gray_in[0] = None
        found = cascade.detectMultiScale(g, scaleFactor=1.15, minNeighbors=5, minSize=(22, 22))
        if len(found):
            x, y, w, h = max(found, key=lambda f: f[2] * f[3])
            new = np.array([x, y, w, h], dtype=np.float32) * DS
            old = face["box"]
            face["box"] = new if old is None else old * 0.5 + new * 0.5      # smooth jitter
            face["seen"] = time.time()


if not a.no_face:
    threading.Thread(target=detector, daemon=True).start()
fb = open("/dev/fb0", "r+b", buffering=0)
shown = None
try:
    while proc.poll() is None:
        with lock:
            jpg, latest[0] = latest[0], None
        if jpg is None:
            time.sleep(0.01)
            continue
        im = Image.open(io.BytesIO(jpg)).convert("RGB")
        if im.size != (LW, LH):
            im = im.resize((LW, LH))
        if a.flip:
            im = im.rotate(180)
        if a.mirror:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        if not a.no_face:
            if gray_in[0] is None:
                gray_in[0] = np.asarray(im.convert("L").resize((LW // DS, LH // DS)))
            if face["box"] is not None and time.time() - face["seen"] < 0.6:
                x, y, w, h = face["box"]
                d = ImageDraw.Draw(im)
                d.rectangle([x, y, x + w, y + h], outline=(0, 255, 90), width=3)
        arr = np.rot90(np.asarray(im), ROT)
        r = (arr[..., 0].astype(np.uint16) >> 3) << 11
        g = (arr[..., 1].astype(np.uint16) >> 2) << 5
        b = arr[..., 2].astype(np.uint16) >> 3
        fb.seek(0)
        fb.write((r | g | b).astype("<u2").tobytes())
finally:
    proc.terminate()

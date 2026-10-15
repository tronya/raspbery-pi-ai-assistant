#!/usr/bin/env python3
"""Face tracker: camera -> face position -> /tmp/eyes_gaze ("x y", both -1..1).

x > 0: the person is on the right of the screen (as the viewer sees it), y < 0: up.
eyes.py reads the file, makes the eyes look there and releases the gaze when it
stops being updated (about 1 s after the face disappears).
Usage: python3 track.py [--invert-x] [--invert-y] [--fps 10]
"""
import argparse, os, subprocess, time
import cv2
import numpy as np

cv2.setNumThreads(2)                  # leave CPU for the eyes and the language model

GAZE, GAZE_TMP = "/tmp/eyes_gaze", "/tmp/.eyes_gaze.tmp"
MOOD, MOOD_TMP = "/tmp/eyes_mood", "/tmp/.eyes_mood.tmp"
W, H = 320, 240
TUNING = "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"

ap = argparse.ArgumentParser()
ap.add_argument("--invert-x", action="store_true")
ap.add_argument("--invert-y", action="store_true")
ap.add_argument("--fps", type=int, default=10)
ap.add_argument("--ev", type=float, default=1.5, help="exposure compensation, brighter in the dark")
ap.add_argument("--log-mood", action="store_true", help="print emotion probabilities to the journal")
ap.add_argument("--debug", action="store_true", help="save the last frame to /tmp/track_last.jpg every 2 s")
a = ap.parse_args()

MODEL = os.path.expanduser("~/models/face_detection_yunet_2023mar.onnx")
detector = cv2.FaceDetectorYN.create(MODEL, "", (W, H), 0.5, 0.3, 5000)   # YuNet: robust to angle and dim light
cmd = ["rpicam-vid", "-t", "0", "--nopreview", "-n", "--codec", "mjpeg",
       "--width", str(2 * W), "--height", str(2 * H), "--framerate", str(a.fps),
       "--mode", "1640:1232", "--ev", str(a.ev), "--denoise", "cdn_off", "--tuning-file", TUNING, "-o", "-"]
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)


FER_MODEL = os.path.expanduser("~/models/emotion-ferplus-8.onnx")
fer = cv2.dnn.readNetFromONNX(FER_MODEL)            # FER+: runs locally, frames are never stored or sent
LABELS = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]
# per-emotion thresholds: a resting face already reads ~0.2 "sadness", while a real smile peaks at ~0.25 "happiness"
THR = {"happiness": 0.32, "surprise": 0.22, "sadness": 0.55, "anger": 0.35, "disgust": 0.40, "fear": 0.35, "contempt": 0.45}
MAP = {"neutral": "neutral", "happiness": "happy", "surprise": "surprised", "sadness": "sad",
       "anger": "angry", "disgust": "suspicious", "fear": "scared", "contempt": "suspicious"}


def publish_mood(m):
    with open(MOOD_TMP, "w") as f:
        f.write(m)
    os.replace(MOOD_TMP, MOOD)


def publish(x, y, sc):
    with open(GAZE_TMP, "w") as f:
        f.write(f"{x:.3f} {y:.3f} {sc:.3f}")
    os.replace(GAZE_TMP, GAZE)


buf, pos, last_seen, last_dbg = b"", None, 0.0, 0.0
last_presence = 0.0
ema, cand, cand_n, mood, last_fer, last_mood_pub = None, None, 0, "neutral", 0.0, 0.0
try:
    while True:
        chunk = proc.stdout.read(65536)
        if not chunk:
            break
        if os.path.exists("/tmp/eyes_pause"):          # the language model is answering: free the CPU for it
            buf = b""
            continue
        buf += chunk
        frame = None
        while True:                                  # keep only the newest complete frame
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2) if s >= 0 else -1
            if s < 0 or e < 0:
                if s > 0:
                    buf = buf[s:]
                break
            frame, buf = buf[s:e + 2], buf[e + 2:]
        if frame is None:
            continue
        gray = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
        if gray is None:
            continue
        full = gray                                   # 640x480 frame, used for the expression crop
        gray = cv2.resize(full, (W, H), interpolation=cv2.INTER_AREA)   # 320x240 for the face detector
        _, found = detector.detect(gray)
        faces = [] if found is None else [tuple(map(float, f[:4])) for f in found]
        if a.debug and time.time() - last_dbg > 2:
            last_dbg = time.time()
            vis = gray.copy()
            for (fx, fy, fw, fh) in faces:
                cv2.rectangle(vis, (int(fx), int(fy)), (int(fx + fw), int(fy + fh)), (0, 255, 0), 2)
            cv2.imwrite("/tmp/track_last.jpg", vis)
        if len(faces) == 0:
            if time.time() - last_seen > 1.0:
                ema, cand, cand_n = None, None, 0
                pos = None                           # eyes release the gaze on their own
            continue
        last_seen = time.time()
        if last_seen - last_presence > 1.0:                # tell worktime.py that somebody is at the desk
            with open("/tmp/.eyes_presence.tmp", "w") as f:
                f.write(str(last_seen))
            os.replace("/tmp/.eyes_presence.tmp", "/tmp/eyes_presence")
            last_presence = last_seen
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        xn, yn = (x + w / 2) / W, (y + h / 2) / H
        gx = max(-1.0, min(1.0, (0.5 - xn) * 2 * 2.0))   # person on the camera's left -> look right
        gy = max(-1.0, min(1.0, (yn - 0.5) * 2 * 1.7))
        if a.invert_x:
            gx = -gx
        if a.invert_y:
            gy = -gy
        # closer face -> bigger on the picture -> bigger eyes (1.0 at about a desk distance)
        sc = max(0.75, min(1.12, 1.0 + (w / W - 0.12) * 2.2))
        now = time.time()
        if now - last_fer > 0.25:                      # read the expression ~4 times a second
            last_fer = now
            mg = 0.15 * w
            x0, y0, x1, y1 = max(0, int(x - mg)), max(0, int(y - mg)), min(W, int(x + w + mg)), min(H, int(y + h + mg))
            crop = full[2 * y0:2 * y1, 2 * x0:2 * x1]
            if crop.size:
                crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                fer.setInput(cv2.resize(crop, (64, 64)).astype(np.float32).reshape(1, 1, 64, 64))
                o = fer.forward()[0]
                e = np.exp(o - o.max())
                pr = e / e.sum()
                ema = pr if ema is None else 0.6 * ema + 0.4 * pr
                top = int(ema.argmax())
                best = max(range(1, 8), key=lambda k: ema[k] / THR[LABELS[k]])
                name = MAP[LABELS[best]] if ema[best] > THR[LABELS[best]] else "neutral"
                cand, cand_n = (name, cand_n + 1) if name == cand else (name, 1)
                if a.log_mood:
                    print(" ".join(f"{LABELS[k][:4]}={ema[k]:.2f}" for k in range(8)), "->", cand, cand_n, flush=True)
                if cand_n >= 3 and cand != mood:       # stable for ~0.75 s
                    mood = cand
                    publish_mood(mood)
                    last_mood_pub = now
                elif mood != "neutral" and now - last_mood_pub > 2:
                    publish_mood(mood)                 # keep the emotion alive while it lasts
                    last_mood_pub = now
        new = np.array([gx, gy, sc])
        pos = new if pos is None else pos * 0.4 + new * 0.6   # light smoothing
        publish(*pos)
finally:
    proc.terminate()

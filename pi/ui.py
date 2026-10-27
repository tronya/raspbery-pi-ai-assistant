#!/usr/bin/env python3
"""Touch menu for the 3.5" TFT (480x320 landscape, XPT2046 touch).

Runs as root. While the menu is open it creates /tmp/ui_active; eyes.py then stops drawing and,
when the flag disappears, clears the screen and draws the eyes again.
Tap anywhere on the eyes -> menu. Screens: Marstek, Camera, System, Work, Settings.
"""
import io, json, os, queue, sqlite3, statistics, subprocess, threading, time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import evdev
except ImportError:
    raise SystemExit("python3-evdev is needed")

LW, LH = 480, 320
FLAG = "/tmp/ui_active"
HOME = "/home/tronyak"
CAL = os.path.join(HOME, "touch_cal.json")
SET = os.path.join(HOME, "ui_settings.json")
DB = os.path.join(HOME, "marstek.db")
IDLE_S = 40                      # back to the eyes after this long without a touch
CAMERA_MAX_S = 180
PARTICLES_MAX_S = 900
PX0, PX1, PY0, PW = 128, 352, 48, 224     # the particle picture: 224x224 px in the middle of the screen
ROT = 1                          # same rotation as eyes.py

BG, TILE, TILE2 = (12, 14, 22), (30, 36, 54), (44, 52, 76)
TXT, DIM = (236, 238, 245), (140, 148, 168)
ACC, GRN, ORG, RED = (80, 170, 255), (70, 205, 115), (255, 170, 40), (255, 75, 65)
FD = "/usr/share/fonts/truetype/dejavu/"


def font(size, bold=False):
    return ImageFont.truetype(FD + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)


F12, F14, F16, F20, F26, F60 = font(12), font(14), font(16), font(20, True), font(26, True), font(60, True)


# ------------------------------------------------------------------ helpers
def run(*cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def load_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def save_json(path, data):
    json.dump(data, open(path, "w"))


def show(img):
    """PIL RGB 480x320 -> RGB565, rotated like eyes.py, written to the framebuffer."""
    arr = np.rot90(np.asarray(img), ROT)
    r = (arr[..., 0].astype(np.uint16) >> 3) << 11
    g = (arr[..., 1].astype(np.uint16) >> 2) << 5
    b = arr[..., 2].astype(np.uint16) >> 3
    with open("/dev/fb0", "r+b", buffering=0) as fb:
        fb.write((r | g | b).astype("<u2").tobytes())


def clear_screen():
    with open("/dev/fb0", "r+b", buffering=0) as fb:
        fb.write(bytes(320 * 480 * 2))


# ------------------------------------------------------------------ touch
class Touch(threading.Thread):
    """Collects raw (x, y) of every finished touch into a queue."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        dev = next((evdev.InputDevice(p) for p in evdev.list_devices() if "ADS7846" in evdev.InputDevice(p).name), None)
        if dev is None:
            raise SystemExit("touch controller not found")
        self.dev = dev

    def run(self):
        x = y = None
        down, samples = False, []
        for e in self.dev.read_loop():
            if e.type == evdev.ecodes.EV_ABS:
                if e.code == evdev.ecodes.ABS_X:
                    x = e.value
                elif e.code == evdev.ecodes.ABS_Y:
                    y = e.value
                if down and x is not None and y is not None:
                    samples.append((x, y))
            elif e.type == evdev.ecodes.EV_KEY and e.code == evdev.ecodes.BTN_TOUCH:
                if e.value:
                    down, samples = True, []
                else:
                    down = False
                    if len(samples) >= 3:
                        s = samples[len(samples) // 4:]                       # skip the unstable start
                        self.q.put((statistics.median(p[0] for p in s), statistics.median(p[1] for p in s)))


# ------------------------------------------------------------------ data sources
def marstek():
    try:
        db = sqlite3.connect("file:" + DB + "?mode=ro", uri=True, timeout=3)
        now = time.time()
        full = db.execute("SELECT ts,soc,cap_wh,temp_c,load_w,grid_w,pv_w,mode,rssi FROM samples WHERE soc IS NOT NULL ORDER BY ts DESC LIMIT 1").fetchone()
        rich = db.execute("SELECT cap_wh,mode,rssi FROM samples WHERE cap_wh IS NOT NULL ORDER BY ts DESC LIMIT 1").fetchone()
        series = db.execute("SELECT ts,soc FROM samples WHERE soc IS NOT NULL AND ts>? ORDER BY ts", (now - 86400,)).fetchall()
        if not full:
            return None
        return {"age": now - full[0], "soc": full[1], "cap": rich[0] if rich else full[2], "temp": full[3], "load": full[4],
                "grid": full[5], "pv": full[6], "mode": (rich[1] if rich else None) or full[7], "rssi": rich[2] if rich else None,
                "series": series}
    except Exception:
        return None


def uptime_uk():
    s = int(float(open("/proc/uptime").read().split()[0]))
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (f"{d} д " if d else "") + (f"{h} г " if h or d else "") + f"{m} хв"


def sysinfo():
    mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
    disk = run("df", "-h", "/").splitlines()[-1].split()
    svcs = {s: run("systemctl", "is-active", s) == "active"
            for s in ("ollama", "eyes", "eyetrack", "eyes-bot", "alertwatch", "worktime", "marstek-logger")}
    return {"temp": run("vcgencmd", "measure_temp").replace("temp=", ""), "load": open("/proc/loadavg").read().split()[:3],
            "ram": (mem["MemTotal"] - mem["MemAvailable"]) // 1024, "ram_t": mem["MemTotal"] // 1024,
            "disk": disk[4], "up": uptime_uk(), "svcs": svcs,
            "alert": os.path.exists("/tmp/eyes_alert"), "warn": os.path.exists("/tmp/eyes_warn")}


# ------------------------------------------------------------------ drawing primitives
def new():
    im = Image.new("RGB", (LW, LH), BG)
    return im, ImageDraw.Draw(im)


def header(d, title, back=True):
    d.rectangle([0, 0, LW, 44], fill=TILE)
    if back:
        d.polygon([(22, 22), (34, 12), (34, 32)], fill=TXT)
    d.text((54 if back else 16, 22), title, font=F20, fill=TXT, anchor="lm")
    return [((0, 0, 70, 44), "back")] if back else []


def button(d, rect, label, fill=TILE2, color=TXT, f=F16):
    d.rounded_rectangle(rect, radius=10, fill=fill)
    d.text(((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2), label, font=f, fill=color, anchor="mm")


def icon(d, kind, cx, cy, c=ACC):
    if kind == "battery":
        d.rounded_rectangle([cx - 24, cy - 13, cx + 20, cy + 13], radius=4, outline=c, width=3)
        d.rectangle([cx + 20, cy - 5, cx + 25, cy + 5], fill=c)
        d.rectangle([cx - 19, cy - 8, cx + 4, cy + 8], fill=c)
    elif kind == "camera":
        d.rounded_rectangle([cx - 24, cy - 14, cx + 24, cy + 16], radius=6, outline=c, width=3)
        d.ellipse([cx - 10, cy - 8, cx + 10, cy + 12], outline=c, width=3)
        d.rectangle([cx - 10, cy - 20, cx + 2, cy - 14], fill=c)
    elif kind == "system":
        d.rounded_rectangle([cx - 18, cy - 18, cx + 18, cy + 18], radius=4, outline=c, width=3)
        d.rectangle([cx - 8, cy - 8, cx + 8, cy + 8], fill=c)
        for k in (-10, 0, 10):
            d.line([cx + k, cy - 24, cx + k, cy - 18], fill=c, width=3)
            d.line([cx + k, cy + 18, cx + k, cy + 24], fill=c, width=3)
    elif kind == "work":
        d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], outline=c, width=3)
        d.line([cx, cy, cx, cy - 12], fill=c, width=3)
        d.line([cx, cy, cx + 9, cy + 5], fill=c, width=3)
    elif kind == "settings":
        for k, v in ((-12, -6), (0, 8), (12, -2)):
            d.line([cx - 20, cy + k, cx + 20, cy + k], fill=c, width=3)
            d.ellipse([cx + v - 5, cy + k - 5, cx + v + 5, cy + k + 5], fill=c)
    elif kind == "emotions":
        d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], outline=c, width=3)
        d.ellipse([cx - 11, cy - 9, cx - 5, cy - 3], fill=c)
        d.ellipse([cx + 5, cy - 9, cx + 11, cy - 3], fill=c)
        d.arc([cx - 12, cy - 4, cx + 12, cy + 14], 20, 160, fill=c, width=3)
    elif kind == "particles":
        for dx, dy, col in ((-9, 6, (90, 255, 235)), (10, 6, (255, 200, 70)), (0, -9, (235, 235, 245))):
            d.ellipse([cx + dx - 13, cy + dy - 13, cx + dx + 13, cy + dy + 13], outline=col, width=3)
            d.ellipse([cx + dx - 2, cy + dy - 2, cx + dx + 2, cy + dy + 2], fill=col)
    elif kind == "eyes":
        for dx in (-13, 13):
            d.ellipse([cx + dx - 11, cy - 15, cx + dx + 11, cy + 15], outline=c, width=3)
            d.ellipse([cx + dx - 4, cy - 4, cx + dx + 4, cy + 4], fill=c)


# ------------------------------------------------------------------ the app
class App:
    def __init__(self):
        self.touch = Touch()
        self.touch.start()
        self.cal = load_json(CAL, None)
        self.settings = {"sleep_after_min": 1, "mood_mirror": True, **load_json(SET, {})}
        self.screen, self.buttons = "eyes", []
        self.last_touch, self.entered = 0.0, 0.0
        self.cal_step, self.cal_raw = 0, []
        self.cam = None
        self.cache = {}
        self.confirm = None
        try:
            os.remove(FLAG)
        except OSError:
            pass

    # ---- coordinates
    def to_screen(self, raw):
        if not self.cal:
            return None
        a = np.array(self.cal)
        x, y = np.array([raw[0], raw[1], 1.0]) @ a
        return float(min(LW - 1, max(0, x))), float(min(LH - 1, max(0, y)))

    def calibrate(self, raws):
        targets = [(40, 40), (440, 40), (440, 280), (40, 280)]
        R = np.array([[r[0], r[1], 1.0] for r in raws])
        T = np.array(targets, dtype=float)
        sol, *_ = np.linalg.lstsq(R, T, rcond=None)
        self.cal = sol.tolist()
        save_json(CAL, self.cal)

    # ---- state changes
    def go(self, screen):
        if self.screen == "camera" and screen != "camera":
            self.stop_camera()
        self.screen, self.entered, self.cache = screen, time.time(), {}
        if screen == "eyes":
            self.buttons = []
            try:
                os.remove(FLAG)
            except OSError:
                pass
            return
        open(FLAG, "w").close()
        if screen == "camera":
            self.start_camera()
        elif screen == "particles":
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import particles                                  # imported late: numpy-heavy, only needed here
            self.scene = particles.Scene(PW)
            im = Image.new("RGB", (LW, LH), (0, 0, 0))          # black screen with a back button; later only the middle is redrawn
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([8, 8, 76, 48], radius=10, fill=TILE)
            d.polygon([(26, 28), (40, 16), (40, 40)], fill=TXT)
            d.text((46, 28), "назад", font=F12, fill=TXT, anchor="lm")
            show(im)
            self.buttons = [((0, 0, 90, 60), "back")]

    def set_setting(self, key, value):
        self.settings[key] = value
        save_json(SET, self.settings)

    # ---- camera
    def start_camera(self):
        self.track_was_on = run("systemctl", "is-active", "eyetrack") == "active"
        run("systemctl", "stop", "eyetrack")                # the tracker owns the camera otherwise
        self.latest, self.cam_lock = [None], threading.Lock()
        self.cam = subprocess.Popen(
            ["rpicam-vid", "-t", "0", "--nopreview", "-n", "--codec", "mjpeg", "--width", "480", "--height", "320",
             "--framerate", "10", "--mode", "1640:1232", "--tuning-file", "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json",
             "-o", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

        def reader():
            buf = b""
            while self.cam and self.cam.poll() is None:
                chunk = self.cam.stdout.read(65536)
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
                    with self.cam_lock:
                        self.latest[0] = buf[s:e + 2]
                    buf = buf[e + 2:]

        threading.Thread(target=reader, daemon=True).start()

    def stop_camera(self):
        if self.cam:
            self.cam.terminate()
            try:
                self.cam.wait(timeout=5)
            except Exception:
                self.cam.kill()
            self.cam = None
        if getattr(self, "track_was_on", True):
            run("systemctl", "start", "eyetrack")

    # ---- screens (each returns a PIL image and fills self.buttons)
    def draw_home(self):
        im, d = new()
        d.text((16, 22), "Меню", font=F20, fill=TXT, anchor="lm")
        d.text((LW - 16, 22), time.strftime("%H:%M"), font=F20, fill=DIM, anchor="rm")
        tiles = [("battery", "Marstek", "marstek"), ("camera", "Камера", "camera"), ("system", "Система", "system"),
                 ("work", "Робота", "work"), ("emotions", "Емоції", "emotions"), ("particles", "Частинки", "particles"),
                 ("settings", "Налаштув.", "settings"), ("eyes", "Очі", "eyes")]
        self.buttons = []
        for i, (ic, label, target) in enumerate(tiles):
            col, row = i % 4, i // 4
            x0, y0 = 8 + col * 118, 52 + row * 128
            rect = (x0, y0, x0 + 110, y0 + 118)
            d.rounded_rectangle(rect, radius=14, fill=TILE)
            icon(d, ic, x0 + 55, y0 + 46)
            d.text((x0 + 55, y0 + 94), label, font=F14, fill=TXT, anchor="mm")
            self.buttons.append((rect, target))
        return im

    def draw_marstek(self):
        im, d = new()
        self.buttons = header(d, "Marstek")
        if "m" not in self.cache or time.time() - self.cache.get("t", 0) > 2:
            self.cache = {"t": time.time(), "m": marstek()}
        m = self.cache.get("m")
        if not m:
            d.text((LW // 2, 160), "Немає даних від батареї", font=F20, fill=DIM, anchor="mm")
            return im
        soc = m["soc"] or 0
        col = GRN if soc >= 50 else ORG if soc >= 20 else RED
        d.rounded_rectangle([20, 62, 250, 150], radius=14, outline=TXT, width=4)
        d.rectangle([250, 90, 260, 122], fill=TXT)
        d.rounded_rectangle([26, 68, 26 + int(218 * min(100, soc) / 100), 144], radius=9, fill=col)
        d.text((135, 106), f"{soc:g}%", font=F60, fill=(255, 255, 255) if soc > 30 else TXT, anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
        rows = [("Режим", m["mode"] or "—"), ("Навантаження", f"{m['load']:g} Вт" if m["load"] is not None else "—"),
                ("Мережа", f"{m['grid']:g} Вт" if m["grid"] is not None else "—"),
                ("Сонце", f"{m['pv']:g} Вт" if m["pv"] is not None else "—"),
                ("Температура", f"{m['temp']:g} °C" if m["temp"] is not None else "—")]
        for i, (k, v) in enumerate(rows):
            y = 62 + i * 18
            d.text((278, y), k, font=F14, fill=DIM)
            d.text((LW - 14, y), v, font=F14, fill=TXT, anchor="ra")
        d.text((20, 160), f"{m['cap']:g} із 2009 Вт·год" if m["cap"] else "", font=F14, fill=DIM)
        if m["age"] > 120:
            d.text((LW - 14, 160), f"дані {int(m['age'] // 60)} хв тому", font=F14, fill=ORG, anchor="ra")
        # last 24 h
        d.text((20, 192), "Заряд за 24 години", font=F14, fill=DIM)
        d.rounded_rectangle([20, 212, LW - 20, 300], radius=8, fill=TILE)
        pts = m["series"]
        if len(pts) > 1:
            t1, t0 = pts[-1][0], max(pts[0][0], pts[-1][0] - 86400)
            xy = [(24 + (p[0] - t0) / max(1, t1 - t0) * (LW - 48), 296 - (p[1] / 100) * 80) for p in pts[:: max(1, len(pts) // 160)]]
            d.line(xy, fill=ACC, width=2)
        for pct in (0, 50, 100):
            y = 296 - pct / 100 * 80
            d.line([20, y, 26, y], fill=DIM)
        return im

    def draw_system(self):
        im, d = new()
        self.buttons = header(d, "Система")
        if "s" not in self.cache or time.time() - self.cache.get("t", 0) > 3:
            self.cache = {"t": time.time(), "s": sysinfo()}
        s = self.cache["s"]
        t = float(s["temp"].replace("'C", "") or 0)
        rows = [("Температура", s["temp"].replace("'C", " °C"), GRN if t < 60 else ORG if t < 75 else RED),
                ("Load", " ".join(x[:4] for x in s["load"]), TXT),
                ("Пам'ять", f"{s['ram']}/{s['ram_t']} МБ", TXT), ("Диск", s["disk"], TXT), ("Працює", s["up"], TXT)]
        for i, (k, v, c) in enumerate(rows):
            d.text((16, 58 + i * 28), k, font=F14, fill=DIM)
            d.text((244, 58 + i * 28), v, font=F14, fill=c, anchor="ra")
        names = {"ollama": "модель", "eyes": "очі", "eyetrack": "трекер", "eyes-bot": "бот", "alertwatch": "тривоги",
                 "worktime": "робота", "marstek-logger": "Marstek"}
        for i, (k, ok) in enumerate(s["svcs"].items()):
            y = 58 + i * 22
            d.ellipse([272, y, 284, y + 12], fill=GRN if ok else RED)
            d.text((294, y + 6), names.get(k, k), font=F14, fill=TXT, anchor="lm")
        status = "ТРИВОГА!" if s["alert"] else ("Тривога поруч" if s["warn"] else "Тривог немає")
        d.rounded_rectangle([14, 236, LW - 14, 292], radius=10, fill=(90, 28, 28) if s["alert"] else (80, 54, 14) if s["warn"] else TILE)
        d.text((LW // 2, 264), status.replace("🚨 ", ""), font=F20, fill=TXT, anchor="mm")
        return im

    def draw_work(self):
        im, d = new()
        self.buttons = header(d, "Робота")
        st = load_json("/tmp/worktime_state.json", None)
        if not st:
            d.text((LW // 2, 160), "Немає даних", font=F20, fill=DIM, anchor="mm")
            return im
        now = time.time()
        fmt = lambda s: f"{int(s // 3600)} г {int(s % 3600 // 60)} хв" if s >= 3600 else f"{int(s // 60)} хв"
        working = st["mode"] == "work"
        d.rounded_rectangle([14, 56, LW - 14, 150], radius=14, fill=TILE)
        d.text((LW // 2, 80), "Зараз працюєте" if working else "Перерва", font=F16, fill=DIM, anchor="mm")
        cur = (now - st["session_start"]) if working else (now - st["since"] if st.get("since") else 0)
        d.text((LW // 2, 118), fmt(cur) if cur else "—", font=F26, fill=GRN if working else ORG, anchor="mm")
        total = st["today_work_s"] + (now - st["session_start"] if working else 0)
        d.rounded_rectangle([14, 162, 236, 250], radius=14, fill=TILE)
        d.text((125, 186), "Сьогодні", font=F14, fill=DIM, anchor="mm")
        d.text((125, 220), fmt(total), font=F20, fill=TXT, anchor="mm")
        d.rounded_rectangle([244, 162, LW - 14, 250], radius=14, fill=TILE)
        d.text((362, 186), "Сесій", font=F14, fill=DIM, anchor="mm")
        d.text((362, 220), str(st["today_sessions"] + (1 if working else 0)), font=F20, fill=TXT, anchor="mm")
        bar = min(1.0, total / (8 * 3600))
        d.rounded_rectangle([14, 268, LW - 14, 286], radius=9, fill=TILE)
        d.rounded_rectangle([14, 268, 14 + max(18, int((LW - 28) * bar)), 286], radius=9, fill=ACC)
        d.text((LW // 2, 303), "ціль 8 годин", font=F12, fill=DIM, anchor="mm")
        return im

    def draw_settings(self):
        im, d = new()
        self.buttons = header(d, "Налаштування")
        if "track" not in self.cache or time.time() - self.cache.get("t", 0) > 2:
            self.cache = {"t": time.time(), "track": run("systemctl", "is-active", "eyetrack") == "active"}
        track = self.cache["track"]
        rows = [("Стеження за обличчям", track, "track"), ("Дзеркало емоцій", self.settings["mood_mirror"], "mirror")]
        for i, (label, on, key) in enumerate(rows):
            y = 54 + i * 46
            d.rounded_rectangle([14, y, LW - 14, y + 40], radius=10, fill=TILE)
            d.text((28, y + 20), label, font=F16, fill=TXT, anchor="lm")
            d.rounded_rectangle([LW - 90, y + 8, LW - 26, y + 32], radius=12, fill=GRN if on else TILE2)
            d.text((LW - 58, y + 20), "ВКЛ" if on else "ВИКЛ", font=F14, fill=(255, 255, 255), anchor="mm")
            self.buttons.append(((14, y, LW - 14, y + 40), "toggle_" + key))
        y = 146
        mins = self.settings["sleep_after_min"]
        d.rounded_rectangle([14, y, LW - 14, y + 40], radius=10, fill=TILE)
        d.text((28, y + 20), "Очі засинають через", font=F16, fill=TXT, anchor="lm")
        d.rounded_rectangle([LW - 110, y + 8, LW - 26, y + 32], radius=12, fill=ACC)
        d.text((LW - 68, y + 20), f"{mins} хв" if mins else "ніколи", font=F14, fill=(10, 10, 10), anchor="mm")
        self.buttons.append(((14, y, LW - 14, y + 40), "cycle_sleep"))
        for i, (label, tag, fill) in enumerate([("Калібрувати тач", "recal", TILE2), ("Перезавантажити", "ask_reboot", (110, 70, 20)),
                                                ("Вимкнути Pi", "ask_off", (120, 36, 36))]):
            x0 = 14 + i * 154
            button(d, (x0, 206, x0 + 144, 270), label, fill=fill, f=F14)
            self.buttons.append(((x0, 206, x0 + 144, 270), tag))
        return im

    EMOS = [("neutral", "Спокій"), ("happy", "Радість"), ("joy", "Сміх ^^"), ("laughing", "Регіт"), ("love", "Кохання"),
            ("excited", "Захват"), ("wink", "Підморг"), ("smug", "Самовпевн."), ("curious", "Цікавий"), ("thinking", "Думає"),
            ("confused", "Збентежен."), ("surprised", "Здивован."), ("scared", "Страх"), ("nervous", "Нервує"), ("sad", "Сум"),
            ("cry", "Плаче"), ("embarrassed", "Ніяково"), ("angry", "Злість"), ("evil", "Підступний"), ("determined", "Рішучий"),
            ("suspicious", "Підозра"), ("bored", "Нудьга"), ("sleepy", "Сонний"), ("sick", "Нездужає"), ("dizzy", "Паморочиться"),
            ("dead", "Мертвий"), ("pain", "Біль"), ("money", "Гроші"),
            ("roll", "Закотити очі"), ("scan", "Роззирнутись"), ("blink", "Кліпнути"), ("yawn", "Позіхнути"),
            ("peek", "Підглянути"), ("wiggle", "Крутнути"), ("dtake", "Глянути двічі"), ("squint", "Примружитись"),
            ("browup", "Брова вгору"), ("tilt", "Нахилити"), ("slowblink", "Повільно"), ("droop", "Задрімати")]

    def draw_emotions(self):
        im, d = new()
        pages = (len(self.EMOS) + 19) // 20
        page = self.cache.get("page", 0) % pages
        self.buttons = header(d, "Емоції")
        button(d, (LW - 96, 6, LW - 10, 38), f"{page + 1}/{pages}  ›", fill=TILE2, f=F14)
        self.buttons.append(((LW - 96, 6, LW - 10, 38), "page"))
        for i, (key, label) in enumerate(self.EMOS[page * 20:page * 20 + 20]):
            col, row = i % 4, i // 4
            x0, y0 = 8 + col * 118, 52 + row * 53
            rect = (x0, y0, x0 + 110, y0 + 46)
            anim = key in ("roll", "scan", "blink", "yawn", "peek", "wiggle", "dtake", "squint", "browup", "tilt", "slowblink", "droop")
            button(d, rect, label, fill=(46, 70, 100) if anim else TILE, f=F14)
            self.buttons.append((rect, "emo_" + key))
        return im

    def draw_particles(self):
        f = self.scene.frame()
        arr = np.zeros((LH, PW, 3), np.uint8)
        arr[PY0:PY0 + PW] = f
        rot = np.rot90(arr, ROT)                                # PW rows of the portrait framebuffer
        r = (rot[..., 0].astype(np.uint16) >> 3) << 11
        g = (rot[..., 1].astype(np.uint16) >> 2) << 5
        b = rot[..., 2].astype(np.uint16) >> 3
        with open("/dev/fb0", "r+b", buffering=0) as fb:
            fb.seek((LW - PX1) * 320 * 2)
            fb.write((r | g | b).astype("<u2").tobytes())
        return None

    def draw_confirm(self):
        im, d = new()
        d.text((LW // 2, 100), self.confirm[0], font=F26, fill=TXT, anchor="mm")
        d.text((LW // 2, 140), "Ви впевнені?", font=F16, fill=DIM, anchor="mm")
        button(d, (50, 190, 220, 270), "Так", fill=(150, 40, 40), f=F26)
        button(d, (260, 190, 430, 270), "Ні", fill=TILE2, f=F26)
        self.buttons = [((50, 190, 220, 270), "confirm_yes"), ((260, 190, 430, 270), "confirm_no")]
        return im

    def draw_calibrate(self):
        im, d = new()
        targets = [(40, 40), (440, 40), (440, 280), (40, 280)]
        tx, ty = targets[self.cal_step]
        d.text((LW // 2, 150), f"Калібрування {self.cal_step + 1}/4", font=F26, fill=TXT, anchor="mm")
        d.text((LW // 2, 184), "Торкніться хрестика пальцем чи пером", font=F16, fill=DIM, anchor="mm")
        d.line([tx - 22, ty, tx + 22, ty], fill=ACC, width=3)
        d.line([tx, ty - 22, tx, ty + 22], fill=ACC, width=3)
        d.ellipse([tx - 7, ty - 7, tx + 7, ty + 7], outline=ACC, width=2)
        self.buttons = []
        return im

    def draw_camera(self):
        with self.cam_lock:
            jpg = self.latest[0]
        if not jpg:
            return None
        im = Image.open(io.BytesIO(jpg)).convert("RGB")
        if im.size != (LW, LH):
            im = im.resize((LW, LH))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([8, 8, 76, 48], radius=10, fill=(0, 0, 0))
        d.polygon([(26, 28), (40, 16), (40, 40)], fill=TXT)
        d.text((46, 28), "назад", font=F12, fill=TXT, anchor="lm")
        self.buttons = [((0, 0, 90, 60), "back")]
        return im

    # ---- touch handling
    def on_tap(self, raw):
        now = time.time()
        if now - self.last_touch < 0.35:
            return
        self.last_touch = now
        if self.screen == "calibrate":
            self.cal_raw.append(raw)
            self.cal_step += 1
            if self.cal_step >= 4:
                self.calibrate(self.cal_raw)
                self.go("home")
            else:
                self.entered = now
            return
        if not self.cal:
            self.cal_step, self.cal_raw = 0, []
            self.go("calibrate")
            return
        pos = self.to_screen(raw)
        if self.screen == "eyes":
            self.go("home")
            return
        for (x0, y0, x1, y1), action in self.buttons:
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                self.do(action)
                return
        if self.screen == "particles":
            self.scene.tap()

    def do(self, action):
        if action == "back":
            self.go("home")
        elif action in ("marstek", "camera", "system", "work", "settings", "particles"):   # simple screens
            self.go(action)
        elif action == "eyes":
            self.go("eyes")
        elif action == "emotions":
            self.go("emotions")
        elif action == "page":
            self.cache["page"] = self.cache.get("page", 0) + 1
        elif action.startswith("emo_"):
            with open("/tmp/eyes_cmd", "w") as f:               # eyes.py picks it up as soon as the menu closes
                f.write(action[4:])
            self.go("eyes")
        elif action == "toggle_track":
            on = run("systemctl", "is-active", "eyetrack") == "active"
            run("systemctl", "disable" if on else "enable", "--now", "eyetrack")
            self.cache = {}
        elif action == "toggle_mirror":
            self.set_setting("mood_mirror", not self.settings["mood_mirror"])
        elif action == "cycle_sleep":
            order = [1, 5, 10, 30, 0]
            cur = self.settings["sleep_after_min"]
            self.set_setting("sleep_after_min", order[(order.index(cur) + 1) % len(order)] if cur in order else 1)
        elif action == "recal":
            self.cal_step, self.cal_raw = 0, []
            self.go("calibrate")
        elif action == "ask_reboot":
            self.confirm = ("Перезавантажити Pi?", ["systemctl", "reboot"])
            self.screen = "confirm"
        elif action == "ask_off":
            self.confirm = ("Вимкнути Pi?", ["systemctl", "poweroff"])
            self.screen = "confirm"
        elif action == "confirm_yes":
            subprocess.Popen(self.confirm[1])
            self.go("home")
        elif action == "confirm_no":
            self.screen = "settings"

    # ---- main loop
    def loop(self):
        last_shown, last_frame = 0.0, None
        while True:
            try:
                raw = self.touch.q.get(timeout=0.004 if self.screen == "particles" else 0.12)
                self.on_tap(raw)
                last_shown = 0
                while not self.touch.q.empty():
                    self.touch.q.get_nowait()
            except queue.Empty:
                pass
            if self.screen == "eyes":
                continue
            now = time.time()
            limit = CAMERA_MAX_S if self.screen == "camera" else PARTICLES_MAX_S if self.screen == "particles" else IDLE_S
            if self.screen != "calibrate" and now - max(self.last_touch, self.entered) > limit:
                self.go("eyes")
                continue
            period = 0.12 if self.screen == "camera" else 0.03 if self.screen == "particles" else 1.0
            if now - last_shown < period:
                continue
            draw = {"home": self.draw_home, "marstek": self.draw_marstek, "system": self.draw_system, "work": self.draw_work,
                    "settings": self.draw_settings, "emotions": self.draw_emotions, "particles": self.draw_particles, "confirm": self.draw_confirm, "calibrate": self.draw_calibrate,
                    "camera": self.draw_camera}[self.screen]
            im = draw()
            if self.screen == "particles":                  # drawn straight into the framebuffer by draw_particles
                last_shown = now
                continue
            if im is not None:
                key = hash(im.tobytes())
                if key != last_frame:                       # do not push identical frames over the slow SPI bus
                    show(im)
                    last_frame = key
                last_shown = now


if __name__ == "__main__":
    app = App()
    try:
        app.loop()
    finally:
        try:
            app.stop_camera()
            os.remove(FLAG)
        except Exception:
            pass

#!/usr/bin/env python3
"""Marstek battery logger: polls the local UDP API every INTERVAL seconds, stores one row per poll in SQLite.

Read-only: only Get* methods are used, nothing is ever changed on the battery.
Config in ~/.env (optional): MARSTEK_IP=192.168.50.252, MARSTEK_INTERVAL=30
"""
import json, os, socket, sqlite3, time, urllib.parse, urllib.request

HOME = os.path.expanduser("~")
DB = os.path.join(HOME, "marstek.db")


def load_env():
    env = {}
    try:
        for line in open(os.path.join(HOME, ".env")):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v
    except FileNotFoundError:
        pass
    return env


ENV = load_env()
IP = ENV.get("MARSTEK_IP", "192.168.50.252")
INTERVAL = int(ENV.get("MARSTEK_INTERVAL", "30"))
KEEP_DAYS = 400
LOW1, LOW2, FULL_AT, OFFLINE_MIN = 20, 10, 100, 10      # alert thresholds (percent / minutes)


def telegram(text):
    try:
        chat = open(os.path.join(HOME, ".owner")).read().strip()
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{ENV['TELEGRAM_TOKEN']}/sendMessage", data), timeout=20).read()
    except Exception as e:
        print("telegram error:", e, flush=True)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2.0)
sock.bind(("", 30000))                    # the battery answers to port 30000
_n = 100


def call(method, tries=8):
    """One API call with retries (the battery's Wi-Fi is sleepy). Returns the 'result' dict or None."""
    global _n
    _n += 1
    msg = json.dumps({"id": _n, "method": method, "params": {"id": 0}}).encode()
    for _ in range(tries):
        try:
            sock.sendto(msg, (IP, 30000))
            data, addr = sock.recvfrom(4096)
            if addr[0] == IP:
                r = json.loads(data)
                if isinstance(r.get("result"), dict):
                    return r["result"]
        except (socket.timeout, OSError, ValueError):
            time.sleep(0.8)
    return None


db = sqlite3.connect(DB)
db.execute("""CREATE TABLE IF NOT EXISTS samples (
    ts INTEGER PRIMARY KEY, soc REAL, cap_wh REAL, temp_c REAL, load_w REAL, grid_w REAL, pv_w REAL,
    mode TEXT, rssi REAL, ok INTEGER,
    pv_e REAL, grid_out_e REAL, grid_in_e REAL, load_e REAL)""")        # *_e: lifetime counters kept by the battery itself
db.commit()
print("marstek logger started: ip", IP, "every", INTERVAL, "s ->", DB, flush=True)

cycle = 0
flags = {"low1": False, "low2": False, "full": False}
last_ok, offline_sent = time.monotonic(), False      # monotonic: the wall clock may jump at boot
while True:
    t0 = time.time()
    es, bat, mode = call("ES.GetStatus"), call("Bat.GetStatus"), call("ES.GetMode")
    wifi = call("Wifi.GetStatus", tries=2) if cycle % 10 == 0 else None
    cycle += 1
    ok = 1 if (es or bat or mode) else 0
    row = (
        int(t0),
        (es or {}).get("bat_soc") if es else (bat or {}).get("soc"),
        (es or {}).get("bat_cap") if es else (bat or {}).get("bat_capacity"),
        (bat or {}).get("bat_temp"),
        (es or {}).get("offgrid_power") if es else (mode or {}).get("offgrid_power"),
        (es or {}).get("ongrid_power") if es else (mode or {}).get("ongrid_power"),
        (es or {}).get("pv_power"),
        (mode or {}).get("mode"),
        (wifi or {}).get("rssi"),
        ok,
        (es or {}).get("total_pv_energy"),
        (es or {}).get("total_grid_output_energy"),
        (es or {}).get("total_grid_input_energy"),
        (es or {}).get("total_load_energy"),
    )
    try:
        db.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        if cycle % 2880 == 1:
            db.execute("DELETE FROM samples WHERE ts < ?", (int(t0) - KEEP_DAYS * 86400,))
        db.commit()
    except sqlite3.Error as e:
        print("db error:", e, flush=True)
    if not ok:
        print(time.strftime("%H:%M:%S"), "battery did not answer", flush=True)
    # --- Telegram alerts (with hysteresis, so each fires once per event)
    soc = row[1]
    if ok:
        last_ok = time.monotonic()
        if offline_sent:
            offline_sent = False
            telegram("✅ Marstek знову на зв'язку" + (f" (заряд {soc:g}%)" if soc is not None else ""))
    elif not offline_sent and time.monotonic() - last_ok > OFFLINE_MIN * 60:
        offline_sent = True
        telegram(f"⚠️ Marstek не відповідає вже {OFFLINE_MIN} хв (Wi-Fi, живлення?)")
    if soc is not None:
        if soc <= LOW1 and not flags["low1"]:
            flags["low1"] = True
            telegram(f"🪫 Marstek: заряд {soc:g}% — меншає, є ще ~{(row[2] or 0):g} Вт·год")
        elif soc >= LOW1 + 5:
            flags["low1"] = False
        if soc <= LOW2 and not flags["low2"]:
            flags["low2"] = True
            telegram(f"🔴 Marstek: заряд лише {soc:g}%! Скоро вимкнеться")
        elif soc >= LOW2 + 5:
            flags["low2"] = False
        if soc >= FULL_AT and not flags["full"]:
            flags["full"] = True
            telegram("🔋 Marstek заряджено на 100%")
        elif soc < FULL_AT - 5:
            flags["full"] = False
    time.sleep(max(1.0, INTERVAL - (time.time() - t0)))

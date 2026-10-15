#!/usr/bin/env python3
"""Air-raid alert watcher for one oblast (alerts.in.ua API).

- every POLL seconds asks for the active alerts and looks at OBLAST
- alert starts / ends: sends a Telegram message to the owner of the eyes bot
- while an alert is active: /tmp/eyes_alert holds the text, so eyes.py shows the alarm face

Config in ~/.env: ALERTS_API_TOKEN=..., TELEGRAM_TOKEN=... (the owner chat id is in ~/.owner)
"""
import json, os, time, urllib.parse, urllib.request

OBLAST = "Львівська область"
# oblasts that border OBLAST: a warning is shown when an alert starts there
NEIGHBOURS = {
    "Волинська область": "Волинь",
    "Рівненська область": "Рівне",
    "Тернопільська область": "Тернопіль",
    "Івано-Франківська область": "Ів.-Франківськ",
    "Закарпатська область": "Закарпаття",
}
POLL = 30
HOME = os.path.expanduser("~")
FLAG = "/tmp/eyes_alert"          # alert in OBLAST itself
WARN = "/tmp/eyes_warn"           # alert in a neighbouring oblast


def load_env():
    env = {}
    for line in open(os.path.join(HOME, ".env")):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v
    return env


ENV = load_env()


def telegram(text):
    try:
        chat = open(os.path.join(HOME, ".owner")).read().strip()
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{ENV['TELEGRAM_TOKEN']}/sendMessage", data), timeout=20).read()
    except Exception as e:
        print("telegram error:", e, flush=True)


def active_by_oblast():
    """{oblast: sorted list of districts with an air-raid alert}"""
    url = "https://api.alerts.in.ua/v1/alerts/active.json?token=" + urllib.parse.quote(ENV["ALERTS_API_TOKEN"])
    with urllib.request.urlopen(url, timeout=25) as r:
        alerts = json.load(r).get("alerts", [])
    out = {}
    for al in alerts:
        if al.get("alert_type") == "air_raid":
            out.setdefault(al.get("location_oblast"), set()).add(al.get("location_title", "?"))
    return {k: sorted(v) for k, v in out.items()}


def set_flag(path, on, text=""):
    if on:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        try:
            os.remove(path)
        except OSError:
            pass


state, since, nb_prev = None, None, set()
print("alertwatch started for", OBLAST, "+ neighbours", list(NEIGHBOURS), flush=True)
while True:
    try:
        by = active_by_oblast()
        districts = by.get(OBLAST, [])
        now_active = bool(districts)
        near = {o for o in NEIGHBOURS if o in by}

        # --- alert in the oblast itself
        if now_active:
            set_flag(FLAG, True, "ТРИВОГА! " + OBLAST.replace(" область", " обл."))
        if now_active and state is not True:
            since = time.time()
            telegram(f"🚨 Повітряна тривога: {OBLAST}\nРайони: " + ", ".join(districts))
            print("ALERT", districts, flush=True)
        elif not now_active and state is True:
            set_flag(FLAG, False)
            mins = int((time.time() - since) / 60) if since else 0
            telegram(f"✅ Відбій тривоги: {OBLAST} (тривала ~{mins} хв)")
            print("clear", flush=True)
        elif not now_active:
            set_flag(FLAG, False)
        state = now_active

        # --- alerts next door (only a warning, the own alert has priority on the screen)
        if near:
            names = [NEIGHBOURS[o] for o in sorted(near)]
            set_flag(WARN, True, "Поруч: " + names[0] + (f" +{len(names) - 1}" if len(names) > 1 else ""))
        else:
            set_flag(WARN, False)
        started = near - nb_prev
        if started and not now_active:
            lines = [f"• {o}: " + ", ".join(by[o][:4]) + (f" та ще {len(by[o]) - 4}" if len(by[o]) > 4 else "") for o in sorted(started)]
            telegram("⚠️ Тривога в суміжній області (до Львівщини близько):\n" + "\n".join(lines))
            print("NEIGHBOUR ALERT", sorted(started), flush=True)
        elif nb_prev and not near and not now_active:
            telegram("🟢 У суміжних областях відбій.")
            print("neighbours clear", flush=True)
        nb_prev = near
    except Exception as e:
        print("poll error:", e, flush=True)
    time.sleep(POLL)

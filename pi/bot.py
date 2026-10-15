#!/usr/bin/env python3
"""Telegram bot -> local Ollama model -> animated eyes. Stdlib only.

Config in ~/.env:  TELEGRAM_TOKEN=...   (optional: OLLAMA_MODEL=gemma3:1b)
Pairing: the owner sends `/start <code>` once; the code is in ~/.pair.
The owner's chat id is then stored in ~/.owner and everyone else is ignored.
"""
import json, os, random, re, secrets, subprocess, time, urllib.request, urllib.parse, uuid

HOME = os.path.expanduser("~")
CMD = "/tmp/eyes_cmd"
EMOTIONS = ["neutral", "happy", "sad", "angry", "thinking", "surprised", "sleepy", "love", "excited", "scared", "suspicious", "bored", "cry", "joy", "wink", "dizzy", "evil"]
EXTRA = ["pain", "dead", "confused", "smug", "nervous", "sick", "laughing", "determined", "money", "curious",
         "embarrassed", "yawn", "roll", "scan"]            # only via Telegram commands, the model does not choose them
SYSTEM_EN = "You are Okko, a tiny friendly creature with eyes. Answer the user directly with ONE short sentence (max 12 words). "
SYSTEM_UK = "Ти — Окко, маленька добра істота з очима. Відповідай ОДНИМ коротким реченням (до 12 слів) українською. "

# The emotion is picked by simple keyword rules (the tiny model is fast but bad at choosing it).
# Order matters: the first group that matches the user's message wins.
RULES = [
    ("angry", ["stupid", "idiot", "useless", "hate you", "shut up", "dumb", "дурн", "тупий", "тупа", "ідіот", "ненавиджу", "замовкни", "нікчем"]),
    ("love", ["love you", "i love", "kiss", "❤", "люблю", "кохаю", "цілую", "обіймаю"]),
    ("scared", ["scared", "afraid", "boo", "ghost", "help me", "fear", "страшн", "боюсь", "боюся", "бу!", "привид", "допоможи"]),
    ("sad", ["sad", "died", "dead", "cry", "lonely", "miss you", "depress", "unhappy", "сумно", "помер", "померла", "плач", "самотн", "сумую", "погано", "шкода"]),
    ("sleepy", ["tired", "sleep", "exhaust", "bedtime", "good night", "втомив", "втомл", "спати", "сонн", "виснаж", "добраніч"]),
    ("surprised", ["wow", "omg", "incredible", "unbelievable", "no way", "нічого собі", "ого", "неймовірн"]),
    ("excited", ["won", "win ", "got a job", "promotion", "great news", "amazing", "awesome", "party", "yay", "виграв", "виграла", "ура", "круто", "отримав роботу", "чудово", "перемог"]),
    ("laughing", ["lmao", "rofl", "умер від сміху", "ахах", "аха-ха"]),
    ("money", ["money", "salary", "rich", "got paid", "зарплат", "гроші", "багат"]),
    ("embarrassed", ["shy", "embarrass", "соромно", "ніяково"]),
    ("sick", ["feel sick", "nausea", "i'm ill", "хворі", "нудить", "захворів"]),
    ("nervous", ["nervous", "anxious", "worried", "exam", "хвилююсь", "переживаю"]),
    ("confused", ["confus", "don't understand", "do not understand", "не розумію", "заплутав"]),
    ("determined", ["let's go", "focus", "determined", "вперед", "сконцентр"]),
    ("curious", ["curious", "i wonder", "цікаво"]),
    ("smug", ["told you so", "i told you", "proud of me", "я ж казав", "я молодець"]),
    ("joy", ["joke", "funny", "haha", "lol", "жарт", "смішн", "ха-ха"]),
    ("bored", ["bored", "boring", "нудно", "нудн"]),
    ("dizzy", ["dizzy", "spinning", "запаморочен"]),
    ("evil", ["revenge", "evil plan", "помст"]),
    ("suspicious", ["suspicious", "secret", "підозр", "секрет"]),
    ("wink", ["wink", "flirt", "підморг"]),
    ("happy", ["hello", "hi ", "hi!", "thanks", "thank you", "good morning", "nice", "привіт", "дякую", "доброго ранку", "гарно"]),
    ("thinking", ["why ", "how ", "what is", "explain", "calculate", "capital", "чому", "як ", "що таке", "поясни", "скільки", "яка столиця"]),
]


def classify(user_text, reply):
    u = " " + user_text.lower() + " "
    for emo, words in RULES:
        if any(w in u for w in words):
            return emo
    r = reply.lower()
    if any(w in r for w in ("congrat", "wonderful", "great", "glad", "happy", "вітаю", "чудово", "радий", "рада")):
        return "happy"
    return "neutral"


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
TOKEN = ENV["TELEGRAM_TOKEN"]
MODEL = ENV.get("OLLAMA_MODEL", "gemma3:1b")
MODEL_UK = ENV.get("OLLAMA_MODEL_UK", "gemma3:1b")        # the tiny model cannot write Ukrainian: use the bigger one for it
SYSTEM = SYSTEM_UK if ENV.get("REPLY_LANG", "en") == "uk" else SYSTEM_EN   # REPLY_LANG=uk in ~/.env for Ukrainian
API = f"https://api.telegram.org/bot{TOKEN}/"


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(API + method, data), timeout=70) as r:
        return json.load(r)


def tg_photo(chat_id, path, caption=""):
    """Upload a picture to the owner (multipart/form-data, stdlib only)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("chat_id", str(chat_id)), ("caption", caption)):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{os.path.basename(path)}"\r\n'
                 "Content-Type: image/jpeg\r\n\r\n".encode() if path.endswith(".jpg") else
                 f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{os.path.basename(path)}"\r\n'
                 "Content-Type: image/png\r\n\r\n".encode())
    parts.append(open(path, "rb").read())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(API + "sendPhoto", b"".join(parts),
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=60).read()


def take_photo(path="/tmp/okko_photo.jpg"):
    """The tracker owns the camera: stop it for a moment, shoot, start it again."""
    subprocess.run(["sudo", "systemctl", "stop", "eyetrack"], timeout=30)
    try:
        subprocess.run(["rpicam-still", "-n", "-t", "1500", "--width", "1280", "--height", "960",
                        "--tuning-file", "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json", "-o", path],
                       timeout=40, capture_output=True)
    finally:
        subprocess.run(["sudo", "systemctl", "start", "eyetrack"], timeout=30)
    return path if os.path.exists(path) and os.path.getsize(path) > 1000 else None


def screenshot(path="/tmp/fbshot.png"):
    subprocess.run(["sudo", "/usr/bin/python3", "/home/tronyak/fbshot.py"], timeout=30, capture_output=True)
    return path if os.path.exists(path) else None


def status_text():
    def run(*cmd):
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    temp = run("vcgencmd", "measure_temp").replace("temp=", "")
    thr = run("vcgencmd", "get_throttled").replace("throttled=", "")
    load = open("/proc/loadavg").read().split()[:3]
    mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
    disk = run("df", "-h", "/").splitlines()[-1].split()
    up = run("uptime", "-p").replace("up ", "")
    svc = {s: run("systemctl", "is-active", s) for s in ("ollama", "eyes", "eyetrack", "eyes-bot", "alertwatch", "worktime")}
    bad = [f"{k}: {v}" for k, v in svc.items() if v != "active"]
    alerts = "🚨 ТРИВОГА у Львівській" if os.path.exists("/tmp/eyes_alert") else (
        "⚠️ тривога в сусідній: " + open("/tmp/eyes_warn", encoding="utf-8").read() if os.path.exists("/tmp/eyes_warn") else "🟢 тривог немає")
    loaded = run("ollama", "ps").splitlines()[1:2]
    return (f"🌡 {temp}" + (" ⚠️ було обмеження частоти" if thr not in ("0x0", "") else "") + f"\n"
            f"⏱ працює {up}\n⚙️ load {' '.join(load)}\n"
            f"🧠 RAM вільно {mem['MemAvailable'] // 1024} МБ із {mem['MemTotal'] // 1024} МБ\n"
            f"💾 диск {disk[4]} зайнято (вільно {disk[3]})\n"
            f"🛠 служби: " + ("всі працюють" if not bad else ", ".join(bad)) + f"\n{alerts}\n"
            f"🤖 модель у пам'яті: " + (loaded[0].split()[0] if loaded else "жодної"))


def battery_text():
    import sqlite3
    try:
        db = sqlite3.connect(os.path.expanduser("~/marstek.db"))
        now = int(time.time())
        last = db.execute("SELECT ts,soc,cap_wh,temp_c,load_w,grid_w,pv_w,mode,load_e,pv_e FROM samples WHERE ok=1 ORDER BY ts DESC LIMIT 1").fetchone()
        if not last:
            return "У базі поки немає даних Marstek."
        ts, soc, cap, temp, load, grid, pv, mode, load_e, pv_e = last
        d = db.execute("SELECT MIN(soc),MAX(soc),AVG(load_w),MAX(load_w) FROM samples WHERE ok=1 AND ts>?", (now - 86400,)).fetchone()
        n24 = db.execute("SELECT COUNT(*),SUM(ok) FROM samples WHERE ts>?", (now - 86400,)).fetchone()
        e0 = db.execute("SELECT load_e FROM samples WHERE ok=1 AND load_e IS NOT NULL AND ts>? ORDER BY ts LIMIT 1", (now - 86400,)).fetchone()
        used = (load_e - e0[0]) if (e0 and load_e is not None) else None
        age = now - ts
        return (f"🔋 Marstek: {soc:g}% ({cap:g} Вт·год)" + (f", {temp:g} °C" if temp is not None else "") + f"\n"
                f"режим: {mode or '?'}, навантаження: {load if load is not None else '?'} Вт"
                + (f", мережа: {grid} Вт" if grid else "") + (f", сонце: {pv} Вт" if pv else "") + "\n"
                f"за 24 год: заряд {d[0]:g}–{d[1]:g}%, середнє навантаження {d[2]:.0f} Вт (пік {d[3]:g} Вт)"
                + (f", лічильник навантаження +{used:g}" if used is not None else "") + "\n"
                f"даних за добу: {n24[1] or 0} з {n24[0]} опитувань; останнє {age} с тому")
    except Exception as e:
        return f"Не вдалося прочитати базу Marstek: {e}"


def eyes(cmd):
    try:
        with open(CMD, "w") as f:
            f.write(cmd)
    except OSError:
        pass


def time_hint(history):
    """Only spend prompt tokens on the clock when the user seems to ask about time or date."""
    last = history[-1]["content"].lower() if history else ""
    return any(w in last for w in ("time", "date", "day", "clock", "година", "час", "дата", "день"))


def ask(history):
    """Return (emotion, text, raw). Tokens are streamed so the eyes can show progress."""
    cyr = bool(history) and bool(re.search("[А-Яа-яІіЇїЄєҐґ]", history[-1]["content"]))
    model = MODEL_UK if cyr else MODEL
    system = (SYSTEM_UK if cyr else SYSTEM) + ("Now: " + time.strftime("%H:%M, %A. ") if time_hint(history) else "")
    for attempt in range(3):
        body = json.dumps({
            "model": model, "stream": True, "keep_alive": "30m",
            "messages": [{"role": "system", "content": system}] + history,
            "options": {"temperature": 0.6 + 0.15 * attempt, "num_predict": 40, "stop": ["\n"]},
        }).encode()
        req = urllib.request.Request("http://127.0.0.1:11434/api/chat", body, {"Content-Type": "application/json"})
        content, n, last = "", 0, 0.0
        with urllib.request.urlopen(req, timeout=300) as r:
            for line in r:
                content += json.loads(line).get("message", {}).get("content", "")
                n += 1
                if time.time() - last > 0.4:       # the first token also ends the "loading" phase
                    eyes("progress %.2f" % min(0.95, n / 18))
                    last = time.time()
        text = re.sub(r"^\s*\[[A-Za-z]+\]\s*", "", content).strip()
        if text:
            user_text = history[-1]["content"] if history else ""
            return classify(user_text, text), text, text
    return "sad", "I could not think of an answer. Try again?", ""


def owner_id():
    try:
        return int(open(os.path.join(HOME, ".owner")).read().strip())
    except Exception:
        return None


def main():
    pair = os.path.join(HOME, ".pair")
    if owner_id() is None and not os.path.exists(pair):
        with open(pair, "w") as f:
            f.write(secrets.token_hex(3))
        os.chmod(pair, 0o600)
    history, offset = [], 0
    print("bot started, owner:", owner_id(), flush=True)
    while True:
        try:
            upd = tg("getUpdates", offset=offset, timeout=50)["result"]
        except Exception as e:
            print("poll error:", e, flush=True)
            time.sleep(5)
            continue
        for u in upd:
            offset = u["update_id"] + 1
            m = u.get("message")
            if not m or "text" not in m:
                continue
            cid, text = m["chat"]["id"], m["text"].strip()
            if owner_id() is None:
                code = open(pair).read().strip()
                if text == f"/start {code}":
                    open(os.path.join(HOME, ".owner"), "w").write(str(cid))
                    os.remove(pair)
                    tg("sendMessage", chat_id=cid, text="Готово, тепер я слухаю тільки тебе 👀")
                    eyes("happy")
                continue
            if cid != owner_id():
                continue
            try:
                if text.startswith("/"):
                    cmd = text[1:].split("@")[0].lower()
                    if cmd == "start":
                        tg("sendMessage", chat_id=cid, text="Привіт! Пиши мені — відповім. Команди: /" + ", /".join(EMOTIONS + EXTRA) + ", /work, /battery, /status, /screen, /photo, /reset")
                    elif cmd in EMOTIONS + EXTRA:
                        eyes(cmd)
                    elif cmd == "battery":
                        tg("sendMessage", chat_id=cid, text=battery_text())
                    elif cmd == "status":
                        tg("sendMessage", chat_id=cid, text=status_text())
                    elif cmd == "screen":
                        p = screenshot()
                        if p:
                            tg_photo(cid, p, "Так зараз виглядає екран")
                            subprocess.run(["sudo", "rm", "-f", p])
                        else:
                            tg("sendMessage", chat_id=cid, text="Не вдалося зняти екран.")
                    elif cmd == "photo":
                        eyes("wink")
                        p = take_photo()
                        if p:
                            tg_photo(cid, p, "📷 " + time.strftime("%H:%M:%S"))
                            os.remove(p)                     # nothing is kept on the Pi
                        else:
                            tg("sendMessage", chat_id=cid, text="Камера не відповіла.")
                    elif cmd in ("work", "stats"):
                        try:
                            st = json.load(open("/tmp/worktime_state.json"))
                            now_ = time.time()
                            mins = lambda s: (f"{int(s // 3600)} г {int(s % 3600 // 60)} хв" if s >= 3600 else f"{int(s // 60)} хв")
                            cur_ = (f"Зараз: працюєте вже {mins(now_ - st['session_start'])}" if st["mode"] == "work"
                                    else f"Зараз: перерва {mins(now_ - st['since'])}" if st["since"] else "Зараз: вас не видно")
                            tg("sendMessage", chat_id=cid, text=f"📊 Сьогодні: {mins(st['today_work_s'])} роботи, сесій: {st['today_sessions']}\n{cur_}")
                        except Exception:
                            tg("sendMessage", chat_id=cid, text="Поки немає даних про роботу.")
                    elif cmd == "reset":
                        history.clear()
                        tg("sendMessage", chat_id=cid, text="Забув усе.")
                    elif cmd.startswith("look "):
                        eyes(cmd)
                    continue
                eyes("thinking")
                time.sleep(0.1)
                eyes("busy on")
                tg("sendChatAction", chat_id=cid, action="typing")
                history.append({"role": "user", "content": text})
                open("/tmp/eyes_pause", "w").close()           # pause face tracking while the model thinks
                try:
                    emo, answer, raw = ask(history[-8:])
                finally:
                    try:
                        os.remove("/tmp/eyes_pause")
                    except OSError:
                        pass
                if raw:
                    history.append({"role": "assistant", "content": raw})
                else:
                    history.pop()
                del history[:-16]
                eyes("busy off")
                tg("sendMessage", chat_id=cid, text=answer)
                try:                                   # short answers also go on the screen
                    with open("/tmp/eyes_say", "w", encoding="utf-8") as f:
                        f.write(answer[:160])
                except OSError:
                    pass
                eyes(emo)
                time.sleep(0.2)
                eyes("mouth on")
                time.sleep(min(12, max(1.5, len(answer) * 0.06)))
                eyes("mouth off")
            except Exception as e:
                print("handle error:", e, flush=True)
                eyes("busy off")
                time.sleep(0.1)
                eyes("sad")
                try:
                    tg("sendMessage", chat_id=cid, text="Щось пішло не так: " + str(e)[:200])
                except Exception:
                    pass


if __name__ == "__main__":
    main()

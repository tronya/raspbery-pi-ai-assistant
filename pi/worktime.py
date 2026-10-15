#!/usr/bin/env python3
"""Work-time companion: counts how long you sit in front of the camera.

track.py touches /tmp/eyes_presence (epoch seconds) whenever it sees a face.
- gaps up to BREAK_AFTER (3 min) do not interrupt a work session
- a longer absence ends the session and counts as a break
- coming back after a break of GREET_MIN (5 min) or more: a welcome-back message
- while you keep working: a friendly reminder every REMIND_MIN minutes
All texts are written by the local language model (with static fallbacks).
Only times are stored (~/worklog.json), never pictures.
"""
import json, os, random, re, time, urllib.parse, urllib.request

HOME = os.path.expanduser("~")
PRES, PAUSE = "/tmp/eyes_presence", "/tmp/eyes_pause"
STATE, LOG = "/tmp/worktime_state.json", os.path.join(HOME, "worklog.json")
BREAK_AFTER = int(os.environ.get("WORK_BREAK_AFTER_S", 180))   # seconds without a face before the session counts as ended
GREET_MIN = int(os.environ.get("WORK_GREET_MIN_S", 300))      # a break at least this long gets a welcome-back message
TICK = 5


def load_env():
    env = {}
    for line in open(os.path.join(HOME, ".env")):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v
    return env


ENV = load_env()
MODEL = ENV.get("OLLAMA_MODEL", "gemma3:1b")
REMIND_MIN = int(ENV.get("WORK_REMIND_MIN", "45"))
LANG = ENV.get("WORK_LANG", "uk")


def eyes(cmd):
    try:
        open("/tmp/eyes_cmd", "w").write(cmd)
    except OSError:
        pass


def telegram(text):
    if os.environ.get("WORK_NO_TELEGRAM"):
        print("[telegram skipped]", text, flush=True)
        return
    try:
        chat = open(os.path.join(HOME, ".owner")).read().strip()
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{ENV['TELEGRAM_TOKEN']}/sendMessage", data), timeout=20).read()
    except Exception as e:
        print("telegram error:", e, flush=True)


def fmt(seconds):
    m = int(seconds // 60)
    return f"{m // 60} г {m % 60} хв" if m >= 60 else f"{m} хв"


# Ukrainian lines written by hand: the 1B model cannot write decent Ukrainian. {w} = minutes worked, {a} = minutes away.
BANK = {
    "back": [
        ("happy", "З поверненням! Відпочив {a} хв — тепер мозок як новенький. Працюємо?"),
        ("excited", "О, ти повернувся! Я вже соромився сам дивитись у порожній стілець."),
        ("happy", "Привіт знову! Чай випито, ноги розім'яті — готовий до подвигів?"),
        ("love", "Нарешті! Я тут майже встиг заснути. Ну що, береш на себе нові задачі?"),
        ("happy", "Бачу тебе — і все на місці. {a} хв відпочинку, а далі знову в бій!"),
        ("excited", "Є контакт! Перерва скінчилась — дай п'ять уявною лапкою й вперед."),
        ("happy", "З поверненням у стрій! Цікавий факт: після перерви мозок працює краще. Перевіримо?"),
        ("love", "Скучив! Можеш не поспішати... ну, може, трішки поспішай. Готовий?"),
        ("excited", "Ти повернувся, а отже день ще не програно. Починаємо?"),
        ("happy", "Ласкаво просимо назад! Вода є, думки є — лишилось сісти й зробити."),
        ("happy", "Ага, хтось сьогодні вже попрацював {w} хв. Повага. Продовжимо?"),
        ("excited", "Перерва закінчилась, а я ні! Гей, давай зробимо щось круте."),
    ],
    "back_long": [
        ("happy", "Нічого собі, тебе не було {a} хв! Сподіваюсь, ти встиг і пообідати, і відпочити."),
        ("excited", "Довгоочікуваний герой повернувся! Я трохи охолов — розігріваємось?"),
        ("love", "{a} хвилин без тебе — це вічність. Радий, що ти знову тут!"),
    ],
    "remind": [
        ("sleepy", "Ти вже {w} хв у роботі. Потягнись, випий води й поглянь у вікно!"),
        ("happy", "Маленька пауза? Подивись на щось далеке 20 секунд — очі подякують."),
        ("sleepy", "Факт: очі втомлюються швидше за голову. Дай їм хвилинку відпочинку!"),
        ("love", "Ти молодець, {w} хв поспіль! А тепер встань і розімни плечі."),
        ("happy", "Час на склянку води. Я стежу, щоб ти не перетворився на кактус."),
        ("sleepy", "Спина просить розминки. Ти ж не хочеш образити спину?"),
        ("excited", "Вже {w} хв — це хвилин сорок п'ять спокійної праці. Крок до чайника?"),
        ("happy", "Жарт: програмісти п'ють каву, бо без неї компілятор не розуміє. Піди зроби?"),
        ("sleepy", "Мої очі закриваються за тебе. Приєднаєшся до перерви?"),
        ("love", "Ти сьогодні в хорошій формі! Нагорода — п'ять хвилин відпочинку."),
        ("happy", "Цікаво: у голові після 45 хв роботи думки йдуть по колу. Встань і прогуляйся!"),
        ("excited", "Секретний прийом: встань, потягнись угору, видихни. Працює краще за каву!"),
    ],
    "remind_long": [
        ("sleepy", "{w} хв без перерви! Ти не робот, а я вже й так достатньо дивний. Перерва?"),
        ("excited", "Ого, {w} хв поспіль! Відпочинок — не слабкість, а паливо. Заправляйся!"),
    ],
}
_decks = {}


def pick_bank(kind, info):
    """Pick a line without repeating before the whole deck was used."""
    deck = _decks.get(kind)
    if not deck:
        deck = _decks[kind] = random.sample(BANK[kind], len(BANK[kind]))
    emo, text = deck.pop()
    return emo, text.format(w=info.get("worked", 0), a=info.get("away", 0))


THEMES = ["a tiny fun fact", "a light joke", "a warm compliment", "a playful challenge", "a calm, cosy remark",
          "a short riddle", "a quirky observation about breaks", "a cheerful pep talk"]
FALLBACK = {k: [t for _, t in v] for k, v in BANK.items()}


def generate(kind, info):
    """One short line: from the hand-written bank (Ukrainian) or written by the local model (English)."""
    if LANG == "uk":
        if kind == "back" and info["away"] >= 45:
            kind = "back_long"
        elif kind == "remind" and info["worked"] >= 90:
            kind = "remind_long" if random.random() < 0.6 else "remind"
        return pick_bank(kind, info)
    return generate_llm(kind, info)


def generate_llm(kind, info):
    """Ask the local model for one short line (works well in English), returns (emotion, text)."""
    theme = random.choice(THEMES)
    sys_ = ("You are Okko, a small friendly creature with expressive eyes who keeps a person company at their desk. "
            "Write ONE short sentence (max 18 words) " + ("in Ukrainian" if LANG == "uk" else "in English") +
            f", including {theme}. Start with your emotion in square brackets: happy/excited/love/sleepy/thinking.")
    if kind == "back":
        user = (f"The person was away for {info['away']} minutes after working {info['worked']} minutes. "
                "Welcome them back and ask if they are ready to work.")
    else:
        user = (f"The person has been working for {info['worked']} minutes without a pause. "
                "Gently suggest a short rest.")
    try:
        open(PAUSE, "w").close()                          # give the CPU to the model
        body = json.dumps({"model": MODEL, "stream": False, "keep_alive": "30m",
                           "messages": [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
                           "options": {"temperature": 0.95, "num_predict": 70, "stop": ["\n"]}}).encode()
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:11434/api/chat", body, {"Content-Type": "application/json"}), timeout=300))
        out = r["message"]["content"].strip()
        m = re.match(r"\s*\[([A-Za-z]+)\]\s*(.*)", out, re.S)
        emo, text = (m.group(1).lower(), m.group(2).strip()) if m else ("happy", out)
        cyr = sum("а" <= c.lower() <= "я" or c in "іїєґ" for c in text)
        if (LANG == "uk" and cyr < 0.6 * max(1, len(text.replace(" ", "")))) or not (8 < len(text) < 190):
            raise ValueError("bad generation")
        return (emo if emo in ("happy", "excited", "love", "sleepy", "thinking") else "happy"), text
    except Exception as e:
        print("generation failed, using fallback:", e, flush=True)
        return "happy", random.choice(FALLBACK[kind]).format(w=info.get("worked", 0), a=info.get("away", 0))
    finally:
        try:
            os.remove(PAUSE)
        except OSError:
            pass


def say(emo, text):
    try:
        open("/tmp/eyes_say", "w", encoding="utf-8").write(text[:160])
    except OSError:
        pass
    eyes(emo)


def load_log():
    try:
        return json.load(open(LOG))
    except Exception:
        return {}


def add_work(seconds, start):
    log = load_log()
    day = time.strftime("%Y-%m-%d", time.localtime(start))
    d = log.setdefault(day, {"work_s": 0, "sessions": 0})
    d["work_s"] += int(seconds)
    d["sessions"] += 1
    json.dump(log, open(LOG, "w"), ensure_ascii=False, indent=1)


def write_state(mode, since, session_start):
    log = load_log().get(time.strftime("%Y-%m-%d"), {"work_s": 0, "sessions": 0})
    json.dump({"mode": mode, "since": since, "session_start": session_start,
               "today_work_s": log["work_s"], "today_sessions": log["sessions"]}, open(STATE, "w"))


def last_seen():
    try:
        return float(open(PRES).read())
    except Exception:
        return 0.0


mode, away_since, session_start, next_remind, last_worked = "away", 0.0, 0.0, 0.0, 0.0
seen_before = False
print("worktime started; model", MODEL, "remind every", REMIND_MIN, "min", flush=True)
while True:
    try:
        now, seen = time.time(), last_seen()
        if os.path.exists(PAUSE) and mode == "work":
            seen = max(seen, now)                         # tracker paused on purpose: do not count it as absence
        if mode == "away" and seen and now - seen < 15:
            away = (seen - away_since) if away_since else 0
            mode, session_start, next_remind = "work", seen, seen + REMIND_MIN * 60
            if away_since and away >= GREET_MIN:
                emo, text = generate("back", {"away": int(away // 60), "worked": int(last_worked // 60)})
                say(emo, text)
                telegram(f"👋 {text}\n(перерва {fmt(away)}, до того працювали {fmt(last_worked)})")
                print("welcome back after", fmt(away), flush=True)
            else:
                print("session started", flush=True)
            seen_before = True
        elif mode == "work":
            if now - seen > BREAK_AFTER:
                last_worked = seen - session_start
                add_work(last_worked, session_start)
                mode, away_since = "away", seen
                print("session ended, worked", fmt(last_worked), flush=True)
            elif now >= next_remind:
                worked = now - session_start
                emo, text = generate("remind", {"worked": int(worked // 60)})
                say(emo, text)
                telegram(f"⏰ {text}\n(працюєте вже {fmt(worked)})")
                next_remind += REMIND_MIN * 60
                print("reminder after", fmt(worked), flush=True)
        write_state(mode, away_since if mode == "away" else session_start, session_start)
    except Exception as e:
        print("error:", e, flush=True)
    time.sleep(TICK)

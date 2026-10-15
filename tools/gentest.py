import json, random, re, time, urllib.request
SYS = ("Ти — Окко, маленька добра істота з очима, яка сидить на столі поруч з людиною. "
       "Пиши ОДНЕ коротке речення українською (до 14 слів), тепло й з гумором. Починай з емоції в дужках: [happy] або [excited] або [love] або [sleepy].")
SHOTS = [
    ("Людина повернулась після перерви 15 хв, до цього працювала 50 хв. Привітай і спитай, чи готова працювати.",
     "[happy] З поверненням! Кава випита, мозок свіжий — поїхали далі?"),
    ("Людина працює 45 хв без пауз. Лагідно порадь відпочити.",
     "[sleepy] Ти вже 45 хвилин у роботі — потягнись і подивись у вікно!"),
    ("Людина повернулась після перерви 30 хв, до цього працювала 90 хв. Привітай і спитай, чи готова працювати.",
     "[excited] О, ти знову тут! Відпочив як слід — давай зробимо щось круте!"),
]
def gen(user, theme):
    msgs = [{"role": "system", "content": SYS}]
    for u, a in SHOTS:
        msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": user + f" Додай {theme}."})
    body = json.dumps({"model": "gemma3:1b", "stream": False, "keep_alive": "30m", "messages": msgs,
                       "options": {"temperature": 0.8, "num_predict": 60, "stop": ["\n"]}}).encode()
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/chat", body, {"Content-Type": "application/json"}), timeout=300))
    return time.time() - t, r["message"]["content"].strip()
themes = ["маленький цікавий факт", "легкий жарт", "щирий комплімент", "жартівливий виклик", "спокійну лагідну думку"]
tasks = ["Людина повернулась після перерви 17 хв, до цього працювала 52 хв. Привітай і спитай, чи готова працювати.",
         "Людина працює 45 хв без пауз. Лагідно порадь відпочити.",
         "Людина повернулась після перерви 8 хв, до цього працювала 25 хв. Привітай і спитай, чи готова працювати."]
gen(tasks[0], themes[0])
for i in range(6):
    dt, txt = gen(random.choice(tasks), random.choice(themes))
    print(f"{dt:.0f}s {txt}")

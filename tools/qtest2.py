import time, importlib.util, sys
spec = importlib.util.spec_from_file_location("bot", "/home/tronyak/bot.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.eyes = lambda c: None
m.MODEL = sys.argv[1]
m.SYSTEM = (
    "You are Okko, a small friendly creature with expressive eyes on a screen. "
    "Reply to the user with ONE short sentence (max 12 words). "
    "Start with your emotion in square brackets, one of: happy, sad, angry, surprised, love, excited, scared, thinking, sleepy, neutral.\n"
    "User: I won the lottery! -> [excited] Wow, congratulations, that is amazing!\n"
    "User: My dog died today. -> [sad] Oh no, I am so sorry to hear that.\n"
    "User: You are useless and stupid. -> [angry] Hey, that is really rude!\n"
    "User: What is 2+2? -> [thinking] Hmm, that would be four.\n"
    "User: I love you! -> [love] Aww, I love you too!\n"
    "User: Boo! -> [scared] Eek! You startled me!\n"
    "User: I did not sleep all night. -> [sleepy] Oh, you must be so tired.\n"
    "User: Hello! -> [happy] Hi there! Nice to see you!\n"
)
m.ask([{"role": "user", "content": "hi"}])
for q in ["Hi! How are you today?", "My cat just learned to open doors!", "You are a stupid robot.", "I am so tired today...", "What is the capital of France?", "Boo!", "I got a new job!", "Tell me a joke"]:
    t = time.time(); emo, text, raw = m.ask([{"role": "user", "content": q}]); print(f"{time.time()-t:.1f}s [{emo}] {text}")

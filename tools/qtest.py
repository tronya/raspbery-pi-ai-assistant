import time, importlib.util, sys
spec = importlib.util.spec_from_file_location("bot", "/home/tronyak/bot.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.eyes = lambda c: None
m.MODEL = sys.argv[1]
m.ask([{"role": "user", "content": "hi"}])      # warm-up: load the model
for q in ["Hi! How are you today?", "My cat just learned to open doors!", "You are a stupid robot.", "I am so tired today...", "What is the capital of France?", "Boo!"]:
    t = time.time(); emo, text, raw = m.ask([{"role": "user", "content": q}]); print(f"{time.time()-t:.1f}s [{emo}] {text}")

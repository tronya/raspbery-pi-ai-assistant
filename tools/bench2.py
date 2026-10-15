import json, time, urllib.request, importlib.util
spec = importlib.util.spec_from_file_location("bot", "/home/tronyak/bot.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def go(opts, q):
    body = json.dumps({"model": "gemma3:1b", "stream": False, "keep_alive": "30m",
                       "messages": [{"role": "system", "content": m.SYSTEM}, {"role": "user", "content": q}],
                       "options": {"temperature": 0.6, "num_predict": 45, "stop": ["\n"], **opts}}).encode()
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/chat", body, {"Content-Type": "application/json"}), timeout=300))
    pe, ev = r["prompt_eval_duration"] / 1e9, r["eval_duration"] / 1e9
    print(f"{opts}: total {time.time()-t:.1f}s | prompt {r['prompt_eval_count']} tok {pe:.1f}s ({r['prompt_eval_count']/pe:.0f} tok/s) | gen {r['eval_count']/ev:.1f} tok/s", flush=True)
for opts in [{}, {"num_thread": 4}, {"num_thread": 3}, {"num_thread": 4, "num_batch": 64}, {"num_thread": 4, "num_ctx": 1024}]:
    go(opts, "Hi! How are you today? (%s)" % opts)

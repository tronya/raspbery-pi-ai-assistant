import json, time, urllib.request, importlib.util
spec = importlib.util.spec_from_file_location("bot", "/home/tronyak/bot.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sysmsg = m.SYSTEM
for q in ["Hi! How are you today?", "I am so tired today..."]:
    body = json.dumps({"model": "gemma3:1b", "stream": False, "keep_alive": "30m",
                       "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": q}],
                       "options": {"temperature": 0.6, "num_predict": 45, "stop": ["\n"]}}).encode()
    t = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/chat", body, {"Content-Type": "application/json"}), timeout=300))
    ev, pe = r["eval_duration"] / 1e9, r["prompt_eval_duration"] / 1e9
    print(f"total {time.time()-t:.1f}s | load {r['load_duration']/1e9:.1f}s | prompt {r['prompt_eval_count']} tok {pe:.1f}s | gen {r['eval_count']} tok {ev:.1f}s ({r['eval_count']/ev:.1f} tok/s)")

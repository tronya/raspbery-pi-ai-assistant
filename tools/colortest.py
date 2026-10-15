import importlib.util, numpy as np
spec = importlib.util.spec_from_file_location("eyes", "/home/tronyak/eyes.py")
e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)
for name in ["neutral", "thinking", "angry", "sleeping"]:
    p = dict(e.EMO[name]); p["sl"], p["sr"] = p["sl"], p["sr"]
    img = e.render(p, 1.0, True, (3.0, 0.4) if name == "thinking" else None, None)
    lit = img[img.max(axis=2) > 120]
    m = lit.mean(axis=0) if len(lit) else (0, 0, 0)
    print(f"{name:9s} colour {p['cr']:.0f},{p['cg']:.0f},{p['cb']:.0f} -> bright pixels mean R={m[0]:.0f} G={m[1]:.0f} B={m[2]:.0f} (n={len(lit)})")

import importlib.util, os
spec = importlib.util.spec_from_file_location("ui", "/home/tronyak/ui.py")
ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(ui)
app = ui.App()
app.confirm = ("Перезавантажити Pi?", ["true"])
os.makedirs("/tmp/uishots", exist_ok=True)
for name in ["home", "emotions", "marstek", "settings", "confirm", "calibrate"]:
    im = getattr(app, "draw_" + name)()
    im.save(f"/tmp/uishots/{name}.png")
    print(name, "ok", len(app.buttons), "buttons")
# contact sheet
from PIL import Image
names = ["home", "emotions", "marstek", "settings"]
sheet = Image.new("RGB", (480 * 2 + 10, 320 * 3 + 20), (60, 60, 60))
for i, n in enumerate(names):
    sheet.paste(Image.open(f"/tmp/uishots/{n}.png"), ((i % 2) * 490, (i // 2) * 330))
sheet.save("/tmp/uishots/sheet.png")
try: os.remove(ui.FLAG)
except OSError: pass

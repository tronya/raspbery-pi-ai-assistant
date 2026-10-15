import importlib.util, os, time, subprocess
spec = importlib.util.spec_from_file_location("ui", "/home/tronyak/ui.py")
ui = importlib.util.module_from_spec(spec); spec.loader.exec_module(ui)
app = ui.App()
print("eyetrack before:", ui.run("systemctl", "is-active", "eyetrack"))
app.go("camera"); time.sleep(6)
im = app.draw_camera()
print("camera frame:", None if im is None else im.size, "| buttons:", len(app.buttons), "| eyetrack during:", ui.run("systemctl", "is-active", "eyetrack"))
t = time.time(); n = 0
while time.time() - t < 5:
    if app.draw_camera() is not None: n += 1
    time.sleep(0.1)
print("frames drawn in 5 s:", n)
app.go("eyes"); time.sleep(4)
print("eyetrack after:", ui.run("systemctl", "is-active", "eyetrack"), "| flag removed:", not os.path.exists(ui.FLAG), "| rpicam still running:", bool(ui.run("pgrep", "rpicam-vid")))

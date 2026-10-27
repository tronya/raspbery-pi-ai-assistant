# Okko: a Raspberry Pi desk companion with living eyes

A small desk assistant for a **Raspberry Pi 4** with a 3.5" SPI touch screen and a camera.
It shows animated cartoon eyes that follow your face, mirror your expression, react to a Telegram chat with a
**local** language model, keep track of your work time, warn about air-raid alerts and show the state of a
Marstek home battery. Everything runs on the Pi; only Telegram messages and the alerts API leave it.

## What it does

| Part | File | What |
|---|---|---|
| Eyes | `pi/eyes.py` | 20 fps animated eyes on the framebuffer: 30+ emotions, brows, blinking, continuous breathing and micro-saccades, idle behaviours every ~15-30 s (look around, peek, double take, squint, brow raise, head tilt, slow blink, drowsy droop, eye roll, short mini-emotions), sleep with a yawn, speech bubbles, "thinking" face with a progress bar, alert banners |
| Face tracking | `pi/track.py` | YuNet face detector (OpenCV) → eyes follow you, size follows distance; FER+ reads your expression and the eyes mirror it. No frames are stored |
| Touch menu | `pi/ui.py` | Tap the screen: Marstek, camera, system, work time, emotion picker, settings (with touch calibration, reboot/shutdown) |
| Particles | `pi/particles.py` | A numpy port of the physics engine of [tronya/particles](https://github.com/tronya/particles) (attractors, swirl, flow, turbulence, gravity, orbit walls) for ~7500 particles, same colour groups and additive blending. Touch menu → Particles; a tap bursts it and cycles: three planets gathered in the middle (one dense white ball) → three separate balls → only the white one. ~20 fps |
| Bot | `pi/bot.py` | Telegram bot (owner only): chat with a local model, emotions picked by keyword rules, `/photo`, `/screen`, `/status`, `/battery`, `/work`, emotion commands |
| Work time | `pi/worktime.py` | Counts continuous time in front of the camera, welcomes you back after a break, reminds to rest |
| Alerts | `pi/alertwatch.py` | Air-raid alerts for one oblast (red eyes + Telegram) and a softer warning for neighbouring ones (alerts.in.ua API) |
| Marstek | `pi/marstek_logger.py` | Read-only logger of a Marstek battery (local UDP API) into SQLite + Telegram alerts (low, full, offline) |
| Helpers | `pi/camview.py`, `pi/fbshot.py`, `tools/` | live camera preview, framebuffer screenshot, benchmarks and test patterns |
| Services | `systemd/` | one unit per component |

## Hardware used

- Raspberry Pi 4 (2 GB is enough), metal case with a thermal pad (fans are not needed)
- 3.5" 480x320 SPI TFT, ILI9486 + XPT2046 touch ("PiScreen"-compatible)
- Camera Module on the CSI port (tested with an IMX219 IR-cut module)
- Optional: Marstek battery on the same Wi-Fi

## Setup (short version)

1. **Screen**: in `/boot/firmware/config.txt` add
   `dtparam=spi=on` and `dtoverlay=piscreen,drm,speed=16000000,rotate=90`, and for the camera `dtoverlay=imx219`.
   Keep SPI at **16 MHz**: at 32 MHz white/orange came out pink with green fringes.
   Move the console off the screen: in `cmdline.txt` use `console=tty3 vt.global_cursor_default=0` and mask `getty@tty1`.
2. **Packages**: `sudo apt install python3-pil python3-numpy python3-evdev fonts-dejavu-core`
3. **OpenCV in a venv** (the 4.x line has the cascades; 5.x dropped them):
   `python3 -m venv --system-site-packages ~/venv && ~/venv/bin/pip install "opencv-python-headless<5"`
4. **Models** into `~/models/`: YuNet `face_detection_yunet_2023mar.onnx` ([OpenCV Zoo](https://github.com/opencv/opencv_zoo)) and
   `emotion-ferplus-8.onnx` ([ONNX Model Zoo](https://github.com/onnx/models)).
5. **Ollama** (<https://ollama.com>) and `ollama pull qwen2.5:0.5b` + `ollama pull gemma3:1b`.
6. **Secrets**: copy `.env.example` to `~/.env`, fill it in, `chmod 600 ~/.env`. Never commit it.
7. **Files**: copy `pi/*.py` to the Pi's home directory, `systemd/*.service` to `/etc/systemd/system/`,
   then `sudo systemctl daemon-reload && sudo systemctl enable --now eyes eyetrack eyes-bot ui worktime alertwatch marstek-logger`.
   The scripts assume the user `tronyak` (`/home/tronyak`): change it with
   `sed -i 's#/home/tronyak#/home/YOU#g' pi/*.py tools/*.py systemd/*.service` before copying.
8. **Pair the bot**: the first start writes a one-time code to `~/.pair`; send `/start <code>` to your bot. From then on only
   your chat is served. Optional services (`alertwatch`, `marstek-logger`) can simply be left disabled.

## How the pieces talk

Plain files in `/tmp`, no daemons to wire up: `eyes_cmd` (emotion or command), `eyes_say` (speech bubble text),
`eyes_gaze` (face position from the tracker), `eyes_mood` (expression read from the face), `eyes_alert` / `eyes_warn` (alerts),
`eyes_presence` (somebody is at the desk), `eyes_pause` (give the CPU to the language model), `ui_active` (the menu owns the screen).
The eyes are the only writer of the framebuffer while the menu is closed.

## Safety and privacy notes

- Secrets live only in `~/.env`; `.gitignore` keeps it, the bot owner id (`~/.owner`), the pairing code and the databases out of git.
- Face detection, tracking, expression reading and the language models all run locally. `/photo` and `/screen` are on-demand
  uploads of one picture to your own Telegram chat; nothing is stored on the Pi afterwards.
- The Marstek logger only uses `Get*` methods and never changes the battery.
- The tracker, bot and menu use `sudo` for a few `systemctl` calls (the Pi here has passwordless sudo for its single user).

## Status

A hobby project that grew by trial and error; it works on the author's Pi. Expect rough edges. No license has been chosen yet.

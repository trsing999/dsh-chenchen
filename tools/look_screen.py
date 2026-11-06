"""给她看一眼屏幕：截屏存进她的房间。

用法：python look_screen.py
产物：<world>/room/屏幕.jpg（下采样到长边 1280、JPEG 78，兼顾清晰与体积）
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORLD = os.path.join(os.path.expanduser("~"), ".dsh", "worlds", "default")
ROOM = os.path.join(WORLD, "room")
OUT = os.path.join(ROOM, "屏幕.jpg")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "look_screen.log")


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def capture():
    from PIL import ImageGrab

    img = ImageGrab.grab(all_screens=True)
    w, h = img.size
    longest = max(w, h)
    if longest > 1280:
        scale = 1280 / longest
        img = img.resize((int(w * scale), int(h * scale)))
    os.makedirs(ROOM, exist_ok=True)
    tmp = OUT + ".tmp.jpg"
    img.convert("RGB").save(tmp, "JPEG", quality=78, optimize=True)
    os.replace(tmp, OUT)
    size = os.path.getsize(OUT)
    log("captured %dx%d -> %s (%d KB)" % (img.size[0], img.size[1], OUT, size // 1024))
    return OUT, size


if __name__ == "__main__":
    path, size = capture()
    print("OK", path, size)

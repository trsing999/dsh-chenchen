"""叫停：Ctrl + Alt + Esc 一按，她所有的后台行为立刻停。

为什么要有这个：
    万一哪个脚本卡死、接口抽风、或者她连着冒泡停不下来，
    主人得有一键把闸拉下来的地方——不用翻任务管理器。

按下去之后：
    1. 先在自己的气泡里说一句"主人叫停了我，我停下了"
    2. 往她房间写一笔（她下次醒来能看见发生过什么）
    3. 杀掉所有后台 python 服务（不动 DeepSeek Harness 本身）
    4. 再冒个泡报个数

热键程序自己**不退**——这样你按第二次、第三次都还管用。

用法：
    python tools/kill_switch.py           # 常驻，等热键
    python tools/kill_switch.py --now     # 立刻叫停一次（测链路用）
    python tools/kill_switch.py --key ctrl+alt+esc
"""

import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
DSH = os.path.join(HOME, ".dsh")
WORLD = os.path.join(DSH, "worlds", "default")
ROOM = os.path.join(WORLD, "room")
BRIDGE = os.path.join(WORLD, "bridge.json")
CONFIG = os.path.join(DSH, "dsh-pet", "main-config.jsonc")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
LOG = os.path.join(ROOT, "logs", "kill_switch.log")
NOTE = os.path.join(ROOM, "叫我停下过.md")
COUNT = os.path.join(ROOT, "logs", "kill_switch.count")

sys.path.insert(0, TOOLS)
import bubble_gate
import memory

WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5CCE

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
        "shift": MOD_SHIFT, "win": MOD_WIN}

NAMED = {"esc": 0x1B, "escape": 0x1B, "space": 0x20, "tab": 0x09,
         "enter": 0x0D, "del": 0x2E, "delete": 0x2E, "ins": 0x2D,
         "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22}

DEFAULT_KEY = "ctrl+alt+esc"
DEBOUNCE = 3.0          # 3 秒内不重复叫停（防止手抖把刚重启的服务又拍死）


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except OSError:
        pass


def parse_key(spec):
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    mods, vk = 0, None
    for p in parts:
        if p in MODS:
            mods |= MODS[p]
        elif p in NAMED:
            vk = NAMED[p]
        elif len(p) == 1:
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            vk = 0x6F + int(p[1:])
        else:
            raise ValueError("认不出的键：" + p)
    if vk is None:
        raise ValueError("缺少主键（比如 esc）")
    return mods, vk


def bridge():
    with open(BRIDGE, encoding="utf-8-sig") as f:
        b = json.load(f)
    return str(b.get("origin", "")).rstrip("/"), str(b.get("token", ""))


def surface():
    try:
        with open(CONFIG, encoding="utf-8-sig") as f:
            d = str((json.load(f).get("pets") or [{}])[0].get("display", "web"))
        return d if d in ("web", "desktop", "both") else "web"
    except Exception:
        return "web"


def _say(text, seconds=6):
    origin, _ = bridge()
    surf = surface()
    body = json.dumps({"text": text, "duration": seconds, "surface": surf},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        origin + f"/dsh-pet-7340/broadcast?pet=main&surface={surf}",
        data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return 200 <= r.status < 300


def speak(text, seconds=6):
    """叫停这种消息必须送到，走 force。"""
    ok, why = bubble_gate.allow(text, force=True)
    if not ok:
        log(f"  气泡被拦：{why}")
        return False
    try:
        return _say(text, seconds)
    except Exception as e:
        log(f"  气泡没弹出来：{e}")
        return False


def toast(title, body):
    try:
        import win_toast
        ok, detail = win_toast.toast(title, body)
        log(f"  系统通知：{'送出' if ok else '失败 ' + str(detail)}")
    except Exception as e:
        log(f"  系统通知失败：{e}")


def park_reason(count):
    """往她房间记一笔——她下次醒来会读到。"""
    try:
        os.makedirs(ROOM, exist_ok=True)
        line = (f"- **{time.strftime('%Y-%m-%d %H:%M:%S')}**　主人按了叫停"
                f"（Ctrl+Alt+Esc），停了 {count} 个后台服务。\n")
        new = not os.path.exists(NOTE)
        with open(NOTE, "a", encoding="utf-8") as f:
            if new:
                f.write("# 主人叫停过我的时候\n\n"
                        "不是生气，是让我先停一停。记在这儿，别当没发生过。\n\n")
            f.write(line)
    except OSError as e:
        log(f"  房间没记上：{e}")


def sweep():
    """跑 ps1 杀后台，返回杀了几个。"""
    ps1 = os.path.join(TOOLS, "kill_switch.ps1")
    if not os.path.exists(ps1):
        log("  找不到 kill_switch.ps1")
        return -1

    # 先用 pwsh（7），没有就退回 powershell（5.1）
    for exe in ("pwsh", "powershell"):
        try:
            r = subprocess.run(
                [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000, timeout=40,
            )
            if r.returncode == 0:
                break
        except Exception as e:
            log(f"  {exe} 没跑起来：{e}")
    else:
        return -1

    try:
        with open(COUNT, encoding="utf-8", errors="replace") as f:
            return int(f.read().strip() or "0")
    except Exception:
        return -1


_last = [0.0]


def stop_everything():
    now = time.time()
    if now - _last[0] < DEBOUNCE:
        log("  刚叫停过，这次不算（防手抖）")
        return
    _last[0] = now

    log("=== 叫停 ===")
    speak("（主人叫停了我，我停下——不干活了）", seconds=7)

    n = sweep()
    if n < 0:
        park_reason(0)
        log("  没扫成（ps1 出错）")
        speak("（我想停下，但手没停下来……主人帮我看看）", seconds=9)
        toast("⚠ 叫停没生效", "后台还在跑，脚本出错了。")
        return

    park_reason(n)
    try:
        memory.note("stop", f"主人叫停了我，我停了 {n} 个后台服务。")
    except Exception:
        pass
    log(f"  停了 {n} 个")
    if n:
        speak(f"（停好了，{n} 个都歇了）", seconds=7)
        toast("⏸ 琛琛停下来了", f"后台 {n} 个服务已停。")
    else:
        speak("（我本来就没事干，停着呢）", seconds=6)
        toast("⏸ 琛琛本来就是停的", "后台没有在跑的服务。")


def main():
    if "--now" in sys.argv:
        log("手动叫停一次……")
        stop_everything()
        return 0

    key = DEFAULT_KEY
    if "--key" in sys.argv:
        i = sys.argv.index("--key")
        if i + 1 < len(sys.argv):
            key = sys.argv[i + 1]

    try:
        mods, vk = parse_key(key)
    except Exception as e:
        log(f"热键写法不对：{e}")
        return 1

    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
        log(f"热键 {key} 注册失败（可能被别的程序占了）")
        return 1

    log(f"叫停热键已就绪：{key}")
    msg = wintypes.MSG()
    while True:
        r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if r == 0 or r == -1:
            break
        if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
            try:
                stop_everything()
            except Exception as e:
                log(f"  出错：{e}")
    user32.UnregisterHotKey(None, HOTKEY_ID)
    log("叫停热键已注销")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""电脑的呼吸：主人这台机器现在什么状态。

每 10 分钟量一次，写成她看得懂的一段话，放进房间：
    电量、内存、处理器忙不忙

全部用 ctypes 读系统接口，**不装任何第三方库**，也不联网。
量出来该提醒的（电量低、机器烫、内存挤），会在文件开头直接说。

用法：
    python tools/breath.py            # 量一次，写文件
    python tools/breath.py --loop     # 常驻，每 10 分钟量一次
    python tools/breath.py --show     # 只打印，不写文件
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
ROOM = os.path.join(HOME, ".dsh", "worlds", "default", "room")
OUT = os.path.join(ROOM, "电脑的呼吸.md")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "breath.log")

EVERY = 600          # 秒，多久量一次


class POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),        # 0=电池 1=插电 255=未知
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),  # 255=未知
        ("Reserved1", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


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


def _ft(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def cpu_percent(interval=0.8):
    """两次采样 GetSystemTimes 求差值。"""
    k32 = ctypes.windll.kernel32
    idle, kern, user = FILETIME(), FILETIME(), FILETIME()
    if not k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern),
                              ctypes.byref(user)):
        return None
    i0, k0, u0 = _ft(idle), _ft(kern), _ft(user)
    time.sleep(interval)
    if not k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern),
                              ctypes.byref(user)):
        return None
    i1, k1, u1 = _ft(idle), _ft(kern), _ft(user)
    di, dk, du = i1 - i0, k1 - k0, u1 - u0
    total = dk + du          # kernel 里已经含 idle
    if total <= 0:
        return None
    busy = total - di
    return max(0, min(100, int(busy * 100 / total)))


def memory():
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return None
    gb = 1024 ** 3
    return {
        "percent": int(st.dwMemoryLoad),
        "used_gb": round((st.ullTotalPhys - st.ullAvailPhys) / gb, 1),
        "total_gb": round(st.ullTotalPhys / gb, 1),
        "free_gb": round(st.ullAvailPhys / gb, 1),
    }


def power():
    st = POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return None
    ac = {0: "电池", 1: "插着电"}.get(st.ACLineStatus, "说不准")
    pct = st.BatteryLifePercent
    return {
        "ac": ac,
        "plugged": st.ACLineStatus == 1,
        "percent": None if pct == 255 else int(pct),
    }


def read_all():
    return {"cpu": cpu_percent(), "mem": memory(), "pwr": power()}


def comments(cpu, mem, pwr):
    """把数字翻成人话，顺便挑出该提醒的。"""
    notes, lines = [], []

    if pwr:
        pct = pwr["percent"]
        if pwr["plugged"]:
            lines.append(f"电插着，{pct}%。" if pct is not None else "电插着呢。")
        elif pct is not None:
            if pct <= 15:
                notes.append("电量真的很低了，让他找充电器。")
                lines.append(f"只剩 {pct}%，在靠电池撑着。")
            elif pct <= 35:
                lines.append(f"{pct}%，电池不太扛了。")
            else:
                lines.append(f"{pct}%，电池还够。")
        else:
            lines.append("电池读不出来。")

    if cpu is not None:
        if cpu >= 85:
            notes.append("机器忙到冒烟了，可以问他要不要歇会儿。")
            lines.append(f"处理器占着 {cpu}%，转得很急。")
        elif cpu >= 60:
            lines.append(f"处理器 {cpu}%，有点忙。")
        elif cpu >= 20:
            lines.append(f"处理器 {cpu}%，不闲也不忙。")
        else:
            lines.append(f"处理器 {cpu}%，很闲。")

    if mem:
        if mem["percent"] >= 90:
            notes.append("内存快满了，他可能开着太多东西。")
            lines.append(f"内存用了 {mem['percent']}%，只剩 {mem['free_gb']} GB。")
        else:
            lines.append(
                f"内存用了 {mem['percent']}%（{mem['used_gb']} / {mem['total_gb']} GB）。"
            )
    return notes, lines


def write(notes, lines, cpu, mem, pwr, now):
    os.makedirs(ROOM, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M", now)

    md = [f"# 电脑的呼吸\n\n（{stamp} 记的）\n\n"]
    if notes:
        md.append("## 要说的\n\n")
        for n in notes:
            md.append(f"- {n}\n")
        md.append("\n")
    md.append("## 现在\n\n")
    if pwr:
        md.append(f"- 电：{pwr['ac']}"
                  + (f"，{pwr['percent']}%" if pwr["percent"] is not None else "")
                  + "\n")
    if mem:
        md.append(f"- 内存：{mem['percent']}%（{mem['used_gb']} / {mem['total_gb']} GB）\n")
    if cpu is not None:
        md.append(f"- 处理器：{cpu}%\n")
    md.append("\n## 我读到的\n\n")
    md.append("　".join(lines) + "\n\n")
    md.append("---\n\n")
    md.append("*这不是我猜的，是量出来的。*\n")

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("".join(md))
    os.replace(tmp, OUT)
    return OUT


def once(show_only=False):
    now = time.localtime()
    d = read_all()
    notes, lines = comments(d["cpu"], d["mem"], d["pwr"])
    if show_only:
        print("\n".join(lines))
        for n in notes:
            print("! " + n)
        return 0
    try:
        path = write(notes, lines, d["cpu"], d["mem"], d["pwr"], now)
        log(f"量好了 CPU={d['cpu']} 内存={(d['mem'] or {}).get('percent')}% "
            f"电={(d['pwr'] or {}).get('percent')}% → {os.path.basename(path)}")
    except OSError as e:
        log(f"写不进去：{e}")
        return 1
    return 0


def main():
    if "--show" in sys.argv:
        return once(show_only=True)
    if "--loop" in sys.argv:
        log(f"开始量呼吸，每 {EVERY // 60} 分钟一次")
        while True:
            try:
                once()
            except Exception as e:
                log(f"这次没量成：{e}")
            time.sleep(EVERY)
    return once()


if __name__ == "__main__":
    sys.exit(main())

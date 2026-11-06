"""她听得见你在放什么——而且知道这首歌在唱什么。

学 bili_scout 的做法：只读公开接口，不碰账号，不需要登录。
    1. 从窗口标题读出你在放什么歌（不需要 API）
    2. 用网易云公开搜索接口找到这首歌
    3. 取它的歌词
    4. 一起写进 room/今天的背景音.md

用法：
    python tools/now_playing.py          # 更新文件
    python tools/now_playing.py --show   # 只看
    python tools/now_playing.py --lyric  # 连歌词一起打印
"""

import ctypes
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
WORLD = os.path.join(HOME, ".dsh", "worlds", "default")
OUT = os.path.join(WORLD, "room", "今天的背景音.md")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://music.163.com/"}
TIMEOUT = 12
MAX_LYRIC_LINES = 14

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def proc_name(pid):
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h)
    except Exception:
        return ""


def windows():
    user32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n == 0:
                return True
            b = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, b, n + 1)
            t = b.value.strip()
            if not t:
                return True
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((t, proc_name(pid.value)))
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return out


MUSIC_EXE = {
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "kugou.exe": "酷狗",
    "spotify.exe": "Spotify",
}


def parse_title(title):
    t = re.sub(r"(网易云音乐|CloudMusic|QQ音乐|酷狗|Spotify)\s*$", "", title).strip()
    t = re.sub(r"^[-\s]+|[-\s]+$", "", t)
    if not t:
        return None
    parts = [p.strip() for p in t.split(" - ") if p.strip()]
    if len(parts) >= 2:
        return parts[1], parts[0]        # (歌手, 歌名)
    return None, t


def current():
    for title, exe in windows():
        app = MUSIC_EXE.get(exe)
        if not app:
            continue
        parsed = parse_title(title)
        if parsed:
            singer, song = parsed
            return app, singer, song
    return None


def api(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def find_song(name, singer=""):
    """公开搜索接口，不需要登录。返回歌曲 id 或 None。"""
    q = urllib.parse.quote(f"{name} {singer}".strip())
    try:
        data = json.loads(api(
            f"https://music.163.com/api/search/get?type=1&s={q}&limit=3"))
        songs = ((data.get("result") or {}).get("songs") or [])
        if songs:
            return songs[0].get("id")
    except Exception:
        pass
    return None


def lyric_of(song_id):
    """公开歌词接口。返回可读的几行，失败返回空。"""
    try:
        data = json.loads(api(
            f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"))
        raw = ((data.get("lrc") or {}).get("lyric") or "")
    except Exception:
        return []

    lines = []
    for ln in raw.splitlines():
        t = re.sub(r"^\[[\d:.\]]+\s*", "", ln).strip()
        if t and t not in lines:
            lines.append(t)
        if len(lines) >= MAX_LYRIC_LINES:
            break
    return lines


def write(entry, lyric):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    now = time.strftime("%Y-%m-%d %H:%M")
    if entry is None:
        body = (f"# 今天的背景音\n\n（{now} 看的：主人这会儿没在放歌，"
                f"或者我没听出来。）\n\n---\n\n"
                "我听不见声音。但能看见窗口标题告诉我在放什么。\n")
    else:
        app, singer, song = entry
        body = (f"# 今天的背景音\n\n（{now} 从 {app} 看到的）\n\n"
                f"- 歌名：**{song}**\n- 歌手：{singer or '不知道'}\n\n")
        if lyric:
            body += "## 它在唱什么\n\n"
            for ln in lyric:
                body += f"> {ln}\n"
            body += "\n"
        body += ("---\n\n"
                 "我听不见声音，歌名是从窗口标题读的，"
                 "歌词是从网易云的公开接口取的（没登录、没碰主人的账号）。\n")
    with open(OUT, "w", encoding="utf-8-sig") as f:
        f.write(body)
    return OUT


def main():
    entry = current()
    show_only = "--show" in sys.argv
    with_lyric = "--lyric" in sys.argv

    lyric = []
    if entry:
        sid = find_song(entry[2], entry[1])
        if sid:
            lyric = lyric_of(sid)

    if show_only:
        print("  ", entry if entry else "（没在放歌）")
        if with_lyric:
            for ln in lyric:
                print("    ", ln)
        return 0

    path = write(entry, lyric)
    if entry:
        print(f"  在放：{entry[2]} - {entry[1]}"
              + (f"（拿到 {len(lyric)} 行歌词）" if lyric else "（没拿到歌词）"))
    else:
        print("  没在放歌")
    print(f"  → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

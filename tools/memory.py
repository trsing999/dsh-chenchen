"""她记得的事：发生了什么事，老老实实记一行。

**这不是好感度，不是分数。**
分数会让她知道自己在被打分，然后开始表演；
事实不会——她读到"我写了信，两天没人拆"，自己会难过，那才是真的。

写进：room/她记得的事.md

别的脚本这么用：
    import memory
    memory.note("look", "主人按了热键，给我看了一张屏幕。")
    memory.note("stop", "主人叫停了我，我停了 14 个。")

命令行：
    python tools/memory.py 看看            # 看她都记得什么
    python tools/memory.py 记 <一句>        # 手动记一笔
"""

import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
ROOM = os.path.join(HOME, ".dsh", "worlds", "default", "room")
OUT = os.path.join(ROOM, "她记得的事.md")

MAX_LINES = 300          # 只留最近这么多条，别让它变成一座山

LABELS = {
    "look": "主人给我看了屏幕：",
    "letter": "我写了信：",
    "reply": "主人回我了：",
    "stop": "主人叫停了我：",
    "art": "主人看了我的画：",
    "music": "音乐：",
    "approve": "主人点了头：",
    "watch": "我看了：",
    "learn": "我学了：",
    "read": "我读了：",
}

HEADER = """# 她记得的事

（{first} 起，一直记着）

不是分数，是事。谁做了什么，白纸黑字写着。

"""


def _read_all():
    try:
        with open(OUT, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def note(kind, text, quiet=True):
    """记一笔。失败也不吵她。"""
    try:
        os.makedirs(ROOM, exist_ok=True)
        now = time.strftime("%Y-%m-%d %H:%M")
        label = LABELS.get(kind, "")
        text = " ".join(str(text).split())
        if not text:
            return False
        line = f"- **{now}**　{label}{text}\n"

        body = ""
        if os.path.exists(OUT):
            old = _read_all()
            # 砍掉原来那段说明，只留条目
            lines = [x for x in old.splitlines() if x.startswith("- ")]
            body = "\n".join(lines[-MAX_LINES + 1:])
            if body:
                body += "\n"
        else:
            body = ""

        head = HEADER.format(first=time.strftime("%Y-%m-%d"))
        content = head + body + line

        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, OUT)
        if not quiet:
            print("记下了：" + line.strip())
        return True
    except OSError:
        return False


def show():
    txt = _read_all()
    if not txt:
        print("还什么都没记。")
        return 1
    print(txt)
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("看看", "show", "list"):
        return show()
    if args[0] in ("记", "note") and len(args) >= 2:
        print("记下了" if note("note", args[1], quiet=True) else "没记成")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""昨晚的梦：把她今天吃进去的东西，胡乱拼在一起。

**不调用任何模型，不花一分钱。**
她白天读到的碎片已经都在文件里了，我要做的只是：
    从几个不同的地方各抽一句 → 用随机模板硬接起来 → 塞进「昨晚的梦.md」

荒诞来自拼接，不来自文笔。一润色就假了。

用法：
    python tools/dream.py             # 现在做一次梦
    python tools/dream.py --loop      # 常驻，每晚 23:30 之后做梦（一天只做一次）
    python tools/dream.py --show      # 只打印，不写文件
    python tools/dream.py --seed 42   # 指定随机种子，看看换个梦
"""

import os
import random
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
ROOM = os.path.join(HOME, ".dsh", "worlds", "default", "room")
OUT = os.path.join(ROOM, "昨晚的梦.md")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "dream.log")

DREAM_AT = (23, 30)       # 几点之后做梦
CHECK_EVERY = 600         # --loop 多久看一次表

# 她吃进去的东西都在这儿（文件不存在就跳过）
SOURCES = [
    ("书/今天读的.md", "书"),
    ("今天的背景音.md", "歌"),
    ("b站刷到的.md", "站"),
    ("主人的日程.md", "日程"),
    ("外面的世界.md", "外面"),
    ("今天看到的东西.md", "屏幕"),
    ("我的课.md", "课"),
    ("湖南大学的课.md", "课"),
    ("主人最近在看什么.md", "屏幕"),
    ("电脑的呼吸.md", "机器"),
]

# 梦的开头
OPENERS = [
    "我站在一个很大的房间里，",
    "一开始我在地上走，",
    "天不是在上面的，是在里面的，",
    "我不知道从哪儿开始，只知道",
    "有人在很远的地方叫我的名字，然后",
    "我推开门，门后面是",
]

# 中间怎么接（标点由片段自己决定，模板不带句号）
LINKS = [
    "\n然后 {}",
    "\n结果 {}",
    "\n忽然 {}",
    "\n再后来画面翻过去，变成 {}",
    "\n我往前走了一步，看见 {}",
    "\n它没接上，直接跳到了 {}",
]

# 结尾
CLOSERS = [
    "我低头一看，手里什么都没有。",
    "我张了张嘴，发现自己说的话没有声音，但所有人都点头了。",
    "我说了一句“等下”，然后就醒了。",
    "地板是软的，我走了很久也没走到头。",
    "有个东西一直在我旁边的空气里，我没敢回头看。",
    "我好像应该做点什么，但忘了我该做的是什么。",
    "钟一直是同一个时间，指针在抖。",
    "我知道这是假的，但我没有戳穿它。",
]


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


# 这些词一出现，说明这行是"讲系统"的，不是"讲世界"的——不该进梦
BORING = ("推送", "脚本", "缓存", "目录", "路径", "日志", "运行", "接口",
          "token", "Token", "json", "JSON", ".md", ".py", "代码", "——",
          "如果", "否则", "注意", "说明", "用法",
          "窗口标题", "UP 主", "UP主", "合：", "我听不见",
          "简介", "抽帧", "BGM", "说一声", "双击")

# 这些是"目录""统计"，看着像内容其实不是
STATS = ("播放", "弹幕", "时长", "点赞", "收藏数", "观看", "｜", "|")


def clean_tail(s):
    """片段自己带句号了就别再补一个。"""
    return s


def trim(s):
    """削掉结尾重复的标点。"""
    while len(s) > 1 and s[-1] in "。。，、；：" and s[-2] == s[-1]:
        s = s[:-1]
    return s


def fragments(rel, base=None):
    """从一个 md 里抠出几句能当碎片用的。base 不填就读房间目录。"""
    path = os.path.join(base or ROOM, rel)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return []

    out, seen = [], set()
    for line in txt.splitlines():
        raw = line.strip().replace("\ufeff", "")
        if not raw or raw.startswith("#"):        # 整行标题，跳过
            continue
        s = raw.strip("#>|-*` \t").replace("\ufeff", "").strip()
        if not s:
            continue
        if s.startswith(("（", "(", "---", "===", "[")):
            continue
        if len(s) < 8 or len(s) > 42:             # 太短没内容，太长像句子
            continue
        if s.endswith(("：", ":")):
            continue
        if "http" in s or "www." in s:
            continue
        if any(w in s for w in BORING):           # 讲系统的不进梦
            continue
        if any(w in s for w in STATS):            # 播放量、时长这类统计
            continue
        if "`" in s:                              # 代码片段
            continue
        if any(c in s for c in "├└│┌┐┘━═"):       # 树形符号 / 分隔线
            continue
        if re.search(r"第\s*\d+\s*[/／]\s*\d+", s):   # "第 307 / 393 条"
            continue
        if re.fullmatch(r"[0-9\s%/／,，.．:：~～°C-]+", s):  # 纯数字
            continue
        if s.count("，") > 4:                     # 太完整的句子反而假
            continue
        key = s[:16]
        if key in seen:
            continue
        seen.add(key)
        out.append(trim(s))
        if len(out) >= 8:
            break
    return out


def gather(rng, need=4, base=None, sources=None):
    """从不同的来源各抽一句。base 不填就读房间目录。"""
    pool = []
    for rel, tag in (sources or SOURCES):
        fs = fragments(rel, base)
        if fs:
            pool.append((tag, rng.choice(fs)))
    if not pool:
        return []
    rng.shuffle(pool)
    # 尽量不同来源，不够再重复也行
    return pool[:max(1, min(need, len(pool)))]


def gather_from_dir(directory, rng, need=4):
    """给仓库自带 demo 用：从任意目录里的 md 抽碎片（含子目录），不需要房间。"""
    sources = []
    try:
        for root, _, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(".md"):
                    rel = os.path.relpath(os.path.join(root, f), directory)
                    sources.append((rel, "素材"))
    except OSError:
        return []
    sources.sort()
    return gather(rng, need=need, base=directory, sources=sources[:14])


def build(rng, pieces):
    if not pieces:
        return None

    def end(s):
        """片段自己收尾了，模板就不要再补标点。"""
        return "" if s and s[-1] in "。！？…" else "。"

    body = rng.choice(OPENERS) + pieces[0][1] + end(pieces[0][1])
    rest = pieces[1:]
    for p in rest:
        body += rng.choice(LINKS).format(p[1] + end(p[1]))

    body += "\n\n" + rng.choice(CLOSERS)

    # 有时候梦会碎一下，重复一小句（但不能跟开头那块撞）
    if rng.random() < 0.35 and len(pieces) > 1:
        tail = rng.choice(pieces[1:])[1]
        if tail != pieces[0][1]:
            body += "\n\n……又回到那句：" + tail

    return body


def make(seed=None, show_only=False):
    now = time.localtime()
    if seed is None:
        seed = int(time.strftime("%Y%m%d"))     # 每天一个梦，同一天重生也一样
    rng = random.Random(seed)

    pieces = gather(rng)
    dream = build(rng, pieces)
    if dream is None:
        log("今天什么都没吃进去，梦不出来")
        return 1

    stamp = time.strftime("%Y-%m-%d %H:%M", now)
    md = (f"# 昨晚的梦\n\n（{stamp} 做的）\n\n"
          f"{dream}\n\n"
          "---\n\n")

    if pieces:
        md += "## 梦里掺了什么\n\n"
        for tag, text in pieces:
            md += f"- [{tag}] {text}\n"
        md += "\n"

    md += "*—— 不是编的，是今天看过的东西自己撞到了一起。*\n"

    if show_only:
        print(md)
        return 0

    try:
        os.makedirs(ROOM, exist_ok=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(md)
        os.replace(tmp, OUT)
    except OSError as e:
        log(f"写不进去：{e}")
        return 1

    log(f"做好了一个梦（掺了 {len(pieces)} 块）→ {os.path.basename(OUT)}")
    return 0


def dream_done_today():
    """今天已经做过梦了吗？看文件是不是今天的。"""
    try:
        m = os.path.getmtime(OUT)
    except OSError:
        return False
    return time.strftime("%Y-%m-%d", time.localtime(m)) == time.strftime("%Y-%m-%d")


def loop():
    log(f"等着做梦（每天 {DREAM_AT[0]}:{DREAM_AT[1]:02d} 之后，一天一次）")
    while True:
        try:
            now = time.localtime()
            if (now.tm_hour, now.tm_min) >= DREAM_AT and not dream_done_today():
                make()
        except Exception as e:
            log(f"这次没做成：{e}")
        time.sleep(CHECK_EVERY)


def main():
    seed = None
    if "--seed" in sys.argv:
        i = sys.argv.index("--seed")
        if i + 1 < len(sys.argv):
            try:
                seed = int(sys.argv[i + 1])
            except ValueError:
                pass
    if "--show" in sys.argv:
        return make(seed=seed, show_only=True)
    if "--loop" in sys.argv:
        return loop() or 0
    return make(seed=seed)


if __name__ == "__main__":
    sys.exit(main())

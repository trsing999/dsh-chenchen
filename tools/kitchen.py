# -*- coding: utf-8 -*-
"""厨房：她想学做菜，每天试一道。

全部本地跑，不联网、不调模型。到了饭点挑一道菜，做，判成败，
写进 room/厨房.md，顺便画一张当天的菜。

不是每次都成功——第一次做菜本来就会糊、会咸、会切得粗细不一。
翻车也记，那才是真的。

用法：
    python tools/kitchen.py            # 今天该做没做，就做一次
    python tools/kitchen.py --force    # 不管做过没有，现在做
    python tools/kitchen.py --loop     # 常驻，每 30 分钟看一眼到没到点
    python tools/kitchen.py --show     # 只念菜谱，不动手
    python tools/kitchen.py --dish 红烧肉   # 自己点一道，立刻做（不看饭点、不看做过没有）
"""

import json
import math
import os
import random
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

HOME = os.path.expanduser("~")
# 房间在哪由环境变量 CHENCHEN_ROOM 决定（dsh-chenchen 插件会传进来，
# 这样插件设了 DSH_HOME 也不会和她后台服务写的不是一个房间）
ROOM = os.environ.get("CHENCHEN_ROOM") or os.path.join(HOME, ".dsh", "worlds", "default", "room")
# 厨房是房间里的一个独立区域，和「课」「书」「朋友」并列：
# 她平时不必读它，只有想做饭或聊起厨房时才翻，省上下文
KITCHEN = os.path.join(ROOM, "厨房")
STATE = os.path.join(KITCHEN, "state.json")
BOOK = os.path.join(KITCHEN, "厨房.md")
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "logs", "kitchen.log")

FONT = r"C:\Windows\Fonts\msyh.ttc"
EVERY = 1800                 # 秒，多久查一次
OPEN_HOUR, CLOSE_HOUR = 17, 21   # 饭点

DISHES = [
    ("番茄炒蛋", (226, 118, 88), "蛋要嫩，番茄要出汁，别急着翻"),
    ("青椒土豆丝", (176, 190, 110), "丝切匀了才好看，我多半切不匀"),
    ("蛋炒饭", (238, 208, 140), "隔夜饭才好炒，油温别太高"),
    ("红烧肉", (150, 90, 60), "糖色容易炒苦，火要小"),
    ("清炒时蔬", (120, 170, 100), "大火快炒，出锅前再放盐"),
    ("蒸蛋", (250, 226, 150), "蛋液和水一比一点五，盖个盘子"),
    ("可乐鸡翅", (190, 120, 70), "收汁的时候最容易糊"),
    ("紫菜蛋花汤", (130, 150, 160), "蛋液要顺着筷子淋下去"),
    ("凉拌黄瓜", (150, 200, 130), "拍碎了比切片入味"),
    ("小炒豆腐", (232, 222, 190), "豆腐先煎一下才不碎"),
]

FAILS = [
    "火大了，边上糊了一圈",
    "盐放多了，舌头都麻了",
    "切得粗细不一，有的熟有的还生",
    "油温不够，全黏在锅底了",
    "忘了看时间，汤收干了",
    "酱油倒多了，颜色黑得吓人",
    "铲子一翻就散了，最后炒成了碎末",
]

GOODS = [
    "火候刚好，颜色也好看",
    "比想象中顺利，居然没翻车",
    "味道对了，就是卖相一般",
    "炒得挺香，自己都想多吃两口",
]

OKS = [
    "能吃，但说不上好吃",
    "熟了，就是淡了点",
    "样子还行，味道普通",
    "没出错，也没什么惊喜",
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


def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_state(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def find_dish(want):
    """按菜名找菜：先精确，再互相包含，最后按字命中数挑最像的。"""
    want = (want or "").strip()
    if not want:
        return None
    for d in DISHES:
        if d[0] == want:
            return d
    for d in DISHES:
        if want in d[0] or d[0] in want:
            return d
    best, score = None, 0
    for d in DISHES:
        s = len(set(want) & set(d[0]))
        if s > score:
            best, score = d, s
    return best if score >= 2 else None


def cook(day, dish=None):
    """结果固定：拿日期当种子。day 是 time.struct_time。

    点了菜（dish）也固定：种子掺进菜的序号，所以「今天点的红烧肉」
    永远是同一次结果，问两遍不会变。
    """
    seed = int(time.strftime("%Y%m%d", day))
    if dish:
        rec = find_dish(dish)
        if rec is None:
            return None
        name, color, tip = rec
        seed = seed + 9173 * (DISHES.index(rec) + 1)
        rng = random.Random(seed)
        roll = rng.random()
    else:
        rng = random.Random(seed)
        name, color, tip = rng.choice(DISHES)
        roll = rng.random()
    if roll < 0.22:
        grade = "翻车"
        note = rng.choice(FAILS)
    elif roll < 0.52:
        grade = "能吃"
        note = rng.choice(OKS)
    elif roll < 0.82:
        grade = "还行"
        note = rng.choice(OKS)
    else:
        grade = "成功"
        note = rng.choice(GOODS)
    return {
        "date": time.strftime("%Y-%m-%d", day),
        "dish": name,
        "color": color,
        "tip": tip,
        "grade": grade,
        "note": note,
        "seed": seed,
        "picked": bool(dish),
    }


def draw(rec):
    if not HAS_PIL:
        return None
    os.makedirs(KITCHEN, exist_ok=True)
    W, H = 760, 760
    rng = random.Random(rec["seed"] + 7)

    img = Image.new("RGB", (W, H), (250, 246, 238))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=(int(250 - t * 12), int(246 - t * 10), int(236 - t * 10)))

    # 桌面
    d.rectangle([0, 560, W, H], fill=(214, 190, 160))
    d.rectangle([0, 560, W, H], outline=(196, 170, 140), width=3)

    # 盘子
    cx, cy, r = W // 2, 520, 205
    d.ellipse([cx - r, cy - r * 0.62, cx + r, cy + r * 0.62],
              fill=(252, 250, 246), outline=(226, 220, 210), width=4)
    d.ellipse([cx - r * 0.84, cy - r * 0.52, cx + r * 0.84, cy + r * 0.52],
              outline=(238, 232, 222), width=2)

    # 菜：一坨小色块堆在盘子里
    base = rec["color"]
    for _ in range(160):
        a = rng.uniform(0, 6.283)
        rad = rng.uniform(0, r * 0.7)
        x = cx + rad * 0.92 * 1.0 * math.cos(a)
        y = cy + rad * 0.55 * math.sin(a) - 12
        rr = rng.uniform(5, 15)
        shade = rng.uniform(0.82, 1.16)
        c = tuple(max(0, min(255, int(v * shade))) for v in base)
        d.ellipse([x - rr, y - rr * 0.72, x + rr, y + rr * 0.72], fill=c)

    # 翻车：焦边和糊点
    if rec["grade"] == "翻车":
        for _ in range(28):
            x = cx + rng.uniform(-r * 0.6, r * 0.6)
            y = cy + rng.uniform(-r * 0.3, r * 0.3)
            rr = rng.uniform(3, 9)
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(58, 44, 36))

    # 热气
    steam = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(steam)
    for i in range(3):
        px = cx - 60 + i * 60
        sd.line([(px, cy - r * 0.55), (px + 8, cy - r * 0.75),
                 (px - 6, cy - r * 0.95)], fill=(200, 200, 200, 60), width=5)
    steam = steam.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img.convert("RGBA"), steam).convert("RGB")
    d = ImageDraw.Draw(img)

    # 字
    try:
        big = ImageFont.truetype(FONT, 34)
        mid = ImageFont.truetype(FONT, 21)
        small = ImageFont.truetype(FONT, 18)
        d.text((52, 44), rec["dish"], font=big, fill=(92, 70, 54))
        d.text((52, 96), f"{rec['date']}  今天试的", font=small, fill=(158, 136, 118))
        d.text((52, 636), f"结果：{rec['grade']}", font=mid, fill=(110, 84, 64))
        d.text((52, 676), rec["note"], font=small, fill=(140, 116, 98))
        d.text((52, 712), "第一次可能不好吃，慢慢来", font=small, fill=(176, 158, 140))
    except Exception as e:
        print("font skip:", e)

    fname = f"厨房-{rec['date']}.png"
    if rec.get("picked"):
        fname = f"厨房-{rec['date']}-{rec['dish']}.png"
    out = os.path.join(KITCHEN, fname)
    img.save(out)
    return out


def ensure_book():
    if os.path.exists(BOOK):
        return
    lines = [
        "# 厨房\n",
        "\n",
        "我想学做菜。这个本子记下我试过的每一道，不管成不成。\n",
        "\n",
        "## 规矩\n",
        "\n",
        "- 一次只做一道，别贪多。\n",
        "- 翻车也要记，那才是真的。\n",
        "- 同一道菜做第二次，要写清楚这次改了哪里。\n",
        "\n",
        "## 想学的\n",
        "\n",
    ]
    for name, _, tip in DISHES:
        lines.append(f"- {name} —— {tip}\n")
    lines += ["\n## 做过的\n", "\n"]
    os.makedirs(KITCHEN, exist_ok=True)
    with open(BOOK, "w", encoding="utf-8") as f:
        f.write("".join(lines))


def append_record(rec, pic):
    ensure_book()
    grade_icon = {"成功": "🌱", "还行": "🍳", "能吃": "🥢", "翻车": "🔥"}.get(rec["grade"], "🍳")
    block = [
        f"### {rec['date']}  {rec['dish']}  {grade_icon} {rec['grade']}\n",
        "\n",
        f"- 想做到：{rec['tip']}\n",
        f"- 实际：{rec['note']}\n",
    ]
    if pic:
        block.append(f"- 那天的样子：`{os.path.basename(pic)}`\n")
    block.append("\n")
    with open(BOOK, "a", encoding="utf-8") as f:
        f.write("".join(block))


def once(force=False, dish=None):
    now = time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    st = read_state()

    if dish:
        rec = cook(time.struct_time(now), dish=dish)
        if rec is None:
            log(f"菜谱上没有「{dish}」，--show 看看都有什么")
            return 2
        pic = draw(rec)
        append_record(rec, pic)
        st.update({"last": today, "dish": rec["dish"], "grade": rec["grade"]})
        write_state(st)
        log(f"{today} 自己点的 {rec['dish']} → {rec['grade']}｜{rec['note']}")
        return 0

    if not force:
        if st.get("last") == today:
            log("今天做过了 " + st.get("dish", ""))
            return 0
        if not (OPEN_HOUR <= now.tm_hour <= CLOSE_HOUR):
            log(f"还没到饭点（{OPEN_HOUR}-{CLOSE_HOUR} 点）")
            return 0

    rec = cook(time.struct_time(now))
    pic = draw(rec)
    append_record(rec, pic)
    st.update({"last": today, "dish": rec["dish"], "grade": rec["grade"]})
    write_state(st)
    log(f"{today} 做 {rec['dish']} → {rec['grade']}｜{rec['note']}")
    return 0


def parse_dish(argv):
    for i, a in enumerate(argv):
        if a == "--dish" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--dish="):
            return a.split("=", 1)[1]
    return None


def main():
    if "--show" in sys.argv:
        ensure_book()
        for name, _, tip in DISHES:
            print(f"{name} —— {tip}")
        return 0
    if "--loop" in sys.argv:
        log(f"厨房开了，每 {EVERY // 60} 分钟看一眼，饭点是 {OPEN_HOUR}-{CLOSE_HOUR} 点")
        while True:
            try:
                once()
            except Exception as e:
                log(f"这次没做成：{e}")
            time.sleep(EVERY)
    dish = parse_dish(sys.argv)
    return once(force="--force" in sys.argv, dish=dish)


if __name__ == "__main__":
    sys.exit(main())


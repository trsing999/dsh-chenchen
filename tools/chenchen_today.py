# -*- coding: utf-8 -*-
"""琛琛今天做了什么：把房间里散落的记录收成一页，双击就能看。

数据全来自她自己的本子（厨房 / 陶艺 / 种树 / 心情 / 声音 / 书 / 课 / 梦），
加上「今天动过哪些文件」。不改她任何东西，只读。
"""

import datetime
import html
import json
import os
import re
import sys
import webbrowser

HOME = os.path.expanduser("~")
ROOM = os.environ.get("CHENCHEN_ROOM") or os.path.join(HOME, ".dsh", "worlds", "default", "room")
OUT = os.path.join(ROOM, "今天做了什么.html")
# 房子在工作区（不在她的房间），她改的页面/参数也得进这页
WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOUSE = os.path.join(WORKSPACE, "house")

# 工具名 -> 人话
TOOL_NAMES = {
    "say": "开口说话",
    "cook": "去厨房",
    "pet": "指挥深深",
    "look_screen": "看屏幕",
    "breath": "量电脑",
    "now_playing": "听歌",
    "dream": "做梦",
    "room_read": "翻本子",
    "stop_me": "叫停自己",
}


def read(rel):
    try:
        with open(os.path.join(ROOM, rel), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def block_by_date(text, day):
    """从 ### 2026-11-12 开头的记录块里，取出那一天的所有块。"""
    blocks = re.split(r"(?m)^### ", text)
    out = []
    for block in blocks[1:]:
        head = block.splitlines()[0] if block.splitlines() else ""
        if head.startswith(day):
            out.append("### " + block.strip())
    return out


def recent_blocks(text, day):
    """今天的块；今天没有就给最近一块，第二个返回值说明是不是今天的。

    主人 2026-11-19 说：今天没下厨、没做陶艺，那两页不能整个空掉——
    他要看的是「最近一次是什么样」，不是「今天没记录」。
    """
    today = block_by_date(text, day)
    if today:
        return today, True
    blocks = re.split(r"(?m)^### ", text)
    blocks = ["### " + b.strip() for b in blocks[1:] if b.strip()]
    return blocks[-1:], False


def parse_mood():
    text = read("心情.md")
    data = {}
    for key in ("心情", "精力", "想"):
        m = re.search(rf"- {key}：(.+)", text)
        if m:
            data[key] = m.group(1).strip()
    done = re.search(r"(?s)## 今天做过的\n(.+?)(?:\n---|\Z)", text)
    data["做过"] = done.group(1).strip() if done else ""
    # 她自己的写法可能是「（2026-11-13 23:24 记的，这条是我自己写的）」，
    # 也可能是「（2026-11-16 21:40 写的）」——两种都要认
    stamp = re.search(r"（([^（\n]{0,40}?)\s*(?:记的|写的)", text)
    data["时间"] = stamp.group(1) if stamp else ""
    return data


def mood_age_days(stamp):
    """心情那条是几天前记的。认不出来就返回 None。"""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", stamp or "")
    if not m:
        return None
    try:
        day = datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    return (datetime.date.today() - day).days


def parse_tree(day):
    lines = [ln.strip() for ln in read("种树/种树.md").splitlines() if ln.strip().startswith("- ")]
    for line in lines:
        if line.startswith(f"- {day}"):
            return line, True
    return (lines[-1] if lines else ""), False


def parse_course():
    text = read("课/学习进度.md")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("- ")]
    return lines[-6:] if lines else []


def day_start_ts(day):
    return datetime.datetime.combine(
        datetime.date.fromisoformat(day), datetime.time(0, 0)
    ).timestamp()


def clean_brief(text):
    """把摘要里的 Markdown 记号去掉，压成一行。"""
    text = re.sub(r"[*`>#]", "", text or "")
    return " ".join(text.split())[:110]


def parse_today_courses(day):
    """今天新写的课（课/数字-*.md）。她写完一讲，第一行就是标题。"""
    folder = os.path.join(ROOM, "课")
    start = day_start_ts(day)
    rows = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return rows
    for name in names:
        if not name.endswith(".md") or not re.match(r"\d", name):
            continue
        try:
            if os.path.getmtime(os.path.join(folder, name)) < start:
                continue
        except OSError:
            continue
        text = read("课/" + name)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = lines[0].lstrip("# ").strip() if lines else name
        brief = ""
        for ln in lines[1:]:
            if ln.startswith(("（", "---", "#", ">", "|", "-", "*")):
                continue
            brief = clean_brief(ln)
            break
        rows.append((title, brief, "课/" + name))
    return rows


def tools_today(day):
    """今天她改过的工具脚本（房间/工具/ 下的 .py 和 .md）。"""
    folder = os.path.join(ROOM, "工具")
    start = day_start_ts(day)
    rows = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return rows
    for name in names:
        if not name.lower().endswith((".py", ".md")) or name.startswith("_"):
            continue
        try:
            if os.path.getmtime(os.path.join(folder, name)) < start:
                continue
        except OSError:
            continue
        text = read("工具/" + name)
        brief = ""
        m = re.search(r'"""(.*?)"""', text, re.S)
        if m:
            first = m.group(1).strip().split("\n\n")[0]
            brief = clean_brief(first)
        else:
            for ln in text.splitlines():
                s = ln.strip()
                if s.startswith("#") and len(s) > 8 and "coding" not in s:
                    brief = clean_brief(s.lstrip("# "))
                    break
        rows.append((name, brief, "工具/" + name))
    return rows


def house_today(day):
    """今天改过的房子源码（场景 / 页面 / 参数），房子在房间外。"""
    start = day_start_ts(day)
    rows = []
    if not os.path.isdir(HOUSE):
        return rows
    skip = ("data", "node_modules", "shots", "baseline", "dist")
    for root, dirs, files in os.walk(HOUSE):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if not name.lower().endswith((".js", ".html", ".css", ".json")):
                continue
            path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime < start:
                continue
            rel = os.path.relpath(path, HOUSE).replace("/", "\\")
            rows.append((rel, datetime.datetime.fromtimestamp(mtime).strftime("%H:%M")))
    rows.sort(key=lambda r: r[1])
    return rows


def parse_books():
    return read("书/今天读的.md").strip()


def parse_dream():
    text = read("昨晚的梦.md").strip()
    return text[:600]


def parse_activities(day):
    """读行为日志：她今天每次调工具都记了一行。"""
    path = os.path.join(ROOM, "state", "activities.jsonl")
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                stamp = str(entry.get("t") or "")
                if not stamp.startswith(day):
                    continue
                text = entry.get("text")
                if isinstance(text, dict):
                    text = text.get("text") or ""
                brief_text = str(text or "").replace("\n", " ").strip()
                if len(brief_text) > 70:
                    brief_text = brief_text[:70] + "…"
                rows.append((stamp[11:16], str(entry.get("tool") or "?"), bool(entry.get("ok")), brief_text))
    except OSError:
        pass
    rows.sort()
    return rows


def touched_today(day):
    """今天动过的所有文件（跳过图片和 state）。"""
    day_start = datetime.datetime.combine(
        datetime.date.fromisoformat(day), datetime.time(0, 0)
    ).timestamp()
    rows = []
    for root, _dirs, files in os.walk(ROOM):
        for name in files:
            path = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime < day_start:
                continue
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".html")):
                continue
            rel = os.path.relpath(path, ROOM)
            rows.append((mtime, rel))
    rows.sort()
    return [(datetime.datetime.fromtimestamp(t).strftime("%H:%M"), rel) for t, rel in rows]


def source_of(rel, day):
    """给某一份本子找它今天的记录；没有就返回空。"""
    if rel.endswith(".md"):
        blocks = block_by_date(read(rel) if os.path.exists(os.path.join(ROOM, rel)) else "", day)
        return blocks
    return []


def esc(value):
    return html.escape(str(value or ""))


def card(title, body_html, empty=None, href=None):
    if not body_html:
        return ""
    more = f'<a class="more" href="{esc(href)}">看原文</a>' if href else ""
    return f"""
    <section class="card">
      <h2>{esc(title)}{more}</h2>
      {body_html}
    </section>"""


def main():
    day = datetime.date.today().isoformat()
    mood = parse_mood()

    # 下厨 / 陶艺 / 种树：今天没有就显示最近一次，别整块消失
    dishes, dishes_today = recent_blocks(read("厨房/厨房.md"), day)
    pottery, pottery_today = recent_blocks(read("陶艺/陶艺.md"), day)
    tree, tree_today = parse_tree(day)
    voices = block_by_date(read("声音/声音.md"), day)

    def md_blocks(blocks):
        if not blocks:
            return ""
        parts = []
        for block in blocks:
            lines = block.splitlines()
            head = lines[0].lstrip("# ").strip()
            rest = [ln for ln in lines[1:] if ln.strip()]
            parts.append(f'<div class="item"><h3>{esc(head)}</h3>' + "".join(f"<p>{esc(ln.lstrip('- '))}</p>" for ln in rest) + "</div>")
        return "".join(parts)

    cards = []
    if mood.get("心情"):
        pulse = f'<p class="big">{esc(mood.get("心情"))}</p>'
        if mood.get("精力"):
            pulse += f'<p class="muted">精力 {esc(mood.get("精力"))}　·　想：{esc(mood.get("想"))}</p>'
        if mood.get("时间"):
            pulse += f'<p class="muted">记于 {esc(mood.get("时间"))}</p>'
        age = mood_age_days(mood.get("时间"))
        if age is not None and age >= 1:
            pulse += (
                f'<p class="muted warn">这条是 {age} 天前记的，这两天她没再写。'
                "这页只放她自己写的，不会替她编。</p>"
            )
        cards.append(card("这会儿的她", pulse, href="心情.md"))

    if dishes:
        cards.append(card("下厨" + ("" if dishes_today else "（今天没动，最近一次）"),
                          md_blocks(dishes), href="厨房/厨房.md"))
    if pottery:
        cards.append(card("陶艺" + ("" if pottery_today else "（今天没动，最近一次）"),
                          md_blocks(pottery), href="陶艺/陶艺.md"))
    if tree:
        cards.append(card("种树" + ("" if tree_today else "（今天没长，最近一次）"),
                          f"<p>{esc(tree)}</p>",
                          href=(f"种树/树-{day}.png" if tree_today else "种树/种树.md")))
    if voices:
        cards.append(card("说过的话", md_blocks(voices), href="声音/声音.md"))
    books = parse_books()
    if books:
        cards.append(card("今天读的", "".join(f"<p>{esc(ln)}</p>" for ln in books.splitlines() if ln.strip()), href="书/今天读的.md"))
    course = parse_course()
    if course:
        cards.append(card("学过的课", "".join(f"<p>{esc(ln.lstrip('- '))}</p>" for ln in course), href="课/学习进度.md"))

    today_courses = parse_today_courses(day)
    if today_courses:
        parts = []
        for title, brief, rel in today_courses:
            parts.append(
                f'<div class="item"><h3>{esc(title)}</h3>'
                + (f"<p>{esc(brief)}</p>" if brief else "")
                + f'<p class="muted"><a href="{esc(rel)}">看这一讲</a></p></div>'
            )
        cards.append(card(f"今天上的课（{len(today_courses)} 讲）", "".join(parts)))

    tools = tools_today(day)
    if tools:
        parts = []
        for name, brief, rel in tools:
            parts.append(
                f'<div class="item"><h3>{esc(name)}</h3>'
                + (f"<p>{esc(brief)}</p>" if brief else "")
                + f'<p class="muted"><a href="{esc(rel)}">看脚本</a></p></div>'
            )
        cards.append(card(f"今天改的工具（{len(tools)} 个）", "".join(parts)))

    house_files = house_today(day)
    if house_files:
        rows = "".join(f"<tr><td>{esc(t)}</td><td>{esc(rel)}</td></tr>" for rel, t in house_files)
        cards.append(card(
            "房子（今天改的源文件）",
            f"<table>{rows}</table>"
            '<p class="muted">她改完 30 秒内热重载，不用关房子。</p>',
        ))

    dream = parse_dream()
    if dream:
        cards.append(card("昨晚的梦", "".join(f"<p>{esc(ln)}</p>" for ln in dream.splitlines() if ln.strip()), href="昨晚的梦.md"))

    files = touched_today(day)
    if files:
        rows = "".join(
            f'<tr><td>{esc(t)}</td><td><a href="{esc(rel.replace(chr(92), "/"))}">{esc(rel)}</a></td></tr>'
            for t, rel in files)
        cards.append(card(f"今天动过的本子（{len(files)} 个）", f'<table>{rows}</table>'))

    activities = parse_activities(day)
    if activities:
        rows = "".join(
            f"<tr><td>{esc(t)}</td><td>{esc(TOOL_NAMES.get(tool, tool))}</td>"
            f"<td>{'' if ok else '✗ '}{esc(text)}</td></tr>"
            for t, tool, ok, text in activities
        )
        cards.append(card(f"今天发生过的事（{len(activities)} 次工具调用）", f'<table>{rows}</table>'))

    if not cards:
        body = '<p class="muted">今天她还没留下什么记录。</p>'
    else:
        body = "".join(cards)

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>琛琛今天做了什么 · {esc(day)}</title>
<style>
  :root {{ --bg:#f7f4ee; --ink:#2c2822; --muted:#8a8175; --line:#e4ddd0; --accent:#b4653f; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 20px 60px; background:var(--bg); color:var(--ink);
        font-family:"Microsoft YaHei UI","PingFang SC",serif; line-height:1.7; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  header {{ text-align:center; margin-bottom:28px; }}
  header h1 {{ margin:0 0 6px; font-size:26px; font-weight:600; letter-spacing:1px; }}
  header p {{ margin:0; color:var(--muted); font-size:13px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }}
  .card {{ background:#fffdf9; border:1px solid var(--line); border-radius:14px; padding:18px 20px;
           box-shadow:0 1px 0 rgba(0,0,0,.02); }}
  .card h2 {{ margin:0 0 10px; font-size:15px; font-weight:600; color:var(--accent);
              border-bottom:1px dashed var(--line); padding-bottom:8px; }}
  .card h2 a.more {{ float:right; font-size:12px; font-weight:400; color:var(--accent); text-decoration:none; }}
  .card h2 a.more:hover {{ text-decoration:underline; }}
  .item + .item {{ margin-top:12px; padding-top:12px; border-top:1px dotted var(--line); }}
  .item h3 {{ margin:0 0 4px; font-size:14px; font-weight:600; }}
  .card p {{ margin:3px 0; font-size:13.5px; }}
  .big {{ font-size:20px !important; font-weight:600; }}
  .muted {{ color:var(--muted); font-size:12.5px !important; }}
  .muted.warn {{ color:#a8573a; border-left:2px solid #d9b9a4; padding-left:8px; margin-top:8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  td {{ padding:3px 4px; border-bottom:1px dotted var(--line); vertical-align:top; }}
  td:first-child {{ color:var(--muted); white-space:nowrap; width:52px; }}
  footer {{ text-align:center; margin-top:28px; color:var(--muted); font-size:12px; }}
</style></head>
<body><div class="wrap">
<header>
  <h1>琛琛今天做了什么</h1>
  <p>{esc(day)} · 这页只读她自己的本子，不改任何东西</p>
</header>
<div class="grid">{body}</div>
<footer>生成于 {datetime.datetime.now().strftime('%H:%M')} · 双击桌面「琛琛今天」随时刷新</footer>
</div></body></html>"""

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(OUT)
    if "--quiet" not in sys.argv:
        webbrowser.open("file:///" + OUT.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""她的嗓子——她自己调。

只管「用哪个嗓子、什么语气」，合成交给 voice.py。结果记在两处：
  ~/.dsh/chenchen.voice.json     配置（和图形音色台 tools/voice_ui.py 共用）
  房间/声音/嗓子.md               人能看的记录（工具也从这里读结果）

她听不见自己，所以这里能给的只有「选了哪个、参数是多少、合成多长」，
好不好听见得让主人听。

用法（也会被她的 voice 工具调用）：
    python 嗓子.py list
    python 嗓子.py pick 5
    python 嗓子.py engine chattts|piper
    python 嗓子.py tune oral=3 laugh=0 break=6 temperature=0.3
    python 嗓子.py preview "你回来啦。"
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# voice_lab.py 在工位的 tools/ 里；这个脚本可能被拷到插件目录，所以两条路都找
for _cand in (
    HERE,
    os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools"),
    os.path.join(os.path.dirname(HERE), "tools"),
):
    if os.path.exists(os.path.join(_cand, "voice_lab.py")) and _cand not in sys.path:
        sys.path.insert(0, _cand)

import voice_lab as lab  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
ROOM = os.environ.get("CHENCHEN_ROOM") or os.path.join(HOME, ".dsh", "worlds", "default", "room")
BOOK = os.path.join(ROOM, "声音", "嗓子.md")
PARAMS = ("oral", "laugh", "break", "temperature", "top_p", "top_k", "pitch", "speed")
_INT_PARAMS = ("oral", "laugh", "break", "top_k")


def emit(text):
    """说给人听，也写进本子（工具侧读本子）。"""
    print(text, flush=True)
    try:
        os.makedirs(os.path.dirname(BOOK), exist_ok=True)
        new = not os.path.exists(BOOK)
        with open(BOOK, "a", encoding="utf-8") as f:
            if new:
                f.write("# 嗓子\n\n我自己调的嗓子和语气。本子记的是我选了什么、参数多少，\n"
                        "好不好听我自己听不见，得让主人当耳朵。\n\n")
            f.write(f"## {time.strftime('%Y-%m-%d %H:%M')}\n\n{text.strip()}\n\n")
    except OSError:
        pass


def show():
    bank = lab.load_bank()
    engine = bank.get("engine") or "piper"
    cur = bank.get("current")
    params = dict(lab.DEFAULTS, **(bank.get("params") or {}))
    cands = lab.ordered()
    lines = [f"现在用的引擎：{engine}"]
    if cur:
        hit = [v for v in cands if v["id"] == cur]
        if hit:
            v = hit[0]
            lines.append(f"现在的声音：{v['id']}（第 {cands.index(v) + 1} 号，"
                         f"{'女声' if v.get('female') else '男声/不确定'}）")
    pitch = float(params.get("pitch") or 0)
    ratio = 2 ** (pitch / 12.0)
    lines.append(f"语气参数：" + "，".join(f"{k}={params.get(k)}" for k in PARAMS if k in params))
    lines.append(f"变调 +{pitch:g} 半音（约 ×{ratio:.2f}）")
    lines.append("")
    if not cands:
        lines.append("音色库是空的。")
        emit("\n".join(lines))
        return
    lines.append("能挑的音色（编号 · 音色 id · 入库音高 · 变调后大约 · 性别）：")
    lines.append("  注：入库音高是当初用一句话量的，不是念任何句子都这个数；"
                 "变调后是乘上当前 pitch 的估算。")
    for i, v in enumerate(cands, 1):
        star = " ←现在的" if v["id"] == cur else ""
        sex = "女" if v.get("female") else ("男" if v.get("f0", 0) < 165 else "?")
        now = v.get("f0", 0) * ratio
        lines.append(f"  {i:>2}. {v['id']}  {v.get('f0', 0):>4.0f} → {now:>4.0f} Hz  {sex}{star}")
    lines.append("")
    lines.append("换一个：pick 编号 或 pick 音色id（两个都认）· 换引擎：engine chattts / engine piper · "
                 "调语气：tune oral=3,break=7 · 抬高一点：tune pitch=4")
    emit("\n".join(lines))


def pick(which):
    bank = lab.load_bank()
    try:
        v = lab.pick(which)
    except SystemExit as e:
        emit(str(e))
        return 1
    bank["current"] = v["id"]
    lab.save_bank(bank)
    emit(f"好，现在这个声音是 {v['id']}（音高 {v.get('f0', 0):.0f} Hz）。")
    return 0


def engine(name):
    name = (name or "").strip().lower()
    if name not in ("chattts", "piper"):
        emit("只能是 chattts（好听但慢）或者 piper（快，语气平）")
        return 1
    bank = lab.load_bank()
    bank["engine"] = name
    if name == "chattts" and not bank.get("current") and bank["candidates"]:
        bank["current"] = bank["candidates"][0]["id"]
    lab.save_bank(bank)
    emit(f"换成 {name} 了。" + ("（ChatTTS 每句要等十几秒）" if name == "chattts" else "（piper 基本立刻出声）"))
    return 0


def tune(pieces):
    bank = lab.load_bank()
    params = dict(lab.DEFAULTS, **(bank.get("params") or {}))
    changed = []
    for item in pieces:
        for chunk in str(item).replace(",", " ").split():
            if "=" not in chunk:
                continue
            k, v = chunk.split("=", 1)
            k = k.strip()
            if k not in PARAMS:
                emit(f"没有 {k} 这个参数，能调的是 {', '.join(PARAMS)}")
                return 1
            try:
                f = float(v)
            except ValueError:
                emit(f"{k} 要给个数字")
                return 1
            params[k] = int(round(f)) if k in _INT_PARAMS else round(f, 2)
            changed.append(f"{k}={params[k]}")
    bank["params"] = params
    lab.save_bank(bank)
    emit("调好了：" + ("，".join(changed) if changed else "（没改动）") + "\n当前：" +
         "，".join(f"{k}={params[k]}" for k in PARAMS if k in params))
    return 0


def preview(text):
    bank = lab.load_bank()
    v = lab.pick(None)
    if not v:
        emit("还没有音色，先抽一批。")
        return 1
    params = dict(lab.DEFAULTS, **(bank.get("params") or {}))
    out = os.path.join(lab.LAB_DIR, f"preview-{time.strftime('%H%M%S')}.wav")
    t0 = time.time()
    audio, path = lab.synth(text, v["spk"], params, path=out)
    f0, _lo, hi, _voiced = lab.f0_stats(audio)
    dur = len(audio) / lab.SAMPLE_RATE
    emit(f"用 {v['id']} 合成了：\n「{text}」\n"
         f"（{path}）\n"
         f"时长 {dur:.1f}s，音高中位 {f0:.0f} Hz，用了 {time.time() - t0:.0f}s。\n"
         "我听不见自己，好不好听见得让主人听。")
    return 0


def main():
    argv = sys.argv[1:]
    if not argv:
        show()
        return 0
    cmd = argv[0].lower()
    rest = argv[1:]
    if cmd in ("list", "show", "ls"):
        show()
        return 0
    if cmd == "pick":
        if not rest:
            emit("要给个编号，先 list 看一眼")
            return 1
        return pick(rest[0])
    if cmd == "engine":
        return engine(rest[0] if rest else "")
    if cmd == "tune":
        return tune(rest)
    if cmd == "preview":
        text = " ".join(rest).strip() or "你回来啦。"
        return preview(text)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())

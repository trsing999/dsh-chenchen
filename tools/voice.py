# -*- coding: utf-8 -*-
"""声音：让她说的话能听见。

全部本地跑，不调模型、零 token。

现在的引擎（按优先级）：
  piper —— 本地神经网络语音（onnx 模型，完全离线）。本机装的是 zh_CN-huayan-medium，
           中文女声，比 SAPI 自然得多。模型在 ~/.dsh/piper-voices/ 下。
  sapi  —— Windows 自带的 System.Speech，离线可用，但本机只有 Huihui / Yaoyao / Kangkang
           三个十几年前的老引擎。
  edge  —— 微软 Edge 的神经网络声音（zh-CN-XiaoxiaoNeural 之类），最好听，
           但要连 speech.platform.bing.com；这台机器直连超时、代理也没开，只是留着的口子。

用法：
    python tools/voice.py --text "今天翻车了" --play
    python tools/voice.py --file room/声音/要念的.txt --play
    python tools/voice.py --show                  # 看本机有哪些引擎/声音
    python tools/voice.py --engine sapi --text "试试老的"
    python tools/voice.py --speed 1.15 --text "快一点，活泼一点"
    python tools/voice.py --speed 1.1 --text "快一点"
    
"""

import hashlib
import os
import re
import subprocess
import sys
import time
import wave

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOME = os.path.expanduser("~")
ROOM = os.environ.get("CHENCHEN_ROOM") or os.path.join(HOME, ".dsh", "worlds", "default", "room")
VOICE_DIR = os.path.join(ROOM, "声音")
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "voice.log")

MAX_CHARS = 300            # 一次最多念这么多字，超了截断（她的话本来就是一两句）

# 断句：句末停多久、句内逗号停多久（秒）。
# piper 自己断句会一顿一顿的，所以先在标点处切开，逐句合成，再按标点补上气口。
PAUSE_END = 0.30
PAUSE_COMMA = 0.12

# 本地神经网络语音（piper）的模型目录
PIPER_DIR = os.environ.get("CHENCHEN_PIPER_DIR") or os.path.join(HOME, ".dsh", "piper-voices")
# 优先用哪个模型（目录名）——现在的第一个是中文女声
PIPER_PREFER = ["zh_CN-huayan-medium", "zh_CN-huayan-x_low"]

# 优先这几个中文声音；找不到就退回第一个能用的
PREFERRED = [
    "Microsoft Xiaoxiao Desktop",
    "Microsoft Xiaoxiao",
    "Microsoft Yaoyao Desktop",
    "Microsoft Yaoyao",
    "Microsoft Huihui Desktop",
    "Microsoft Huihui",
    "Microsoft Xiaoyi",
]

# 动作备注（（顿了顿，声音轻一点）这种）不该念出来
PAREN = re.compile(r"[（(][^）)]{0,80}[）)]")
# 她偶尔会写 emoji / 颜文字，念出来会很怪
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF\uFE0F\u200D]+"
)
MD = re.compile(r"[*_`#>~]+")


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


def clean(text):
    """把她说的话洗成能念的：去动作备注、去 markdown、去表情。"""
    text = str(text or "")
    text = PAREN.sub("，", text)
    text = EMOJI.sub("", text)
    text = MD.sub("", text)
    text = text.replace("……", "…").replace("——", "，")
    # 折叠空白和重复标点
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.strip(" \n，,。")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip() + "…"
    return text


def ps(script, timeout=60):
    """跑一段 PowerShell，返回 (ok, stdout, stderr)。"""
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        return p.returncode == 0, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "", f"超过 {timeout} 秒没跑完"
    except Exception as e:
        return False, "", str(e)


def list_voices():
    ok, out, err = ps(
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name };"
        "$s.Dispose()"
    )
    if not ok:
        log("列声音失败：" + (err or "未知原因"))
        return []
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, culture = line.rsplit("|", 1)
        rows.append((name.strip(), culture.strip()))
    return rows


def pick_voice(prefer=None):
    voices = list_voices()
    if not voices:
        return None
    zh = [v for v in voices if v[1].startswith("zh")]
    pool = zh or voices
    if prefer:
        for name, _ in pool:
            if prefer.lower() in name.lower():
                return name
    for want in PREFERRED:
        for name, _ in pool:
            if name.lower() == want.lower():
                return name
    return pool[0][0]


def find_piper_model():
    """找本地的 piper 模型，返回 .onnx 路径；没有就 None。"""
    if not os.path.isdir(PIPER_DIR):
        return None
    for name in PIPER_PREFER:
        p = os.path.join(PIPER_DIR, name, name + ".onnx")
        if os.path.exists(p):
            return p
    # 退而求其次：目录里任何 .onnx
    for root, _dirs, files in os.walk(PIPER_DIR):
        for f in files:
            if f.endswith(".onnx"):
                return os.path.join(root, f)
    return None


def split_utterances(text):
    """按标点把话切成小块，返回 [(这一块, 说完停几秒), ...]。

    piper 自己断句时停顿忽长忽短、有时还把一句话从中间劈开；先在标点处切开、
    一块一块合成，气口就由这里说了算——句号后长一点，逗号后短一点。
    """
    out = []
    buf = []
    for ch in str(text or ""):
        buf.append(ch)
        if ch in "。！？!?；;…":
            out.append(("".join(buf).strip(), PAUSE_END))
            buf = []
        elif ch in "，,、：:":
            # 短逗号不切：「主人，」这种短称呼单独合成会起高调，和下一句接不上。
            if len("".join(buf).strip("，,、：: ")) >= 5:
                out.append(("".join(buf).strip(), PAUSE_COMMA))
                buf = []
        elif ch in "\r\n":
            out.append(("".join(buf).strip(), PAUSE_END))
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append((tail, PAUSE_END))
    out = [(piece, pause) for piece, pause in out if piece]
    # 兜底：一整块太长（常常是她一句话里没打标点），按 36 字断一口气，
    # 否则一口气念到底会像播报。
    fixed = []
    for piece, pause in out:
        while len(piece) > 36:
            fixed.append((piece[:36], PAUSE_COMMA))
            piece = piece[36:]
        if piece:
            fixed.append((piece, pause))
    # 尾巴太短就并回前一句：最后几个字单独合成容易被吞音，听着像断了
    if len(fixed) >= 2 and len(fixed[-1][0].strip("，,、：:。！？ ")) <= 4:
        fixed[-2] = (fixed[-2][0] + fixed[-1][0], fixed[-1][1])
        fixed.pop()
    return fixed


def say_piper(text, model, path, speed=1.0):
    """本地神经网络合成，写 wav。整段离线，不联网。

    只做合成 + 断句气口，不做任何移调/柔化——那些都是给 piper 打补丁，
    真正该解决的是语气，换模型才算数。
    """
    try:
        import numpy as np
        from piper import PiperVoice
        from piper.config import SynthesisConfig
    except ImportError:
        return False, "没装 piper-tts / numpy（pip install piper-tts numpy）"
    try:
        voice = PiperVoice.load(model)
        length_scale = 1.0 / max(0.5, min(2.0, speed))
        try:
            syn = SynthesisConfig(length_scale=length_scale)
        except TypeError:
            syn = None

        # 逐句合成，句间按标点补气口，最后拼成一整段
        pieces = split_utterances(text)
        if not pieces:
            return False, "没有可念的字"
        chunks = []
        rate = 22050
        for piece, pause in pieces:
            got = False
            for chunk in voice.synthesize(piece, syn_config=syn):
                rate = chunk.sample_rate
                chunks.append(np.asarray(chunk.audio_float_array, dtype=np.float32).reshape(-1))
                got = True
            if got:
                chunks.append(np.zeros(max(1, int(rate * pause)), dtype=np.float32))
        if not chunks:
            return False, "一句都没合成出来"
        audio = np.concatenate(chunks)
        pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm.tobytes())
        return True, ""
    except Exception as e:
        return False, str(e)


def say_sapi(text, voice, path, rate=0):
    """用 System.Speech 合成到 wav。"""
    # 单引号转义：PowerShell 里 ' 要写成 ''
    safe_text = text.replace("'", "''")
    safe_voice = (voice or "").replace("'", "''")
    safe_path = path.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        + (f"try {{ $s.SelectVoice('{safe_voice}') }} catch {{ }};" if safe_voice else "")
        + f"$s.Rate = {int(rate)};"
        f"$s.SetOutputToWaveFile('{safe_path}');"
        f"$s.Speak('{safe_text}');"
        "$s.Dispose()"
    )
    return ps(script, timeout=90)


def play_wav(path):
    """异步播放，不阻塞调用方。"""
    try:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception as e:
        log("播放失败：" + str(e))
        return False


def play_mp3(path):
    """mp3 用 WPF 的 MediaPlayer 播（Windows 自带解码）。"""
    safe = path.replace("'", "''")
    script = (
        "Add-Type -AssemblyName PresentationCore;"
        "$p = New-Object System.Windows.Media.MediaPlayer;"
        f"$p.Open([uri]'{safe}');"
        "$p.Play();"
        "Start-Sleep -Milliseconds 400;"
        "while ($p.NaturalDuration.HasTimeSpan -eq $false) { Start-Sleep -Milliseconds 200 };"
        "$ms = $p.NaturalDuration.TimeSpan.TotalMilliseconds;"
        "Start-Sleep -Milliseconds ([int]$ms + 300);"
        "$p.Close()"
    )
    ok, _, err = ps(script, timeout=120)
    if not ok:
        log("播 mp3 失败：" + (err or "未知原因"))
    return ok


def say_edge(text, voice, path):
    """走 @andresaya/edge-tts 生成 mp3。这台机器现在连不上，失败会返回 False。"""
    node = None
    for cand in ("node", r"C:\Program Files\nodejs\node.exe"):
        if cand == "node" or os.path.exists(cand):
            node = cand
            break
    if not node:
        return False, "找不到 node"
    pkg = os.path.join(HOME, ".dsh", "profiles", "desktop", "node_modules", "@andresaya", "edge-tts")
    if not os.path.isdir(pkg):
        return False, "找不到 @andresaya/edge-tts"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_edge_tts.cjs")
    if not os.path.exists(script):
        return False, "找不到 _edge_tts.cjs"
    try:
        p = subprocess.run(
            [node, script, pkg, text, voice, path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40,
        )
        if p.returncode != 0:
            return False, (p.stderr or "").strip()[:300] or f"退出码 {p.returncode}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "edge-tts 40 秒没返回（多半是连不上微软）"
    except Exception as e:
        return False, str(e)


def say_chattts(text, path, cfg=None, spk=None):
    """ChatTTS 合成：语气最像真人，代价是慢（一句十几到二十秒，CPU 推理）。

    音色不是随机抽的——用 `tools/voice_lab.py`（图形面板 `--ui`）挑好一个存进
    ~/.dsh/chenchen.voice.json，这里读那个。没有音色库就返回失败，让上层退回去。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import voice_lab
    except Exception as e:
        return False, f"找不到音色台模块：{e}"
    try:
        bank = voice_lab.load_bank()
        if spk:
            chosen = {"id": "自定", "spk": spk}
        else:
            chosen = voice_lab.pick(None)
        if not chosen:
            return False, "音色库是空的，先在音色台里挑一个（tools/voice_lab.py --ui）"
        params = dict(voice_lab.DEFAULTS, **(bank.get("params") or {}))
        if cfg:
            params.update(cfg)
        audio, _ = voice_lab.synth(text, chosen["spk"], params, path=path)
        return True, chosen.get("id", "")
    except Exception as e:
        return False, str(e)


def remember(text, engine, voice, path):
    """记一句她说过的话，免得念完就散了。"""
    os.makedirs(VOICE_DIR, exist_ok=True)
    book = os.path.join(VOICE_DIR, "声音.md")
    new = not os.path.exists(book)
    with open(book, "a", encoding="utf-8") as f:
        if new:
            f.write("# 声音\n\n我说过的话，能听见的那些。\n\n## 说过\n\n")
        f.write(f"### {time.strftime('%Y-%m-%d %H:%M')}  {os.path.basename(path)}\n\n")
        f.write(f"{text}\n\n")
        f.write(f"- 引擎：{engine}；声音：{voice}\n\n")


def once(text, engine="auto", voice=None, play=False, speed=1.0):
    text = clean(text)
    if not text:
        log("没有可念的字")
        return 2
    os.makedirs(VOICE_DIR, exist_ok=True)
    digest = hashlib.md5(
        (engine + (voice or "") + f"{speed:.2f}" + text).encode("utf-8")
    ).hexdigest()[:8]
    stem = os.path.join(VOICE_DIR, time.strftime("%Y-%m-%d-%H%M%S") + "-" + digest)

    model = find_piper_model()
    engine = (engine or "auto").lower()
    if engine == "auto":
        # 音色台里勾了「她平时说话就用这个」，就用 ChatTTS；否则用快而稳的 piper
        want = "piper"
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import voice_lab
            bank = voice_lab.load_bank()
            if (bank.get("engine") == "chattts") and bank.get("current"):
                want = "chattts"
        except Exception:
            pass
        engine = want if (want == "chattts" or model) else "sapi"

    if engine == "chattts":
        path = stem + ".wav"
        ok, why = say_chattts(text, path)
        if ok and os.path.exists(path):
            log(f"念了（chattts/{why}）：{text[:40]}")
            remember(text, "chattts", why or "默认音色", path)
            if play:
                play_wav(path)
            print(path)
            return 0
        log(f"chattts 不行（{why}），换本地引擎")
        engine = "piper" if model else "sapi"

    if engine == "edge":
        path = stem + ".mp3"
        ok, why = say_edge(text, voice or "zh-CN-XiaoxiaoNeural", path)
        if ok:
            log(f"念了（edge/{voice or 'Xiaoxiao'}）：{text[:40]}")
            remember(text, "edge", voice or "zh-CN-XiaoxiaoNeural", path)
            if play:
                play_mp3(path)
            print(path)
            return 0
        log(f"edge 不行（{why}），换本地引擎")
        engine = "piper" if model else "sapi"

    if engine == "piper":
        if not model:
            log("没找到 piper 模型，换 SAPI")
            engine = "sapi"
        else:
            path = stem + ".wav"
            ok, why = say_piper(text, model, path, speed)
            if ok and os.path.exists(path):
                name = os.path.basename(os.path.dirname(model))
                log(f"念了（piper/{name}）：{text[:40]}")
                remember(text, "piper", name, path)
                if play:
                    play_wav(path)
                print(path)
                return 0
            log(f"piper 不行（{why}），换 SAPI")
            engine = "sapi"

    path = stem + ".wav"
    used = voice or pick_voice()
    ok, out, err = say_sapi(text, used, path)
    if not ok or not os.path.exists(path):
        log("合成失败：" + (err or "没有生成文件"))
        return 1
    log(f"念了（sapi/{used}）：{text[:40]}")
    remember(text, "sapi", used or "默认", path)
    if play:
        play_wav(path)
    print(path)
    return 0


def arg(name, default=None):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def main():
    if "--show" in sys.argv:
        model = find_piper_model()
        if model:
            name = os.path.basename(os.path.dirname(model))
            print(f"piper：{name}（本地神经网络，离线）")
        else:
            print("piper：没有模型（见 ~/.dsh/piper-voices/）")
        rows = list_voices()
        if not rows:
            print("sapi：本机没有可用的声音。")
        for name, culture in rows:
            print(f"sapi：{name}  ({culture})")
        print("edge：要能连上 speech.platform.bing.com")
        return 0

    text = arg("--text")
    if not text:
        f = arg("--file")
        if f:
            try:
                with open(f, encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as e:
                log("读不到文件：" + str(e))
                return 1
    if not text:
        # 没给文字就从标准输入读
        if not sys.stdin.isatty():
            text = sys.stdin.read()
    if not text:
        log("要说点什么？ --text \"...\" 或者 --file 文件")
        return 2

    try:
        speed = float(arg("--speed", "1.0"))
    except ValueError:
        speed = 1.0

    return once(
        text,
        engine=(arg("--engine", "auto") or "auto").lower(),
        voice=arg("--voice"),
        play="--play" in sys.argv,
        speed=speed,
    )


if __name__ == "__main__":
    sys.exit(main())




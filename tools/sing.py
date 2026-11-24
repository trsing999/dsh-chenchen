# -*- coding: utf-8 -*-
"""绮萱唱歌：数字谱 + 歌词 -> wav。

她在会话里点歌时用这个。流程：
  1. 解析 1=C 数字简谱（1-7，0 休止，数字后加 ' 高八度、, 低八度）
  2. 每个汉字配一个音（标点不占音位，「|」分句）
  3. 生成 ustx 工程（song.ps1），再让 OpenUtau 渲染（run.ps1）
  4. 成品复制到 房间/唱歌/<名字>.wav，结果写成一段话返回

没给谱时用内置兜底旋律，并在结果里说清楚「这是兜底的，不是照谱唱的」。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]
OU = WORK / 'dl' / 'openutau'
ROOM = Path(os.environ.get('CHENCHEN_ROOM') or (Path.home() / '.dsh' / 'worlds' / 'default' / 'room'))
OUTDIR = ROOM / '唱歌'

# 兜底旋律：温柔的五声音阶小句，八音一轮
FALLBACK = [6, 1, 2, 3, 2, 1, 6, 5]

PUNCT = re.compile(r'[^\w\u4e00-\u9fff]')
LOCK = Path(os.environ.get('SING_LOCK') or (OU / '.sing.lock'))


def parse_notes(text):
    """把一个音（数字 + 可选 ' 或 ,）转成 1=C 的相对音高。休止 0 返回 None。"""
    m = re.match(r"^([0-7])(['‘’]*)([,，]*)$", text.strip())
    if not m:
        raise ValueError(f'看不懂这个音：{text!r}（要 1-7 或 0，高八度加 \'，低八度加 ,）')
    n, up, down = int(m.group(1)), len(m.group(2)), len(m.group(3))
    if n == 0:
        return None
    return n + 12 * up - 12 * down


def split_bars(text):
    return [p.strip() for p in re.split(r'[|｜]', text) if p.strip()]


def chars_of(sentence):
    return PUNCT.sub('', sentence)


def build(lyrics_text, notes_text, bpm, semitones):
    sentences = split_bars(lyrics_text)
    if not sentences:
        raise ValueError('歌词是空的')
    if notes_text:
        bars = split_bars(notes_text)
        if len(bars) != len(sentences):
            raise ValueError(f'谱分了 {len(bars)} 句，词分了 {len(sentences)} 句，对不上')
        note_bars = []
        for bar in bars:
            toks = bar.split()
            if not toks:
                toks = list(bar.replace(' ', ''))
            note_bars.append([parse_notes(t) for t in toks])
        scored = True
    else:
        note_bars = []
        for s in sentences:
            n = len(chars_of(s))
            note_bars.append([FALLBACK[i % len(FALLBACK)] for i in range(n)])
        scored = False

    lyrics, tones, durs, gaps = [], [], [], []
    for si, (sent, notes) in enumerate(zip(sentences, note_bars)):
        chars = chars_of(sent)
        if len(chars) != len(notes):
            raise ValueError(
                f'第 {si + 1} 句「{sent}」有 {len(chars)} 个字，谱有 {len(notes)} 个音，对不上。'
                '每个字要正好一个音。')
        for ci, (ch, n) in enumerate(zip(chars, notes)):
            last = ci == len(chars) - 1
            if n is None:  # 休止：跳过这个字，留空白
                if gaps:
                    gaps[-1] += 480
                continue
            pitch = 60 + (n - 1) - semitones  # 1=C 的 C4 起
            dur = 960 if last else 480
            lyrics.append(ch)
            tones.append(pitch)
            durs.append(dur)
            gaps.append(0)
        if gaps:
            gaps[-1] += 480  # 句间喘口气

    return {
        'bpm': bpm, 'lyrics': lyrics, 'tones': tones, 'durs': durs, 'gaps': gaps,
        'breath': 20, 'voicing': 88, 'gender': 10, 'tension': 0,
    }, scored


def run(cmd, timeout, logname):
    """跑 pwsh，输出写日志文件（不走管道：OpenUtau 会继承句柄，管道会一直挂住）。
    超时就把整棵进程树杀掉，别留一个 OpenUtau 在后台。"""
    log = OU / logname
    with open(log, 'w', encoding='utf-8', errors='replace') as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(OU))
        try:
            p.wait(timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)],
                           capture_output=True)
            raise
    return log.read_text(encoding='utf-8', errors='replace')


def report(text):
    """结果写成一段话，工具层读这个文件。成功失败都写，别留旧内容误导。"""
    try:
        OUTDIR.mkdir(parents=True, exist_ok=True)
        (OUTDIR / '最近一首.md').write_text(text.strip() + '\n', encoding='utf-8')
    except OSError:
        pass
    print(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lyrics', required=True, help='歌词，「|」分句')
    ap.add_argument('--notes', default='', help='数字简谱，空格分隔，「|」分句；不给就用兜底旋律')
    ap.add_argument('--name', default='', help='成品名字（默认用时间）')
    ap.add_argument('--bpm', type=int, default=120)
    ap.add_argument('--semitones', type=int, default=0, help='整首降几个半音（正数=降）')
    a = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    name = a.name.strip() or time.strftime('唱歌-%Y%m%d-%H%M%S')
    name = re.sub(r'[\\/:*?"<>|]', '_', name)

    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < 180:
            report(f'上一首还在唱（{int(age)} 秒前开始的），等它唱完再点。')
            return 2
        LOCK.unlink(missing_ok=True)

    try:
        data, scored = build(a.lyrics, a.notes, a.bpm, a.semitones)
    except ValueError as e:
        report(str(e))
        return 1

    LOCK.write_text(str(os.getpid()), encoding='utf-8')
    try:
        work = OU / '_工程'
        work.mkdir(exist_ok=True)
        js = work / f'{name}.json'
        ustx = work / f'{name}.ustx'
        import json
        js.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
        out = run(['pwsh', '-NoProfile', '-File', str(OU / 'speak.ps1'),
                   '-Json', str(js), '-Ustx', str(ustx)], 120, '_sing-建工程.log')
        if 'SAVED' not in out:
            report('建工程失败：' + out[-400:])
            return 1
        out = run(['pwsh', '-NoProfile', '-File', str(OU / 'run.ps1'), '-Ustx', str(ustx)],
                  260, '_sing-渲染.log')
        if 'OK ->' not in out:
            report('渲染没成，日志在 `dl/openutau/_sing-渲染.log`：\n' + out[-400:])
            return 1
        src = Path(out.split('OK ->')[1].split()[0])
        dst = OUTDIR / f'绮萱-{name}.wav'
        shutil.copy2(src, dst)
        secs = sum(d + g for d, g in zip(data['durs'], data['gaps'])) / 480 * 60 / a.bpm
        head = '唱好了。' if scored else '唱好了（这段调是我临时兜底配的，不是照谱唱的）。'
        how = '照你的数字谱唱的' if scored else '给我数字谱就能照你自己的调唱'
        nchars = len(data['lyrics'])
        extra = f'，整首降 {a.semitones} 个半音' if a.semitones else '，没降调'
        report(
            f'{head}\n\n'
            f'- 文件：{dst}\n'
            f'- 长短：约 {secs:.1f} 秒，{nchars} 个字，{a.bpm} BPM{extra}\n'
            f'- 谱：{how}\n\n'
            '想发给主人，就把这个 wav 放进 `房间/微信文件/`，它会自己发出去。'
        )
        return 0
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())

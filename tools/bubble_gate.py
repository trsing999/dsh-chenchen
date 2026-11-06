"""气泡限流：别让琛琛刷屏。

所有往深深气泡里说话的通道，都先过这一关：

    import bubble_gate
    ok, why = bubble_gate.allow(text)
    if not ok:
        # 别发，why 里写着为什么
        ...

规则（写死的，改这里就行）：
    1. 每分钟最多 2 条
    2. 同一句话 90 秒内不重复发
    3. force=True 只给"叫停"这类必须送达的消息用

状态存在 logs/bubble_rate.json，所有进程共用。
"""

import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "logs", "bubble_rate.json")
LOCK = STATE + ".lock"

LIMIT = 2          # 每分钟最多几条
WINDOW = 60        # 窗口秒数
DEDUP = 90         # 同一句话多久内不重复


class _Lock:
    """跨进程的简单文件锁——抢不到就等一会儿，等不到就算了（宁可少发不卡死）。"""

    def __init__(self, path=LOCK, tries=40, wait=0.02):
        self.path, self.tries, self.wait = path, tries, wait
        self.fd = None

    def __enter__(self):
        for _ in range(self.tries):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                time.sleep(self.wait)
            except OSError:
                return self
        return self

    def __exit__(self, *a):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            try:
                os.unlink(self.path)
            except OSError:
                pass


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _save(d):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, STATE)
    except OSError:
        pass


def _key(text):
    """同一句话判重：去空白、截前 40 字。"""
    return " ".join(str(text).split())[:40]


def allow(text="", force=False, limit=LIMIT, window=WINDOW, dedup=DEDUP):
    """能发吗？→ (True, "") / (False, 原因)

    注意：同意之后**不**自动记账，要发成功了再调 done(text)。
    这样失败的那条不会白占额度。
    """
    if force:
        return True, ""

    now = time.time()
    with _Lock():
        d = _load()

        # 1. 滑动窗口
        times = [t for t in d.get("times", []) if now - t < window]
        if len(times) >= limit:
            left = int(window - (now - min(times))) + 1
            d["times"] = times
            _save(d)
            return False, f"太密了（{window} 秒内已说 {len(times)} 条，{left} 秒后再说）"

        # 2. 同一句话重复
        k = _key(text)
        seen = d.get("seen") or {}
        t = seen.get(k)
        if k and t and now - t < dedup:
            d["times"] = times
            _save(d)
            return False, f"这句刚说过（{int(dedup - (now - t))} 秒内不重复）"

        # 3. 过关 → 立刻记账（不等发送结果：宁可少发一条，不能拦不住）
        times.append(now)
        d["times"] = times

        if k:
            seen = {kk: tt for kk, tt in (d.get("seen") or {}).items()
                    if now - tt < dedup * 4}
            seen[k] = now
            d["seen"] = seen

        _save(d)
        return True, ""


def done(text=""):
    """老接口，留着不报错。记账已经在 allow() 里做完了。"""
    return True


def stats():
    """现在还能说几句 / 最近说了什么——排查用。"""
    now = time.time()
    d = _load()
    times = [t for t in d.get("times", []) if now - t < WINDOW]
    return {"最近%d秒" % WINDOW: len(times), "上限": LIMIT,
            "还能说": max(0, LIMIT - len(times))}


def say(bubble_func, text, seconds=8, force=False):
    """一步到位：过关 → 发 → 记账。发不出去就返回 False。

    bubble_func(text, seconds) 是各脚本自己的 POST 函数。
    """
    ok, why = allow(text, force=force)
    if not ok:
        return False, why
    sent = False
    try:
        sent = bool(bubble_func(text, seconds))
    except TypeError:
        try:
            sent = bool(bubble_func(text))
        except Exception:
            sent = False
    except Exception:
        sent = False
    if sent:
        done(text)
    return sent, ("" if sent else "发送失败")


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(stats(), ensure_ascii=False))
    if len(sys.argv) > 1:
        ok, why = allow(sys.argv[1])
        print(("能发" if ok else "不能发") + ("" if ok else "：" + why))

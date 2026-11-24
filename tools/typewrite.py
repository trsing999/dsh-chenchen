# -*- coding: utf-8 -*-
"""慢写：把内容按真实打字速度一点点写进文件（给 dsh-chenchen 的 typewrite 工具用）。

主进程收到参数后，把内容落到临时文件，然后 detach 一个 worker 进程去慢慢写，
自己立刻退出——插件那边 runPy 等的是主进程，所以工具调用很快就返回。

worker 每次写 5 个字（默认），间隔 = 5 / cps 秒，每块写完都 flush + fsync，
实况页轮询到文件增长就能看到她"正在写"。

用法：
    python typewrite.py --path 目标文件 --content 内容 [--cps 1.0]
    python typewrite.py --worker --path 目标文件 --content-file 临时文件 [--cps 1.0]
"""
import argparse
import ctypes
import os
import subprocess
import sys
import tempfile
import time


def pid_alive(pid):
    """Windows 上查进程还在不在（OpenProcess 拿不到句柄就是没了）。"""
    try:
        if os.name != 'nt':
            os.kill(pid, 0)
            return True
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def acquire_lock(path):
    """同一文件同时只允许一个 worker 在写，返回 lock 路径或 None。"""
    lock = path + '.typewrite.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lock
    except FileExistsError:
        try:
            with open(lock, encoding='utf-8') as f:
                old = int(f.read().strip() or 0)
        except (OSError, ValueError):
            old = 0
        if old and pid_alive(old):
            return None          # 上一个 worker 还在写，这次不抢
        try:
            os.remove(lock)
        except OSError:
            return None
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except OSError:
            return None


def spawn_worker(args):
    worker_args = [
        sys.executable, os.path.abspath(__file__),
        '--worker', '--path', args.path,
        '--content-file', args.content_file,
        '--cps', str(args.cps), '--chunk', str(args.chunk),
    ]
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        worker_args,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def run_worker(args):
    lock = acquire_lock(args.path)
    if lock is None:
        return 3                 # 这个文件已经在慢写了
    try:
        try:
            with open(args.content_file, encoding='utf-8', errors='replace') as f:
                content = f.read()
        except OSError:
            return 1
        total = len(content)
        chunk = max(1, int(args.chunk))
        cps = max(0.05, float(args.cps))
        delay = chunk / cps

        try:
            d = os.path.dirname(os.path.abspath(args.path))
            if d:
                os.makedirs(d, exist_ok=True)
            with open(args.path, 'w', encoding='utf-8') as f:
                f.write('')
                f.flush()
                i = 0
                while i < total:
                    f.write(content[i:i + chunk])
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                    i += chunk
                    time.sleep(delay)
        except OSError:
            return 1
        return 0
    finally:
        for p in (lock, args.content_file):
            if not p:
                continue
            try:
                os.remove(p)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--content', default=None)
    ap.add_argument('--content-file', default=None)
    ap.add_argument('--cps', type=float, default=1.0)
    ap.add_argument('--chunk', type=int, default=1)   # 默认逐字写，别一下冒一段
    ap.add_argument('--worker', action='store_true')
    args = ap.parse_args()

    if args.worker:
        return run_worker(args)

    content = args.content
    if content is None and args.content_file:
        with open(args.content_file, encoding='utf-8', errors='replace') as f:
            content = f.read()
    content = content or ''

    # 内容通过临时文件交给 worker（命令行参数放几千字会被截断/转义炸）
    tmp = os.path.join(tempfile.gettempdir(), '.typewrite-%d.tmp' % os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(content)
    args.content_file = tmp
    spawn_worker(args)
    print('started', len(content))
    return 0


if __name__ == '__main__':
    sys.exit(main())

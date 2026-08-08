"""
evctl_strategy_exec.py — 启动器 (仿 server/scripts/evctl.py)

用法:
    python scripts/evctl_strategy_exec.py start      # 后台启动
    python scripts/evctl_strategy_exec.py stop       # 停止
    python scripts/evctl_strategy_exec.py status     # 查看状态
    python scripts/evctl_strategy_exec.py restart    # 重启
    python scripts/evctl_strategy_exec.py logs       # 实时日志

设计: 与 server/scripts/evctl.py 同款 4 操作, 但不依赖 EvTrade 项目任何代码
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# 路径
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_PID_FILE = _PROJECT_ROOT / "logs" / "strategy_exec.pid"
_LOG_FILE = _PROJECT_ROOT / "logs" / "strategy_exec.log"
_DEFAULT_PORT = 8001


def _ensure_logs_dir() -> None:
    (_PROJECT_ROOT / "logs").mkdir(exist_ok=True)


def _read_pid() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        # 校验进程存在
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        return None


def _is_running() -> int | None:
    """返进程 pid 或 None"""
    pid = _read_pid()
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        _PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _start() -> None:
    """后台启动 strategy_exec"""
    if _is_running():
        print("[start] already running (pid={})".format(_read_pid()))
        return
    _ensure_logs_dir()
    port = int(os.environ.get("STRATEGY_EXEC_PORT", _DEFAULT_PORT))

    cmd = [
        sys.executable, "-m", "uvicorn",
        "strategy_exec.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--log-level", os.environ.get("LOG_LEVEL", "info").lower(),
    ]
    print(f"[start] cmd: {' '.join(cmd)}")
    print(f"[start] log: {_LOG_FILE}")

    with _LOG_FILE.open("ab") as f:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_PROJECT_ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # 独立进程组
        )
    _PID_FILE.write_text(str(proc.pid))
    time.sleep(2)  # 等启动
    pid = _read_pid()
    if pid is None:
        print("[start] ❌ 启动失败, 看 log:", _LOG_FILE)
        sys.exit(1)
    print(f"[start] ✅ started (pid={pid}, port={port})")


def _stop() -> None:
    """停止 strategy_exec"""
    pid = _is_running()
    if pid is None:
        print("[stop] not running")
        return
    print(f"[stop] stopping pid={pid}...")
    try:
        os.kill(pid, signal.SIGTERM)
        # 等 5s
        for _ in range(50):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                _PID_FILE.unlink(missing_ok=True)
                print("[stop] ✅ stopped")
                return
        # 还在跑 → SIGKILL
        os.kill(pid, signal.SIGKILL)
        _PID_FILE.unlink(missing_ok=True)
        print("[stop] ✅ force killed")
    except ProcessLookupError:
        _PID_FILE.unlink(missing_ok=True)
        print("[stop] ✅ already gone")


def _status() -> None:
    pid = _is_running()
    if pid is None:
        print("[status] ❌ not running")
        sys.exit(1)
    print(f"[status] ✅ running (pid={pid})")
    port = int(os.environ.get("STRATEGY_EXEC_PORT", _DEFAULT_PORT))
    print(f"[status] port={port}, log={_LOG_FILE}")
    # 健康检查
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            body = r.read().decode()
            print(f"[status] /health => {body}")
    except Exception as e:
        print(f"[status] /health 失败: {e}")


def _restart() -> None:
    _stop()
    time.sleep(1)
    _start()


def _logs() -> None:
    if not _LOG_FILE.exists():
        print(f"[logs] log file not found: {_LOG_FILE}")
        return
    import shutil
    if shutil.which("tail"):
        subprocess.run(["tail", "-f", str(_LOG_FILE)])
    else:
        # 没 tail 命令就 dump 最后 100 行
        lines = _LOG_FILE.read_text(errors="replace").splitlines()
        print("\n".join(lines[-100:]))


def main() -> None:
    parser = argparse.ArgumentParser(description="strategy_exec process controller")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start", help="后台启动")
    sub.add_parser("stop", help="停止")
    sub.add_parser("status", help="查看状态")
    sub.add_parser("restart", help="重启")
    sub.add_parser("logs", help="实时日志 (tail -f)")

    args = parser.parse_args()
    {"start": _start, "stop": _stop, "status": _status, "restart": _restart, "logs": _logs}[args.cmd]()


if __name__ == "__main__":
    main()
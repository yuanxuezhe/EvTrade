#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EvTrade 一键启停 — 开发期进程生命周期管理 (跨平台单一 Python 入口)

Usage:
    python scripts/evctl.py start                  # 起三个
    python scripts/evctl.py stop                   # 停三个
    python scripts/evctl.py restart                # 停 + 起
    python scripts/evctl.py status                 # 看状态
    python scripts/evctl.py start backend          # 只起后端
    python scripts/evctl.py stop frontend hqserver # 停指定

约束:
    - Python 3.6.8 兼容 (无 dataclasses / walrus / capture_output+text)
    - 端口 8000 / 50998 / 8765 硬编码, 不读 env
    - 仅用标准库 (无 psutil / colorama)
"""

import os
import re
import sys
import time
import shutil
import signal
import subprocess

IS_WINDOWS = sys.platform == 'win32'

try:
    from urllib.request import urlopen
    from urllib.error import URLError, HTTPError
except ImportError:  # pragma: no cover
    urlopen = None
    URLError = HTTPError = Exception

# ============================================================================
# 常量
# ============================================================================

BACKEND_PORT = 8000
FRONTEND_PORT = 50998
HQSERVER_PORT = 8765

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
LOG_DIR = os.path.join(SCRIPT_DIR, '.logs')
PID_DIR = os.path.join(SCRIPT_DIR, '.pids')

# Windows 进程分离 flags: DETACHED_PROCESS(0x08) | CREATE_NEW_PROCESS_GROUP(0x200)
_WIN_DETACHED_FLAGS = 0x00000008 | 0x00000200

# ============================================================================
# 服务表
# ============================================================================


class Service(object):
    def __init__(self, name, port, cwd, cmd, preflight=None):
        self.name = name
        self.port = port
        self.cwd = cwd
        self.cmd = cmd
        self.log_file = os.path.join(LOG_DIR, name + '.log')
        self.pid_file = os.path.join(PID_DIR, name + '.pid')
        self.preflight = preflight or []  # list of module names to import-check


def _node_exe():
    """定位 node.exe (Windows 专用)."""
    for name in ('node.exe', 'node'):
        found = shutil.which(name)
        if found:
            return found
    return None


def _vite_cmd():
    """构造直接调 node + vite.js 的命令 (绕开 npx 在 Windows 的 .cmd 解析坑)."""
    node = _node_exe()
    if node is None:
        raise RuntimeError('node.exe not found in PATH')
    vite_js = os.path.join(
        PROJECT_ROOT, 'client', 'node_modules', 'vite', 'bin', 'vite.js'
    )
    if not os.path.exists(vite_js):
        raise RuntimeError(
            'vite not installed at ' + vite_js + ' — run `npm install` in client/'
        )
    return [
        node, vite_js,
        '--host', '0.0.0.0',
        '--port', str(FRONTEND_PORT),
        '--strictPort',
    ]


SERVICES = {
    'backend': Service(
        'backend', BACKEND_PORT,
        PROJECT_ROOT,
        [sys.executable, '-u', '-m', 'uvicorn', 'server.main:app',
         '--host', '0.0.0.0', '--port', str(BACKEND_PORT)],
        preflight=['uvicorn'],
    ),
    'frontend': Service(
        'frontend', FRONTEND_PORT,
        os.path.join(PROJECT_ROOT, 'client'),
        _vite_cmd(),
    ),
    'hqserver': Service(
        'hqserver', HQSERVER_PORT,
        os.path.join(PROJECT_ROOT, 'hq'),
        [sys.executable, '-u', 'hqserver.py'],
        preflight=['aio_pika', 'websockets'],
    ),
}

VALID_ACTIONS = ['start', 'stop', 'restart', 'status']
DEFAULT_SERVICES = ['backend', 'frontend', 'hqserver']

# ============================================================================
# 输出辅助 (无 ANSI 颜色, 跨平台一致)
# ============================================================================


def _emit(level, msg, stream):
    stream.write('[' + level + '] ' + msg + '\n')
    stream.flush()


def log_info(msg):
    _emit('INFO', msg, sys.stdout)


def log_ok(msg):
    _emit('OK', msg, sys.stdout)


def log_warn(msg):
    _emit('WARN', msg, sys.stderr)


def log_err(msg):
    _emit('ERR', msg, sys.stderr)


def _short(cmd):
    cmd = cmd.strip()
    if len(cmd) > 60:
        return cmd[:57] + '...'
    return cmd


# ============================================================================
# 平台进程工具
# ============================================================================


def find_pid_by_port(port):
    """返回占用该端口的 PID; 端口空闲返回 None."""
    if IS_WINDOWS:
        return _find_pid_by_port_windows(port)
    return _find_pid_by_port_linux(port)


def _find_pid_by_port_linux(port):
    try:
        out = subprocess.check_output(
            ['ss', '-ltnp', 'sport = :' + str(port)],
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return None
    m = re.search(r'pid=(\d+)', out)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _find_pid_by_port_windows(port):
    try:
        out = subprocess.check_output(
            ['netstat', '-ano', '-p', 'TCP'],
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return None
    needle = ':' + str(port) + ' '
    for line in out.splitlines():
        line = line.strip()
        if needle in line and 'LISTENING' in line:
            parts = line.split()
            if len(parts) >= 5:
                try:
                    return int(parts[-1])
                except ValueError:
                    pass
    return None


def read_cmdline(pid):
    """读取进程命令行; 失败返回 ''."""
    if pid is None:
        return ''
    if IS_WINDOWS:
        return _read_cmdline_windows(pid)
    return _read_cmdline_linux(pid)


def _read_cmdline_linux(pid):
    try:
        with open('/proc/' + str(pid) + '/cmdline', 'rb') as f:
            data = f.read()
        return data.replace(b'\x00', b' ').decode('utf-8', errors='replace').strip()
    except (IOError, OSError):
        return ''


def _read_cmdline_windows(pid):
    # Win11 24H2+ 移除了 wmic, 改走 PowerShell Get-CimInstance
    ps_cmd = (
        "(Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid) +
        "' | Select-Object -ExpandProperty CommandLine)"
    )
    try:
        out = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command', ps_cmd],
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return ''
    return out.strip()


def pid_alive(pid):
    """PID 是否还活着."""
    if pid is None or pid <= 0:
        return False
    if IS_WINDOWS:
        return _pid_alive_windows(pid)
    return _pid_alive_linux(pid)


def _pid_alive_linux(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _pid_alive_windows(pid):
    try:
        out = subprocess.check_output(
            ['tasklist', '/FI', 'PID eq ' + str(pid), '/NH', '/FO', 'CSV'],
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return False
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) >= 2:
            try:
                return int(parts[1].strip('"')) == pid
            except ValueError:
                pass
    return False


def procname(pid):
    """读取进程名 (image name / comm); 失败返回 ''."""
    if pid is None or pid <= 0:
        return ''
    if IS_WINDOWS:
        return _procname_windows(pid)
    return _procname_linux(pid)


def _procname_linux(pid):
    try:
        with open('/proc/' + str(pid) + '/comm') as f:
            return f.read().strip()
    except (IOError, OSError):
        return ''


def _procname_windows(pid):
    try:
        out = subprocess.check_output(
            ['tasklist', '/FI', 'PID eq ' + str(pid), '/NH', '/FO', 'CSV'],
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=3,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, OSError):
        return ''
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if parts:
            return parts[0].strip('"')
    return ''


def kill_tree(pid, timeout=3):
    """杀进程树; SIGTERM → 等 timeout → SIGKILL."""
    if pid is None or not pid_alive(pid):
        return
    if IS_WINDOWS:
        _kill_tree_windows(pid)
        return
    _kill_tree_unix(pid, timeout)


def _kill_tree_unix(pid, timeout):
    # 先 SIGTERM 整个进程组
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return
    end = time.time() + timeout
    while time.time() < end:
        if not pid_alive(pid):
            return
        time.sleep(0.2)
    # 兜底 SIGKILL
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def _kill_tree_windows(pid):
    subprocess.call(
        ['taskkill', '/F', '/T', '/PID', str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def kill_stragglers(pattern):
    """兜底: 用 pkill / taskkill 清掉残留进程."""
    if IS_WINDOWS:
        return
    try:
        subprocess.call(
            ['pkill', '-KILL', '-f', pattern],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        pass


# ============================================================================
# 后台 spawn
# ============================================================================


def spawn_detached(cmd, cwd, log_path, pid_file):
    """Popen 启动后台进程, 写 pid_file. 返回 Popen."""
    log_f = open(log_path, 'ab', buffering=0)
    try:
        if IS_WINDOWS:
            # Python 3.6 限制: close_fds=True 与 stdio 重定向互斥
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=_WIN_DETACHED_FLAGS,
            )
        else:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
    except Exception:
        log_f.close()
        raise
    with open(pid_file, 'w') as f:
        f.write(str(p.pid))
    return p


# ============================================================================
# 服务启动
# ============================================================================


def _preflight_check(svc):
    """启动前 import-check. Python 版本不对/依赖缺失时给出明确错误."""
    if not svc.preflight:
        return True
    missing = []
    for mod in svc.preflight:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        log_err(
            'preflight failed for ' + svc.name + ': missing module(s) ' +
            ', '.join(missing) + ' in ' + sys.executable +
            ' (Python ' + sys.version.split()[0] + ')'
        )
        return False
    return True


def start_service(svc):
    """启动单个服务. 端口被占 (非孤儿) 视为 skip-success. 真正失败返回 False."""
    name = svc.name
    port = svc.port

    port_pid = find_pid_by_port(port)
    if port_pid is not None:
        if name == 'frontend':
            cmd = read_cmdline(port_pid)
            if 'vite' in cmd or 'esbuild' in cmd:
                log_warn(
                    'port ' + str(port) + ' held by orphan (' +
                    _short(cmd) + ', pid=' + str(port_pid) +
                    '), killing and taking over'
                )
                kill_tree(port_pid, timeout=2)
                time.sleep(1)
                port_pid = find_pid_by_port(port)
                if port_pid is not None:
                    log_err('port ' + str(port) + ' still busy after kill, skip')
                    return False
            else:
                log_warn(
                    'port ' + str(port) + ' held by non-frontend process ' +
                    '(pid=' + str(port_pid) + ', cmd=' + _short(cmd) + '), skip'
                )
                return True
        else:
            log_warn(
                'port ' + str(port) + ' already in use ' +
                '(pid=' + str(port_pid) + '), skip ' + name
            )
            return True

    # 预检: import 一下确认 Python/依赖 OK
    if not _preflight_check(svc):
        return False

    # 清理 stale pid 文件
    _cleanup_stale_pidfile(svc.pid_file)

    # spawn
    try:
        p = spawn_detached(svc.cmd, svc.cwd, svc.log_file, svc.pid_file)
    except (OSError, IOError) as e:
        log_err('failed to spawn ' + name + ': ' + str(e))
        return False

    # 启动后多轮存活检查 (0.5s / 1.5s / 3.0s)
    # 父进程 (uvicorn reloader) 早期打印 "Uvicorn running" 后才 fork 子进程去 import main:app;
    # 子进程若在中段崩 (e.g. PEP 585 语法触发 TypeError), 父进程会延迟才感知并退出.
    # 单次 0.5s 检查只能挡住秒挂场景, 挡不住"父进程晚感知"型死亡.
    _SURVIVAL_CHECKPOINTS = (0.5, 1.5, 3.0)
    last_cp = 0.0
    for cp in _SURVIVAL_CHECKPOINTS:
        time.sleep(cp - last_cp)
        last_cp = cp
        if not pid_alive(p.pid):
            try:
                os.unlink(svc.pid_file)
            except OSError:
                pass
            log_err(
                name + ' (pid=' + str(p.pid) + ') died within ' +
                str(cp) + 's after start. tail of ' + svc.log_file + ':'
            )
            _tail_log(svc.log_file, 15)
            return False

    log_ok(name + ' started (pid=' + str(p.pid) + ', log=' + svc.log_file + ')')
    return True


def _tail_log(path, n):
    """打最后 n 行日志, 用于 spawn 失败时的诊断."""
    try:
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
        for line in lines[-n:]:
            sys.stderr.write('    ' + line)
        sys.stderr.flush()
    except (IOError, OSError):
        log_err('  (cannot read log)')


def _cleanup_stale_pidfile(pid_file):
    if not os.path.exists(pid_file):
        return
    try:
        old_pid = int(open(pid_file, 'r').read().strip())
        if not pid_alive(old_pid):
            os.unlink(pid_file)
    except (ValueError, IOError, OSError):
        try:
            os.unlink(pid_file)
        except OSError:
            pass


def start_backend():
    return start_service(SERVICES['backend'])


def start_frontend():
    return start_service(SERVICES['frontend'])


def start_hqserver():
    return start_service(SERVICES['hqserver'])


def start_all(services=None):
    if services is None:
        services = list(DEFAULT_SERVICES)
    fails = 0
    for name in services:
        if name not in SERVICES:
            log_err('unknown service: ' + name)
            fails += 1
            continue
        ok = start_service(SERVICES[name])
        if not ok:
            fails += 1
    if 'backend' in services:
        if wait_health():
            log_ok('backend healthy')
        else:
            log_warn('backend health check failed')
    return fails == 0


# ============================================================================
# 停止
# ============================================================================


def stop_by_pidfile(svc):
    pid_file = svc.pid_file
    if not os.path.exists(pid_file):
        return
    try:
        pid = int(open(pid_file, 'r').read().strip())
    except (ValueError, IOError, OSError):
        try:
            os.unlink(pid_file)
        except OSError:
            pass
        return
    if pid_alive(pid):
        log_info('stopping ' + svc.name + ' (pid=' + str(pid) + ')')
        kill_tree(pid, timeout=3)
    try:
        os.unlink(pid_file)
    except OSError:
        pass


def stop_all(services=None):
    # 反序: 后启动的先停, 减少前端 WS 断连噪音
    if services is None:
        reverse = list(reversed(DEFAULT_SERVICES))
    else:
        reverse = list(reversed(services))
    for name in reverse:
        if name in SERVICES:
            stop_by_pidfile(SERVICES[name])
    time.sleep(1)
    # 兜底: 端口残留检查
    for name in (services or DEFAULT_SERVICES):
        if name not in SERVICES:
            continue
        port = SERVICES[name].port
        leftover = find_pid_by_port(port)
        if leftover is not None:
            log_warn(
                'port ' + str(port) + ' still held (pid=' + str(leftover) +
                '), sweeping'
            )
            kill_tree(leftover, timeout=2)
    return True


# ============================================================================
# 健康检查
# ============================================================================


def wait_health(url=None, attempts=10, interval=1):
    if urlopen is None:
        return False
    if url is None:
        url = 'http://127.0.0.1:' + str(BACKEND_PORT) + '/api/health'
    for i in range(attempts):
        try:
            r = urlopen(url, timeout=1)
            if getattr(r, 'status', 200) == 200:
                return True
        except (URLError, HTTPError, ValueError, OSError):
            pass
        if i < attempts - 1:
            time.sleep(interval)
    return False


# ============================================================================
# 状态
# ============================================================================


def status_one(svc):
    name = svc.name
    port = svc.port
    pid_file = svc.pid_file

    port_pid = find_pid_by_port(port)
    if port_pid is not None:
        name_str = procname(port_pid) or '(unknown)'
        log_info(
            name.ljust(9) + ' port ' + str(port) +
            ' LISTEN  pid=' + str(port_pid) + '  ' + name_str
        )
    else:
        log_info(name.ljust(9) + ' port ' + str(port) + ' free')

    if os.path.exists(pid_file):
        try:
            pf_pid = int(open(pid_file, 'r').read().strip())
            if pid_alive(pf_pid):
                log_info(name.ljust(9) + ' pidfile alive pid=' + str(pf_pid))
            else:
                log_info(name.ljust(9) + ' pidfile dead pid=' + str(pf_pid))
        except (ValueError, IOError, OSError):
            log_info(name.ljust(9) + ' pidfile unreadable')
    else:
        log_info(name.ljust(9) + ' pidfile missing')


def status_all():
    for name in DEFAULT_SERVICES:
        status_one(SERVICES[name])
    if wait_health(attempts=1, interval=0):
        log_ok('GET /api/health -> 200 OK')
    else:
        log_err('GET /api/health -> FAIL')


# ============================================================================
# CLI
# ============================================================================


def parse_args(argv):
    if len(argv) < 2:
        return None, None, 'missing action (use one of: ' + ', '.join(VALID_ACTIONS) + ')'
    action = argv[1]
    if action not in VALID_ACTIONS:
        return None, None, (
            'unknown action: ' + action +
            ' (use one of: ' + ', '.join(VALID_ACTIONS) + ')'
        )
    services = argv[2:]
    if not services:
        services = list(DEFAULT_SERVICES)
    for s in services:
        if s not in SERVICES:
            return None, None, (
                'unknown service: ' + s +
                ' (use one of: ' + ', '.join(SERVICES.keys()) + ')'
            )
    return action, services, None


def restart_all(services=None):
    stop_all(services)
    time.sleep(1)
    return start_all(services)


def main():
    action, services, err = parse_args(sys.argv)
    if err:
        log_err(err)
        return 2
    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR)
    if not os.path.isdir(PID_DIR):
        os.makedirs(PID_DIR)
    if action == 'start':
        ok = start_all(services)
        return 0 if ok else 1
    if action == 'stop':
        stop_all(services)
        return 0
    if action == 'restart':
        ok = restart_all(services)
        return 0 if ok else 1
    if action == 'status':
        status_all()
        return 0
    return 0  # unreachable


if __name__ == '__main__':
    sys.exit(main())

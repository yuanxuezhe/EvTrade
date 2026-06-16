## 1. evctl.py 骨架与常量

- [x] 1.1 在 `scripts/evctl.py` 顶部定义模块级常量: `BACKEND_PORT=8000` / `FRONTEND_PORT=50998` / `HQSERVER_PORT=8765`, 用 `__file__` 推导 `PROJECT_ROOT` / `LOG_DIR` / `PID_DIR`
- [x] 1.2 定义服务表 `SERVICES = {name: Service(...)}` 含 `name` / `port` / `cwd` / `cmd` / `log_file` / `pid_file` 五个字段
- [x] 1.3 写输出辅助 `log_info` / `log_ok` / `log_warn` / `log_err`, 统一前缀 `[INFO] [OK] [WARN] [ERR]`, 不带 ANSI 颜色, 支持 stream 选择 (stdout / stderr)

## 2. 平台相关进程工具

- [x] 2.1 实现 `find_pid_by_port(port)`: Linux `ss -ltnp 'sport = :PORT'`, Windows `netstat -ano -p TCP` + 文本过滤
- [x] 2.2 实现 `read_cmdline(pid)`: Linux 读 `/proc/<pid>/cmdline`; Windows 调 `wmic process where ProcessId=N get CommandLine /value`
- [x] 2.3 实现 `pid_alive(pid)`: Linux `os.kill(pid, 0)`; Windows `tasklist /FI /FO CSV`
- [x] 2.4 实现 `kill_tree(pid, timeout=3)`: Linux SIGTERM → 等 timeout → SIGKILL, 走进程组; Windows `taskkill /F /T /PID`

## 3. 后台进程 spawn

- [x] 3.1 实现 `spawn_detached(cmd, cwd, log_path, pid_file)`: Popen + `start_new_session`(Linux) / `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`(Windows), stdout/stderr → 日志文件
- [x] 3.2 验证 PID 文件里的 PID 30 秒后 `pid_alive` 仍 True — 通过 `python scripts/evctl.py status` 实测三服务 PID alive, `/api/health` 200 OK

## 4. 服务启动

- [x] 4.1 `start_backend()`: 端口被占 warn + 跳过; 否则 `uvicorn main:app --reload`
- [x] 4.2 `start_frontend()`: 端口被占 → 读 cmdline 嗅探 vite/esbuild 孤儿, 强杀后接管
- [x] 4.3 `start_hqserver()`: 端口被占 warn + 跳过; 否则 `python hqserver.py`
- [x] 4.4 `start_all(services=None)`: backend → frontend → hqserver 串行, backend 起完后 `wait_health`

## 5. 停止

- [x] 5.1 `stop_by_pidfile(svc)`: 读 pidfile, alive → `kill_tree`; 不论结果 unlink
- [x] 5.2 `stop_all(services=None)`: hqserver → frontend → backend 反序停, 停完扫端口残留
- [x] 5.3 `kill_stragglers(pattern)`: Linux `pkill -KILL -f pattern` (Windows 上 find_pid_by_port + taskkill 兜底在 stop_all 中)

## 6. 状态与健康检查

- [x] 6.1 `wait_health(url, attempts=10, interval=1)`: `urllib.request.urlopen(url, timeout=1)`, 200 → True
- [x] 6.2 `status_one(svc)`: port LISTEN pid procname / free; pidfile alive / dead / missing
- [x] 6.3 `status_all()`: 三服务 + `/api/health` 探测 — 实测输出正常

## 7. CLI 入口

- [x] 7.1 `parse_args(argv)`: action ∈ {start, stop, restart, status}; services ⊂ {backend, frontend, hqserver}; 错 → exit 2 — 实测 `frobnicate` / `start postgres` / no-arg 都返回 2
- [x] 7.2 `main()`: dispatch + 退出码 0/1/2
- [x] 7.3 `restart_all(services=None)`: stop_all + sleep(1) + start_all
- [x] 7.4 `if __name__ == '__main__':` 守卫 + shebang `#!/usr/bin/env python3`

## 8. README

- [x] 8.1 重写 `scripts/README.md`: Usage 矩阵 / Ports / Layout / Behavior / 退出码 — 完成

## 9. 手动验证

- [x] 9.1 `python scripts/evctl.py start` → 三服务起来, 日志在 `.logs/`, pid 在 `.pids/` — **已通过**: 3.6.8 跑出 backend/frontend/hqserver 三个 PID (21372/2580/24632), backend healthy
- [x] 9.2 `python scripts/evctl.py status` → 三端口都 LISTEN, 三 pid 都 alive, `/api/health` 200 — **已通过**
- [ ] 9.3 浏览器 `http://localhost:50998` → Vue 登录页能加载 — **跳过**: 用户手动检查
- [x] 9.4 `python scripts/evctl.py restart` → 三服务不残留重启 — **已通过**: stop→sleep→start 全部三个 PID 更新
- [x] 9.5 `python scripts/evctl.py stop` → 三端口全 free, 三 pid 文件全清 — **已通过**
- [x] 9.6 `python scripts/evctl.py start backend` → 只起后端, frontend/hqserver 不动 — **已通过**: port 8000 in use → skip-warn; frontend/hqserver PID 保持不变
- [x] 9.7 模拟 vite 孤儿 → **已通过 (意外覆盖)**: 在 9.1 第二次跑时, 上一轮的 vite (pid 33032) 还在 50998, 被识别为 vite 孤儿, 报 `[WARN] port 50998 held by orphan (..., pid=33032), killing and taking over`, 强杀并接管, 报 `[OK] frontend started (pid=42944)`
- [x] 9.8 `python scripts/evctl.py start postgres` → 退出码 2 — **已通过**
- [x] 9.9 `python scripts/evctl.py frobnicate` → 退出码 2 — **已通过**
- [x] 9.10 在 Windows 上重复 9.1-9.5 — **已通过**: 当前就是 Windows (pyenv-win 3.6.8)

## 10. 旧脚本清理

- [x] 10.1 `git grep ...` → 业务代码无引用 — **已通过**: 引用只在 `PROJECT_ANALYSIS_REPORT.md` / `SPEC_P0.md` (历史文档, 不更新)
- [x] 10.2 `rm` 7 个旧脚本 — **已通过**: dev.sh / dev.cmd / dev.ps1 / _start_*.cmd×3 / restart.sh 全删
- [x] 10.3 再跑一次 9.1-9.5 确认目录里只剩 `evctl.py` + `README.md` + `.logs/` + `.pids/`, 三服务一切正常 — **已通过**: start→status→stop→status 全链路 OK
- [x] 10.4 `python --version` → 确认实际跑的 Python ≥ 3.6.8 (兼容下限) — **已通过**: `Python 3.6.8` (pyenv-win)

## 实施中发现并修的 3 个真实环境 bug

1. **`wmic` Win11 24H2+ 不可用** → `_read_cmdline_windows` 改走 PowerShell `Get-CimInstance Win32_Process -Filter 'ProcessId=N' | Select-Object -ExpandProperty CommandLine`, 无新依赖
2. **`subprocess.Popen(..., close_fds=True, stdout=log, stderr=STDOUT, ...)` Windows 3.6 抛 ValueError** → 3.6 限制: close_fds=True 与 stdio 重定向互斥 (3.7+ 放开). Windows 分支去掉 `close_fds=True`
3. **`npx` 在 `subprocess.Popen` 找不到** → Python 不自动解析 `.cmd` 后缀, 需要走 `cmd /c` 但那样 PID 变 cmd.exe 的. 改用直接 `node client/node_modules/vite/bin/vite.js` (npx 内部最终做的事)

## 实施后用户实际跑出的第 4 个 bug (post-implementation hardening)

4. **Popen 成功 ≠ 子进程真活** → 用户用 pyenv 当前激活的 3.6.81 (没装 uvicorn/aio_pika) 跑 `start`, backend/hqserver Popen 都成功, 报 `[OK] X started`, 实际 0.1s 内就死 (`No module named uvicorn`). 加双层防护:
   - **预检** (`_preflight_check`): spawn 前 `__import__()` 一下 `uvicorn` / `aio_pika` / `websockets`, 缺则报 `[ERR] preflight failed for X: missing module(s) Y in <python.exe> (Python <ver>)` 并 return False
   - **启动后存活检查**: `spawn_detached` 之后 `time.sleep(0.5)`, `pid_alive(p.pid)`. 死了就 unlink pidfile, 打 `[ERR] X (pid=N) died shortly after start. tail of <log>:`, 然后 tail 15 行日志
   - 实测: 错 Python 跑出来 backend/hqserver 都被预检挡住, frontend 正常 (走 node 不受影响); 对 Python 跑出来无影响, 三服务正常起

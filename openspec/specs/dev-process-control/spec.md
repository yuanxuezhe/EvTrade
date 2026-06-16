# dev-process-control — 开发服务进程管控

## Purpose

为本地开发提供统一的、单入口的 Python 脚本 `scripts/evctl.py`，以一致的方式在三平台（Linux / Windows / git-bash）启停三个开发服务（backend FastAPI/uvicorn 8000、frontend Vite 50998、hqserver WebSocket quotes 8765）。消除散落在 `start.sh` / `restart.sh` / `stop.sh` 中的脆弱 shell 逻辑、端口 fallback 与孤儿进程问题。

## Requirements

### Requirement: 单一 Python 入口

The system SHALL provide a single Python entry point `scripts/evctl.py` that manages the lifecycle of three development services: backend (FastAPI/uvicorn, port 8000), frontend (Vite, port 50998), and hqserver (WebSocket quotes, port 8765). The entry point SHALL be invokable as `python scripts/evctl.py <action> [services...]` on any platform (Linux, Windows, git-bash).

#### Scenario: 三平台一致调用

- **WHEN** developer runs `python scripts/evctl.py status` on Linux, Windows, or git-bash
- **THEN** output shows the same field set: ports, PID files, and backend `/api/health` status, in the same order

#### Scenario: Python 3.6.8 兼容

- **WHEN** evctl.py is run with `python` whose version is `3.6.8`
- **THEN** it imports without `SyntaxError` and runs the requested action to completion

### Requirement: 四个动作 start / stop / restart / status

The system SHALL support four actions: `start`, `stop`, `restart`, `status`. Each action SHALL accept an optional service list (default: all three). A service list SHALL be a subset of `{backend, frontend, hqserver}`; unknown service names SHALL cause a non-zero exit with a clear error message.

#### Scenario: 默认目标 = 三服务全集

- **WHEN** developer runs `python scripts/evctl.py start` with no service argument
- **THEN** backend, frontend, and hqserver are all started in sequence

#### Scenario: 子集操作

- **WHEN** developer runs `python scripts/evctl.py stop frontend hqserver`
- **THEN** only frontend and hqserver are stopped; backend is left untouched

#### Scenario: 未知服务名

- **WHEN** developer runs `python scripts/evctl.py start postgres`
- **THEN** script exits with non-zero status and prints a list of valid service names

### Requirement: 端口硬编码 8000 / 50998 / 8765

The system SHALL hardcode the three service ports as module-level constants. The script SHALL NOT read port numbers from environment variables.

#### Scenario: 不读 env

- **WHEN** developer sets `EVTRADE_API_PORT=9999` in the shell
- **THEN** evctl.py still binds backend to port 8000 (env var is ignored)

#### Scenario: 端口冲突时跳过启动

- **WHEN** `start backend` is requested but port 8000 is already bound by another process
- **THEN** backend is NOT started and a warning is printed; the rest of the requested services (if any) proceed

### Requirement: 跨平台进程管理

The system SHALL abstract three platform-dependent operations: (1) find the PID bound to a given port, (2) read a process's command line, (3) kill a process tree. The abstraction SHALL detect the platform via `sys.platform` and select the appropriate implementation transparently. The caller of these helpers SHALL NOT need to know which platform is in use.

#### Scenario: Linux 路径

- **WHEN** running on Linux and `find_pid_by_port(8000)` is called
- **THEN** the helper parses `ss -ltnp 'sport = :8000'` output and returns the PID, or `None` if port is free

#### Scenario: Windows 路径

- **WHEN** running on Windows and `find_pid_by_port(8000)` is called
- **THEN** the helper parses `netstat -ano` output and returns the PID, or `None` if port is free

#### Scenario: 进程树杀 (Linux)

- **WHEN** running on Linux and `kill_tree(pid)` is called
- **THEN** the helper sends SIGTERM to the process group identified by `pid`, waits up to 3 seconds, then sends SIGKILL to any survivors

#### Scenario: 进程树杀 (Windows)

- **WHEN** running on Windows and `kill_tree(pid)` is called
- **THEN** the helper invokes `taskkill /F /T /PID <pid>` and waits for it to return

### Requirement: Vite 孤儿检测与接管

The system SHALL detect when port 50998 is held by a "stale" Vite/esbuild process (e.g. one whose parent terminal was killed via ctrl-C but the process survived). Detection SHALL be by reading the occupying process's command line and matching `vite` or `esbuild`. On detection, the system SHALL kill the stale process and proceed with the requested start.

#### Scenario: 孤儿 vite 占用 50998

- **WHEN** `start frontend` is requested and port 50998 is held by PID 1234 whose cmdline contains `vite`
- **THEN** a warning is printed identifying the orphan; PID 1234 is killed; the new vite is started; port 50998 is now held by the new vite's PID

#### Scenario: 端口被非 vite 进程占用

- **WHEN** `start frontend` is requested and port 50998 is held by PID 5678 whose cmdline does NOT contain `vite` or `esbuild`
- **THEN** a warning is printed identifying the foreign process; the new vite is NOT started; exit status is 0 (skip, not failure)

### Requirement: Vite 严格端口

The system SHALL launch Vite with `--strictPort` so that Vite does NOT silently fall back to a different port (e.g. 50999) when 50998 is unavailable. If the port is unavailable, Vite SHALL exit with an error, which the system surfaces.

#### Scenario: strictPort flag 注入

- **WHEN** `start frontend` runs
- **THEN** the spawned Vite process is `npx vite --host 0.0.0.0 --port 50998 --strictPort`

### Requirement: PID 与日志文件

The system SHALL write the actual service process PID (the one returned by `Popen`, NOT a shell wrapper PID) to `scripts/.pids/<service>.pid` on successful start. The system SHALL redirect service stdout and stderr to `scripts/.logs/<service>.log` in append mode. Stale PID files (PID file exists but process is dead) SHALL be removed on next start.

#### Scenario: PID 文件清理

- **WHEN** `start backend` is requested and `scripts/.pids/backend.pid` contains a PID that is no longer alive
- **THEN** the stale PID file is removed before the new backend is started

### Requirement: 状态输出

The system SHALL implement a `status` action that prints: (1) the three ports and whether each is LISTEN-ing (with owning PID and process name if available), (2) the contents of each PID file and whether the PID is alive, (3) the result of `GET http://127.0.0.1:8000/api/health` (200 OK or FAIL).

#### Scenario: 三服务都在跑

- **WHEN** `status` is requested and all three services are healthy
- **THEN** output shows 3 lines of `port LISTEN  PID=...`, 3 lines of `pid file alive`, and `GET /api/health -> 200 OK`

#### Scenario: 部分服务未起

- **WHEN** `status` is requested and only backend is running
- **THEN** output shows backend line normally; frontend and hqserver show `free` and `pid file missing`; `/api/health` shows 200

### Requirement: 重启 = stop + start

The system SHALL implement `restart` as `stop` followed by a 1-second pause followed by `start`. The stop and start phases SHALL each respect the requested service subset.

#### Scenario: 全量重启

- **WHEN** `restart` is requested with no service argument
- **THEN** all three services are stopped, then all three are started in sequence

#### Scenario: 单服务重启

- **WHEN** `restart backend` is requested
- **THEN** only backend is stopped and restarted; frontend and hqserver are untouched

### Requirement: 后端健康检查等待

The system SHALL poll `http://127.0.0.1:8000/api/health` for up to 10 attempts (1 second apart) after backend start. If all attempts fail, the system SHALL print a warning and continue (the rest of the requested services still start). The poll SHALL use `urllib.request` (no third-party HTTP client).

#### Scenario: backend 正常起来

- **WHEN** `start` is requested and backend becomes healthy within 5 seconds
- **THEN** `start` prints `[OK] backend healthy` and proceeds to start the other services

#### Scenario: backend 起不来

- **WHEN** `start` is requested and `/api/health` fails all 10 attempts
- **THEN** `start` prints `[ERR] backend health check failed` and continues to start frontend and hqserver anyway

### Requirement: 退出码

The system SHALL exit with status 0 on success, 1 on a partial failure (e.g. some requested services failed to start, or some health checks failed), and 2 on invalid CLI usage (unknown action, unknown service name).

#### Scenario: 未知动作

- **WHEN** developer runs `python scripts/evctl.py frobnicate`
- **THEN** script prints error listing valid actions and exits with status 2

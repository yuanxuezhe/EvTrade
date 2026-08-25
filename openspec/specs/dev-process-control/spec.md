# dev-process-control — 开发服务进程管控

## Purpose

为本地开发提供统一的、单入口的 Python 脚本 `scripts/evctl.py`，以一致的方式在三平台（Linux / Windows / git-bash）启停三个开发服务（backend FastAPI/uvicorn 8000、frontend Vite 50998、hqserver WebSocket quotes 8765）。消除散落在 `start.sh` / `restart.sh` / `stop.sh` 中的脆弱 shell 逻辑、端口 fallback 与孤儿进程问题。

## Requirements

### Requirement: 文档目录约定

The system SHALL maintain a single documentation workflow root:

1. **`openspec/`** — 动态工作流：当前 spec 真相源（`specs/<cap>/spec.md`）、变更追踪（`changes/<name>/` + 配套 skill `openspec-*`）、AI 协作约定（`AGENTS.md`）、工具配置（`.openspec.yaml`、`config.yaml`）。
2. **`知识库/`** — 实现级事实文档（HOW），与代码同步维护。

`docs/`（历史归档、API 契约速查）与 `kb/`（早期知识库）已删除，历史内容通过 git 历史查阅。

#### Scenario: 新增 spec 的正确位置

- **WHEN** 描述一个**当前实现的**能力（"system SHALL ..."）
- **THEN** 该 spec 写入 `openspec/specs/<cap>/spec.md`；如果该能力由一个 OpenSpec change 引入，对应 change 归档时通过 `opsx:archive` 同步 delta 到该文件

#### Scenario: 历史草稿与大型设计的位置

- **WHEN** 沉淀一份被覆盖前的演进版本或跨 capability 大型设计
- **THEN** 不再新建顶层归档目录：演进记录由 git 历史（中文提交说明）承载；大型设计随对应 change 的 `design.md` 保存

## Requirements

### Requirement: 单一 Python 入口

The system SHALL provide a single Python entry point `scripts/evctl.py` that manages the lifecycle of three development services: backend (FastAPI/uvicorn, port 8000), frontend (Vite, port 50998), and hqserver (WebSocket quotes, port 8765). The entry point SHALL be invokable as `python scripts/evctl.py <action> [services...]` on any platform (Linux, Windows, git-bash).

#### Scenario: 三平台一致调用

- **WHEN** developer runs `python scripts/evctl.py status` on Linux, Windows, or git-bash
- **THEN** output shows the same field set: ports, PID files, and backend `/api/health` status, in the same order

#### Scenario: Python 3.6.8 兼容

- **WHEN** evctl.py is run with `python` whose version is `3.6.8`
- **THEN** it imports without `SyntaxError` and runs the requested action to completion

#### Scenario S-DPC-005: spawn 后存活检查（v10 新增，2026-06-22 ba8b364）

- **WHEN** evctl.py spawn 一个服务后 0.5s / 1.5s / 3.0s 任一时刻检测到 PID 已死
- **THEN** 报错并打 `scripts/.logs/<svc>.log` 最后 15 行（uvicorn 子进程的 stderr 通过 `subprocess.STDOUT` 重定向已写入该日志，因此 traceback 必然可见）
- **AND** 返回 False 让 start_all 增加 fails 计数

#### Scenario S-DPC-006: import 链兼容 Python 3.6.8（v10 新增，2026-06-22 ba8b364）

- **WHEN** developer run `python scripts\evctl.py start backend` 在 Python 3.6.8 下
- **THEN** `uvicorn main:app` 整个 import 链不能出现 `TypeError: 'type' object is not subscriptable`（PEP 585 内建泛型 `list[T]` / `dict[T,U]` 在 3.6.8 下不可用）
- **AND** 若 import 失败，traceback 应在 `scripts/.logs/backend.log` 中可读

#### Scenario S-DPC-007: asyncio.create_task 不出现在 server/（v10 新增，2026-06-22 ba8b364）

- **WHEN** 项目代码（生产 + 测试）需要在 running loop 中调度协程
- **THEN** 必须使用 `asyncio.ensure_future(coro)` 而非 `asyncio.create_task(coro)`（后者 Python 3.7+ 才可用，本项目 `.python-version = 3.6.81`）
- **AND** 两种调用在 running loop 中均返回 `Task`，支持 `.cancel()` / `.done()` / `.result()`

### Requirement: backend uvicorn WS keepalive ping 探测阈值（ws-keepalive-ping-slack 2026-08-10）

The system SHALL launch the backend (port 8000) uvicorn with WebSocket keepalive ping settings that tolerate realistic client pong latency:

- `--ws-ping-interval 20`（服务端每 20s 发 native WS ping）
- `--ws-ping-timeout 60`（pong 容忍窗口 60s，而非 uvicorn 默认 20s）

**Why**：uvicorn 默认 `ws_ping_timeout=20s` 下，浏览器 quote_update 全市场订阅（`''`，≈1260 帧/s）时渲染主线程 backpressure 导致 native pong 延迟 ~20-30s，服务端探测误断 `1011 keepalive ping timeout`，前端每 ~2.3min 重连一次。`hq/hqserver.py` 2026-07-09 已对同款 bug 设 `ping_interval=15, ping_timeout=60`，本次对齐 backend。实测：不回 pong 时默认 40s 被关，`timeout=60` 下 80s 才关；正常自动 pong 客户端 140s 稳定，证明服务器/代理/数据均正常。

**How to apply**：在 `scripts/evctl.py` backend Service 的 uvicorn 命令行显式加两个 flag + 注释；任何其他 backend 启动方式（如生产部署）也应沿用相同或更宽松的 `ws_ping_timeout`。

#### Scenario: 浏览器 pong 延迟 20-30s 不被误断

- **GIVEN** backend 以 `--ws-ping-timeout 60` 启动，浏览器 quote_update 全市场订阅
- **WHEN** 浏览器渲染 backpressure 使 native pong 延迟 ~20-30s
- **THEN** 连接 MUST 保持存活（60s 窗口 > 延迟），不再 `1011 keepalive ping timeout`

#### Scenario: 真正死连接仍被探测踢掉

- **GIVEN** backend 以 `--ws-ping-timeout 60` 启动
- **WHEN** 客户端网络真断且 60s 内完全无 pong
- **THEN** 服务端 MUST 仍关闭该连接（探测功能保留），并触发前端既有重连/兜底

#### Scenario: 启动参数生效

- **GIVEN** `evctl.py restart backend`
- **WHEN** 裸 socket 客户端建立 WS 后故意不回 pong
- **THEN** 连接在 `20s ping + 60s timeout ≈ 80s` 才被服务端关闭（而非默认的 40s）

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

### Requirement: evctl 管理 hermes serve daemon

> 2026-08-23 用户拍板覆盖 ai-agent-panel 的「不纳入 evctl」决策：hermes serve 是 AI Agent 功能的必需 daemon，纳入 evctl 默认启动集。

The system SHALL provide a `hermes` service in the `SERVICES` table of `scripts/evctl.py`: port `9119`, working directory project root, and command `[<hermes-cli>, "serve"]`. The `hermes` service SHALL be part of `DEFAULT_SERVICES` so that `evctl start` / `stop` / `restart` / `status` / `logs` (without explicit service arguments) all cover it. Before starting `hermes`, the system SHALL preflight-check that the `hermes` CLI is resolvable via `shutil.which`; if missing, it SHALL print an installation guide and treat the service start as failed (without crashing other commands or silently skipping). If port `9119` is already occupied (e.g. a manually started daemon), `evctl start hermes` SHALL treat it as skip-success. The preflight mechanism SHALL support callable preflight items in addition to the existing module-import checks.

#### Scenario: evctl start 一并拉起 hermes serve

- **GIVEN** 机器已安装 Hermes Agent CLI（`hermes` 在 PATH）
- **WHEN** 运行 `python scripts/evctl.py start`
- **THEN** hermes serve 以默认服务之一启动（`[hermes, serve]`，cwd 项目根，日志 `scripts/.logs/hermes.log`，PID `scripts/.pids/hermes.pid`）

#### Scenario: hermes CLI 缺失时给出明确指引

- **GIVEN** 机器未安装 Hermes Agent（`shutil.which('hermes') is None`）
- **WHEN** 运行 `python scripts/evctl.py start`
- **THEN** 输出 hermes 预检失败 + 安装指引（`hermes serve` / SKILL.md 路径），`evctl start` 对该服务返回失败（退出码 1），但其它命令（stop/status/logs）不受影响

#### Scenario: 端口被占视为已运行

- **GIVEN** 用户已手动 `hermes serve`（9119 被占）
- **WHEN** 运行 `python scripts/evctl.py start hermes`
- **THEN** evctl warn 端口已被占并 skip（不重复 spawn），与其它服务端口占用语义一致

### Requirement: pytest testpaths 覆盖工作测试目录（2026-08-25）

The `pytest.ini` SHALL 设置 `testpaths = server/tests tests`，确保项目根运行 `pytest` 时能发现 `server/tests/`（auth / push / services / test_place_async / test_v78_skip_rebroadcast / test_rpc_handlers / test_script_* / test_orders_cancel）下的工作测试。Root `tests/` 目录保留集成脚本（`tests/strategy_exec/`、`tests/hq/`、`tests/client/`、根目录的 `test_quote_pattern_subscribe.py` / `test_quota_batch.py` / `stress_quota_5etf.py`）。

#### Scenario: 默认 pytest 跑到 server/tests 工作测试

- **WHEN** developer 在项目根运行 `pytest`
- **THEN** pytest 同时从 `server/tests/`（工作测试）与 `tests/`（集成 / 脚本）收集
- **AND** legacy `tests/server/` 子树已被整体删除（曾引用已删 `server.models.orm` / `server.models.user` 模块，不再被收集）

### Requirement: Ruff 作为默认 lint 工具（2026-08-25）

The `pyproject.toml` SHALL 包含 `[tool.ruff]` section，强制：
- `line-length = 120`（与 CLAUDE.md § 六 一致）
- `select = ["E", "F", "W"]`（pycodestyle 错误/警告 + pyflakes）
- `target-version = "py310"`（与 `.python-version` 一致）

The `.ruff_cache/` 目录（已在 repo 内）作为缓存目标。dev dependencies MUST 包含 `ruff>=0.6.0`。

#### Scenario: ruff check 0 错误（开发期）

- **WHEN** developer 运行 `ruff check server/ hq/ iquant/ scripts/ conftest.py tests/`
- **THEN** exit code 0；无 rule violation
- **NOTE**：CI 当前非阻断（基线错误由后续 change 清理）；dev 工具必须自己先修

### Requirement: GitHub Actions CI workflow（2026-08-25）

The `.github/workflows/ci.yml` SHALL 在 push / pull_request 到 `master` 时自动验证：

- **`backend` job**: ubuntu + Python 3.10 + uv → `uv sync --frozen` → `pytest hq/ server/tests/`（lint 非阻断）
- **`frontend` job**: ubuntu + Node 20 → `cd client && npm ci` → `npm run build`

The CI SHALL NOT push artifacts or deploy。Cache SHALL be enabled for both pip (uv) and npm dependencies。

#### Scenario: push 触发 CI

- **WHEN** developer push 一个 commit 到 `master`
- **THEN** GitHub Actions 并行运行 `backend` 与 `frontend` jobs
- **AND** 两个 job 必须均成功才允许合并

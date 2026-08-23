# EvTrade 启停脚本

单一 Python 入口, 跨平台 (Linux / Windows / git-bash) 管理开发期 5 个默认服务 (backend / frontend / hqserver / strategy_exec / hermes) + 1 个可选服务 (broker) 的 start / stop / restart / status / logs。

## 用法

```bash
# Windows (git-bash / cmd / PowerShell)
python scripts\evctl.py start
python scripts\evctl.py stop
python scripts\evctl.py restart
python scripts\evctl.py status

# Linux
python3 scripts/evctl.py start
```

### 动作 × 服务矩阵

| 动作 \ 服务 | 全部 (默认) | 仅 backend | 仅 frontend | frontend + hqserver |
|---|---|---|---|---|
| start | `python scripts\evctl.py start` | `… start backend` | `… start frontend` | `… start frontend hqserver` |
| stop | `… stop` | `… stop backend` | `… stop frontend` | `… stop frontend hqserver` |
| restart | `… restart` | `… restart backend` | `… restart frontend` | `… restart frontend hqserver` |
| status | `… status` | `… status backend` | `… status frontend` | `… status frontend hqserver` |

合法动作: `start` / `stop` / `restart` / `status` / `logs`。
合法服务: `backend` / `frontend` / `hqserver` / `strategy_exec` / `hermes` / `broker`（`broker` 为可选，需显式指定）。

## 端口

| 服务 | 端口 | 备注 |
|---|---|---|
| backend (FastAPI/uvicorn) | **8000** | — |
| frontend (Vite) | **50998** | `--strictPort` 模式, 端口被占直接退出 (不静默 fallback) |
| hqserver (WebSocket quotes) | **8765** | hq/hqserverd/target/release/hqserverd[.exe] 内部写死 (Rust 二进制) |
| strategy_exec | **8001** | 从 `strategy_exec/.env` 加载环境变量 |
| hermes (Hermes Agent daemon) | **9119** | `hermes serve`；外部 Hermes Agent，AI 助手后端依赖；CLI 缺失时 preflight 报指引 |
| broker（可选） | 无 TCP | `python -u xtquant_api.py`（纯 RabbitMQ publisher，依赖 QMT/xtquant 环境） |

端口在 `scripts/evctl.py` 顶部硬编码, **不读环境变量**。改端口要同时改 `client/vite.config.js` 的 `proxy.target` (现指向 `http://localhost:8000`)。

## 目录布局

```
scripts/
├── evctl.py          ← 唯一入口 (本文件配套使用)
├── README.md         ← 本文档
├── .logs/            ← 各服务 stdout+stderr 追加日志 (backend/frontend/hqserver/strategy_exec/hermes/broker)
└── .pids/            ← 各服务真实 PID (Popen 返回值, 不是壳进程)
```

## 行为细节

### 启动

- 端口被占 (非前端) → 跳过启动, warn
- 前端端口被占 → 读占用进程 cmdline, 含 `vite` 或 `esbuild` 视为孤儿 (ctrl-C 切断终端后残留) → warn + 强杀 + 接管; 否则跳过
- Vite 用 `--strictPort` — 端口被占时 vite 自身会报错退出, 不再静默跳到 50999
- backend 起完后做 `/api/health` 健康检查 (10 次 × 1s); 失败 warn 不阻塞后续

### 停止

- 按 `DEFAULT_SERVICES` 反序停 (hermes → strategy_exec → hqserver → frontend → backend, 减少前端 WebSocket 断连噪音)
- PID 文件里的进程先 SIGTERM → 等 3s → SIGKILL (Linux); Windows 用 `taskkill /F /T`
- 停完再扫一次三个端口, 残留进程 `taskkill /F /T` / `pkill -KILL` 兜底

### 状态

- 三服务的端口占用 (LISTEN pid procname / free)
- 三服务的 pidfile (alive / dead / missing)
- backend `GET /api/health` 一次探测 (200 OK / FAIL)

### 退出码

- `0` — 全部动作成功
- `1` — 部分失败 (例如某服务 spawn 失败)
- `2` — 参数错误 (未知动作 / 未知服务名)

## 平台差异 (库内吸收, 调用方无感)

| 动作 | Linux | Windows |
|---|---|---|
| 查端口 PID | `ss -ltnp` | `netstat -ano` |
| 读进程 cmdline | `/proc/<pid>/cmdline` | `wmic process get CommandLine` |
| 进程是否存活 | `os.kill(pid, 0)` | `tasklist /FI /FO CSV` |
| 杀进程树 | SIGTERM → SIGKILL, 走进程组 | `taskkill /F /T /PID` |
| 后台进程 spawn | `start_new_session=True` | `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP` |

## 常见问题

**Q: 启动时端口被占怎么办?**
A: 看 status 输出, 找到占用的 PID, 手动 taskkill / kill (或 `evctl.py stop` 先尝试走 pidfile 清理)。

**Q: Vite 端口冲突但不是 vite 进程?**
A: 这是别人 (其他应用) 占着 50998, `evctl.py` 不会强杀, 报 warn 跳过。先把占用的进程停了再 start。

**Q: 删了 .pids/ 里的文件会怎样?**
A: 下次 start 会读不到, 正常 spawn 新的; status 会显示 `pidfile missing`, 不影响。

**Q: 能否跨平台共用同一份脚本?**
A: 是, evctl.py 是单一 Python 文件, Linux / Windows / git-bash 行为一致。

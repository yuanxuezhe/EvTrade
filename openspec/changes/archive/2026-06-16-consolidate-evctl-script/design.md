## Context

`scripts/` 现状:

| 文件 | 角色 | 平台 | 完整度 |
|---|---|---|---|
| `dev.sh` | 调 `dev.ps1` 的 bash 包装 | git-bash / Linux | 薄 |
| `dev.cmd` | 调 `dev.ps1` 的 cmd 包装 | Windows cmd | 薄 |
| `dev.ps1` | Windows 主控 (PowerShell) | Windows | 缺 vite 孤儿检测, PID 是壳进程 |
| `_start_backend.cmd` | dev.ps1 间接调用的子脚本 | Windows | 仅 `cd` + 启动 + 重定向 |
| `_start_frontend.cmd` | 同上 | Windows | 同上 |
| `_start_hqserver.cmd` | 同上 | Windows | 同上 |
| `restart.sh` | Linux / git-bash 主控 | Linux / git-bash | 完整 (孤儿检测, --strictPort, 健康检查) |
| `README.md` | 文档 | 任意 | 端口与代码不一致 (写 8002/3000, 实际 8000/50998) |

`restart.sh` 已在 c5e139e commit 加入了 vite 孤儿检测 + `--strictPort`, 是行为最完整的实现。本次重构把它 (和 dev.ps1) 的逻辑合并到一个 Python 文件。

约束:
- Python 3.6.8 (`.python-version` = `3.6.81`), 不能用 `dataclasses` / walrus / `subprocess.run(capture_output, text)` 等 3.7+ 特性
- 端口 8000 / 50998 / 8765 硬编码, 不读 env
- `requirements.txt` 不含 psutil / colorama, 不能引入第三方库
- `.python-version` 已 commit, 任何运行 `python` 的环境必须能跑 evctl.py

## Goals / Non-Goals

**Goals:**
- 单一 Python 入口, 跨平台一致行为
- 保留 restart.sh 已验证的特性: vite 孤儿检测, `--strictPort`, 健康检查, PID 文件
- 平台差异 (port query / cmdline / kill) 在库内吸收, 调用方 0 感知
- 输出格式简单一致, 跨平台无 ANSI 颜色坑
- 一次操作可针对服务子集, 不强制全量

**Non-Goals:**
- 不做 daemon / 后台守护 / 系统服务 (systemd / nssm)
- 不做健康监控 / 进程崩溃自动重启 (start 是一次性, restart 才是恢复)
- 不做端口 / 路径 env 化 (本次明确不做)
- 不引入 psutil / colorama / 任何新依赖
- 不打包成可执行文件 (`pyinstaller` 等)
- 不提供远程主机管理 (`evctl.py ssh user@host start` 不做)

## Decisions

### D1: 单文件 `scripts/evctl.py`, 不用 package

**Why**: 总规模 ~300 行, 拆 package 反而增加引用成本; 单文件直接 `python evctl.py ...` 即可, 不需要 `python -m evctl` 也行。

**Alternatives considered**:
- `scripts/evctl/__init__.py` + `__main__.py` + 多个模块 — 过度拆分, ~300 行不值得
- `scripts/evctl.py` (单文件) — 选中, 与项目 `client/package.json` / `server/*.py` 风格一致

### D2: CLI 用 `sys.argv` 手解, 不用 `argparse`

**Why**: 3.6 兼容 OK; 命令集小 (4 动作 × 3 服务 + 默认 all), 手解 30 行; 不引入 argparse 的 `--help` 体积。

**Trade-off**: 无 `--help` 自动生成 — 接受, 行为在 README 里讲清即可。

### D3: 端口与路径用模块级常量

```python
BACKEND_PORT    = 8000
FRONTEND_PORT   = 50998
HQSERVER_PORT   = 8765  # hqserver 写死

PROJECT_ROOT    = ...  # evctl.py 所在目录的父目录 (用 __file__ 解)
LOG_DIR         = PROJECT_ROOT / 'scripts' / '.logs'
PID_DIR         = PROJECT_ROOT / 'scripts' / '.pids'
```

**Why**: 满足"不读 env"; `__file__` 推导 `PROJECT_ROOT` 不依赖 CWD。

### D4: 平台差异用 `sys.platform` 分支, 不抽象成策略类

**Why**: 三个差异点 (port query / cmdline / kill) 都是小函数, ~20 行内; 抽象成 strategy / adapter 反而增加间接层。直接 `if sys.platform == 'win32': ... else: ...` 透明, 易读。

**Alternatives considered**:
- 抽 `ProcessBackend` 接口 + `LinuxBackend` / `WindowsBackend` — 拒绝, 三个方法不值得
- 抽 `_platform_utils.py` — 拒绝, 单文件已经够短

### D5: 杀进程用 `os.kill(pid, SIGTERM)` → wait → `SIGKILL`, Windows 用 `taskkill /F /T /PID`

**Why**:
- Linux: uvicorn / hqserver 都是 Python 主进程 + 可能的工作进程 (如 uvicorn 的 reload worker), `pkill -TERM` 自然级联; 等待 3s 不退再 `SIGKILL`
- Windows: `subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], check=False)` 处理进程树 (`/T` = tree), 简单可靠
- 都用 PID 文件里的主 PID 即可, 不需要枚举 children

**Trade-off**: 拿不到中间态 (e.g. uvicorn 的 reloader 派生进程) — 接受, taskkill /T 能兜住。

### D6: Vite 孤儿检测用 `cmdline` 嗅探, 不维护白名单进程名

**Why**: Vite / esbuild 进程被 ctrl-C 切断终端后, 端口 50998 仍被它们占着, restart 启动会撞端口。嗅探 cmdline 含 "vite" 或 "esbuild" 视为孤儿, 强杀后接管。

**实现**:
- Linux: `tr '\0' ' ' < /proc/<pid>/cmdline` → 全文匹配
- Windows: `wmic process where ProcessId=<pid> get CommandLine /value` → 解析 `CommandLine=...`

**Why not psutil**: 见 Non-Goals, 不引依赖。

**Trade-off**: 误判 (非 vite 进程被误杀) 风险 — 接受, 命中 cmdline 关键字再 warn, 不会静默; 误判时可手动停。

### D7: 健康检查 `urllib.request.urlopen(url, timeout=N)`, 最多 10 次 × 1s

**Why**: 标准库内置, 3.6 兼容 (3.6 已有 `timeout` 参数); 不引 requests。

**Trade-off**: 只检查 backend 的 `/api/health`; frontend / hqserver 暂无内置 health endpoint, 启动后用端口已 listen 即视为"启动"。

### D8: 输出用纯文本前缀 `[OK] [WARN] [ERR] [INFO]`, 不用 ANSI 颜色

**Why**:
- Windows cmd 默认不识别 ANSI, 需要 `os.system('')` 或 colorama, 麻烦
- git-bash / Linux 终端 + Windows Terminal (新) 支持 ANSI, 但 Windows 旧 cmd 不支持, 跨平台不一致
- 日志重定向到文件时, ANSI 控制符全是噪音

**Trade-off**: 比 ANSI 颜色稍弱可读性 — 接受, 简洁 > 花哨。

### D9: 启动后台进程用 `subprocess.Popen` + 显式 `start_new_session` (Linux) / `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` (Windows)

**Why**:
- Linux: `start_new_session=True` 让进程脱离父进程组, 不被 SIGINT 级联杀掉; 用 `os.setsid` 兜底
- Windows: `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS` 让子进程脱离控制台, 关掉 evctl.py 不影响后台
- stdout / stderr 重定向到 `<LOG_DIR>/<service>.log`, 用 `with open(..., 'ab', 0)` 立即落盘

**Why not `nohup`**: Windows 无 nohup; `Popen` 自己处理。

### D10: PID 文件记 Popen 返回的 PID (真实服务进程), 不用壳进程 PID

**Why**: `dev.ps1` 用 `Start-Process cmd.exe` 记的是 `cmd.exe` PID, taskkill 之后子进程不一定死, 状态不准确。`Popen(['python', '-m', 'uvicorn', ...])` 拿到的就是 python 进程 PID, taskkill /T 之后树都死。

## Risks / Trade-offs

- [Windows 上 `wmic` 在 Win11 22H2 之后被标记 deprecated] → 缓解: 现在还能用; 真废了再切到 `Get-CimInstance Win32_Process` (但那是 PowerShell, 不能从 Python 直接调; 备用方案是 subprocess 调 PowerShell)。当前接受。
- [dev.ps1 用户的工作流被打断] → 缓解: README 显式给出新命令; git history 保留旧文件直到第一次归档。
- [`taskkill /F` 是硬杀, 不给应用清理机会 (uvicorn 的 startup event 不会触发)] → 缓解: 这是开发期脚本, 业务无持久状态; 生产用 systemd / nssm, 不在本次范围。
- [跨平台 `kill -0` 在 Windows 不可用] → 缓解: `pid_alive(pid)` 在 Windows 上用 `OpenProcess` (ctypes) 或 `subprocess.run(['tasklist', '/FI', f'PID eq {pid}'])` 检查; 取后者, 标准库。
- [Python 3.6.8 是 2021 年 EOL 版本, 部分新 PEP 不支持] → 缓解: 库内只用 3.6 兼容子集 (无 walrus, 无 match, 无 `subprocess.run(capture_output, text)`, f-string OK)。
- [新启动不再带 `--reload` (uvicorn)] → 决策: 保留 `--reload`, 跟现状一致; 接受 taskkill /T 兜底树杀。

## Migration Plan

实施步骤见 `tasks.md` checklist。简述:

1. 写 `scripts/evctl.py` (新文件, ~300 行)
2. 写 `scripts/README.md` (重写, 一个入口)
3. **同时保留**旧文件 (`dev.sh` / `dev.ps1` / `restart.sh` / `_start_*.cmd`) — 不删
4. 手动跑 `python scripts/evctl.py start` → 验证三服务起来
5. 跑 `python scripts/evctl.py status` → 验证端口/PID/health 输出
6. 跑 `python scripts/evctl.py restart` → 验证停+起无残留
7. 跑 `python scripts/evctl.py stop` → 验证端口释放
8. 旧入口跑一遍回归: `dev.sh start` / `dev.ps1 -Action start` / `restart.sh start` — 确认旧路径不受新文件影响 (它们独立, 互不引用)
9. 删除旧文件 (7 个)
10. 跑一次 `git grep restart.sh` / `git grep dev.ps1` — 确认无残留引用

**Rollback**: 旧文件在第 9 步前保留, 任何一步失败 `git restore scripts/` 即可回退。

## Open Questions

无。设计已收敛, 待实施验证。

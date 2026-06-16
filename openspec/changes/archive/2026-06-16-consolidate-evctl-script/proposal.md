## Why

`scripts/` 目前有 4 套入口（`dev.sh` / `dev.cmd` / `dev.ps1` / `restart.sh`）和 3 个 `_start_*.cmd` 间接层, 行为不一致, 维护成本高:

- `restart.sh` (bash, ~260 行) 是当前最完整的实现, 含 vite 孤儿检测 + `--strictPort` + 健康检查 + 颜色输出
- `dev.ps1` (PowerShell) 是 Windows 入口, 但缺失 vite 孤儿防护, PID 文件记的是 `cmd.exe` 壳进程而非真实服务进程
- `README.md` 文档端口 (8002/3000) 与实际代码 (8000/50998) 不一致
- `_start_*.cmd` 三个子脚本只做 `cd` + 启动 + 重定向日志, 是无谓的间接层

路线 C: 抽出一个 Python 入口 `scripts/evctl.py` 作为唯一真源, 砍掉所有 bash/cmd/ps1 包装和间接子脚本。跨平台差异在库内吸收, 调用方只看到一个命令。

## What Changes

- **新增** `scripts/evctl.py`: 单一 Python 入口, 提供 `start` / `stop` / `restart` / `status` 四个动作, 可对 backend / frontend / hqserver 三个服务中的子集操作
- **删除** `scripts/dev.sh` (旧版薄包装, 由 evctl.py 取代)
- **删除** `scripts/dev.cmd` (旧版薄包装)
- **删除** `scripts/dev.ps1` (Windows 主控, 逻辑搬到 evctl.py)
- **删除** `scripts/_start_backend.cmd` / `scripts/_start_frontend.cmd` / `scripts/_start_hqserver.cmd` (evctl.py 直接 spawn, 不再间接)
- **删除** `scripts/restart.sh` (Linux 主控, 逻辑搬到 evctl.py)
- **重写** `scripts/README.md`: 反映单一 Python 入口, 端口列表与代码对齐 (8000 / 50998 / 8765)

**BREAKING**: 调用方从 `dev.sh start` / `dev.ps1 -Action start` / `restart.sh start` 改为 `python scripts/evctl.py start`。现有 `.pids/*.pid` 和 `.logs/*.log` 文件路径不变, 无需迁移。

## Capabilities

### New Capabilities

- `dev-process-control`: 开发期进程生命周期管理 — start / stop / restart / status, 跨平台 (Linux / Windows / git-bash), 端口/PID 文件/日志路径为内部实现细节。约束: 端口 8000 / 50998 / 8765 硬编码 (不动 env), Python 3.6.8 兼容, 不引入第三方依赖。

### Modified Capabilities

无。`configuration` 和 `frontend` capability 的需求不变 (端口数值未变, 启动/停止流程的对外行为由 `evctl.py` 继承)。

## Impact

- **代码**: `scripts/evctl.py` 新增 (单文件, ~300 行)
- **删除**: `scripts/dev.sh` / `dev.cmd` / `dev.ps1` / `_start_*.cmd` / `restart.sh` 共 7 个文件
- **文档**: `scripts/README.md` 重写
- **开发者**: 命令行调用方式变化, 见 BREAKING 说明
- **CI / IDE**: 若有外部脚本依赖 `restart.sh` / `dev.ps1` 入口, 需同步更新
- **运行时**: `.logs/*.log` 和 `.pids/*.pid` 路径不变; 后台进程 (uvicorn / vite / hqserver) 仍是同一组, 端口 / 命令行参数不变

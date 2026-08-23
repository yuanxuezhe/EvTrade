# Proposal — hermes serve 纳入 evctl 管理

## 背景

AI Agent 功能（`/ws/agent_channel`）依赖外部 daemon **hermes serve**（Hermes Agent 的 headless JSON-RPC/WebSocket gateway，默认 `127.0.0.1:9119`，LLM 后端 MiniMax M3）。

原 `2026-08-23-ai-agent-panel` 方案明确「**❌ 不纳入 hermes serve 到 evctl 管理**」（用户手动 `hermes serve` 起）。实际运行暴露出问题：用户手动起 daemon 易忘、无统一状态/日志入口，AI 对话框报 "hermes serve daemon not reachable" 时无从排查。

**用户拍板（2026-08-23）：覆盖原决策，将 hermes serve 纳入 `scripts/evctl.py` 管理，作为默认服务随 `evctl start` 一起启动。**

## 目标

- `evctl start`（无参）→ 除 backend/frontend/hqserver/strategy_exec 外，**同时拉起 hermes serve**
- `evctl stop` / `restart` / `status` / `logs` 对 hermes 全生效
- hermes CLI 缺失时，`start` 给出明确安装指引（不静默失败、不 crash 其它命令）

## 设计

### evctl 服务表（scripts/evctl.py）

仿照既有 `Service(name, port, cwd, cmd, preflight=...)` 模式新增：

| 项 | 值 |
|---|---|
| name | `hermes` |
| port | `HERMES_PORT = 9119` |
| cwd | 项目根 |
| cmd | `[shutil.which('hermes') or 'hermes', 'serve']`（外部 CLI，不走 venv） |
| preflight | callable `_hermes_preflight()`：`shutil.which('hermes')` 存在才 True |

- 加入 **`DEFAULT_SERVICES`**（`['backend', 'frontend', 'hqserver', 'strategy_exec', 'hermes']`）→ `evctl start`/`stop`/`status`/`logs` 无参时自动覆盖。
- `start_service` 的「端口被占 → 跳过（skip-success）」逻辑天然兼容用户手动起的 hermes serve：9119 被占即视为已运行。
- `_preflight_check` 扩展支持 **callable 预检**（现有逻辑只支持 import 检查）；hermes 缺失时 `_hermes_preflight()` 打印安装指引并返回 False → `evctl start` 对该服务 fail（用户已接受该语义）。

### 健康检查

- `start_service` 沿用 spawn 后多轮 PID 存活检查 + 端口占用判定，不新增 hermes 专属 healthz（后端 `HermesServeClient.is_reachable()` 已做 `GET /healthz` 探活）。

### 与既有文档/决策的关系

- **覆盖** ai-agent-panel proposal「不纳入 evctl」行 → 在本 change 的 tasks 里标注决策变更，归档时反映到 `dev-process-control/spec.md`。
- `知识库/脚本工具/启停脚本.md` 服务表补 hermes 行（含 9119 端口、外部依赖说明）。

## Out of Scope

- 不自动安装 Hermes Agent（外部工具，用户自装；仅给出 PATH 缺失指引）
- 不把 hermes 纳入 `evctl` 之外的生命周期（如 systemd / docker-compose）管理
- 不改后端 `HermesServeClient` 探活逻辑

## 文件

| 文件 | 改动 |
|---|---|
| `scripts/evctl.py` | 新增 hermes 服务（约 20 行）：HERMES_PORT、_hermes_cmd、_hermes_preflight、SERVICES、DEFAULT_SERVICES、docstring、_preflight_check 支持 callable |
| `知识库/脚本工具/启停脚本.md` | 服务表补 hermes 行 + 用法示例 + 修改指南 |
| `scripts/README.md` | 补 hermes（该文件已过时，顺带校准服务清单） |
| `openspec/specs/dev-process-control/spec.md` | 归档时 merge：evctl 管理 hermes 服务 |

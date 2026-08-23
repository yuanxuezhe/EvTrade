# Spec Delta — dev-process-control (hermes serve 纳入 evctl 管理)

## REQ-DEVCTL-011 — evctl 管理 hermes serve daemon

> 用户拍板 2026-08-23 覆盖 ai-agent-panel 的「不纳入 evctl」决策：hermes serve 是 AI Agent 功能的必需 daemon，纳入 evctl 默认启动集。

### Purpose

把 Hermes Agent 的 headless daemon `hermes serve`（默认 `127.0.0.1:9119`，JSON-RPC/WS gateway）纳入 `scripts/evctl.py` 统一生命周期管理，作为**默认服务**随 `evctl start` 一起启动，避免用户手动起 daemon 易忘、无统一状态/日志入口。

### Requirements

- `scripts/evctl.py` SHALL 在 `SERVICES` 表提供 `hermes` 服务：端口 `9119`，cwd 项目根，cmd `[<hermes-cli>, "serve"]`。
- `hermes` SHALL 加入 `DEFAULT_SERVICES`，使 `evctl start`/`stop`/`restart`/`status`/`logs`（无参）都覆盖它。
- 启动 `hermes` 前 SHALL 做 CLI 预检：`shutil.which('hermes')` 不存在时打印安装指引并视为该服务启动失败（不 crash 其它命令 / 不静默跳过）。
- `evctl start hermes` 在 9119 端口已被占（用户手动起过）时 SHALL 视为 skip-success，不重复拉起。
- `_preflight_check` SHALL 支持 callable 预检项（除既有 module import 检查外）。

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

### Out of Scope

- 不自动安装 Hermes Agent（外部工具）
- 不引入 hermes 专属 healthz 探测（后端 `HermesServeClient.is_reachable()` 已覆盖）
- 不把 hermes 纳入 systemd / docker-compose 管理

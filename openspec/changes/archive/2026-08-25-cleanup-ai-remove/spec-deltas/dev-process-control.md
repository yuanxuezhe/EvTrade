# Spec Delta: dev-process-control — 删 evctl 管理 hermes 段

## REMOVED Requirements

### Requirement: evctl 管理 hermes serve daemon

> ❌ 本 Requirement 因 `2026-08-25-cleanup-ai-remove` change **整段删除**（含 3 个 Scenario）。

理由：用户拍板移除 AI，evctl 不再管理外部 `hermes serve` daemon。

**删除范围**（`openspec/specs/dev-process-control/spec.md` line 231-253）：
- 段首描述（hermes 纳管决策）
- Scenario: evctl start 一并拉起 hermes serve
- Scenario: hermes CLI 缺失时给出明确指引
- Scenario: 端口被占视为已运行

**对应代码删除**：
- `scripts/evctl.py`：`HERMES_PORT` 常量 / `_hermes_cmd()` / `_hermes_preflight()` / `SERVICES['hermes']` / `OPTIONAL_SERVICES` 中 hermes 条目
- `scripts/init_strategy_exec_env.py`：`request_grant_token()` 函数（hermesagent grant）

## ADDED Requirements

无。

## Notes

- preflight callable 检查能力保留（callable + module-import 混合预检），只是去掉了 hermes 这一用例。
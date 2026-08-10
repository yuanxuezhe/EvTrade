# spec-delta: configuration（现有 spec 增量）

## REMOVED Requirements

### STRATEGY_ENGINE_ENABLED 灰度门 — 已移除

> **变更说明（2026-08-10）**：`STRATEGY_ENGINE_ENABLED` 网格引擎灰度门随 `aa70dae` 从 `server/config.py` **删除**。网格引擎已下线，灰度门无意义。

- ~~`STRATEGY_ENGINE_ENABLED` env 定义~~（config.py 已删）
- ~~网格引擎 503 灰度门行为~~（`false` 时 `/api/strategy` 除 flags 外返 503 — 端点已删）

## MODIFIED Requirements

### REQ-CFG-008（策略相关 env）— 只保留现行条目

- 删除对网格引擎的 env 描述（`/api/strategy` 路由灰度）
- 保留并确认现行策略 env：
  - `STRATEGY_EXCHANGE_NAME` / `STRATEGY_SIGNAL_QUEUE`（signal 消费，server + strategy_exec 共享）
  - `STRATEGY_EXEC_API_URL` / `STRATEGY_EXEC_API_TOKEN`（strategy_exec 转发，REQ-CFG-012）
  - 无新增 env

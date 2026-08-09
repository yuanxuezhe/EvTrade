# spec-delta: data-model（strategy_task 扩展 3 字段 + 写权限说明）

## Purpose

strategy-exec-service change 在 `strategy_task` 表加 3 个字段（乐观锁 + 执行服务标识），并明确策略相关表的写权限归属（EvTrade 只读 vs strategy_exec 可写）。

## MODIFIED Requirements

### §8 `strategy_task` 表结构（v120+ 新增 3 字段）

> **变更说明（2026-08-09）**：strategy_exec 独立服务写 `strategy_task.progress` / `live_signals` / `status`，与 EvTrade `signal_consumer` 写 `status` 存在并发，加乐观锁。

原 `strategy_task` 23 字段保持不变，**新增 3 字段**：

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `execution_service` | String(16) | NO | `'evtrade'` | 任务执行服务标识：`'evtrade'`（老服务）/ `'strategy_exec'`（v120+ 新服务）|
| `execution_pid` | Integer | YES | NULL | strategy_exec 实例进程 pid（用于排查 + 监控）|
| `version` | Integer | NO | 0 | **乐观锁**，UPDATE 时 `WHERE version=:v` 防 lost update |

#### Scenario: migration 幂等添加 3 字段

- **WHEN** 跑 migration `2026-08-09-strategy-task-exec-fields.py`
- **THEN** 检查 `INFORMATION_SCHEMA.COLUMNS` 找 3 列
- **AND** 已存在则跳过（幂等）
- **AND** 不存在则 `ALTER TABLE strategy_task ADD COLUMN ...`（3 次 ALTER）
- **AND** 现有 task 的 `execution_service` 默认 `'evtrade'`（migration 时回填默认值）

#### Scenario: 双服务并发写 strategy_task

- **WHEN** strategy_exec 写 progress（version=0 → 1）
- **AND** 同时 EvTrade signal_consumer 写 status（version=0 → 1）
- **THEN** 后到的写 `WHERE version=0` 不匹配 → 影响行数 = 0
- **AND** 重试读最新 version，再写 `WHERE version=1`
- **AND** 最坏 case: 重试 3 次仍冲突 → 抛 `OptimisticLockError`
- **AND** 写 `strategy_task.error_msg='concurrent update conflict, retries=3'`

## ADDED Requirements

### §12 `strategy_script` 写权限说明

> **变更说明（2026-08-09）**：脚本定义（code / params_schema / is_public）仍由 EvTrade 主进程 CRUD。strategy_exec 只读。

`strategy_script` 表写权限归属：

- **EvTrade 后端可写**：`POST /api/script-strategy/scripts` / `PUT` / `DELETE`
- **strategy_exec 只读**：启动 task 时按 `(user_id, script_id)` 复合 PK 读取 code + params_schema
- **不能**反向：strategy_exec 不能 POST/PUT scripts

#### Scenario: strategy_exec 启动 task 读 script

- **WHEN** EvTrade POST `/internal/run-task` {task_id, script_id='ma5_e2e'}
- **THEN** strategy_exec 查 `StrategyScript.query_one(user_id, 'ma5_e2e')`（read-only）
- **AND** 读 code / params_schema / description
- **AND** 加载到 Backtrader sandbox 执行

### §13 `strategy_script_audit` 写权限说明

> **变更说明（2026-08-09）**：audit 表改由 strategy_exec 写入。

`strategy_script_audit` 表写权限归属：

- **strategy_exec 可写**：每条 BUY/SELL/SIGNAL/INFO 触发时 INSERT 一行
- **EvTrade 后端可读**：admin / 用户查 audit（前端 /audit endpoint 仍调 EvTrade）
- **EvTrade 不写**：audit 只由 strategy_exec 写入

#### Scenario: strategy_exec 写 audit

- **WHEN** 用户脚本 next() 调 `self.buy_signal(price=1680, volume=100)`
- **THEN** strategy_exec INSERT `strategy_script_audit` (task_id, stime, phase='bar', trigger_type='BUY', ...)
- **AND** 同时 publish_signal 到 RabbitMQ
- **AND** EvTrade `/audit` endpoint 读这条 audit 返前端

### §15 `users` / §16 `sys_config` 写权限说明（不变）

- `users` / `sys_config` 仍由 EvTrade 写入
- strategy_exec **不**写 user/config 表
- strategy_exec 只读 `users.username` / `role`（如需）

## Cross References

- 完整迁移：`server/migrations/2026-08-09-strategy-task-exec-fields.py`
- 完整使用：`strategy-exec/spec.md` REQ-SE-007
- Schema SoT：`server/schema.yml`（sync_schema.py apply 同步）
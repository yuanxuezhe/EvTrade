# strategy-exec — Spec Delta (2026-08-29)

## 修改类型
MODIFIED — 新增 REQ-SE-013 his_hq mock 离线模式 + REQ-SE-014 stale-queued cleanup

## 变更内容

### § 新增 REQ-SE-013: broker his_hq 离线 mock 模式

**Why**：Linux dev 环境无 xtquant / QMT Windows broker，`fetch_his_bars()` 等 RabbitMQ 队列 30s 超时 → BROKER_ERROR 502 → 回测永远卡 queued。需要一个**离线 mock 通道**，让 dev 环境也能跑通回测。

#### 触发方式

- `sys_config.user='0' AND cfg_key='his_hq_test_mode' = '1'` 时，`fetch_his_bars()` **不连 RabbitMQ**，直接调 `generate_mock_bars()` 返确定性 K 线
- 默认 '0'（关），所有路径走真实 broker（行为不变）
- 通过 `scripts/evctl.py set-his-hq-test-mode 0|1` 切换；SystemConfig 页可切换
- `server/infra/db.py` `init_db` 兜底 seed `his_hq_test_mode=0`

#### Mock K 线生成规则（确定性）

- **seed 派生**：`int(hash(stock_code)) % (2**31)` → 同 stock_code 同区间 = 同数据（跨重启一致）
- **起始价**：`50 + (seed % 100)` → 50~150 区间
- **随机游走**：`random.Random(seed).gauss(0, 0.02)` 日涨跌幅 → OHLC
- **OHLC 关系**：high ≥ max(open, close)；low ≤ min(open, close)
- **跳过周末**：Sat / Sun 不生成 bar
- **period 适配**：
  - `1d`：每个工作日 1 根 K 线
  - `1m` / `5m` / `15m` / `30m` / `60m`：暂返空（仅 1d 完整实现，其他期后续扩展）
- **volume**：固定 1000000 + seed 微扰

#### sys_config 读 + 缓存

- strategy_exec 端实现 `strategy_exec.data_access.sys_config.read(key, default=0)`
- 直连 MySQL（共享 `EVTRADE_DB_URL`）
- 内存缓存 5s（避免每次 fetch 打 DB）
- 错误/缺失 → 返 default

#### Scenario: 离线开发模式回测

- **GIVEN** `sys_config.his_hq_test_mode = '1'`
- **WHEN** EvTrade POST `/internal/run-task` 回测 (admin token + 任意策略)
- **THEN** strategy_exec 不连 RabbitMQ
- **AND** `fetch_his_bars('600519.SH', '20250101', '20250601', '1d')` 返 ~104 根工作日 K 线（确定性数据）
- **AND** run_backtest 正常完成 → DB `status='finished'`，pnl / trades_count / backtest_result 全有
- **AND** 前端 ws 收到 4 条 task_progress_update（load_script / build → / running / done）

#### Scenario: 关闭 mock 走真实 broker

- **GIVEN** `sys_config.his_hq_test_mode = '0'`（默认）
- **WHEN** strategy_exec 调 `fetch_his_bars`
- **THEN** 走真实 RabbitMQ 流程（与原行为一致）
- **AND** broker 不响应时返 `HQHistoryError` (BROKER_ERROR 502) — 与原行为一致

### § 新增 REQ-SE-014: stale-queued cleanup (admin only)

**Why**：dev 环境无 broker 时，老 queued 任务永远卡 queued。前端看到「排队中」但实际是历史遗留。

#### 端点

```
POST /api/script-strategy/strategies/{strategy_id}/stale-queued/cleanup
```

- admin only：非 admin 返 403 FORBIDDEN
- strategy 不存在：返 404 NO_STRATEGY
- 阈值默认 24h（与 stale-queued 视觉标记一致）

#### helper `server.services.script_strategy.batches.mark_stale_queued_failed`

- 单 SQL:
  ```sql
  UPDATE strategy_task
     SET status = 'failed',
         error_msg = 'broker his_hq unavailable (回填 2026-08-29 离线 mock 后) — 建议重测',
         version = version + 1,
         updated_at = NOW()
   WHERE strategy_id = :sid
     AND status = 'queued'
     AND started_at IS NULL
     AND created_at < NOW() - INTERVAL :h HOUR
  ```
- 返 rowcount (int cleaned_count)
- **不删行**，仅 UPDATE status
- 乐观锁更新（与 update_task_status 一致）

#### 数据安全（用户硬规则 2026-08-27）

- 不 drop / truncate / delete from / ALTER
- 不动 strategy_task schema
- 仅 UPDATE status（行保留，owner/admin 决定后续重测）

#### Scenario: admin cleanup 老 queued

- **GIVEN** admin token + strategy 有 N 条老 queued (started_at IS NULL + age > 24h)
- **WHEN** admin POST `/strategies/{id}/stale-queued/cleanup`
- **THEN** 返 `200 {strategy_id, cleaned_count: N}`
- **AND** DB 中老 task status 从 'queued' → 'failed', error_msg 记录 cleanup 原因
- **AND** 行数不变（不删行）
- **WHEN** 非 admin 调
- **THEN** 返 `403 FORBIDDEN`
- **WHEN** strategy 不存在
- **THEN** 返 `404 NO_STRATEGY`

## 影响面

| 模块 | 影响 |
|---|---|
| strategy_exec/strategy_exec/market_data/mock_history.py | 新增 ~80 行 |
| strategy_exec/strategy_exec/market_data/hq_history.py | +30 行 |
| strategy_exec/strategy_exec/data_access/sys_config.py | 新增 ~25 行 |
| server/infra/db.py | +10 行 |
| server/main.py | +3 行 |
| server/services/script_strategy/batches.py | +25 行 |
| server/api/script_strategy/strategies.py | +25 行 |
| scripts/evctl.py | +30 行 |
| tests/strategy_exec/test_mock_history.py | ~60 行 |
| tests/strategy_exec/test_sys_config_cache.py | ~40 行 |
| server/tests/strategy/test_stale_queued_cleanup.py | ~50 行 |

## 不修改

- 不动 RabbitMQ 拓扑 / queue / exchange
- 不动 broker / QMT 真实链路
- 不动 signal_consumer / task_progress_consumer
- 不动策略算法 (run_backtest / sweep)
- 不动 MySQL schema / 不删行
- 不动老 queued 任务原始数据 (created_at / progress / params)
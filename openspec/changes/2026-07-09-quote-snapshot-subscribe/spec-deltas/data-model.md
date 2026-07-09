# Spec Delta: data-model

## MODIFIED Requirements

### Requirement: QuoteSnapshot 表写入流程（v1：latest-only）

`quote_snapshots` 表在 QuoteConsumer 收到 hqserver tick 时按 stock_code UPSERT。

#### Scenario: 收到 tick 时

- **WHEN** QuoteConsumer._fanout_tick 收到任意 tick
- **AND** `_parse_tick` 成功解析 stock_code（last_price + fields）
- **THEN** 调用 `repo.quote_snapshots.upsert(db, parsed_snapshot_data)`：
  - INSERT 到 quote_snapshots（23 字段 + ts = utcnow）
  - ON CONFLICT (stock_code) DO UPDATE SET 所有数值字段 + ts
- **AND** 表行数 = 当前最新价格覆盖次数累计（latest-only 模型，不增加历史行）
- **AND** upsert 失败 → log.error，不抛出，不阻塞后续 tick

#### Scenario: 批量读最新

- **WHEN** 前端订阅 N 个标的（subscribe 请求）
- **THEN** 后端 `repo.quote_snapshots.get_latest_multi(db, [stock_code,...])`：
  - WHERE stock_code IN (...) ORDER BY ts DESC，每个 code 取 1 行
  - 按 stock_code 分组成 dict，缺数据键缺失
- **AND** 返回 dict 用于 ws 推多条 `snapshot` 帧

#### Scenario: 单查最新

- **WHEN** 任意模块要查 stock_code 的当前快照
- **THEN** `repo.quote_snapshots.get_latest(db, stock_code)` 返单行或 None

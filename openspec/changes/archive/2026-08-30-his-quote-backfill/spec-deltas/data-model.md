# data-model — Spec Delta (2026-08-30)

## 修改类型
ADDED — 登记 2 张表：`minute_bars`（行情分钟 K 线）+ `quote_sync_config`（行情同步任务表/配置）

## 变更内容

### ADDED: `minute_bars` — 历史分钟 K 线表

| 列 | 类型 | PK | 说明 |
|---|---|---|---|
| `stock_code` | String(16) | ✓ | 证券代码（如 159992.SZ） |
| `stime` | String(16) | ✓ | 14 位 `YYYYMMDDHHMMSS`（broker/strategy_exec 全链路一致） |
| `open` | Float | | 开盘（元/股） |
| `close` | Float | | 收盘（元/股） |
| `high` | Float | | 最高（元/股） |
| `low` | Float | | 最低（元/股） |
| `avg_price` | Float | | 均价 = VWAP = `amount/(volume*100)`（元/股；A股 volume 单位是手，1 手=100 股） |
| `volume` | Integer | | 成交量（手） |

- 主键 `(stock_code, stime)` 复合 — 多标的复用，写入 `ON DUPLICATE KEY UPDATE` 幂等可重跑
- 数据源：broker his_hq 1m（xtquant `get_market_data_ex` 返 OHLCV+amount）
- 写入者：`server/services/quote_sync/broker.py`（前端驱动按日）/ `scripts/fetch_minute_bars.py`（CLI backdoor）
- 读取者：回测 / 分析（本 change 不含）

### ADDED: `quote_sync_config` — 行情同步任务表（配置）

| 列 | 类型 | PK | 说明 |
|---|---|---|---|
| `stock_code` | String(16) | ✓ | 证券代码 |
| `start_date` | String(8) | | 时间区间起点 YYYYMMDD |
| `end_date` | String(8) | | 时间区间终点（空串=开放，补到昨天） |
| `last_loaded_date` | String(8) | | 当前已加载到的日期（游标），成功同步后推进 |
| `auto_sync` | Integer(1) | | 启用自动同步标志（1/0，默认 1） |

- 该表即"要跟踪并自动补全的证券"配置；往表加一行 = 声明跟踪该证券
- `last_loaded_date` 是续传游标：前端从 `last_loaded_date+1` 逐日补到 `min(end_date||昨天, 昨天)`
- 新增配置时 `last_loaded_date` 自动 = `MIN(昨天, COALESCE(MAX(minute_bars 该标 stime 日期), start_date))`

## Scenario: 按日补全游标推进

- **WHEN** 前端对 `quote_sync_config` 某行（last_loaded_date=20260824）调 `POST /api/quote-sync/sync {stock_code, date=20260825}`
- **THEN** broker 返 20260825 当日 1m K 线 → upsert `minute_bars`
- **AND** 成功后 `quote_sync_config.last_loaded_date = 20260825`
- **AND** 前端进下一天；若 broker 失败 → `last_loaded_date` 不变，返失败原因

## Scenario: 昨天封顶

- **WHEN** 当前日期 2026-08-30，end_date 空
- **THEN** 补全末天 = 2026-08-29（昨天），今天 08-30 数据不全不进

## 影响面
- `server/schema.yml` +2 表定义
- `server/tables/{minute_bars,quote_sync_config}.py` + `__init__.py` 导出
- Tables Overview 总业务表数 20 → 22

## 不修改
- 不动现有 20 张表
- 不 drop/rebuild（只 ADD）

## 测试覆盖
- `server/tests/services/quote_sync/test_broker.py`（VWAP / 空日 / _weekdays_in）
- `server/tests/test_api_quote_sync.py`（list/add/delete/sync 游标推进）

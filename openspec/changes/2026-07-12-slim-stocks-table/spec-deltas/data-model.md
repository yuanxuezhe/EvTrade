# Spec Delta: data-model — §13 stocks 表瘦身（v23 2026-07-12）

## MODIFIED Requirements

### Requirement: §13 stocks 表字段定义

精简 stocks 表字段，从 14 个业务字段裁剪到 6 个业务字段（保留 3 个 + 新增 3 个）。

#### REMOVED Fields（9 个已删除）

- ~~`industry`~~ 已删除 — 行业字段前端从未消费
- ~~`market`~~ 已删除 — 市场从 `stock_code` 后缀派生
- ~~`list_date`~~ 已删除 — 上市日期未在 UI 展示
- ~~`total_share`~~ 已删除 — 总股本未在 UI 展示
- ~~`float_share`~~ 已删除 — 流通股本未在 UI 展示
- ~~`market_cap`~~ 已删除 — 总市值未在 UI 展示
- ~~`pe_ratio`~~ 已删除 — PE 未在 UI 展示
- ~~`pb_ratio`~~ 已删除 — PB 未在 UI 展示
- ~~`intro`~~ 已删除 — 公司简介未在 UI 展示

#### MODIFIED Fields（保留）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `stock_code` | VARCHAR(16) | NO | — | 股票代码(PK,如 `000001.SZ`) |
| `stock_name` | VARCHAR(64) | NO | `""` | 股票名(如 `平安银行`) |
| `sector` | VARCHAR(64) | YES | NULL | 板块(申万二级,前端筛选/编辑) |

#### ADDED Fields（3 个新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `is_t0_able` | TINYINT(1) | NO | `0` | 回转标志 (FALSE=不可 T+0, TRUE=可 T+0) |
| `min_buy_qty` | INT | NO | `100` | 最小买入数量 (A 股默认 100 股) |
| `trade_unit` | INT | NO | `1` | 买卖单位 (序号无义,默认 1) |

#### REMOVED Indexes（2 个索引已删除）

- ~~`ix_stocks_industry`~~ 已删除 — industry 字段不存在
- ~~`ix_stocks_market`~~ 已删除 — market 字段不存在

#### Scenario: 字段精简后的 API 返回结构

- **GIVEN** stocks 表已迁移，字段裁剪到 6 个
- **WHEN** `GET /api/stocks` 返回列表
- **THEN** 每行 dict 仅包含：`stock_code`, `stock_name`, `sector`, `is_t0_able`, `min_buy_qty`, `trade_unit`
- **AND** 不再包含：`industry`, `market`, `list_date`, `total_share`, `float_share`, `market_cap`, `pe_ratio`, `pb_ratio`, `intro`

#### Scenario: 历史数据保留在 stocks_legacy

- **GIVEN** 迁移前 stocks 表有 N 行数据
- **WHEN** 执行 `2026-07-12-slim-stocks-table.py`
- **THEN** `CREATE TABLE stocks_legacy AS SELECT * FROM stocks` 完整保留原 14 字段
- **AND** 原 stocks 表字段裁剪到 6 字段
- **AND** 原 N 行数据根据迁移策略丢弃（裁剪后字段值不可用）

#### Scenario: admin 编辑 stocks 字段白名单

- **GIVEN** admin 调用 `PATCH /api/stocks/{code}` with body `{stock_name, sector, is_t0_able, min_buy_qty, trade_unit}`
- **WHEN** 请求处理
- **THEN** 6 字段全部可被覆盖
- **AND** 字段名错误（`industry` / `pe_ratio` 等）返 422 拒绝
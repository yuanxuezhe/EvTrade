# Spec Delta: data-model §13 stocks 表加 short_name 字段

**Change**: 2026-07-12-stocks-cache-and-short-name
**Target**: `openspec/specs/data-model/spec.md` §13

## 增量内容

### §13. `stocks` — 股票基础信息表（v23 → v25 增量）

新增字段 `short_name`：

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `short_name` | VARCHAR(16) | YES | NULL | **拼音首字母简称**(如「平安银行」→ `PAYH`),用于首字母快速筛选 |

**说明**:
- 加在 `stock_code` 之后(同 VARCHAR 16 列族)
- 可空:存量数据 backfill 前为 NULL,backfill 后所有 5529 行均有值
- 用户"自己去维护":不再走自动同步,新增/重命名需手动 SQL UPDATE

**索引**: 不单独加索引(全量 cache 在前端,后端 LIKE 前缀查询 5529 行毫秒级)

**backfill 脚本**:
- `server/scripts/backfill_short_name.py` 用 `pypinyin.lazy_pinyin(s)` 取每个字首字母,拼接大写
- 一次性跑: `python3 server/scripts/backfill_short_name.py`
- 幂等:已填的不覆盖

### Scenario: short_name 自动 backfill

- **GIVEN** stocks 表 5529 行,`short_name` 全部为 NULL
- **WHEN** 跑 `python3 server/scripts/backfill_short_name.py`
- **THEN** 每行 `short_name` 填入 `stock_name` 的拼音首字母大写
- **AND** 进度日志每 500 行打印一次
- **AND** 失败行(如空 stock_name)打印警告但不中断

### Scenario: admin 编辑 short_name 字段

- **GIVEN** admin 调用 `PATCH /api/stocks/{code}` with body `{short_name: 'PAYH'}`
- **WHEN** 请求处理
- **THEN** short_name 被更新到 DB
- **AND** 返回的完整 stock 对象含 `short_name` 字段

### Scenario: Pydantic 字段白名单扩展

- **GIVEN** StockUpdateRequest 之前 5 字段(stock_name/sector/is_t0_able/min_buy_qty/trade_unit)
- **WHEN** v25 改动
- **THEN** 加 `short_name: Optional[str] = Field(None, max_length=16)`
- **AND** extra=forbid 仍生效,9 旧字段(industry/market/...)继续 422
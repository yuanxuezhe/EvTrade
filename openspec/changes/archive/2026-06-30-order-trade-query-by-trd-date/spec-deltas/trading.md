# trading delta — 委托/成交按 trd_date 区间查询

## MODIFIED Requirements

### REQ-TRADE-001: 查询 — 委托/成交区间过滤

**Before:**
- `GET /api/orders?stock_code=...` — 委托列表（走 `qry_orders`），按激活日 trd_date 过滤
- `GET /api/trades?stock_code=...` — 成交列表（走 `qry_trades`），`ORDER BY created_at DESC`（DB 入库时间）
- 响应 `{code: 0, msg: "", list: [...]}`

**After:**
- `GET /api/orders?stock_code=...&start_date=YYYYMMDD&end_date=YYYYMMDD` — 委托列表
- `GET /api/trades?stock_code=...&start_date=YYYYMMDD&end_date=YYYYMMDD` — 成交列表
- 新增 query 入参语义：
  - 两个都缺省 → 维持原行为（按激活日 trd_date 过滤）
  - 仅 `start_date` → `trd_date >= start_date`
  - 仅 `end_date` → `trd_date <= end_date`
  - 都给 → `start_date <= trd_date <= end_date`
- 参数格式：8 位数字字符串 `^\d{8}$`，FastAPI 自动 422 校验
- 排序：`GET /api/trades` 改为 `ORDER BY trade_time DESC, trade_id DESC`（trade_time 同秒二级 trade_id 兜底）

#### 入参校验（Pydantic v1 约束）

- `Query(None, regex=r"^\d{8}$", description="...")` — Pydantic v1 用 `regex=`，v2 才改名 `pattern=`
- 项目 `requirements.txt` 锁 `pydantic>=1.9.0,<2.0.0`，本轮保持 `regex=`

#### 向后兼容

- 所有现有调用方（bootstrap、place 响应的 list 风格、admin reconcile）不传新参数 → 行为完全不变
- `ListOrdersResponse` / `TradesListResponse` schema 字段不变
- `OrderOut.trd_date` / `TradeOut.trd_date` 字段已在（v6/v7 已加）

## Cross-References

- 实施计划：`docs/superpowers/plans/2026-06-30-order-trade-query-by-trd-date.md`（commit `5a183a6`）
- 设计稿：`docs/superpowers/specs/2026-06-30-order-trade-query-by-trd-date-design.md`（commit `df493cd`）
- 实施 commits：`7006af2` / `fa15e88` / `751cfc7` / `1e75a13`
- 验证：`server/test_trades_api.py` 区间 + 排序用例

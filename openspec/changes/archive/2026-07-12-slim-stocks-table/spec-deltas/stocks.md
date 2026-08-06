# Spec Delta: stocks — REQ-STOCK-005 字段映射瘦身（v23 2026-07-12）

## MODIFIED Requirements

### Requirement: REQ-STOCK-005 东方财富数据源适配契约

字段映射裁剪到 6 个核心业务字段。

#### REMOVED Field Mappings

- ~~`INDUSTRYCSRC1` → `industry`~~ 已删除
- ~~`INDUSTRYCSRC2` → `sector`~~ 保留为 sector（板块字段重命名/映射保留）
- ~~`REG_CAPITAL`~~ 已删除
- ~~`ORG_PROFILE` → `intro`~~ 已删除
- ~~`TRADE_MARKET` → `market`~~ 已删除（market 从 stock_code 派生）

#### MODIFIED Field Mappings（保留）

```python
# 字段映射（→ Stock ORM）
SECUCODE            → stock_code        # 保留
SECURITY_NAME_ABBR  → stock_name        # 保留
INDUSTRYCSRC2       → sector            # 板块(申万二级)，保留
```

#### ADDED Field Sources（新增 — admin 手动维护）

```python
# 以下字段由 admin 手动设置，不从东方财富 API 抓取：
is_t0_able   → 是否支持 T+0 回转交易（默认 FALSE）
min_buy_qty  → 最小买入数量（默认 100 股，A 股标准）
trade_unit   → 买卖单位（默认 1，序号无业务意义）
```

#### Scenario: crawler 拉取字段裁剪

- **GIVEN** 同步任务从东方财富拉取 `000001.SZ`
- **WHEN** `eastmoney.fetch_base_info(stock_code)` 调用
- **THEN** 返回 dict 仅含：`stock_code`, `stock_name`, `sector`
- **AND** 不再含：`industry`, `market`, `intro`, `list_date`, `total_share`, `float_share`, `market_cap`, `pe_ratio`, `pb_ratio`

#### Scenario: WS stock_synced payload 字段同步

- **GIVEN** 单只股票 upsert 成功
- **WHEN** runner 推送 `stock_synced` WS 消息
- **THEN** payload `data` 字段仅含：`stock_code`, `stock_name`, `sector`
- **AND** 6 字段（`is_t0_able` / `min_buy_qty` / `trade_unit`）**不**通过 WS 推送（admin 编辑触发本地缓存更新，不广播）

#### Scenario: admin 编辑新增字段

- **GIVEN** admin 在 `/admin/stock-config` 页面编辑单只股票
- **WHEN** 修改 `is_t0_able` / `min_buy_qty` / `trade_unit`
- **THEN** `PATCH /api/stocks/{code}` 白名单接受这 3 字段
- **AND** 字段持久化到 stocks 表
- **AND** 前端本地缓存同步更新（**不**广播 WS，v22 范围最小化保留）
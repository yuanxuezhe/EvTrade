# 历史 trades.amount 一致性 backfill

## 1. Why

change `system-delegation-price-fill-calc`（2026-07-02）T11.1 dry-run 发现历史 trades 表存在 `amount != price × volume` 的脏数据：

```
total trades rows:        1
amount != price * volume: 1
inconsistency rate:       100.00%

--- sample ---
trd_date | trade_id | order_no | price | volume | amount | expected
20260702 | 319025875780432 | 10000001 | 10.28 | 7200 | 0.0 | 74016.0
```

1 条历史 trade（20260702）amount 被记为 0，应为 74016.0。
原因为本 change 之前的 push handler 未做 `amount = price × volume` 本地算（broker 推送的 amount=0 时被采纳）。

## 2. 修复方案（草案）

### 2.1 一次性 backfill SQL

```sql
UPDATE trades
SET amount = ROUND(price * volume, 4),
    updated_at = datetime('now')
WHERE ABS(amount - price * volume) > 0.01;
```

预期影响：仅本次扫描出的 1 行（trd_date=20260702, trade_id=319025875780432）。

### 2.2 关联 trades.amount 修复后的 orders.traded_amount / orders.avg_price 同步

对涉及到的 order_no，重算对应 Order 的累计字段：

```sql
WITH per_order AS (
  SELECT order_no, trd_date,
         SUM(amount) AS new_traded_amount,
         SUM(volume) AS new_traded_volume
  FROM trades
  WHERE order_no IN (
    SELECT DISTINCT order_no FROM trades
    WHERE ABS(amount - price * volume) > 0.01
  )
  GROUP BY order_no, trd_date
)
UPDATE orders
SET traded_amount = (SELECT new_traded_amount FROM per_order
                     WHERE per_order.order_no = orders.order_no
                       AND per_order.trd_date = orders.trd_date),
    traded_volume = (SELECT new_traded_volume FROM per_order
                     WHERE per_order.order_no = orders.order_no
                       AND per_order.trd_date = orders.trd_date),
    avg_price = CASE WHEN (SELECT new_traded_volume FROM per_order
                            WHERE per_order.order_no = orders.order_no
                              AND per_order.trd_date = orders.trd_date) > 0
                     THEN (SELECT new_traded_amount FROM per_order
                           WHERE per_order.order_no = orders.order_no
                             AND per_order.trd_date = orders.trd_date)
                          / (SELECT new_traded_volume FROM per_order
                             WHERE per_order.order_no = orders.order_no
                               AND per_order.trd_date = orders.trd_date)
                     ELSE avg_price END,
    updated_at = datetime('now')
WHERE (order_no, trd_date) IN (
  SELECT order_no, trd_date FROM trades
  WHERE ABS(amount - price * volume) > 0.01
);
```

## 3. 范围与豁免

- **不在线执行**：本 issue 仅记录 backfill SQL 草案，实际执行需：
  - 开停盘窗口
  - 备份 data/evtrade.db
  - 跑完跑一次 dry-run 复查（行数应=0）
  - 由用户手动确认
- **不影响 change `system-delegation-price-fill-calc` 验收**：该 change 关注的是从今往后 amount 写入语义统一，历史脏数据由本 issue 独立处理。
- **执行人**：下次数据库维护窗口（待定）

## 4. 验收

- backfill 完成后 dry-run 结果：`mismatch = 0`
- 对应 Order 的 traded_amount / traded_volume / avg_price 与 trades 表现一致
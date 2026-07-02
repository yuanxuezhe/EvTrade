# 历史 orders.status 一致性 backfill

## 1. Why

change `align-status-codes-to-xtconstant`（2026-07-02）完成后，所有 status 写入点
（`place.py` / `cancel.py` / `push/handlers._infer_order_status` / 前端
`inferOrderStatus`）均改用 broker xtconstant 字典（48-57 + 255）。

但历史 DB 中的 Order.status 仍可能是本地旧码（49/50/51/53/56 等），导致前端 STATUS_LABEL
按 broker 字典查表时返回错位的标签（例如旧的 `'53' = 本地已撤` → 新字典 `'53' = broker 部成部撤`）。

需一次性 backfill 把历史行的 status 翻译为 broker 码。

## 2. 当前 dev DB 情况（dry_run_status_distribution.py）

```
$ python scripts/dry_run_status_distribution.py
orders total:    0
distinct status: 0
cancel rows:     0  (order_flag=1)
```

dev DB 暂时为空（0 行），**当下无 backfill 动作可做**。

历史会话记录（2026-07-02 之前）曾发现：

```
orders total: 1
cancel rows:  1   (该行 status='53' 本地已撤, 需改 → '54' broker 已撤)
```

后续 dev DB 可能有更多历史数据；正式 backfill 前**必须重跑 dry-run**重新评估行数。

## 3. 修复方案（草案）

### 3.1 翻译规则（本地旧码 → broker 码）

| 本地码 | 含义（旧） | broker 码 | 含义（新） | 风险 |
|--------|-----------|-----------|-----------|------|
| 49     | 本地已报  | 50        | broker 已报 | 低：与 broker 49=待报 区分 |
| 50     | 本地部成  | 55        | broker 部成 | 低 |
| 51     | 本地已成  | 56        | broker 已成 | **中：与 broker 51=已报待撤 区分** |
| 53     | 本地已撤  | 54        | broker 已撤 | **中：与 broker 53=部成部撤 区分** |
| 56     | 本地部成部撤 | 53     | broker 部成部撤 | **中：与 broker 56=已成 区分** |
| 55     | 本地废单  | 57        | broker 废单 | **中：与 broker 55=部成 区分** |

⚠️ **关键风险**：本表为多对多映射，单凭 status 字段无法无歧义翻译。必须结合
`order_flag` / `traded_volume` / `cancelled_volume` / `volume` 等旁证字段做联合判断。

### 3.2 联合判断 SQL（推荐方案）

```sql
-- Dry-run: 评估每个 status 分类的实际影响行数
-- 不做 UPDATE,只 SELECT

-- 类别 A: cancel-row (order_flag=1) status='53' 本地已撤 → '54' broker 已撤
SELECT 'cancel-row 53→54', COUNT(*)
FROM orders
WHERE order_flag = 1 AND status = '53';

-- 类别 B: 原单 status='49' 本地已报 → '50' broker 已报
--         旁证: traded_volume = 0 且 cancelled_volume = 0
SELECT 'orig 49→50 (pure 已报)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '49'
  AND IFNULL(traded_volume, 0) = 0 AND IFNULL(cancelled_volume, 0) = 0;

-- 类别 C: 原单 status='50' 本地部成 → '55' broker 部成
--         旁证: 0 < traded_volume < volume 且 cancelled_volume = 0
SELECT 'orig 50→55 (部成)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '50'
  AND IFNULL(traded_volume, 0) > 0
  AND IFNULL(traded_volume, 0) < IFNULL(volume, 0)
  AND IFNULL(cancelled_volume, 0) = 0;

-- 类别 D: 原单 status='51' 本地已成 → '56' broker 已成
--         旁证: traded_volume = volume 且 cancelled_volume = 0
SELECT 'orig 51→56 (已成)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '51'
  AND IFNULL(traded_volume, 0) = IFNULL(volume, 0)
  AND IFNULL(cancelled_volume, 0) = 0;

-- 类别 E: 原单 status='53' 本地已撤 → '54' broker 已撤
--         旁证: cancelled_volume > 0 且 traded_volume = 0
SELECT 'orig 53→54 (pure 已撤)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '53'
  AND IFNULL(cancelled_volume, 0) > 0
  AND IFNULL(traded_volume, 0) = 0;

-- 类别 F: 原单 status='53' 本地已撤 (部分撤) → '54' broker 已撤 (运营归类)
--         旁证: 0 < traded_volume < volume 且 cancelled_volume > 0
SELECT 'orig 53→54 (部撤归已撤)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '53'
  AND IFNULL(cancelled_volume, 0) > 0
  AND IFNULL(traded_volume, 0) > 0
  AND IFNULL(traded_volume, 0) < IFNULL(volume, 0);

-- 类别 G: 原单 status='56' 本地部成部撤 → '53' broker 部成部撤
--         旁证: 0 < traded_volume < volume 且 cancelled_volume > 0
SELECT 'orig 56→53 (部成部撤)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '56'
  AND IFNULL(cancelled_volume, 0) > 0
  AND IFNULL(traded_volume, 0) > 0
  AND IFNULL(traded_volume, 0) < IFNULL(volume, 0);

-- 类别 H: 原单 status='55' 本地废单 → '57' broker 废单
--         旁证: cancelled_volume = volume (一次性抹平)
SELECT 'orig 55→57 (废单)', COUNT(*)
FROM orders
WHERE order_flag = 0 AND status = '55'
  AND IFNULL(cancelled_volume, 0) = IFNULL(volume, 0);
```

### 3.3 Backfill UPDATE（联合条件防误判）

```sql
BEGIN TRANSACTION;

-- 类别 A: cancel-row 53 → 54
UPDATE orders SET status = '54', updated_at = datetime('now')
WHERE order_flag = 1 AND status = '53';

-- 类别 B: 原单 49 → 50 (纯已报)
UPDATE orders SET status = '50', updated_at = datetime('now')
WHERE order_flag = 0 AND status = '49'
  AND IFNULL(traded_volume, 0) = 0 AND IFNULL(cancelled_volume, 0) = 0;

-- 类别 C: 原单 50 → 55 (部成)
UPDATE orders SET status = '55', updated_at = datetime('now')
WHERE order_flag = 0 AND status = '50'
  AND IFNULL(traded_volume, 0) > 0
  AND IFNULL(traded_volume, 0) < IFNULL(volume, 0)
  AND IFNULL(cancelled_volume, 0) = 0;

-- 类别 D: 原单 51 → 56 (已成)
UPDATE orders SET status = '56', updated_at = datetime('now')
WHERE order_flag = 0 AND status = '51'
  AND IFNULL(traded_volume, 0) = IFNULL(volume, 0)
  AND IFNULL(cancelled_volume, 0) = 0;

-- 类别 E + F: 原单 53 → 54 (已撤类全部归 broker 已撤, 运营角度)
UPDATE orders SET status = '54', updated_at = datetime('now')
WHERE order_flag = 0 AND status = '53'
  AND IFNULL(cancelled_volume, 0) > 0;

-- 类别 G: 原单 56 → 53 (部成部撤)
UPDATE orders SET status = '53', updated_at = datetime('now')
WHERE order_flag = 0 AND status = '56'
  AND IFNULL(cancelled_volume, 0) > 0
  AND IFNULL(traded_volume, 0) > 0
  AND IFNULL(traded_volume, 0) < IFNULL(volume, 0);

-- 类别 H: 原单 55 → 57 (废单)
UPDATE orders SET status = '57', updated_at = datetime('now')
WHERE order_flag = 0 AND status = '55'
  AND IFNULL(cancelled_volume, 0) = IFNULL(volume, 0);

COMMIT;

-- 复查: 没有任何本地旧码残留
SELECT status, COUNT(*) FROM orders
WHERE status IN ('49', '50', '51', '53', '56', '55')
GROUP BY status;
-- 预期: 0 行
```

## 4. 范围与豁免

- **不在线执行**：本 issue 仅记录 backfill SQL 草案，实际执行需：
  - 开停盘窗口
  - 备份 `data/evtrade.db`
  - 先跑 §3.2 dry-run 评估每类影响行数（应为 0 或预期数）
  - 由用户手动确认后再跑 §3.3 UPDATE
  - 跑完再跑 §3.3 末尾复查（残留应为 0）
- **不影响 change `align-status-codes-to-xtconstant` 验收**：该 change 关注的是从今往后 status 写入语义统一，历史脏数据由本 issue 独立处理。
- **与 `tracking/2026-07-02-trades-amount-backfill` 同步执行**：两个 backfill 在同一个维护窗口跑完。
- **执行人**：下次数据库维护窗口（待定）。dev DB 当前为空，无需立即行动。

## 5. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 旧码本意已不可辨（脏数据） | 低 | 行翻译错位 → 前端字典查表仍不对 | §3.2 dry-run 联合条件, 仅旁证明确的行才改 |
| UPDATE 漏条件把不该改的改了 | 中 | 静默错位 | 跑前备份, 跑后复查 `status IN ('49','50','51','53','55','56')` 应=0 |
| broker 字典 future 改回本地码 | 极低 | 历史行又不对 | 留 rollback: §6 |
| dev DB 与生产数据不一致 | 低 | dry-run 评估行数 ≠ 生产实际 | 在生产前重跑 dry-run（dry-run 是只读，无风险）|

## 6. Rollback

```sql
-- 假设已经记录了变更前 status 的快照 (-- pre-status 备份字段名)
-- 部署时建议先加 ALTER TABLE ... ADD COLUMN pre_status VARCHAR(2) 暂存

UPDATE orders SET status = pre_status
WHERE pre_status IS NOT NULL;

-- 跑完后清理
ALTER TABLE orders DROP COLUMN pre_status;
```

或最简回滚：从 §3 "执行前" 备份的 sqlite 还原文件。

## 7. 验收

- §3.2 dry-run 每类行数与历史会话记录一致（dev DB 当前为 0，生产/历史库需重新评估）
- §3.3 UPDATE 影响行数 = §3.2 dry-run 评估行数
- §3.3 末尾复查残留 = 0
- 前端 STATUS_LABEL 按 broker 字典解读历史行，无错位标签
- E2E 冒烟（task 6.5）通过：dev 环境手动跑，下单/撤单/推送链路正常

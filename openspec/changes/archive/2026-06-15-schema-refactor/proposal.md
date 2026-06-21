# 2026-06-15-schema-refactor — 本地数据库 schema 字段重命名 + 配套代码改写

## Why

v4 持久化层（`server/models/orm.py`）存在以下设计问题：
- 多表用自增 `id` 整型 PK，但表已有 UNIQUE 业务键（`order_id` / `trade_id` / `stock_code` / `trd_date`），id 冗余
- 字段命名风格混乱：snake_case（`stock_code`）混大写常量（`TRD_DATE`）和缩略词（`avl_amt`）
- `assets` 用 `id=1 + TRD_DATE UNIQUE` 实现"单行"，但业务语义是"当前资金快照"，TRD_DATE 冗余
- `orders.order_remark` 与 broker 透传字段重名，被误复用为"携带本地 order_no"
- `positions` 字段名是中文式英译（`initial_position`/`total`），与柜台报文（`last_vol`/`volume`）不直接对应
- `trading_day` 表名与 `TradingDay` 类表达力不足，实际是"系统级状态机"
- 有 `trd_date` 的表缺少组合主键（按 trd_date 维度查询/唯一性不充分）

## What Changes

### 1. 清理 schema
- 去 `id`：用 UNIQUE / 复合业务键做主键
- 字段名对齐柜台报文语义
- `trd_date` 全部小写

### 2. 改写 6 张表
| 表 | 改写点 |
|---|---|
| `orders` | 删 `id` / `order_remark`；`TRD_DATE→trd_date`；复合主键 `(trd_date, order_id)`；初始 `order_id` 占位 `PENDING-{order_no}` |
| `trades` | 删 `id`；`TRD_DATE→trd_date`；复合主键 `(trd_date, trade_id)` |
| `positions` | 删 `id` / `TRD_DATE`；重命名 `initial_position→last_vol` / `available→avl_vol` / `total→vol` / `cost→cost_price`；PK = `stock_code` |
| `assets` | 删 `id` / `TRD_DATE`；无 PK，单行（push handler 负责"取首行 + 覆盖"） |
| `trading_day` → `sys_status` | 重命名表 + 类；`current_date→trd_date`；PK = `trd_date` |
| `reconcile_report` | `TRD_DATE→trd_date`；复合主键 `(trd_date, mode, created_at)`（替换原 `id`） |

### 3. 改写代码（同步）
- 后端 ORM / service / API / 路由注册
- 6 个 pytest 测试文件
- 前端 12 个 vue/js 文件
- openspec 4 个活跃 spec + 1 个新 change 提案

### 4. URL 路径
- `/api/admin/trading-day*` → **`/api/admin/sys-status*`**

## Impact

- 🟡 **破坏性变更**：旧客户端调 `/admin/trading-day*` 会 404
- 🟡 现有 `evtrade.db` 是旧 schema（带 id / 大写 TRD_DATE）→ **需 `rm evtrade.db` 后重启**，本提案不提供迁移脚本
- 🟢 柜台 RPC 协议不变
- 🟢 业务功能（盘前/盘中/盘后流程）不变

## Risk Mitigation

- 复合主键 `(trd_date, order_id)` 在 broker 未及时回 `order_id` 时，用 `PENDING-{order_no}` 占位 + `handle_ord_cfm` 通过 `remark` (= `order_no`) 兜底匹配
- 前端 store 保留兼容旧字段名 1 个版本（holdings store log 输出），不影响主路径

## Verification

1. `python -c "from models.orm import *"` 加载无错
2. 全文搜：`grep -r "TRD_DATE\|order_remark\|current_date\|initial_position" server/ client/src/ --include="*.py" --include="*.vue" --include="*.js"` 应只在 `archive/` 命中
3. `pytest server/ -v` 全绿（需 Python 3.8+，3.6 下 `AsyncMock` 不可用为已知环境问题）
4. 手动：登录 → 下单 → ord_cfm 推送回填 `order_id` → pos_cfm 推送更新 `last_vol/avl_vol/vol/cost_price`
5. 浏览器：Dashboard / Holdings / Position / Orders / Trade / T0Trade 页无 `NaN` / `undefined`

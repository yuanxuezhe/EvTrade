# Persistence layer + T0 panel (v4)

## 1. Why

当前问题（2026-06-14 评估）：
- 委托/成交/资金/持仓查询每次都调柜台 RPC：慢、依赖网络、不可重放
- 快速 T0 没有支撑（一键买卖 + 配平系数）
- 撤单失败用户无感（前一次修复仅在内存中）
- 费率硬编码在公式里
- 缺交易日屏障：日初未做时还能查到旧数据导致误下单
- 缺交易时段约束：盘后仍可下废单
- 委托/成交无法关联具体交易日
- 本地缺可幂等匹配的标识（柜台 order_id 有时漏送）
- 错误信息只 print，不落库

目标：**本地 SQLite 成为业务数据唯一展示源**；RPC 只用于"事实写入"（下单/撤单）+ 对账；交易日 + 时段双重屏障；订单序号保证幂等匹配。

## 2. What

### 2.1 命名规范（**snake_case 列名 + 8 位日期值**）

- **列名**：`snake_case`（`stock_code`、`traded_volume`、`order_no`）
- **日期值**：8 位数字字符串 `'20260614'`（字段名沿用 `TRD_DATE` 是用户约定）
- **表名**：`snake_case`（`orders`、`trading_day`）
- **不**采用 ALL_CAPS 列名（与 SQLAlchemy 默认一致，避免 20+ 字段重写）

### 2.2 新增 10 张表

| # | 表名 | 用途 | 写入源 |
|---|---|---|---|
| 1 | `orders` | 委托主表 | place_order INSERT / ord_cfm UPSERT / 对账覆盖 |
| 2 | `trades` | 成交表 | trd_cfm UPSERT / 对账覆盖 |
| 3 | `positions` | 持仓表 | pos_cfm UPSERT / 对账覆盖 |
| 4 | `assets` | 资金表（单行）| ast_cfm UPDATE / 对账覆盖 |
| 5 | `quote_snapshots` | 行情快照 | hqserver push |
| 6 | `fee_config` | 费率（单行）| 前端 Settings |
| 7 | `trading_day` | 交易日状态机 | 日初处理 |
| 8 | `trading_session` | 时段配置（单行）| admin 配置 |
| 9 | `reconcile_config` | 对账配置（单行）| admin 配置 |
| 10 | `reconcile_report` | 对账历史 | 日初处理 |
| 11 | `order_no_seq` | 订单序号生成器（单行）| place_order |

### 2.3 屏障矩阵

| 屏障 | 下单 | 撤单 | 查询 | 日初 |
|---|---|---|---|---|
| `require_trading_day` | ✅ | ✅ | ❌ | ❌ |
| `require_trading_session` | ✅ | ✅ | ❌ | ❌ |
| `require_trader` | ✅ | ✅ | ❌ | ❌ |
| `require_admin` | ❌ | ❌ | ❌ | ✅ |

### 2.4 默认查询交易日

```python
def resolve_default_trd_date(db) -> str:
    """返回 8 位数字日期字符串"""
    active = db.query(TradingDay).filter_by(status='active').first()
    if active:
        return active.current_date  # 已激活 → 用当日
    # 未激活 → 兜底：取本地表 MAX
    row = db.execute(text("SELECT MAX(TRD_DATE) FROM orders")).first()
    if row and row[0]:
        return row[0]
    return datetime.now().strftime('%Y%m%d')
```

API 支持 `?trading_day=20260614` 覆盖默认。

### 2.5 下单流程

```
1. POST /api/orders/place
2. require_trading_day → 503 TRADING_DAY_NOT_INIT
3. require_trading_session → 503 OUTSIDE_TRADING_SESSION
4. 幂等：client_order_id 已在 → 200 + 原单
5. 生成 order_no（原子递增，8 位）
6. INSERT orders (status="48"待报, TRD_DATE=current, ORDER_RMRK=order_no)
7. 调 ord_stk(..., remark=order_no)
8. 成功 → UPDATE order_id, status="49"已报
9. 失败 → UPDATE status="55"废单, status_msg=err
10. 推 WS order_update
```

### 2.6 撤单流程

```
1. DELETE /api/orders/{id}
2. require_trading_day + require_trading_session
3. SELECT orders WHERE order_id=? → 404
4. 调 rpc_cancel_order(order_id)
5. 成功 → 不本地改 status（等 push 推 53已撤）
6. 失败 → 500 + 错误信息
```

### 2.7 push 处理（4 类）

| 推送 | 落库 | 匹配键 | 触发 WS |
|---|---|---|---|
| `ord_cfm` | UPSERT orders | order_id 优先，ORDER_RMRK 兜底 | order_update |
| `trd_cfm` | UPSERT trades + UPDATE orders.traded_volume/avg_price | order_id | trade_update + order_update |
| `pos_cfm` | UPSERT positions | stock_code | position_update |
| `ast_cfm` | UPDATE assets (单行) | id=1 | asset_update |

### 2.8 日初处理

```
POST /api/admin/trading-day/init
1. 取 reconcile_config（auto_reconcile / auto_use_broker_data）
2. RPC 并行：qry_asset + qry_pos + qry_orders + qry_mch
3. 算 diff
4. auto=True → 覆盖本地 4 张表
   auto=False → 写 reconcile_report，不动数据
5. RPC 失败 → 503，不切交易日，可重试
6. 成功 → 关闭旧 active + 新增 active
```

### 2.9 T0 配平计算

新增 `server/services/t0.py`，计算：
- 盈亏平衡回补价/量
- 含费率（commission + stamp_tax + slippage）
- 一键下单 `POST /api/t0/execute`（默认对手价 price_type=14）

### 2.10 前端改动

- `client/src/stores/clock.js`（新）：轮询 `/api/trading/clock`
- `client/src/utils/guards.js`（新）：拦截 503 错误码
- `Trade.vue`：按钮置灰（无时钟/无 session）
- `Settings.vue`（新）：费率编辑页
- `AdminTradingDay.vue`（新）：日初处理页
- 顶部 banner：未初始化时红条提示

## 3. Impact

| 文件 | 改动 |
|---|---|
| `server/models/types.py` | +10 ORM models |
| `server/db.py` | +10 表初始化 |
| `server/services/guards.py` | 新增（屏障） |
| `server/services/trading_clock.py` | 新增（时段判断） |
| `server/services/t0.py` | 新增（配平算法） |
| `server/services/reconcile.py` | 新增（日初对账） |
| `server/services/order_no.py` | 新增（8 位序号生成器） |
| `server/api/orders.py` | 重写：先写 DB 再调 RPC |
| `server/api/trades.py` | 查询改 DB |
| `server/api/positions.py` | 查询改 DB |
| `server/api/asset.py` | 查询改 DB |
| `server/api/t0.py` | 新增 |
| `server/api/settings.py` | 新增（费率 CRUD） |
| `server/api/admin/trading_day.py` | 新增（日初处理） |
| `server/api/admin/reconcile.py` | 新增（对账配置 + 历史） |
| `server/api/admin/session.py` | 新增（时段配置） |
| `server/api/clock.py` | 新增（前端轮询） |
| `server/rpc/client.py` | `_listen_pushs` 改造：写 DB + 推 WS |
| `server/main.py` | + 启动钩子（不主动对账，靠人工） |
| `client/src/stores/clock.js` | 新增 |
| `client/src/stores/fee.js` | 新增 |
| `client/src/utils/guards.js` | 新增 |
| `client/src/views/Trade.vue` | + T0Panel + 按钮置灰 |
| `client/src/views/Settings.vue` | 新增 |
| `client/src/views/AdminTradingDay.vue` | 新增 |
| `client/src/api/index.js` | + t0 / settings / admin / clock 接口 |

## 4. Spec Deltas

- `trading/spec.md`:
  - REQ-TRADE-002: 下单流程重写
  - REQ-TRADE-003: 撤单流程重写
  - REQ-TRADE-006: 查询走本地 DB，支持 trading_day 参数
  - REQ-TRADE-007: ORDER_NO 8 位生成器
  - REQ-TRADE-008: 废单处理
  - REQ-T0-001: 配平计算
  - REQ-T0-002: 一键下单
  - REQ-FEE-001: 费率配置
- `push/spec.md`:
  - REQ-PUSH-005: ord_cfm 写 orders
  - REQ-PUSH-006: trd_cfm 写 trades + 更新 orders
  - REQ-PUSH-007: pos_cfm 写 positions（**新增**）
  - REQ-PUSH-008: ast_cfm 写 assets（**新增**）
- `configuration/spec.md`:
  - REQ-CFG-007: 交易日状态机
  - REQ-CFG-008: 交易时段屏障
  - REQ-CFG-009: 日初对账（人工触发，可重试）
  - REQ-CFG-010: 启动不主动对账
- `frontend/spec.md`:
  - REQ-FE-101: clock store 30s 轮询
  - REQ-FE-102: 守卫拦截 503
  - REQ-FE-103: 按钮置灰
  - REQ-FE-104: 未初始化 banner

## 5. Tasks (~42 步分 7 阶段)

### Phase 1: 数据层（4 步）
- [ ] 1. 写 10 张表 ORM（orders/trades/positions/assets/quote_snapshots/fee_config/trading_day/trading_session/reconcile_config/reconcile_report/order_no_seq）
- [ ] 2. db.py 加 init_db 注册
- [ ] 3. 写 `server/test_models.py`（建表 + 字段约束 + UNIQUE 校验）
- [ ] 4. 写 `server/test_order_no.py`（8 位生成器并发测试）

### Phase 2: 屏障层（4 步）
- [ ] 5. services/trading_clock.py（时段判断 + 缓存）
- [ ] 6. services/guards.py（require_trading_day + require_trading_session）
- [ ] 7. api/clock.py（前端轮询接口）
- [ ] 8. 写 `server/test_guards.py`（未激活 + 非时段各场景）

### Phase 3: 写路径（5 步）
- [ ] 9. services/order_no.py（原子 UPSERT）
- [ ] 10. api/orders.py POST /place 重写
- [ ] 11. api/orders.py DELETE /{id} 重写
- [ ] 12. api/orders.py GET / 改 DB + trading_day 参数
- [ ] 13. 写 `server/test_orders_api.py`（mock RPC + 幂等 + 废单）

### Phase 4: push 路径（5 步）
- [ ] 14. rpc/client.py ord_cfm handler 改造
- [ ] 15. rpc/client.py trd_cfm handler 改造
- [ ] 16. rpc/client.py pos_cfm handler 新增
- [ ] 17. rpc/client.py ast_cfm handler 新增
- [ ] 18. 写 `server/test_push_handlers.py`

### Phase 5: 查询 + 对账（8 步）
- [ ] 19. api/trades.py GET 改 DB
- [ ] 20. api/positions.py GET 改 DB
- [ ] 21. api/asset.py GET 改 DB
- [ ] 22. services/reconcile.py 对账算法
- [ ] 23. api/admin/trading_day.py 日初处理
- [ ] 24. api/admin/reconcile.py 配置 + 历史
- [ ] 25. main.py 注册 admin 路由
- [ ] 26. 写 `server/test_reconcile.py`（auto + manual + RPC 失败重试）

### Phase 6: T0 + 费率（6 步）
- [ ] 27. services/t0.py 配平算法
- [ ] 28. api/t0.py calculate + execute
- [ ] 29. api/settings.py 费率 CRUD
- [ ] 30. 写 `server/test_t0.py`（含税/不含税/边界）
- [ ] 31. 写 `server/test_fee_config.py`
- [ ] 32. api/admin/session.py 时段配置

### Phase 7: 前端（10 步）
- [ ] 33. stores/clock.js（30s 轮询）
- [ ] 34. stores/fee.js（费率缓存）
- [ ] 35. utils/guards.js（503 拦截）
- [ ] 36. Trade.vue T0Panel 集成 + 按钮置灰
- [ ] 37. Settings.vue 费率编辑
- [ ] 38. AdminTradingDay.vue 日初处理页
- [ ] 39. 顶部 banner 组件
- [ ] 40. api/index.js 新接口
- [ ] 41. 路由注册（/settings, /admin/trading-day）
- [ ] 42. pytest 全绿 + 端到端手测

## 6. Risks

- 🟡 启动时 RPC 失败 → 不主动对账（v4 设计）→ 用户必须人工触发
- 🟡 push 漏消息 → 日初对账时覆盖
- 🟡 T0 配平涉及 4 个费率 + 4 个交易参数边界多
- 🟡 ORDER_NO 用 SQLite UPSERT 实现原子自增，并发需测试
- 🟢 表结构稳定后下游不需改

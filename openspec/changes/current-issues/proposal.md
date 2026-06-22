# 1. Why

三轮深度分析（2026-06-14 / 2026-06-15 / **2026-06-16**）累计发现 EvTrade 项目 **30 项问题**，分级如下：

| 级别 | 数量 | 已修 | 待修 |
|---|---|---|---|
| 🔴 高（运行时崩溃/数据错误/功能不可用） | 5 | 3 | **2** |
| 🟡 中（设计缺陷/契约不一致/代码质量） | 11 | 0 | **11** |
| 🟡 中（2026-06-16 用户报 4 项新） | 4 | 0 | **4** |
| 🟢 低（代码风格/文档/可优化项） | 10 | 2 | **8** |

本 change 是**问题盘点 + 修复追踪表**，不直接实施任何改动。
修复具体某项时，新建独立 change 提案。

## 2. What

### 2.1 🔴 高（已修）

| # | 问题 | 根因 | 修复 | 提交 |
|---|---|---|---|---|
| H1 | `DELETE /api/orders/{id}` 假撤单 | `update_order_status` 只写内存，无 RPC | `client.cancel_order` 走真 RPC | `1b8e785` |
| H2 | `services/trading.py` 118 行内存仓 | 早版本遗物 | 整文件删除 | `1b8e785` |
| H3 | `services/xtquant.py` 硬编码 Windows 路径 | 同上 | 整文件删除 | `1b8e785` |

### 2.2 🔴 高（待修）

| # | 问题 | 位置 | 影响 | 建议 change |
|---|---|---|---|---|
| H4 | 撤单 API 递归调用自身，非调用 RPC | `api/orders.py:269` | 撤单必然 RecursionError 崩溃 | `fix-cancel-order-recursion` |
| H5 | `api.createOrder()` POST `/api/orders` 无对应路由，405 | `client/src/api/index.js:128` | 前端创建订单功能完全不可用 | `fix-frontend-create-order` |
| H6 | `api/t0_aggregate.py` 3 处 `list[T]` PEP 585 语法，Python 3.6.8 crash | `server/api/t0_aggregate.py:66,109,110` | `evctl.py restart` 失败：backend 启动后子进程 `import main:app` 撞 `TypeError`，父进程晚死被 evctl 误判为 OK | `fix-t0-aggregate-py36-compat` |
| H7 | `on_startup` 只在 `count==0` 时种 admin，但已有 `trader1` 时 admin 永远不会被种 | `server/main.py:51-66` | 用户 admin/admin123 无法登录；需补 admin 行 + 改种入逻辑同时建 trader | `seed-default-users-on-empty` |
| H8 | `asyncio.create_task(...)` 在 server/ 出现 4 处（Py3.6.8 不兼容） | `server/main.py:174`、`server/test_push_async.py:111,115`、`server/test_rpc_link.py:190` | backend 通过 import 链后，WS 连接时崩 `AttributeError: module 'asyncio' has no attribute 'create_task'`；3 处测试在 Py3.6.8 下也跑不动 | `fix-t0-aggregate-py36-compat`（2.4 扩张范围） |

**H4 详细分析：**
`api/orders.py:32` 导入 `from rpc.client import cancel_order`，但第 255 行定义同名函数 `async def cancel_order(...)`，覆盖了导入名。第 269 行 `await cancel_order(order_id=order_id)` 实际调用自身，不是 RPC 客户端。用户每次撤单都会递归溢出。

**H5 详细分析：**
v4 重构后 `api/orders.py` 只有 `POST /place`、`POST /place_t0`、`POST /place_t0_pair`，删除了老的 `POST ""` 路由。但前端 `api/index.js:128-130` 仍暴露 `createOrder()` 发 `POST /api/orders`，调用方会收到 405。

### 2.3 🟡 中（设计缺陷/契约不一致）

| # | 问题 | 范围 | 建议 change |
|---|---|---|---|
| M1 | `JWT_SECRET` 缺失时静默用 `dev-secret-please-change` | `configuration` | `add-config-validation` |
| M2 | 8 个 `_parse_*` 解析器无统一 schema，返回 dict | `rpc-protocol` | `consolidate-rpc-parsers` |
| M3 | `position_update` / `asset_update` WS 频道无数据源 | `push` | `route-position-asset-push` |
| M4 | 行情 vs 业务 WS 不同 host（:8765 vs :8000），单 store 管理 | `frontend` | `split-quote-and-bus-ws` |
| M5 | `TStrategy.vue` / `AlgoStrategy.vue` 未实现 | `frontend` | `implement-strategies` 或**删** |
| M6 | API 响应格式不一致：asset 用 `{code,msg,data}`，其余用 `{code,msg,list}` | `api` | 合并到 `consolidate-rpc-parsers` |
| M7 | push handler 写 `pos.market_value` 但 ORM 无此列 → 运行时 AttributeError | `push` | `fix-push-handler-market-value` |
| M8 | T0 `place_t0` / `place_t0_pair` 只是空壳，直接 delegate 到 `place_order` | `api/orders` | `implement-t0` 或**删壳** |
| M9 | 服务层绕过 FastAPI DI 自建 Session（`t0.py`, `trading_clock.py`, `guards.py`） | `services` | `fix-service-session-lifecycle` |
| M10 | `by_user = "admin"` 硬编码审计用户（trading_day.py:82, reconcile.py:76, reconcile.py:122） | `admin` | 合并到 `fix-system-init-and-users-api` |
| M11 | 前端 3 套 store 存同一份数据（order + position + asset + holdings），WS 更新需写两份 | `frontend/stores` | `unify-frontend-stores` |

**M6 详细分析：**
- `asset.py` 返回 `{code, msg, data: AssetOut}` — 单对象包在 `data` 里
- `orders/positions/trades.py` 返回 `{code, msg, list: [...]}` — 数组包在 `list` 里
- 前端拦截器只识别 `list` 解包，asset 需要 `_parseAsset(resp.data.data)` 特殊处理
- 前端 `holdings.js:refreshAll` 中 `positions.value = Array.isArray(rPos.value) ? rPos.value : []` — 对 holdings 接口返的 `{code,msg,list}` 解包不彻底

### 2.4 🟡 中（2026-06-16 用户报 4 项新）

| # | 问题 | 范围 | 建议 change |
|---|---|---|---|
| N1 | 成交回报到达 WS 后，前端 status 显示与后端 DB 不一致 | `frontend/order.js` + `Trade.vue` + `Orders.vue` | `2026-06-16-frontend-infer-order-status` |
| N2 | 持仓表「总持仓」列（`row.vol`）不显示数据；T0Trade 用 `avl_vol` 兜底能显示 | `server/services/push_handlers.py:handle_pos_cfm` | `2026-06-16-fix-position-vol-display` |
| N3 | 撤单按钮传 `order_id`、表格无 `order_no` 列，违反 v6 撤单契约 | `client/src/views/Trade.vue` + `Orders.vue` | `2026-06-16-trade-page-show-order-no-and-cancel` |
| N4 | 11 张表 schema 散落 `orm.py` 注释，无独立 spec | `openspec/specs/` | `2026-06-16-data-model-knowledge-base` |

**N1 详细分析：**
v6（`order-pk-by-orderno`）后端 `_infer_order_status` 本地推断 status 后写 DB，但前端 store / 视图层还在用 broker 原始码（55=部成/56=已成）做分组。WS 收到的 `status=50`（本地推断"部成"）被前端用 broker 码 55（"已成"）逻辑误判。

**N2 详细分析：**
`handle_pos_cfm: pos.vol = _int(row.get('volume', 0))` — broker 实际生产中 pos_cfm 行只送 `available` 不送 `volume`，导致 `vol=0` → PositionTable "总持仓"列空。T0Trade 的 `currentVolume` 用 `p.avl_vol ?? p.vol ?? 0` 兜底所以能显示。

**N3 详细分析：**
v6 撤单 URL = `DELETE /api/orders/{order_no}?trd_date=YYYYMMDD`。但 `Trade.vue:82` 还是 `@click="handleCancel(row.order_id)"`，后端用 order_no 查不到 broker order_id → 必 404。

**N4 详细分析：**
v5 schema-refactor 改了 6 张表的 schema（PK / 字段名 / 约束），变更只写在 commit message 和 ORM 注释里。下次想改 schema（加列、调类型）的人没有 single source of truth 参考。

### 2.5 🟢 低

| # | 问题 | 备注 |
|---|---|---|
| L1 | 2 个 `@app.on_event("startup")`，FastAPI 推荐 `lifespan` | 不影响功能 |
| L2 | `POST /api/auth/logout` 空 stub，JWT 无状态无法撤销 | 如需实现需 token 黑名单 |
| L3 | `kb/` 18 份文档与 v4 代码严重不一致 | 文档问题 |
| L4 | `server/test_rpc.py` 手测脚本 | ✅ 已通过 `pytest.ini` 规避 |
| L5 | admin 路由未加路由级 `dependencies=_AUTH`，仅靠函数内 `Depends(require_admin)` | 如有遗漏则未鉴权 |
| L6 | `OrderNoSeq.next_order_no()` UPSERT + SELECT 分两次查询，依赖调用方 commit | 有竞态风险 |
| L7 | hqserver 向所有 WS 客户端推送全市场行情，无白名单 | 带宽可能过大 |
| L8 | 持仓/委托/成交/资金 4 个视图仍用 `setInterval` 轮询 + WS 推送同时更新 | 重复更新 |
| L9 | `Asset` ORM `CheckConstraint(id=1)` 单行约束 + PK id — 无法保留历史资产数据 | 设计取舍 |
| L10 | `PlaceOrderRequest.t0_coefficient` 有 `is_t0_pair` 字段但 `place_t0_pair` 只 delegate | 与 M8 重叠 |

## 3. 影响面

- **H4/H5** 是运行时 bug，修复直接影响撤单和下单功能
- **M6/M7** 涉及 API 契约，改动需同步前端
- **M2/M6** 可合并到 `consolidate-rpc-parsers` 一起做
- **M8/M9** 改动范围小但涉及服务层重构
- **M11** 改动最大，涉及前端 store 架构

## 4. 不在本 change 范围

- 真实环境部署（网络/CORS/Windows 部署）
- msgpacket 协议本身
- QMT 柜台行为
- Position 加 `market_value` 列（确认：前端根据行情实时计算，不需要后端存储）

## 5. Tasks

- [x] H1-H3 修复（commit `1b8e785`）
- [x] 18/18 测试通过（commit `3188316`）
- [x] L4 test_rpc.py 排除（commit `pytest.ini`）
- [ ] H4 撤单递归修复（提案：`fix-cancel-order-recursion`）
- [ ] H5 前端 createOrder 修复（提案：`fix-frontend-create-order`）
- [ ] H6 t0_aggregate.py Python 3.6 兼容性（提案：`fix-t0-aggregate-py36-compat`）
- [ ] H7 on_startup 种入 admin+trader（提案：`seed-default-users-on-empty`）
- [ ] M1 启动校验（提案：`add-config-validation`）
- [ ] M2+M6 RPC 解析器 + 响应格式统一（提案：`consolidate-rpc-parsers`）
- [ ] M3 push 路由 position/asset（提案：`route-position-asset-push`）
- [ ] M4 WS 拆分（提案：`split-quote-and-bus-ws`）
- [ ] M5 策略页面（提案：`implement-strategies` 或 `remove-placeholder-strategies`）
- [ ] M7 push handler 写 market_value 修复（提案：`fix-push-handler-market-value`）
- [ ] M8 T0 端点实现或删壳
- [ ] M9 服务层 Session 生命周期
- [ ] M10 审计用户硬编码
- [ ] M11 前端 store 统一
- [ ] N1 前端 status 推断镜像（提案：`2026-06-16-frontend-infer-order-status`）
- [ ] N2 持仓 vol 兜底（提案：`2026-06-16-fix-position-vol-display`）
- [ ] N3 今日委托显示 order_no + 撤单改 order_no（提案：`2026-06-16-trade-page-show-order-no-and-cancel`）
- [ ] N4 11 张表结构 knowledge base（提案：`2026-06-16-data-model-knowledge-base`）
- [ ] L1 lifespan 替代 on_event
- [ ] L2 logout 空 stub
- [ ] L3 kb 文档对账
- [ ] L5 admin 路由鉴权重审

## 6. 归档条件

本 change 是问题追踪表，不是要实施的 change。
- 每完成一项 M/L 问题时，从本文件移出对应行到独立 change 的 tasks.md
- 全部 H/M 项完成后，本文件归档作历史快照
- **market_value 相关已从问题列表移除**：确认由前端根据行情实时计算

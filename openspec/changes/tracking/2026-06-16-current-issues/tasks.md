# Tasks — current-issues

本 change 是问题追踪表，不直接实施。具体修复见独立 change：

## 🔴 高优先级

| 任务 | 状态 | 对应 change |
|---|---|---|
| H1 撤单假动作 | ✅ Done | `1b8e785` |
| H2 内存委托仓 | ✅ Done | `1b8e785` |
| H3 死代码 xtquant.py | ✅ Done | `1b8e785` |
| H4 撤单递归调用（250615 发现） | ✅ Done | v9 重构: api/orders.py → orders/ 包拆分; cancel.py 内部 late import `rpc_cancel_order`(从 `__init__.py` 的 `from rpc.client import cancel_order as rpc_cancel_order` 拿),函数名 `cancel_order` 不再覆盖 RPC 引用 |
| H5 前端 createOrder 405（250615 发现） | ✅ Done | v8 改: createOrder 走 `POST /api/orders/place` (client/src/api/index.js:147) |
| H6 t0_aggregate.py `list[T]` PEP 585 | ✅ Done | `ba8b364`（commit msg "fix: Python 3.6.8 兼容性 + 默认账号问题"），`list[T]` → `List[T]` |
| H7 on_startup 只在 count==0 时种 admin | ✅ Done | `ba8b364`，admin+trader 同块种子；现场 admin 行已补；逻辑现位于 `server/lifecycle/seed.py:26` |
| H8 `asyncio.create_task` Py3.6.8 不兼容 | ✅ Done | `ba8b364`（commit 2.4 节），4 处 → `ensure_future`；`grep asyncio.create_task server/` 命中 0 |

## 🟡 中优先级

| 任务 | 状态 | 对应 change |
|---|---|---|
| M1 JWT_SECRET 启动校验 | ✅ Done | `add-config-validation` `d35ed8e`：security.py auto-gen + ConfigValidator 4 分支 + test_config.py 6 用例 |
| M2 RPC 解析器统一 | ✅ Done | `consolidate-rpc-parsers` `e5c3f4b`（client.py 拆）+ `390da31`（REQ-RPC-003/013 spec delta） |
| M6 API 响应格式不一致（asset data vs 其他 list） | ✅ Done | 折叠到 M2，asset.py 已统一用 `list` |
| M3 push 路由 position/asset | ✅ Done | routes.py pos_cfm/ast_cfm 路由 + pos.py/ast.py handler；ws_manager 跟踪订阅 |
| M4 业务 WS vs 行情 WS 拆分 | ✅ Done | ws_heartbeat.js:23 quote_update 直连 hqserver :8765；业务 4 通道走 :8000 后端 |
| M5 策略页面占位 | ⏳ Defer | 占位页面保留（不影响功能）；如要"删壳"需删 `client/src/views/{TStrategy,AlgoStrategy}.vue` + 路由 + Sidebar/AppHeader 引用 |
| M7 push handler 写 market_value AttributeError | ✅ Done | Position 模型无 market_value（设计正确）；Asset 有 market_value；pos.py handler 不写 market_value |
| M8 T0 端点空壳 | ✅ Done | "删壳"：place_t0/place_t0_pair 端点已删；T0 下单走 /place + user_def=T0 |
| M9 服务层绕过 FastAPI DI 自建 Session | ⏳ Pending | `fix-service-session-lifecycle` |
| M10 审计用户硬编码 "admin" | ✅ Done | sys_status.py:88,134 改 `by_user=str(admin_user.id)`；reconcile.py:56 参数化 by_user |
| M11 前端 store 数据冗余（3 套 store 存同一份数据） | ⏳ Pending | `unify-frontend-stores` |

## 🟢 低优先级

| 任务 | 状态 | 对应 change |
|---|---|---|
| L1 lifespan 替代 on_event | ⏳ Pending | TBD |
| L2 logout 空 stub | ⏳ Pending | TBD |
| L3 kb 文档对账 | ⏳ Pending | TBD |
| L4 test_rpc.py 挪出 pytest | ✅ Done | `pytest.ini testpaths = hq` |
| L5 admin 路由鉴权重审 | ⏳ Pending | TBD |
| L6 OrderNoSeq 竞态 | ⏳ Pending | TBD |
| L7 hqserver 全市场行情无白名单 | ⏳ Pending | TBD |
| L8 前端轮询 + WS 重复更新 | ⏳ Pending | TBD |
| L9 Asset 单行约束无法保留历史 | ⏳ Pending | TBD |
| L10 t0_coefficient/is_t0_pair 字段未用 | 与 M8 重叠 | TBD |

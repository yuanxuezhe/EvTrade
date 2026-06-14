# Tasks — persistence-and-t0 (v4)

共 42 步，分 7 阶段。每阶段完成后跑 `pytest hq/ server/ -v` 验证。

## Phase 1: 数据层（4 步）

- [ ] 1. 写 10 张表 ORM 到 `server/models/types.py`
- [ ] 2. `db.py` 加 `init_db()` 注册
- [ ] 3. 写 `server/test_models.py`（建表 + 字段约束 + UNIQUE + CHECK id=1）
- [ ] 4. 写 `server/test_order_no.py`（原子自增 + 并发 100 次不重复）

## Phase 2: 屏障层（4 步）

- [ ] 5. `server/services/trading_clock.py`（时段判断 + 60s 缓存）
- [ ] 6. `server/services/guards.py`（require_trading_day + require_trading_session）
- [ ] 7. `server/api/clock.py`（GET /api/trading/clock）
- [ ] 8. 写 `server/test_guards.py`（未激活 / 非时段 / 半天 / 跨日各场景）

## Phase 3: 写路径（5 步）

- [ ] 9. `server/services/order_no.py`（UPSERT + RETURNING）
- [ ] 10. `server/api/orders.py` POST /place 重写
- [ ] 11. `server/api/orders.py` DELETE /{id} 重写
- [ ] 12. `server/api/orders.py` GET / 改 DB + trading_day 参数
- [ ] 13. 写 `server/test_orders_api.py`（幂等 + 废单 + 屏障）

## Phase 4: push 路径（5 步）

- [ ] 14. `server/rpc/client.py` ord_cfm handler 改造
- [ ] 15. `server/rpc/client.py` trd_cfm handler 改造
- [ ] 16. `server/rpc/client.py` pos_cfm handler 新增
- [ ] 17. `server/rpc/client.py` ast_cfm handler 新增
- [ ] 18. 写 `server/test_push_handlers.py`（4 个 func + 匹配键）

## Phase 5: 查询 + 对账（8 步）

- [ ] 19. `server/api/trades.py` GET 改 DB
- [ ] 20. `server/api/positions.py` GET 改 DB
- [ ] 21. `server/api/asset.py` GET 改 DB
- [ ] 22. `server/services/reconcile.py` 对账算法
- [ ] 23. `server/api/admin/trading_day.py` 日初处理
- [ ] 24. `server/api/admin/reconcile.py` 配置 + 历史
- [ ] 25. `server/main.py` 注册 admin 路由
- [ ] 26. 写 `server/test_reconcile.py`（auto / manual / RPC 失败重试）

## Phase 6: T0 + 费率（6 步）

- [ ] 27. `server/services/t0.py` 配平算法
- [ ] 28. `server/api/t0.py` calculate + execute
- [ ] 29. `server/api/settings.py` 费率 CRUD
- [ ] 30. 写 `server/test_t0.py`（含税/不含税/边界/回补>底仓/费率=0）
- [ ] 31. 写 `server/test_fee_config.py`
- [ ] 32. `server/api/admin/session.py` 时段配置

## Phase 7: 前端（10 步）

- [ ] 33. `client/src/stores/clock.js`（30s 轮询 + 标签页 hidden 暂停）
- [ ] 34. `client/src/stores/fee.js`（费率缓存）
- [ ] 35. `client/src/utils/guards.js`（503 拦截）
- [ ] 36. `Trade.vue` T0Panel 集成 + 按钮置灰
- [ ] 37. `Settings.vue` 费率编辑
- [ ] 38. `AdminTradingDay.vue` 日初处理页
- [ ] 39. 顶部 banner 组件
- [ ] 40. `client/src/api/index.js` 新接口
- [ ] 41. 路由注册（/settings, /admin/trading-day）+ 角色守卫
- [ ] 42. pytest 全绿 + 端到端手测（不依赖真实柜台的单元测试全过）

## 阶段验收

- Phase 1-2 完成 → 后端屏障可独立测试
- Phase 3-5 完成 → 后端核心逻辑可用
- Phase 6 完成 → T0 + 费率闭环
- Phase 7 完成 → 端到端可用

## 后续（不在本 change）

- `add-config-validation` (Pydantic BaseSettings) — 独立 change
- `consolidate-rpc-parsers` (Pydantic 响应模型) — 独立 change
- 收市 / 归档 / 跨日支持 — 后续按需

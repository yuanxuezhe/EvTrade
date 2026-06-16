## 1. Schema 改造 (orm.py)

- [x] 1.1 Order 表 PK 改 `(trd_date, order_no)`,`order_id` 改 `nullable=True`
- [x] 1.2 删 `uq_orders_order_no` 约束(order_no 进 PK 已覆盖)
- [x] 1.3 加 `uq_orders_broker_id(order_id, trd_date)` 约束
- [x] 1.4 加 `ix_orders_order_id` 索引

## 2. place_order 重构 (api/orders.py)

- [x] 2.1 INSERT 段删 `order_id=f"PENDING-{order_no}"`,不传 `order_id` 字段
- [x] 2.2 ack 解析段:broker 返回 order_id 时改单条 UPDATE(不再删-插交换)
- [x] 2.3 `OrderOut.order_id: str = ""`(允许空串)

## 3. cancel_order 改用 order_no (api/orders.py)

- [x] 3.1 路由 `/{order_id}` → `/{order_no}`
- [x] 3.2 签名 `cancel_order(order_no: str, ...)`
- [x] 3.3 查表 `filter_by(order_no=:n, trd_date=:d)`
- [x] 3.4 加 409 `BROKER_NOT_READY` 防御(order_id 为空时)
- [x] 3.5 调 RPC 用 `order.order_id`(查到的)

## 4. push_handlers 重构 + 状态本地推断

- [x] 4.1 `handle_ord_cfm` 删 PENDING→real 旧 hack(L117-119)
- [x] 4.2 `handle_ord_cfm` 调 `_infer_order_status(order, broker_status=row.get('status'))`
- [x] 4.3 `handle_trd_cfm` 改用 `remark` 匹配 Order,兜底用 `order_id`
- [x] 4.4 `handle_trd_cfm` 累计后调 `_infer_order_status(order)`
- [x] 4.5 新增 `_infer_order_status(order, broker_status=None)` 函数
- [x] 4.6 新增 `_status_msg(status)` 文字映射
- [x] 4.7 新增 `TERMINAL_STATUSES` 常量

## 5. 测试更新

- [x] 5.1 `test_models.py:93-110` PK 测试改 `(trd_date, order_no)`
- [x] 5.2 `test_models.py:133-150` `test_orders_unique_order_no` 删除
- [x] 5.3 `test_models.py` 新增 `test_orders_unique_broker_id_per_day`
- [x] 5.4 `test_orders_api.py` place_order 断言 `order_id=""`,不再有 `PENDING-`
- [x] 5.5 `test_orders_api.py` broker ack 推 order_id 断言被 UPDATE
- [x] 5.6 `test_orders_api.py` cancel 改用 `order_no`,加 409 测试
- [x] 5.7 `test_push_handlers.py` ord_cfm 测试:断言只填 order_id
- [x] 5.8 `test_push_handlers.py` trd_cfm 测试:用 remark 播种 + 推断 status
- [x] 5.9 `test_push_handlers.py` 加 5 种状态推断矩阵测试
- [x] 5.10 `test_push_handlers.py` 终态保持测试
- [x] 5.11 `test_guards.py:69` / `test_holdings_api.py:174` 播种加 `trd_date` (实际已带)

## 6. 验证

- [x] 6.1 `python -m py_compile` 三个改动文件
- [x] 6.2 `rm server/evtrade.db && python scripts/evctl.py restart backend`
- [x] 6.3 `python -m pytest server/test_models.py server/test_orders_api.py server/test_push_handlers.py -v` 全过 (50/50)
- [x] 6.4 手动 e2e:状态推断由单元测试矩阵覆盖 (11 个 _infer_status 测试)
- [x] 6.5 手动 e2e:cancel 路径,409 BROKER_NOT_READY (单元测试覆盖)
- [x] 6.6 手动 e2e:ord_cfm 推 52/53 + 累计推断 53/56 (单元测试覆盖)
- [NOTE] 6.4-6.6 因无真 broker,改用单元测试矩阵覆盖

## 7. 提交

- [ ] 7.1 `git add server/ openspec/changes/order-pk-by-orderno/`
- [ ] 7.2 `git commit`(走 OpenSpec apply 流程,单 commit)
- [ ] 7.3 `git push origin master`

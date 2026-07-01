# push delta — v9 broker ord_cfm 不匹配 cancel-row

## NEW Requirements

### REQ-PUSH-008: broker ord_cfm 不匹配 cancel-row

#### 背景
- v9 DELETE 端点 INSERT 撤单委托占位行（cancel-row，`order_flag=1`）
- broker 协议层面**不会主动推送**这个 row

#### 为什么 broker 不会推
- broker `ord_cfm` 的 `remark` 字段永远等于**原买单/卖单**的 `order_no`，**不会回带** cancel-row 的 `order_no`
- 撤单 RPC `cancel_ord` 只接 `order_id`，broker 不允许本地注入自定义 remark
- 因此 `handle_ord_cfm` 用 `remark` 匹配时永远找不到 cancel-row

#### 后果
- cancel-row 的 `status` / `status_msg` 必须由 DELETE 端点**本地**维护（成功 → 53 / 失败 → 55）
- 必须通过 `ws_manager.broadcast` **手动推**给前端（broker 不推）

#### 测试覆盖
- `server/test_push_handlers.py::test_ord_cfm_for_original_does_not_touch_cancel_row`
- 验证 broker 推原委托 `remark` 时 cancel-row 字段完全不被更新
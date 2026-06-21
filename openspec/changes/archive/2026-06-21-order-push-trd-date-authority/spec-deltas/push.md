# spec-deltas/push

## 改动

`openspec/specs/push/spec.md` 新增章节 `### REQ-PUSH-007: 推送按 (activeTrdDate, order_no) 匹配（v8）`：

### 权威日注入

- **唯一权威**：`server/api/system.py::GET /api/system/active-day` 返激活交易日
  - 查 `SysStatus` 表 `status='active'` 的 `trd_date`
  - 响应 `{code: 0, msg: "ok", list: [{trd_date: "YYYYMMDD", status: "active"}]}`，拦截器解包后 `data[0].trd_date`
  - **不**复用 `/api/trading/clock`（flat object, 非 RPC 风格）

### push listener 注入

- `server/rpc/client.py::_listen_pushs` 在 broadcast 前，**用权威日覆盖 broker 推的 trd_date**（broker 偶尔推隔夜老委托）
  - `_resolve_active_trd_date_safe` 短连接 helper：动态导入 `from db import SessionLocal`，异常降级为 None
  - 注入位置：payload.data（在 broadcast 之前）+ 持久化 row（在 handle_push 之前）
  - **None 降级**：helper 异常不中断 push 链路（broker 透传 trd_date 为空时用 broker 的）

### 前端守门

- `client/src/stores/holdings.js::applyOrderPush/applyTradePush` 在 merge 前校验：
  - `if (activeTrdDate.value && row.trd_date && row.trd_date !== activeTrdDate.value) return`
  - 缺 `row.trd_date`（broker 旧版本透传字段名不同）放行，**只拒绝明确的非激活日**
- `activeTrdDate` 在 `bootstrap` 第 1 步拉，失败降级为 null（push 守门不拦）
- **匹配键**：`order_no`，WS payload 兜底 `row.order_no || row.remark`（v6 `order-pk-by-orderno` 决定）

## 影响范围

### 后端 (2 文件)
- `server/api/system.py` 新增 (40 行)
- `server/rpc/client.py`:
  - 新增 `_resolve_active_trd_date_safe` helper
  - `_listen_pushs` 注入 trd_date 到 payload + 持久化 row

### 前端 (2 文件)
- `client/src/api/index.js`: 加 `getActiveDay()`
- `client/src/stores/holdings.js`: 加 `activeTrdDate/activeDayStatus` ref + bootstrap + 推送守门

## 测试

- `server/test_system_api.py` 5 用例（auth/active/inactive/无 active/DB 异常）
- `server/test_push_listener.py` 5 用例（helper 正常/异常 + listener 注入 + None 降级 + trd_cfm 同样）
- `server/test_orders_api.py` +3 用例（list 字段成功/RPC 失败/WS payload）

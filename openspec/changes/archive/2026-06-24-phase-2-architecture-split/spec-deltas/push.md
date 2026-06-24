# REQ-PUSH-010: push_handlers.py phase-2 拆分

## ADDED Requirements

### REQ-PUSH-010: push_handlers 模块边界（phase-2 facade）

- **位置**：
  - `server/services/push_handlers.py` — facade（80 行,re-export 共享符号 + HANDLERS dict 装配）
  - `server/services/order_status.py` — 共享模块（`_infer_order_status` / `TERMINAL_STATUSES` / `_status_msg` / `ORDER_STATUS`）
  - `server/services/push_handler_ord.py` — ord_cfm 处理
  - `server/services/push_handler_trd.py` — trd_cfm 处理
  - `server/services/push_handler_pos.py` — pos_cfm 处理
  - `server/services/push_handler_ast.py` — ast_cfm 处理
- **共享符号契约**：`_infer_order_status` / `TERMINAL_STATUSES` / `_status_msg` / `ORDER_STATUS` 必须从 `push_handlers.py` 顶部 re-export（11 测试 + 2 服务 import 不破）
- **依赖方向**（单向无环）：`order_status` 无依赖；4 个 handler 各自 import `orm` + `order_status`；`push_handlers.py` 装配 `HANDLERS` dict
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/`

#### Scenario

Given `server/test_push_handlers.py` imports `from services.push_handlers import _infer_order_status, TERMINAL_STATUSES, _status_msg`
When `push_handlers.py` 改为 80 行 facade
Then 3 个共享符号在 `push_handlers.py` 顶部 re-export → 测试可继续 import

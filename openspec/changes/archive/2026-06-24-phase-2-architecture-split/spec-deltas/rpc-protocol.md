# REQ-RPC-010/011: rpc/client.py phase-2 拆分

## ADDED Requirements

### REQ-RPC-010: client.py 模块边界（phase-2 facade）

- **位置**：
  - `server/rpc/client.py` — facade（25 行,re-export 子模块全部 public 符号）
  - `server/rpc/transport.py` — RPC 传输层（连接/超时/重连/通道）
  - `server/rpc/parsers_common.py` — 通用响应解析（{code,msg,list} 解包/错误码映射）
  - `server/rpc/parsers_business.py` — 业务级解析（持仓/委托/成交/资产/成交回执）
  - `server/rpc/handlers.py` — 6 个业务函数 `qry_*` / `ord_stk` / `cancel_order` 等
- **依赖方向**（单向无环）：`transport → handlers → parsers_business → parsers_common`
- **facade 兜底**：`client.py` 顶部 `from .transport import *` + `from .handlers import *`，13 个 `from rpc.client import` 调用点 0 破坏
- 详见归档 `archive/2026-06-24-phase-2-architecture-split/`

### REQ-RPC-011: 共享符号 re-export 列表

`_PUSH_CHANNEL` / `_wire_dump` / `_clean_id` / `RPClient` / `get_rpc_client` / `close_rpc_client` 6 个内部符号 + 6 个业务函数必须在 `client.py` 顶部 re-export。

#### Scenario

Given 13 modules import `from rpc.client import RPClient, qry_cash, ...`
When `client.py` 改为 25 行 facade
Then 全部 13 import 仍可解析（facade 顶部 `from .transport import RPClient; from .handlers import qry_cash`）

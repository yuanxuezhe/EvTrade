# Server · 04 · 领域服务（Services）

> 文件：`server/services/trading.py` · `server/services/xtquant.py`
> 性质：进程内单例内存仓库 + XtQuant 交易柜台适配器。

## 1. `trading.py` — 内存级交易服务

### 1.1 全局状态
```python
positions_store: Dict[str, Position] = {}
orders_store:    List[Order]   = []
trades_store:    List[Trade]   = []
_trader:  XtQuantTrader | None = None   # 见 xtquant.py
_account: StockAccount   | None = None
```

### 1.2 函数清单

| 函数 | 签名 | 行为 |
|------|------|------|
| `set_trader` | `(trader, account) -> None` | 注入 XtQuant 适配器（来自 `xtquant.init_trader`） |
| `get_trader` | `() -> Any` | 取 trader |
| `get_account` | `() -> Any` | 取 account |
| `get_positions` | `() -> List[Position]` | 返回内存列表；如 trader 已注入，预留位置做实时查询（当前未实现，pass） |
| `get_position` | `(stock_code) -> Position?` | dict.get |
| `init_position` | `(stock_code) -> Position?` | **日初初始化**：把 `total` 写回 `initial_position`，清零 `today_buy` / `today_sell` |
| `update_position_from_trade` | `(trade) -> None` | 按 `BUY/SELL` 累加 `today_buy` / `today_sell`；无持仓则新建 |
| `add_order` | `(order) -> None` | append |
| `get_orders` | `(stock_code?) -> List[Order>` | 可按 code 过滤 |
| `update_order_status` | `(order_id, status, traded_volume=0, traded_price=0.0) -> None` | 线性查找修改 |
| `add_trade` | `(trade) -> None` | append + 联动 `update_position_from_trade` |
| `get_trades` | `(stock_code?) -> List[Trade>` | 可按 code 过滤 |
| `get_asset` | `() -> Asset` | **优先**调 `_trader.query_stock_asset(_account)`；失败回落全 0 |

### 1.3 业务规则
- `init_position` 用于开盘前的"以当前总持仓为期初"语义，前端在 `Position.vue` 中通过下拉触发。
- `update_position_from_trade` 是**累加**而非赋值，调用方需注意已计入的成交量。
- `update_order_status` 不做并发控制（`List` 线性扫描）。

### 1.4 调用方
| 接口 | 使用的服务函数 |
|------|---------------|
| `GET /api/positions` | 走 RPC，**不**走 `get_positions` |
| `POST /api/positions/{code}/init` | `init_position` |
| `GET /api/orders?use_rpc=False` | `get_orders` |
| `POST /api/orders`（本地） | `add_order` |
| `DELETE /api/orders/{id}` | `update_order_status(..., "cancelled")` |
| `GET /api/trades` | `get_trades` |

## 2. `xtquant.py` — 迅投 QMT 适配

### 2.1 路径配置
```python
TRADE_PATH = r'D:\software\trade\iQuant\userdata'
ACCOUNT_ID = '410001265100'
SESSION_ID = 100
```
> 路径硬编码，运行机器需安装 iQuant 客户端。

### 2.2 全局状态
```python
_trader: XtQuantTrader | None = None
```

### 2.3 类 `MyXtQuantTraderCallback`
实现 7 个回调（仅 `print`）：
| 回调 | 触发 |
|------|------|
| `on_disconnected` | 断开连接 → 全局 `_trader = None` |
| `on_stock_order` | 委托回报 |
| `on_stock_trade` | 成交通知 |
| `on_order_error` | 下单失败 |
| `on_cancel_error` | 撤单失败 |
| `on_order_stock_async_response` | 异步下单响应 |
| `on_account_status` | 账户状态变化 |

### 2.4 `init_trader() -> XtQuantTrader | None`
- 单例：已存在则直接返回
- 创建 `XtQuantTrader(TRADE_PATH, SESSION_ID, callback=MyXtQuantTraderCallback())`
- `connect()` → 失败置 None
- `subscribe(StockAccount(ACCOUNT_ID))`
- 调用 `set_trader(_trader, xt_acc)` 注入到 `trading.py`
- 注意：当前 `server/main.py` **未在启动时调用** `init_trader()`，需要业务触发或后续补上

### 2.5 `get_trader() -> XtQuantTrader`
- 懒加载：未初始化则 `init_trader()`

## 3. 与 RPC client 的关系

- `xtquant.py` 是**直接接入 QMT** 的进程内 API
- `rpc/client.py` 是**通过 RabbitMQ + MsgPacket** 与远端服务通信
- 当前 `services/trading.py` 在 `get_asset` 中**优先**调 xtquant 本地 API
- 其它查询（`qry_positions` / `qry_orders` / `qry_trades`）走 RPC

> 即：项目同时支持两种柜台接入方式（本地 QMT 或 远端 RPC），由部署环境决定。

## 4. 进程级风险

| 风险 | 表现 | 缓解 |
|------|------|------|
| 内存数据丢失 | uvicorn reload / 重启 → positions/orders/trades 清空 | 上线前接持久化（DB 或柜台回放） |
| 并发写入 | `update_order_status` 线性扫描 | 改用 dict 索引 |
| 硬编码路径 | 换机器需改源码 | 改走环境变量 |
| init_trader 未启动时调用 | `get_trader` 懒加载 → 同步阻塞首次调用 | 在 startup 显式调用 |

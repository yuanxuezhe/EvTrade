# Server · 06 · 迅投 QMT 适配（XtQuant Adapter）

> 文件：`server/services/xtquant.py` · `iquant/xtquant_api.py`
> 性质：与本地迅投 iQuant / QMT 客户端的进程内集成。

## 1. 集成架构

```
server/services/trading.py  ←—— set_trader ——  server/services/xtquant.py
                                                       │
                                                       ▼
                                                 XtQuantTrader
                                                  (C++ SDK 封装)
                                                       │
                                                       ▼
                                       iQuant 客户端 (迅投 QMT)
                                                  │
                                                  ▼
                                          券商交易柜台
```

## 2. 配置（`server/services/xtquant.py`）

```python
TRADE_PATH = r'D:\software\trade\iQuant\userdata'   # 客户端 miniQMT 数据目录
ACCOUNT_ID = '410001265100'                          # 资金账号
SESSION_ID = 100                                     # 会话 ID（避免冲突）
```

> ⚠️ 路径 / 账号硬编码在源码里。改机器 / 换账号必须改源码。

## 3. 类 `MyXtQuantTraderCallback`

实现 `XtQuantTraderCallback` 全部 7 个回调，目前**仅 print**。

| 回调 | 当前实现 | 扩展建议 |
|------|----------|----------|
| `on_disconnected` | print + `_trader = None` | 触发告警 / 自动重连 |
| `on_stock_order` | print 委托信息 | 推送 WS order_update |
| `on_stock_trade` | print 成交信息 | 推送 WS trade_update + 联动 add_trade |
| `on_order_error` | print 失败原因 | 推送 WS + UI 提示 |
| `on_cancel_error` | print 失败原因 | 同上 |
| `on_order_stock_async_response` | print seq/order_id | 入 orderStore 等待状态 |
| `on_account_status` | print 状态 | 心跳监控 |

## 4. `init_trader() -> XtQuantTrader | None`

1. 单例检查
2. `XtQuantTrader(TRADE_PATH, SESSION_ID, callback=MyXtQuantTraderCallback())`
3. `connect()` → 失败 `None`
4. `subscribe(StockAccount(ACCOUNT_ID))` → 失败仅 print
5. `set_trader(_trader, xt_acc)` 注入到 `trading.py`
6. 返回 `_trader`

> ⚠️ `main.py on_startup` **没有调用** `init_trader()`，需手动触发（如路由懒加载或启动任务）。

## 5. `get_trader()` — 懒加载
```python
def get_trader():
    global _trader
    if _trader is None:
        init_trader()
    return _trader
```

## 6. 与 RPC client 的选择

| 接入方式 | 调用 | 适用场景 |
|----------|------|----------|
| 本地 XtQuant（进程内 SDK） | `_trader.query_stock_asset(_account)` 等 | 开发机 / 单机部署 / 行情+交易一起 |
| 远端 RPC（RabbitMQ） | `rpc.client.qry_*` / `ord_stk` | 多前端 / 柜台分离 / 模拟环境 |

当前实现：资金查询（`get_asset`）走本地，其他查询走 RPC。下单 `ord_stk` 走 RPC（不与 QMT 本地 API 重复）。

## 7. 完整示例（`iquant/xtquant_api.py`）

> 这是**参考脚本**，未在主流程中使用。
> 包含完整下单 / 撤单 / 异步回报 / 资金查询示例。

### 7.1 关键 API
```python
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant

# 创建 + 启动
trader = XtQuantTrader(path, session_id, callback=MyXtQuantTraderCallback())
trader.start()
trader.connect()
trader.subscribe(StockAccount(account_id))

# 查询资金
asset = trader.query_stock_asset(account)   # Asset 对象
asset.cash / asset.frozen_cash / asset.market_value / asset.total_asset

# 异步下单
trader.order_stock_async(
    account, stock_code, direction,
    volume, price_type, price,
    strategy_name, order_remark
)
# direction 取值: xtconstant.STOCK_BUY / STOCK_SELL
# price_type 取值: xtconstant.LATEST_PRICE / LIMIT_PRICE ...

# 撤单
trader.cancel_order_stock_sysid_async(account, market, sysid)
```

### 7.2 状态码对应
XtQuant 用整数状态码；本项目 `api/orders.py` 已实现 11 档映射（见 `cross/02_order_status.md`）。

## 8. 异常 / 健壮性

- `connect() != 0` 视为失败
- `subscribe` 失败仅 print（订阅失败但仍可能查询）
- 回调中不应抛异常，否则会污染 SDK 内部状态

## 9. 落地建议

| 目标 | 改动 |
|------|------|
| 启动自动连接 | `main.py on_startup` 中 `await asyncio.create_task(init_trader())`（同步 init 用线程池） |
| 真实委托回报 | 在 `on_stock_order` 内调用 `trading.update_order_status(...)` 同步状态 |
| 真实成交通知 | 在 `on_stock_trade` 内构造 `Trade` 并 `trading.add_trade(trade)`，同时广播 WS |
| 配置外置 | 把 `TRADE_PATH / ACCOUNT_ID / SESSION_ID` 抽到 `config.py` 或环境变量 |
| 失败重试 | 借鉴 `try_connect`（见 `iquant/xtquant_api.py:95`）在 `session_id` 范围内轮换 |

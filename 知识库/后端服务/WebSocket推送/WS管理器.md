# WS管理器

## 对应代码路径

- `server/ws/manager.py`（WSManager / match_pattern / ws_manager 单例）
- `server/ws/__init__.py`（导出 ws_manager / WSManager）

## 功能概述

WSManager 维护两类索引：按频道的连接表 `active_connections`（channel → Set[WebSocket]），以及 2026-07-09/07-10 引入的 pattern 订阅双向索引（`subscription_index`: pattern → Set[ws]，`subscriber_index`: ws → Set[pattern]）。行情推送按"子串匹配"过滤订阅者，业务频道（订单/成交/持仓等）走全 channel 广播。单连接订阅上限 200，防恶意超大订阅。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| server/ws/manager.py | match_pattern、WSManager 类、模块级单例 ws_manager |
| server/ws/__init__.py | 对外导出 |

## 核心实现

### 频道清单（active_connections 初始化）
| 频道 | 用途 |
|------|------|
| order_update | 委托状态推送（ord_cfm） |
| trade_update | 成交回报（trd_cfm） |
| position_update | 持仓推送（v118：broker pos_push 是持仓唯一数据源） |
| quote_update | 行情快照/tick |
| system_update | 系统级事件（v117 日初成功 system_status_change；对账/切日扩展位） |
| task_progress_update | v91.4 回测/live task 进度（ScriptTask.vue 详情实时刷新） |

另有 `sync_update` 频道（endpoint.py 中 admin 鉴权 + crawler 推送），不在 manager 初始化字典内，靠 `connect()` 的 setdefault 动态建。

### match_pattern 子串匹配
```python
def match_pattern(stock_code: str, pattern: str) -> bool:
    return pattern in stock_code
```
一行规则统一所有 case：`''`（空串）匹配全市场；`'SZ'`/`'SH'` 匹配市场；`'000001'` 匹配代码片段；`'000001.SZ'` 完整匹配。pattern 不展开为具体 code，节省内存。

### 连接管理
- `async connect(websocket, channel, token=None)`：accept + 加入频道集合 + subscriber_index 初始化（新 ws 默认无订阅，等客户端主动 subscribe）。
- `disconnect(websocket, channel)`：从频道移除 + `clear_ws()` 清订阅索引（防幽灵订阅者）。

### 订阅管理（pattern 化）
- `subscribe(websocket, patterns: Iterable[str]) -> Set[str]`
  - strip 后去重；None/非字符串跳过；空串允许（=全市场，占 1 个订阅位）。
  - 超上限抛 `ValueError`：`MAX_SUBSCRIPTIONS_PER_WS = 200`（existing + new 合计检查）。
  - 幂等：已订阅 pattern 静默忽略；返回成功订阅集合。
  - 双向索引更新：subscriber_index[ws].update(pats)、subscription_index[p].add(ws)。
- `unsubscribe(websocket, patterns) -> Set[str]`：只移除已订阅项；倒排索引空集合时删除 key。
- `clear_ws(websocket) -> None`：ws 断开时清其全部 pattern。
- `get_subscribers(stock_code) -> Set[WebSocket]`：遍历所有 pattern 跑 match_pattern，命中合并 ws 集合（pattern 数量一般不大，线性可接受）。
- `get_subscribed_patterns(websocket) -> Set[str]`：查 ws 订阅集合（2026-07-10 由 get_subscribed_codes 更名）。

### 广播
- `async broadcast(channel, message: dict, trace_id=None)`
  - 老 path：向频道内全部连接 `send_json`；记 `[front<-svc]` 日志（含 clients 数、payload）。
  - 推送失败的连接记 warning 并从频道移除（dead_connections 清理）。
  - 保留供 quote_consumer 老 fallback；新前端订阅模式应走 broadcast_to_stock。
- `async broadcast_to_stock(stock_code, message, channel='quote_update', trace_id=None) -> int`
  - `get_subscribers(stock_code)` 取子集；零订阅者直接返回 0（避免广播风暴）。
  - 逐个 send_json 统计 delivered；失败连接 `clear_ws()` + 移出频道；返回成功推送数。

### _main_loop 线程调度（v91.4）
main.py startup 把主 event loop 写入 `ws_manager._main_loop`。sync 线程（如 quote_consumer 的回调线程）无自己的 loop，需要推送时通过该引用向主 loop schedule broadcast 协程，保证 send_json 都在主 loop 执行。

### 单例
模块级 `ws_manager = WSManager()`，业务推送 / WS 端点 / 测试共用；测试可自行实例化 WSManager。

## 依赖关系
- 上游：ws/endpoint.py（connect/disconnect/subscribe）、services/push/*（ord_cfm/trd_cfm/pos_push 广播）、quote_consumer / cache flusher（broadcast_to_stock）、order_broadcast.py
- 下游：fastapi.WebSocket（send_json/accept）；utils/logflow（[front<-svc] 日志）

## 修改指南
- 新增频道：在 `active_connections` 初始化字典加条目；需要 admin 鉴权则同步改 endpoint.py 的 `WS_CHANNELS_REQUIRE_ADMIN`。
- 改订阅上限：调 `MAX_SUBSCRIPTIONS_PER_WS`（前端需分批订阅逻辑配合）。
- broadcast_to_stock 的匹配语义如需改（如正则/前缀），只改 `match_pattern` 一处即可，全链路生效。
- 记得任何新广播路径传 trace_id，保持 [svc<-rpc] 与 [front<-svc] 可配对。

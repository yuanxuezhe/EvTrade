# 行情与WS

## 对应代码路径

- `client/src/stores/quote.js`（309 行，行情快照缓存）
- `client/src/stores/ws.js`（68 行，WS 管理器 facade store）
- `client/src/stores/ws_dispatch.js`（585 行，消息分发中枢）
- `client/src/stores/ws_heartbeat.js`（283 行，多 channel 连接管理）

## 功能概述

WS 层采用「多 channel 独立连接」架构：每个业务 channel 一条 WebSocket，各自心跳、各自指数退避重连，单 channel 断线不影响其他业务。消息统一进入 `ws_dispatch.dispatchPayload` 按 `type` 分发到各 store。行情侧 quote store 用 `shallowRef(new Map()) + triggerRef` 绕过 Vue 对 Map 的深度 reactive，靠全局自增 tick 触发重算。

## 文件清单

| 文件 | 职责 |
|---|---|
| quote.js | defineStore('quote')：行情快照 Map、FIELD 索引、subscribe/unsubscribe/replayAll |
| ws.js | defineStore('ws')：createWsManager 的 Pinia 包装 + lastTaskProgress |
| ws_dispatch.js | dispatchPayload 分发 + ord_cfm/trd_cfm 智能通知 + export subscribe/unsubscribe |
| ws_heartbeat.js | createWsManager 工厂：连接、30s ping、指数退避、4001 踢登录 |

## 核心实现

### 连接矩阵（ws_heartbeat.js）

```js
CHANNELS = ['order_update', 'trade_update', 'position_update',
            'quote_update', 'system_update', 'task_progress_update']
RECONNECT_BASE_DELAY = 1000    // 首次重连 1s
RECONNECT_MAX_DELAY  = 30000   // 退避上限 30s
WS_IDLE_TIMEOUT_MS   = 300000  // 空闲 5min 强制断开重连
```

- `_wsUrl(channel)`：`ws(s)://host/ws/{channel}?token=...`；行情支持 `VITE_QUOTE_WS_URL` 直连 hqserver。
- onopen：启动 30s 心跳定时器（客户端主动发 ping）+ 空闲超时计时。
- onclose：`code === 4001` → `_onTokenExpired`（单次保护，动态 import auth 清 session + 跳 /login，不重连）；否则指数退避重连（retryCount 递增取 min(base*2^n, 30s)）。
- onmessage：任何消息重置 `_lastRecvAt`；收到 ping 回 pong；业务帧回调 onMessage。
- `sendToChannel(channel, payload)`：未连接时静默失败（重连后靠 replay 补）。

### quote.js — 行情缓存

```js
const FIELD = { LAST: 2, OPEN: 3, ..., BID_VOL: 26 }   // 31 字段索引常量
const byCode = shallowRef(new Map())                    // code -> 快照
const tick = ref(0)                                     // 全局自增，驱动 daypnl 等 watcher
const subscribedSet = ref(new Set())
```

- `update(payload)`：合并 next + snapshot 字典数值化；v108 起从 snapshot 派生 31 字段 `fields` 数组。写 Map 后 `triggerRef(byCode)` + tick++。
- `applySnapshots(snapMap)`：批量首屏快照，复用 update 路径。
- `subscribe(codes)`：去重 → 超过 100 只切全市场 `['']` → REST `/quote/snapshots` 立即出价 → `wsDispatch.subscribe` 发订阅协议。
- `replayAll`：WS 重连后强制重发全部订阅（fix-ws-reconnect-subscription，防服务端重连丢订阅）。
- 读取 API：get/getQuote/getLastPrice/getField/getChangePct/getDepth/codes/size。

### ws.js — facade store

- `onConnected(channel)`：`channel === 'quote_update'` 时动态 `import('./quote')` → replayAll。
- 暴露 connect/disconnect/connected/lastEvent/sendToChannel + `lastTaskProgress`（ScriptTask.vue 读）。

### ws_dispatch.js — 分发表

`dispatchPayload` 按 `type` 分发：

| type | 处理 |
|---|---|
| ord_cfm | `_onOrderCfm`：diff 检查 + applyOrderPush → `_notifyOrderSmart` 按状态（50/55/56/57/54/53）分色 ElNotification |
| trd_cfm | `_onTradeCfm`：applyTradePush + payload.data.position → applyPositionUpdate |
| pos_push | `_onPosPush`（v118）：position_update channel 独立路径，直连 applyPositionUpdate |
| quote | applyQuote（持仓白名单过滤）→ quoteStore.update |
| task_progress_update | 写 ws.lastTaskProgress |
| asset_update | `_onAssetUpdate`（v99）：覆盖 holdings.cachedAsset（v110 available + v114 last_asset） |
| subscribe_ack / unsubscribe_ack | 确认回执（计数） |
| rpc_status | rpc_status store.setFromPayload |
| sync_started/progress/completed/failed/stopped + stock_synced | sync store 对应 onXxx |
| system_status_change | `_onSystemStatusChange`：init_start 开 initializing gate / init_aborted·init_completed 关 gate + resetForNewDay + `window.dispatchEvent('evtrade:day-init-completed')` |
| init_completed | 同上收尾 |

初始化期保护：`_isInitializing()` 读 holdings.initializing，初始化期间的交易推送计入 `_discardedDuringInit` 并丢弃（初始化完成后 resetForNewDay 全量校准）。

导出的 `subscribe(codes)/unsubscribe(codes)`：组 `quote_subscribe` 协议帧走 sendToChannel。

## 依赖关系

- ws.js → ws_heartbeat（createWsManager）+ ws_dispatch（dispatchPayload/subscribe）+ quote（动态 import replay）。
- ws_dispatch → holdings（applyXxx）、quote、rpc_status、sync、ws.lastTaskProgress；`_isInitializing` 读 holdings。
- quote → ws_dispatch（subscribe）+ api（snapshots REST）；反向由 ws_dispatch 调 quote.update（无环）。
- App.vue：watch isAuthenticated → ws.connect()/disconnect()。
- holdings_daypnl 依赖 quote.tick 驱动当日盈亏重算。

## 修改指南

- **新增推送类型**：ws_dispatch.dispatchPayload 加 case + 抽 `_onXxx` 私有函数；需要新 channel 时同步改 ws_heartbeat 的 CHANNELS 与后端。
- **改订阅协议**：quote.subscribe 与 ws_dispatch 的 subscribe/unsubscribe 帧格式、replayAll 三处保持一致，漏一处会出现重连后行情停更。
- **改行情字段**：只改 quote.js 的 FIELD 常量与 update 的 snapshot 派生段；消费方全部走 getField/getLastPrice，不要直接戳 Map。
- **改心跳/重连参数**：调 ws_heartbeat 顶部三个常量即可；注意与后端 idle 超时（10min）配套，30s ping 必须短于服务端 idle。
- **初始化期丢帧策略**：改 `_isInitializing`/`_discardedDuringInit` 时确认 init_completed 后有 resetForNewDay 兜底，否则丢的帧不会补回。

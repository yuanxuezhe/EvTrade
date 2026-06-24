/**
 * ws.js — WS 推送订阅 (facade, phase-2 拆分)
 *
 * phase-2 拆分:
 *   ws_heartbeat.js  — WebSocket 连接 / 重连 / 心跳 (~165 行)
 *   ws_dispatch.js   — payload → store 业务分发 + 通知 (~150 行)
 *   ws.js (本文件)   — Pinia store 装配 facade (~50 行)
 *
 * 协议:
 *   服务端把柜台 push 包（func + rows）原样转成 JSON:
 *   { type: "ord_cfm" | "trd_cfm" | "pos_cfm" | "ast_cfm",
 *     channel: "order_update" | "trade_update" | ...,
 *     ts: "...", data: { ...row fields... } }
 *
 * 行为:
 *   - 启动时连接所有 5 个 channel (含 quote_update 直连 hqserver)
 *   - 收到消息按 type 分发到 order / position / asset / holdings store
 *   - Element Plus 通知（成功/警告/危险，对应已成/部成/废单）
 *   - 断线自动重连（指数退避）
 *
 * 外部 API（兼容 21 view 不变）:
 *   wsStore.connect()    — 启动所有 channel
 *   wsStore.disconnect() — 主动断开
 *   wsStore.connected    — ref<boolean>
 *   wsStore.lastEvent    — ref<payload>
 */
import { defineStore } from 'pinia'
import { createWsManager } from './ws_heartbeat'
import { dispatchPayload } from './ws_dispatch'

export const useWsStore = defineStore('ws', () => {
  // ws_heartbeat 持有连接 + 心跳, 业务分发通过 onMessage 回调注入
  const { connect, disconnect, connected, lastEvent } = createWsManager(dispatchPayload)

  return {
    connected,
    lastEvent,
    connect,
    disconnect
  }
})

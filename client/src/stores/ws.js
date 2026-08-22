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
 *   { type: "ord_cfm" | "trd_cfm",
 *     channel: "order_update" | "trade_update",
 *     ts: "...", data: { ...row fields... } }
 *
 * 行为:
 *   - 启动时连接 4 个 channel（order_update / trade_update + quote_update 直连 hqserver）
 *   - 收到消息按 type 分发到 order / holdings store
 *   - Element Plus 通知（成功/警告/危险，对应已成/部成/废单）
 *   - 断线自动重连（指数退避）
 *
 * change consolidate-position-data-flow: pos_cfm / ast_cfm 类型推送已删除
 *   (xtquant broker 不发)。position_update / asset_update WS channel 也已删除,
 *   Position/Asset 数据走 day-init reconcile + holdings.positions / cachedAsset 内存缓存。
 *
 * 外部 API（兼容 21 view 不变）:
 *   wsStore.connect()    — 启动所有 channel
 *   wsStore.disconnect() — 主动断开
 *   wsStore.connected    — ref<boolean>
 *   wsStore.lastEvent    — ref<payload>
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { createWsManager } from './ws_heartbeat'
import { dispatchPayload } from './ws_dispatch'
import { makeLogger } from '../utils/logger'

const log = makeLogger('ws')

export const useWsStore = defineStore('ws', () => {
  // ws_heartbeat 持有连接 + 心跳, 业务分发通过 onMessage 回调注入
  // quote-snapshot-subscribe: 暴露 sendToChannel（quoteStore.subscribe 用）
  // fix-ws-reconnect-subscription: onConnected 回调在 ws 重连成功后强制重发 quote 订阅
  const onConnected = (channel) => {
    if (channel !== 'quote_update') return
    // 动态 import 避免循环依赖（quote → ws_dispatch → ws → ws_heartbeat → ?）
    import('./quote').then(({ useQuoteStore }) => {
      const quoteStore = useQuoteStore()
      if (quoteStore.subscribedSet.size > 0) {
        log.info('[ws] replay subscriptions:', quoteStore.subscribedSet.size)
        quoteStore.replayAll().catch((e) => log.warn('replay failed:', e?.message))
      }
    }).catch((e) => log.warn('quote import failed:', e?.message))
  }
  const { connect, disconnect, connected, lastEvent, sendToChannel } = createWsManager(dispatchPayload, onConnected)

  // task 进度推送 (ScriptTask.vue 订阅)
  const lastTaskProgress = ref(null)

  return {
    connected,
    lastEvent,
    lastTaskProgress,
    connect,
    disconnect,
    sendToChannel,
  }
})

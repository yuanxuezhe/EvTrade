import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * RPC 通信状态 (来自后端 rpc_health 心跳):
 *   0 = RPC 通讯正常
 *   1 = RPC 通信异常 (积压/超时/连接失败)
 *   2 = RPC 通信正常，但没有返回正常数据
 *
 * 唯一数据源是 ws_dispatch._onRpcStatus 写入的 push 帧
 * + AppHeader.onMounted() 拉 /api/asset/rpc-status 初始化。
 */
export const useRpcStatusStore = defineStore('rpc_status', () => {
  const status = ref(0)
  const message = ref('RPC通讯正常')
  const lastOkAt = ref(0)
  const lastErrMsg = ref('')
  const lastUpdatedAt = ref(0)
  const requestQueueDepth = ref(0)

  function setFromPayload(data) {
    if (!data) return
    if (typeof data.status === 'number') status.value = data.status
    if (typeof data.message === 'string') message.value = data.message
    if (typeof data.last_ok_at === 'number') lastOkAt.value = data.last_ok_at
    if (typeof data.last_err_msg === 'string') lastErrMsg.value = data.last_err_msg
    if (typeof data.request_queue_depth === 'number') requestQueueDepth.value = data.request_queue_depth
    lastUpdatedAt.value = Date.now()
  }

  return {
    status,
    message,
    lastOkAt,
    lastErrMsg,
    lastUpdatedAt,
    requestQueueDepth,
    setFromPayload,
  }
})

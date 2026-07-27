/**
 * useRpcStatusStore — RPC 三态推送接收
 *
 * 覆盖 ws_dispatch 写入 / getRpcStatus 首屏拉取的字段映射
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useRpcStatusStore } from '../../src/stores/rpc_status'

describe('useRpcStatusStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('默认 0 = 正常', () => {
    const s = useRpcStatusStore()
    expect(s.status).toBe(0)
    expect(s.message).toBe('RPC通讯正常')
  })

  it('写入 status=1 + 错误信息', () => {
    const s = useRpcStatusStore()
    s.setFromPayload({ status: 1, message: 'RPC通信异常', last_err_msg: 'queue backlog', request_queue_depth: 120 })
    expect(s.status).toBe(1)
    expect(s.message).toBe('RPC通信异常')
    expect(s.lastErrMsg).toBe('queue backlog')
    expect(s.requestQueueDepth).toBe(120)
  })

  it('写入 status=2 (code=0 但 row_count=0)', () => {
    const s = useRpcStatusStore()
    s.setFromPayload({ status: 2, message: 'RPC通信正常，但没有返回正常数据' })
    expect(s.status).toBe(2)
  })

  it('接受 /api/asset/rpc-status 原始返回 (无 status 字段时不抛错)', () => {
    const s = useRpcStatusStore()
    s.setFromPayload({ ok: true })
    expect(s.status).toBe(0)
  })
})

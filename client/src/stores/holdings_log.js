/**
 * holdings_log.js — holdings store 操作流水日志 helper
 *
 * phase-2 抽取：保持 holdings.js 单 store facade (R3),
 * 但把无状态依赖的日志工具放到独立模块
 *
 * 调用者：holdings.js 内部 createLogger(loadHistory ref) → { log, clearHistory }
 */
import { makeLogger } from '../utils/logger'

const _log = makeLogger('holdings')

export const MAX_HISTORY = 200

/**
 * 创建日志工具
 *
 * @param {Ref<Array>} loadHistory  Pinia store 的 ref<Array>
 * @returns {{ log, clearHistory }}
 */
export function createLogger(loadHistory) {
  let _histId = 0

  function log(level, tag, source, message, detail = null) {
    _histId++
    const entry = {
      id: _histId,
      ts: Date.now(),
      level,        // 'info' / 'ok' / 'warn' / 'err'
      tag,          // '缓存' | '交易' | '用户' | '系统'
      source,       // 'bootstrap' / 'refresh' / 'ws' / 'user' / 'rpc'
      message,
      detail
    }
    loadHistory.value.unshift(entry)
    if (loadHistory.value.length > MAX_HISTORY) {
      loadHistory.value.length = MAX_HISTORY
    }
    // 同时写一份到 logger 便于扫描 (UI 流水本身仍走 loadHistory ref)
    const tagStr = `${source}/${tag} ${message}`
    if (level === 'err') _log.error(tagStr, detail || '')
    else if (level === 'warn') _log.warn(tagStr, detail || '')
    else _log.info(tagStr, detail || '')
    return entry
  }

  function clearHistory() {
    loadHistory.value = []
  }

  return { log, clearHistory }
}

/**
 * logger.js — 前端统一日志器（console + localStorage ring buffer）
 *
 * 用途:
 *   - 替代裸 console.* 调用, 提供等级 (DEBUG/INFO/WARN/ERROR) + 模块名前缀
 *   - 持久化最近 1000 条到 localStorage (key: evtrade:log:ring)
 *   - 暴露 window.__evtradeDownloadLog() 给 console 一键下载日志
 *   - 暴露 window.__evtradeSetLogLevel(level) 调试期动态调级别
 *
 * 设计:
 *   - 不引入第三方日志库 (loglevel / winston-browser), 保持依赖最小
 *   - 同源 (同 window) 单例, 多次 import 复用
 *   - localStorage 写入失败时静默降级到 console only (隐私模式 / quota 超限)
 *
 * 配合后端 REQ-LOG-006:
 *   - 后端日志落地 server/logs/server-YYYYMMDD.log
 *   - 前端日志落地浏览器 localStorage (跨会话保留直到 quota 满)
 *   - 配合 dev tool: window.__evtradeDownloadLog() 拉到本地后用 grep/jq 分析
 *
 * 用法:
 *   import { logger } from '@/utils/logger'  // 或 '../utils/logger'
 *   logger.info('ws', 'connected', { channel: 'quote_update' })
 *   logger.error('api', 'request failed', err)
 *
 *   // 一键下载:
 *   window.__evtradeDownloadLog()
 */

const LEVELS = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40 }
const LEVEL_NAMES = ['DEBUG', 'INFO', 'WARN', 'ERROR']

const RING_KEY = 'evtrade:log:ring'
const RING_MAX = 1000
const LEVEL_KEY = 'evtrade:log:level'

// ---- ring buffer (FIFO, 满则驱逐最老) ----
let _ring = []
try {
  const raw = localStorage.getItem(RING_KEY)
  if (raw) {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) _ring = parsed
  }
} catch (_e) {
  _ring = []  // 解析失败 → 重置
}

function _pushRing(entry) {
  _ring.push(entry)
  if (_ring.length > RING_MAX) {
    // 驱逐最老的 (RING_MAX/4) 条, 避免每次都写 localStorage
    _ring = _ring.slice(_ring.length - Math.floor(RING_MAX * 0.75))
  }
  try {
    localStorage.setItem(RING_KEY, JSON.stringify(_ring))
  } catch (_e) {
    // quota 超限 / 隐私模式 → 静默降级
  }
}

function _nowIso() {
  // 2026-07-07T08:33:29.058Z
  return new Date().toISOString()
}

// ---- 当前级别 ----
function _getLevel() {
  try {
    const v = localStorage.getItem(LEVEL_KEY)
    if (v && LEVELS[v] != null) return LEVELS[v]
  } catch (_e) { /* ignore */ }
  return LEVELS.INFO  // 默认 INFO
}

function _setLevel(name) {
  if (LEVELS[name] == null) return false
  try { localStorage.setItem(LEVEL_KEY, name) } catch (_e) { /* ignore */ }
  return true
}

// ---- 核心: 输出到 console + ring buffer ----
function _emit(levelName, module, args) {
  if (LEVELS[levelName] < _getLevel()) return
  const ts = _nowIso()
  const prefix = `[${levelName}][${ts}][${module || 'app'}]`
  const line = prefix + ' ' + args.map(_stringify).join(' ')

  // console (按级别选方法, 这样 dev tool 能 filter)
  const consoleFn =
    levelName === 'ERROR' ? console.error :
    levelName === 'WARN'  ? console.warn  :
    levelName === 'DEBUG' ? console.debug :
                            console.log
  consoleFn(prefix, ...args)

  // ring buffer (只存纯文本, 不存对象引用, 防内存泄漏)
  _pushRing(line)
}

function _stringify(arg) {
  if (arg instanceof Error) return arg.stack || (arg.name + ': ' + arg.message)
  if (typeof arg === 'string') return arg
  try { return JSON.stringify(arg) } catch (_e) { return String(arg) }
}

// ---- public API ----
function makeLogger(defaultModule) {
  return {
    debug: (...args) => _emit('DEBUG', defaultModule, args),
    info:  (...args) => _emit('INFO',  defaultModule, args),
    warn:  (...args) => _emit('WARN',  defaultModule, args),
    error: (...args) => _emit('ERROR', defaultModule, args),
  }
}

// ---- 全局 API (挂到 window) ----
function _downloadLog() {
  const lines = _ring.length ? _ring.join('\n') : '(empty)'
  const blob = new Blob([lines], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  a.href = url
  a.download = `evtrade-client-${ts}.log`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function _clearLog() {
  _ring = []
  try { localStorage.removeItem(RING_KEY) } catch (_e) { /* ignore */ }
}

function _setLevelApi(name) {
  const ok = _setLevel(name)
  if (!ok) console.warn('[logger] invalid level:', name, '(allowed:', LEVEL_NAMES.join(',') + ')')
  return ok
}

function _bindWindow() {
  if (typeof window === 'undefined') return  // SSR / Node 环境跳过
  window.__evtradeDownloadLog = _downloadLog
  window.__evtradeClearLog = _clearLog
  window.__evtradeSetLogLevel = _setLevelApi
  window.__evtradeGetLogLevel = () => LEVEL_NAMES.find(n => LEVELS[n] === _getLevel()) || 'INFO'
  window.__evtradeLogStats = () => ({
    ringSize: _ring.length,
    ringMax: RING_MAX,
    level: window.__evtradeGetLogLevel(),
  })
}

// 副作用: 挂 window API (模块加载即生效)
_bindWindow()

// 默认 logger (模块名 'app'), 各业务模块可 makeLogger('ws') / makeLogger('api')
const logger = makeLogger('app')

export {
  logger,
  makeLogger,
  LEVELS,
  LEVEL_NAMES,
  RING_MAX,
  RING_KEY,
}

export default logger
/**
 * auth_idb.js — token & user 持久化到 IndexedDB
 *
 * 用途:
 *   - 登录成功后把 token + user 写入 IDB, 浏览器刷新 / 重开 tab 后自动恢复
 *   - 重新登录 → saveSession 覆盖 → 旧 token 失效,新 token 生效
 *   - 登出 → clearSession 清空
 *
 * 设计:
 *   - 独立数据库 EvTrade-auth（不复用 holdings-cache / stocks,生命周期与认证状态分离）
 *   - 单 store 'kv', 单 key 'session', value = { token, user, savedAt }
 *   - 复用 utils/idb.js 的 openDB / idbGet / idbPut / idbDelete（Promise 风格）
 *   - 单例 _db + _initPromise：多次 initAuthIDB 复用同一 connection
 *
 * 不影响:
 *   - tokenStorage (client/src/api/index.js) 仍读 localStorage 作同步 fallback
 *     hydrate 完成后 IDB 数据已写回 localStorage, ws_heartbeat 的同步读路径不变
 */
import { openDB, idbGet, idbPut, idbDelete } from '../utils/idb'

const DB_NAME = 'auth'
const DB_VERSION = 1
const STORE = 'kv'
const KEY = 'session'

let _db = null
let _initPromise = null

/**
 * 初始化 / 复用 IDB connection
 * @returns {Promise<IDBDatabase>}
 */
export function initAuthIDB() {
  if (_db) return Promise.resolve(_db)
  if (_initPromise) return _initPromise
  _initPromise = openDB(DB_NAME, DB_VERSION, [STORE])
    .then((db) => { _db = db; return db })
  return _initPromise
}

/**
 * 读取已持久化的 session（无则返 null）
 * @returns {Promise<{token: string, user: object|null, savedAt: number}|null>}
 */
export async function loadSession() {
  try {
    const db = await initAuthIDB()
    const v = await idbGet(db, STORE, KEY)
    if (!v || typeof v !== 'object') return null
    if (!v.token) return null
    return {
      token: v.token,
      user: v.user || null,
      savedAt: v.savedAt || 0
    }
  } catch (e) {
    // 隐身模式 / IDB 禁用等场景不抛, 仅返回 null 让上层走 /login
    return null
  }
}

/**
 * 写入 session（覆盖旧的）
 * @param {{token: string, user?: object|null}} payload
 */
export async function saveSession({ token, user }) {
  if (!token) throw new Error('[auth_idb] saveSession: token is required')
  const db = await initAuthIDB()
  await idbPut(db, STORE, KEY, {
    token,
    user: user || null,
    savedAt: Date.now()
  })
}

/**
 * 清除已持久化的 session（不抛错）
 */
export async function clearSession() {
  try {
    const db = await initAuthIDB()
    await idbDelete(db, STORE, KEY)
  } catch (_) {
    // ignore: IDB 失败不影响登出 / 401 流程
  }
}
/**
 * idb.js — 浏览器 IndexedDB 薄封装
 *
 * 用途：
 *   - 仅作为前端持久化层（holds 缓存当日 orders / trades，断网/重启后 F5 即时显示）
 *   - 不是 critical store；IDB 写失败不抛，仅 warn
 *   - 浏览器之外环境（Node 测试 / happy-dom）走 mock 路径，unit-test 见 tests/client/stores/test_holdings_idb.js
 *
 * 设计：
 *   - thin Promise 包装，所有 export 都是 async
 *   - openDB 自动 resolve；多次 openDB(name) 复用同一 connection
 *   - 单调用失败：reject → 由调用方 try/catch
 *
 * change add-manual-adjust-and-history-pages
 */
const DB_PREFIX = 'EvTrade'

// 进程内 connection 缓存（按 dbName 引用）
const _connections = new Map()

/**
 * 打开（或复用）IDB 数据库
 *
 * @param {string} dbName         DB 名（不含 EvTrade 前缀，前缀自动加）
 * @param {number} version        schema version（>=1）
 * @param {string[]} [storeNames] 需要存在的 object store 名（首次按需 createObjectStore）
 * @param {Function} [onUpgrade]  可选, schema 升级回调 (db, oldV, newV) => void,
 *                                用于删旧 store / 加索引等 (必须在 onupgradeneeded 事务内)
 * @returns {Promise<IDBDatabase>}
 */
export function openDB(dbName, version = 1, storeNames = [], onUpgrade = null) {
  const fullName = `${DB_PREFIX}-${dbName}`
  if (_connections.has(fullName)) {
    return Promise.resolve(_connections.get(fullName))
  }

  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('[IDB] indexedDB API not available (Node or sandbox)'))
      return
    }

    const req = indexedDB.open(fullName, version)

    req.onupgradeneeded = (event) => {
      const db = event.target.result
      const oldV = event.oldVersion
      const newV = event.newVersion
      for (const store of storeNames) {
        if (!db.objectStoreNames.contains(store)) {
          db.createObjectStore(store)
        }
      }
      if (typeof onUpgrade === 'function') {
        onUpgrade(db, oldV, newV)
      }
    }
    req.onsuccess = (event) => {
      const db = event.target.result
      _connections.set(fullName, db)
      resolve(db)
    }
    req.onerror = () => reject(req.error || new Error('[IDB] open failed'))
    req.onblocked = () =>
      reject(new Error('[IDB] open blocked (close other tabs?)'))
  })
}

/**
 * 读取 object store 中 key 对应的 value（不存在时返 null）
 * @param {IDBDatabase} db
 * @param {string} store
 * @param {IDBValidKey} key
 * @returns {Promise<any>}
 */
export function idbGet(db, store, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const req = tx.objectStore(store).get(key)
    req.onsuccess = () => resolve(req.result === undefined ? null : req.result)
    req.onerror = () => reject(req.error || new Error('[IDB] get failed'))
  })
}

/**
 * 写入（覆盖）value
 * @returns {Promise<void>}
 */
export function idbPut(db, store, key, value) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    const req = tx.objectStore(store).put(value, key)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error || new Error('[IDB] put failed'))
  })
}

/**
 * 删除单 key
 * @returns {Promise<void>}
 */
export function idbDelete(db, store, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    const req = tx.objectStore(store).delete(key)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error || new Error('[IDB] delete failed'))
  })
}

/**
 * 清空整个 store
 * @returns {Promise<void>}
 */
export function idbClear(db, store) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    const req = tx.objectStore(store).clear()
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error || new Error('[IDB] clear failed'))
  })
}

/**
 * 取 store 内全部 key（用于复合 key 场景的"按日扫描"，IDB 原生不支持 prefix scan）
 * @returns {Promise<IDBValidKey[]>}
 */
export function idbGetAllKeys(db, store) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const req = tx.objectStore(store).getAllKeys()
    req.onsuccess = () => resolve(req.result || [])
    req.onerror = () => reject(req.error || new Error('[IDB] getAllKeys failed'))
  })
}

/**
 * 取 store 内全部 records (getAll)
 * @returns {Promise<any[]>}
 */
export function idbGetAll(db, store) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const req = tx.objectStore(store).getAll()
    req.onsuccess = () => resolve(req.result || [])
    req.onerror = () => reject(req.error || new Error('[IDB] getAll failed'))
  })
}

/**
 * 关闭并清理 connection 缓存（测试 teardown 用）
 */
export function _resetForTests() {
  for (const db of _connections.values()) {
    try { db.close() } catch (_) { /* ignore */ }
  }
  _connections.clear()
}

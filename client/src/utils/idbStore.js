/**
 * idbStore.js — 4 张业务表 + 1 张 meta 的 IndexedDB 封装
 *
 * 业务表（4 张，对应用户视角"资金/持仓/委托/成交"）:
 *   - asset:     1 行 (singleton), 资金快照
 *   - positions: 多行, keyPath=stock_code, 持仓字典
 *   - orders:    多行, keyPath=order_no, 委托字典
 *   - trades:    多行, keyPath=[trd_date, trade_id] 复合键, 成交字典
 *
 * Meta 表（1 张）:
 *   - _meta: 2-3 行, 存 schema_version / last_rehydrate_ms / last_write_ms
 *
 * Schema 升级策略: 改 SCHEMA_VERSION 即触发 deleteDatabase + 重建
 *   - 升级时: 旧 DB 整库删, 启动后下次 API 调用触发 bulkReplace 重新灌入
 *   - 不写迁移函数 (用户选 "全量清空, 简单粗暴")
 *
 * DevTools 浏览: Application > IndexedDB > evtrade-cache > 5 个 object store
 */
import { openDB, deleteDB } from 'idb'

export const DB_NAME = 'evtrade-cache'
export const SCHEMA_VERSION = 1

// 4 业务 + 1 meta
export const STORES = ['asset', 'positions', 'orders', 'trades', '_meta']

// 业务表 keyPath 集中定义（供 write/read helper 引用）
export const KEY_PATHS = {
  asset: 'id',                          // 固定 'singleton'
  positions: 'stock_code',
  orders: 'order_no',
  trades: ['trd_date', 'trade_id'],     // 复合键
  _meta: 'key',
}

let _dbPromise = null

/**
 * 打开 DB（单例）。version 冲突时由 idb 触发 upgrade 回调。
 *
 * 注意: openDB 的 version 与 SCHEMA_VERSION 必须一致；改 SCHEMA_VERSION 后
 * 下次打开会自动触发 upgrade（同时执行旧 DB delete-and-recreate 逻辑，
 * 因为本设计下 upgrade 永远 = 删表重建）。
 */
export function openCacheDB() {
  if (_dbPromise) return _dbPromise
  _dbPromise = openDB(DB_NAME, SCHEMA_VERSION, {
    upgrade(db, oldVersion) {
      // v1 初始化 + 任意旧版本升级到 SCHEMA_VERSION 时都重建所有表
      // （用户策略：全量清空，无迁移函数）
      for (const name of STORES) {
        if (db.objectStoreNames.contains(name)) {
          db.deleteObjectStore(name)
        }
        const opts = {}
        if (name !== 'asset' && name !== '_meta') {
          opts.keyPath = KEY_PATHS[name]
        } else if (name === 'asset') {
          opts.keyPath = KEY_PATHS[name]  // 'id'
        } else {
          opts.keyPath = KEY_PATHS[name]  // 'key'
        }
        db.createObjectStore(name, opts)
      }
      // 写初始 schema_version 到 _meta
      // 注意: upgrade 回调内是同步的 version transaction, 用 tx.oncomplete 不便链式,
      // 写 SCHEMA_VERSION 行由 initMeta() 在外部完成
      console.log(`[idbStore] upgrade ${oldVersion} → ${SCHEMA_VERSION}, recreated all stores`)
    },
  })
  return _dbPromise
}

/**
 * 初始化 _meta 表：写入 schema_version 标记。
 * 在 DB 第一次打开后调用一次。
 */
export async function initMeta() {
  const db = await openCacheDB()
  const tx = db.transaction('_meta', 'readwrite')
  await tx.store.put({ key: 'schema_version', value: SCHEMA_VERSION })
  await tx.store.put({ key: 'last_rehydrate_ms', value: Date.now() })
  await tx.done
}

/**
 * 检查 schema_version 是否匹配。返回 false 时调用方应触发 deleteDatabase 重灌。
 */
export async function checkSchemaVersion() {
  const db = await openCacheDB()
  const row = await db.get('_meta', 'schema_version')
  return row && row.value === SCHEMA_VERSION
}

/**
 * 不匹配时: 删整库 + 重新打开。
 * 返回新 DB 实例（_dbPromise 被重置）。
 */
export async function resetAndReopen() {
  _dbPromise = null
  await deleteDB(DB_NAME)
  const db = await openCacheDB()
  await initMeta()
  return db
}

/**
 * 记录最近一次 write-through 时间。
 */
export async function touchLastWrite() {
  const db = await openCacheDB()
  await db.put('_meta', { key: 'last_write_ms', value: Date.now() })
}

// ============== 通用读写 helper ==============
// 上层 store 用这些 API，不需要直接接触 openCacheDB()

/**
 * 清空指定 object store
 */
export async function clearStore(storeName) {
  const db = await openCacheDB()
  await db.clear(storeName)
}

/**
 * 单条 upsert (put)。对于 trades 复合键传数组。
 */
export async function putItem(storeName, item) {
  const db = await openCacheDB()
  await db.put(storeName, item)
}

/**
 * 单条 delete (by key)
 */
export async function deleteItem(storeName, key) {
  const db = await openCacheDB()
  await db.delete(storeName, key)
}

/**
 * 批量 upsert (clear + 多 put)。用于 fetchXxx 完成后的全量同步。
 *
 * idb v8 注意:
 *   - tx.store.bulkPut **不存在** (v8 移除了批量便捷方法,只暴露 IDB 标准 API)
 *   - tx.store.put(value, key) 存在且 async, 可并行 await
 *   - 也可以走非事务 db.clear + 多次 db.put, IDB 会自动合并到 readwrite 事务
 *
 * 事务写法选: 显式 readwrite 事务, 保证 clear + puts 原子性 (中途失败 → 全回滚)
 */
export async function bulkReplace(storeName, items) {
  const db = await openCacheDB()
  const tx = db.transaction(storeName, 'readwrite')
  await tx.store.clear()
  if (items && items.length > 0) {
    await Promise.all(items.map((item) => tx.store.put(item)))
  }
  await tx.done
}

/**
 * 读单条 (by key)
 */
export async function getItem(storeName, key) {
  const db = await openCacheDB()
  return await db.get(storeName, key)
}

/**
 * 读全部 (返回数组，按 keyPath 顺序)
 */
export async function getAll(storeName) {
  const db = await openCacheDB()
  return await db.getAll(storeName)
}

/**
 * 计数
 */
export async function countStore(storeName) {
  const db = await openCacheDB()
  return await db.count(storeName)
}

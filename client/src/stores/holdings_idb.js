/**
 * holdings_idb.js — 当日 orders / trades IDB 持久化（v13: 复合 PK 改造）
 *
 * 用途：
 *   - 解决"Today's Orders 页面 F5 后空白等待"痛点
 *   - bootstrap() 命中 IDB 时立刻回填 Pinia（200ms 内显示），不去拉 RPC
 *   - ws push 时 fire-and-forget 写 IDB（不阻塞 event loop）
 *
 * 设计 (v13 复合 key):
 *   - DB schema v2, 2 个 object store: `orders` / `trades`
 *   - key = 复合 PK 字符串:
 *       orders  → `${trd_date}:${order_no}`        (镜像 server/models/orm.py:Order PK)
 *       trades  → `${trd_date}:${order_no}:${trade_id}`  (镜像 Trade PK)
 *   - value = 单行 OrderOut / TradeOut (JSON 深拷贝, 不与 Pinia 共享引用)
 *   - ws push 增量 = O(1) idbPut（不再读全量 / 写全量）
 *   - 跨日清理由 loadXxxForDate / clearDate 内部按 prefix 扫描（IDB 无原生 prefix scan）
 *   - 写失败一律 console.warn，**不抛**（critical path 不被 IDB 卡住）
 *
 * v12 → v13 schema 迁移:
 *   - v12 key = trd_date, value = array（不兼容 v13 复合 key 维度）
 *   - 升级 onUpgrade 回调: 删旧 store, 由 openDB 自动重建
 *   - IDB 是 cache, 丢旧数据可接受（bootstrap 重新拉 RPC 写回）
 *
 * 调用者：
 *   - holdings_bootstrap.js：bootstrap 启动 initIDB() + loadXxxForDate
 *   - holdings_push.js：applyOrderPush/applyTradePush 末尾调 saveOrder/saveTrade（fire-and-forget）
 *   - 不被 view 引用，view 仅读 Pinia (useHoldingsStore)
 *
 * change optimize-push-data-flow (v13)
 *   - IDB 改复合 key 存（每行单 key, 镜像 DB PK 结构）
 *   - 删 v12 的 saveOrdersForDate / saveTradesForDate（trd_date 单 key 全量）
 *   - 改 saveOrder(order) / saveTrade(trade) 单行 API
 *   - 跨日清理走 idbGetAllKeys 扫描 + filter
 */
import { openDB, idbGet, idbPut, idbDelete, idbGetAllKeys } from '../utils/idb'

const DB_NAME = 'holdings-cache'
const DB_VERSION = 2
const STORE_ORDERS = 'orders'
const STORE_TRADES = 'trades'

// module-level 单例 db handle（process 内复用）
let _db = null
let _initPromise = null

/**
 * 拼装 orders 复合 key（镜像 server/models/orm.py:Order PK）
 */
function _orderKey(order) {
  return `${order.trd_date}:${order.order_no}`
}

/**
 * 拼装 trades 复合 key（镜像 server/models/orm.py:Trade PK）
 */
function _tradeKey(trade) {
  return `${trade.trd_date}:${trade.order_no}:${trade.trade_id}`
}

/**
 * 判断 key 是否属于指定交易日（orders + trades 共用）
 *   - orders  key:  `${trd_date}:${order_no}`         → startsWith(`${trdDate}:`)
 *   - trades  key:  `${trd_date}:${order_no}:${trade_id}` → startsWith(`${trdDate}:`)
 */
function _isKeyOfDate(key, trdDate) {
  return typeof key === 'string' && key.startsWith(`${trdDate}:`)
}

/**
 * 初始化（首次调为后续 get/put 打开 DB）。
 * 多次调用复用同一 connection；IDB API 不可用（Node / SSR）时 reject。
 *
 * v12 → v13 升级：删旧 v12 store (key = trd_date, value = array),
 * 由 openDB 内 storeNames 循环按需重建.
 *
 * @returns {Promise<IDBDatabase>}
 */
export function initIDB() {
  if (_db) return Promise.resolve(_db)
  if (_initPromise) return _initPromise
  _initPromise = openDB(
    DB_NAME,
    DB_VERSION,
    [STORE_ORDERS, STORE_TRADES],
    (db, oldV) => {
      // v12 → v13 升级: 删旧 store (复合 key 维度不兼容, IDB 是 cache 丢可接受)
      if (oldV < 2) {
        if (db.objectStoreNames.contains(STORE_ORDERS)) {
          db.deleteObjectStore(STORE_ORDERS)
        }
        if (db.objectStoreNames.contains(STORE_TRADES)) {
          db.deleteObjectStore(STORE_TRADES)
        }
      }
    }
  )
    .then((db) => {
      _db = db
      return db
    })
    .catch((e) => {
      _initPromise = null
      throw e
    })
  return _initPromise
}

/**
 * 异步读取当前 db handle（init 后），未 init 时为 null。
 */
export function _getDb() {
  return _db
}

/**
 * Internal: ensure db ready, return db or null（不可用时不抛）
 */
async function _ensure() {
  try {
    return await initIDB()
  } catch (e) {
    console.warn('[IDB] init failed:', e?.message || e)
    return null
  }
}

/**
 * Internal: 加载指定日期的某 store 全部 row（按复合 key 前缀扫描）
 *   - IDB 无原生 prefix scan, 走 getAllKeys + filter + get
 *   - 数量级: 当日 ~100-1000 单, 扫描 + N 次 get 仍是 ms 级
 * @returns {Promise<Array>}
 */
async function _loadByDate(storeName, trdDate) {
  if (!trdDate) return null
  try {
    const db = await initIDB()
    const allKeys = await idbGetAllKeys(db, storeName)
    const dayKeys = allKeys.filter((k) => _isKeyOfDate(k, trdDate))
    if (dayKeys.length === 0) return null
    const rows = await Promise.all(
      dayKeys.map((k) => idbGet(db, storeName, k))
    )
    // 过滤 null (防御性: 极端竞态下 key 存在但 value 缺失)
    return rows.filter(Boolean)
  } catch (e) {
    console.warn(`[IDB] _loadByDate(${storeName}, ${trdDate}) failed:`, e?.message || e)
    return null
  }
}

/**
 * Internal: 清掉指定日期在某 store 内的全部 key（按复合 key 前缀扫描）
 */
async function _clearByDate(storeName, trdDate) {
  if (!trdDate) return
  try {
    const db = await initIDB()
    const allKeys = await idbGetAllKeys(db, storeName)
    const dayKeys = allKeys.filter((k) => _isKeyOfDate(k, trdDate))
    await Promise.all(dayKeys.map((k) => idbDelete(db, storeName, k)))
  } catch (e) {
    console.warn(`[IDB] _clearByDate(${storeName}, ${trdDate}) failed:`, e?.message || e)
  }
}

/**
 * Internal: 深拷贝序列化（避免 Pinia ref 变更污染 IDB 缓存）
 */
function _clone(obj) {
  return obj == null ? obj : JSON.parse(JSON.stringify(obj))
}

/**
 * 保存单笔委托到 IDB（fire-and-forget；失败 warn 不抛）
 *
 * v13 复合 key: key = `${trd_date}:${order_no}`
 *
 * @param {Object} order  OrderOut
 */
export function saveOrder(order) {
  if (!order || !order.trd_date || !order.order_no) return
  _ensure().then((db) => {
    if (!db) return
    return idbPut(db, STORE_ORDERS, _orderKey(order), _clone(order))
  }).catch((e) => {
    console.warn('[IDB] saveOrder failed:', _orderKey(order), e?.message || e)
  })
}

/**
 * 加载指定日期的全部委托（IDB 命中返 Array，miss 返 null）
 *
 * @param {string} trdDate
 * @returns {Promise<Array | null>}
 */
export function loadOrdersForDate(trdDate) {
  return _loadByDate(STORE_ORDERS, trdDate)
}

/**
 * 保存单笔成交到 IDB（fire-and-forget；失败 warn 不抛）
 *
 * v13 复合 key: key = `${trd_date}:${order_no}:${trade_id}`
 *
 * @param {Object} trade  TradeOut
 */
export function saveTrade(trade) {
  if (!trade || !trade.trd_date || !trade.order_no || !trade.trade_id) return
  _ensure().then((db) => {
    if (!db) return
    return idbPut(db, STORE_TRADES, _tradeKey(trade), _clone(trade))
  }).catch((e) => {
    console.warn('[IDB] saveTrade failed:', _tradeKey(trade), e?.message || e)
  })
}

/**
 * 加载指定日期的全部成交
 *
 * @param {string} trdDate
 * @returns {Promise<Array | null>}
 */
export function loadTradesForDate(trdDate) {
  return _loadByDate(STORE_TRADES, trdDate)
}

/**
 * 清掉指定日期的 IDB key（跨日切换时调用：orders + trades 同步清）
 *
 * @param {string} trdDate
 * @returns {Promise<void>}
 */
export async function clearDate(trdDate) {
  if (!trdDate) return
  await Promise.all([
    _clearByDate(STORE_ORDERS, trdDate),
    _clearByDate(STORE_TRADES, trdDate),
  ])
}

/**
 * 仅测试用：重置 module-level 单例（happy-dom 测每个用例前调）。
 */
export function _resetForTests() {
  _db = null
  _initPromise = null
}

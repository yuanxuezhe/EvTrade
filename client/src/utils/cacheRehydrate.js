/**
 * cacheRehydrate.js — 启动时从 IDB 恢复 4 张业务表到 Pinia store
 *
 * 调用时机: main.js 创建 Pinia 之后、App.mount 之前
 *
 * 流程:
 *   1) openCacheDB() → 第一次写入 schema_version
 *   2) checkSchemaVersion() → 不匹配则 resetAndReopen()
 *   3) 并行 getAll 4 表 → 写回 Pinia 对应 ref
 *   4) touch last_rehydrate_ms
 *
 * 容错: IDB 读失败 → 静默降级 (Pinia 用初始值, 不阻塞启动)
 */
import { openCacheDB, initMeta, checkSchemaVersion, resetAndReopen, getAll, touchLastWrite } from './idbStore'
import { useAssetStore } from '../stores/asset'
import { usePositionStore } from '../stores/position'
import { useHoldingsStore } from '../stores/holdings'

/**
 * 启动 rehydrate (供 main.js await)
 *
 * @returns {Promise<{asset: number, positions: number, orders: number, trades: number}>}
 *          各表 rehydrate 出的行数 (用于日志 / 调试)
 */
export async function rehydrateFromIDB() {
  try {
    // 1) 打开 + 首次写 schema_version
    await openCacheDB()
    const ok = await checkSchemaVersion()
    if (!ok) {
      console.warn('[cacheRehydrate] schema_version 不匹配, 触发重灌')
      await resetAndReopen()
    } else {
      // 即使匹配, 也确保 schema_version 存在 (首次)
      await initMeta()
    }

    // 2) 并行读 4 表
    const [assetRows, posRows, orderRows, tradeRows] = await Promise.all([
      getAll('asset').catch(() => []),
      getAll('positions').catch(() => []),
      getAll('orders').catch(() => []),
      getAll('trades').catch(() => []),
    ])

    // 3) 写回 Pinia (按 store)
    const assetStore = useAssetStore()
    if (assetRows.length > 0) {
      const row = assetRows[0]
      assetStore.asset = {
        cash: Number(row.cash) || 0,
        frozen_cash: Number(row.frozen_cash) || 0,
        market_value: Number(row.market_value) || 0,
        total_asset: Number(row.total_asset) || 0,
      }
    }

    const positionStore = usePositionStore()
    if (posRows.length > 0) {
      positionStore.positions = posRows
    }

    // 持仓也回灌到 holdings.positions (v8 单一源架构)
    const holdingsStore = useHoldingsStore()
    if (posRows.length > 0) {
      holdingsStore.positions = posRows
    }
    if (orderRows.length > 0) {
      holdingsStore.orders = orderRows
    }
    if (tradeRows.length > 0) {
      holdingsStore.trades = tradeRows
    }

    await touchLastWrite()

    const counts = {
      asset: assetRows.length,
      positions: posRows.length,
      orders: orderRows.length,
      trades: tradeRows.length,
    }
    console.log('[cacheRehydrate] 4 表恢复完成', counts)
    return counts
  } catch (e) {
    // 任何 IDB 错误都不应阻塞启动
    console.error('[cacheRehydrate] 失败, 降级为空缓存:', e)
    return { asset: 0, positions: 0, orders: 0, trades: 0 }
  }
}

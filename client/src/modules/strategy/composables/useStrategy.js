/**
 * useStrategy.js — 策略 CRUD + 状态/类型映射组合式（task 11.2）
 *
 * 职责：
 * - 暴露 CRUD 操作的薄封装（带 ElMessage 提示）
 * - status / type 文案映射（视图层使用）
 * - 提供分组 getters（已 activeStrategies / t0Strategies 等复用 store）
 *
 * 注：底层 store 已做缓存 + pending 守门，此处只加 UI 副作用
 */
import { ElMessage } from 'element-plus'
import { useStrategyStore } from '../../../stores/strategy'

// status 映射（spec REQ-STRAT-005）
export const STATUS_LABEL = {
  active: '运行中',
  paused: '已暂停',
  stopped: '已停止',
}
export const STATUS_TYPE = {
  active: 'success',
  paused: 'warning',
  stopped: 'info',
}
// type 映射
export const TYPE_LABEL = {
  general: '普通策略',
  t0: 'T0 策略',
}
export const TYPE_TAG_TYPE = {
  general: 'info',
  t0: 'warning',
}

export function useStrategy() {
  const store = useStrategyStore()

  // ---- CRUD wrapper --------------------------------------------------
  async function refresh() {
    try {
      await store.loadStrategies()
    } catch (e) {
      ElMessage.error('加载策略失败：' + (e?.message || e))
    }
  }

  async function create(payload) {
    try {
      const strat = await store.createStrategy(payload)
      ElMessage.success('策略已创建')
      return strat
    } catch (e) {
      ElMessage.error('创建失败：' + (e?.response?.data?.detail?.msg || e?.message || e))
      return null
    }
  }

  async function update(id, patch) {
    try {
      const strat = await store.updateStrategy(id, patch)
      ElMessage.success('已保存')
      return strat
    } catch (e) {
      ElMessage.error('更新失败：' + (e?.response?.data?.detail?.msg || e?.message || e))
      return null
    }
  }

  async function remove(id) {
    try {
      await store.deleteStrategy(id)
      ElMessage.success('策略已删除')
      return true
    } catch (e) {
      ElMessage.error('删除失败：' + (e?.response?.data?.detail?.msg || e?.message || e))
      return false
    }
  }

  async function control(id, action) {
    try {
      const res = await store.controlStrategy(id, action)
      const label = { pause: '已暂停', resume: '已恢复', stop: '已停止', clear_now: '已请求清仓' }[action]
      ElMessage.success(label || '操作成功')
      return res
    } catch (e) {
      ElMessage.error('操作失败：' + (e?.response?.data?.detail?.msg || e?.message || e))
      return null
    }
  }

  return {
    store,
    refresh, create, update, remove, control,
    STATUS_LABEL, STATUS_TYPE, TYPE_LABEL, TYPE_TAG_TYPE,
  }
}
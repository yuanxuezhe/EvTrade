/**
 * BatchTasksTable.test.js — 批次内任务表格动态列 (v123, 6.4)
 *
 * 覆盖:
 * - 参数动态列由 schema key 驱动 (前几列)
 * - schema 为空时退化为 task.params 键并集 (按出现顺序)
 * - 固定结果列 (状态/PnL/指标) 存在
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import '../../setup-view'
import { mountView } from '../../setup-view'
import BatchTasksTable from '@/components/strategy/BatchTasksTable.vue'

function _mkTask(over = {}) {
  return {
    id: 1,
    params: { fast: 5, slow: 20 },
    status: 'finished',
    pnl: 123.4,
    backtest_metric_value: 1.2345,
    trades_count: 10,
    backtest_start_date: '20260101',
    backtest_end_date: '20260131',
    error_msg: null,
    ...over,
  }
}

const SCHEMA = [
  { key: 'fast', type: 'int', default: 5 },
  { key: 'slow', type: 'int', default: 20 },
]

// 取 el-table-column stub 的 data-label 列表 (动态列断言)
function _columnLabels(wrapper) {
  return wrapper.findAll('.el-tablecolumn').map((c) => c.attributes('data-label'))
}

describe('BatchTasksTable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('参数动态列来自 schema key (fast/slow 在前, 结果列在后)', () => {
    const wrapper = mountView(BatchTasksTable, {
      props: { tasks: [_mkTask()], schema: SCHEMA, selectedId: null },
    })
    const labels = _columnLabels(wrapper)
    // 动态参数列 + 固定结果列
    expect(labels).toContain('fast')
    expect(labels).toContain('slow')
    expect(labels.indexOf('fast')).toBeLessThan(labels.indexOf('状态'))
    expect(labels.indexOf('slow')).toBeLessThan(labels.indexOf('状态'))
    expect(labels).toContain('PnL')
    expect(labels).toContain('指标')
    expect(labels).toContain('成交笔数')
  })

  it('schema 为空时退化为 task.params 键并集 (按出现顺序)', () => {
    const tasks = [
      _mkTask({ id: 1, params: { a: 1 } }),
      _mkTask({ id: 2, params: { b: 2, a: 9 } }),
    ]
    const wrapper = mountView(BatchTasksTable, {
      props: { tasks, schema: [], selectedId: null },
    })
    const labels = _columnLabels(wrapper)
    // a 先出现于 task1 → 排在 b 前
    expect(labels.indexOf('a')).toBeGreaterThanOrEqual(0)
    expect(labels.indexOf('b')).toBeGreaterThanOrEqual(0)
    expect(labels.indexOf('a')).toBeLessThan(labels.indexOf('b'))
  })

  it('无 schema 无任务 params 时只渲染固定结果列, 不崩', () => {
    const wrapper = mountView(BatchTasksTable, {
      props: { tasks: [_mkTask({ params: {} })], schema: [], selectedId: null },
    })
    expect(wrapper.find('[data-el="batch-tasks-table"]').exists()).toBe(true)
  })
})

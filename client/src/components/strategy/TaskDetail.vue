<!--
  TaskDetail.vue — 任务详情面板 (v123, 从旧 ScriptTask 抽取)

  展示单个 strategy_task 的回测/实盘详情: 摘要 → 回测结果 → 最佳参数 →
  权益曲线 → 执行详情子 Tab (信号流 / 进度 / 交易明细 / 执行日志)。
  Props:
    - task: Object   完整 task (getTask 返回)
    - strategyName: String  所属策略名 (标题用)
  Emits:
    - none
-->
<template>
  <div class="td-wrap" data-el="task-detail">
    <div class="td-title">
      {{ strategyName }} · 任务 #{{ task.id }}
      <el-tag size="small" :type="task.mode === 'live' ? 'danger' : 'info'">
        {{ task.mode === 'live' ? '实盘' : '回测' }}
      </el-tag>
    </div>

    <el-descriptions :column="3" border size="small" class="td-summary">
      <el-descriptions-item label="状态">
        <el-tag size="small" :type="_statusType(task.status)">{{ _statusLabel(task.status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="标的">{{ task.stock_code }}</el-descriptions-item>
      <el-descriptions-item label="周期">{{ task.period || '-' }}</el-descriptions-item>

      <el-descriptions-item v-if="task.status === 'running' && task.progress" label="进度" :span="3">
        <div class="td-progress-panel">
          <el-progress
            :percentage="progressPercent"
            :status="progressStatus"
            :stroke-width="14"
            text-inside
            :format="() => progressText"
            data-el="td-progress-bar"
          />
          <div class="td-progress-detail">
            <el-tag size="small" :type="progressPhaseTagType" effect="dark">{{ progressPhaseLabel }}</el-tag>
            <span class="td-progress-msg">{{ task.progress.msg || '' }}</span>
            <span class="td-progress-time">最后更新: {{ task.progress.updated_at || '' }}</span>
          </div>
        </div>
      </el-descriptions-item>

      <el-descriptions-item label="PnL">
        <span :class="task.pnl > 0 ? 'up' : task.pnl < 0 ? 'down' : ''">
          {{ (task.pnl || 0).toFixed(2) }}
        </span>
      </el-descriptions-item>
      <el-descriptions-item label="成交笔数">{{ task.trades_count || 0 }}</el-descriptions-item>
      <el-descriptions-item label="回测区间">
        <span v-if="task.backtest_start_date">{{ task.backtest_start_date }} ~ {{ task.backtest_end_date }}</span>
        <span v-else class="td-muted">—</span>
      </el-descriptions-item>

      <el-descriptions-item v-if="task.status === 'failed' && task.error_msg" label="错误" :span="3">
        <pre class="td-error">{{ task.error_msg }}</pre>
      </el-descriptions-item>
    </el-descriptions>

    <template v-if="task.mode === 'backtest' && task.backtest_result">
      <h4>回测结果</h4>
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="PnL">
          <span :class="(task.backtest_result.best?.pnl || 0) > 0 ? 'up' : 'down'">
            {{ (task.backtest_result.best?.pnl || 0).toFixed(2) }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="收益率">
          {{ ((task.backtest_result.best?.pnl_pct || 0) * 100).toFixed(2) }}%
        </el-descriptions-item>
        <el-descriptions-item label="胜率">
          {{ ((task.backtest_result.best?.win_rate || 0) * 100).toFixed(1) }}%
        </el-descriptions-item>
        <el-descriptions-item label="成交笔数">
          {{ task.backtest_result.best?.trades_count || 0 }}
        </el-descriptions-item>
      </el-descriptions>

      <h4>参数</h4>
      <div class="td-params">
        <el-tag
          v-for="(v, k) in (task.params || {})"
          :key="k"
          size="small"
          effect="plain"
          type="info"
          style="margin-right: 4px"
        >{{ k }}={{ v }}</el-tag>
        <span v-if="!Object.keys(task.params || {}).length" class="td-muted">—</span>
      </div>

      <h4>权益曲线</h4>
      <div ref="chartRef" class="td-chart"></div>

      <h4>执行详情</h4>
      <el-tabs v-model="subTab" class="td-tabs" data-el="td-tabs">
        <el-tab-pane label="信号流" name="signals">
          <div class="td-signals-filter">
            <el-radio-group v-model="signalFilter" size="small" @change="loadSignals" data-el="td-signal-filter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="BUY">买入</el-radio-button>
              <el-radio-button value="SELL">卖出</el-radio-button>
              <el-radio-button value="INFO">信号</el-radio-button>
            </el-radio-group>
            <span class="td-signals-count">
              共 {{ signalData.total_signals || 0 }} 条
              <span v-if="signalData.truncated" class="td-muted">(已截断)</span>
            </span>
          </div>
          <el-table :data="signalData.signals || []" size="small" border max-height="400" data-el="td-signals-table">
            <el-table-column label="时间" prop="stime" width="140" />
            <el-table-column label="类型" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="_signalType(row.signal_type || row.type)">{{ row.signal_type || row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="价格" prop="price" width="80">
              <template #default="{ row }">
                <span v-if="row.price !== undefined">{{ _fmtPrice(row.price, row.stock_code) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="触发原因 / 详情" min-width="200">
              <template #default="{ row }">
                <span>{{ row.msg }}</span>
                <div v-if="row.indicators" class="td-signal-indicators">
                  <el-tag v-for="(v, k) in row.indicators" :key="k" size="small" type="info">
                    {{ k }}={{ typeof v === 'number' ? v.toFixed(4) : v }}
                  </el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="140">
              <template #default="{ row }">
                <span v-if="row.state" class="td-signal-state">
                  持仓 {{ row.state.position || 0 }} 股
                  <span v-if="row.state.cash !== undefined">· 现金 {{ Number(row.state.cash).toFixed(2) }}</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="盈亏" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.pnl !== undefined" :class="row.pnl > 0 ? 'up' : row.pnl < 0 ? 'down' : ''">
                  {{ Number(row.pnl).toFixed(2) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`进度 (${progressData.length} bar)`" name="progress">
          <div class="td-progress-summary" v-if="progressData.length">
            <el-tag>总 bar 数: {{ progressData.length }}</el-tag>
            <el-tag type="info">权益范围: {{ progressMinEquity.toFixed(2) }} ~ {{ progressMaxEquity.toFixed(2) }}</el-tag>
            <el-tag type="success">期末权益: {{ progressData[progressData.length - 1]?.equity?.toFixed(2) }}</el-tag>
          </div>
          <el-table :data="progressData" size="small" border max-height="400" data-el="td-progress-table">
            <el-table-column label="#" prop="bar_idx" width="60" />
            <el-table-column label="时间" prop="stime" width="140" />
            <el-table-column label="收盘" prop="close" width="80">
              <template #default="{ row }">{{ Number(row.close).toFixed(4) }}</template>
            </el-table-column>
            <el-table-column label="持仓" prop="position" width="80" align="right" />
            <el-table-column label="现金" width="100" align="right">
              <template #default="{ row }">{{ Number(row.cash).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="权益" min-width="100" align="right">
              <template #default="{ row }">
                <span :class="row.equity > (row.cash + row.position * row.close) ? 'up' : ''">
                  {{ Number(row.equity).toFixed(2) }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="交易明细" name="trades">
          <el-table :data="task.backtest_result.best?.trades || []" size="small" border>
            <el-table-column label="时间" prop="stime" width="140" />
            <el-table-column label="方向" width="60">
              <template #default="{ row }">
                <el-tag size="small" :type="row.side === 'BUY' ? 'success' : 'danger'">{{ row.side }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="价格" prop="price" width="80" />
            <el-table-column label="数量" prop="volume" width="80" />
            <el-table-column label="盈亏" width="100" align="right">
              <template #default="{ row }">
                <span :class="row.pnl > 0 ? 'up' : row.pnl < 0 ? 'down' : ''">{{ (row.pnl || 0).toFixed(2) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`执行日志 (${executionLog.length})`" name="execution">
          <div v-if="executionLog.length" class="td-exec-summary">
            <el-tag>总阶段: {{ executionLog.length }}</el-tag>
            <el-tag type="info">耗时: {{ executionLog[executionLog.length - 1]?.elapsed_ms || 0 }} ms</el-tag>
            <el-tag type="success">bars: {{ executionLog.filter(e => e.phase === 'bar').length }}</el-tag>
          </div>
          <el-input
            v-model="executionFilter"
            placeholder="过滤 (phase / msg / bar_idx)"
            size="small"
            clearable
            class="td-exec-filter"
          />
          <el-table :data="filteredExecutionLog" size="small" border max-height="500" data-el="td-exec-table">
            <el-table-column label="耗时" prop="elapsed_ms" width="80">
              <template #default="{ row }"><code class="td-exec-ms">{{ row.elapsed_ms }}ms</code></template>
            </el-table-column>
            <el-table-column label="阶段" prop="phase" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="_phaseType(row.phase)">{{ row.phase }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="bar_idx" prop="bar_idx" width="80">
              <template #default="{ row }"><span v-if="row.bar_idx !== undefined">{{ row.bar_idx }}</span></template>
            </el-table-column>
            <el-table-column label="消息" prop="msg" min-width="380" />
            <el-table-column label="stime" prop="stime" width="140" />
            <el-table-column label="close" prop="close" width="80">
              <template #default="{ row }"><span v-if="row.close !== undefined">{{ Number(row.close).toFixed(4) }}</span></template>
            </el-table-column>
            <el-table-column label="持仓" prop="position" width="60">
              <template #default="{ row }"><span v-if="row.position !== undefined">{{ row.position }}</span></template>
            </el-table-column>
            <el-table-column label="权益" prop="equity" width="100" align="right">
              <template #default="{ row }"><span v-if="row.equity !== undefined">{{ Number(row.equity).toFixed(2) }}</span></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </template>

    <template v-else-if="task.mode === 'live'">
      <h4>实盘运行</h4>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="当前持仓">
          <span v-for="(vol, code) in (task.positions || {})" :key="code">{{ code }}: {{ vol }} 股 </span>
          <span v-if="!task.positions || !Object.keys(task.positions).length" class="td-muted">无</span>
        </el-descriptions-item>
        <el-descriptions-item label="累计 PnL">
          <span :class="task.pnl > 0 ? 'up' : task.pnl < 0 ? 'down' : ''">{{ (task.pnl || 0).toFixed(2) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="成交笔数">{{ task.trades_count || 0 }}</el-descriptions-item>
      </el-descriptions>
      <h4>实盘信号流</h4>
      <el-table :data="signalData.signals || []" size="small" border max-height="400" data-el="td-live-signals-table">
        <el-table-column label="时间" prop="stime" width="140" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="_signalType(row.signal_type || row.type)">{{ row.signal_type || row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="价格" prop="price" width="80">
          <template #default="{ row }"><span v-if="row.price !== undefined">{{ Number(row.price).toFixed(4) }}</span></template>
        </el-table-column>
        <el-table-column label="详情" prop="msg" min-width="300" />
        <el-table-column label="单号" prop="order_no" width="120">
          <template #default="{ row }"><code v-if="row.order_no" class="td-order-no">{{ row.order_no }}</code></template>
        </el-table-column>
      </el-table>
    </template>

    <template v-else-if="task.error_msg">
      <h4>错误</h4>
      <pre class="td-error">{{ task.error_msg }}</pre>
    </template>

    <template v-else>
      <el-empty description="任务尚未运行" />
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { scriptStrategyApi } from '../../api/script_strategy'
import { formatPrice } from '../../composables/usePricePrecision'

const props = defineProps({
  task: { type: Object, default: null },
  strategyName: { type: String, default: '' },
})

const subTab = ref('signals')
const signalFilter = ref('')
const signalData = ref({ signals: [], progress: [], total_signals: 0, truncated: false })
const progressData = ref([])
const executionFilter = ref('')
const chartRef = ref(null)
let chart = null

// ──── 进度面板 computeds ────
const progressPercent = computed(() => {
  const p = props.task?.progress
  if (!p) return 0
  if (p.pct !== undefined && p.pct !== null) return Math.round(p.pct)
  if (p.total) return Math.round((p.current || 0) / p.total * 100)
  if (p.total_bars) return Math.round((p.bar_idx || 0) / p.total_bars * 100)
  return 0
})
const progressText = computed(() => {
  const p = props.task?.progress
  if (!p) return ''
  if (p.pct !== undefined && p.pct !== null) return `${Math.round(p.pct)}%`
  if (p.total) return `${p.current || 0}/${p.total}`
  if (p.total_bars) return `${p.bar_idx || 0}/${p.total_bars}`
  return ''
})
const progressStatus = computed(() => {
  const p = props.task?.progress
  if (!p) return ''
  if (p.phase === 'done') return 'success'
  if (p.phase === 'failed') return 'exception'
  return ''
})
const PHASE_LABELS = {
  start: { label: '启动', type: 'info' },
  load_script: { label: '📥 加载脚本', type: 'info' },
  build_cerebro: { label: '🔧 构造引擎', type: 'info' },
  running: { label: '🔄 回测中', type: 'primary' },
  writing_result: { label: '💾 写结果', type: 'info' },
  live_running: { label: '🟢 实盘运行中', type: 'success' },
  done: { label: '✅ 完成', type: 'success' },
  failed: { label: '❌ 失败', type: 'danger' },
}
const progressPhaseLabel = computed(() => {
  const phase = props.task?.progress?.phase
  return PHASE_LABELS[phase]?.label || phase || '⏳ 准备中'
})
const progressPhaseTagType = computed(() => {
  const phase = props.task?.progress?.phase
  return PHASE_LABELS[phase]?.type || 'info'
})

const progressMinEquity = computed(() => progressData.value.length
  ? Math.min(...progressData.value.map(p => p.equity || 0)) : 0)
const progressMaxEquity = computed(() => progressData.value.length
  ? Math.max(...progressData.value.map(p => p.equity || 0)) : 0)

const executionLog = computed(() => props.task?.backtest_result?.execution_log || [])
const filteredExecutionLog = computed(() => {
  const kw = executionFilter.value.trim().toLowerCase()
  if (!kw) return executionLog.value
  return executionLog.value.filter(e => {
    if (String(e.phase || '').toLowerCase().includes(kw)) return true
    if (String(e.msg || '').toLowerCase().includes(kw)) return true
    if (e.bar_idx !== undefined && String(e.bar_idx).includes(kw)) return true
    return false
  })
})

// ──── 状态/信号映射 ────
function _statusType(s) {
  return {
    queued: 'info', running: 'warning', finished: 'success',
    failed: 'danger', stopped: 'primary',
  }[s] || 'primary'
}
function _statusLabel(s) {
  return {
    queued: '排队中', running: '运行中', finished: '完成',
    failed: '失败', stopped: '已停',
  }[s] || (s || '—')
}
function _signalType(t) {
  return {
    BUY: 'success', SELL: 'danger', INFO: 'info', WARN: 'warning',
    STOP: 'primary', TP: 'primary', ERROR: 'danger',
  }[t] || 'primary'
}
function _phaseType(p) {
  return {
    start: 'primary', sandbox_ok: 'success', sandbox_err: 'danger',
    on_init_start: 'primary', on_init_done: 'success', on_init_err: 'danger',
    bar: 'info', on_bar_err: 'danger',
    on_finish_start: 'primary', on_finish_done: 'success', on_finish_err: 'warning',
    done: 'success', empty_bars: 'warning',
  }[p] || 'primary'
}
function _fmtPrice(v, code) {
  try { return formatPrice(v, code) } catch { return Number(v).toFixed(4) }
}

// ──── 信号加载 ────
async function loadSignals() {
  if (!props.task?.id) return
  try {
    const data = await scriptStrategyApi.getTaskSignals(props.task.id, {
      type: signalFilter.value || null, limit: 500,
    })
    signalData.value = data
    progressData.value = data.progress || []
  } catch (e) { /* ignored */ }
}

// ──── 权益曲线 (echarts) ────
function _disposeChart() {
  if (chart) { chart.dispose(); chart = null }
}
function renderChart() {
  if (!chartRef.value || !props.task?.backtest_result?.best?.equity_curve) return
  const best = props.task.backtest_result.best
  const eq = best.equity_curve
  const trades = best.trades || []
  const tradeBuyData = []
  const tradeSellData = []
  for (const t of trades) {
    const point = { name: t.stime, value: [t.stime, t.price] }
    if (t.side === 'BUY') tradeBuyData.push(point)
    else if (t.side === 'SELL') tradeSellData.push(point)
  }
  const closeSeries = (best.progress_log || []).map(p => ({ stime: p.stime, value: p.close }))
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    legend: { top: 0, left: 'center', data: ['权益', '收盘价', 'BUY', 'SELL'] },
    grid: { left: 60, right: 60, top: 40, bottom: 60 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 20 }],
    xAxis: { type: 'category', data: eq.map(e => e.stime), splitLine: { show: false } },
    yAxis: [
      { type: 'value', name: '权益', position: 'left', scale: true },
      { type: 'value', name: '价格', position: 'right', scale: true, splitLine: { show: false } },
    ],
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'cross' },
      formatter: (params) => params.map(p => {
        let line = p.marker + p.seriesName + ': ' + (p.value[1]?.toFixed?.(2) || p.value[1])
        if (p.seriesName === 'BUY' || p.seriesName === 'SELL') line += ' (' + (p.data.side || '') + ')'
        return line
      }).join('<br/>'),
    },
    series: [
      { name: '权益', data: eq.map(e => e.equity), type: 'line', smooth: true, yAxisIndex: 0, areaStyle: { opacity: 0.15 } },
      ...(closeSeries.length ? [{ name: '收盘价', data: closeSeries, type: 'line', yAxisIndex: 1, showSymbol: false, lineStyle: { type: 'dashed', width: 1, opacity: 0.5 } }] : []),
      { name: 'BUY', data: tradeBuyData, type: 'scatter', yAxisIndex: 1, symbol: 'triangle', symbolSize: 12, itemStyle: { color: '#67c23a' } },
      { name: 'SELL', data: tradeSellData, type: 'scatter', yAxisIndex: 1, symbol: 'triangle', symbolRotate: 180, symbolSize: 12, itemStyle: { color: '#f56c6c' } },
    ],
  })
}

watch(() => props.task?.id, async (id) => {
  _disposeChart()
  signalData.value = { signals: [], progress: [], total_signals: 0, truncated: false }
  progressData.value = []
  executionFilter.value = ''
  subTab.value = 'signals'
  if (id == null) return
  await nextTick()
  renderChart()
  await loadSignals()
}, { immediate: true })

// task 对象更新 (轮询/ws 刷新 progress) 但 id 不变 → 仅重绘图表(如结果出现)
watch(() => props.task, async () => {
  if (props.task?.id) {
    await nextTick()
    renderChart()
  }
})

onBeforeUnmount(() => _disposeChart())
</script>

<style scoped>
.td-wrap { padding: 4px; }
.td-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; display: flex; gap: 8px; align-items: center; }
.td-summary { margin-bottom: 16px; }
.td-muted { color: var(--text-placeholder); }
.up { color: var(--color-up, #f56c6c); font-weight: 600; }
.down { color: var(--color-down, #67c23a); font-weight: 600; }
.td-error {
  color: var(--color-down, #f56c6c); background: var(--bg-base);
  padding: 8px; border-radius: 4px; font-size: 12px; white-space: pre-wrap;
  margin: 0;
}
.td-params { margin-bottom: 8px; }
.td-wrap h4 {
  font-size: 13px; margin: 16px 0 8px; color: var(--text-secondary);
  text-transform: uppercase; letter-spacing: 0.5px;
}
.td-chart { width: 100%; height: 250px; border: 1px solid var(--border-light); border-radius: 4px; background: var(--bg-base); }
.td-tabs { margin-top: 8px; }
.td-signals-filter { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.td-signals-count { font-size: 12px; color: var(--text-secondary); margin-left: auto; }
.td-signal-indicators { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.td-signal-state { font-size: 12px; color: var(--text-secondary); }
.td-order-no { font-family: var(--font-mono, monospace); font-size: 11px; background: var(--bg-base); padding: 1px 4px; border-radius: 2px; }
.td-progress-summary { display: flex; gap: 8px; margin-bottom: 8px; }
.td-progress-panel { width: 100%; }
.td-progress-detail { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 8px; font-size: 13px; color: var(--color-text-secondary); }
.td-progress-msg { flex: 1; min-width: 200px; color: var(--color-text-primary); }
.td-progress-time { font-size: 12px; color: var(--color-text-tertiary); margin-left: auto; }
.td-exec-summary { display: flex; gap: 8px; margin-bottom: 8px; }
.td-exec-filter { margin-bottom: 8px; }
.td-exec-ms { font-family: var(--font-mono, monospace); font-size: 11px; background: var(--bg-base); padding: 1px 4px; border-radius: 2px; }
</style>

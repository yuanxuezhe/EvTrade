<!--
  BacktestForm.vue — 策略回测表单 (替代旧 SweepForm)

  职责: 让用户配置一次回测 (单次 / 参数扫描), 类型驱动渲染 params_schema。
  Props:
    - schema: Array<{key, type, min, max, step, default, values}>  脚本 params_schema
    - visible: Boolean  抽屉显隐
    - stockCode: String  策略绑定标的 (只读展示; 空 → 存量 NULL 策略, 用输入框兜底)
  Emits:
    - update:visible(Boolean)
    - submit({ mode, stock_code, backtest_start_date, backtest_end_date,
               params | param_ranges, period, metric, concurrency })
-->
<template>
  <el-drawer
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="回测策略"
    size="560px"
    append-to-body
    destroy-on-close
    data-el="backtest-form"
  >
    <el-form label-width="110px" size="small" class="bf-form">
      <el-form-item label="运行模式">
        <el-radio-group v-model="mode" size="small" data-el="bf-mode">
          <el-radio-button value="single">单次回测</el-radio-button>
          <el-radio-button value="sweep">参数扫描</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="标的">
        <template v-if="stockCode">
          <span class="bf-stock-bound" data-el="bf-stock">{{ stockCode }}</span>
        </template>
        <el-input v-else v-model="stock_code" placeholder="如 600519.SH" data-el="bf-stock" />
      </el-form-item>

      <el-form-item label="回测起止">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYYMMDD"
          range-separator="~"
          start-placeholder="开始"
          end-placeholder="结束"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="K线周期">
        <el-select v-model="period" style="width: 100%">
          <el-option label="1分钟" value="1m" />
          <el-option label="5分钟" value="5m" />
          <el-option label="15分钟" value="15m" />
          <el-option label="30分钟" value="30m" />
          <el-option label="1小时" value="1h" />
          <el-option label="1日" value="1d" />
        </el-select>
      </el-form-item>

      <el-divider content-position="left">{{ mode === 'single' ? '参数 (单次)' : '参数扫描' }}</el-divider>

      <!-- 单次回测: 参数按 schema 类型渲染, 默认值=default -->
      <template v-if="mode === 'single'">
        <el-form-item v-for="p in schema" :key="p.key" :label="p.key">
          <el-input-number
            v-if="p.type === 'int' || p.type === 'float'"
            v-model="singleParams[p.key]"
            :step="p.step || 1"
            :min="p.min"
            :max="p.max"
            :precision="p.type === 'float' ? 4 : 0"
            style="width: 100%"
            data-el="bf-single-param"
          />
          <el-select v-else-if="p.type === 'choice'" v-model="singleParams[p.key]" style="width: 100%">
            <el-option v-for="v in (p.values || [])" :key="v" :label="String(v)" :value="v" />
          </el-select>
          <el-input v-else v-model="singleParams[p.key]" data-el="bf-single-param" />
        </el-form-item>
      </template>

      <!-- 参数扫描: 类型驱动 (int/float → 起止+步长; choice → 值列表; string → 固定) -->
      <template v-else>
        <div v-for="p in sweepRows" :key="p.key" class="bf-sweep-row">
          <div class="bf-sweep-head">
            <el-checkbox v-model="p.enabled" data-el="bf-sweep-enable">
              <span class="bf-sweep-key">{{ p.key }}</span>
              <el-tag size="small" effect="plain">{{ p.type }}</el-tag>
            </el-checkbox>
            <span v-if="!p.enabled" class="bf-sweep-lock">不参与, 用默认值</span>
          </div>

          <template v-if="p.enabled">
            <!-- int / float: 起止 + 步长 (含端点) -->
            <div v-if="p.type === 'int' || p.type === 'float'" class="bf-sweep-range">
              <el-input-number v-model="p.start" :step="p.step || 1" placeholder="起" data-el="bf-sweep-start" />
              <span class="bf-sweep-sep">~</span>
              <el-input-number v-model="p.end" :step="p.step || 1" placeholder="止" data-el="bf-sweep-end" />
              <span class="bf-sweep-sep">步长</span>
              <el-input-number v-model="p.step" :min="0.0001" placeholder="步" data-el="bf-sweep-step" />
            </div>
            <!-- choice: 逗号分隔值列表 -->
            <el-input
              v-else-if="p.type === 'choice'"
              v-model="p.valuesStr"
              placeholder="逗号分隔值, 如 SMA,EMA"
              data-el="bf-sweep-values"
            />
            <!-- string: 固定值 -->
            <el-input v-else v-model="p.value" placeholder="固定值" data-el="bf-sweep-value" />
          </template>
        </div>

        <el-form inline size="small" class="bf-meta">
          <el-form-item label="排序指标">
            <el-select v-model="metric" style="width: 130px" data-el="bf-metric">
              <el-option label="Sharpe" value="sharpe" />
              <el-option label="总收益" value="total_return" />
              <el-option label="Calmar" value="calmar" />
            </el-select>
          </el-form-item>
          <el-form-item label="并发">
            <el-input-number v-model="concurrency" :min="1" :max="16" />
          </el-form-item>
        </el-form>

        <div class="bf-summary" :class="_comboClass">
          <span>预计组合数: <strong>{{ comboSize }}</strong></span>
          <el-tag v-if="comboSize > HARD_LIMIT" type="danger" effect="dark" size="small">
            ⛔ 超过硬上限 {{ HARD_LIMIT }}, 无法提交
          </el-tag>
          <el-tag v-else-if="comboSize > SOFT_WARN" type="warning" effect="dark" size="small">
            ⚠️ 超过软警告 {{ SOFT_WARN }}, 建议缩小网格
          </el-tag>
        </div>
      </template>

      <div class="bf-actions">
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="onSubmit" data-el="bf-submit">
          {{ mode === 'single' ? '开始回测' : '开始扫描' }}
        </el-button>
      </div>
    </el-form>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  schema: { type: Array, default: () => [] },
  visible: { type: Boolean, default: false },
  stockCode: { type: String, default: '' },  // 策略绑定标的 (只读展示)
})
const emit = defineEmits(['update:visible', 'submit'])

const SOFT_WARN = 64
const HARD_LIMIT = 512

const submitting = ref(false)
const mode = ref('single')
const stock_code = ref('')
const dateRange = ref(null)
const period = ref('1d')
const metric = ref('sharpe')
const concurrency = ref(2)
const singleParams = ref({})
const sweepRows = ref([])

// 重置表单 (destroy-on-close 下抽屉重开会重建, 这里兜底)
watch(() => props.visible, (v) => { if (v) _init() })
function _init() {
  mode.value = 'single'
  stock_code.value = ''
  dateRange.value = null
  period.value = '1d'
  metric.value = 'sharpe'
  concurrency.value = 2
  singleParams.value = {}
  for (const p of props.schema) {
    singleParams.value[p.key] = p.default
  }
  sweepRows.value = (props.schema || []).map((p) => {
    if (p.type === 'int' || p.type === 'float') {
      const hasRange = p.min !== undefined && p.max !== undefined && p.step
      return {
        key: p.key,
        type: p.type,
        enabled: hasRange,                       // 有 min/max/step 默认参与扫描
        start: p.min !== undefined ? p.min : p.default,
        end: p.max !== undefined ? p.max : (p.default !== undefined ? p.default : p.min),
        step: p.step || 1,
      }
    }
    if (p.type === 'choice') {
      return { key: p.key, type: p.type, enabled: false, valuesStr: (p.values || []).join(',') }
    }
    return { key: p.key, type: 'string', enabled: false, value: p.default ?? '' }
  })
}

// 展开单参取值序列 (与后端 _expand_values 对齐: int/float 含端点, int 取整)
function _expandRow(row) {
  if (row.type === 'int' || row.type === 'float') {
    if (row.start === undefined || row.end === undefined || !row.step) return []
    const vals = []
    let v = Number(row.start)
    const end = Number(row.end)
    const step = Number(row.step)
    if (step <= 0) return []
    while (v <= end) {
      vals.push(row.type === 'int' ? Math.round(v) : Math.round(v * 1e10) / 1e10)
      v += step
    }
    if (vals.length && vals[vals.length - 1] !== end) vals.push(end)
    return vals
  }
  if (row.type === 'choice') {
    return (row.valuesStr || '').split(',').map((s) => s.trim()).filter(Boolean)
  }
  return [row.value]
}

const comboSize = computed(() => {
  const active = sweepRows.value.filter((r) => r.enabled)
  if (!active.length) return 1
  let n = 1
  for (const r of active) {
    const vals = _expandRow(r)
    if (!vals.length) return 0
    n *= vals.length
  }
  return n
})

const canSubmit = computed(() => {
  if (mode.value === 'single') return true
  return comboSize.value > 0 && comboSize.value <= HARD_LIMIT
})

const _comboClass = computed(() => {
  if (comboSize.value > HARD_LIMIT) return 'bf-combo-bad'
  if (comboSize.value > SOFT_WARN) return 'bf-combo-warn'
  return ''
})

function onSubmit() {
  if (!dateRange.value || !dateRange.value[0] || !dateRange.value[1]) {
    ElMessage.warning('请选择回测起止日期')
    return
  }
  const payload = {
    mode: mode.value,
    backtest_start_date: dateRange.value[0],
    backtest_end_date: dateRange.value[1],
    period: period.value,
  }
  // 标的由策略绑定; 仅存量 NULL 策略用输入兜底
  if (stock_code.value) payload.stock_code = stock_code.value
  if (mode.value === 'single') {
    payload.params = { ...singleParams.value }
  } else {
    payload.param_ranges = {}
    for (const r of sweepRows.value) {
      if (!r.enabled) continue
      if (r.type === 'int' || r.type === 'float') {
        payload.param_ranges[r.key] = { type: r.type, start: r.start, end: r.end, step: r.step }
      } else if (r.type === 'choice') {
        payload.param_ranges[r.key] = { type: 'choice', values: _expandRow(r) }
      } else {
        payload.param_ranges[r.key] = { type: 'string', value: r.value }
      }
    }
    if (!Object.keys(payload.param_ranges).length) {
      ElMessage.warning('参数扫描至少启用 1 个参数')
      return
    }
    payload.metric = metric.value
    payload.concurrency = concurrency.value
  }
  submitting.value = true
  emit('submit', payload)
  setTimeout(() => { submitting.value = false }, 500)
}
</script>

<style scoped>
.bf-form { padding: 4px 0; }
.bf-sweep-row {
  padding: 10px;
  margin-bottom: 10px;
  background: #f7f8fa;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}
.bf-sweep-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.bf-sweep-key { font-weight: 600; margin-right: 6px; }
.bf-sweep-lock { color: #909399; font-size: 12px; margin-left: auto; }
.bf-sweep-range {
  display: flex;
  align-items: center;
  gap: 6px;
}
.bf-sweep-sep { color: #909399; font-size: 12px; }
.bf-meta { margin-top: 12px; }
.bf-summary {
  margin-top: 8px;
  padding: 10px 12px;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 13px;
}
.bf-combo-warn { color: #e6a23c; }
.bf-combo-bad { color: #f56c6c; }
.bf-actions { margin-top: 16px; text-align: right; }
.bf-stock-bound { font-weight: 600; color: var(--text-secondary); }
</style>

<!--
  SweepForm.vue — 参数扫描配置表单 (script-strategy v122+)

  职责: 让用户配置 param_grid + metric, 实时算组合数 + 警告, 提交触发 scan。
  Props:
    - schema: Array<{key, type, min, max, step, default, values}>  脚本的 params_schema
    - taskId: Number   被 sweep 的 task id
  Emits:
    - submit({param_grid, metric, select_top_n, concurrency})
    - cancel()
-->
<template>
  <div class="sf-wrap" data-el="sweep-form">
    <p class="sf-desc">参数扫描: 对 schema 中每个参数选扫描值(逗号分隔), 锁定则不参与笛卡尔积。</p>

    <el-table :data="rows" size="small" border>
      <el-table-column label="参数" prop="key" width="100" />
      <el-table-column label="类型" prop="type" width="80">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ row.type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="扫描值 (逗号分隔)" min-width="220">
        <template #default="{ row }">
          <el-input
            v-model="row.scanStr"
            size="small"
            :placeholder="_placeholderFor(row)"
            :disabled="row.locked"
            @change="onScanStrChange(row)"
            data-el="sf-scan-input"
          />
          <span class="sf-hint" v-if="!row.locked">{{ row.values?.length || 0 }} 个值</span>
        </template>
      </el-table-column>
      <el-table-column label="锁定(不参与)" width="100" align="center">
        <template #default="{ row }">
          <el-checkbox v-model="row.locked" @change="onLockChange(row)" data-el="sf-lock">
            锁定
          </el-checkbox>
        </template>
      </el-table-column>
      <el-table-column label="默认值" width="100">
        <template #default="{ row }">{{ _defaultLabel(row) }}</template>
      </el-table-column>
    </el-table>

    <el-form :inline="true" size="small" class="sf-meta">
      <el-form-item label="排序指标">
        <el-select v-model="metric" style="width: 140px" data-el="sf-metric">
          <el-option label="Sharpe" value="sharpe" />
          <el-option label="总收益" value="total_return" />
          <el-option label="Calmar" value="calmar" />
        </el-select>
      </el-form-item>
      <el-form-item label="并发">
        <el-input-number v-model="concurrency" :min="1" :max="8" />
      </el-form-item>
      <el-form-item label="Top N">
        <el-input-number v-model="selectTopN" :min="1" :max="10" />
      </el-form-item>
    </el-form>

    <div class="sf-summary">
      <span>预计组合数: <strong :class="_comboClass">{{ comboSize }}</strong></span>
      <el-tag v-if="comboSize > HARD_LIMIT" type="danger" effect="dark" size="small">
        ⛔ 超过硬上限 {{ HARD_LIMIT }}, 无法提交
      </el-tag>
      <el-tag v-else-if="comboSize > SOFT_WARN" type="warning" effect="dark" size="small">
        ⚠️ 超过软警告 {{ SOFT_WARN }}, 建议缩小网格
      </el-tag>
    </div>

    <div class="sf-actions">
      <el-button @click="$emit('cancel')">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="onSubmit" data-el="sf-submit">
        开始扫描
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  schema: { type: Array, default: () => [] },
  taskId: { type: Number, required: true },
})

const emit = defineEmits(['submit', 'cancel'])

const SOFT_WARN = 64
const HARD_LIMIT = 512

const submitting = ref(false)
const metric = ref('sharpe')
const concurrency = ref(2)
const selectTopN = ref(1)

// schema → 行: 每字段 { key, type, default, min, max, step, values, valuesStr(扫描值), locked }
// 默认: 锁定(只 default), 即不参与笛卡尔积
function _initRows(schema) {
  return (schema || []).map((p) => {
    // 默认扫描值: 若有 min/max/step 推一个最小3值的范围, 否则用 default
    let defaultScan = []
    if (p.type === 'choice' && Array.isArray(p.values)) {
      defaultScan = p.values
    } else if (p.min !== undefined && p.max !== undefined && p.step) {
      // 生成 3 个值: min, min+step, max
      const a = Number(p.min), b = Number(p.max), s = Number(p.step)
      const mid = Math.round(((a + b) / 2) / s) * s
      defaultScan = [a, mid, b].filter((v, i, arr) => arr.indexOf(v) === i)
    } else {
      defaultScan = [p.default]
    }
    return {
      ...p,
      values: defaultScan,
      scanStr: defaultScan.join(','),
      locked: defaultScan.length <= 1,  // 单值字段默认锁定
    }
  })
}

const rows = ref(_initRows(props.schema))
watch(() => props.schema, (v) => { rows.value = _initRows(v) })

// 解析扫描值字符串
function onScanStrChange(row) {
  const parts = (row.scanStr || '').split(',').map((s) => s.trim()).filter(Boolean)
  if (row.type === 'int') {
    row.values = parts.map((s) => Number.parseInt(s, 10)).filter((n) => !Number.isNaN(n))
  } else if (row.type === 'float') {
    row.values = parts.map((s) => Number.parseFloat(s)).filter((n) => !Number.isNaN(n))
  } else if (row.type === 'choice') {
    // choice 直接用 schema.values
    row.values = row.values  // 不变
  }
}

// 锁定切换: 解锁时若 values 空, 恢复默认扫描值
function onLockChange(row) {
  if (!row.locked && (!row.values || row.values.length === 0)) {
    row.scanStr = String(row.default)
    onScanStrChange(row)
  }
}

function _placeholderFor(row) {
  if (row.type === 'choice') return `${row.values?.length || 0} 个值(锁定)`
  if (row.min !== undefined && row.max !== undefined) return `e.g. ${row.min},${((row.min + row.max) / 2).toFixed(1)},${row.max}`
  return '逗号分隔数字'
}

function _defaultLabel(row) {
  if (row.type === 'choice') return Array.isArray(row.values) ? row.values.join(' / ') : '—'
  return row.default
}

// 笛卡尔积计数(锁定字段不参与)
const comboSize = computed(() => {
  const scanFields = rows.value.filter((r) => !r.locked && r.values?.length > 0)
  if (scanFields.length === 0) return 1  // 全部锁定 → 1 个组合
  let n = 1
  for (const r of scanFields) n *= r.values.length
  return n
})

const _comboClass = computed(() => {
  if (comboSize.value > HARD_LIMIT) return 'sf-combo-bad'
  if (comboSize.value > SOFT_WARN) return 'sf-combo-warn'
  return ''
})

const canSubmit = computed(() => {
  if (comboSize.value > HARD_LIMIT) return false
  const scanCount = rows.value.filter((r) => !r.locked).length
  if (scanCount === 0) return false  // 至少解锁 1 个参数
  return true
})

function onSubmit() {
  if (!canSubmit.value) return
  const param_grid = {}
  for (const r of rows.value) {
    if (!r.locked && r.values?.length) param_grid[r.key] = r.values
  }
  emit('submit', {
    param_grid,
    metric: metric.value,
    select_top_n: selectTopN.value,
    concurrency: concurrency.value,
  })
  submitting.value = true
  // 由父组件关闭抽屉后 this 销毁, submitting 仅作占位
  setTimeout(() => { submitting.value = false }, 500)
}
</script>

<style scoped>
.sf-wrap { padding: 12px 0; }
.sf-desc { color: #909399; font-size: 13px; margin-bottom: 12px; }
.sf-hint { color: #c0c4cc; font-size: 12px; margin-left: 8px; }
.sf-meta { margin-top: 16px; }
.sf-summary {
  margin-top: 16px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
  display: flex;
  gap: 12px;
  align-items: center;
}
.sf-combo-warn { color: #e6a23c; }
.sf-combo-bad { color: #f56c6c; }
.sf-actions { margin-top: 16px; text-align: right; }
</style>
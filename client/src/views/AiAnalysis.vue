<template>
  <div class="ai-analysis-view fade-in-up">
    <!-- 顶部声明 -->
    <div class="content-card">
      <div class="card-header">
        <div>
          <h3 class="card-title">AI 分析 (PoC)</h3>
          <p class="card-sub">
            基于 <code>invest-analyst</code> skill 跑技术分析 (1m broker 拉数 + 多周期 resample + PDF 顺势策略 + MACD/RSI/BOLL/KDJ 8 维评分)
          </p>
        </div>
        <div class="card-header-extra">
          <el-tag size="small" type="warning" effect="plain">仅供研究/教育</el-tag>
        </div>
      </div>

      <!-- 输入区 -->
      <el-form :inline="true" :model="form" class="ai-form" label-position="top">
        <el-form-item label="证券代码">
          <el-input
            v-model="form.stockCode"
            placeholder="159992.SZ"
            style="width: 180px"
            clearable
          />
        </el-form-item>
        <el-form-item label="分析周期">
          <el-select
            v-model="form.periods"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选 1+ 个周期"
            style="width: 280px"
          >
            <el-option v-for="p in PERIOD_OPTIONS" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="开始日期">
          <el-input
            v-model="form.startDate"
            placeholder="20240813"
            style="width: 140px"
            clearable
          />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-input
            v-model="form.endDate"
            placeholder="20260812"
            style="width: 140px"
            clearable
          />
        </el-form-item>
        <el-form-item label=" ">
          <el-button
            type="primary"
            :icon="DataAnalysis"
            :loading="loading"
            :disabled="!canSubmit"
            @click="onSubmit"
          >
            {{ loading ? '分析中...' : '开始分析' }}
          </el-button>
        </el-form-item>
        <el-form-item label=" ">
          <el-button :icon="Refresh" @click="onReset" :disabled="loading">重置</el-button>
        </el-form-item>
      </el-form>

      <div class="form-hint">
        <el-text size="small" type="info">
          ⚠️ 同步调用，单次分析 60-180s，期间页面可继续查看其它内容，但不能重复提交。
          1d/4h 周期由本系统内部从 1m 数据 resample 得到（broker 不支持 1d）。
        </el-text>
      </div>
    </div>

    <!-- 错误区 -->
    <div v-if="errorMsg" class="error-bar">
      <el-alert :title="errorMsg" type="error" show-icon :closable="false" />
    </div>

    <!-- 结果区 -->
    <div v-if="result" class="content-card">
      <!-- 综合结论 -->
      <div v-if="result.synthesis" class="synthesis">
        <div class="synth-left">
          <div class="synth-label">综合结论</div>
          <div class="synth-action" :class="actionClass(result.synthesis.final_action)">
            {{ result.synthesis.final_action || '-' }}
          </div>
        </div>
        <div class="synth-meta">
          <div class="meta-item">
            <span class="meta-label">avg_score</span>
            <span class="meta-value text-mono">{{ result.synthesis.avg_score }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">confidence</span>
            <span class="meta-value text-mono">{{ result.synthesis.final_confidence }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">周期分布</span>
            <span class="meta-value text-mono">
              B:{{ result.synthesis.action_distribution?.BUY || 0 }}
              S:{{ result.synthesis.action_distribution?.SELL || 0 }}
              H:{{ result.synthesis.action_distribution?.HOLD || 0 }}
            </span>
          </div>
          <div class="meta-item">
            <span class="meta-label">耗时</span>
            <span class="meta-value text-mono">{{ result.elapsed_sec }}s</span>
          </div>
        </div>
      </div>

      <!-- 关键表格 -->
      <el-table
        :data="result.table_rows"
        border
        size="default"
        style="width: 100%"
        :header-cell-style="{ background: 'var(--bg-soft)', fontWeight: 600 }"
        empty-text="无数据"
      >
        <el-table-column prop="period" label="周期" width="80" align="center" />
        <el-table-column label="建议" width="90" align="center">
          <template #default="{ row }">
            <el-tag
              v-if="row.action"
              :type="actionTagType(row.action)"
              effect="dark"
              size="small"
            >
              {{ row.action }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="score" width="80" align="center">
          <template #default="{ row }">
            <span class="text-mono">{{ row.score?.toFixed(3) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="confidence" width="100" align="center">
          <template #default="{ row }">
            <span class="text-mono">{{ row.confidence?.toFixed(2) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="close" width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ row.close?.toFixed(4) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="EMA89" width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ row.ema89?.toFixed(4) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="入场" width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ row.entry?.toFixed(4) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="止损" width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono text-danger">{{ row.stop?.toFixed(4) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="止盈" width="100" align="right">
          <template #default="{ row }">
            <span class="text-mono text-up">{{ row.tp?.toFixed(4) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏比" width="80" align="center">
          <template #default="{ row }">
            <span class="text-mono">{{ row.rr?.toFixed(2) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="MACD_hist" width="110" align="right">
          <template #default="{ row }">
            <span class="text-mono">{{ row.macd_hist?.toFixed(4) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="RSI" width="70" align="center">
          <template #default="{ row }">
            <span class="text-mono">{{ row.rsi?.toFixed(1) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="KDJ.K" width="80" align="center">
          <template #default="{ row }">
            <span class="text-mono">{{ row.kdj_k?.toFixed(1) ?? '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="风险源" width="160" align="center">
          <template #default="{ row }">
            <el-text v-if="row.risk_source" type="info" size="small">
              {{ row.risk_source }}
            </el-text>
          </template>
        </el-table-column>
      </el-table>

      <!-- 详情摘要（按周期展开） -->
      <div v-if="result.report?.per_period" class="per-period">
        <h4 class="card-title">各周期详情</h4>
        <el-collapse v-model="openPeriods">
          <el-collapse-item
            v-for="(v, tp) in result.report.per_period"
            :key="tp"
            :name="tp"
            :title="`${tp} — ${v.advice?.action || 'N/A'} (score=${v.trend?.score?.toFixed(3) ?? '-'})`"
          >
            <pre class="period-json">{{ formatPeriod(v) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- 免责声明 -->
      <div class="disclaimer">
        {{ result.disclaimer }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { DataAnalysis, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { aiAnalysisApi } from '../api/ai_analysis'

const PERIOD_OPTIONS = ['1d', '4h', '1h', '30m', '15m', '5m', '1m']

// 默认值：跑 1d 1 档 ≈ 1-2 分钟
const form = reactive({
  stockCode: '159992.SZ',
  periods: ['1d'],
  startDate: '20240813',
  endDate: '20260812',
})

const loading = ref(false)
const result = ref(null)
const errorMsg = ref('')
const openPeriods = ref([])

const canSubmit = computed(() => {
  return (
    !!form.stockCode.trim() &&
    form.periods.length > 0 &&
    /^\d{8}$/.test(form.startDate) &&
    /^\d{8}$/.test(form.endDate)
  )
})

function onReset() {
  form.stockCode = ''
  form.periods = ['1d']
  form.startDate = ''
  form.endDate = ''
  result.value = null
  errorMsg.value = ''
}

async function onSubmit() {
  if (!canSubmit.value) {
    ElMessage.warning('请检查输入：股票代码 + 至少 1 个周期 + 8 位日期')
    return
  }
  loading.value = true
  errorMsg.value = ''
  result.value = null
  try {
    const data = await aiAnalysisApi.analyze({
      stockCode: form.stockCode.trim(),
      periods: form.periods,
      startDate: form.startDate,
      endDate: form.endDate,
    })
    if (data.code !== 0) {
      errorMsg.value = data.msg || `后端返回 code=${data.code}`
      return
    }
    result.value = data
    ElMessage.success(`分析完成 (${data.elapsed_sec}s)`)
    // 默认展开第一个周期
    if (data.report?.per_period) {
      const first = Object.keys(data.report.per_period)[0]
      openPeriods.value = [first]
    }
  } catch (e) {
    const msg = e?.response?.data?.detail?.msg || e?.message || '请求失败'
    errorMsg.value = `调用失败：${msg}`
    ElMessage.error(errorMsg.value)
  } finally {
    loading.value = false
  }
}

function actionTagType(action) {
  if (action === 'BUY') return 'success'
  if (action === 'SELL') return 'danger'
  return 'warning'
}
function actionClass(action) {
  if (action === 'BUY') return 'action-buy'
  if (action === 'SELL') return 'action-sell'
  return 'action-hold'
}
function formatPeriod(v) {
  if (!v || v.error) return JSON.stringify(v, null, 2)
  const { summary, trend, strategy_signals, advice, risk } = v
  return JSON.stringify({ summary, trend, strategy_signals, advice, risk }, null, 2)
}
</script>

<style scoped>
.ai-analysis-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}

.ai-form {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: flex-end;
}

.form-hint {
  margin-top: var(--space-2);
  font-size: 12px;
}

.error-bar {
  width: 100%;
}

.content-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-light);
  gap: var(--space-4);
  flex-wrap: wrap;
}

.card-header-extra {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.card-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}

.card-sub code {
  background: var(--bg-soft);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-family: var(--font-mono);
}

.synthesis {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-4);
  background: var(--bg-soft);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
  flex-wrap: wrap;
}

.synth-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.synth-label {
  font-size: 11px;
  color: var(--text-secondary);
  font-weight: 500;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.synth-action {
  font-size: 32px;
  font-weight: 700;
  font-family: var(--font-mono);
  letter-spacing: 1px;
}

.synth-action.action-buy { color: var(--color-up); }
.synth-action.action-sell { color: var(--color-down); }
.synth-action.action-hold { color: var(--text-secondary); }

.synth-meta {
  display: flex;
  gap: var(--space-5);
  flex: 1;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-label {
  font-size: 11px;
  color: var(--text-secondary);
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.meta-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.text-mono { font-family: var(--font-mono); }
.text-danger { color: var(--color-down); }
.text-up { color: var(--color-up); }

.per-period {
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-light);
}

.per-period h4 {
  margin: 0 0 var(--space-3) 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.period-json {
  background: var(--bg-soft);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: var(--space-3);
  font-size: 11px;
  line-height: 1.5;
  max-height: 360px;
  overflow: auto;
  font-family: var(--font-mono);
  color: var(--text-regular);
}

.disclaimer {
  margin-top: var(--space-4);
  padding: var(--space-3);
  background: var(--bg-soft);
  border-left: 3px solid var(--color-warning);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

@media (max-width: 720px) {
  .synth-action { font-size: 24px; }
}
</style>

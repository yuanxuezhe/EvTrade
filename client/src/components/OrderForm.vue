<template>
  <div class="order-form-wrap content-card">
    <!-- 买卖 Tab -->
    <div class="direction-tabs">
      <button
        class="tab-btn buy"
        :class="{ active: form.order_type === '23' }"
        @click="form.order_type = '23'"
      >
        <el-icon><Top /></el-icon>
        <span>买入</span>
      </button>
      <button
        class="tab-btn sell"
        :class="{ active: form.order_type === '24' }"
        @click="form.order_type = '24'"
      >
        <el-icon><Bottom /></el-icon>
        <span>卖出</span>
      </button>
    </div>

    <div class="form-body">
      <el-form :model="form" label-position="top" size="default">
        <el-form-item label="股票代码">
          <el-input
            v-model="form.stock_code"
            placeholder="如 000001.SZ"
            clearable
            @change="onStockCodeChange"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item label="价格类型">
          <el-segmented
            v-model="form.price_type"
            :options="priceTypeOptions"
            block
          />
        </el-form-item>

        <el-form-item label="委托价格">
          <el-input-number
            v-model="form.price"
            :min="0"
            :precision="2"
            :step="0.01"
            :disabled="form.price_type !== 11"
            controls-position="right"
            style="width: 100%"
          />
          <div class="price-quick">
            <button
              v-for="p in priceShortcuts"
              :key="p.label"
              type="button"
              class="quick-btn"
              @click="applyPriceShortcut(p)"
            >
              {{ p.label }}
            </button>
          </div>
        </el-form-item>

        <el-form-item label="委托数量">
          <el-input-number
            v-model="form.volume"
            :min="100"
            :step="100"
            controls-position="right"
            style="width: 100%"
          />
          <div class="volume-quick">
            <button
              v-for="v in volumeShortcuts"
              :key="v"
              type="button"
              class="quick-btn"
              @click="form.volume = v"
            >
              {{ formatVolume(v) }}
            </button>
          </div>
        </el-form-item>

        <div class="form-summary">
          <div class="summary-row">
            <span class="summary-label">预估金额</span>
            <span class="summary-value text-mono">¥{{ formatMoney(estimatedAmount) }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">手续费(估算)</span>
            <span class="summary-value text-mono text-secondary">¥{{ formatMoney(estimatedFee) }}</span>
          </div>
        </div>

        <div class="form-actions">
          <el-button
            :type="form.order_type === '23' ? 'danger' : 'success'"
            size="large"
            class="submit-btn"
            @click="handleSubmit"
            :loading="submitting"
          >
            {{ form.order_type === '23' ? '确认买入' : '确认卖出' }}
          </el-button>
          <el-button size="large" @click="handleReset" :disabled="submitting">
            重置
          </el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Top, Bottom } from '@element-plus/icons-vue'
import { formatMoney } from '../utils/format'

const props = defineProps({
  onSubmit: { type: Function, required: true },
  defaultStockCode: { type: String, default: '' }
})

const submitting = ref(false)

const form = reactive({
  stock_code: props.defaultStockCode || '',
  // 柜台 order_type：股票 23=买入，24=卖出
  order_type: '23',
  // 柜台 price_type 数字：11=指定价(限价) 5=最新价 14=对手价 44=市价 ...
  price_type: 11,
  price: 0,
  volume: 100
})

// 价格类型 → 柜台枚举数字（与后端/柜台一致）
const priceTypeOptions = [
  { label: '限价', value: 11 },
  { label: '最新价', value: 5 },
  { label: '挂单价', value: 14 },
  { label: '市价', value: 44 }
]

const priceShortcuts = [
  { label: '涨停', op: 'up10' },
  { label: '+1%', op: 'plus1' },
  { label: '-1%', op: 'minus1' },
  { label: '跌停', op: 'down10' }
]

const volumeShortcuts = [100, 500, 1000, 5000, 10000]

const estimatedAmount = computed(() => (form.price || 0) * (form.volume || 0))
const estimatedFee = computed(() => Math.max(5, estimatedAmount.value * 0.00025))

function formatVolume(v) {
  return v >= 10000 ? `${v / 10000}万` : String(v)
}

function applyPriceShortcut(p) {
  if (!form.price) {
    ElMessage.warning('请先输入基准价格')
    return
  }
  switch (p.op) {
    case 'up10': form.price = Number((form.price * 1.10).toFixed(2)); break
    case 'down10': form.price = Number((form.price * 0.90).toFixed(2)); break
    case 'plus1': form.price = Number((form.price * 1.01).toFixed(2)); break
    case 'minus1': form.price = Number((form.price * 0.99).toFixed(2)); break
  }
}

function onStockCodeChange() {
  form.stock_code = form.stock_code.toUpperCase().trim()
}

async function handleSubmit() {
  if (!form.stock_code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  if (form.price_type === 11 && form.price <= 0) {
    ElMessage.warning('限价单需要输入价格')
    return
  }
  if (form.volume <= 0) {
    ElMessage.warning('请输入数量')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认${form.order_type === '23' ? '买入' : '卖出'} ${form.stock_code} ${form.volume} 股，
预估金额 ¥${formatMoney(estimatedAmount.value)}`,
      '订单确认',
      {
        confirmButtonText: '确认下单',
        cancelButtonText: '取消',
        type: form.order_type === '23' ? 'warning' : 'info',
        confirmButtonClass: form.order_type === '23' ? 'el-button--danger' : 'el-button--success'
      }
    )
  } catch {
    return
  }
  submitting.value = true
  try {
    await props.onSubmit({ ...form })
    handleReset()
  } finally {
    submitting.value = false
  }
}

function handleReset() {
  form.price = 0
  form.volume = 100
}
</script>

<style scoped>
.order-form-wrap {
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.direction-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  background: var(--bg-soft);
  border-bottom: 1px solid var(--border-light);
}

.tab-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: var(--space-4);
  background: transparent;
  border: none;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
}

.tab-btn::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 2px;
  background: currentColor;
  transition: width var(--transition-base);
}

.tab-btn.buy.active {
  color: var(--color-up);
  background: var(--color-up-bg);
}

.tab-btn.sell.active {
  color: var(--color-down);
  background: var(--color-down-bg);
}

.tab-btn.active::after {
  width: 40%;
}

.form-body {
  padding: var(--space-5);
}

.price-quick,
.volume-quick {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
  flex-wrap: wrap;
}

.quick-btn {
  padding: 4px 10px;
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-xs);
  font-size: 12px;
  color: var(--text-regular);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.quick-btn:hover {
  border-color: var(--brand-primary);
  color: var(--brand-primary);
  background: var(--bg-hover);
}

.form-summary {
  padding: var(--space-3) var(--space-4);
  background: var(--bg-soft);
  border-radius: var(--radius-md);
  margin: var(--space-4) 0;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 4px 0;
}

.summary-label {
  color: var(--text-secondary);
}

.summary-value {
  font-weight: 600;
  color: var(--text-primary);
}

.form-actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.submit-btn {
  flex: 1;
  font-weight: 600 !important;
  letter-spacing: 1px;
}

:deep(.el-form-item) {
  margin-bottom: var(--space-4);
}

:deep(.el-form-item__label) {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  padding-bottom: 4px;
}
</style>

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
        <el-form-item label="股票代码" class="row-tight">
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

        <!-- 价格类型 + 委托价格：同一行 -->
        <div class="price-row">
          <el-form-item label="价格类型" class="row-tight price-type-col">
            <el-segmented
              v-model="form.price_type"
              :options="priceTypeOptions"
              block
              size="small"
            />
          </el-form-item>
          <el-form-item label="委托价格" class="row-tight price-col">
            <el-input-number
              v-model="form.price"
              :min="0"
              :precision="form.price_type === 11 ? null : 2"
              :step="form.price_type === 11 ? 0.01 : null"
              :disabled="form.price_type !== 11"
              :placeholder="form.price_type === 11 ? '输入价格' : '市价单无需输入'"
              controls-position="right"
              style="width: 100%"
            />
          </el-form-item>
        </div>

        <el-form-item label="委托数量" class="row-tight">
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
            <span class="summary-value text-mono">
              <template v-if="form.price_type === 11">¥{{ formatMoney(estimatedAmount) }}</template>
              <template v-else>— 市价单 —</template>
            </span>
          </div>
        </div>

        <div class="form-actions">
          <el-button
            :type="form.order_type === '23' ? 'danger' : 'success'"
            size="default"
            class="submit-btn"
            @click="handleSubmit"
            :loading="submitting"
          >
            {{ form.order_type === '23' ? '确认买入' : '确认卖出' }}
          </el-button>
          <el-button size="default" @click="handleReset" :disabled="submitting">
            重置
          </el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Top, Bottom } from '@element-plus/icons-vue'
import { formatMoney } from '../utils/format'

const props = defineProps({
  onSubmit: { type: Function, required: true },
  defaultStockCode: { type: String, default: '' }
})

const emit = defineEmits(['apply-quote-price', 'update:stockCode'])

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

const volumeShortcuts = [100, 500, 1000, 5000, 10000]

const estimatedAmount = computed(() => (form.price || 0) * (form.volume || 0))

// 切换市价(44)时清空价格；切回限价(11)也清空（避免残留的旧值误下单）
watch(() => form.price_type, (newType, oldType) => {
  if (newType !== 11) {
    // 市价单不依赖具体价格，但保留作为显示用也行；这里清空避免误读
    form.price = 0
  }
})

// 外部双击行情价格带入：要求限价模式
function onExternalApply(price) {
  if (form.price_type !== 11) form.price_type = 11
  form.price = Number(price)
}
defineExpose({ onExternalApply })

function formatVolume(v) {
  return v >= 10000 ? `${v / 10000}万` : String(v)
}

function onStockCodeChange() {
  form.stock_code = form.stock_code.toUpperCase().trim()
  // 通知父组件（Trade.vue）：行情面板要切换到这只票
  emit('update:stockCode', form.stock_code)
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
  const amountNote = form.price_type === 11
    ? `预估金额 ¥${formatMoney(estimatedAmount.value)}`
    : `市价单（价格类型 ${form.price_type}）`
  try {
    await ElMessageBox.confirm(
      `确认${form.order_type === '23' ? '买入' : '卖出'} ${form.stock_code} ${form.volume} 股，\n${amountNote}`,
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
  padding: var(--space-3);
  background: transparent;
  border: none;
  font-size: 14px;
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
  padding: var(--space-3) var(--space-4);
}

.price-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-3);
  align-items: start;
}

.price-type-col {
  min-width: 180px;
}

.volume-quick {
  display: flex;
  gap: var(--space-1);
  margin-top: var(--space-1);
  flex-wrap: wrap;
}

.quick-btn {
  padding: 2px 8px;
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-xs);
  font-size: 11px;
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
  padding: var(--space-2) var(--space-3);
  background: var(--bg-soft);
  border-radius: var(--radius-sm);
  margin: var(--space-3) 0;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  padding: 2px 0;
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
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.submit-btn {
  flex: 1;
  font-weight: 600 !important;
  letter-spacing: 1px;
}

/* 紧凑化：缩小 el-form-item 间距 */
:deep(.row-tight.el-form-item) {
  margin-bottom: var(--space-3);
}

:deep(.el-form-item__label) {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
  padding-bottom: 2px;
  line-height: 1.4;
}

:deep(.el-input__wrapper),
:deep(.el-input-number) {
  font-size: 13px;
}
</style>
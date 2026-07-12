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
          <!-- v26: StockCodeAutocomplete 通用组件 (cache 跨页面共享) -->
          <StockCodeAutocomplete
            v-model="form.stock_code"
            placeholder="输入代码 / 名称 / 首字母"
            @select="onAutocompleteSelect"
            @update:model-value="onStockCodeChange"
          />
        </el-form-item>

        <!-- 价格类型：单行 inline radio-button (与 T0Trade 价格档风格一致;2026-07-09 单行化重构, v15 替换 2×2 grid 避免占满整行) -->
        <el-form-item label="价格类型" class="row-tight">
          <el-radio-group v-model="form.price_type" size="default">
            <el-radio-button
              v-for="opt in priceTypeOptions"
              :key="opt.value"
              :value="opt.value"
            >
              {{ opt.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- 委托价格：独立全宽行 (与"委托数量"对称) -->
        <el-form-item label="委托价格" class="row-tight">
          <el-input-number
            v-model="form.price"
            :min="0"
            :precision="2"
            :step="form.price_type === PriceType.LIMIT ? 0.01 : null"
            :disabled="form.price_type !== PriceType.LIMIT"
            :placeholder="form.price_type === PriceType.LIMIT ? '输入价格' : '市价单无需输入'"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>

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
              <template v-if="form.price_type === PriceType.LIMIT">¥{{ formatMoney(estimatedAmount) }}</template>
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
import { Top, Bottom } from '@element-plus/icons-vue'
import { formatMoney } from '../utils/format'
import { PriceType, priceTypeOptions, OrderType } from '../constants/priceType'
import StockCodeAutocomplete from './StockCodeAutocomplete.vue'

const props = defineProps({
  onSubmit: { type: Function, required: true },
  defaultStockCode: { type: String, default: '' }
})

// 2026-07-09: emit 名改 kebab-case, 与父组件 Trade.vue @update:stock-code 对应
// v26: StockCodeAutocomplete 选中候选时 emit select(stock), OrderForm 触发行情拉取
const emit = defineEmits(['apply-quote-price', 'update:stock-code', 'stock-selected'])

const submitting = ref(false)

const form = reactive({
  stock_code: props.defaultStockCode || '',
  // v27: 证券名称, 由 StockCodeAutocomplete @select 回调写入 (UI 展示用, 不参与后端下单字段)
  stock_name: '',
  // 柜台 order_type：股票 23=买入，24=卖出
  order_type: OrderType.BUY,
  // 柜台 price_type 数字：5=最新价 11=指定价 (限价) 14=对手价 44=市价 ...
  price_type: PriceType.LIMIT,
  price: 0,
  volume: 100
})

// 价格类型选项（从常量导入）
// const priceTypeOptions = [
//   { label: '限价', value: 11 },
//   { label: '最新价', value: 5 },
//   { label: '挂单价', value: 14 },
//   { label: '市价', value: 44 }
// ]

const volumeShortcuts = [100, 500, 1000, 5000, 10000]

const estimatedAmount = computed(() => (form.price || 0) * (form.volume || 0))

// 切换市价 (44) 时清空价格；切回限价 (11) 也清空（避免残留的旧值误下单）
watch(() => form.price_type, (newType, oldType) => {
  if (newType !== PriceType.LIMIT) {
    // 市价单不依赖具体价格，但保留作为显示用也行；这里清空避免误读
    form.price = 0
  }
})

// 外部双击行情价格带入：要求限价模式
function onExternalApply(price) {
  if (form.price_type !== PriceType.LIMIT) form.price_type = PriceType.LIMIT
  form.price = Number(price)
}
defineExpose({ onExternalApply })

function formatVolume(v) {
  return v >= 10000 ? `${v / 10000}万` : String(v)
}

function onStockCodeChange(val) {
  // v27: StockCodeAutocomplete 拆成左右两半后, modelValue 永远是纯 stock_code (600519.SH)
  //   名称走 @select → onAutocompleteSelect 写到 form.stock_name
  //   用户手动改代码时这里只更新 stock_code, 名称由控件内部 watch 清空
  const raw = (val || '').trim()
  form.stock_code = raw.toUpperCase()
  // 2026-07-09: emit 名改 kebab-case, 与父组件 Trade.vue @update:stock-code 对应
  emit('update:stock-code', form.stock_code)
}

function onAutocompleteSelect(stock) {
  // v26: StockCodeAutocomplete 选中真实存在的 stock 时触发
  // v27: stock.stock_name 写到 form.stock_name (UI 展示, 不参与下单字段)
  if (stock && stock.stock_name) {
    form.stock_name = stock.stock_name
  }
  // 转发给父组件 (Trade.vue 可触发行情预拉取)
  emit('stock-selected', stock)
}

async function handleSubmit() {
  if (!form.stock_code) {
    ElMessage.warning('请输入股票代码')
    return
  }
  if (form.price_type === PriceType.LIMIT && form.price <= 0) {
    ElMessage.warning('限价单需要输入价格')
    return
  }
  if (form.volume <= 0) {
    ElMessage.warning('请输入数量')
    return
  }
  const amountNote = form.price_type === PriceType.LIMIT
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

/* v15 trade-pricetype-inline: 价格类型 radio-button 单行布局,沿用 el-radio-group 默认样式,不需 grid 重置 */
</style>

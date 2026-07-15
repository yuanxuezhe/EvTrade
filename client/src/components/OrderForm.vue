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
      <!-- v32: label 同行 (label-position="left" label-width="80px"), 让左列 420px 充分利用 -->
      <el-form :model="form" label-position="left" label-width="80px" size="default">
        <el-form-item label="股票代码" class="row-tight">
          <!-- v28: StockCodePicker 强化'输入合法性'契约, blur 时未选自动清空 -->
          <StockCodePicker
            v-model="form.stock_code"
            placeholder="输入代码 / 名称 / 首字母"
            tag-type="primary"
            @select="onAutocompleteSelect"
            @update:model-value="onStockCodeChange"
            @blur="onStockCodeBlur"
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
            :step="form.price_type === PriceType.FIX_PRICE ? 0.01 : null"
            :disabled="form.price_type !== PriceType.FIX_PRICE"
            :placeholder="form.price_type === PriceType.FIX_PRICE ? '输入价格' : '市价单无需输入'"
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
              <template v-if="form.price_type === PriceType.FIX_PRICE">¥{{ formatMoney(estimatedAmount) }}</template>
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
import StockCodePicker from './StockCodePicker.vue'

const props = defineProps({
  onSubmit: { type: Function, required: true },
  defaultStockCode: { type: String, default: '' }
})

const emit = defineEmits(['apply-quote-price', 'update:stock-code', 'stock-selected'])

const submitting = ref(false)

const form = reactive({
  stock_code: props.defaultStockCode || '',
  // v28: 证券名称, 由 StockCodePicker @select 回调写入 (UI 展示用, 不参与后端下单字段)
  stock_name: '',
  // 柜台 order_type：股票 23=买入，24=卖出
  order_type: OrderType.BUY,
  // 柜台 price_type 数字：5=最新价 14=对手价 (UI 称"限价") 44=市价
  //   原 11=指定价 已从 UI 选项中移除 (v__: UI"限价"实际送 14, 送参数 code 不变)
  price_type: PriceType.FIX_PRICE,
  price: 0,
  volume: 100
})

// 价格类型选项（从常量导入）
// const priceTypeOptions = [
//   { label: '限价', value: 14 },
//   { label: '最新价', value: 5 },
//   { label: '市价', value: 44 }
// ]

const volumeShortcuts = [100, 500, 1000, 5000, 10000]

const estimatedAmount = computed(() => (form.price || 0) * (form.volume || 0))

// 切到非对手价 (最新价 5 / 市价 44) 时清空价格；切回对手价 (14) 也清空（避免残留的旧值误下单）
watch(() => form.price_type, (newType, oldType) => {
  if (newType !== PriceType.FIX_PRICE) {
    // 市价/最新价不依赖具体价格，但保留作为显示用也行；这里清空避免误读
    form.price = 0
  }
})

// 外部双击行情价格带入：要求对手价 (UI 称"限价") 模式
function onExternalApply(price) {
  if (form.price_type !== PriceType.FIX_PRICE) form.price_type = PriceType.FIX_PRICE
  form.price = Number(price)
}
defineExpose({ onExternalApply })

function formatVolume(v) {
  return v >= 10000 ? `${v / 10000}万` : String(v)
}

function onStockCodeChange(val) {
  // v28: StockCodePicker 已收紧 emit 语义, 此处 val 必然来自 onSelectItem 真正选中
  //   若来自 blur 未选中, val = '' (前端也已清空 form.stock_code)
  //   仅做 trim + uppercase 归一化, 然后转发给父组件
  const raw = (val || '').trim()
  form.stock_code = raw.toUpperCase()
  // 2026-07-09: emit 名改 kebab-case, 与父组件 Trade.vue @update:stock-code 对应
  emit('update:stock-code', form.stock_code)
}

function onStockCodeBlur() {
  // v28: 控件失焦时若未真正选中已自动 emit('') 清空
  //   这里只需把 form.stock_name 同步清掉 (UI 上下文, 避免残留陈旧名称)
  if (!form.stock_code) {
    form.stock_name = ''
    emit('update:stock-code', '')
  }
}

function onAutocompleteSelect(stock) {
  // v28: StockCodePicker 选中真实存在的 stock 时触发
  //   stock.stock_name 写到 form.stock_name (UI 展示, 不参与下单字段)
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
  if (form.price_type === PriceType.FIX_PRICE && form.price <= 0) {
    ElMessage.warning('限价单需要输入价格')
    return
  }
  if (form.volume <= 0) {
    ElMessage.warning('请输入数量')
    return
  }
  const amountNote = form.price_type === PriceType.FIX_PRICE
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
  /* v32: 修 commit 4 副作用 — 4 个 form-item + 快捷金额 + 按钮 在 206.5px cell 内溢出, 加纵向滚动 */
  overflow-y: auto;
  flex: 1;
  min-height: 0;
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
  /* v35: 与上方 el-form-item 对齐 — el-form label-width=80px, 此处左边留 80px 让按钮行与 input 区域对齐 */
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-left: 80px;
  /* 兜底: 即使 el-form label-width 变动, 仍与 label 末位对齐 */
  box-sizing: border-box;
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

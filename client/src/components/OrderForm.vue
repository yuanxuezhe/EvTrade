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

        <!-- v33: 价格类型 + 委托价格 → 合并为 1 行 PriceTypeInput (input + select 50/50) -->
        <el-form-item label="委托价格" class="row-tight" prop="price">
          <PriceTypeInput
            v-model:price="form.price"
            v-model:price-type="form.price_type"
            :stock-code="form.stock_code"
          />
        </el-form-item>

        <!-- v33: 可用行 — 在价格组合行下, 委托数量行上; 根据买入/卖出 + 价格类型实时计算 -->
        <el-form-item label="可交易" class="row-tight">
          <div class="order-available-row">
            <span class="order-available-label">{{ availableLabel }}</span>
            <span class="order-available-value">{{ availableText }}</span>
          </div>
        </el-form-item>

        <el-form-item label="委托数量" class="row-tight" prop="volume">
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
              <!-- v33.1.3: 最新价=last_price; 市价=方向对手方价 (买→卖1, 卖→买1) -->
              <template v-else-if="form.stock_code && estimatedPrice > 0">¥{{ formatMoney(estimatedAmountByPriceType) }}<span class="summary-sub">({{ estimatedPriceLabel }} ¥{{ formatPriceAuto(estimatedPrice) }} × {{ formatVolume(form.volume) }})</span></template>
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
import { formatMoney, formatPriceAuto } from '../utils/format'
import { PriceType, priceTypeOptions, OrderType } from '../constants/priceType'
import StockCodePicker from './StockCodePicker.vue'
import PriceTypeInput from './PriceTypeInput.vue'
import { useAssetStore } from '../stores/asset'
import { usePositionStore } from '../stores/position'
import { useQuoteStore } from '../stores/quote'

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
  // v83: 柜台 price_type: 11=限价 5=最新价 44=市价 (与 xtconstant 柜台协议 1:1 对齐)
  //   UI 默认 FIX_PRICE = 11
  price_type: PriceType.FIX_PRICE,
  price: 0,
  volume: 100
})

// v33: 新增 — 持仓 / 资金 / 行情 store 引用 (用于可交易数量实时计算)
const assetStore = useAssetStore()
const positionStore = usePositionStore()
const quoteStore = useQuoteStore()

// 价格类型选项（从常量导入）
// const priceTypeOptions = [
//   { label: '限价', value: 14 },
//   { label: '最新价', value: 5 },
//   { label: '市价', value: 44 }
// ]

const volumeShortcuts = [100, 500, 1000, 5000, 10000]

const estimatedAmount = computed(() => (form.price || 0) * (form.volume || 0))

// v33.1.3: 按价格类型取预估价
//   FIX_PRICE: 输入价
//   LATEST_PRICE: 直接取 last_price (最新价, 不分方向)
//   MARKET_PEER_PRICE_FIRST: 按方向取对手方最优价 (买→卖1, 卖→买1)
const estimatedPrice = computed(() => {
  if (!form.stock_code) return 0
  if (form.price_type === PriceType.FIX_PRICE) {
    return Number(form.price) || 0
  }
  const q = quoteStore.getQuote(form.stock_code)
  if (form.price_type === PriceType.LATEST_PRICE) {
    // 最新价 — 直接读 q.last_price
    return Number(quoteStore.getLastPrice(form.stock_code)) || 0
  }
  if (form.price_type === PriceType.MARKET_PEER_PRICE_FIRST) {
    const isBuy = String(form.order_type) === '23'
    // 买→卖1价 (q.ask_prices[0]), 卖→买1价 (q.bid_prices[0]) — store 在 update(snapshot) 路径写数组
    const peer = isBuy ? q?.ask_prices?.[0] : q?.bid_prices?.[0]
    return Number(peer) || 0
  }
  return 0
})

// 实际预估金额: estimatedPrice × volume (FIX_PRICE=输入价; 最新价=最新; 市价=方向对手方价)
// 行情不可得 (estimatedPrice=0) → 0; volume=0 → 0
const estimatedAmountByPriceType = computed(() => {
  const px = estimatedPrice.value
  const vol = Number(form.volume) || 0
  if (px <= 0 || vol <= 0) return 0
  return px * vol
})

// v33.1.3: 预估金额 sub 标签
//   FIX_PRICE: 空
//   LATEST_PRICE: "最新价" (不分方向)
//   MARKET_PEER_PRICE_FIRST: 按方向 "卖一价" (买) / "买一价" (卖)
const estimatedPriceLabel = computed(() => {
  if (!form.stock_code) return ''
  if (form.price_type === PriceType.FIX_PRICE) return ''
  if (form.price_type === PriceType.LATEST_PRICE) return '最新价'
  if (form.price_type === PriceType.MARKET_PEER_PRICE_FIRST) {
    const isBuy = String(form.order_type) === '23'
    return isBuy ? '卖一价' : '买一价'
  }
  return ''
})

// ==============================================================
// v33: 可交易数量 (可买 / 可卖) 计算 — 实时响应持仓 + 资金 + 行情
// ==============================================================

/** 买卖方向 label — 动态切换 "可买" / "可卖" */
const availableLabel = computed(() =>
  form.order_type === OrderType.BUY ? '可买 (股)' : '可卖 (股)'
)

/**
 * 可买/可卖数量
 *
 * 买入时 (用可用的现金 cash 计算):
 *   - 限价 (FIX_PRICE) → 用 输入价格
 *   - 最新价 (LATEST_PRICE) → 行情最新价 (quote.last_price)
 *   - 市价 (MARKET_PEER_PRICE_FIRST) → 卖一价 (ask_price[0])
 *   - 公式: floor(cash / price / 100) * 100 (A股 100 股一手, 不足一手部分丢弃)
 *
 * 卖出时 (用持仓 avl_vol 即"可用"):
 *   - 取持仓 avl_vol 字段 (T+1 制度下该字段即为可卖数)
 *   - 未持仓 / 行情无 → "0"
 */
const availableText = computed(() => {
  // ----- 卖出: 直接返回 avl_vol -----
  if (form.order_type === OrderType.SELL) {
    if (!form.stock_code) return '0'
    const pos = positionStore.positions.find((p) => p.stock_code === form.stock_code)
    if (!pos) return '0'
    const avl = Number(pos.avl_vol) || 0
    return avl.toLocaleString()
  }

  // ----- 买入: 根据价格类型取不同价格, 计算可买股数 -----
  if (!form.stock_code) return '—'
  const cash = Number(assetStore.asset.cash) || 0
  if (cash <= 0) return '0'

  let px = 0
  if (form.price_type === PriceType.FIX_PRICE) {
    px = Number(form.price) || 0
  } else if (form.price_type === PriceType.LATEST_PRICE) {
    // 最新价 — 行情 last_price
    px = quoteStore.getLastPrice(form.stock_code) ?? 0
  } else if (form.price_type === PriceType.MARKET_PEER_PRICE_FIRST) {
    // 吃对手方最优价 (买→卖1, 卖→买1)
    const q = quoteStore.getQuote(form.stock_code)
    const isBuy = String(form.order_type) === '23'
    const peer = isBuy ? q?.ask_prices?.[0] : q?.bid_prices?.[0]
    px = Number(peer) || 0
  }
  if (px <= 0) return '—'

  // A 股最小买入 100 股, 向下取整到 100 倍数
  const raw = Math.floor(cash / px / 100) * 100
  return raw.toLocaleString()
})

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

// v53: 外部双击持仓带入 stock_code (REQ-FE-HOLDINGS-DBLCLICK)
//   与 onExternalApply 对偶, 同时暴露出来让父组件可调用
function onExternalApplyStockCode(code) {
  const c = String(code || '').trim().toUpperCase()
  form.stock_code = c
  emit('update:stock-code', c)
}
defineExpose({ onExternalApply, onExternalApplyStockCode })

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

/* v33: 可交易行 — 与 summary-row 对称, 左 label 右 value */
.order-available-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  padding: 2px 0;
}

.order-available-label {
  color: var(--text-secondary);
  font-size: 12px;
}

.order-available-value {
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-mono, 'SF Mono', Consolas, monospace);
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

/* v33.1: 预估金额的细分小字 (最新价/卖一价 × N股) */
.summary-sub {
  margin-left: 8px;
  font-size: 11px;
  font-weight: normal;
  color: var(--text-secondary);
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

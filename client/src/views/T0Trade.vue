<template>
  <div class="t0-trade fade-in-up">
    <!-- 顶部：股票选择 + 实时报价 -->
    <div class="content-card quote-bar">
      <div class="quote-left">
        <el-input
          v-model="stockCode"
          placeholder="股票代码 (如 600519.SH)"
          style="width: 220px"
          @keyup.enter="onSubmit"
          @change="onStockCodeChange"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button @click="showPicker = true" :icon="List">选择持仓</el-button>
      </div>
      <div class="quote-mid" v-if="lastPrice != null">
        <div class="price-line">
          <span class="last-price" :class="priceClass">{{ formatPrice(lastPrice) }}</span>
          <span class="change" :class="priceClass">
            {{ changePct >= 0 ? '+' : '' }}{{ changePct?.toFixed(2) }}%
          </span>
        </div>
        <div class="quote-meta">
          <span v-if="isStale" class="stale">⚠ 行情过期</span>
          <span v-else class="fresh">● 实时</span>
        </div>
      </div>
      <div class="quote-mid placeholder" v-else>
        <span>输入代码获取实时行情</span>
      </div>
    </div>

    <!-- 3 个核心卡片：敞口 / T0 成本 / 预期收益 -->
    <div class="content-card-row">
      <el-card class="metric-card" shadow="hover">
        <template #header>
          <span class="card-title">📊 持仓敞口</span>
        </template>
        <div class="metric-body">
          <div class="metric-row">
            <span class="label">当前持仓</span>
            <span class="value text-mono">{{ formatNumber(currentVolume) }} 股</span>
          </div>
          <div class="metric-row">
            <span class="label">平均成本</span>
            <span class="value text-mono">{{ formatPrice(cost) }}</span>
          </div>
          <div class="metric-row">
            <span class="label">持仓成本</span>
            <span class="value text-mono">¥{{ formatAmount(positionCostTotal) }}</span>
          </div>
          <div class="metric-row">
            <span class="label">实时市值</span>
            <span class="value text-mono">
              {{ hasQuote ? '¥' + formatAmount(marketValue) : '--' }}
            </span>
          </div>
          <div class="metric-row">
            <span class="label">浮盈</span>
            <span class="value text-mono" :class="profitClass">
              {{ hasQuote ? (profit >= 0 ? '+' : '') + formatAmount(profit) : '--' }}
            </span>
          </div>
          <div class="metric-row">
            <span class="label">收益率</span>
            <span class="value text-mono" :class="profitClass">
              {{ hasQuote && costTotal > 0
                ? (profit >= 0 ? '+' : '') + (profitRate * 100).toFixed(2) + '%'
                : '--' }}
            </span>
          </div>
        </div>
      </el-card>

      <el-card class="metric-card" shadow="hover">
        <template #header>
          <span class="card-title">💰 T0 成本</span>
        </template>
        <div class="metric-body">
          <div class="metric-row">
            <span class="label">今日买入</span>
            <span class="value text-mono">{{ formatNumber(t0Stats.today_buy_volume) }} 股</span>
          </div>
          <div class="metric-row">
            <span class="label">买入金额</span>
            <span class="value text-mono">¥{{ formatAmount(t0Stats.today_buy_amount) }}</span>
          </div>
          <div class="metric-row">
            <span class="label">今日卖出</span>
            <span class="value text-mono">{{ formatNumber(t0Stats.today_sell_volume) }} 股</span>
          </div>
          <div class="metric-row">
            <span class="label">卖出金额</span>
            <span class="value text-mono">¥{{ formatAmount(t0Stats.today_sell_amount) }}</span>
          </div>
          <div class="metric-row">
            <span class="label">委托笔数</span>
            <span class="value text-mono">
              {{ t0Stats.order_count }} 条
              <span class="sub" v-if="t0Stats.open_order_count > 0">
                ({{ t0Stats.open_order_count }} 待报)
              </span>
            </span>
          </div>
          <div class="metric-row">
            <span class="label">成交笔数</span>
            <span class="value text-mono">{{ t0Stats.trade_count }} 条</span>
          </div>
        </div>
      </el-card>

      <el-card class="metric-card" shadow="hover">
        <template #header>
          <span class="card-title">📈 预期收益</span>
        </template>
        <div class="metric-body">
          <div class="metric-row">
            <span class="label">已实现</span>
            <span class="value text-mono" :class="t0Class">
              {{ (t0Stats.realized_pnl >= 0 ? '+' : '') + formatAmount(t0Stats.realized_pnl) }}
            </span>
          </div>
          <div class="metric-row">
            <span class="label">浮动</span>
            <span class="value text-mono" :class="t0Class">
              {{ (t0Stats.unrealized_pnl >= 0 ? '+' : '') + formatAmount(t0Stats.unrealized_pnl) }}
            </span>
          </div>
          <div class="metric-row big">
            <span class="label">合计</span>
            <span class="value text-mono big" :class="t0Class">
              {{ (t0Stats.total_pnl >= 0 ? '+' : '') + formatAmount(t0Stats.total_pnl) }}
            </span>
          </div>
          <div class="metric-row">
            <span class="label">回报率</span>
            <span class="value text-mono" :class="t0Class">
              {{
                t0Stats.position_cost_total > 0
                  ? ((t0Stats.total_pnl / t0Stats.position_cost_total) * 100).toFixed(2) + '%'
                  : '--'
              }}
            </span>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 操作区：左一键动作，右配平 -->
    <div class="content-card-row">
      <el-card class="action-card" shadow="hover">
        <template #header>
          <span class="card-title">⚡ 一键动作</span>
        </template>
        <div class="action-body">
          <div class="action-row">
            <el-button
              type="success"
              size="large"
              :icon="Top"
              :disabled="!canBuy"
              :loading="submitting"
              @click="onOneClickBuy"
              class="big-btn"
            >
              一键全仓买入
              <div class="btn-sub">{{ formatNumber(oneClickBuyQty) }} 股</div>
            </el-button>
            <el-button
              type="danger"
              size="large"
              :icon="Bottom"
              :disabled="!canSell"
              :loading="submitting"
              @click="onOneClickSell"
              class="big-btn"
            >
              一键全仓卖出
              <div class="btn-sub">{{ formatNumber(oneClickSellQty) }} 股</div>
            </el-button>
          </div>

          <el-divider />

          <el-form :inline="true" class="order-form">
            <el-form-item label="方向">
              <el-radio-group v-model="manualDirection" size="large">
                <el-radio-button value="23">买入</el-radio-button>
                <el-radio-button value="24">卖出</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="委托类型">
              <el-select v-model="priceType" style="width: 130px">
                <el-option label="最新价" value="latest" />
                <el-option label="对手价" value="oppose" />
                <el-option label="限价" value="limit" />
                <el-option label="市价" value="market" />
              </el-select>
            </el-form-item>
            <el-form-item label="价格" v-if="priceType === 'limit'">
              <el-input-number
                v-model="limitPrice"
                :min="0"
                :step="0.01"
                :precision="2"
                style="width: 140px"
              />
            </el-form-item>
            <el-form-item :label="`价格 (${priceTypeLabel})`" v-else>
              <span class="text-mono">{{ formatPrice(orderPrice) }}</span>
            </el-form-item>
            <el-form-item label="数量">
              <el-input-number
                v-model="manualVolume"
                :min="0"
                :step="100"
                :precision="0"
                style="width: 140px"
              />
            </el-form-item>
            <el-form-item label="配平系数">
              <el-input-number
                v-model="balanceCoeff"
                :min="0"
                :max="2"
                :step="0.1"
                :precision="2"
                style="width: 120px"
              />
            </el-form-item>
          </el-form>

          <div class="action-row">
            <el-button
              :type="manualDirection === '23' ? 'success' : 'danger'"
              size="large"
              :icon="manualDirection === '23' ? Top : Bottom"
              :disabled="!canManualSubmit"
              :loading="submitting"
              @click="onManualSubmit"
              class="big-btn"
            >
              {{ manualDirection === '23' ? '下买单' : '下卖单' }}
              <div class="btn-sub">{{ formatNumber(manualVolume) }} 股 × ¥{{ formatPrice(orderPrice) }}</div>
            </el-button>
          </div>

          <div class="hint" v-if="insufficientCash">
            ⚠ 资金不足：需要 ¥{{ formatAmount(balanceAmount) }}，可用 ¥{{ formatAmount(asset?.cash || 0) }}
          </div>
          <div class="hint warn" v-if="insufficientPosition">
            ⚠ 持仓不足：需要 {{ formatNumber(Math.abs(balanceQty)) }} 股，可用 {{ formatNumber(currentVolume) }} 股
          </div>
        </div>
      </el-card>

      <el-card class="balance-card" shadow="hover">
        <template #header>
          <span class="card-title">⚖ 配平计算</span>
        </template>
        <div class="action-body">
          <el-form :inline="true" class="order-form">
            <el-form-item label="目标持仓">
              <el-input-number
                v-model="targetVolume"
                :min="0"
                :step="100"
                :precision="0"
                style="width: 140px"
              />
            </el-form-item>
            <el-form-item label="配平系数">
              <el-input-number
                v-model="balanceCoeff"
                :min="0"
                :max="2"
                :step="0.1"
                :precision="2"
                style="width: 120px"
              />
            </el-form-item>
          </el-form>

          <div class="balance-result">
            <div class="balance-row" :class="direction">
              <span class="balance-icon">
                <el-icon v-if="direction === 'buy'"><Top /></el-icon>
                <el-icon v-else-if="direction === 'sell'"><Bottom /></el-icon>
                <el-icon v-else><Check /></el-icon>
              </span>
              <span class="balance-text">
                <template v-if="direction === 'flat'">已配平</template>
                <template v-else>
                  <strong>{{ direction === 'buy' ? '需买入' : '需卖出' }}</strong>
                  <span class="text-mono big-num">{{ formatNumber(Math.abs(balanceQty)) }}</span>
                  股
                </template>
              </span>
            </div>
            <div class="balance-detail">
              <div>差额: <span class="text-mono">{{ delta > 0 ? '+' : '' }}{{ formatNumber(delta) }}</span> 股</div>
              <div>金额: <span class="text-mono">¥{{ formatAmount(balanceAmount) }}</span></div>
              <div v-if="hasQuote">单价: <span class="text-mono">¥{{ formatPrice(lastPrice) }}</span></div>
            </div>
          </div>

          <div class="action-row">
            <el-button
              :type="direction === 'buy' ? 'success' : (direction === 'sell' ? 'danger' : 'info')"
              size="large"
              :disabled="direction === 'flat' || !canBalanceSubmit"
              :loading="submitting"
              @click="onOneClickBalance"
              class="big-btn full"
            >
              一键配平{{ direction === 'flat' ? '（无差额）' : (direction === 'buy' ? '买入' : '卖出') }}
              <div class="btn-sub" v-if="direction !== 'flat'">
                {{ formatNumber(Math.abs(balanceQty)) }} 股 × ¥{{ formatPrice(orderPrice) }}
              </div>
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 持仓选择弹窗 -->
    <el-dialog v-model="showPicker" title="选择持仓" width="500px">
      <el-table :data="holdingsPositions" @row-click="onPickPosition">
        <el-table-column prop="stock_code" label="代码" width="120" />
        <el-table-column prop="volume" label="持仓" align="right">
          <template #default="{ row }">{{ formatNumber(row.volume || row.total) }}</template>
        </el-table-column>
        <el-table-column label="现价" align="right">
          <template #default="{ row }">
            {{ formatPrice(quoteStore.getLastPrice(row.stock_code)) }}
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Top, Bottom, List, Check } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useAssetStore } from '../stores/asset'
import { useQuoteStore } from '../stores/quote'
import { useT0Balance } from '../composables/useT0Balance'
import { api } from '../api'
import { t0StatsApi } from '../api/t0_stats'
import { formatNumber, formatPrice, formatAmount } from '../utils/format'

const holdingsStore = useHoldingsStore()
const assetStore = useAssetStore()
const quoteStore = useQuoteStore()
const { positions } = storeToRefs(holdingsStore)
const { asset } = storeToRefs(assetStore)

const stockCode = ref('600519.SH')
const showPicker = ref(false)
const submitting = ref(false)

// T0 配平 composable
const t0 = useT0Balance(stockCode)
const {
  targetVolume, balanceCoeff, priceType, limitPrice,
  currentVolume, cost,
  lastPrice, changePct, isStale, hasQuote,
  marketValue, costTotal, profit, profitRate,
  delta, direction, balanceQty, balanceAmount,
  orderPrice,
  oneClickBuyQty, oneClickSellQty,
  insufficientCash, insufficientPosition,
} = t0

// 手动下单
const manualDirection = ref('23')   // 23=买 24=卖
const manualVolume = ref(100)
const priceTypeLabel = computed(() => {
  return { latest: '最新', oppose: '对手', limit: '限价', market: '市价' }[priceType.value] || ''
})

// 持仓列表
const holdingsPositions = computed(() => positions.value)

// 颜色 class
const priceClass = computed(() => {
  if (changePct.value == null) return ''
  return changePct.value >= 0 ? 'up' : 'down'
})
const profitClass = computed(() => profit.value >= 0 ? 'up' : 'down')
const t0Class = computed(() => t0Stats.value.total_pnl >= 0 ? 'up' : 'down')

// T0 统计
const t0Stats = ref({
  TRD_DATE: '', stock_code: '',
  today_buy_volume: 0, today_sell_volume: 0,
  today_buy_amount: 0, today_sell_amount: 0,
  realized_pnl: 0, cost_basis: 0, position_volume: 0,
  position_cost_total: 0, unrealized_pnl: 0, total_pnl: 0,
  order_count: 0, trade_count: 0, open_order_count: 0
})

async function loadT0Stats() {
  if (!stockCode.value) return
  try {
    t0Stats.value = await t0StatsApi.get(stockCode.value)
  } catch (e) {
    console.warn('T0 stats load failed:', e)
  }
}

function onStockCodeChange() {
  loadT0Stats()
}

function onPickPosition(row) {
  stockCode.value = row.stock_code
  showPicker.value = false
  loadT0Stats()
}

// 校验
const canBuy = computed(() => hasQuote.value && oneClickBuyQty.value > 0)
const canSell = computed(() => currentVolume.value > 0)
const canManualSubmit = computed(() => {
  if (!hasQuote.value || manualVolume.value <= 0) return false
  if (priceType.value === 'limit' && !limitPrice.value) return false
  return true
})
const canBalanceSubmit = computed(() =>
  hasQuote.value && balanceQty.value !== 0 && !insufficientCash.value && !insufficientPosition.value
)

// 提交下单
async function submitOrder({ orderType, volume, price }) {
  submitting.value = true
  try {
    const priceTypeCode = priceType.value === 'market' ? 44
      : priceType.value === 'oppose' ? 14
      : 11  // 'latest' / 'limit'
    const res = await api.placeOrder({
      stock_code: stockCode.value,
      order_type: orderType,
      price_type: priceTypeCode,
      price: price,
      volume: volume,
      t0_coefficient: balanceCoeff.value,
    })
    if (res.code === 0) {
      const dir = orderType === '23' ? '买' : '卖'
      ElMessage.success(`${dir}单已报：${volume} 股 @ ¥${formatPrice(price)}`)
      loadT0Stats()
    } else {
      ElMessage.error(res.msg || res.error || '下单失败')
    }
  } catch (e) {
    const detail = e?.response?.data?.detail
    const code = detail?.code
    if (code === 'TRADING_DAY_NOT_INIT') {
      ElMessageBox.confirm(
        '当前未做日初处理，无法交易。是否前往系统初始化？',
        '需要日初',
        { confirmButtonText: '前往', cancelButtonText: '取消', type: 'warning' }
      ).then(() => {
        // router 没有直接引入，用 location 兜底
        window.location.href = '/system-init'
      }).catch(() => {})
    } else if (code === 'OUTSIDE_TRADING_SESSION') {
      ElMessage.warning(detail.msg || '非交易时段，仅可查询')
    } else {
      ElMessage.error(detail?.msg || e.message || '下单失败')
    }
  } finally {
    submitting.value = false
  }
}

function onOneClickBuy() {
  if (!canBuy.value) return
  submitOrder({ orderType: '23', volume: oneClickBuyQty.value, price: orderPrice.value })
}
function onOneClickSell() {
  if (!canSell.value) return
  submitOrder({ orderType: '24', volume: oneClickSellQty.value, price: orderPrice.value })
}
function onManualSubmit() {
  if (!canManualSubmit.value) return
  submitOrder({ orderType: manualDirection.value, volume: manualVolume.value, price: orderPrice.value })
}
function onOneClickBalance() {
  if (!canBalanceSubmit.value) return
  const orderType = direction.value === 'buy' ? '23' : '24'
  submitOrder({ orderType, volume: Math.abs(balanceQty.value), price: orderPrice.value })
}

// 监听 stockCode 变化 → 加载 stats
watch(stockCode, () => loadT0Stats())

// 监听成交推送 → 自动刷新 stats
let _unwatchTrades = null
onMounted(async () => {
  await loadT0Stats()
  // 监听 trades 变化（ws 推送会触发）
  _unwatchTrades = watch(
    () => holdingsStore.trades?.length,
    () => loadT0Stats()
  )
})
onUnmounted(() => {
  if (_unwatchTrades) _unwatchTrades()
})
</script>

<style scoped>
.t0-trade {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.content-card,
.content-card-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.content-card {
  padding: 16px 20px;
  background: var(--el-bg-color);
  border-radius: 8px;
  align-items: center;
  justify-content: space-between;
  min-height: 60px;
}

.quote-bar {
  display: flex;
  align-items: center;
  gap: 24px;
}

.quote-left {
  display: flex;
  gap: 8px;
  align-items: center;
}

.quote-mid {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.quote-mid.placeholder {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.price-line {
  display: flex;
  gap: 12px;
  align-items: baseline;
}

.last-price {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--mono-font);
}

.change {
  font-size: 16px;
  font-weight: 500;
}

.up { color: #f56c6c; }   /* A股红涨绿跌 */
.down { color: #67c23a; }

.quote-meta {
  font-size: 12px;
  margin-top: 4px;
}

.stale { color: var(--el-color-warning); }
.fresh { color: var(--el-color-success); }

.content-card-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.metric-card,
.action-card,
.balance-card {
  flex: 1;
  min-width: 280px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}

.metric-body,
.action-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 0;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 4px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.metric-row:last-child {
  border-bottom: none;
}

.metric-row .label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.metric-row .value {
  font-size: 14px;
  font-weight: 500;
}

.metric-row.big .value.big {
  font-size: 22px;
  font-weight: 700;
}

.action-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.big-btn {
  height: 60px !important;
  font-size: 16px !important;
  font-weight: 600 !important;
  display: flex !important;
  flex-direction: column !important;
  align-items: center !important;
  justify-content: center !important;
  flex: 1;
  min-width: 160px;
}

.big-btn.full {
  flex: 1 1 100%;
}

.btn-sub {
  font-size: 11px;
  font-weight: 400;
  opacity: 0.85;
  margin-top: 2px;
}

.order-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.balance-result {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px 16px;
  margin: 8px 0;
}

.balance-row {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  margin-bottom: 8px;
}

.balance-row.buy { color: #f56c6c; }
.balance-row.sell { color: #67c23a; }
.balance-row.flat { color: var(--el-color-info); }

.balance-icon { font-size: 24px; }

.big-num {
  font-size: 28px;
  font-weight: 700;
  margin: 0 4px;
  font-family: var(--mono-font);
}

.balance-detail {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 4px 8px;
}

.hint.warn {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  border-radius: 4px;
}

.text-mono {
  font-family: var(--mono-font);
}

.sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: 4px;
}

@media (max-width: 768px) {
  .content-card-row {
    grid-template-columns: 1fr;
  }
}
</style>

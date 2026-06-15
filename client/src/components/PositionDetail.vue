<template>
  <div class="pos-detail">
    <!-- 概览卡片 -->
    <div class="detail-summary">
      <div class="summary-card">
        <div class="sc-label">做T收益</div>
        <div class="sc-value text-mono" :class="profit >= 0 ? 'text-up' : 'text-down'">
          ¥{{ profit.toFixed(2) }}
        </div>
        <div class="sc-sub">
          {{ profit >= 0 ? '盈利' : '亏损' }}
        </div>
      </div>
      <div class="summary-card">
        <div class="sc-label">需买回</div>
        <div class="sc-value text-mono" :class="needBuyBack > 0 ? 'text-down' : ''">
          {{ needBuyBack }} 股
        </div>
        <div class="sc-sub">{{ needBuyBack > 0 ? '低于期初' : '已达期初' }}</div>
      </div>
    </div>

    <!-- 持仓信息 -->
    <div v-if="position" class="detail-pos">
      <div class="dp-row">
        <span class="dp-label">期初</span>
        <span class="dp-value text-mono">{{ position.last_vol }}</span>
      </div>
      <div class="dp-row">
        <span class="dp-label">今日买入</span>
        <span class="dp-value text-mono text-up">+{{ position.today_buy }}</span>
      </div>
      <div class="dp-row">
        <span class="dp-label">今日卖出</span>
        <span class="dp-value text-mono text-down">-{{ position.today_sell }}</span>
      </div>
      <div class="dp-row">
        <span class="dp-label">可用</span>
        <span class="dp-value text-mono">{{ position.avl_vol }}</span>
      </div>
      <div class="dp-row total">
        <span class="dp-label">总持仓</span>
        <span class="dp-value text-mono">{{ position.vol }}</span>
      </div>
    </div>

    <!-- 委托/成交 切换 -->
    <div class="detail-tabs">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="时间线" name="timeline">
          <div class="timeline">
            <div
              v-for="(item, idx) in orderTradeList"
              :key="idx"
              class="tl-item"
              :class="item.order_type === '23' ? 'tl-buy' : 'tl-sell'"
            >
              <div class="tl-marker">
                <div class="tl-dot"></div>
                <div class="tl-line" v-if="idx !== orderTradeList.length - 1"></div>
              </div>
              <div class="tl-content">
                <div class="tl-head">
                  <span class="tl-type">{{ item.type }} · {{ item.order_type === '23' ? '买入' : '卖出' }}</span>
                  <span class="tl-time text-mono text-secondary">{{ item.time }}</span>
                </div>
                <div class="tl-body text-mono">
                  {{ item.volume }} 股 @ ¥{{ item.price.toFixed(2) }}
                  <span class="tl-status" v-if="item.status !== '-'">
                    · <OrderStatusBadge :status="item.statusKey" size="sm" :remark="item.remark" :status_msg="item.status_msg" />
                  </span>
                </div>
              </div>
            </div>
            <el-empty v-if="orderTradeList.length === 0" description="无委托/成交" :image-size="80" />
          </div>
        </el-tab-pane>
        <el-tab-pane label="表格" name="table">
          <el-table :data="orderTradeList" size="small" style="width: 100%" max-height="400">
            <el-table-column prop="time" label="时间" width="90" />
            <el-table-column prop="type" label="类型" width="70">
              <template #default="{ row }">
                <el-tag :type="row.type === '委托' ? 'info' : 'success'" size="small" effect="light">
                  {{ row.type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="order_type" label="方向" width="60">
              <template #default="{ row }">
                <span class="dir-chip" :class="row.order_type === '23' ? 'buy' : 'sell'">
                  {{ row.order_type === '23' ? '买' : '卖' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="volume" label="数量" align="right" width="80" />
            <el-table-column prop="price" label="价格" align="right" width="80">
              <template #default="{ row }">
                <span class="text-mono">{{ row.price.toFixed(2) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="statusLabel" label="状态" width="110">
              <template #default="{ row }">
                <OrderStatusBadge v-if="row.statusKey" :status="row.statusKey" :remark="row.remark" :status_msg="row.status_msg" />
                <span v-else class="text-secondary">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import OrderStatusBadge from './OrderStatusBadge.vue'
import { STATUS_LABEL } from '../utils/format'

const props = defineProps({
  orders: { type: Array, default: () => [] },
  trades: { type: Array, default: () => [] },
  position: { type: Object, default: null },
  stockCode: { type: String, default: '' }
})

const activeTab = ref('timeline')

const orderTradeList = computed(() => {
  const list = []
  for (const order of props.orders) {
    list.push({
      time: order.order_time,
      type: '委托',
      order_type: order.order_type,
      volume: order.volume,
      price: order.price,
      status: STATUS_LABEL[order.status] || order.status,
      statusKey: order.status,
      remark: order.remark || '',
      status_msg: order.status_msg || '',
      order_id: order.order_id
    })
  }
  for (const trade of props.trades) {
    list.push({
      time: trade.trade_time,
      type: '成交',
      order_type: trade.order_type,
      volume: trade.volume,
      price: trade.price,
      status: '-',
      statusKey: '',
      order_id: trade.order_id
    })
  }
  return list.sort((a, b) => (b.time || '').localeCompare(a.time || ''))
})

const profit = computed(() => {
  if (!props.position) return 0
  const { today_buy, today_sell } = props.position
  const buyVolume = Math.min(today_buy, today_sell)

  const totalBuy = props.trades
    .filter((t) => t.order_type === '23')
    .reduce((sum, t) => sum + t.volume * t.price, 0)
  const totalSell = props.trades
    .filter((t) => t.order_type === '24')
    .reduce((sum, t) => sum + t.volume * t.price, 0)

  const avgBuy = today_buy > 0 ? totalBuy / today_buy : 0
  const avgSell = today_sell > 0 ? totalSell / today_sell : 0
  return (avgSell - avgBuy) * buyVolume
})

const needBuyBack = computed(() => {
  if (!props.position) return 0
  const { last_vol, vol } = props.position
  return Math.max(0, last_vol - vol)
})
</script>

<style scoped>
.pos-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.detail-summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.summary-card {
  background: var(--bg-soft);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.sc-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.sc-value {
  font-size: 22px;
  font-weight: 700;
  margin-top: var(--space-2);
}

.sc-sub {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.detail-pos {
  background: var(--bg-soft);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
}

.dp-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--border-light);
}

.dp-row:last-child {
  border-bottom: none;
}

.dp-row.total {
  font-weight: 600;
}

.dp-label {
  color: var(--text-secondary);
}

.dp-value {
  color: var(--text-primary);
}

.timeline {
  padding: var(--space-2) 0;
}

.tl-item {
  display: flex;
  gap: var(--space-3);
  padding-bottom: var(--space-4);
}

.tl-marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 4px;
}

.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid;
  flex-shrink: 0;
}

.tl-buy .tl-dot { border-color: var(--color-up); background: var(--color-up-bg); }
.tl-sell .tl-dot { border-color: var(--color-down); background: var(--color-down-bg); }

.tl-line {
  flex: 1;
  width: 2px;
  background: var(--border-light);
  margin-top: 4px;
}

.tl-content {
  flex: 1;
  padding-bottom: var(--space-2);
}

.tl-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.tl-type {
  font-weight: 600;
  font-size: 13px;
}

.tl-buy .tl-type { color: var(--color-up); }
.tl-sell .tl-type { color: var(--color-down); }

.tl-time {
  font-size: 12px;
}

.tl-body {
  font-size: 13px;
  color: var(--text-regular);
  margin-top: 4px;
}

.tl-status {
  color: var(--text-secondary);
  margin-left: 4px;
}

.dir-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  padding: 2px 8px;
  border-radius: var(--radius-xs);
  font-size: 12px;
  font-weight: 600;
}

.dir-chip.buy {
  background: var(--color-up-bg);
  color: var(--color-up);
}

.dir-chip.sell {
  background: var(--color-down-bg);
  color: var(--color-down);
}
</style>

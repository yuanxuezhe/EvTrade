<template>
  <div class="position-detail">
    <div class="detail-header">
      <h3>{{ stockCode }} 委托/成交明细</h3>
    </div>

    <el-table :data="orderTradeList" style="width: 100%" size="small">
      <el-table-column prop="time" label="时间" width="100" />
      <el-table-column prop="type" label="类型" width="60">
        <template #default="{ row }">
          <el-tag :type="row.type === '委托' ? 'info' : 'success'" size="small">
            {{ row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="direction" label="方向" width="60">
        <template #default="{ row }">
          <span :class="row.direction === 'BUY' ? 'text-buy' : 'text-sell'">
            {{ row.direction === 'BUY' ? '买入' : '卖出' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="volume" label="数量" width="100" align="right" />
      <el-table-column prop="price" label="价格" width="100" align="right">
        <template #default="{ row }">
          {{ row.price.toFixed(2) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="80" />
      <el-table-column prop="order_id" label="委托号" />
    </el-table>

    <div class="summary">
      <div class="profit">
        做T收益: <span :class="profit >= 0 ? 'text-buy' : 'text-sell'">¥{{ profit.toFixed(2) }}</span>
      </div>
      <div class="rebalance">
        需买回: <span class="text-sell">{{ needBuyBack }}股</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  orders: { type: Array, default: () => [] },
  trades: { type: Array, default: () => [] },
  position: { type: Object, default: null },
  stockCode: { type: String, default: '' }
})

const orderTradeList = computed(() => {
  const list = []

  for (const order of props.orders) {
    list.push({
      time: order.order_time,
      type: '委托',
      direction: order.direction,
      volume: order.volume,
      price: order.price,
      status: order.status === 'filled' ? '成交' : order.status,
      order_id: order.order_id
    })
  }

  for (const trade of props.trades) {
    list.push({
      time: trade.trade_time,
      type: '成交',
      direction: trade.direction,
      volume: trade.volume,
      price: trade.price,
      status: '-',
      order_id: trade.order_id
    })
  }

  return list.sort((a, b) => a.time.localeCompare(b.time))
})

const profit = computed(() => {
  if (!props.position) return 0
  const { today_buy, today_sell } = props.position
  const buyVolume = Math.min(today_buy, today_sell)

  const totalBuy = props.trades
    .filter(t => t.direction === 'BUY')
    .reduce((sum, t) => sum + t.volume * t.price, 0)
  const totalSell = props.trades
    .filter(t => t.direction === 'SELL')
    .reduce((sum, t) => sum + t.volume * t.price, 0)

  const avgBuy = today_buy > 0 ? totalBuy / today_buy : 0
  const avgSell = today_sell > 0 ? totalSell / today_sell : 0

  return (avgSell - avgBuy) * buyVolume
})

const needBuyBack = computed(() => {
  if (!props.position) return 0
  const { initial_position, total } = props.position
  return initial_position - total
})
</script>

<style scoped>
.position-detail {
  margin-top: 20px;
  padding: 15px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
}
.detail-header h3 {
  margin: 0 0 15px 0;
}
.summary {
  margin-top: 15px;
  display: flex;
  gap: 30px;
  font-size: 16px;
}
.text-buy { color: #f56c6c; }
.text-sell { color: #67c23a; }
</style>
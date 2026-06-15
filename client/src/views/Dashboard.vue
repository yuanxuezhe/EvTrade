<template>
  <div class="dashboard fade-in-up">
    <!-- KPI 卡片 -->
    <section class="stats-grid">
      <StatCard
        label="总资产"
        :value="displayTotalAsset"
        prefix="¥"
        :trend="0.85"
        icon="Wallet"
        accent="primary"
        sublabel="账户总市值"
      />
      <StatCard
        label="可用资金"
        :value="displayCash"
        prefix="¥"
        icon="Money"
        accent="info"
        sublabel="可用于交易"
      />
      <StatCard
        label="持仓市值"
        :value="displayMarketValue"
        prefix="¥"
        icon="DataAnalysis"
        accent="warning"
        :sublabel="`${positionCount} 只持仓`"
      />
      <StatCard
        label="今日盈亏"
        :value="todayPnL"
        prefix="¥"
        :trend="todayPnLPercent"
        icon="TrendCharts"
        :accent="todayPnL >= 0 ? 'up' : 'down'"
        sublabel="基于今日成交估算"
      />
    </section>

    <!-- 资产分布 + 委托概况 -->
    <section class="overview-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">资产分布</h3>
            <p class="panel-sub">现金 vs 持仓市值</p>
          </div>
          <el-tag size="small" type="info" effect="plain">实时</el-tag>
        </div>
        <EChart :option="assetChartOption" height="280px" />
      </div>

      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">委托概况</h3>
            <p class="panel-sub">今日委托状态分布</p>
          </div>
          <router-link to="/orders" class="link-more">
            查看全部 <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
        <div class="order-stats">
          <div class="order-stat" v-for="s in orderStats" :key="s.key">
            <div class="order-stat-bar">
              <div
                class="order-stat-fill"
                :style="{ width: `${s.percent}%`, background: s.color }"
              ></div>
            </div>
            <div class="order-stat-meta">
              <span class="order-stat-label">
                <span class="dot" :style="{ background: s.color }"></span>
                {{ s.label }}
              </span>
              <span class="order-stat-value text-mono">{{ s.count }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 持仓 + 最近委托 -->
    <section class="lower-grid">
      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">持仓 Top 5</h3>
            <p class="panel-sub">按市值排序</p>
          </div>
          <router-link to="/positions" class="link-more">
            查看全部 <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
        <el-table :data="topPositions" :show-header="true" size="default">
          <el-table-column prop="stock_code" label="代码" width="120">
            <template #default="{ row }">
              <div class="stock-cell">
                <div class="stock-code">{{ row.stock_code }}</div>
                <div class="stock-name">{{ row.stock_name || '--' }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="vol" label="持仓量" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ formatNumber(row.vol) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="avl_vol" label="可用" align="right">
            <template #default="{ row }">
              <span class="text-mono">{{ formatNumber(row.avl_vol) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="今日变动" align="right">
            <template #default="{ row }">
              <div class="change-cell">
                <span v-if="row.today_buy > 0" class="text-up text-mono">+{{ row.today_buy }}</span>
                <span v-if="row.today_sell > 0" class="text-down text-mono">-{{ row.today_sell }}</span>
                <span v-if="!row.today_buy && !row.today_sell" class="text-secondary">--</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="topPositions.length === 0" description="暂无持仓" :image-size="80" />
      </div>

      <div class="content-card panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">最近委托</h3>
            <p class="panel-sub">今日最新 6 条</p>
          </div>
          <router-link to="/trade" class="link-more">
            前往交易 <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
        <div class="activity-list">
          <div
            v-for="order in recentOrders"
            :key="order.order_id"
            class="activity-item"
          >
            <div class="activity-marker" :class="order.order_type === '23' ? 'buy' : 'sell'">
              {{ order.order_type === '23' ? '买' : '卖' }}
            </div>
            <div class="activity-main">
              <div class="activity-top">
                <span class="activity-stock">{{ order.stock_code }}</span>
                <span class="activity-time text-secondary">{{ order.order_time }}</span>
              </div>
              <div class="activity-bottom">
                <span class="text-mono text-secondary">
                  {{ formatNumber(order.volume) }} 股 @ ¥{{ formatMoney(order.price) }}
                </span>
                <OrderStatusBadge :status="order.status" :remark="order.remark" :status_msg="order.status_msg" />
              </div>
            </div>
          </div>
          <el-empty v-if="recentOrders.length === 0" description="暂无委托" :image-size="80" />
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import StatCard from '../components/StatCard.vue'
import EChart from '../components/EChart.vue'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'
import { useAssetStore } from '../stores/asset'
import { useOrderStore } from '../stores/order'
import { usePositionStore } from '../stores/position'
import { useHoldingsStore } from '../stores/holdings'
import { useUiStore } from '../stores/ui'
import { formatMoney, formatNumber, STATUS_LABEL, STATUS_TYPE } from '../utils/format'

const assetStore = useAssetStore()
const orderStore = useOrderStore()
const positionStore = usePositionStore()
const holdingsStore = useHoldingsStore()
const uiStore = useUiStore()

/**
 * 持仓市值：初始值从 holdings.cachedAsset.market_value（后端查询）
 *         之后用 holdings.liveMarketValue（实时重算）覆盖
 * 总资产同理。
 *
 * 优先实时值；当且仅当实时全空时（holdings 还没 bootstrap 完）
 * 才用 cachedAsset 作兜底。
 */
const displayMarketValue = computed(() => {
  const live = holdingsStore.liveMarketValue
  if (live.withQuote > 0) return live.sum
  return holdingsStore.cachedAsset.market_value || assetStore.asset.market_value || 0
})
const displayTotalAsset = computed(() => {
  return holdingsStore.liveTotalAsset || holdingsStore.cachedAsset.total_asset
    || assetStore.asset.total_asset || 0
})
const displayCash = computed(() =>
  holdingsStore.cachedAsset.cash || assetStore.asset.cash || 0
)
const displayFrozen = computed(() =>
  holdingsStore.cachedAsset.frozen_cash || assetStore.asset.frozen_cash || 0
)
const positionCount = computed(() => holdingsStore.positions.length)

const topPositions = computed(() =>
  [...holdingsStore.positions]
    .sort((a, b) => (b.vol || 0) - (a.vol || 0))
    .slice(0, 5)
)

const recentOrders = computed(() =>
  [...holdingsStore.orders]
    .sort((a, b) => (b.order_time || '').localeCompare(a.order_time || ''))
    .slice(0, 6)
)

const todayPnL = computed(() => {
  let buy = 0
  let sell = 0
  for (const t of orderStore.trades) {
    if (t.order_type === '23') buy += t.volume * t.price
    else if (t.order_type === '24') sell += t.volume * t.price
  }
  return sell - buy
})

const todayPnLPercent = computed(() => {
  const base = assetStore.asset.total_asset || 1
  return (todayPnL.value / base) * 100
})

const orderStats = computed(() => {
  const orders = orderStore.orders
  const total = orders.length || 1
  // 按 tone 分组聚合 11 个细粒度状态（柜台数字）
  //   48 未报 / 49 待报 / 50 已报
  //   51 已报待撤 / 52 部成待撤 / 53 部撤 / 54 已撤
  //   55 部成 / 56 已成 / 57 废单 / 255 未知
  const groups = [
    {
      key: 'done',
      label: '已成交',
      color: '#16b572',
      statuses: ['56']
    },
    {
      key: 'working',
      label: '部分成交',
      color: '#ffa726',
      statuses: ['55', '52', '53']
    },
    {
      key: 'pending',
      label: '已报/待报',
      color: '#5fa8ff',
      statuses: ['50', '49', '48']
    },
    {
      key: 'terminal',
      label: '已撤单',
      color: '#a0aec0',
      statuses: ['54', '51']
    },
    {
      key: 'rejected',
      label: '废单',
      color: '#e85d75',
      statuses: ['57']
    }
  ]
  return groups.map((g) => {
    const count = orders.filter((o) => g.statuses.includes(String(o.status || ''))).length
    return { ...g, count, percent: (count / total) * 100 }
  })
})

const assetChartOption = computed(() => {
  const cash = Number(displayCash.value) || 0
  const frozen = Number(displayFrozen.value) || 0
  const market = Number(displayMarketValue.value) || 0
  const isDark = uiStore.theme === 'dark'
  return {
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>¥{c} ({d}%)',
      backgroundColor: isDark ? '#1a2138' : '#ffffff',
      borderColor: isDark ? '#2e3e60' : '#e8edf5',
      textStyle: { color: isDark ? '#e7ecf5' : '#1a2238' }
    },
    legend: {
      bottom: 0,
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: isDark ? '#b9c2d4' : '#4a5568' }
    },
    color: ['#4f7cff', '#7c5cff', '#16b572'],
    series: [
      {
        name: '资产分布',
        type: 'pie',
        radius: ['55%', '78%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: isDark ? '#141a2e' : '#ffffff',
          borderWidth: 3
        },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 600,
            color: isDark ? '#e7ecf5' : '#1a2238',
            formatter: '{b}\n¥{c}'
          }
        },
        labelLine: { show: false },
        data: [
          { value: cash, name: '可用资金' },
          { value: frozen, name: '冻结资金' },
          { value: market, name: '持仓市值' }
        ]
      }
    ]
  }
})

onMounted(async () => {
  // Dashboard 数据获取：
  //   - 持仓/资金：App 启动时 holdings store 已 bootstrap，这里只做兜底
  //   - 委托/成交：仍由本页拉（holdings 不管这两个）
  //   - 持仓 top 5：从 holdings.positions 读（统一来源）
  await Promise.all([
    assetStore.fetchAsset(),
    orderStore.fetchOrders(),
    orderStore.fetchTrades()
  ])
  // 兜底：若 holdings 还没 bootstrap（例如直接打开 /dashboard）
  if (!holdingsStore.bootstrapped) {
    holdingsStore.bootstrap()
  }
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-5);
}

.overview-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

.lower-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: var(--space-5);
}

.panel {
  padding: var(--space-5);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-4);
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.link-more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--brand-primary);
  text-decoration: none;
  transition: gap var(--transition-fast);
}

.link-more:hover {
  gap: 6px;
}

.order-stats {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.order-stat-bar {
  height: 6px;
  background: var(--bg-soft);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.order-stat-fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width 500ms;
}

.order-stat-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  font-size: 13px;
}

.order-stat-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-regular);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.order-stat-value {
  color: var(--text-primary);
  font-weight: 600;
}

.stock-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stock-code {
  font-weight: 600;
  color: var(--text-primary);
}

.stock-name {
  font-size: 11px;
  color: var(--text-secondary);
}

.change-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 13px;
}

.activity-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.activity-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  background: var(--bg-soft);
  border: 1px solid transparent;
  transition: all var(--transition-fast);
}

.activity-item:hover {
  border-color: var(--border-base);
  background: var(--bg-elevated);
  box-shadow: var(--shadow-xs);
}

.activity-marker {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  font-weight: 700;
  font-size: 13px;
  color: white;
  flex-shrink: 0;
}

.activity-marker.buy { background: var(--color-up-gradient); }
.activity-marker.sell { background: var(--color-down-gradient); }

.activity-main {
  flex: 1;
  min-width: 0;
}

.activity-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.activity-stock {
  font-weight: 600;
  color: var(--text-primary);
}

.activity-time {
  font-size: 12px;
  font-family: var(--font-mono);
}

.activity-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}

@media (max-width: 1280px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .overview-grid, .lower-grid { grid-template-columns: 1fr; }
}
</style>

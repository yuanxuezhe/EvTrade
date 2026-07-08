<template>
  <div class="t0-trade fade-in-up">
    <!-- Header + 设置条 (方案2: 设置条在标题右侧) -->
    <div class="t0-header">
      <span class="t0-title">⚡ 快速做T</span>
      <div class="qs-row">
        <span class="qs-label">仓位</span>
        <el-radio-group v-model="quickPct" size="small">
          <el-radio-button
            v-for="p in PCT_OPTIONS"
            :key="p"
            :value="p"
            :label="String(p) + '%'"
          />
        </el-radio-group>
        <span class="qs-divider">|</span>
        <span class="qs-label">价格档</span>
        <el-radio-group v-model="quickPriceType" size="small">
          <el-radio-button
            v-for="opt in PRICE_TYPE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </el-radio-group>
        <el-button size="small" @click="holdingsStore.refreshPositions()" :loading="refreshing">刷新</el-button>
      </div>
    </div>

    <!-- quota frame: 5 个账户级 metric pill (change-quota-frame) -->
    <div class="quota-frame">
      <!-- v18: T0 任务快速选择器 (按当前选中 stock_code 自动过滤) -->
      <el-tooltip content="选择/取消当前做T归属的 task；新建请用下方按钮" placement="top">
        <el-select
          v-model="selectedTaskId"
          placeholder="归属 task (可选)"
          clearable
          size="small"
          filterable
          class="t0-task-quick-select"
          @clear="selectedTaskId = null"
          no-data-text="暂无活跃 task，请新建"
        >
          <el-option
            v-for="t in filteredActiveTasks"
            :key="t.id"
            :value="t.id"
            :label="`#${t.id} ${t.stock_code} (base+target=${t.base_volume + t.target_volume})`"
          />
        </el-select>
      </el-tooltip>
      <el-button size="small" link type="primary" @click="onManageTasks">
        管理任务
      </el-button>
      <span class="qs-divider">|</span>
      <div class="qf-pill" data-pill="cashAvail">
        <span class="qf-label">现金余量</span>
        <span class="qf-value text-mono">¥{{ formatAmount(quotaAggregate.cashAvail) }}</span>
      </div>
      <div class="qf-pill" data-pill="frozenCash">
        <span class="qf-label">冻结资金</span>
        <span class="qf-value text-mono">¥{{ formatAmount(quotaAggregate.frozenCash) }}</span>
      </div>
      <div class="qf-pill" data-pill="t0AvailVol">
        <span class="qf-label">T+0 可用持仓</span>
        <span class="qf-value text-mono">{{ formatNumber(quotaAggregate.t0AvailVol) }}</span>
      </div>
      <div class="qf-pill" data-pill="todayPnl" :class="todayPnlClass">
        <span class="qf-label">今日已盈亏</span>
        <span class="qf-value text-mono">{{ todayPnlText }}</span>
      </div>
      <div class="qf-pill qf-pill--desktop-only" data-pill="marketValue">
        <span class="qf-label">持仓市值</span>
        <span class="qf-value text-mono">¥{{ formatAmount(quotaAggregate.marketValue) }}</span>
      </div>
    </div>

    <!-- 主表 (占视口主体, 含副行 + 操作列) -->
    <el-table
      :data="sortedRows"
      :row-class-name="ptRowClass"
      @row-click="onOpenDrawer"
      @sort-change="onSortChange"
      class="position-table"
      empty-text="暂无持仓"
      size="default"
    >
      <el-table-column prop="stock_code" label="代码" width="80" />
      <el-table-column label="名称" width="80">
        <template #default="{ row }">{{ row.stock_name || row.stock_code }}</template>
      </el-table-column>
      <el-table-column prop="vol" label="持仓" align="right" width="70" sortable="custom">
        <template #default="{ row }">{{ formatNumber(row.vol) }}</template>
      </el-table-column>
      <el-table-column prop="last_price" label="现价" align="right" width="80" sortable="custom">
        <template #default="{ row }">
          <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ formatPrice(quoteStore.getLastPrice(row.stock_code)) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="change_pct" label="涨跌" align="right" width="70" sortable="custom">
        <template #default="{ row }">
          <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ quoteStore.getChangePct(row.stock_code)?.toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- 今盈 (t0Stats realized_pnl, 按需加载) -->
      <el-table-column prop="realized_pnl" label="今盈" align="right" width="90" sortable="custom">
        <template #default="{ row }">
          <template v-if="t0StatsMap[row.stock_code]">
            <span :class="t0StatsMap[row.stock_code].realized_pnl >= 0 ? 'up' : 'down'">
              {{ (t0StatsMap[row.stock_code].realized_pnl >= 0 ? '+' : '') + formatAmount(t0StatsMap[row.stock_code].realized_pnl) }}
            </span>
          </template>
          <span v-else class="muted">--</span>
        </template>
      </el-table-column>

      <!-- 净敞口 (today_buy_volume - today_sell_volume) -->
      <el-table-column prop="net_exposure" label="净敞口" align="right" width="80" sortable="custom">
        <template #default="{ row }">
          <template v-if="t0StatsMap[row.stock_code]">
            <span :class="netExposure(row) > 0 ? 'up' : netExposure(row) < 0 ? 'down' : ''">
              {{ netExposure(row) > 0 ? '+' : '' }}{{ netExposure(row) }}
            </span>
          </template>
          <span v-else class="muted">--</span>
        </template>
      </el-table-column>

      <!-- 浮盈% (holdingsStore.getReturnRate) — 默认按此 desc -->
      <el-table-column prop="return_rate" label="浮盈%" align="right" width="70" sortable="custom">
        <template #default="{ row }">
          <span :class="holdingsStore.getReturnRate(row.stock_code) >= 0 ? 'up' : 'down'">
            {{ (holdingsStore.getReturnRate(row.stock_code) * 100).toFixed(2) }}%
          </span>
        </template>
      </el-table-column>

      <!-- quota 列 (change-quota-frame): 可买 + 可卖 -->
      <el-table-column label="可买" align="right" width="80" prop="max_buyable">
        <template #default="{ row }">
          <el-tooltip
            :content="quoteStore.getLastPrice(row.stock_code) ? `依赖最新价 ¥${formatPrice(quoteStore.getLastPrice(row.stock_code))}` : '依赖最新价, 未到时显示 0'"
            placement="top"
          >
            <span class="text-mono quota-cell" :class="`quota-${quotaLevel(quotaForRow(row).maxBuyable)}`">
              {{ formatNumber(quotaForRow(row).maxBuyable) }}
            </span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="可卖" align="right" width="80" prop="max_sellable">
        <template #default="{ row }">
          <el-tooltip content="持仓可用 vol (avl_vol)" placement="top">
            <span class="text-mono quota-cell" :class="`quota-${quotaLevel(quotaForRow(row).maxSellable)}`">
              {{ formatNumber(quotaForRow(row).maxSellable) }}
            </span>
          </el-tooltip>
        </template>
      </el-table-column>

      <!-- 操作列: 4 按钮 (买/卖/配平/详情) -->
      <el-table-column label="操作" align="center" width="200" fixed="right">
        <template #default="{ row }">
          <div class="op-col">
            <el-tooltip :content="buyState(row).tip" placement="top">
              <el-button type="primary" size="small" :disabled="buyState(row).disabled" @click.stop="onQuickBuy(row)" class="op-btn-buy">
                买{{ quickPct }}%
              </el-button>
            </el-tooltip>
            <el-tooltip :content="sellState(row).tip" placement="top">
              <el-button type="danger" size="small" :disabled="sellState(row).disabled" @click.stop="onQuickSell(row)" class="op-btn-sell">
                卖{{ quickPct }}%
              </el-button>
            </el-tooltip>
            <el-tooltip :content="balanceState(row).tip" placement="top">
              <el-button
                type="warning"
                size="small"
                :disabled="balanceState(row).disabled"
                @click.stop="onQuickBalance(row)"
                class="op-btn-balance"
              >
                {{ getBalanceLabel(row) }}
              </el-button>
            </el-tooltip>
            <el-button type="primary" link size="small" @click.stop="onOpenDrawer(row)" class="op-btn-detail">
              详情
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M5 12h14M13 5l7 7-7 7"/>
              </svg>
            </el-button>
          </div>
        </template>
      </el-table-column>

      <!-- 副行 (默认展开, 通过 expand 实现) -->
      <el-table-column type="expand" width="0">
        <template #default="{ row }">
          <div class="sub-row">
            <div class="sub-item">
              <span class="sub-label">成本</span>
              <span class="sub-value text-mono">{{ formatPrice(row.cost_price) }}</span>
            </div>
            <div class="sub-item">
              <span class="sub-label">成本额</span>
              <span class="sub-value text-mono">¥{{ formatAmount((row.cost_price || 0) * (row.vol || 0)) }}</span>
            </div>
            <div class="sub-item">
              <span class="sub-label">今笔</span>
              <span class="sub-value text-mono">
                {{ t0StatsMap[row.stock_code]?.trade_count || 0 }}
              </span>
            </div>
            <div class="sub-item">
              <span class="sub-label">胜率</span>
              <span class="sub-value text-mono">
                {{ ((t0StatsMap[row.stock_code]?.win_rate || 0) * 100).toFixed(1) }}%
              </span>
            </div>
            <div class="sub-item sub-popover" v-if="t0StatsMap[row.stock_code]">
              <span class="sub-label">30天</span>
              <el-popover
                trigger="hover"
                placement="top"
                :width="220"
                :show-after="100"
                @show="() => ensureHistory30d(row.stock_code)"
              >
                <template #reference>
                  <span class="sub-value text-mono sub-popover-ref">
                    <template v-if="history30dMap[row.stock_code]?.length > 0">
                      ¥{{ formatAmount(history30dMap[row.stock_code][history30dMap[row.stock_code].length - 1]) }}
                      <span :class="history30dMap[row.stock_code][history30dMap[row.stock_code].length - 1] >= 0 ? 'up' : 'down'">{{ history30dMap[row.stock_code][history30dMap[row.stock_code].length - 1] >= 0 ? '↑' : '↓' }}</span>
                    </template>
                    <template v-else>
                      <span class="text-secondary">hover ↗</span>
                    </template>
                  </span>
                </template>
                <div class="sub-popover-list">
                  <div v-if="!history30dMap[row.stock_code] || history30dMap[row.stock_code].length === 0" class="text-secondary text-mono" style="padding: 4px 0">
                    加载中...
                  </div>
                  <div
                    v-for="(v, i) in [...(history30dMap[row.stock_code] || [])].reverse()"
                    :key="i"
                    class="sub-popover-row"
                  >
                    <span class="text-secondary">D-{{ i }}</span>
                    <span class="text-mono" :class="v >= 0 ? 'up' : 'down'">
                      {{ v >= 0 ? '+' : '' }}{{ formatAmount(v) }}
                    </span>
                  </div>
                </div>
              </el-popover>
            </div>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 底部: 当前选中标的 30 日累计曲线 (80px 高, 7/30/90D 切换) -->
    <div class="bottom-chart" v-if="cumHistory.length > 0">
      <div class="bottom-chart-header">
        <span class="bottom-chart-label">📈 {{ stockCode || '--' }} 累计曲线</span>
        <el-radio-group v-model="historyDays" size="small" @change="loadT0History">
          <el-radio-button :value="7">7D</el-radio-button>
          <el-radio-button :value="30">30D</el-radio-button>
          <el-radio-button :value="90">90D</el-radio-button>
        </el-radio-group>
      </div>
      <svg :viewBox="`0 0 ${bottomChartW} ${bottomChartH}`" class="bottom-chart-svg" preserveAspectRatio="none">
        <line
          :x1="0" :y1="bottomZeroY"
          :x2="bottomChartW" :y2="bottomZeroY"
          stroke="#dcdfe6" stroke-width="1" stroke-dasharray="3,3"
        />
        <path
          :d="bottomCumPath"
          :stroke="cumHistory[cumHistory.length - 1]?.cum_pnl >= 0 ? '#f56c6c' : '#67c23a'"
          stroke-width="2" fill="none"
        />
        <path
          :d="bottomCumAreaPath"
          :fill="cumHistory[cumHistory.length - 1]?.cum_pnl >= 0 ? 'rgba(245,108,108,0.12)' : 'rgba(103,194,58,0.12)'"
          stroke="none"
        />
      </svg>
      <div class="bottom-chart-tip">
        累计 ¥{{ formatAmount(cumHistory[cumHistory.length - 1]?.cum_pnl || 0) }} ({{ cumHistory.length }} 天)
      </div>
    </div>

    <!-- 右侧明细抽屉 (点击行/详情打开) — 保持原有功能 -->
    <el-drawer
      v-model="drawerVisible"
      :size="drawerSize"
      direction="rtl"
      :with-header="false"
      :modal="true"
      :modal-class="'t0-drawer-modal'"
      custom-class="t0-detail-drawer"
    >
      <div class="t0-drawer" v-loading="drawerLoading">
        <header class="t0-drawer-header">
          <div class="t0-drawer-title">
            <span class="t0-drawer-code">{{ stockCode }}</span>
            <el-tag size="small" type="info" effect="plain">做T 明细</el-tag>
          </div>
          <el-button link @click="drawerVisible = false">
            <el-icon><Close /></el-icon>
          </el-button>
        </header>

        <section class="t0-drawer-stats">
          <div class="stat-block">
            <span class="stat-label">今日成交</span>
            <span class="stat-value text-mono">{{ drawerStats.trade_count || 0 }} 笔</span>
          </div>
          <div class="stat-block">
            <span class="stat-label">已实现</span>
            <span class="stat-value text-mono" :class="(drawerStats.realized_pnl || 0) >= 0 ? 'up' : 'down'">
              {{ (drawerStats.realized_pnl >= 0 ? '+' : '') + formatAmount(drawerStats.realized_pnl) }}
            </span>
          </div>
          <div class="stat-block">
            <span class="stat-label">今日买/卖</span>
            <span class="stat-value text-mono">{{ formatNumber(drawerStats.today_buy_volume) }} / {{ formatNumber(drawerStats.today_sell_volume) }}</span>
          </div>
          <div class="stat-block">
            <span class="stat-label">总盈亏</span>
            <span class="stat-value text-mono" :class="(drawerStats.total_pnl || 0) >= 0 ? 'up' : 'down'">
              {{ (drawerStats.total_pnl >= 0 ? '+' : '') + formatAmount(drawerStats.total_pnl) }}
            </span>
          </div>
        </section>

        <section class="t0-drawer-section">
          <div class="t0-drawer-section-title">
            📈 累计收益曲线
            <el-radio-group v-model="drawerDays" size="small" @change="onDrawerChangeDays">
              <el-radio-button :value="7">7 天</el-radio-button>
              <el-radio-button :value="30">30 天</el-radio-button>
              <el-radio-button :value="90">90 天</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="!drawerHistory || !drawerHistory.points || drawerHistory.points.length === 0" class="t0-drawer-empty">
            暂无历史数据
          </div>
          <div v-else class="t0-drawer-chart">
            <svg :viewBox="`0 0 ${drawerChartW} ${drawerChartH}`" preserveAspectRatio="none" width="100%" :height="drawerChartH">
              <line :x1="drawerChartPad" :y1="drawerZeroY" :x2="drawerChartW - drawerChartPad" :y2="drawerZeroY" stroke="#dcdfe6" stroke-width="1" />
              <path :d="drawerCumPath" :stroke="(drawerCumHistory[drawerCumHistory.length - 1]?.cum_pnl || 0) >= 0 ? '#f56c6c' : '#67c23a'" stroke-width="2" fill="none" />
              <path :d="drawerCumAreaPath" :fill="(drawerCumHistory[drawerCumHistory.length - 1]?.cum_pnl || 0) >= 0 ? 'rgba(245,108,108,0.12)' : 'rgba(103,194,58,0.12)'" />
            </svg>
            <div class="t0-drawer-chart-tip">
              累计 ¥{{ formatAmount(drawerCumHistory[drawerCumHistory.length - 1]?.cum_pnl || 0) }} ({{ drawerCumHistory.length }} 天)
            </div>
          </div>
        </section>

        <section class="t0-drawer-section">
          <div class="t0-drawer-section-title">📋 累计统计 (全部历史)</div>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="已实现盈亏">
              <span :class="(drawerAggregate?.summary?.realized_pnl || 0) >= 0 ? 'up' : 'down'">
                {{ formatAmount(drawerAggregate?.summary?.realized_pnl || 0) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="胜率">
              {{ ((drawerAggregate?.summary?.win_rate || 0) * 100).toFixed(1) }}%
            </el-descriptions-item>
            <el-descriptions-item label="平均回报">
              {{ ((drawerAggregate?.summary?.avg_return || 0) * 100).toFixed(2) }}%
            </el-descriptions-item>
            <el-descriptions-item label="交易笔数">
              {{ drawerAggregate?.summary?.trade_count || 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </section>

        <footer class="t0-drawer-footer">
          <el-button size="default" @click="drawerVisible = false">关闭</el-button>
        </footer>
      </div>
    </el-drawer>

    <!-- v18: T0Task 管理抽屉 -->
    <el-drawer v-model="tasksDrawerVisible" title="T0 任务管理" size="70%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskList
        :visible="tasksDrawerVisible"
        embedding="drawer"
        @detail="onOpenTaskDetail"
        @balance="onBalanceTask"
        @close="onCloseTask"
        @create="createDialogVisible = true"
      />
    </el-drawer>

    <!-- v18: T0Task 单任务详情抽屉 -->
    <el-drawer v-model="tasksDetailVisible" :title="`task #${viewingTaskId} 详情`" size="55%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskDetail v-if="tasksDetailVisible" :task-id="viewingTaskId" embedding="drawer" />
    </el-drawer>

    <!-- v18: T0Task 创建弹窗 -->
    <T0TaskCreateDialog
      v-model="createDialogVisible"
      :loading="createDialogLoading"
      :default-stock-code="stockCode"
      @submit="onCreateTaskSubmit"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { useOrderStore } from '../stores/order'
import { useAssetStore } from '../stores/asset'
import {
  PCT_OPTIONS, PRICE_TYPE_OPTIONS,
  loadQuickDefaults, saveQuickDefaults,
  isBuyDisabled, buildQuickOrder, calcBalanceQty,
} from '../composables/useQuickT0'
import {
  buyBtnState, sellBtnState, balanceBtnState,
} from '../composables/useT0TradeButtons'
import { useT0Stats } from '../composables/useT0Stats'
import { useT0Keybindings } from '../composables/useT0Keybindings'
import { useT0Quota, quotaLevel } from '../composables/useT0Quota'
import { useUiStore } from '../stores/ui'
import { t0StatsApi } from '../api/t0_stats'
// v18 change t0-task-management: 集成 T0Task 快速选择器 + 管理面板抽屉
import { useT0TasksStore } from '../stores/t0_tasks'
import T0TaskList from '../components/trade/T0TaskList.vue'
import T0TaskDetail from '../components/trade/T0TaskDetail.vue'
import T0TaskCreateDialog from '../components/trade/T0TaskCreateDialog.vue'
import { t0TasksApi } from '../api/t0_tasks'
import { formatNumber, formatPrice, formatAmount } from '../utils/format'
import { useT0ChartGeometry, useT0DrawerChartGeometry } from '../composables/useT0ChartGeometry'
import { useT0OrderSubmit } from '../composables/useT0OrderSubmit'
import { makeLogger } from '../utils/logger'

const log = makeLogger('T0Trade')

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()
const quoteStore = useQuoteStore()
const assetStore = useAssetStore()
const uiStore = useUiStore()
// v18 change t0-task-management: T0Task 缓存 store（便于按 stock_code 自动过滤下拉）
const t0TasksStore = useT0TasksStore()
const { positions } = storeToRefs(holdingsStore)
const { asset: assetData } = storeToRefs(assetStore)

// stockCode: 默认取第一个持仓，不再硬编码 600519.SH
const stockCode = ref(null)
const submitting = ref(false)
const refreshing = ref(false)

// v18: T0Task 快速选择器 + 管理抽屉
const selectedTaskId = ref(null)            // 当前下单归属 task；null = 不归属
const tasksDrawerVisible = ref(false)      // 管理面板抽屉
const tasksDetailVisible = ref(false)      // 单 task 详情抽屉
const viewingTaskId = ref(null)            // 详情查看中的 task
const createDialogVisible = ref(false)     // 新建 task 弹窗
const createDialogLoading = ref(false)

// 按当前选中 stock_code 自动过滤活跃 task
const filteredActiveTasks = computed(() => {
  const all = t0TasksStore.activeTasks || []
  if (!stockCode.value) return all
  return all.filter((t) => t.stock_code === stockCode.value)
})
// 选中行变化时，如果当前 task 不再适用, 清空
watch([stockCode, filteredActiveTasks], ([code, list]) => {
  if (selectedTaskId.value && !list.find((t) => t.id === selectedTaskId.value)) {
    // 当前 task 不在过滤列表 — 自动清空 (stock_code 不匹配 或 task 不再 active)
    selectedTaskId.value = null
  }
})

async function onManageTasks() {
  tasksDrawerVisible.value = true
  // 每次打开都拉一次最新（保证对账/查看最新统计）
  await t0TasksStore.loadTasks()
}

function onOpenTaskDetail(taskId) {
  viewingTaskId.value = taskId
  tasksDetailVisible.value = true
}

// 接住子组件的 balance/close 事件 → 调对应 store action
async function onBalanceTask(taskId) {
  try {
    const r = await t0TasksStore.balanceTask(taskId)
    const dir = r.action === 'BUY' ? '买入' : r.action === 'SELL' ? '卖出' : '无需操作'
    ElMessage.info(`task #${taskId} 配平建议：${dir} ${r.volume} 股 — ${r.reason}`)
  } catch (e) { /* ElMessage 已被拦截器弹 */ }
}
async function onCloseTask(taskId) {
  if (!confirm(`确认一键平仓 task #${taskId} 到 base_volume？将生成平仓委托`)) return
  try {
    const r = await t0TasksStore.closeTask(taskId)
    ElMessage.success(`task #${taskId} 已平仓：${r.action} ${r.volume} 股`)
    await t0TasksStore.loadTasks()  // 刷新概览
  } catch (e) {}
}

async function onCreateTaskSubmit(form) {
  createDialogLoading.value = true
  try {
    const t = await t0TasksStore.createTask(form)
    if (t && t.id) {
      ElMessage.success(`task #${t.id} 创建成功，自动选中`)
      // 自动选中新创建的 task（如果 stock_code 匹配当前选中）
      if (t.stock_code === stockCode.value) {
        selectedTaskId.value = t.id
      }
    }
    createDialogVisible.value = false
  } finally {
    createDialogLoading.value = false
  }
}

// ---- 抽屉控制 (保持原有功能) ----
const drawerVisible = ref(false)
const drawerLoading = ref(false)
const drawerStats = ref({ order_count: 0, trade_count: 0, realized_pnl: 0, unrealized_pnl: 0, total_pnl: 0, today_buy_volume: 0, today_sell_volume: 0, today_buy_amount: 0, today_sell_amount: 0 })
const drawerHistory = ref(null)
const drawerDays = ref(30)
function onOpenDrawer(row) {
  if (!row || !row.stock_code) return
  const code = row.stock_code
  stockCode.value = code
  drawerVisible.value = true
  drawerLoading.value = true
  Promise.all([
    t0StatsApi.get(code).catch((e) => { log.warn('drawer t0 stats failed', e); return null }),
    t0StatsApi.getHistory(code, drawerDays.value).catch((e) => { log.warn('drawer t0 history failed', e); return null }),
  ]).then(([stats, hist]) => {
    if (stats) drawerStats.value = stats
    drawerHistory.value = hist
  }).finally(() => { drawerLoading.value = false })
}
function onDrawerChangeDays(days) {
  drawerDays.value = days
  if (!stockCode.value) return
  t0StatsApi.getHistory(stockCode.value, days).then((h) => { drawerHistory.value = h }).catch(() => {})
}

const drawerSize = computed(() => (typeof window !== 'undefined' && window.innerWidth < 1100 ? '420px' : '540px'))
const drawerCumHistory = computed(() => {
  const pts = drawerHistory.value?.points || []
  let cum = 0
  return pts.map(p => ({ ...p, cum_pnl: (cum += p.realized_pnl) }))
})
const drawerChartW = 460
const drawerChartH = 140
const drawerChartPad = 16
const { cumPath: drawerCumPath, cumAreaPath: drawerCumAreaPath, zeroY: drawerZeroY } =
  useT0DrawerChartGeometry(drawerCumHistory, { W: drawerChartW, H: drawerChartH, pad: drawerChartPad })
const drawerAggregate = ref(null)
watch(drawerVisible, async (v) => {
  if (v && stockCode.value) {
    try {
      const agg = await t0StatsApi.getAggregate({ userDef: 'T0', days: 90 })
      drawerAggregate.value = (agg?.by_stock || []).find(s => s.stock_code === stockCode.value) || agg
    } catch (e) {
      log.warn('drawer aggregate failed', e)
    }
  }
})
function ptRowClass({ row }) {
  const classes = []
  if (row.stock_code === stockCode.value) classes.push('is-selected')
  if (row.stock_code === selectedRowCode.value) classes.push('is-focused')
  return classes.join(' ')
}

// ---- 快速做T 全局设置 ----
const _quickDefaults = loadQuickDefaults()
const quickPct = ref(_quickDefaults.pct)
const quickPriceType = ref(_quickDefaults.priceType)
watch([quickPct, quickPriceType], ([p, pt]) => {
  saveQuickDefaults(p, pt)
})

// ---- 持仓列表 ----
const holdingsPositions = computed(() => positions.value)

// ---- 排序 + 选中行 (change t0-trade-polish-bundle commit 5) ----
// sortBy/sortOrder: el-table @sort-change 写入, sortedRows 派生
//   null = 用户没排序, 走原顺序 (positions.value 顺序)
// selectedRowCode: ↑↓ 切换, 排序变化时按 stockCode 同步 (不变性)
const sortBy = ref(null)         // 'vol' | 'last_price' | 'change_pct' | 'realized_pnl' | 'net_exposure' | 'return_rate' | null
const sortOrder = ref(null)      // 'ascending' | 'descending' | null
const selectedRowCode = ref(null)
function onSortChange({ prop, order }) {
  sortBy.value = order ? prop : null
  sortOrder.value = order || null
}
function _rowSortValue(row, key) {
  if (!key) return 0
  switch (key) {
    case 'vol': return Number(row.vol) || 0
    case 'last_price': return quoteStore.getLastPrice(row.stock_code) || 0
    case 'change_pct': return quoteStore.getChangePct(row.stock_code) || 0
    case 'realized_pnl': return t0StatsMap.value[row.stock_code]?.realized_pnl ?? 0
    case 'net_exposure': return netExposure(row)
    case 'return_rate': return holdingsStore.getReturnRate(row.stock_code) || 0
    default: return 0
  }
}
const sortedRows = computed(() => {
  const list = [...holdingsPositions.value]
  if (!sortBy.value || !sortOrder.value) return list
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  list.sort((a, b) => {
    const va = _rowSortValue(a, sortBy.value)
    const vb = _rowSortValue(b, sortBy.value)
    return (va - vb) * dir
  })
  return list
})
function _moveSelection(delta) {
  const list = sortedRows.value
  if (list.length === 0) return
  const curIdx = list.findIndex(r => r.stock_code === selectedRowCode.value)
  let next = curIdx + delta
  if (next < 0) next = 0
  if (next >= list.length) next = list.length - 1
  selectedRowCode.value = list[next].stock_code
}
function _selectedRow() {
  return sortedRows.value.find(r => r.stock_code === selectedRowCode.value)
}

// ---- t0StatsMap: 每个持仓的今日统计 (走 useT0Stats 30s TTL 缓存) ----
const t0StatsMap = ref({})

// ---- quota frame: 账户级 5 pill 概览 (change-quota-frame) ----
const { aggregate: quotaAggregate, rowQuota: quotaForRow } = useT0Quota(t0StatsMap)
const todayPnlText = computed(() => {
  const v = quotaAggregate.value.todayPnl
  if (v === 0) return '¥0'
  const sign = v > 0 ? '+' : '-'
  return `${sign}¥${formatAmount(Math.abs(v))}`
})
const todayPnlClass = computed(() => {
  const v = quotaAggregate.value.todayPnl
  if (v > 0) return 'qf-pill--up'
  if (v < 0) return 'qf-pill--down'
  return ''
})
async function loadAllT0Stats() {
  const codes = holdingsPositions.value?.map(p => p.stock_code) || []
  const map = await useT0Stats.loadAll(codes)
  t0StatsMap.value = map
}
// 差量加载: 仅拉新增标的 (持仓变化时只补差量, 删的标的无需动作)
async function loadDiffT0Stats(newCodes, oldCodes) {
  const oldSet = new Set(oldCodes || [])
  const added = newCodes.filter(c => !oldSet.has(c))
  if (added.length === 0) return
  const addedMap = await useT0Stats.loadAll(added)
  // merge 到现有 t0StatsMap
  t0StatsMap.value = { ...t0StatsMap.value, ...addedMap }
}

// ---- 净敞口 / 配平按钮文本 ----
function netExposure(row) {
  const s = t0StatsMap.value[row.stock_code]
  if (!s) return 0
  return (s.today_buy_volume || 0) - (s.today_sell_volume || 0)
}
function getBalanceQty(row) {
  const net = netExposure(row)
  return net === 0 ? null : Math.abs(net)
}
function getBalanceLabel(row) {
  const net = netExposure(row)
  if (net === 0) return '配平'
  return `配${net > 0 ? '-' : '+'}${Math.abs(net)}`
}
function getBalanceTip(row) {
  const net = netExposure(row)
  if (net === 0) return '已配平'
  return `配平: ${net > 0 ? `卖${Math.abs(net)}` : `买${Math.abs(net)}`} 抵消今日净敞口`
}

// ---- 按钮 disabled + tooltip 状态 (委派 useT0TradeButtons + lib/t0-calc) ----
function _rowBalance(row) {
  const net = netExposure(row)
  if (net === 0) return null
  return { side: net > 0 ? 'sell' : 'buy', qty: Math.abs(net) }
}
function buyState(row) {
  return buyBtnState(row, {
    pct: quickPct.value,
    cash: assetData.value?.cash,
    price: quoteStore.getLastPrice(row.stock_code),
    submitting: submitting.value,
  })
}
function sellState(row) {
  return sellBtnState(row, { pct: quickPct.value, submitting: submitting.value })
}
function balanceState(row) {
  return balanceBtnState(row, {
    balance: _rowBalance(row),
    cash: assetData.value?.cash,
    price: quoteStore.getLastPrice(row.stock_code),
    submitting: submitting.value,
  })
}

// ---- 底部累计曲线 (按当前 stockCode) ----
const historyDays = ref(30)
const historyData = ref(null)
async function loadT0History() {
  if (!stockCode.value) return
  try {
    historyData.value = await t0StatsApi.getHistory(stockCode.value, historyDays.value)
  } catch (e) {
    log.warn('load t0 history failed', e)
    historyData.value = null
  }
}
const cumHistory = computed(() => {
  const pts = historyData.value?.points || []
  let cum = 0
  return pts.map(p => ({ ...p, cum_pnl: (cum += p.realized_pnl) }))
})
const bottomChartW = 800
const bottomChartH = 80
const bottomChartPad = 24
const {
  cumPath: bottomCumPath,
  cumAreaPath: bottomCumAreaPath,
  zeroY: bottomZeroY,
} = useT0ChartGeometry(cumHistory, { W: bottomChartW, H: bottomChartH, pad: bottomChartPad })

// ---- 副行 30 天 hover popover (改文字列表) ----
const history30dMap = ref({})
async function ensureHistory30d(code) {
  if (!code || history30dMap.value[code]) return
  try {
    const hist = await t0StatsApi.getHistory(code, 30)
    const pts = []
    let cum = 0
    if (hist?.points) {
      for (const p of hist.points) {
        cum += p.realized_pnl
        pts.push(cum)
      }
    }
    history30dMap.value = { ...history30dMap.value, [code]: pts }
  } catch (e) {
    log.warn(`history30d failed for ${code}`, e)
    history30dMap.value = { ...history30dMap.value, [code]: [] }
  }
}

// ---- 提交下单 (保持 useT0OrderSubmit) ----
const priceType = ref('latest')
const balanceCoeff = ref(1.0)
const { submitOrder } = useT0OrderSubmit({
  stockCode, priceType, balanceCoeff, submitting,
  orderStore,
  onAfterSuccess: () => loadAllT0Stats(),
})

// ---- M-008 v3: 行内快捷买卖 (v18: 把 selectedTaskId 透传给下单) ----
function onQuickBuy(row) {
  if (isBuyDisabled(row)) return ElMessage.warning(`${row.stock_code} 持仓为 0, 无法按比例买`)
  const r = buildQuickOrder(row, 'buy', quickPct.value, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 买 ${r.qty} 股 (${r.label})`,
    '一键买入', { confirmButtonText: '确认买入', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: '23', volume: r.qty, price: r.price, taskId: selectedTaskId.value }))
    .catch(() => {})
}
function onQuickSell(row) {
  const r = buildQuickOrder(row, 'sell', quickPct.value, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 卖 ${r.qty} 股 (${r.label})`,
    '一键卖出', { confirmButtonText: '确认卖出', cancelButtonText: '取消', type: 'warning' }
  ).then(() => submitOrder({ orderType: '24', volume: r.qty, price: r.price, taskId: selectedTaskId.value }))
    .catch(() => {})
}
function onQuickBalance(row) {
  const bal = calcBalanceQty(row, row.today_buy_volume || 0, row.today_sell_volume || 0)
  if (bal.error) return ElMessage.warning(bal.error)
  const r = buildQuickOrder(row, bal.side, 100, quickPriceType.value)
  if (r.error) return ElMessage.warning(r.error)
  r.qty = bal.qty
  // 配平操作强烈建议绑定 task (否则无法正确归类), 给提示
  if (!selectedTaskId.value) {
    ElMessage.warning('未选 task，配平操作不会被归类。建议先在上方选 task。')
  }
  ElMessageBox.confirm(
    `${row.stock_code} ${bal.side === 'buy' ? '买入' : '卖出'} ${bal.qty} 股 配平 (净额归零)`,
    '一键配平', { confirmButtonText: '确认配平', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: bal.side === 'buy' ? '23' : '24', volume: bal.qty, price: r.price, taskId: selectedTaskId.value }))
    .catch(() => {})
}


// ---- 快捷键 (change t0-trade-polish-bundle commit 5) ----
useT0Keybindings({
  isEnabled: () => uiStore.t0Keybindings && !drawerVisible.value,
  onBuy: () => { const r = _selectedRow(); if (r && !buyState(r).disabled) onQuickBuy(r) },
  onSell: () => { const r = _selectedRow(); if (r && !sellState(r).disabled) onQuickSell(r) },
  onBalance: () => { const r = _selectedRow(); if (r && !balanceState(r).disabled) onQuickBalance(r) },
  onSelectPrev: () => _moveSelection(-1),
  onSelectNext: () => _moveSelection(1),
  onEnter: () => { const r = _selectedRow(); if (r) onOpenDrawer(r) },
})

// Escape 单独监听 (无 uiStore 开关, 抽屉打开随时关)
function onEscapeKey(e) {
  if (e.key === 'Escape' && drawerVisible.value) {
    drawerVisible.value = false
  }
}

// ---- 初始化 ----
onMounted(async () => {
  await loadAllT0Stats()
  // v18: 加载 task 列表（用于头部下拉 + 管理面板）
  t0TasksStore.loadTasks().catch(() => {})
  // 默认选中第一个持仓
  if (!stockCode.value && holdingsPositions.value.length > 0) {
    stockCode.value = holdingsPositions.value[0].stock_code
    await loadT0History()
    // 副行 30 天 popover: lazy load via @show 触发, 不在 onMounted 预拉
  }
  window.addEventListener('keydown', onEscapeKey)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onEscapeKey)
})
// 注: useT0Keybindings 已自管 onMounted/onUnmounted, 不在此再 addEventListener

// 当持仓变化时，仅差量加载 t0Stats (新增标的 fetch, 删除标的无需动作, 走 cache)
watch(() => holdingsPositions.value.map(p => p.stock_code), async (newCodes, oldCodes) => {
  if (!oldCodes) return  // initial 不触发 (onMounted 已全量)
  await loadDiffT0Stats(newCodes, oldCodes)
})

// 监听 stockCode 变化 → 加载底部曲线 (副行 30 天由 popover @show 触发, 不预拉)
watch(stockCode, async (code) => {
  if (code && !drawerVisible.value) {
    await loadT0History()
  }
})
</script>

<style scoped>
.t0-trade {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  height: 100%;
}

/* Header + 设置条 */
.t0-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}

/* quota frame: 5 个账户级 metric pill (change-quota-frame) */
.quota-frame {
  display: flex;
  gap: 8px;
  padding: 6px 12px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}
.qf-pill {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 4px 12px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  min-width: 110px;
}
.qf-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.qf-value {
  font-size: 14px;
  font-weight: 600;
}
.qf-pill--up .qf-value { color: #f56c6c; }
.qf-pill--down .qf-value { color: #67c23a; }

/* 移动端窄屏 (<1100px): 持仓市值折叠 */
@media (max-width: 1100px) {
  .qf-pill--desktop-only { display: none; }
  .quota-frame { gap: 6px; }
  .qf-pill { min-width: 90px; padding: 4px 8px; }
}
.t0-title {
  font-size: 16px;
  font-weight: 700;
}
.qs-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qs-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.qs-divider {
  color: var(--el-border-color);
}

/* 主表 */
.position-table {
  flex: 1;
  min-height: 0;
}
.position-table :deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--el-fill-color-light);
}
.position-table :deep(tr) {
  cursor: pointer;
}
.position-table :deep(tr.is-selected td) {
  background-color: var(--el-color-primary-light-9) !important;
}
.position-table :deep(tr.is-focused td) {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}

/* 操作列 */
.op-col {
  display: flex;
  gap: 4px;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
}
.op-col :deep(.el-button) {
  padding: 4px 6px !important;
  font-size: 12px !important;
  font-weight: 600;
}
.op-btn-buy :deep(span), .op-btn-sell :deep(span), .op-btn-balance :deep(span) {
  color: #fff !important;
}
.op-btn-detail {
  padding: 0 !important;
  font-size: 12px !important;
}

/* 副行 */
.sub-row {
  display: flex;
  gap: 24px;
  padding: 4px 16px 8px;
  flex-wrap: wrap;
  background: var(--el-fill-color-light);
}
.sub-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
/* 副行 hover popover (改文字列表) */
.sub-popover {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}
.sub-popover-ref {
  cursor: pointer;
  border-bottom: 1px dashed var(--el-color-primary);
  padding: 0 2px;
}
.sub-popover-list {
  max-height: 240px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.6;
}
.sub-popover-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 1px 0;
}
.sub-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.sub-value {
  font-size: 13px;
  font-weight: 500;
}

/* 底部累计曲线 */
.bottom-chart {
  padding: 4px 12px 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.bottom-chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}
.bottom-chart-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.bottom-chart-svg {
  width: 100%;
  height: 80px;
  display: block;
}
.bottom-chart-tip {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  text-align: right;
  margin-top: 2px;
}

/* 颜色 */
.up { color: #f56c6c; }
.down { color: #67c23a; }
.muted { color: var(--el-color-info); }
.text-mono { font-family: var(--mono-font); }

/* quota 单元格颜色 (change-quota-frame) */
.quota-cell { font-weight: 600; }
.quota-high { color: #67c23a; }   /* 绿: ≥1000 充足 */
.quota-mid  { color: #e6a23c; }   /* 橙: 100-999 紧张 */
.quota-low  { color: #f56c6c; }   /* 红: 1-99 极紧 */
.quota-none { color: var(--el-color-info); }  /* 灰: 0 */

/* 抽屉样式 (保持与原版本一致) */
.t0-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.t0-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.t0-drawer-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.t0-drawer-code {
  font-size: 16px;
  font-weight: 700;
}
.t0-drawer-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 12px 16px;
}
.stat-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.stat-value {
  font-size: 16px;
  font-weight: 600;
}
.t0-drawer-section {
  padding: 12px 16px;
}
.t0-drawer-section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
}
.t0-drawer-empty {
  text-align: center;
  padding: 24px;
  color: var(--el-text-color-secondary);
}
.t0-drawer-chart {
  margin-top: 8px;
}
.t0-drawer-chart-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: right;
  margin-top: 4px;
}
.t0-drawer-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

/* 移动端适配 */
@media (max-width: 768px) {
  .t0-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .position-table {
    font-size: 12px;
  }
  .sub-row {
    gap: 12px;
    padding: 4px 8px 6px;
  }
  .sub-popover {
    display: none;  /* 移动端 hover 不工作, 静态隐藏 30 天明细 */
  }
  .bottom-chart-svg {
    height: 60px;
  }
}
</style>

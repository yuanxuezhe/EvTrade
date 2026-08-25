<!--
  T0Trade.vue — 快速做T 主页面

  布局: 上下分区, 无页面标题, 工具栏只有一条 (做T配置行)
    ┌──────────────────────────────┐
    │ 工具栏 (做T配置 + 从右到左:      │
    │   刷新 → 添加任务 → 任务筛选)     │
    ├──────────────────────────────┤
    │ 上半: 主表 (task 视角,           │
    │   每行 = 1 做T 任务, 标的列 90)  │
    ├──────────────────────────────┤
    │ 下半: 当前 task 的实时委托表     │
    │   - 15 列 (对齐今日委托: 交易日/ │
    │     类型/标的/撤单按钮等)          │
    │   - 数据源: holdings.orders     │
    │     .filter(o => o.task_id===id)│
    └──────────────────────────────┘
    添加任务: 900px dialog 集成 HoldingsPanel + T0TaskCreateDialog
    撤单: canCancel(row) 守卫 + handleCancel(row) 调 orderStore.cancelOrder

  数据流:
    主表行选中 / el-select 选 task
      → selectedTaskId.value 变化
      → lowerArea filteredTaskOrders 自动响应
      → computeSelectedTaskDiff() 实时算差 → 配平按钮文案 + disabled 状态

  配平按钮 (前端计算 + 下市价单):
    - 算: holdings.orders.filter(o=>o.task_id===id)
        .reduce((d, o) => d + (order_type==='23'?+1:-1) * (traded_volume||0), 0)
    - 方向: diff>0 多买 → SELL; diff<0 多卖 → BUY; diff===0 按钮 disabled
    - 下单: useT0OrderSubmit.submitOrder({orderType, volume: |diff|, price:0,
             priceType:'market' (priceTypeCode=44), taskId})
-->
<template>
  <div class="t0-trade fade-in-up" :style="rootStyle">
    <!-- 整页只有一条工具栏行 — 做T配置 + (任务筛选 / 添加任务 / 刷新) 全部靠右集中 -->
    <!--   顺序(从右到左): 刷新 → 添加任务 → 任务筛选 → 提示文案 → 3 个 select -->
    <!-- 工具栏 — 百分数 vs 股数 单选互斥输入框 -->
    <div class="t0-config-bar">
      <span class="t0-config-label">做T配置:</span>
      <!-- 模式一: 按比例 (el-radio-group 二选一, 互斥单选) -->
      <el-radio-group v-model="globalMode" size="small">
        <el-radio-button value="pct">按比例</el-radio-button>
        <el-radio-button value="qty">按数量</el-radio-button>
        <el-radio-button value="amount">按金额</el-radio-button>
      </el-radio-group>
      <!-- 输入框按模式条件显隐 + 单位提示 -->
      <!-- 输入框按模式条件显隐 + 单位提示 (两个分支各自独立 v-if, 不用 v-else 防中间被截断) -->
      <template v-if="globalMode === 'pct'">
        <el-input-number
          v-model="globalPctInput"
          :min="0.001"
          :max="100"
          :step="0.1"
          :precision="3"
          size="small"
          controls-position="right"
          style="width: 130px"
          placeholder="百分数"
        />
        <span class="t0-unit-hint">%</span>
      </template>
      <template v-else-if="globalMode === 'qty'">
        <el-input-number
          v-model="globalQtyInput"
          :min="1"
          :step="100"
          size="small"
          controls-position="right"
          style="width: 130px"
          placeholder="股数"
        />
        <span class="t0-unit-hint">股</span>
      </template>
      <template v-if="globalMode === 'amount'">
        <el-input-number
          v-model="globalAmountInput"
          :min="0.01"
          :step="100"
          :precision="2"
          size="small"
          controls-position="right"
          style="width: 130px"
          placeholder="金额"
        />
        <span class="t0-unit-hint">元</span>
      </template>
      <!-- 价格 + 价格类型 → 复用 Trade.vue 同款 PriceTypeInput 组件 (左 50% 价格, 右 50% 类型) -->
      <PriceTypeInput
        v-model:price="orderPrice"
        v-model:price-type="orderPriceTypeCode"
        :stock-code="selectedStockCode"
        :width="220"
        size="small"
      />
      <el-select
        v-model="globalQtyBase"
        size="small"
        style="width: 110px"
        :disabled="globalMode !== 'pct'"
        :title="globalMode !== 'pct' ? '仅按比例模式有效' : '持仓基数 (仅按比例有效)'"
      >
        <el-option v-for="o in qtyBaseOptions" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
      <span class="t0-config-hint">（按比例 = 买: 可用金额÷最新价×pct% / 卖: 持仓基数×pct% · 按数量 = 直接输入股数 · 按金额 = 金额÷最新价取整到交易单位）</span>
      <span class="t0-spacer"></span>
      <el-tooltip content="选择/取消当前做T归属的 task；新建请用添加任务入口" placement="top">
        <el-select
          v-model="selectedTaskId"
          placeholder="任务筛选"
          size="small"
          clearable
          filterable
          class="qs-task-select"
          @change="onTaskChange"
        >
          <el-option
            v-for="t in filteredActiveTasks"
            :key="t.id"
            :value="t.id"
            :label="`#${t.id} ${t.stock_code}`"
          />
        </el-select>
      </el-tooltip>
      <el-button type="primary" size="small" :icon="Plus" @click="onAddTaskOpen">添加任务</el-button>
      <el-button size="small" @click="onRefresh" :loading="refreshing">刷新</el-button>
    </div>

    <!-- 上下分区: 上半主表 + 下半委托表 -->
    <div class="t0-split">
      <section class="t0-upper">
        <div class="area-hint">
          <el-icon><List /></el-icon><span>做T任务（共 {{ taskRows.length }} 条）</span>
        </div>
        <DataTableView
          :columns="taskColumns"
          :data="taskRows"
          :row-class-name="ptRowClass"
          :size="'default'"
          :empty-description="'暂无 T0 任务，点击「添加任务」按钮创建'"
          @row-click="onTaskRowClick"
          @row-dblclick="(row) => { if (row.stock_code) stockCode = row.stock_code }"
        >
          <template #column-status="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
          <template #column-id="{ row }">
            <span class="text-mono">#{{ row.id }}</span>
          </template>
          <template #column-stock_code="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px" v-t0-badge="row.stock_code">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
          <template #column-initial_position="{ row }">
            <span class="text-mono">{{ formatNumber(holdingsStore.positions?.find(p=>p.stock_code===row.stock_code)?.last_vol ?? 0) }}</span>
          </template>
          <template #column-current_position="{ row }">
            <span class="text-mono">{{ formatNumber(holdingsStore.positions?.find(p=>p.stock_code===row.stock_code)?.vol ?? 0) }}</span>
          </template>
          <template #column-last_price="{ row }">
            <!-- 通用 LivePriceCell (与 HoldingsPanel / CachePositions 三处一致) -->
            <LivePriceCell :stock-code="row.stock_code" />
          </template>
          <template #column-t0_pnl="{ row }">
            <span class="text-mono" :class="(t0PnlCell(row)?.total_pnl ?? 0) >= 0 ? 'up' : 'down'">
              {{ (t0PnlCell(row)?.total_pnl ?? 0) >= 0 ? '+' : '' }}{{ formatMoney(t0PnlCell(row)?.total_pnl ?? 0) }}
            </span>
          </template>
          <template #column-t0_today_pnl="{ row }">
            <span class="text-mono" :class="(t0PnlCell(row)?.today_pnl ?? 0) >= 0 ? 'up' : 'down'">
              {{ (t0PnlCell(row)?.today_pnl ?? 0) >= 0 ? '+' : '' }}{{ formatMoney(t0PnlCell(row)?.today_pnl ?? 0) }}
            </span>
          </template>
          <template #column-action="{ row }">
            <div class="op-col">
              <el-button type="danger" size="small" :disabled="!canOpRow(row)" @click.stop="onBuyTask(row)">买</el-button>
              <el-button type="success" size="small" :disabled="!canOpRow(row)" @click.stop="onSellTask(row)">卖</el-button>
              <el-button v-if="row.status === 'active'" type="warning" link size="small"
                :disabled="computeRowBalanceDiff(row.id) === 0" @click.stop="onBalanceTask(row.id)">
                {{ balanceBtnLabel(row.id) }}
              </el-button>
              <el-button v-if="row.status !== 'archived'" type="info" link size="small"
                @click.stop="onArchiveTask(row.id)">归档</el-button>
            </div>
          </template>
        </DataTableView>
      </section>

      <!-- 下半: 当前选中 task 的实时委托表 -->
      <section class="t0-lower">
        <div class="area-hint">
          <el-icon><Document /></el-icon>
          <span>
            <template v-if="selectedTaskId">
              task #{{ selectedTaskId }}
              <template v-if="selectedTaskDiff !== 0">
                （实时差 <b :class="selectedTaskDiff > 0 ? 'up' : 'down'">
                  {{ selectedTaskDiff > 0 ? '+' : '' }}{{ selectedTaskDiff }}
                </b> 股 — {{ selectedTaskDiff > 0 ? '需卖' : '需买' }}）
              </template>
              <template v-else>（已平衡）</template>
              ，共 {{ filteredTaskOrders.length }} 笔委托（不限日期, 含历史做T）
            </template>
            <template v-else>请先在上方主表选择 1 个 task，下方展示其委托与实时配平数量</template>
          </span>
        </div>
        <DataTableView
          :columns="taskOrderColumns"
          :data="filteredTaskOrders"
          :size="'default'"
          :default-sort="{ prop: 'order_time', order: 'descending' }"
          :empty-description="'该 task 暂无委托'"
          @row-dblclick="(row) => { if (row.stock_code) stockCode = row.stock_code }"
        >
          <template #column-trd_date="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
          <template #column-order_no="{ row }">
            <span class="text-mono">{{ row.order_no }}</span>
          </template>
          <template #column-type="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
          <template #column-stock_code="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px" v-t0-badge="row.stock_code">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
          <template #column-order_type="{ row }">
            <el-tag :type="row.order_type === '23' ? 'danger' : 'success'" size="small">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </el-tag>
          </template>
          <template #column-volume="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
          <template #column-price_type="{ row }">
            <span class="text-secondary">{{ priceTypeLabel(row.price_type) || '—' }}</span>
          </template>
          <template #column-price="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
          <template #column-traded_volume="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
          </template>
          <template #column-avg_price="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatPrice(row.avg_price, row.stock_code) : '—' }}</span>
          </template>
          <template #column-traded_amount="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatMoney(row.traded_amount) : '—' }}</span>
          </template>
          <template #column-cancelled_volume="{ row }">
            <span class="text-mono">{{ formatNumber(row.cancelled_volume || 0) }}</span>
          </template>
          <template #column-order_id="{ row }">
            <span class="text-mono text-secondary">{{ row.order_id || '—' }}</span>
          </template>
          <template #column-status="{ row }">
            <OrderStatusBadge :status="row.status" :status_msg="row.status_msg" :remark="row.user_def" />
          </template>
          <template #column-action="{ row }">
            <el-button v-if="canCancel(row)" type="danger" size="small"
              :loading="orderStore.cancelling && cancellingOrderNo === row.order_no"
              @click="handleCancel(row)">撤单</el-button>
          </template>
          <template #column-user_def="{ row }">
            <span class="text-secondary">{{ row.user_def || '—' }}</span>
          </template>
          <template #column-order_time="{ row }">
            <span class="text-mono">{{ row.order_time || '—' }}</span>
          </template>
        </DataTableView>
      </section>
    </div>

    <!-- 添加任务 dialog (900px, 左 HoldingsPanel + 右 T0TaskCreateDialog) -->
    <el-dialog
      v-model="createDialogVisible"
      title="添加做T任务"
      width="900px"
      :close-on-click-modal="false"
      align-center
      @open="onAddTaskDialogOpen"
    >
      <div class="add-task-grid">
        <!-- 左侧: 持仓面板 (HoldingsPanel) -->
        <div class="add-task-left">
          <div class="left-hint">
            <el-icon><InfoFilled /></el-icon>
            <span>单击持仓行自动填充右侧股票代码</span>
          </div>
          <HoldingsPanel @select-stock="onHoldingSelected" />
        </div>

        <!-- 右侧: 创建任务表单 -->
        <div class="add-task-right">
          <T0TaskCreateDialog
            v-if="createDialogVisible"
            inline
            :visible="createDialogVisible"
            :loading="createDialogLoading"
            :default-stock-code="stockCode || ''"
            :external-stock-code="externalStockCode"
            @submit="onCreateTaskSubmit"
            @cancel="createDialogVisible = false"
          />
        </div>
      </div>
    </el-dialog>

    <!-- task 详情 drawer -->
    <el-drawer v-model="tasksDetailVisible" :title="`task #${viewingTaskId} 详情`" size="55%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskDetail v-if="tasksDetailVisible" :task-id="viewingTaskId" embedding="drawer" />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { List, Document, Plus, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { useStocksStore } from '../stores/stocks'
import { useT0TasksStore } from '../stores/t0_tasks'
import { useOrderStore } from '../stores/order'
import DataTableView from '../components/DataTableView.vue'
import T0TaskDetail from '../components/trade/T0TaskDetail.vue'
import T0TaskCreateDialog from '../components/trade/T0TaskCreateDialog.vue'
import HoldingsPanel from '../components/trade/HoldingsPanel.vue'
import LivePriceCell from '../components/cells/LivePriceCell.vue'  // 最新价+涨跌幅通用 cell
import PriceTypeInput from '../components/PriceTypeInput.vue'
import { PriceType } from '../constants/priceType.js'
import { useT0OrderSubmit } from '../composables/useT0OrderSubmit'
import { useQuoteSubscription } from '../composables/useQuoteSubscription'
import { formatNumber, formatAmount, formatMoney, priceTypeLabel } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { STATUS_LABEL, STATUS_TYPE } from '../utils/format'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import { useUiStore } from '../stores/ui'
import { makeLogger } from '../utils/logger'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'

const log = makeLogger('T0Trade')
const uiStore = useUiStore()
const rootStyle = computed(() => ({ '--oplog-extra': uiStore.oplogExpanded ? '260px' : '0px' }))

// DataTableView 列定义
const taskColumns = [
  { key: 'status', label: '状态', width: 100, sortable: false },
  { key: 'id', label: '任务编号', width: 90 },
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'initial_position', label: '期初持仓', align: 'right', width: 90, sortable: false },
  { key: 'current_position', label: '当前持仓', align: 'right', width: 80, sortable: false },
  { key: 'last_price', label: '最新价(涨跌幅)', align: 'right', width: 140, sortable: false },
  { key: 't0_pnl', label: '做T总盈亏', align: 'right', width: 110, sortable: false },
  { key: 't0_today_pnl', label: '当日做T盈亏', align: 'right', width: 110, sortable: false },
  { key: 'action', label: '操作', align: 'center', width: 280, fixed: 'right', sortable: false },
]

const taskOrderColumns = [
  { key: 'trd_date', label: '交易日', vBind: COL.STOCK_CODE },
  { key: 'order_no', label: '委托编号', vBind: COL.STOCK_CODE },
  { key: 'type', label: '类型', width: 100, sortable: false },
  { key: 'stock_code', label: '标的', vBind: COL.STOCK_TARGET },
  { key: 'order_type', label: '方向', vBind: COL.DIRECTION },
  { key: 'volume', label: '委托量', vBind: COL.NUMBER },
  { key: 'price_type', label: '价格类型', vBind: COL.PRICE_TYPE },
  { key: 'price', label: '委托价', vBind: COL.PRICE },
  { key: 'traded_volume', label: '成交量', vBind: COL.NUMBER },
  { key: 'avg_price', label: '成交均价', vBind: COL.PRICE },
  { key: 'traded_amount', label: '成交金额', vBind: COL.MONEY, sortable: false },
  { key: 'cancelled_volume', label: '撤单量', vBind: COL.NUMBER },
  { key: 'order_id', label: '合同序号', vBind: COL.SHORT_SNO },
  { key: 'status', label: '状态', vBind: COL.STATUS },
  { key: 'action', label: '操作', width: 100, fixed: 'right', align: 'center', sortable: false },
  { key: 'user_def', label: '备注', minWidth: 120, sortable: false },
  { key: 'order_time', label: '下单时间', vBind: COL.TIME },
]

const holdingsStore = useHoldingsStore()
const quoteStore = useQuoteStore()
const stocksStore = useStocksStore()   // 取 min_buy_qty/trade_unit
const t0TasksStore = useT0TasksStore()
const orderStore = useOrderStore()
const { positions } = storeToRefs(holdingsStore)

const stockCode = ref(null)
const refreshing = ref(false)

// task 管理
const selectedTaskId = ref(null)
const tasksDetailVisible = ref(false)
const viewingTaskId = ref(null)

// 操作列全局配置 (页面顶部 row 共用)
// ref 重写
//   globalMode: 'pct' | 'qty' 二选一互斥单选
//   globalPctInput: 直接是百分数 (用户视角 25 表示 25%, 支持小数), 计算时除以 100
//   globalQtyInput: 直接是股数 (整数)
const globalMode = ref('pct')              // 模式 'pct' (按比例) | 'qty' (按数量) | 'amount' (按金额)
const globalPctInput = ref(25)             // 百分数 (用户视角 25 = 25%, 支持小数 0.001-100)
const globalQtyInput = ref(100)            // 股数 (整数 ≥ 1)
const globalAmountInput = ref(10000)       // 金额 (元)
// 价格类型为 numeric PriceType (11/5/44), 与 PriceTypeInput 配套
//   默认市价 (44)
const orderPriceTypeCode = ref(PriceType.MARKET_PEER_PRICE_FIRST)
const orderPrice = ref(0)                 // 实际下单价格 (FIX_PRICE 用户可改; 最新价/市价 由 watcher 自动填)
const globalQtyBase = ref('last_vol')      // 数量基数 'vol'/'avl_vol'/'last_vol' (pct 模式下的基数)

// 选中 row 的 stock_code (驱动 PriceTypeInput 的 stockCode + watcher 自动填价)
const selectedStockCode = computed(() => {
  if (!selectedTaskId.value) return ''
  const t = t0TasksStore.tasksById[selectedTaskId.value]
  return t?.stock_code || ''
})

// 添加任务 dialog
const createDialogVisible = ref(false)
const createDialogLoading = ref(false)
const externalStockCode = ref('')  // HoldingsPanel 选中 → 驱动 dialog 表单

// 配平: useT0OrderSubmit 实例化（价格类型跟随做T配置 orderPriceTypeCode, numeric）
const balancePriceType = orderPriceTypeCode  // 直接共享 numeric ref, useT0OrderSubmit 已支持
const balanceCoeff = ref(1)               // 配平系数（固定 1）
const balanceSubmitting = ref(false)
const balanceStockCode = computed(() => {
  const t = selectedTaskId.value && t0TasksStore.tasksById[selectedTaskId.value]
  return t?.stock_code || ''
})
const { submitOrder: submitBalanceOrder } = useT0OrderSubmit({
  stockCode: balanceStockCode,
  priceType: balancePriceType,
  balanceCoeff: balanceCoeff,
  submitting: balanceSubmitting,
  orderStore,
  onAfterSuccess: null,
})

const filteredActiveTasks = computed(() => {
  const all = t0TasksStore.activeTasks || []
  if (!stockCode.value) return all
  return all.filter((t) => t.stock_code === stockCode.value)
})

watch([stockCode, filteredActiveTasks], ([code, list]) => {
  if (selectedTaskId.value && !list.find((t) => t.id === selectedTaskId.value)) {
    selectedTaskId.value = null
  }
})

// 进入页面/taskRows 变化时, 默认选中第一条
//   修复配平 stock_code=空 bug: balanceStockCode 依赖 selectedTaskId, 无选中时返回 ''
//   后端 place.py:84 校验 task.stock_code != req.stock_code → 报错
// taskRows 必须在此 watch 之前定义 (复用为下方的 taskRows), 否则 TDZ ReferenceError 导致整个 setup 抛错、页面渲染空白.
const taskRows = computed(() => t0TasksStore.tasks || [])
watch(taskRows, (rows) => {
  if (!selectedTaskId.value && rows && rows.length > 0) {
    selectedTaskId.value = rows[0].id
  }
}, { immediate: true })

// 任务列表 stock_code 自动订阅行情 (REQ-FE-538)
//   - 必须放在 taskRows 定义之后, 否则 TDZ ReferenceError (2026-08-25 修复)
//   - taskRows 变化 → composable 自动 diff subscribe(added) / unsubscribe(removed)
//   - 页面卸载 → composable 自动 unsubscribe(current)
//   - LivePriceCell 由此读到 last_price, last_price 列 + t0PnlCell 才有数据
useQuoteSubscription(() => taskRows.value.map((r) => r.stock_code))

// ---- 上下分区: 下半委托表 + 实时配平 ----
// storeToRefs 是 pinia 解构 ref 必备
const { orders: holdingsOrders } = storeToRefs(holdingsStore)

// 下半委托表: 实时按 task_id 过滤 holdings.orders, 按 order_time desc
//   排除 strategy_type=2 (策略下单母单子单, 由 StrategyOrder.vue 单独展示)
const filteredTaskOrders = computed(() => {
  if (!selectedTaskId.value) return []
  return holdingsOrders.value
    .filter((o) => Number(o.task_id) === Number(selectedTaskId.value) && o.strategy_type !== 2)
    .slice()
    .sort((a, b) => String(b.order_time || '').localeCompare(String(a.order_time || '')))
})

// 核心: 实时算 task 净成交差 (已成交部分 traded_volume)
//   diff = sum(buy.traded_volume) - sum(sell.traded_volume)
//   > 0 → 多买了，应反向 SELL
//   < 0 → 多卖了，应反向 BUY
//   = 0 → 已平衡
function _taskNetDiff(taskId) {
  if (!taskId) return 0
  let buy = 0, sell = 0
  for (const o of holdingsOrders.value) {
    // 排除 strategy_type=2 (策略下单母单子单)
    if (Number(o.task_id) !== Number(taskId)) continue
    if (o.strategy_type === 2) continue
    const tv = Number(o.traded_volume) || 0
    if (o.order_type === '23') buy += tv
    else if (o.order_type === '24') sell += tv
  }
  return buy - sell
}

// 主表"配平"按钮文案 (动态)
function balanceBtnLabel(taskId) {
  const diff = _taskNetDiff(taskId)
  if (diff === 0) return '已平衡'
  if (diff > 0) return `补卖 ${diff}`
  return `补买 ${-diff}`
}

// 主表"配平"按钮 disabled 条件 (diff=0)
function computeRowBalanceDiff(taskId) {
  return _taskNetDiff(taskId)
}

// 当前选中 task 的差值 (下半 header hint 用)
const selectedTaskDiff = computed(() => _taskNetDiff(selectedTaskId.value))

// 委托状态格式化: 统一用 STATUS_LABEL 字典 (format.js), 与下单页 / 历史委托 / Trade.vue 一致.
// 不用私有映射 (旧私有映射有错: '51' 应是 '已报待撤', '56' 应是 '已成' 等).
const orderStatusLabel = (s) => STATUS_LABEL[s] || String(s || '—')
const orderStatusTagType = (s) => STATUS_TYPE[s] || 'default'

// ---- T0Trade 委托表撤单按钮 ----
// 可撤状态白名单 - 仅 已报(50) / 部成(55) 可撤 (与 TodayOrdersPanel 一致)
const CANCELLABLE_STATUSES = new Set(['50', '55'])
const cancellingOrderNo = ref('')
function canCancel(row) {
  if (!row) return false
  if (Number(row.order_flag) === 1) return false  // 本地代理撤单委托行,不能再撤
  return CANCELLABLE_STATUSES.has(String(row.status))
}
async function handleCancel(row) {
  if (!row || !canCancel(row)) return
  cancellingOrderNo.value = row.order_no
  try {
    await orderStore.cancelOrder(row.order_no, row.trd_date)
    ElMessage.success(`已发起撤单 #${row.order_no}`)
  } catch (e) {
    ElMessage.error('撤单失败：' + (e?.message || String(e)))
  } finally {
    cancellingOrderNo.value = ''
  }
}

// 价格类型选项用 PriceTypeInput 内置 + PriceType.label(code); 无本地 priceTypeOptions
const qtyBaseOptions = [
  { value: 'vol',       label: '当前持仓' },
  { value: 'avl_vol',   label: '可用数量' },   // '可用数量' (比 '可用持仓' 更精准)
  { value: 'last_vol',  label: '期初持仓' },
]  

// vol 计算 — 按 globalMode × globalPctInput / globalQtyInput + trade_unit 取整 + ≥ min_buy_qty
//   数据源:
//     - base (pct 模式): holdingsStore.positions[stockCode][globalQtyBase]  (实时) — 卖时
//                        holdingsStore.cachedAsset.available / quoteStore.get(code).last_price — 买时
//     - pct (pct 模式): globalPctInput / 100 (用户输入百分数 → 比例)
//     - qty (qty 模式): globalQtyInput (用户直接输入股数)
//     - trade_unit/min_buy_qty: stocksStore.stocks (按 stock_code 实时匹配)
//   取整规则: floor(raw / unit) * unit  (浮点→整数倍)
//   下界: max(unit_adjusted, min_buy_qty)  (允许小幅超出 raw 一档 unit)
//   重写分发
//     - mode='pct': pct 模式, 用 globalPctInput(百分数)/100 × base
//     - mode='qty': qty 模式, 直接用 globalQtyInput (股数), 与持仓无关
//   按比例下, 买入 base = 可用金额 / 最新价 (可买股数)
//     - 卖 base = qtyBaseOptions 选的 vol/avl_vol/last_vol (持仓基数)
//     - qtyBaseOptions 仅 pct 模式有意义 (qty 模式直接读输入框)
//   ⚠️ 注意: base 仅影响 base/raw/pct 显示字段, 实际下单 volume 用 floor(raw/unit)*unit
//     买时 raw = available/last_price*pct, floor 到 trade_unit 倍数后 → real volume
//     (这意味着 1 股为单位时按用户实际能买多少股, 不强制 min_buy_qty 100 — 仅做下界保护)
function computeOrderVolume(stockCode, direction = '买') {
  const stock = (stockCode ? stocksStore.cacheMap.get(stockCode) : {}) || {}
  const trade_unit = Number(stock.trade_unit) || 1
  const min_buy_qty = Number(stock.min_buy_qty) || 100
  if (!stockCode) return { volume: 0, raw: 0, trade_unit, min_buy_qty, base: 0, pct: 0 }
  // qty 模式: 直接用股数输入, 与持仓/资金无关
  if (globalMode.value === 'qty') {
    const raw = Number(globalQtyInput.value) || 0
    const unit_adjusted = Math.floor(raw / trade_unit) * trade_unit
    const volume = Math.max(unit_adjusted, min_buy_qty)
    return { volume, raw, trade_unit, min_buy_qty, base: raw, pct: 1, mode: 'qty' }
  }
  // amount 模式: 金额 / 最新价 → 股数 → 按 trade_unit 取整
  if (globalMode.value === 'amount') {
    const amount = Number(globalAmountInput.value) || 0
    const price = quoteStore.getLastPrice(stockCode) || 0
    const raw = price > 0 ? amount / price : 0
    const unit_adjusted = Math.floor(raw / trade_unit) * trade_unit
    const volume = Math.max(unit_adjusted, min_buy_qty)
    return { volume, raw, trade_unit, min_buy_qty, base: amount, pct: 1, mode: 'amount' }
  }
  // pct 模式: 按方向取 base
  //   - 买: base = available_cash / last_price (能买的股数上限)
  //   - 卖: base = positions[stockCode][qtyBase] (持仓基数)
  let base = 0
  if (direction === '买') {
    const a = holdingsStore.cachedAsset || {}
    const cash = Number(a.available ?? a.cash) || 0
    const q = quoteStore.get(stockCode) || {}
    const last = Number(q.last_price) || 0
    base = last > 0 ? cash / last : 0
  } else {
    const pos = (holdingsStore.positions || []).find(p => p.stock_code === stockCode)
    base = Number(pos?.[globalQtyBase.value]) || 0
  }
  const pct = (Number(globalPctInput.value) || 0) / 100
  const raw = base * pct
  const unit_adjusted = Math.floor(raw / trade_unit) * trade_unit
  const volume = Math.max(unit_adjusted, min_buy_qty)
  return { volume, raw, trade_unit, min_buy_qty, base, pct, mode: 'pct', direction }
}

// 无 computeOrderPrice — 取最新价的职责在 _recomputeOrderPrice (按价格类型分发)

// 市价下单保护限价（上交所要求：对手盘第五档价格）
// 买入时对手盘 = 卖盘 → ask_prices[4]（卖五）
// 卖出时对手盘 = 买盘 → bid_prices[4]（买五）
// 未取到第五档 → 涨跌停价格（买入用涨停，卖出用跌停）
// 深交所市价无需保护限价，传 0
function _marketOrderProtectPrice(stockCode, orderType) {
  const isSSE = stockCode.startsWith('6')
  if (!isSSE) return 0  // 深交所无需保护限价
  const q = quoteStore.get(stockCode) || {}
  const isBuy = orderType === '23'
  const oppPrices = isBuy ? q.ask_prices : q.bid_prices  // 买→看卖盘，卖→看买盘
  if (oppPrices && oppPrices.length >= 5 && oppPrices[4]) {
    return Number(oppPrices[4]) || 0
  }
  // 未取到第五档，回退涨跌停价
  const prevClose = q.prev_close || (q.fields ? Number(q.fields[6]) : 0)
  if (prevClose && prevClose > 0) {
    const scale = stocksStore.stockScale(stockCode)
    const limit = isBuy ? prevClose * 1.10 : prevClose * 0.90
    return Number(Number(limit).toFixed(scale))
  }
  return 0
}

// 配平下单价格：跟随做T配置价格类型
function _balancePrice(stockCode, orderType) {
  const pt = orderPriceTypeCode.value
  if (pt === PriceType.MARKET_PEER_PRICE_FIRST) return _marketOrderProtectPrice(stockCode, orderType)
  const p = quoteStore.getLastPrice(stockCode)
  return Number(p) || 0
}

// 根据价格类型 + 当前选中 stock_code, 自动填 orderPrice
//   11 (限价) → 选中 row 时自动填 last_price, 用户可手动改
//   5 (最新价) → 0 (UI + 下单 price 都传 0, 柜台撮合)
//   44 (市价) → SSE 取 5 档对手价; 非 SSE = 0
function _recomputeOrderPrice() {
  const code = orderPriceTypeCode.value
  const codeText = selectedStockCode.value
  if (!codeText) {
    orderPrice.value = 0  // 未选标的, 价格归零
    return
  }
  if (code === PriceType.FIX_PRICE) {
    orderPrice.value = Number(quoteStore.getLastPrice(codeText)) || 0
  } else if (code === PriceType.LATEST_PRICE) {
    orderPrice.value = 0
  } else if (code === PriceType.MARKET_PEER_PRICE_FIRST) {
    const p = _marketOrderProtectPrice(codeText, '23')  // 买入方向取保护价
    orderPrice.value = (p > 0) ? p : 0
  }
}

// 监听价格类型切换 + 选中 task 变化 → 重填 orderPrice
watch(orderPriceTypeCode, () => _recomputeOrderPrice())
watch(selectedTaskId, () => _recomputeOrderPrice())

// 主表行单击 → 选中/切换 task (联动下半表)
// 再点同一行 **保留** 焦点 (不清空 selectedTaskId, 交易明细不重置);
//   只有换不同行才切换焦点 (toggle 清空行为会让用户误失焦, 下半交易明细被清空体验差).
function onTaskRowClick(row) {
  // 同 row: 直接返回, 保持 selectedTaskId + 联动状态不变
  if (selectedTaskId.value === row.id) return
  // 切换到不同 row
  selectedTaskId.value = row.id
  const t = t0TasksStore.tasksById[row.id]
  if (t && t.stock_code) stockCode.value = t.stock_code
}

// ---- 主表数据源 (task 视角) ----
// taskRows 定义已提前至上方 watch 之前 (TDZ 规避), 此处不重复声明

function ptRowClass({ row }) {
  const classes = []
  if (row.id === selectedTaskId.value) classes.push('is-selected')
  return classes.join(' ')
}

// ---- 排序 (简化: 只支持 做T盈亏 / 做T收益率% / 当前持仓 3 列) ----
const sortBy = ref(null)
const sortOrder = ref(null)
function onSortChange({ prop, order }) {
  sortBy.value = order ? prop : null
  sortOrder.value = order || null
}
function _taskSortValue(row, key) {
  switch (key) {
    case 'position_vol': return Number(row.summary?.position_vol) || 0
    case 't0_pnl': return t0PnlForRow(row)?.total_pnl || 0   // 总盈亏
    case 't0_today_pnl': return t0PnlForRow(row)?.today_pnl || 0   // 当日做T盈亏
    default: return 0
  }
}

// 纯委托+实时盘口 PnL — 实现放在 setup 内 (上方注释见)
//   不调 quoteStore.getDepth(code) (那是另封装), 直接 quoteStore.get(code) 拿整个行情结构体, 取结构体已有字段 bid_prices[0] / ask_prices[0]
//   quoteStore.byCode 是 shallowRef(Map), update() 内 byCode.value.set(...) + triggerRef(byCode) 让 cell 自动重渲
// PnL 公式
//   - diff = cur - target, diff<0 需买, diff>0 需卖
//   - 价格不区分 ask1/bid1, 统一用最新价 (last_price), PnL = realized + diff × last_price
//   - 配平盘口金额 rate 分母: 统一 diff × last_price (按"按最近价平掉"的市值估算)
// PnL 分两字段
//   - total_pnl: task 创建以来累计 (当前公式) = realized + diff × last_price
//   - today_pnl: 仅当日做T操作平衡后的盈亏 (只算 trd_date === activeDay 的订单)
//     = (今日sell_amt - 今日buy_amt) - (今日净持仓 × last_price)
//     含义: 假设今日做T完全平仓 (净持仓=0), realized = (sell-buy) → 直接是今日做T赚的;
//          如果今日剩有净持仓 (没平完), 扣掉 净持仓 × 现价 (这部分不是做T赚的, 是持仓市值);
//          今日纯做T部分 = (sell_amt - buy_amt) - 净持仓兑现
//     注意: 用户口径 "收益率去掉" → 表格只显示绝对值, 不显示收益率 %
function _calcT0Pnl(code, taskId, base, tgv, orders) {
  // 不调用 quoteStore / holdingsStore, 仅凭参数算 — 方便纯算或给 computed 喂值
  let buyAmt = 0, buyVol = 0, sellAmt = 0, sellVol = 0
  for (const o of orders) {
    const tv = Number(o.traded_volume) || 0
    if (tv <= 0) continue
    const ap = Number(o.avg_price) || 0
    if (!ap) continue
    if (o.order_type === '23') {         // 买
      buyAmt += ap * tv
      buyVol += tv
    } else if (o.order_type === '24') {  // 卖
      sellAmt += ap * tv
      sellVol += tv
    }
  }
  const realized = sellAmt - buyAmt
  const cur = buyVol - sellVol                         // 净持仓 (正=持仓多)
  const target = (Number(base) || 0) + (Number(tgv) || 0)
  // 新语义: diff = 净持仓 - 目标, 负表示需买, 正表示需卖
  const diff = cur - target
  const q = quoteStore.get(code) || {}
  const last = Number(q.last_price) || 0
  const total_pnl = (diff === 0)
    ? realized
    : (last ? realized + diff * last : realized)
  return { total_pnl, diff, last }
}

// 当日做T盈亏 = 用总盈亏公式 (realized + diff × last_price),
//   但 orders 仅过滤 trd_date === activeDay (只看今日委托)
//   与做T总盈亏用相同公式, 仅订单范围不同 → 两栏对比一目了然
function _calcTodayT0Pnl(code, taskId, base, tgv, orders, activeDay) {
  const todayOrders = activeDay
    ? orders.filter((o) => String(o.trd_date) === String(activeDay))
    : []
  const { total_pnl, diff, last } = _calcT0Pnl(code, taskId, base, tgv, todayOrders)
  return total_pnl   // 返回数字 (直接返回对象 {total_pnl, ...} 会被模板当数字用显示成 0)
}

// PnL 反应式 — 行情推过来时由依赖触发 recompute
//   - t0PnlMap: 字典 { "taskId|stock_code": { pnl, rate, diff, ... } }
//   - template 从 t0PnlMap.value[rowKey(row)] 读, 函数 t0PnlForRow 改成 thin wrapper (回退兼容)
// t0PnlMap computed 显式订阅 quoteStore.tick.value
//   - quoteStore.byCode 是 shallowRef(Map), triggerRef(byCode) 在某些
//     el-table cell render 路径下不广播 (cell render 是 v-once 函数 cache 不更新)
//   - 兜底: tick 是 ref, 每次 quote update() 自增, computed 读 tick.value
//     自动订阅 — tick 变 → computed 重算 → t0PnlMap.value 引用变 → cell 重渲.
const t0PnlMap = computed(() => {
  const _tick = quoteStore.tick.value  // 显式订阅
  void _tick
  const out = {}
  const orders = holdingsStore.orders || []
  const tasks = t0TasksStore.tasks || []
  const activeDay = holdingsStore.activeTrdDate || ''  // 当日做T盈亏过滤用
  for (const row of tasks) {
    if (!row || row.status === 'archived') continue
    const code = row.stock_code
    if (!code) continue
    const taskId = row.id
    const base = Number(row.base_volume) || 0
    const tgv = Number(row.target_volume) || 0
    const rs = orders.filter(
      o => o.stock_code === code
        && Number(o.task_id) === Number(taskId)
        && o.order_flag !== 1
        && o.strategy_type !== 2  // 排除策略下单母单子单
    )
    const { total_pnl, diff, last } = _calcT0Pnl(code, taskId, base, tgv, rs)
    // 当日做T盈亏 (trd_date === activeDay)
    const today_pnl = _calcTodayT0Pnl(code, taskId, base, tgv, rs, activeDay)
    // debug: 诊断日志 (window.__t0PnlDebug 开关)
    if (window.__t0PnlDebug && (window.__t0PnlDebug === taskId || window.__t0PnlDebug === 'all')) {
      const todayRs = activeDay ? rs.filter(o => String(o.trd_date) === String(activeDay)) : []
      console.log(`[t0Pnl ${taskId}|${code}] activeDay=${activeDay} rs.total=${rs.length} todayRs=${todayRs.length} total_pnl=${total_pnl} today_pnl=${today_pnl} diff=${diff} last=${last}`)
    }
    // 无 rate 字段 (用户口径: 去掉做T收益率)
    out[`${taskId}|${code}`] = { total_pnl, today_pnl, diff, last }
  }
  return out
})
function _rowKey(row) { return row ? `${row.id}|${row.stock_code}` : '' }
// t0PnlCell 显式订阅 quoteStore.tick, 确保 el-table 重渲
//   - tick 是 ref, 读 .value 才是当前值 (Vue 收集依赖是基于 .value 访问)
//   - 因为函数在 render 函数上下文执行, .value 访问会被 render 收集依赖
//   - 兜底如果 t0PnlMap.value 不在依赖图 (e.g. el-table 模板缓存), tick 自增能强制刷
function t0PnlCell(row) {
  void quoteStore.tick.value    // ← 显式订阅, 触发 render 重跑
  return t0PnlMap.value[_rowKey(row)] || null
}
function t0PnlForRow(row) {
  // 从 t0PnlMap 读 (响应式), 不实时算
  const m = t0PnlMap.value
  const it = m[_rowKey(row)]
  return it ? it.pnl : 0
}
function t0ReturnRateForRow(row) {
  // 空 stub (用户口径"去掉做T收益率") — 保留防止外部 import 引用, 函数返回 0
  return 0
}
const sortedTaskRows = computed(() => {
  const list = [...taskRows.value]
  if (!sortBy.value || !sortOrder.value) return list
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  list.sort((a, b) => (_taskSortValue(a, sortBy.value) - _taskSortValue(b, sortBy.value)) * dir)
  return list
})

// ---- 状态 helpers ----
function statusLabel(s) {
  return s === 'active' ? '活跃' : s === 'closed' ? '已平仓' : s === 'archived' ? '已归档' : s || '—'
}
function statusTagType(s) {
  if (s === 'active') return 'primary'
  if (s === 'closed') return 'info'
  return 'danger'
}

// ---- 做T盈亏 / 收益率 (纯委托 + 实时盘口口径, 不依赖 cost_basis) ----
//
// 口径 (user 业务定义, "实时盘口"而非 cost_basis 静态值):
//   1) 已实现: Σ(卖成交量 × 卖成交均价) − Σ(买成交量 × 买成交均价)
//   2) 配平盘口 (按当前已成交净持仓 vs 目标 base+target):
//        cur    = Σ(买成交) − Σ(卖成交)         // 当前净持仓
//        target = base_volume + target_volume   // 配平目标
//        diff   = cur − target
//        diff<0: 需买; diff>0: 需卖
//   3) 表格只显示绝对值盈亏, 不显示收益率 % (用户口径)
// 当前公式: PnL = realized + diff × last_price (价格统一用最新价)
// 数据源: holdingsStore.orders (同 stock_code 即为该 task 下所有委托), quoteStore.get(code) (行情表结构体已有字段).
// 实现位置: 在 setup 块内 (见 _taskSortValue 下方) — 因 holdingsStore/quoteStore 是 setup 内 const,
//   setup 外定义会 ReferenceError.
// ---- 实现 ---- (setup 内部, 见下方 t0PnlForRow / t0ReturnRateForRow)

// ---- task 操作 ----
function onTaskChange(taskId) {
  selectedTaskId.value = taskId
  if (taskId) {
    const t = t0TasksStore.tasksById[taskId]
    if (t) stockCode.value = t.stock_code
  }
}
function onOpenTaskDetail(taskId) {
  viewingTaskId.value = taskId
  tasksDetailVisible.value = true
}
// 配平按钮: 前端算差值 + 调用 useT0OrderSubmit 下市价单
async function onBalanceTask(taskId) {
  const diff = _taskNetDiff(taskId)
  if (diff === 0) {
    ElMessage.info(`task #${taskId} 已平衡，无需操作`)
    return
  }
  // 防 balanceStockCode 空导致后端校验失败
  //   server/api/orders/place.py:84 校验 task.stock_code != req.stock_code → 报错
  //   兜底: selectedTaskId 失效 / tasksById 缺失 stock_code 时, 直接从 taskRows 拿 row.stock_code
  let stockCodeForBalance = balanceStockCode.value
  if (!stockCodeForBalance) {
    const row = taskRows.value.find((t) => t.id === taskId)
    if (row?.stock_code) {
      stockCodeForBalance = row.stock_code
      log('warn', 'T0', 'balance', `balanceStockCode 为空, 从 taskRows[${taskId}].stock_code 兜底`)
    } else {
      ElMessage.error(`task #${taskId} 缺少 stock_code, 无法配平`)
      return
    }
  }
  const orderType = diff > 0 ? '24' : '23'  // 反向: 多买则卖, 多卖则买
  const volume = Math.abs(diff)
  try {
    await ElMessageBox.confirm(
      `task #${taskId} 实时差 ${diff} 股，将下 ${PriceType.label(orderPriceTypeCode.value)} ${orderType === '23' ? '买' : '卖'} ${volume} 股`,
      '一键配平', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  try {
    // 用 stockCodeOverride 让 useT0OrderSubmit
    //   优先用兜底 stock_code (而不是闭包 stockCode.value, 后者可能为空)
    await submitBalanceOrder({ orderType, volume, price: _balancePrice(stockCodeForBalance, orderType), taskId, stockCodeOverride: stockCodeForBalance })
    // useT0OrderSubmit 内部已 ElMessage.success
    await t0TasksStore.loadTasks()  // 刷新主表（task summary 更新）
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}

// 主表 row 操作按钮可用性 — archived task 任何按钮都不能用
function canOpRow(row) {
  return row.status !== 'archived' && !!row.stock_code
}

// 买/卖按钮 (走全局配置: pct × qtyBase → vol, latest/market → price)
// 价格直接用 orderPrice.value (FIX_PRICE 由 watcher 自动填 + 用户可改; 最新价/市价 由 watcher 预填 0/5 档)
function _prepareOrderPayload(row, direction) {
  const stockCode = row.stock_code
  // computeOrderVolume 接受 direction 参数 — 买入 base=可用金额/最新价
  const volInfo = computeOrderVolume(stockCode, direction)   // {volume, raw, trade_unit, min_buy_qty, base, pct}
  if (!volInfo || !volInfo.volume || volInfo.volume <= 0) {
    ElMessage.warning(`${row.stock_code} 按当前配置算不出可下单数量（可能持仓为空或 0%）`)
    return null
  }
  const orderType = direction === '买' ? '23' : '24'
  return {
    direction, stockCode, price: orderPrice.value, volume: volInfo.volume,
    orderType,                                       // 后端 Pydantic 必填
    taskId: row.id,
    mode: globalMode.value,                          // 'pct' | 'qty' | 'amount'
    qtyBase: globalQtyBase.value,                    // 仅 pct 模式有意义
    pct: globalPctInput.value,                       // pct 模式: 百分数
    qty: globalQtyInput.value,                       // qty 模式: 股数
    amount: globalAmountInput.value,                 // amount 模式: 金额
    priceType: orderPriceTypeCode.value,             // numeric PriceType (11/5/44)
    // 取整提示信息 (供 dialog 显示)
    base: volInfo.base,
    raw: volInfo.raw,
    tradeUnit: volInfo.trade_unit,
    minBuyQty: volInfo.min_buy_qty,
  }
}
// 买/卖 row 按钮联动选中
// row-click 只在换不同行时才同步 selectedTaskId;
//   同 row 二次点击保留焦点 (clear 下半交易明细的旧 toggle 行为已废)
//   - 已选中 → 不重置价格 (用户可能手动改过)
async function onBuyTask(row) {
  if (!canOpRow(row)) {
    ElMessage.warning('该任务不可下单（无标的或已归档）')
    return
  }
  if (selectedTaskId.value !== row.id) {
    onTaskRowClick(row)
    await nextTick()  // 等 watcher 跑完, orderPrice 已是新 stock 的最新价
  }
  const payload = _prepareOrderPayload(row, '买')
  if (!payload) return
  // 二次确认由 order.js 统一拦截, 这里直接下单
  await _submitOrder(payload)
}
async function onSellTask(row) {
  if (!canOpRow(row)) {
    ElMessage.warning('该任务不可下单（无标的或已归档）')
    return
  }
  if (selectedTaskId.value !== row.id) {
    onTaskRowClick(row)
    await nextTick()
  }
  const payload = _prepareOrderPayload(row, '卖')
  if (!payload) return
  // 二次确认由 order.js 统一拦截, 这里直接下单
  await _submitOrder(payload)
}

// 二次确认 dialog 用户点"确认下单" 才真正下单
async function _submitOrder(p) {
  try {
    // priceType 已是 numeric (11/5/44); watcher 已预填 orderPrice, 不需要再重算保护限价
    const priceTypeCode = p.priceType
    // SSE 市价保护限价守卫 — 上交所需对手盘 5 档 (或涨跌停兜底), 未就绪时拒单
    if (
      priceTypeCode === PriceType.MARKET_PEER_PRICE_FIRST
      && (!p.price || p.price <= 0)
      && p.stockCode.startsWith('6')
    ) {
      ElMessage.warning(`市价保护限价未就绪（上交所需对手盘第 5 档或涨跌停价），请稍候再试`)
      return null
    }
    const res = await orderStore.placeOrder({
      stock_code: p.stockCode,
      order_type: p.orderType,
      price_type: priceTypeCode,
      price: p.price,
      volume: p.volume,
      user_def: 'T0',
      strategy_type: 1,  // REQ-TRADE-026; T0Trade.vue 下单 = 快速做T
      ...(p.taskId ? { task_id: p.taskId } : {}),
    })
    ElMessage.success(`${p.direction}单已报：${p.stockCode} ${p.volume} 股 @ ${priceTypeCode === PriceType.MARKET_PEER_PRICE_FIRST ? '市价' : '¥' + formatPrice(p.price, p.stockCode)}`)
    return res
  } catch (e) {
    const detail = e?.response?.data?.detail
    ElMessage.error(detail?.msg || e.message || '下单失败')
    return null
  }
}

async function onCloseTask(taskId) {
  try {
    await ElMessageBox.confirm(
      `确认一键平仓 task #${taskId} 到 base_volume？将生成平仓委托`,
      '一键平仓', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  try {
    const r = await t0TasksStore.closeTask(taskId)
    ElMessage.success(`task #${taskId} 已平仓：${r.action} ${r.volume} 股`)
    await t0TasksStore.loadTasks()
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}
async function onArchiveTask(taskId) {
  try {
    await ElMessageBox.confirm(
      `确认归档 task #${taskId}?`,
      '归档 task', { confirmButtonText: '确认归档', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  try {
    await t0TasksStore.archiveTask(taskId)
    ElMessage.success(`task #${taskId} 已归档`)
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}

// ---- 添加任务 dialog ----
function onAddTaskOpen() {
  externalStockCode.value = ''
  createDialogVisible.value = true
}
function onAddTaskDialogOpen() {
  // dialog 打开后清空 externalStockCode, 让 HoldingsPanel 单击能驱动
  externalStockCode.value = ''
}
function onHoldingSelected({ stock_code, stock_name }) {
  externalStockCode.value = stock_code
}
async function onCreateTaskSubmit(form) {
  createDialogLoading.value = true
  try {
    const t = await t0TasksStore.createTask(form)
    if (t && t.id) {
      ElMessage.success(`task #${t.id} 创建成功，自动选中`)
      selectedTaskId.value = t.id
      if (t.stock_code) stockCode.value = t.stock_code
      createDialogVisible.value = false
    }
  } finally {
    createDialogLoading.value = false
  }
}

// ---- 刷新 ----
async function onRefresh() {
  refreshing.value = true
  try {
    await t0TasksStore.loadTasks()
  } finally {
    refreshing.value = false
  }
}

// ---- 初始化 ----
onMounted(async () => {
  await t0TasksStore.loadTasks()
  if (!stockCode.value && taskRows.value.length > 0) {
    stockCode.value = taskRows.value[0].stock_code
  }
})
</script>

<style scoped>
.t0-trade {
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  height: calc(100% - var(--oplog-extra, 0px));
  min-height: 0;
  overflow: hidden;
}
/* 无 .t0-header / .t0-title / .qs-row — 工具栏在 .t0-config-bar */
.task-table {
  width: 100%;
}
.op-col {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.up { color: var(--el-color-danger, #f56c6c); }
.down { color: var(--el-color-success, #67c23a); }
.muted { color: var(--el-text-color-placeholder, #c0c4cc); }

/* 添加任务 dialog 2 列布局 */
.add-task-grid {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 16px;
  height: 480px;
}
.add-task-left,
.add-task-right {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.add-task-left {
  border-right: 1px solid var(--el-border-color-light, #ebeef5);
  padding-right: 12px;
}
.left-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  margin-bottom: 8px;
  flex-shrink: 0;
}
.add-task-right :deep(.el-dialog) {
  /* dialog 内部嵌套消除二次 dialog 包裹 */
  margin: 0;
}

/* 二次确认 dialog 内部样式 */
.confirm-order-dialog .confirm-detail {
  padding: 0 8px;
}
.confirm-order-dialog .confirm-row {
  display: flex;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter, #ebeef5);
}
.confirm-order-dialog .confirm-row:last-child {
  border-bottom: none;
}
.confirm-order-dialog .confirm-row .label {
  width: 100px;
  color: var(--el-text-color-secondary, #909399);
  font-size: 13px;
}
.confirm-order-dialog .confirm-row .value {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary, #303133);
}
.confirm-order-dialog .confirm-row .value .hint {
  font-weight: 400;
  color: var(--el-text-color-secondary, #909399);
  font-size: 12px;
  margin-left: 6px;
}
.confirm-order-dialog .confirm-row .value.up {
  color: var(--el-color-success, #67c23a);
}
.confirm-order-dialog .confirm-row .value.down {
  color: var(--el-color-danger, #f56c6c);
}

/* 上下分区布局: 上半主表 + 下半委托表, 1:1 flex column */
.t0-split {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
/* 做T全局配置 row — 4 select + 1 checkbox */
.t0-config-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-fill-color-light, #f5f7fa);
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 4px;
  margin: 0 0 8px 0;
  font-size: 12px;
  flex-wrap: wrap;
}
.t0-config-bar .t0-config-label {
  font-weight: 600;
  color: var(--el-text-color-primary, #303133);
  margin-right: 4px;
}
/* 选 task 选择器靠右固定宽度 — 推到右的力交给 .t0-spacer (flex:1) 吃 */
.t0-config-bar .qs-task-select {
  width: 200px;
}
/* 弹性占位 — 把 (刷新/添加任务/选 task) 整体推到最右 */
.t0-config-bar .t0-spacer {
  flex: 1;
}
.t0-config-bar .t0-config-hint {
  color: var(--el-text-color-secondary, #909399);
  font-size: 11px;
  margin-left: 8px;
}
/* 单位提示 (%/股) 紧贴 el-input-number 右侧 */
.t0-config-bar .t0-unit-hint {
  color: var(--el-text-color-regular, #606266);
  font-size: 12px;
  margin-left: -8px;     /* 覆盖 el-input-number 后侧 wrap-padding, 让 % 紧贴输入框 */
  margin-right: 6px;
  user-select: none;
}
.t0-upper,
.t0-lower {
  display: flex;
  flex-direction: column;
  flex: 1 1 50%;
  min-height: 0;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 6px;
  background: var(--el-fill-color-blank, #fff);
  overflow: hidden;
}
.t0-upper { flex-basis: 50%; }
.t0-lower { flex-basis: 50%; }
.area-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  background: var(--el-fill-color-light, #f5f7fa);
  border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5);
  flex-shrink: 0;
}
.task-table,
.order-table {
  width: 100%;
  flex: 1;
  min-height: 0;
}
.task-table :deep(.el-table__body-wrapper),
.order-table :deep(.el-table__body-wrapper) {
  /* 让 el-table 内部滚动条工作 */
  overflow-y: auto;
  overflow-x: auto; /* 主表 9 列宽 1150px > 容器 1010px, 允许横滚 (操作列 fixed 浮动) */
}

/* 选中行美化 - 品牌色低透明度背景 + 4px 左侧强调边, 亮/暗自适应
   rgba(brand-primary, 0.10/0.18) 跟随品牌色, 暗色加深一档 */
.task-table :deep(.el-table__row.is-selected) > td {
  background-color: rgba(79, 124, 255, 0.10) !important;
  box-shadow: inset 4px 0 0 0 var(--brand-primary);
}
.task-table :deep(.el-table__row.is-selected):hover > td {
  background-color: rgba(79, 124, 255, 0.16) !important;
}
html.dark .task-table :deep(.el-table__row.is-selected) > td {
  background-color: rgba(79, 124, 255, 0.18) !important;
}
html.dark .task-table :deep(.el-table__row.is-selected):hover > td {
  background-color: rgba(79, 124, 255, 0.26) !important;
}
</style>
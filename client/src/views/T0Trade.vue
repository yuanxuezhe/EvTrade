<!--
  T0Trade.vue — 快速做T 主页面

  v93 (本轮): UI 整改 (二次确认挪到 sysconfig 见上一个 feat commit)
    - 去标题 "⚡ 快速做T"
    - 顶部独立按钮行删除: (刷新/添加任务/任务筛选) 全部挪到做T配置行末尾 (从右到左: 刷新 → 添加任务 → 任务筛选)
    - 标的列宽 180 → 90 (减一半)

  v74 (本轮): 委托表 11→15 列对齐今日委托
    - 加列: 交易日 / 类型(委托/撤单) / 标的(代码+名称合并) / 操作(撤单按钮)
    - 改: 委托号→委托编号(label); 状态列 el-tag→OrderStatusBadge(对齐今日委托);
         下单时间 (90 + slice(0,8)) → (185 全显)
    - 接入 COL 常量: STOCK_CODE/TARGET/NUMBER/MONEY/STATUS/TIME/2×makeDict
    - 撤单: canCancel(row) 守卫 + handleCancel(row) 调 orderStore.cancelOrder
    - 不动: 上半主表(task 视角 8 列)/ 配平逻辑/ 备注列(放最后)

  v55 (commit 24c7b07): 主表 task 视角 (每行 = 1 做T 任务) + 900px 添加任务 dialog 集成 HoldingsPanel + T0TaskCreateDialog

  v55.1 (本轮): 上下分区布局
    ┌──────────────────────────────┐
    │ Header (标题/选择/添加/刷新)     │
    ├──────────────────────────────┤
    │ 上半: 主表 8 列 (task 视角)     │
    ├──────────────────────────────┤
    │ 下半: 当前 task 的实时委托表     │
    │   - 7 列 (委托号/方向/价格/数量/  │
    │     状态/下单时间/备注)           │
    │   - 数据源: holdings.orders     │
    │     .filter(o => o.task_id===id)│
    └──────────────────────────────┘

  v55.1 数据流:
    主表行选中 / el-select 选 task
      → selectedTaskId.value 变化
      → lowerArea filteredTaskOrders 自动响应
      → computeSelectedTaskDiff() 实时算差 → 配平按钮文案 + disabled 状态

  v55.1 配平按钮 (前端计算 + 下市价单):
    - 算: holdings.orders.filter(o=>o.task_id===id)
        .reduce((d, o) => d + (order_type==='23'?+1:-1) * (traded_volume||0), 0)
    - 方向: diff>0 多买 → SELL; diff<0 多卖 → BUY; diff===0 按钮 disabled
    - 下单: useT0OrderSubmit.submitOrder({orderType, volume: |diff|, price:0,
             priceType:'market' (priceTypeCode=44), taskId})
-->
<template>
  <div class="t0-trade fade-in-up">
    <!-- v93: 整页只剩一条工具栏行 — 做T配置 + (任务筛选 / 添加任务 / 刷新) 全部靠右集中 -->
    <!--   顺序(从右到左): 刷新 → 添加任务 → 任务筛选 → 提示文案 → 3 个 select -->
    <!-- change 2026-07-27-v109-mode-toggle: 工具栏 — 百分数 vs 股数 单选互斥输入框 -->
    <div class="t0-config-bar">
      <span class="t0-config-label">做T配置:</span>
      <!-- 模式一: 按比例 (el-radio-group 二选一, 互斥单选) -->
      <el-radio-group v-model="globalMode" size="small">
        <el-radio-button label="pct">按比例</el-radio-button>
        <el-radio-button label="qty">按数量</el-radio-button>
      </el-radio-group>
      <!-- 输入框按模式条件显隐 + 单位提示 -->
      <!-- change 2026-07-27-v109-mode-toggle: 输入框按模式条件显隐 + 单位提示 (两个分支各自独立 v-if, 不用 v-else 防中间被截断) -->
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
      <template v-else>
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
      <!-- 价格类型 + 持仓基数 (保留不动) -->
      <el-select v-model="globalPriceType" size="small" style="width: 100px">
        <el-option v-for="o in priceTypeOptions" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
      <el-select v-model="globalQtyBase" size="small" style="width: 110px">
        <el-option v-for="o in qtyBaseOptions" :key="o.value" :value="o.value" :label="o.label" />
      </el-select>
      <span class="t0-config-hint">（按比例=持仓×百分数（支持小数）/ 按数量=直接输入股数，价格按所选类型）</span>
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

    <!-- v55.1 上下分区: 上半主表 + 下半委托表 -->
    <div class="t0-split">
      <section class="t0-upper">
        <div class="area-hint">
          <el-icon><List /></el-icon><span>做T任务（共 {{ taskRows.length }} 条）</span>
        </div>
        <!-- 主表 8 列 (v55 task 视角) -->
        <el-table
          :data="taskRows"
          :row-class-name="ptRowClass"
          @sort-change="onSortChange"
          class="task-table"
          empty-text="暂无 T0 任务，点击「添加任务」按钮创建"
          size="default"
          @row-click="onTaskRowClick"
        >
      <!-- 1. 状态 (100) -->
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>

      <!-- 2. 任务编号 (90) -->
      <el-table-column prop="id" label="任务编号" width="90">
        <template #default="{ row }">
          <span class="text-mono">#{{ row.id }}</span>
        </template>
      </el-table-column>

      <!-- 3. 标的 (90: 代码 90, 名称挤到 hover tooltip - v93 列宽减半) -->
      <el-table-column label="标的" show-overflow-tooltip v-bind="COL.STOCK_TARGET">
        <template #default="{ row }">
          <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
          <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
        </template>
      </el-table-column>

      <!-- 4. 期初持仓 (90, sortable) — 数据源 holdingsStore.positions.last_vol -->
      <el-table-column prop="initial_position" label="期初持仓" align="right" width="90" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono">{{ formatNumber(holdingsStore.positions?.find(p=>p.stock_code===row.stock_code)?.last_vol ?? 0) }}</span>
        </template>
      </el-table-column>

      <!-- 5. 当前持仓 (80, sortable) — 数据源 holdingsStore.positions.vol -->
      <el-table-column prop="current_position" label="当前持仓" align="right" width="80" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono">{{ formatNumber(holdingsStore.positions?.find(p=>p.stock_code===row.stock_code)?.vol ?? 0) }}</span>
        </template>
      </el-table-column>

      <!-- 6. 最新价(涨跌幅) (140, sortable) — 数据源 quoteStore.getLastPrice + getChangePct -->
      <el-table-column prop="last_price" label="最新价(涨跌幅)" align="right" width="140" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono">{{ formatPrice(quoteStore.getLastPrice(row.stock_code), row.stock_code) }}</span>
          <span :class="(quoteStore.getChangePct(row.stock_code) ?? 0) >= 0 ? 'up' : 'down'" class="col-change"
            style="margin-left: 4px; font-size: 12px">
            <template v-if="quoteStore.getChangePct(row.stock_code) != null">
              {{ (quoteStore.getChangePct(row.stock_code) ?? 0) >= 0 ? '+' : '' }}{{ (quoteStore.getChangePct(row.stock_code)).toFixed(2) }}%
            </template>
            <template v-else>—</template>
          </span>
        </template>
      </el-table-column>

      <!-- change 2026-07-27-v109-pnl-reactive: template 走 t0PnlCell(row) 函数, 但函数体读 t0PnlMap computed -->
      <!--   - 直接调 t0PnlMap[`${...}`] 会有模板字符串解析问题, 用函数封装 -->
      <!--   - 关键: 函数内访问 t0PnlMap.value → Vue 自动追踪 computed 依赖 (byCode triggerRef → 重渲) -->
      <!-- 6. 做T总盈亏 (110, sortable) — task 创建以来累计 realized + 实时 unrealized (v115) -->
      <el-table-column prop="t0_pnl" label="做T总盈亏" align="right" width="110" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono" :class="(t0PnlCell(row)?.total_pnl ?? 0) >= 0 ? 'up' : 'down'">
            {{ (t0PnlCell(row)?.total_pnl ?? 0) >= 0 ? '+' : '' }}{{ formatMoney(t0PnlCell(row)?.total_pnl ?? 0) }}
          </span>
        </template>
      </el-table-column>

      <!-- v115: 当日做T盈亏 (110, sortable) — 仅当日做T操作平衡后的盈亏 (无收益率) -->
      <el-table-column prop="t0_today_pnl" label="当日做T盈亏" align="right" width="110" sortable="custom">
        <template #default="{ row }">
          <span class="text-mono" :class="(t0PnlCell(row)?.today_pnl ?? 0) >= 0 ? 'up' : 'down'">
            {{ (t0PnlCell(row)?.today_pnl ?? 0) >= 0 ? '+' : '' }}{{ formatMoney(t0PnlCell(row)?.today_pnl ?? 0) }}
          </span>
        </template>
      </el-table-column>

      <!-- 9. 操作 (280 fixed right) — 买 / 卖 / 配平 / 归档 -->
      <!-- v57 commit.2: 改 4 按钮 (买/卖/配平/归档), 详细说明见下方 -->
      <el-table-column label="操作" align="center" width="280" fixed="right">
        <template #default="{ row }">
          <div class="op-col">
            <!-- change 2026-07-21-t0-buy-red-sell-green: 买=红 danger / 卖=绿 success -->
            <el-button
              type="danger"
              size="small"
              :disabled="!canOpRow(row)"
              @click.stop="onBuyTask(row)"
            >买</el-button>
            <el-button
              type="success"
              size="small"
              :disabled="!canOpRow(row)"
              @click.stop="onSellTask(row)"
            >卖</el-button>
            <el-button
              v-if="row.status === 'active'"
              type="warning"
              link
              size="small"
              :disabled="computeRowBalanceDiff(row.id) === 0"
              @click.stop="onBalanceTask(row.id)"
            >{{ balanceBtnLabel(row.id) }}</el-button>
            <el-button
              v-if="row.status !== 'archived'"
              type="info"
              link
              size="small"
              @click.stop="onArchiveTask(row.id)"
            >归档</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>
      </section>

      <!-- 下半: 当前选中 task 的实时委托表 (跨日历史) -->
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
              ，共 {{ filteredTaskOrders.length }} 笔委托（v112: 不限日期, 含历史做T）
            </template>
            <template v-else>请先在上方主表选择 1 个 task，下方展示其委托与实时配平数量</template>
          </span>
        </div>
        <el-table
          :data="filteredTaskOrders"
          class="order-table"
          empty-text="该 task 暂无委托"
          size="default"
        >
          <!-- v74: 15 列对齐今日委托 (交易日/类型/标的/操作 4 列新增, 状态改 OrderStatusBadge, 下单时间去 slice 全显) -->
        <el-table-column prop="trd_date" label="交易日" v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_no" label="委托编号" show-overflow-tooltip v-bind="COL.STOCK_CODE">
          <template #default="{ row }">
            <span class="text-mono">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag v-if="Number(row.order_flag) === 1" type="warning" size="small">撤单</el-tag>
            <span v-else class="text-secondary">委托</span>
          </template>
        </el-table-column>
        <el-table-column label="标的" show-overflow-tooltip v-bind="COL.STOCK_TARGET">
          <template #default="{ row }">
            <span class="text-mono tp-stock-code">{{ row.stock_code }}</span>
            <span class="text-secondary" style="margin-left: 6px">{{ stockName(row.stock_code) || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_type" label="方向" v-bind="COL.DIRECTION">
          <template #default="{ row }">
            <el-tag :type="row.order_type === '23' ? 'danger' : 'success'" size="small">
              {{ row.order_type === '23' ? '买' : '卖' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="volume" label="委托量" v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.volume) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="委托价" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ formatPrice(row.price, row.stock_code) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_volume" label="成交量" v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.traded_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="avg_price" label="成交均价" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatPrice(row.avg_price, row.stock_code) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="traded_amount" label="成交金额" v-bind="COL.MONEY">
          <template #default="{ row }">
            <span class="text-mono">{{ row.traded_volume > 0 ? formatMoney(row.traded_amount) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="cancelled_volume" label="撤单量" v-bind="COL.NUMBER">
          <template #default="{ row }">
            <span class="text-mono">{{ formatNumber(row.cancelled_volume || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" v-bind="COL.STATUS">
          <template #default="{ row }">
            <OrderStatusBadge :status="row.status" :status_msg="row.status_msg" :remark="row.user_def" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              v-if="canCancel(row)"
              type="danger"
              size="small"
              :loading="orderStore.cancelling && cancellingOrderNo === row.order_no"
              @click="handleCancel(row)"
            >撤单</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="user_def" label="备注" min-width="120">
          <template #default="{ row }">
            <span class="text-secondary">{{ row.user_def || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="order_time" label="下单时间" v-bind="COL.TIME">
          <template #default="{ row }">
            <span class="text-mono">{{ row.order_time || '—' }}</span>
          </template>
        </el-table-column>
        </el-table>
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

    <!-- task 详情 drawer (保留 v54) -->
    <el-drawer v-model="tasksDetailVisible" :title="`task #${viewingTaskId} 详情`" size="55%" direction="rtl"
      :close-on-click-modal="false">
      <T0TaskDetail v-if="tasksDetailVisible" :task-id="viewingTaskId" embedding="drawer" />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { List, Document, Plus, InfoFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useQuoteStore } from '../stores/quote'
import { useStocksStore } from '../stores/stocks'
import { useT0TasksStore } from '../stores/t0_tasks'
import { useOrderStore } from '../stores/order'
import T0TaskDetail from '../components/trade/T0TaskDetail.vue'
import T0TaskCreateDialog from '../components/trade/T0TaskCreateDialog.vue'
import HoldingsPanel from '../components/trade/HoldingsPanel.vue'
import { useT0OrderSubmit } from '../composables/useT0OrderSubmit'
import { formatNumber, formatAmount, formatMoney } from '../utils/format'
import { formatPrice } from '../composables/usePricePrecision'
import { STATUS_LABEL, STATUS_TYPE } from '../utils/format'
import { stockName } from '../utils/stockNames'
import { COL } from '../utils/tableColumns'
import { makeLogger } from '../utils/logger'
import OrderStatusBadge from '../components/OrderStatusBadge.vue'

const log = makeLogger('T0Trade')

const holdingsStore = useHoldingsStore()
const quoteStore = useQuoteStore()
const stocksStore = useStocksStore()   // v57 commit.4: 取 min_buy_qty/trade_unit
const t0TasksStore = useT0TasksStore()
const orderStore = useOrderStore()
const { positions } = storeToRefs(holdingsStore)

const stockCode = ref(null)
const refreshing = ref(false)

// task 管理
const selectedTaskId = ref(null)
const tasksDetailVisible = ref(false)
const viewingTaskId = ref(null)

// v57: 操作列改造 — 全局配置 (页面顶部 row 共用)
// change 2026-07-27-v109-mode-toggle: ref 重写
//   globalMode: 'pct' | 'qty' 二选一互斥单选
//   globalPctInput: 直接是百分数 (用户视角 25 表示 25%, 支持小数), 计算时除以 100
//   globalQtyInput: 直接是股数 (整数)
const globalMode = ref('pct')              // 模式 'pct' (按比例) | 'qty' (按数量)
const globalPctInput = ref(25)             // 百分数 (用户视角 25 = 25%, 支持小数 0.001-100)
const globalQtyInput = ref(100)            // 股数 (整数 ≥ 1)
const globalPriceType = ref('market')      // change 2026-07-27-v109-default-market: 价格 'latest' (最新价 11) | 'market' (市价 44), 默认改为市价
const globalQtyBase = ref('last_vol')      // 数量基数 'vol'/'avl_vol'/'last_vol' (pct 模式下的基数)

// 添加任务 dialog
const createDialogVisible = ref(false)
const createDialogLoading = ref(false)
const externalStockCode = ref('')  // HoldingsPanel 选中 → 驱动 dialog 表单

// v55.1 配平: useT0OrderSubmit 实例化（mark 'market' + balanceCoeff=1）
const balancePriceType = ref('market')    // 市价 = priceTypeCode 44
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

// change 2026-07-21-t0-default-select-first: 进入页面/taskRows 变化时, 默认选中第一条
//   修复配平 stock_code=空 bug: balanceStockCode 依赖 selectedTaskId, 无选中时返回 ''
//   后端 place.py:84 校验 task.stock_code != req.stock_code → 报错
// v75 (fix): taskRows 必须在 watch 之前定义 — TDZ ReferenceError 否则整个 setup 抛错,
//   整个 T0Trade 页面渲染空白. 修复: 把 const taskRows 提升到此 watch 之前 (复用为下方的 taskRows).
const taskRows = computed(() => t0TasksStore.tasks || [])
watch(taskRows, (rows) => {
  if (!selectedTaskId.value && rows && rows.length > 0) {
    selectedTaskId.value = rows[0].id
  }
}, { immediate: true })

// ---- v55.1 上下分区: 下半委托表 + 实时配平 ----
// storeToRefs 是 pinia 解构 ref 必备
const { orders: holdingsOrders } = storeToRefs(holdingsStore)

// 下半委托表: 实时按 task_id 过滤 holdings.orders, 按 order_time desc
const filteredTaskOrders = computed(() => {
  if (!selectedTaskId.value) return []
  return holdingsOrders.value
    .filter((o) => Number(o.task_id) === Number(selectedTaskId.value))
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
    if (Number(o.task_id) !== Number(taskId)) continue
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

// 委托状态格式化 (v63: 与下单页 / 历史委托统一用 STATUS_LABEL 字典)
// 删除旧私有 orderStatusLabel (L510) + orderStatusTagType (L520), 它们映射错:
// 旧 '51' = '已成交' 应是 '已报待撤', '56' = '已撤(部)' 应是 '已成' 等.
// 现统一从 format.js STATUS_LABEL / STATUS_TYPE 取, 与 Trade.vue / HistoryOrders.vue 一致.
const orderStatusLabel = (s) => STATUS_LABEL[s] || String(s || '—')
const orderStatusTagType = (s) => STATUS_TYPE[s] || 'default'

// ---- v74: T0Trade 委托表加撤单按钮 ----
// v91: 可撤状态白名单 - 仅 已报(50) / 部成(55) 可撤 (与 TodayOrdersPanel 一致)
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

// change 2026-07-27-v109-mode-toggle: 选项列表 (清理 v109.1 的 9 档 pct + count 项)
const priceTypeOptions = [
  { value: 'latest', label: '最新价' },
  { value: 'market', label: '市价' },
]
const qtyBaseOptions = [
  { value: 'vol',       label: '当前持仓' },
  { value: 'avl_vol',   label: '可用持仓' },
  { value: 'last_vol',  label: '期初持仓' },
]  

// v57 commit.4: vol 计算 — 按 globalMode × globalPctInput / globalQtyInput + trade_unit 取整 + ≥ min_buy_qty
//   数据源:
//     - base (pct 模式): holdingsStore.positions[stockCode][globalQtyBase]  (实时)
//     - pct (pct 模式): globalPctInput / 100 (用户输入百分数 → 比例)
//     - qty (qty 模式): globalQtyInput (用户直接输入股数)
//     - trade_unit/min_buy_qty: stocksStore.stocks (按 stock_code 实时匹配)
//   取整规则: floor(raw / unit) * unit  (浮点→整数倍)
//   下界: max(unit_adjusted, min_buy_qty)  (允许小幅超出 raw 一档 unit)
//   change 2026-07-27-v109-mode-toggle: 重写分发
//     - mode='pct': pct 模式, 用 globalPctInput(百分数)/100 × base
//     - mode='qty': qty 模式, 直接用 globalQtyInput (股数), 与持仓无关
function computeOrderVolume(stockCode) {
  const stock = (stockCode ? stocksStore.cacheMap.get(stockCode) : {}) || {}
  const trade_unit = Number(stock.trade_unit) || 1
  const min_buy_qty = Number(stock.min_buy_qty) || 100
  if (!stockCode) return { volume: 0, raw: 0, trade_unit, min_buy_qty, base: 0, pct: 0 }
  // qty 模式: 直接用股数输入, 与持仓无关
  if (globalMode.value === 'qty') {
    const raw = Number(globalQtyInput.value) || 0
    const unit_adjusted = Math.floor(raw / trade_unit) * trade_unit
    const volume = Math.max(unit_adjusted, min_buy_qty)
    return { volume, raw, trade_unit, min_buy_qty, base: raw, pct: 1, mode: 'qty' }
  }
  // pct 模式: globalPctInput(百分数) / 100 × base
  const pos = (holdingsStore.positions || []).find(p => p.stock_code === stockCode)
  const base = Number(pos?.[globalQtyBase.value]) || 0
  const pct = (Number(globalPctInput.value) || 0) / 100
  const raw = base * pct
  const unit_adjusted = Math.floor(raw / trade_unit) * trade_unit
  const volume = Math.max(unit_adjusted, min_buy_qty)
  return { volume, raw, trade_unit, min_buy_qty, base, pct, mode: 'pct' }
}

// v57: 价格获取 — 'latest' → quoteStore.getLastPrice, 'market' → 后端实际是柜台撮合价 (前端展示为最新价作参考)
function computeOrderPrice(stockCode) {
  const p = quoteStore.getLastPrice(stockCode)
  return Number(p) || 0
}

// 主表行单击 → 选中/取消选中 task (联动下半表)
function onTaskRowClick(row) {
  // 单击 row: 若已选中则取消；否则选中
  if (selectedTaskId.value === row.id) {
    selectedTaskId.value = null
  } else {
    selectedTaskId.value = row.id
    const t = t0TasksStore.tasksById[row.id]
    if (t && t.stock_code) stockCode.value = t.stock_code
  }
}

// ---- 主表数据源 (v55 task 视角) ----
// v75 (fix): taskRows 已提前至 watch 之前定义 — TDZ 修复, 见上方 watch 上方注释.
// const taskRows = computed(() => t0TasksStore.tasks || [])   ← 已前移, 移除此重复声明

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
    case 't0_pnl': return t0PnlForRow(row)?.total_pnl || 0   // v115: 总盈亏
    case 't0_today_pnl': return t0PnlForRow(row)?.today_pnl || 0   // v115: 当日做T盈亏
    default: return 0
  }
}

// v77: 纯委托+实时盘口 PnL — 实现放在 setup 内 (上方注释见)
//   v77.5: 不再调 quoteStore.getDepth(code) (那是另封装), 直接 quoteStore.get(code) 拿整个行情结构体, 然后取结构体已有字段 bid_prices[0] / ask_prices[0]
//   quoteStore.byCode 是 shallowRef(Map), update() 内 byCode.value.set(...) + triggerRef(byCode) 让 cell 自动重渲
// change 2026-07-27-v109-pnl-formula: PnL 公式重构 (用户口径: diff 语义变化)
//   - 老语义: diff = target - cur, diff>0 多买, diff<0 多卖 (公式按 ask1/bid1)
//   - 新语义 (2026-07-27): diff = cur - target, diff<0 需买, diff>0 需卖
//   - 价格不再区分 ask1/bid1, 统一用最新价 (last_price), PnL = realized + diff × last_price
//   - 配平盘口金额 rate 分母: 统一 diff × last_price (按"按最近价平掉"的市值估算)
// change 2026-07-28-v115-t0-pnl-split: PnL 分两字段
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

// v115: 计算"当日做T盈亏"
//   仅过滤 trd_date === activeDay 的订单 (只看今天)
//   公式: today_realized - (今日净持仓 × last_price)
//   含义: 今日做T操作的纯盈亏 (剔除持仓市值波动)
function _calcTodayT0Pnl(code, taskId, base, tgv, orders, activeDay) {
  let buyAmt = 0, buyVol = 0, sellAmt = 0, sellVol = 0
  for (const o of orders) {
    if (activeDay && String(o.trd_date) !== String(activeDay)) continue   // 仅当日
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
  const today_realized = sellAmt - buyAmt
  const today_net_pos = buyVol - sellVol    // 今日净持仓 (正=还持有多)
  const q = quoteStore.get(code) || {}
  const last = Number(q.last_price) || 0
  // 扣减净持仓市值 (持仓兑现 = 不是做T赚的)
  return today_realized - (today_net_pos * last)
}

// change 2026-07-27-v109-pnl-reactive: PnL / 收益率反应式 — 行情推过来时由依赖触发 recompute
//   - t0PnlMap: 字典 { "taskId|stock_code": { pnl, rate, diff, ... } }
//   - template 从 t0PnlMap.value[rowKey(row)] 读, 函数 t0PnlForRow 改成 thin wrapper (回退兼容)
// change 2026-07-27-v109.5: t0PnlMap computed 显式订阅 quoteStore.tick.value
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
  const activeDay = holdingsStore.activeTrdDate || ''  // v115: 当日做T盈亏过滤用
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
    )
    const { total_pnl, diff, last } = _calcT0Pnl(code, taskId, base, tgv, rs)
    // v115: 当日做T盈亏 (trd_date === activeDay)
    const today_pnl = _calcTodayT0Pnl(code, taskId, base, tgv, rs, activeDay)
    // v115.1: rate 字段删除 (用户: 去掉做T收益率)
    out[`${taskId}|${code}`] = { total_pnl, today_pnl, diff, last }
  }
  return out
})
function _rowKey(row) { return row ? `${row.id}|${row.stock_code}` : '' }
// change 2026-07-27-v109.5: t0PnlCell 显式订阅 quoteStore.tick, 确保 el-table 重渲
//   - tick 是 ref, 读 .value 才是当前值 (Vue 收集依赖是基于 .value 访问)
//   - 因为函数在 render 函数上下文执行, .value 访问会被 render 收集依赖
//   - 兜底如果 t0PnlMap.value 不在依赖图 (e.g. el-table 模板缓存), tick 自增能强制刷
function t0PnlCell(row) {
  void quoteStore.tick.value    // ← 显式订阅, 触发 render 重跑
  return t0PnlMap.value[_rowKey(row)] || null
}
function t0PnlForRow(row) {
  // change 2026-07-27-v109-pnl-reactive: 改从 t0PnlMap 读 (响应式), 不再实时算
  const m = t0PnlMap.value
  const it = m[_rowKey(row)]
  return it ? it.pnl : 0
}
function t0ReturnRateForRow(row) {
  // v115.1: 已删除 — 用户口径"去掉做T收益率"
  //   保留空 stub 防止外部 import 引用, 函数返回 0
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

// ---- 做T盈亏 / 收益率 (v77: 纯委托 + 实时盘口口径, 不依赖 cost_basis) ----
//
// 修 bug: 用户 2026-07-21 二次反馈 "实时价 vs 成交价差异时, 页面没正常计算 PnL".
//   v76 用 realized + (livePrice - cost_basis) × taskNetVol 的公式, 但 cost_basis
//   是后端基于成交均价推的静态值, 跟"实时配平"语义不一致 — 用户要的是"实时盘口"口径.
// v77 改为纯委托+盘口 (user 业务定义):
//   1) 已实现: Σ(卖成交量 × 卖成交均价) − Σ(买成交量 × 买成交均价)
//   2) 配平盘口 (按当前已成交净持仓 vs 目标 base+target):
//        cur    = Σ(买成交) − Σ(卖成交)         // 当前净持仓
//        target = base_volume + target_volume   // 配平目标
//        diff   = target − cur
//        diff>0: 配平部分按"补买" 算: Pnl += −(diff) × 卖1价(ask1)  (花卖1价买)
//        diff<0: 配平部分按"补卖" 算: Pnl += (|diff|) × 买1价(bid1)  (收买1价卖)
//        diff=0: 不加盘口项
//   3) 收益率 = Pnl / (Σ成交量 × 均价 + |diff|×盘口价)  (综合成本分母)
// 数据源: holdingsStore.orders (同 stock_code 即为该 task 下所有委托), quoteStore.get(code).bid_prices[0]/.ask_prices[0] (行情表结构体已有字段).
// 实现位置: 在 setup 块内 (见 _taskSortValue 下方) — 因 holdingsStore/quoteStore 是 setup 内 const,
//   setup 外定义会 ReferenceError. (v77 v2)
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
// v55.1 配平按钮: 前端算差值 + 调用 useT0OrderSubmit 下市价单
async function onBalanceTask(taskId) {
  const diff = _taskNetDiff(taskId)
  if (diff === 0) {
    ElMessage.info(`task #${taskId} 已平衡，无需操作`)
    return
  }
  // change 2026-07-21-t0-balance-stock-code-guard: 防 balanceStockCode 空导致后端校验失败
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
      `task #${taskId} 实时差 ${diff} 股，将下市价单 ${orderType === '23' ? '买' : '卖'} ${volume} 股`,
      '一键配平', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch (e) { return }
  try {
    // change 2026-07-21-t0-balance-stock-code-guard: 用 stockCodeOverride 让 useT0OrderSubmit
    //   优先用兜底 stock_code (而不是闭包 stockCode.value, 后者可能为空)
    await submitBalanceOrder({ orderType, volume, price: 0, taskId, stockCodeOverride: stockCodeForBalance })
    // useT0OrderSubmit 内部已 ElMessage.success
    await t0TasksStore.loadTasks()  // 刷新主表（task summary 更新）
  } catch (e) { /* ElMessage 已被 axios 拦截器弹出 */ }
}

// v57: 主表 row 操作按钮可用性 — archived task 任何按钮都不能用
function canOpRow(row) {
  return row.status !== 'archived' && !!row.stock_code
}

// v57: 买/卖按钮 (走全局配置: pct × qtyBase → vol, latest/market → price)
function _prepareOrderPayload(row, direction) {
  const stockCode = row.stock_code
  const volInfo = computeOrderVolume(stockCode)   // v57 commit.4: {volume, raw, trade_unit, min_buy_qty, base, pct}
  if (!volInfo || !volInfo.volume || volInfo.volume <= 0) {
    ElMessage.warning(`${row.stock_code} 按当前配置算不出可下单数量（可能持仓为空或 0%）`)
    return null
  }
  const price = computeOrderPrice(stockCode)
  if (globalPriceType.value === 'latest' && (!price || price <= 0)) {
    ElMessage.warning(`未取得 ${row.stock_code} 最新价，请等待行情推送`)
    return null
  }
  const orderType = direction === '买' ? '23' : '24'
  return {
    direction, stockCode, price, volume: volInfo.volume,
    orderType,                                       // v58 commit.5 fix: 后端 Pydantic 必填, 之前漏掉 → 422
    taskId: row.id,
    mode: globalMode.value,                          // change 2026-07-27-v109-mode-toggle: 'pct' | 'qty'
    qtyBase: globalQtyBase.value,                    // 仅 pct 模式有意义
    pct: globalPctInput.value,                       // change 2026-07-27-v109-mode-toggle: 直接是百分数 (用户视角 25 = 25%)
    qty: globalQtyInput.value,                       // change 2026-07-27-v109-mode-toggle: 仅 qty 模式有意义
    priceType: globalPriceType.value,
    // v57 commit.4: 取整提示信息 (供 dialog 显示)
    base: volInfo.base,
    raw: volInfo.raw,
    tradeUnit: volInfo.trade_unit,
    minBuyQty: volInfo.min_buy_qty,
  }
}
async function onBuyTask(row) {
  if (!canOpRow(row)) return
  const payload = _prepareOrderPayload(row, '买')
  if (!payload) return
  // v93: 二次确认由 order.js 统一拦截, 这里直接下单
  await _submitOrder(payload)
}
async function onSellTask(row) {
  if (!canOpRow(row)) return
  const payload = _prepareOrderPayload(row, '卖')
  if (!payload) return
  // v93: 二次确认由 order.js 统一拦截, 这里直接下单
  await _submitOrder(payload)
}

// 二次确认 dialog 用户点"确认下单" 才真正下单
async function _submitOrder(p) {
  try {
    // v83: 11=限价 5=最新价 44=市价 (与 xtconstant 一致)
    const priceTypeCode = p.priceType === 'market' ? 44
      : p.priceType === 'oppose' ? 44
      : p.priceType === 'latest' ? 5
      : 11  // 'limit'
    const res = await orderStore.placeOrder({
      stock_code: p.stockCode,
      order_type: p.orderType,
      price_type: priceTypeCode,
      price: p.priceType === 'market' ? 0 : p.price,  // 市价 price 传 0
      volume: p.volume,
      user_def: 'T0',
      strategy_type: 1,  // v66: REQ-TRADE-026; T0Trade.vue 下单 = 快速做T
      ...(p.taskId ? { task_id: p.taskId } : {}),
    })
    ElMessage.success(`${p.direction}单已报：${p.stockCode} ${p.volume} 股 @ ${p.priceType === 'market' ? '市价' : '¥' + formatPrice(p.price, p.stockCode)}`)
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
  ElMessage.info(`已选中 ${stock_code} ${stock_name || ''}，请在右侧填写任务参数`)
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
}
/* v93: .t0-header / .t0-title / .qs-row 已删除 — 工具栏合并到 .t0-config-bar */
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

/* v55 添加任务 dialog 2 列布局 */
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

/* v57 commit.2: 二次确认 dialog 内部样式 */
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

/* v55.1 上下分区布局: 上半主表 + 下半委托表, 1:1 flex column */
.t0-split {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
/* v57 commit.2: 做T全局配置 row — 4 select + 1 checkbox */
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
/* v93: 选 task 选择器靠右固定宽度 — 推到右的力交给 .t0-spacer (flex:1) 吃 */
.t0-config-bar .qs-task-select {
  width: 200px;
}
/* v93: 弹性占位 — 把 (刷新/添加任务/选 task) 整体推到最右 */
.t0-config-bar .t0-spacer {
  flex: 1;
}
.t0-config-bar .t0-config-hint {
  color: var(--el-text-color-secondary, #909399);
  font-size: 11px;
  margin-left: 8px;
}
/* change 2026-07-27-v109-mode-toggle: 单位提示 (%/股) 紧贴 el-input-number 右侧 */
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
  overflow-x: auto; /* v57 commit.1: 主表 9 列宽 1150px > 容器 1010px, 允许横滚 (操作列 fixed 浮动) */
}

/* v92: 选中行美化 - 品牌色低透明度背景 + 4px 左侧强调边, 亮/暗自适应
   旧: --el-color-primary-light-9 (#eef2ff) 在暗色模式下是浅蓝突兀
   新: rgba(brand-primary, 0.10/0.18) 跟随品牌色, 暗色加深一档 */
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
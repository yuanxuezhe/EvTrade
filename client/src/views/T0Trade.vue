<template>
  <div class="t0-trade fade-in-up">
    <!-- 快速做T 设置条 (M-008): 全局默认仓位 % + 价格档 (行内可覆盖) -->
    <el-card class="quick-settings-bar" shadow="never">
      <div class="qs-row">
        <span class="qs-label">⚡ 默认仓位</span>
        <el-radio-group v-model="quickPct" size="default">
          <el-radio-button
            v-for="p in PCT_OPTIONS"
            :key="p"
            :value="p"
            :label="String(p) + '%'"
          />
        </el-radio-group>
        <span class="qs-divider">|</span>
        <span class="qs-label">💰 默认价格</span>
        <el-radio-group v-model="quickPriceType" size="default">
          <el-radio-button
            v-for="opt in PRICE_TYPE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            :label="opt.label"
          />
        </el-radio-group>
        <span class="qs-tip">点击行或 [详情] 打开右侧抽屉做T 操作</span>
      </div>
    </el-card>

    <!-- 快速做T 主表 (M-008 v2 表格驱动布局) -->
    <el-card class="position-table-card" shadow="never">
      <template #header>
        <div class="pt-header">
          <span class="card-title">📋 持仓快速做T</span>
          <span class="pt-tip">点击行或 [→] 打开右侧抽屉进行做T 操作</span>
        </div>
      </template>
      <el-table
        :data="holdingsPositions"
        :row-class-name="ptRowClass"
        @row-click="onOpenDrawer"
        class="position-table"
        empty-text="暂无持仓"
      >
        <el-table-column prop="stock_code" label="代码" width="120" />
        <el-table-column label="名称" width="100">
          <template #default="{ row }">{{ row.stock_name || row.stock_code }}</template>
        </el-table-column>
        <el-table-column label="持仓" align="right" width="100">
          <template #default="{ row }">{{ formatNumber(row.vol) }}</template>
        </el-table-column>
        <el-table-column label="现价" align="right" width="100">
          <template #default="{ row }">
            <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
              {{ formatPrice(quoteStore.getLastPrice(row.stock_code)) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="涨跌幅" align="right" width="100">
          <template #default="{ row }">
            <span :class="quoteStore.getChangePct(row.stock_code) >= 0 ? 'up' : 'down'">
              {{ quoteStore.getChangePct(row.stock_code)?.toFixed(2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="170" fixed="right">
          <template #default="{ row }">
            <div class="op-col">
              <!-- 第一行: 买 / 卖 / 配平 (M-008 v3) -->
              <div class="op-row op-row-actions">
                <el-tooltip :content="isBuyDisabled(row) ? `${row.stock_code} 持仓为 0, 无法按比例买` : `按 ${quickPct}% 仓位买入`" placement="top">
                  <el-button type="primary" size="small" :disabled="isBuyDisabled(row) || submitting" @click.stop="onQuickBuy(row)" class="op-btn-buy">
                    买{{ quickPct }}%
                  </el-button>
                </el-tooltip>
                <el-tooltip content="按全局 % 仓位卖出 (0 持仓自动跳过)" placement="top">
                  <el-button type="danger" size="small" :disabled="submitting" @click.stop="onQuickSell(row)" class="op-btn-sell">
                    卖{{ quickPct }}%
                  </el-button>
                </el-tooltip>
                <el-tooltip content="配平: 抵消今日净买卖, 回到当前持仓" placement="top">
                  <el-button type="warning" size="small" :disabled="submitting" @click.stop="onQuickBalance(row)" class="op-btn-balance">
                    配平
                  </el-button>
                </el-tooltip>
              </div>
              <!-- 第二行: 详情 (整行可点也开抽屉, 此按钮是移动端友好入口) -->
              <div class="op-row op-row-detail">
                <el-button type="primary" link size="small" @click.stop="onOpenDrawer(row)" class="op-btn-detail">
                  详情
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M5 12h14M13 5l7 7-7 7"/>
                  </svg>
                </el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- M-008 v3: 右侧明细抽屉 (点击行/详情打开) -->
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
            <span class="value text-mono">¥{{ formatAmount(costTotal) }}</span>
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

    <!-- T0 敞口聚合 + 累计收益 -->
    <div class="content-card-row">
      <el-card class="exposure-card" shadow="hover">
        <template #header>
          <div class="card-header-flex">
            <span class="card-title">📋 T0 敞口聚合（当日）</span>
            <el-button size="small" type="warning" plain :disabled="!exposureTotals || exposureTotals.net_volume === 0"
              @click="onRebalanceAll">⚖ 一键配平（当前标的）</el-button>
          </div>
        </template>
        <div v-if="exposureLoading" class="empty-tip">加载中…</div>
        <div v-else-if="!exposureList.length" class="empty-tip">当日暂无 T0 成交</div>
        <el-table v-else :data="exposureList" stripe size="small" class="exposure-table">
          <el-table-column prop="stock_code" label="标的" width="120" />
          <el-table-column prop="buy_volume" label="买量" width="80" align="right" />
          <el-table-column prop="sell_volume" label="卖量" width="80" align="right" />
          <el-table-column label="净量" width="90" align="right">
            <template #default="{ row }">
              <span :class="row.net_volume > 0 ? 'pos' : row.net_volume < 0 ? 'neg' : ''">
                {{ row.net_volume > 0 ? '+' : '' }}{{ row.net_volume }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="净额" width="110" align="right">
            <template #default="{ row }">
              <span :class="row.net_amount > 0 ? 'neg' : row.net_amount < 0 ? 'pos' : ''">
                {{ row.net_amount > 0 ? '-' : row.net_amount < 0 ? '+' : '' }}{{ formatPrice(Math.abs(row.net_amount)) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="已实现" width="100" align="right">
            <template #default="{ row }">
              <span :class="row.realized_pnl >= 0 ? 'pos' : 'neg'">
                {{ row.realized_pnl >= 0 ? '+' : '' }}{{ formatPrice(row.realized_pnl) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button v-if="Math.abs(row.net_volume) >= 100" size="small" type="primary"
                @click="onRebalanceRow(row)">
                {{ row.net_volume > 0 ? '卖' + Math.abs(row.net_volume) : '买' + Math.abs(row.net_volume) }}
              </el-button>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="exposureTotals" class="exposure-totals">
          <span>合计：买 {{ exposureTotals.buy_volume }} / 卖 {{ exposureTotals.sell_volume }} /
            净 <b :class="exposureTotals.net_volume > 0 ? 'pos' : exposureTotals.net_volume < 0 ? 'neg' : ''">
              {{ exposureTotals.net_volume }}
            </b> / 已实现
            <b :class="exposureTotals.realized_pnl >= 0 ? 'pos' : 'neg'">
              {{ formatPrice(exposureTotals.realized_pnl) }}
            </b>
          </span>
        </div>
      </el-card>

      <el-card class="aggregate-card" shadow="hover">
        <template #header>
          <div class="card-header-flex">
            <span class="card-title">📈 T0 累计收益</span>
            <el-radio-group v-model="aggregateDays" size="small" @change="switchAggregateDays">
              <el-radio-button :value="7">7 天</el-radio-button>
              <el-radio-button :value="30">30 天</el-radio-button>
              <el-radio-button :value="90">90 天</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <div v-if="aggregateLoading" class="empty-tip">加载中…</div>
        <div v-else-if="!aggregate" class="empty-tip">暂无累计数据</div>
        <div v-else class="aggregate-body">
          <div class="metric-row">
            <div class="metric">
              <div class="metric-label">累计已实现</div>
              <div class="metric-value" :class="aggregate.summary.total_realized >= 0 ? 'pos' : 'neg'">
                {{ aggregate.summary.total_realized >= 0 ? '+' : '' }}{{ formatPrice(aggregate.summary.total_realized) }}
              </div>
            </div>
            <div class="metric">
              <div class="metric-label">回报率</div>
              <div class="metric-value" :class="aggregate.summary.return_rate >= 0 ? 'pos' : 'neg'">
                {{ (aggregate.summary.return_rate * 100).toFixed(2) }}%
              </div>
            </div>
            <div class="metric">
              <div class="metric-label">胜率</div>
              <div class="metric-value">
                {{ aggregate.summary.win_days }} / {{ aggregate.summary.total_days }}
                ({{ (aggregate.summary.win_rate * 100).toFixed(0) }}%)
              </div>
            </div>
            <div class="metric">
              <div class="metric-label">笔数 / 标的</div>
              <div class="metric-value">
                {{ aggregate.summary.trade_count }} / {{ aggregate.summary.stocks_traded }}
              </div>
            </div>
          </div>
          <div class="metric-row sub">
            <span>佣金 {{ formatPrice(aggregate.summary.total_commission) }}</span>
            <span>印花税 {{ formatPrice(aggregate.summary.total_stamp_tax) }}</span>
            <span>买入 {{ formatPrice(aggregate.summary.total_buy_amount) }}</span>
            <span>卖出 {{ formatPrice(aggregate.summary.total_sell_amount) }}</span>
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
              <div class="btn-sub">{{ formatNumber(effectiveBuyQty) }} 股 (B)</div>
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
              <div class="btn-sub">{{ formatNumber(effectiveSellQty) }} 股 (S)</div>
            </el-button>
          </div>

          <el-divider />

          <!-- 本次交易表单（一键买/卖/配平/手动单 都共用这组价/量） -->
          <el-form :inline="true" class="order-form manual-trade-form">
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
                placeholder="留空=自动"
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
              <div class="btn-sub">
                {{ manualVolume > 0
                  ? `${formatNumber(manualVolume)} 股 × ¥${formatPrice(orderPrice)}`
                  : `填入数量后下单` }}
              </div>
            </el-button>
          </div>

          <div class="hint" v-if="Number(manualVolume) > 0">
            📌 当前「数量」已填值，一键买/卖/配平按钮将使用此数量（替代自动值）
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
                {{ formatNumber(effectiveBalanceQty) }} 股 × ¥{{ formatPrice(orderPrice) }} (F)
              </div>
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 仓位管理建议卡 -->
    <el-card class="risk-card" shadow="hover">
      <template #header>
        <div class="card-header-flex">
          <span class="card-title">🎯 仓位管理建议</span>
          <span class="risk-tag" :class="riskLevel.level">{{ riskLevel.label }}</span>
        </div>
      </template>
      <div class="risk-body">
        <el-radio-group v-model="riskProfile" size="large" class="risk-profile">
          <el-radio-button value="conservative">保守</el-radio-button>
          <el-radio-button value="balanced">平衡</el-radio-button>
          <el-radio-button value="aggressive">激进</el-radio-button>
          <el-radio-button value="extreme">极限</el-radio-button>
        </el-radio-group>

        <el-row :gutter="12" class="risk-grid">
          <el-col :span="6">
            <div class="risk-item">
              <div class="risk-label">单股仓位上限</div>
              <div class="risk-value">{{ (riskConfig.maxSinglePosition * 100).toFixed(0) }}%</div>
              <div class="risk-hint">¥{{ formatAmount(maxSingleAmount) }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="risk-item">
              <div class="risk-label">预留安全余额</div>
              <div class="risk-value">{{ (riskConfig.reserveCash * 100).toFixed(0) }}%</div>
              <div class="risk-hint">¥{{ formatAmount(reserveAmount) }}</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="risk-item">
              <div class="risk-label">单笔最大买入</div>
              <div class="risk-value">{{ formatNumber(maxBuyQty) }}</div>
              <div class="risk-hint">股</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="risk-item">
              <div class="risk-label">建议配平系数</div>
              <div class="risk-value">{{ suggestedCoeff.toFixed(2) }}</div>
              <div class="risk-hint">
                <el-link type="primary" underline="never" @click="balanceCoeff = suggestedCoeff">应用</el-link>
              </div>
            </div>
          </el-col>
        </el-row>

        <!-- 一键开仓 / 一键平仓 / 一键配平 已在抽屉 (M-008 v2), 此处仅保留参考 -->
        <el-alert
          v-if="riskWarnings.length > 0"
          :title="riskWarnings.length + ' 项风险提示'"
          type="warning"
          :closable="false"
          class="risk-warnings"
        >
          <ul class="warning-list">
            <li v-for="(w, i) in riskWarnings" :key="i">{{ w }}</li>
          </ul>
        </el-alert>
      </div>
    </el-card>

    <!-- T0 历史收益曲线 -->
    <el-card class="history-card" shadow="hover">
      <template #header>
        <div class="card-header-flex">
          <span class="card-title">📈 T0 历史收益曲线</span>
          <div class="history-meta" v-if="historyData">
            <span class="meta-item">
              累计: <b :class="historyData.total_realized >= 0 ? 'up' : 'down'">
                ¥{{ formatAmount(historyData.total_realized) }}
              </b>
            </span>
            <span class="meta-item">
              收益: <b :class="historyData.total_realized >= 0 ? 'up' : 'down'">
                {{ (historyData.total_return_rate * 100).toFixed(2) }}%
              </b>
            </span>
            <span class="meta-item">
              胜: <b>{{ historyData.win_days }}/{{ historyData.total_days }}</b> 天
            </span>
            <el-radio-group v-model="historyDays" size="small" class="days-pick">
              <el-radio-button :value="7">7D</el-radio-button>
              <el-radio-button :value="30">30D</el-radio-button>
              <el-radio-button :value="90">90D</el-radio-button>
            </el-radio-group>
          </div>
        </div>
      </template>
      <div class="chart-wrap" v-if="cumHistory.length > 0">
        <svg :viewBox="`0 0 ${chartW} ${chartH}`" class="chart-svg" preserveAspectRatio="none">
          <!-- 0 轴 -->
          <line
            :x1="0" :y1="zeroY"
            :x2="chartW" :y2="zeroY"
            stroke="#dcdfe6" stroke-width="1" stroke-dasharray="3,3"
          />
          <!-- 累计曲线 -->
          <path
            :d="cumPath"
            :stroke="cumHistory[cumHistory.length - 1].cum_pnl >= 0 ? '#f56c6c' : '#67c23a'"
            stroke-width="2" fill="none"
          />
          <!-- 填充 -->
          <path
            :d="cumAreaPath"
            :fill="cumHistory[cumHistory.length - 1].cum_pnl >= 0 ? 'rgba(245,108,108,0.12)' : 'rgba(103,194,58,0.12)'"
            stroke="none"
          />
          <!-- 每日 bar（实心 = 赚，空心 = 亏） -->
          <g v-for="(p, i) in cumHistory" :key="p.trd_date">
            <line
              :x1="barX(i)" :x2="barX(i)"
              :y1="barY(p.realized_pnl, i)"
              :y2="zeroY"
              :stroke="p.realized_pnl >= 0 ? '#f56c6c' : '#67c23a'"
              stroke-width="3"
              stroke-linecap="round"
            />
            <title>{{ p.trd_date }}: {{ p.realized_pnl >= 0 ? '+' : '' }}¥{{ p.realized_pnl }} ({{ p.trade_count }} 笔)</title>
          </g>
        </svg>
        <div class="x-labels">
          <span v-for="(p, i) in xLabelIndices" :key="i" :style="{ left: (p / (cumHistory.length - 1 || 1) * 100) + '%' }">
            {{ p.slice(4) }}
          </span>
        </div>
      </div>
      <el-empty v-else description="尚无做T 历史" :image-size="60" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Top, Bottom, List, Check, ArrowRight, Close } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useHoldingsStore } from '../stores/holdings'
import { useAssetStore } from '../stores/asset'
import { useQuoteStore } from '../stores/quote'
import { useOrderStore } from '../stores/order'
import { useT0Balance } from '../composables/useT0Balance'
import {
  PCT_OPTIONS, PRICE_TYPE_OPTIONS,
  loadQuickDefaults, saveQuickDefaults,
  isBuyDisabled, buildQuickOrder, calcBalanceQty,
} from '../composables/useQuickT0'
import { api } from '../api'
import { t0StatsApi } from '../api/t0_stats'
import { formatNumber, formatPrice, formatAmount } from '../utils/format'
import { RISK_CONFIGS, DEFAULT_RISK_PROFILE, getRiskConfig, riskProfileOptions } from '../constants/riskProfile'

const holdingsStore = useHoldingsStore()
const orderStore = useOrderStore()  // v8: 下单后立即 upsert 缓存
const assetStore = useAssetStore()
const quoteStore = useQuoteStore()
const { positions } = storeToRefs(holdingsStore)
const { asset } = storeToRefs(assetStore)

const stockCode = ref('600519.SH')
const showPicker = ref(false)
const submitting = ref(false)

// M-008 v2: 抽屉控制
const drawerVisible = ref(false)
// M-008 v3: 抽屉详情独立 state (避免与主页 t0Stats/historyData 互相覆盖)
const drawerLoading = ref(false)
const drawerStats = ref({ order_count: 0, trade_count: 0, realized_pnl: 0, unrealized_pnl: 0, total_pnl: 0, today_buy_volume: 0, today_sell_volume: 0, today_buy_amount: 0, today_sell_amount: 0 })
const drawerHistory = ref(null)
const drawerDays = ref(30)
function onOpenDrawer(row) {
  if (!row || !row.stock_code) return
  const code = row.stock_code
  stockCode.value = code  // 同步主页 (影响 ptRowClass 高亮 + 主页 load)
  drawerVisible.value = true
  drawerLoading.value = true
  // 并行加载抽屉详情 (与主页 loadT0Stats/History 完全独立, 避免互相覆盖)
  Promise.all([
    t0StatsApi.get(code).catch((e) => { console.warn('drawer t0 stats failed', e); return null }),
    t0StatsApi.getHistory(code, drawerDays.value).catch((e) => { console.warn('drawer t0 history failed', e); return null }),
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

// 抽屉宽度: 视口宽 < 1100 时压缩到 420, 否则 540
const drawerSize = computed(() => (typeof window !== 'undefined' && window.innerWidth < 1100 ? '420px' : '540px'))
// 抽屉历史累计曲线
const drawerCumHistory = computed(() => {
  const pts = drawerHistory.value?.points || []
  let cum = 0
  return pts.map(p => ({ ...p, cum_pnl: (cum += p.realized_pnl) }))
})
const drawerChartW = 460
const drawerChartH = 140
const drawerChartPad = 16
const drawerZeroY = computed(() => {
  const pts = drawerCumHistory.value
  if (!pts.length) return drawerChartH / 2
  const max = Math.max(...pts.map(p => p.cum_pnl), 0)
  const min = Math.min(...pts.map(p => p.cum_pnl), 0)
  if (max === min) return drawerChartH / 2
  // 0 线在 max/min 区间的相对位置
  return drawerChartH - drawerChartPad - ((-min) / (max - min)) * (drawerChartH - 2 * drawerChartPad)
})
const drawerCumPath = computed(() => {
  const pts = drawerCumHistory.value
  if (!pts.length) return ''
  const w = drawerChartW - 2 * drawerChartPad
  const h = drawerChartH - 2 * drawerChartPad
  const max = Math.max(...pts.map(p => p.cum_pnl), 0)
  const min = Math.min(...pts.map(p => p.cum_pnl), 0)
  const range = max - min || 1
  return pts.map((p, i) => {
    const x = drawerChartPad + (i / (pts.length - 1 || 1)) * w
    const y = drawerChartPad + (1 - (p.cum_pnl - min) / range) * h
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
})
const drawerCumAreaPath = computed(() => {
  const line = drawerCumPath.value
  if (!line) return ''
  // 0 线 y 位置
  const pts = drawerCumHistory.value
  const max = Math.max(...pts.map(p => p.cum_pnl), 0)
  const min = Math.min(...pts.map(p => p.cum_pnl), 0)
  const range = max - min || 1
  const h = drawerChartH - 2 * drawerChartPad
  const yZero = drawerChartPad + (1 - (0 - min) / range) * h
  const last = pts.length - 1
  const w = drawerChartW - 2 * drawerChartPad
  const xLast = drawerChartPad + (last / (last || 1)) * w
  return `${line} L ${xLast.toFixed(1)} ${yZero.toFixed(1)} L ${drawerChartPad} ${yZero.toFixed(1)} Z`
})
// 抽屉累计统计 (跨期 aggregate API, 后端已存在 /api/orders/t0-aggregate?stock_code=...)
const drawerAggregate = ref(null)
watch(drawerVisible, async (v) => {
  if (v && stockCode.value) {
    try {
      // 注意: t0StatsApi.getAggregate 直接返回 data (非 axios wrapper)
      const agg = await t0StatsApi.getAggregate({ userDef: 'T0', days: 90 })
      // 过滤当前标的
      drawerAggregate.value = (agg?.by_stock || []).find(s => s.stock_code === stockCode.value) || agg
    } catch (e) {
      console.warn('drawer aggregate failed', e)
    }
  }
})
function ptRowClass({ row }) {
  // 当前抽屉选中的行高亮
  return row.stock_code === stockCode.value ? 'is-selected' : ''
}

// 快速做T 全局设置 (顶部设置条, 持久化到 localStorage)
const _quickDefaults = loadQuickDefaults()
const quickPct = ref(_quickDefaults.pct)
const quickPriceType = ref(_quickDefaults.priceType)
watch([quickPct, quickPriceType], ([p, pt]) => {
  saveQuickDefaults(p, pt)
})

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
  exposureList, exposureTotals, exposureLoading, loadExposure, needRebalance,
  aggregate, aggregateLoading, loadAggregate,
} = t0

// 手动下单（0 = 留空，自动用一键算法的量）
const manualDirection = ref('23')   // 23=买 24=卖
const manualVolume = ref(0)
const priceTypeLabel = computed(() => {
  return { latest: '最新', oppose: '对手', limit: '限价', market: '市价' }[priceType.value] || ''
})

// 持仓列表
const holdingsPositions = computed(() => positions.value)

// ---- 本次交易表单的"有效值"：用户填了用填的，否则走自动 ----
const effectiveBuyQty = computed(() => {
  const v = Number(manualVolume.value)
  return v > 0 ? Math.floor(v / 100) * 100 : oneClickBuyQty.value
})
const effectiveSellQty = computed(() => {
  const v = Number(manualVolume.value)
  return v > 0 ? Math.floor(v / 100) * 100 : oneClickSellQty.value
})
const effectiveBalanceQty = computed(() => {
  const v = Number(manualVolume.value)
  return v > 0 ? Math.floor(v / 100) * 100 : balanceQty.value
})

// ---- 仓位管理（4 档 + 风险建议） -----------------------------------------
// RISK_CONFIGS / DEFAULT_RISK_PROFILE 见 constants/riskProfile.js（4 档: conservative/balanced/aggressive/extreme）
const riskProfile = ref(DEFAULT_RISK_PROFILE)
const riskConfig = computed(() => getRiskConfig(riskProfile.value))

// 总资产
const totalAsset = computed(() => Number(asset.value?.total_asset) || 0)
// 可用资金
const availableCash = computed(() => Number(asset.value?.cash) || 0)
// 单股最大可买金额
const maxSingleAmount = computed(() => totalAsset.value * riskConfig.value.maxSinglePosition)
// 安全余额（保留）
const reserveAmount = computed(() => totalAsset.value * riskConfig.value.reserveCash)
// 可用于此股的最大买入金额（= 单股上限 - 当前持仓市值，扣除已用）
const investableAmount = computed(() => {
  const used = marketValue.value
  return Math.max(0, maxSingleAmount.value - used)
})
// 单笔最大买入股数
const maxBuyQty = computed(() => {
  if (!hasQuote.value || lastPrice.value <= 0) return 0
  // 限制 1：可投资金额 / 价格
  const maxByRisk = investableAmount.value / lastPrice.value
  // 限制 2：可用资金 - 保留余额
  const maxByCash = Math.max(0, availableCash.value - reserveAmount.value)
  return Math.floor(Math.min(maxByRisk, maxByCash) / 100) * 100
})
// 建议配平系数（基于浮盈浮亏反向）
const suggestedCoeff = computed(() => {
  // 浮亏时建议加仓（系数 1.5），浮盈时建议减仓（系数 0.5）
  if (profitRate.value < -0.05) return 1.5
  if (profitRate.value < 0) return 1.0
  if (profitRate.value > 0.10) return 0.5
  return RISK_CONFIGS[riskProfile.value].suggestedCoeff
})
// 风险等级
const riskLevel = computed(() => {
  const ratio = totalAsset.value > 0 ? marketValue.value / totalAsset.value : 0
  if (ratio > 0.5) return { level: 'high', label: '⚠ 高风险' }
  if (ratio > 0.25) return { level: 'medium', label: '⚡ 中等' }
  if (ratio > 0.1) return { level: 'low', label: '✅ 合理' }
  return { level: 'safe', label: '🟢 安全' }
})
// 风险提示列表
const riskWarnings = computed(() => {
  const warns = []
  const ratio = totalAsset.value > 0 ? marketValue.value / totalAsset.value : 0
  if (ratio > riskConfig.value.maxSinglePosition) {
    warns.push(`当前 ${stockCode.value} 仓位 ${(ratio * 100).toFixed(1)}%，超过 ${riskProfile.value} 上限 ${(riskConfig.value.maxSinglePosition * 100).toFixed(0)}%`)
  }
  if (availableCash.value < reserveAmount.value) {
    warns.push(`可用资金 ¥${formatAmount(availableCash.value)} 低于安全余额 ¥${formatAmount(reserveAmount.value)}`)
  }
  if (insufficientCash.value) {
    warns.push(`本次买入 ¥${formatAmount(balanceAmount.value)} 超过可用资金 ¥${formatAmount(availableCash.value)}`)
  }
  if (insufficientPosition.value) {
    warns.push(`本次卖出 ${formatNumber(Math.abs(balanceQty.value))} 股超过可用持仓 ${formatNumber(currentVolume.value)}`)
  }
  if (profit.value < 0 && direction.value === 'buy') {
    warns.push('当前浮亏时加仓，请确认止损位')
  }
  return warns
})

// 颜色 class
const priceClass = computed(() => {
  if (changePct.value == null) return ''
  return changePct.value >= 0 ? 'up' : 'down'
})
// 涨跌闪烁 class
const flashClass = ref('')
let _lastPrice = null
watch(lastPrice, (newP, oldP) => {
  if (newP == null || oldP == null) {
    _lastPrice = newP
    return
  }
  if (newP > oldP) flashClass.value = 'flash-up'
  else if (newP < oldP) flashClass.value = 'flash-down'
  else flashClass.value = ''
  _lastPrice = newP
  setTimeout(() => { flashClass.value = '' }, 700)
})
const profitClass = computed(() => profit.value >= 0 ? 'up' : 'down')
const t0Class = computed(() => t0Stats.value.total_pnl >= 0 ? 'up' : 'down')

// T0 统计
const t0Stats = ref({
  trd_date: '', stock_code: '',
  today_buy_volume: 0, today_sell_volume: 0,
  today_buy_amount: 0, today_sell_amount: 0,
  realized_pnl: 0, cost_basis: 0, position_volume: 0,
  position_cost_total: 0, unrealized_pnl: 0, total_pnl: 0,
  order_count: 0, trade_count: 0, open_order_count: 0
})

async function loadT0Stats(code) {
  const c = code || stockCode.value
  if (!c) return
  try {
    t0Stats.value = await t0StatsApi.get(c)
  } catch (e) {
    console.warn('load t0 stats failed', e)
  }
}

const historyDays = ref(30)
const historyData = ref(null)
async function loadT0History(code) {
  const c = code || stockCode.value
  if (!c) return
  try {
    historyData.value = await t0StatsApi.getHistory(c, historyDays.value)
  } catch (e) {
    console.warn('load t0 history failed', e)
    historyData.value = null
  }
}
// 累计收益曲线（每日 realized 累加）
const cumHistory = computed(() => {
  const pts = historyData.value?.points || []
  let cum = 0
  return pts.map(p => ({ ...p, cum_pnl: (cum += p.realized_pnl) }))
})

// SVG 曲线几何
const chartW = 800
const chartH = 200
const chartPad = 24
const cumPath = computed(() => {
  const arr = cumHistory.value
  if (arr.length < 2) return ''
  const minY = Math.min(0, ...arr.map(p => p.cum_pnl))
  const maxY = Math.max(0, ...arr.map(p => p.cum_pnl))
  const range = (maxY - minY) || 1
  return arr.map((p, i) => {
    const x = (i / (arr.length - 1)) * chartW
    const y = chartH - chartPad - ((p.cum_pnl - minY) / range) * (chartH - 2 * chartPad)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})
const cumAreaPath = computed(() => {
  if (!cumPath.value) return ''
  const arr = cumHistory.value
  const minY = Math.min(0, ...arr.map(p => p.cum_pnl))
  const maxY = Math.max(0, ...arr.map(p => p.cum_pnl))
  const range = (maxY - minY) || 1
  const zeroYY = chartH - chartPad - ((0 - minY) / range) * (chartH - 2 * chartPad)
  return cumPath.value + ` L${chartW},${zeroYY.toFixed(1)} L0,${zeroYY.toFixed(1)} Z`
})
const zeroY = computed(() => {
  const arr = cumHistory.value
  if (arr.length === 0) return chartH / 2
  const minY = Math.min(0, ...arr.map(p => p.cum_pnl))
  const maxY = Math.max(0, ...arr.map(p => p.cum_pnl))
  const range = (maxY - minY) || 1
  return chartH - chartPad - ((0 - minY) / range) * (chartH - 2 * chartPad)
})
function barX(i) {
  const arr = cumHistory.value
  if (arr.length <= 1) return chartW / 2
  return (i / (arr.length - 1)) * chartW
}
function barY(realized, i) {
  const arr = cumHistory.value
  if (arr.length === 0) return chartH / 2
  const minR = Math.min(0, ...arr.map(p => p.realized_pnl))
  const maxR = Math.max(0, ...arr.map(p => p.realized_pnl))
  const range = (maxR - minR) || 1
  return chartH - chartPad - ((realized - minR) / range) * (chartH - 2 * chartPad)
}
// X 轴标签（首 / 中 / 末）
const xLabelIndices = computed(() => {
  const arr = cumHistory.value
  if (arr.length === 0) return []
  if (arr.length === 1) return [arr[0].trd_date]
  if (arr.length === 2) return [arr[0].trd_date, arr[1].trd_date]
  const mid = Math.floor(arr.length / 2)
  return [arr[0].trd_date, arr[mid].trd_date, arr[arr.length - 1].trd_date]
})

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
    // v8: 走 orderStore 统一处理（已 _upsertToHoldings 写缓存 + 防御性 status 重算）
    //     res = api 拦截器解包后的 list 数组(1 个 OrderOut)
    const res = await orderStore.placeOrder({
      stock_code: stockCode.value,
      order_type: orderType,
      price_type: priceTypeCode,
      price: price,
      volume: volume,
      t0_coefficient: balanceCoeff.value,
      user_def: 'T0',  // T0 页面下单调标记
    })
    if (res) {
      const dir = orderType === '23' ? '买' : '卖'
      ElMessage.success(`${dir}单已报：${volume} 股 @ ¥${formatPrice(price)}`)
      loadT0Stats()
    } else {
      ElMessage.error('下单失败')
    }
  } catch (e) {
    const detail = e?.response?.data?.detail
    const code = detail?.code
    if (code === 'TRADING_DAY_NOT_INIT') {
      // 日初未做：仅提示，由用户在左侧菜单进入「系统初始化」处理
      ElMessage.warning(detail?.msg || '当前未做日初，请到「系统初始化」处理')
    } else if (code === 'OUTSIDE_TRADING_SESSION') {
      ElMessage.warning(detail?.msg || '非交易时段，仅可查询')
    } else {
      ElMessage.error(detail?.msg || e.message || '下单失败')
    }
  } finally {
    submitting.value = false
  }
}

function onOneClickBuy() {
  if (!canBuy.value) return
  submitOrder({ orderType: '23', volume: effectiveBuyQty.value, price: orderPrice.value })
}
function onOneClickSell() {
  if (!canSell.value) return
  submitOrder({ orderType: '24', volume: effectiveSellQty.value, price: orderPrice.value })
}
function onManualSubmit() {
  if (!canManualSubmit.value) return
  submitOrder({ orderType: manualDirection.value, volume: manualVolume.value, price: orderPrice.value })
}
function onOneClickBalance() {
  if (!canBalanceSubmit.value) return
  const orderType = effectiveBalanceQty.value > 0 ? '23' : '24'
  submitOrder({ orderType, volume: Math.abs(effectiveBalanceQty.value), price: orderPrice.value })
}

// ---- M-008 v3: 行内快捷买卖 (按当前持仓百分比, 全局 quickPct / quickPriceType) ----
function onQuickBuy(row) {
  if (isBuyDisabled(row)) return ElMessage.warning(`${row.stock_code} 持仓为 0, 无法按比例买`)
  const r = buildQuickOrder(row, 'buy', quickPct.value, quickPriceType.value, quoteStore)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 买 ${r.qty} 股 @ ¥${formatPrice(r.price)} (${r.label})`,
    '一键买入', { confirmButtonText: '确认买入', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: '23', volume: r.qty, price: r.price }))
    .catch(() => {})
}
function onQuickSell(row) {
  const r = buildQuickOrder(row, 'sell', quickPct.value, quickPriceType.value, quoteStore)
  if (r.error) return ElMessage.warning(r.error)
  ElMessageBox.confirm(
    `${row.stock_code} 卖 ${r.qty} 股 @ ¥${formatPrice(r.price)} (${r.label})`,
    '一键卖出', { confirmButtonText: '确认卖出', cancelButtonText: '取消', type: 'warning' }
  ).then(() => submitOrder({ orderType: '24', volume: r.qty, price: r.price }))
    .catch(() => {})
}
function onQuickBalance(row) {
  // 配平: 净持仓 + (今日买-今日卖) 决定方向
  const bal = calcBalanceQty(row, row.today_buy_volume || 0, row.today_sell_volume || 0)
  if (bal.error) return ElMessage.warning(bal.error)
  const r = buildQuickOrder(row, bal.side, 100, quickPriceType.value, quoteStore)
  if (r.error) return ElMessage.warning(r.error)
  // buildQuickOrder 算的 qty 是按 vol*pct, 配平要覆盖成 bal.qty
  r.qty = bal.qty
  ElMessageBox.confirm(
    `${row.stock_code} ${bal.side === 'buy' ? '买入' : '卖出'} ${bal.qty} 股 配平 (净额归零)`,
    '一键配平', { confirmButtonText: '确认配平', cancelButtonText: '取消', type: 'info' }
  ).then(() => submitOrder({ orderType: bal.side === 'buy' ? '23' : '24', volume: bal.qty, price: r.price }))
    .catch(() => {})
}

// ---- 一键配平（敞口表 row） ----
function onRebalanceRow(row) {
  if (!row || Math.abs(row.net_volume) === 0) return
  const orderType = row.net_volume > 0 ? '24' : '23'   // 净买入 → 卖；净卖出 → 买
  const vol = Math.abs(row.net_volume)
  // 切换当前 stockCode 到目标股票 → 复用下单流
  stockCode.value = row.stock_code
  // 价格用 quote store 中的最新价（如果没有最新价用 cost_basis 兜底）
  const last = quoteStore.getLastPrice(row.stock_code)
  const fallback = Number(row.cost_basis) || last || 0
  submitOrder({ orderType, volume: vol, price: last || fallback })
}

// ---- 全账户一键配平（只对当前 stockCode 下 1 单；如当前标的无敞口提示切股） ----
function onRebalanceAll() {
  const t = exposureTotals.value
  if (!t || t.net_volume === 0) {
    ElMessage.info('已配平，无净敞口')
    return
  }
  if (!exposureList.value.length) {
    ElMessage.info('当日暂无 T0 成交')
    return
  }
  // 仅当前标的下的敞口才下单（用户明确要求：只当前标的，不要多笔）
  const current = exposureList.value.find((p) => p.stock_code === stockCode.value)
  if (!current) {
    const other = exposureList.value
      .filter((p) => Math.abs(p.net_volume) >= 100)
      .map((p) => p.stock_code)
      .join('、')
    ElMessage.warning(
      other
        ? `当前 ${stockCode.value} 无 T0 敞口；有敞口的标的：${other}，请先切换到对应标的再配平`
        : `当前 ${stockCode.value} 无 T0 敞口`
    )
    return
  }
  ElMessageBox.confirm(
    `当前 ${current.stock_code} 净${current.net_volume > 0 ? '买入' : '卖出'} ${Math.abs(
      current.net_volume
    )} 股，确认按当前 stockCode 下 1 单配平？`,
    '一键配平（当前标的）',
    { confirmButtonText: '配平', cancelButtonText: '取消', type: 'warning' }
  )
    .then(() => onRebalanceRow(current))
    .catch(() => {})
}

const aggregateDays = ref(30)   // 7/30/90
function switchAggregateDays(d) {
  aggregateDays.value = d
  loadAggregate('T0', d)
}

// 监听 stockCode 变化 → 加载 stats
watch(stockCode, () => {
  loadT0Stats()
  loadT0History()
})
watch(historyDays, () => loadT0History())

// 监听成交推送 → 自动刷新 stats
let _unwatchTrades = null
function onKeyDown(e) {
  // Esc 关闭弹窗
  if (e.key === 'Escape') {
    if (showPicker.value) showPicker.value = false
    return
  }
  // 快捷键仅在非输入框时生效
  const tag = (e.target?.tagName || '').toLowerCase()
  if (['input', 'textarea', 'select'].includes(tag)) return
  if (e.ctrlKey || e.metaKey || e.altKey) return
  const k = e.key.toLowerCase()
  if (k === 'b' && canBuy.value) {
    e.preventDefault(); onOneClickBuy()
  } else if (k === 's' && canSell.value) {
    e.preventDefault(); onOneClickSell()
  } else if (k === 'f' && canBalanceSubmit.value) {
    e.preventDefault(); onOneClickBalance()
  }
}

onMounted(async () => {
  await loadT0Stats()
  await loadT0History()
  await loadExposure('T0')
  await loadAggregate('T0', aggregateDays.value)
  // 监听 trades 变化（ws 推送会触发）
  _unwatchTrades = watch(
    () => holdingsStore.trades?.length,
    () => { loadT0Stats(); loadExposure('T0') }
  )
  // 监听全局快捷键
  window.addEventListener('keydown', onKeyDown)
})
onUnmounted(() => {
  if (_unwatchTrades) _unwatchTrades()
  window.removeEventListener('keydown', onKeyDown)
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

/* 快速做T 顶部设置条 (M-008) */
.quick-settings-bar {
  margin: 0;
}

/* M-008 v2: 主表 */
.position-table-card {
  margin: 0;
}
.position-table-card :deep(.el-card__body) {
  padding: 12px;
}
.position-table {
  /* 限制主表最大高度, 避免 16+ 行撑爆视口 (M-008 v2) */
  max-height: 480px;
  overflow-y: auto;
}
.position-table :deep(.el-table__header-wrapper) {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--el-bg-color);
}
.position-table-card .pt-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.position-table-card .pt-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.position-table :deep(tr) {
  cursor: pointer;
}
.position-table :deep(tr.is-selected td) {
  background-color: var(--el-color-primary-light-9) !important;
}
.quick-settings-bar :deep(.el-card__body) {
  padding: 8px 12px;
}
.qs-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.qs-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.qs-divider {
  color: var(--el-border-color);
  font-weight: 300;
}
.qs-tip {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  margin-left: auto;
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

/* T0 敞口聚合 + 累计收益 */
.pos { color: #f56c6c; font-weight: 600; }
.neg { color: #67c23a; font-weight: 600; }
.muted { color: var(--el-color-info); }
.empty-tip {
  padding: 24px;
  text-align: center;
  color: var(--el-color-info);
  font-size: 14px;
}
.exposure-card {
  flex: 1;
  min-width: 0;
}
.exposure-table {
  width: 100%;
}
.exposure-totals {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(64, 158, 255, 0.06);
  border-radius: 4px;
  font-size: 13px;
}
.exposure-totals b {
  font-weight: 600;
  margin: 0 2px;
}
.aggregate-card {
  flex: 1;
  min-width: 0;
}
.aggregate-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 4px;
}
.metric-row {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}
.metric-row.sub {
  font-size: 12px;
  color: var(--el-color-info);
  gap: 16px;
  flex-wrap: wrap;
}
.metric {
  flex: 1;
  min-width: 120px;
  text-align: center;
}
.metric-label {
  font-size: 12px;
  color: var(--el-color-info);
  margin-bottom: 6px;
}
.metric-value {
  font-size: 20px;
  font-weight: 600;
}
.card-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

/* 行情价格跳动动画（最新推送时短暂高亮） */
@keyframes priceFlash {
  0% { background-color: transparent; }
  20% { background-color: var(--el-color-warning-light-7); }
  100% { background-color: transparent; }
}

.last-price {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--mono-font);
  transition: color 0.3s;
  padding: 2px 6px;
  border-radius: 4px;
}

.last-price.flash-up {
  animation: priceFlash 0.6s ease-out;
  color: #f56c6c !important;
}

.last-price.flash-down {
  animation: priceFlash 0.6s ease-out;
  color: #67c23a !important;
}

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

/* 仓位管理 + 风险建议 */
.risk-card { margin-bottom: 16px; }
.card-header-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.risk-profile { margin-bottom: 16px; }
.risk-grid { margin-bottom: 12px; }
.risk-item {
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 8px 10px;       /* V9: 12px 16px -> 8px 10px 收紧 */
  text-align: center;
  min-width: 0;            /* 防止数字溢出撑宽 */
}
.risk-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.risk-value { font-size: 16px; font-weight: 700; color: #303133; line-height: 1.2; }  /* V9: 22px -> 16px */
.risk-hint { font-size: 11px; color: #909399; margin-top: 2px; }
.risk-tag {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}

/* V9: 一键开仓 / 一键平仓 / 一键配平（3 按钮等宽紧凑行） */
.quick-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.quick-actions .quick-btn {
  flex: 1;
  font-weight: 600;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 4px;
}
.quick-actions .quick-btn .btn-sub {
  font-size: 11px;
  font-weight: 400;
  opacity: 0.85;
  letter-spacing: 0.3px;
}
.risk-tag.safe { background: #f0f9eb; color: #67c23a; }
.risk-tag.low { background: #fdf6ec; color: #e6a23c; }
.risk-tag.medium { background: #fef0f0; color: #f56c6c; }
.risk-tag.high { background: #fef0f0; color: #f56c6c; font-weight: 700; }
.risk-warnings { margin-top: 8px; }
.warning-list { margin: 0; padding-left: 20px; line-height: 1.7; }

/* 历史曲线 */
.history-card { margin-bottom: 16px; }
.history-meta { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.history-meta .meta-item { font-size: 13px; color: #606266; }
.history-meta b { font-weight: 700; }
.days-pick { margin-left: 8px; }
.chart-wrap { padding: 8px 4px 0; }
.chart-svg {
  width: 100%;
  height: 200px;
  display: block;
}
.x-labels {
  position: relative;
  height: 22px;
  margin-top: 4px;
}
.x-labels span {
  position: absolute;
  transform: translateX(-50%);
  font-size: 11px;
  color: #909399;
  font-family: var(--mono-font);
}

/* M-008 v3: 行内 3 按钮 + 详情 (操作列两行) */
.op-col {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 2px 0;
}
.op-row {
  display: flex;
  gap: 3px;
  align-items: center;
  justify-content: center;
}
.op-row-actions :deep(.el-button) {
  flex: 1;
  min-width: 0;
  padding: 4px 2px !important;
  font-size: 12px !important;
  font-weight: 600;
}
.op-btn-buy :deep(span), .op-btn-sell :deep(span), .op-btn-balance :deep(span) {
  color: #fff !important;
}
.op-row-detail {
  justify-content: stretch;
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 4px;
}
.op-btn-detail {
  width: 100% !important;
  font-size: 12px !important;
  font-weight: 500;
}
</style>

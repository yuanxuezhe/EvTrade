<!--
  ScriptTask.vue — 策略交易页 (script-strategy change v2)

  流程:
    1. 创建任务 (只存配置): 脚本 + 标的 + 参数 + (可选) 回测日期范围 → status='created'
    2. 运行任务: 选 mode (回测/实盘) → 触发后台执行 → status='running'
    3. 详情: 回测看 PnL/曲线/最佳参数; 实盘看持仓 + 收益

  改动 vs v1:
    - 移除创建时的 mode 选择 (移至运行)
    - 任务表加 "运行" 按钮 (status='created'/'done'/'failed'/'stopped' 时可点)
    - 新增运行抽屉: mode radio + 回测参数覆盖
-->
<template>
  <div class="script-task-view fade-in-up" data-el="script-task-view">
    <header class="st-header">
      <h3 class="st-title">策略交易</h3>
      <div class="st-actions">
        <el-button :icon="Refresh" @click="loadAll" data-el="st-refresh">刷新</el-button>
        <el-button :icon="Plus" type="primary" @click="openCreate" data-el="st-create">新建任务</el-button>
      </div>
    </header>

    <div v-loading="loading" class="st-body">
      <el-table :data="filteredTasks" stripe size="small" class="st-table" data-el="st-table">
        <el-table-column label="ID" prop="id" width="60" />
        <el-table-column label="脚本" min-width="180">
          <template #default="{ row }">
            <span class="st-script-name">{{ scriptNameById(row.script_id) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="标的" prop="stock_code" width="100" />
        <el-table-column label="模式" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.mode" size="small" :type="row.mode === 'live' ? 'danger' : 'info'">
              {{ row.mode === 'live' ? '实盘' : '回测' }}
            </el-tag>
            <span v-else class="st-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="_statusType(row.status)">{{ _statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="PnL" width="100" align="right">
          <template #default="{ row }">
            <span :class="row.pnl > 0 ? 'up' : row.pnl < 0 ? 'down' : ''">
              {{ (row.pnl || 0).toFixed(2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="成交" prop="trades_count" width="60" align="right" />
        <el-table-column label="开始" min-width="140">
          <template #default="{ row }">
            {{ (row.started_at || '').replace('T', ' ').slice(0, 19) }}
          </template>
        </el-table-column>
        <el-table-column label="结束" min-width="140">
          <template #default="{ row }">
            {{ (row.finished_at || '').replace('T', ' ').slice(0, 19) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'running'"
              size="small" link type="primary"
              @click="openRun(row)" data-el="st-run"
            >运行</el-button>
            <el-button
              v-if="row.status === 'running'"
              size="small" link type="danger"
              @click="onStop(row)" data-el="st-stop"
            >停止</el-button>
            <el-button size="small" link @click="openDetail(row)" data-el="st-detail">详情</el-button>
            <el-button size="small" link type="danger" @click="onDelete(row)" data-el="st-delete">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 任务详情抽屉 -->
    <el-drawer v-if="detail" v-model="detailOpen" :title="`任务 #${detail.id} 详情`" size="60%">
      <div class="st-detail">
        <el-descriptions :column="3" border size="small" class="st-summary">
          <el-descriptions-item label="模式">
            <el-tag v-if="detail.mode" size="small" :type="detail.mode === 'live' ? 'danger' : 'info'">
              {{ detail.mode === 'live' ? '实盘' : '回测' }}
            </el-tag>
            <span v-else class="st-muted">未运行</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="_statusType(detail.status)">{{ _statusLabel(detail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="标的">{{ detail.stock_code }}</el-descriptions-item>
          <el-descriptions-item label="PnL">
            <span :class="detail.pnl > 0 ? 'up' : detail.pnl < 0 ? 'down' : ''">
              {{ (detail.pnl || 0).toFixed(2) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="成交笔数">{{ detail.trades_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="周期">{{ detail.period || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.error_msg" label="错误" :span="3">
            <span class="st-error">{{ detail.error_msg }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <template v-if="detail.mode === 'backtest' && detail.backtest_result">
          <h4>回测结果</h4>
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="PnL">
              <span :class="(detail.backtest_result.best?.pnl || 0) > 0 ? 'up' : 'down'">
                {{ (detail.backtest_result.best?.pnl || 0).toFixed(2) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="收益率">
              {{ ((detail.backtest_result.best?.pnl_pct || 0) * 100).toFixed(2) }}%
            </el-descriptions-item>
            <el-descriptions-item label="胜率">
              {{ ((detail.backtest_result.best?.win_rate || 0) * 100).toFixed(1) }}%
            </el-descriptions-item>
            <el-descriptions-item label="成交笔数">
              {{ detail.backtest_result.best?.trades_count || 0 }}
            </el-descriptions-item>
          </el-descriptions>

          <h4>最佳参数</h4>
          <el-table :data="bestParamsRows" size="small" border>
            <el-table-column label="参数" prop="key" />
            <el-table-column label="值" prop="value" />
          </el-table>

          <h4>权益曲线</h4>
          <div ref="chartRef" class="st-chart"></div>

          <!-- 详情子 Tab: 信号流 / 进度时间轴 / 交易明细 -->
          <h4>执行详情</h4>
          <el-tabs v-model="detailSubTab" class="st-detail-tabs" data-el="st-detail-tabs">
            <el-tab-pane label="信号流" name="signals">
              <div class="st-signals-filter">
                <el-radio-group v-model="signalFilter" size="small" @change="loadSignals" data-el="st-signal-filter">
                  <el-radio-button label="">全部</el-radio-button>
                  <el-radio-button label="BUY">买入</el-radio-button>
                  <el-radio-button label="SELL">卖出</el-radio-button>
                  <el-radio-button label="INFO">信号</el-radio-button>
                </el-radio-group>
                <span class="st-signals-count">
                  共 {{ signalData.total_signals || 0 }} 条
                  <span v-if="signalData.truncated" class="st-muted">(已截断)</span>
                </span>
              </div>
              <el-table :data="signalData.signals || []" size="small" border max-height="400" data-el="st-signals-table">
                <el-table-column label="时间" prop="stime" width="140" />
                <el-table-column label="类型" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" :type="_signalType(row.type)">{{ row.type }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="价格" prop="price" width="80">
                  <template #default="{ row }">
                    <span v-if="row.price !== undefined">{{ Number(row.price).toFixed(4) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="触发原因 / 详情" min-width="200">
                  <template #default="{ row }">
                    <span>{{ row.msg }}</span>
                    <div v-if="row.indicators" class="st-signal-indicators">
                      <el-tag v-for="(v, k) in row.indicators" :key="k" size="small" type="info">
                        {{ k }}={{ typeof v === 'number' ? v.toFixed(4) : v }}
                      </el-tag>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="140">
                  <template #default="{ row }">
                    <span v-if="row.state" class="st-signal-state">
                      持仓 {{ row.state.position || 0 }} 股
                      <span v-if="row.state.cash !== undefined">
                        · 现金 {{ Number(row.state.cash).toFixed(2) }}
                      </span>
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="盈亏" width="100" align="right">
                  <template #default="{ row }">
                    <span v-if="row.pnl !== undefined"
                          :class="row.pnl > 0 ? 'up' : row.pnl < 0 ? 'down' : ''">
                      {{ Number(row.pnl).toFixed(2) }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane :label="`进度 (${progressData.length} bar)`" name="progress">
              <div class="st-progress-summary" v-if="progressData.length">
                <el-tag>总 bar 数: {{ progressData.length }}</el-tag>
                <el-tag type="info">权益范围: {{ progressMinEquity.toFixed(2) }} ~ {{ progressMaxEquity.toFixed(2) }}</el-tag>
                <el-tag type="success">期末权益: {{ progressData[progressData.length - 1]?.equity?.toFixed(2) }}</el-tag>
              </div>
              <el-table :data="progressData" size="small" border max-height="400" data-el="st-progress-table">
                <el-table-column label="#" prop="bar_idx" width="60" />
                <el-table-column label="时间" prop="stime" width="140" />
                <el-table-column label="收盘" prop="close" width="80">
                  <template #default="{ row }">{{ Number(row.close).toFixed(4) }}</template>
                </el-table-column>
                <el-table-column label="持仓" prop="position" width="80" align="right" />
                <el-table-column label="现金" width="100" align="right">
                  <template #default="{ row }">{{ Number(row.cash).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column label="权益" min-width="100" align="right">
                  <template #default="{ row }">
                    <span :class="row.equity > (row.cash + row.position * row.close) ? 'up' : ''">
                      {{ Number(row.equity).toFixed(2) }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane label="交易明细" name="trades">
              <el-table :data="detail.backtest_result.best?.trades || []" size="small" border>
                <el-table-column label="时间" prop="stime" width="140" />
                <el-table-column label="方向" width="60">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.side === 'BUY' ? 'success' : 'danger'">{{ row.side }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="价格" prop="price" width="80" />
                <el-table-column label="数量" prop="volume" width="80" />
                <el-table-column label="盈亏" width="100" align="right">
                  <template #default="{ row }">
                    <span :class="row.pnl > 0 ? 'up' : row.pnl < 0 ? 'down' : ''">
                      {{ (row.pnl || 0).toFixed(2) }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <!-- 🆕 执行日志 Tab — 显示每个阶段时间轴 (用于诊断 '跑回测卡哪了') -->
                        <el-tab-pane :label="`执行日志 (${executionLog.length})`" name="execution">
              <div v-if="executionLog.length" class="st-exec-summary">
                <el-tag>总阶段: {{ executionLog.length }}</el-tag>
                <el-tag type="info">耗时: {{ executionLog[executionLog.length - 1]?.elapsed_ms || 0 }} ms</el-tag>
                <el-tag type="success">bars: {{ executionLog.filter(e => e.phase === 'bar').length }}</el-tag>
                <el-tag v-if="detail.backtest_result?.total_bars" type="warning">
                  total_bars: {{ detail.backtest_result.total_bars }}
                </el-tag>
              </div>
              <el-input
                v-model="executionFilter"
                placeholder="过滤 (phase / msg / bar_idx)"
                size="small"
                clearable
                class="st-exec-filter"
                data-el="st-exec-filter"
              />
              <el-table :data="filteredExecutionLog" size="small" border max-height="500" data-el="st-exec-table">
                <el-table-column label="耗时" prop="elapsed_ms" width="80">
                  <template #default="{ row }">
                    <code class="st-exec-ms">{{ row.elapsed_ms }}ms</code>
                  </template>
                </el-table-column>
                <el-table-column label="阶段" prop="phase" width="100">
                  <template #default="{ row }">
                    <el-tag size="small" :type="_phaseType(row.phase)">{{ row.phase }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="bar_idx" prop="bar_idx" width="80">
                  <template #default="{ row }">
                    <span v-if="row.bar_idx !== undefined">{{ row.bar_idx }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="消息" prop="msg" min-width="380" />
                <el-table-column label="stime" prop="stime" width="140">
                  <template #default="{ row }">
                    <span v-if="row.stime">{{ row.stime }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="close" prop="close" width="80">
                  <template #default="{ row }">
                    <span v-if="row.close !== undefined">{{ Number(row.close).toFixed(4) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="持仓" prop="position" width="60">
                  <template #default="{ row }">
                    <span v-if="row.position !== undefined">{{ row.position }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="权益" prop="equity" width="100" align="right">
                  <template #default="{ row }">
                    <span v-if="row.equity !== undefined">{{ Number(row.equity).toFixed(2) }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </template>

        <template v-else-if="detail.mode === 'live'">
          <h4>实盘运行</h4>
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="当前持仓">
              <span v-for="(vol, code) in (detail.positions || {})" :key="code">
                {{ code }}: {{ vol }} 股
              </span>
              <span v-if="!detail.positions || !Object.keys(detail.positions).length" class="st-muted">无</span>
            </el-descriptions-item>
            <el-descriptions-item label="累计 PnL">
              <span :class="detail.pnl > 0 ? 'up' : detail.pnl < 0 ? 'down' : ''">
                {{ (detail.pnl || 0).toFixed(2) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="成交笔数">{{ detail.trades_count || 0 }}</el-descriptions-item>
          </el-descriptions>
          <h4>实盘信号流 (LiveRunner 每 5s flush)</h4>
          <div class="st-signals-filter">
            <el-radio-group v-model="signalFilter" size="small" @change="loadSignals" data-el="st-live-signal-filter">
              <el-radio-button label="">全部</el-radio-button>
              <el-radio-button label="BUY">买入</el-radio-button>
              <el-radio-button label="SELL">卖出</el-radio-button>
              <el-radio-button label="INFO">信号</el-radio-button>
            </el-radio-group>
            <span class="st-signals-count">共 {{ signalData.total_signals || 0 }} 条</span>
          </div>
          <el-table :data="signalData.signals || []" size="small" border max-height="500" data-el="st-live-signals-table">
            <el-table-column label="时间" prop="stime" width="140" />
            <el-table-column label="类型" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="_signalType(row.type)">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="价格" prop="price" width="80">
              <template #default="{ row }">
                <span v-if="row.price !== undefined">{{ Number(row.price).toFixed(4) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="详情" prop="msg" min-width="300" />
            <el-table-column label="持仓" prop="order_no" width="120">
              <template #default="{ row }">
                <code v-if="row.order_no" class="st-order-no">{{ row.order_no }}</code>
              </template>
            </el-table-column>
          </el-table>
        </template>

        <template v-else-if="detail.error_msg">
          <h4>错误</h4>
          <pre class="st-error">{{ detail.error_msg }}</pre>
        </template>

        <template v-else>
          <el-empty description="任务尚未运行, 点击右上 '运行' 按钮触发" />
        </template>
      </div>
    </el-drawer>

    <!-- 新建任务抽屉 (不指定 mode) -->
    <el-drawer v-model="createOpen" title="新建任务" size="500px">
      <el-form :model="createForm" label-width="100px" size="small" class="st-create-form">
        <el-form-item label="脚本">
          <el-select v-model="createForm.script_id" placeholder="选择脚本" filterable style="width: 100%" @change="onScriptChange" data-el="st-form-script">
            <el-option
              v-for="s in scripts"
              :key="s.id"
              :label="s.name"
              :value="s.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="标的">
          <el-input v-model="createForm.stock_code" placeholder="如 600519.SH" data-el="st-form-stock" />
        </el-form-item>

        <el-form-item label="回测起止">
          <el-date-picker
            v-model="createForm.dateRange"
            type="daterange"
            value-format="YYYYMMDD"
            range-separator="~"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 100%"
          />
          <span class="st-hint">可选, 运行回测时也可再设置</span>
        </el-form-item>

        <el-form-item label="K线周期">
          <el-select v-model="createForm.period">
            <el-option label="1分钟" value="1m" />
            <el-option label="5分钟" value="5m" />
            <el-option label="15分钟" value="15m" />
            <el-option label="30分钟" value="30m" />
            <el-option label="1小时" value="1h" />
            <el-option label="1日" value="1d" />
          </el-select>
        </el-form-item>

        <template v-if="createForm.params_schema?.length">
          <h4 class="st-params-title">参数</h4>
          <el-form-item v-for="p in createForm.params_schema" :key="p.key" :label="p.key">
            <el-input-number
              v-if="p.type !== 'choice'"
              v-model="createForm.params[p.key]"
              :step="p.step || 1"
              :min="p.min"
              :max="p.max"
              style="width: 100%"
            />
            <el-select v-else v-model="createForm.params[p.key]" style="width: 100%">
              <el-option v-for="v in p.values" :key="v" :label="String(v)" :value="v" />
            </el-select>
          </el-form-item>
        </template>

        <el-alert type="info" :closable="false" show-icon class="st-create-tip">
          <p>任务创建后 <strong>不会自动运行</strong>, 需在列表点击 "运行" 按钮选择 "回测" 或 "实盘"。</p>
        </el-alert>

        <div class="st-form-actions">
          <el-button @click="createOpen = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="onCreateTask" data-el="st-form-submit">
            创建任务
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <!-- 运行任务抽屉 (选 mode) -->
    <el-drawer v-model="runOpen" :title="`运行任务 #${runForm.id}`" size="500px">
      <el-form :model="runForm" label-width="100px" size="small" class="st-create-form">
        <el-form-item label="任务">
          <span>{{ scriptNameById(runForm.script_id) }} / {{ runForm.stock_code }}</span>
        </el-form-item>

        <el-form-item label="运行模式">
          <el-radio-group v-model="runForm.mode" data-el="st-run-mode">
            <el-radio-button label="backtest">回测</el-radio-button>
            <el-radio-button label="live">实盘</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="runForm.mode === 'backtest'">
          <el-form-item label="起止日期">
            <el-date-picker
              v-model="runForm.dateRange"
              type="daterange"
              value-format="YYYYMMDD"
              range-separator="~"
              start-placeholder="开始"
              end-placeholder="结束"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="K线周期">
            <el-select v-model="runForm.period">
              <el-option label="1分钟" value="1m" />
              <el-option label="5分钟" value="5m" />
              <el-option label="15分钟" value="15m" />
              <el-option label="30分钟" value="30m" />
              <el-option label="1小时" value="1h" />
              <el-option label="1日" value="1d" />
            </el-select>
          </el-form-item>
        </template>

        <el-alert v-else type="warning" :closable="false" show-icon>
          <p><strong>实盘任务</strong>将真实下单到券商, 请确认已测试回测且参数合理。</p>
        </el-alert>

        <div class="st-form-actions">
          <el-button @click="runOpen = false">取消</el-button>
          <el-button type="primary" :loading="running" @click="onRunTask" data-el="st-run-submit">
            {{ runForm.mode === 'live' ? '启动实盘' : '开始回测' }}
          </el-button>
        </div>
      </el-form>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { scriptStrategyApi } from '../api/script_strategy'

const route = useRoute()

const loading = ref(false)
const tasks = ref([])
const scripts = ref([])
const detailOpen = ref(false)
const detail = ref(null)
const createOpen = ref(false)
const creating = ref(false)
const runOpen = ref(false)
const running = ref(false)
const chartRef = ref(null)
let chart = null

const createForm = ref(_blankCreate())
const runForm = ref(_blankRun())

// 详情面板子 Tab + 信号过滤
const detailSubTab = ref('signals')  // 'signals' | 'progress' | 'trades' | 'execution'
const signalFilter = ref('')           // '' / 'BUY' / 'SELL' / 'INFO'
const signalData = ref({ signals: [], progress: [], total_signals: 0, truncated: false })
const progressData = ref([])
const executionFilter = ref('')         // execution_log 过滤关键字
const progressMinEquity = computed(() => progressData.value.length
  ? Math.min(...progressData.value.map(p => p.equity || 0)) : 0)
const progressMaxEquity = computed(() => progressData.value.length
  ? Math.max(...progressData.value.map(p => p.equity || 0)) : 0)

// 从 detail.backtest_result.execution_log 抽出 + 按阶段过滤
const executionLog = computed(() => {
  const r = detail.value?.backtest_result
  if (!r) return []
  return r.execution_log || []
})

const filteredExecutionLog = computed(() => {
  const kw = executionFilter.value.trim().toLowerCase()
  if (!kw) return executionLog.value
  return executionLog.value.filter(e => {
    if (String(e.phase || '').toLowerCase().includes(kw)) return true
    if (String(e.msg || '').toLowerCase().includes(kw)) return true
    if (e.bar_idx !== undefined && String(e.bar_idx).includes(kw)) return true
    return false
  })
})

function _phaseType(p) {
  return {
    start: '',
    sandbox_ok: 'success',
    sandbox_err: 'danger',
    on_init_start: '',
    on_init_done: 'success',
    on_init_err: 'danger',
    bar: 'info',
    on_bar_err: 'danger',
    on_finish_start: '',
    on_finish_done: 'success',
    on_finish_err: 'warning',
    done: 'success',
    empty_bars: 'warning',
  }[p] || ''
}

function _blankCreate() {
  return {
    script_id: null,
    stock_code: '',
    dateRange: null,
    period: '1d',
    params: {},
    params_schema: [],
  }
}

function _blankRun() {
  return {
    id: null,
    script_id: null,
    stock_code: '',
    mode: 'backtest',
    dateRange: null,
    period: '1d',
  }
}

// ─────────────── load ───────────────
async function loadAll() {
  loading.value = true
  try {
    const [t, s] = await Promise.all([
      scriptStrategyApi.listTasks(),
      scriptStrategyApi.listScripts(),
    ])
    tasks.value = t
    scripts.value = s
  } catch (e) {
    // ignored
  } finally {
    loading.value = false
  }
}

const filteredTasks = computed(() => tasks.value)

function scriptNameById(id) {
  const s = scripts.value.find(x => x.id === id)
  return s?.name || `#${id}`
}

function _statusType(s) {
  return {
    created: 'info',
    pending: 'info',
    running: 'warning',
    done: 'success',
    stopped: '',
    failed: 'danger',
  }[s] || ''
}
function _statusLabel(s) {
  return {
    created: '待运行',
    pending: '等待',
    running: '运行中',
    done: '完成',
    stopped: '已停',
    failed: '失败',
  }[s] || s
}

function _signalType(t) {
  return {
    BUY: 'success',
    SELL: 'danger',
    INFO: 'info',
    WARN: 'warning',
    STOP: '',
    TP: '',
    ERROR: 'danger',
  }[t] || ''
}

// ─────────────── 详情 ───────────────
async function openDetail(row) {
  detailOpen.value = true
  detail.value = row
  await nextTick()
  renderChart()
  await loadSignals()
}

async function loadSignals() {
  if (!detail.value?.id) return
  try {
    const data = await scriptStrategyApi.getTaskSignals(detail.value.id, {
      type: signalFilter.value || null,
      limit: 500,
    })
    signalData.value = data
    progressData.value = data.progress || []
  } catch (e) {
    // ignored
  }
}

function renderChart() {
  if (!chartRef.value || !detail.value?.backtest_result?.best?.equity_curve) return
  const eq = detail.value.backtest_result.best.equity_curve
  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: eq.map(e => e.stime) },
    yAxis: { type: 'value', scale: true },
    tooltip: { trigger: 'axis' },
    series: [{
      name: '权益',
      data: eq.map(e => e.equity),
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.2 },
    }],
  })
}

const bestParamsRows = computed(() => {
  if (!detail.value?.best_params) return []
  return Object.entries(detail.value.best_params).map(([k, v]) => ({ key: k, value: String(v) }))
})

// ─────────────── 新建 ───────────────
function openCreate() {
  createForm.value = _blankCreate()
  if (route.query.script_id) {
    createForm.value.script_id = Number(route.query.script_id)
    onScriptChange()
  }
  createOpen.value = true
}

function onScriptChange() {
  const s = scripts.value.find(x => x.id === createForm.value.script_id)
  if (!s) return
  const params = {}
  createForm.value.params_schema = s.params_schema || []
  for (const p of createForm.value.params_schema) {
    params[p.key] = p.default
  }
  createForm.value.params = params
}

async function onCreateTask() {
  if (!createForm.value.script_id) {
    ElMessage.warning('请选择脚本')
    return
  }
  if (!createForm.value.stock_code) {
    ElMessage.warning('请填写标的代码')
    return
  }
  creating.value = true
  try {
    const payload = {
      script_id: createForm.value.script_id,
      stock_code: createForm.value.stock_code,
      params: createForm.value.params,
      period: createForm.value.period,
    }
    if (createForm.value.dateRange) {
      payload.backtest_start_date = createForm.value.dateRange[0]
      payload.backtest_end_date = createForm.value.dateRange[1]
    }
    await scriptStrategyApi.createTask(payload)
    ElMessage.success('任务已创建 (status=created), 请点击运行按钮触发')
    createOpen.value = false
    await loadAll()
  } catch (e) {
    // ignored
  } finally {
    creating.value = false
  }
}

// ─────────────── 运行 ───────────────
function openRun(row) {
  runForm.value = {
    id: row.id,
    script_id: row.script_id,
    stock_code: row.stock_code,
    mode: 'backtest',
    dateRange: row.backtest_start_date && row.backtest_end_date
      ? [row.backtest_start_date, row.backtest_end_date]
      : null,
    period: row.period || '1d',
  }
  runOpen.value = true
}

async function onRunTask() {
  if (runForm.value.mode === 'backtest') {
    if (!runForm.value.dateRange) {
      ElMessage.warning('请选择回测起止日期')
      return
    }
    if (!runForm.value.dateRange[0] || !runForm.value.dateRange[1]) {
      ElMessage.warning('回测起止日期不完整')
      return
    }
  }
  running.value = true
  try {
    const payload = { mode: runForm.value.mode }
    if (runForm.value.mode === 'backtest') {
      payload.backtest_start_date = runForm.value.dateRange[0]
      payload.backtest_end_date = runForm.value.dateRange[1]
      payload.period = runForm.value.period
    } else {
      payload.period = runForm.value.period
    }
    await scriptStrategyApi.runTask(runForm.value.id, payload)
    ElMessage.success('已启动')
    runOpen.value = false
    await loadAll()
  } catch (e) {
    // ignored
  } finally {
    running.value = false
  }
}

// ─────────────── 控制 ───────────────
async function onStop(row) {
  try {
    await scriptStrategyApi.stopTask(row.id)
    ElMessage.success('已停止')
    await loadAll()
  } catch (e) {
    // ignored
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除任务 #${row.id}?`, '删除', { type: 'warning' })
  } catch { return }
  try {
    await scriptStrategyApi.deleteTask(row.id)
    ElMessage.success('已删除')
    await loadAll()
  } catch (e) {
    // ignored
  }
}

// ─────────────── mount ───────────────
onMounted(async () => {
  await loadAll()
  if (route.query.script_id) openCreate()
})

// 详情抽屉关闭时 dispose chart
watch(detailOpen, async (v) => {
  if (!v && chart) {
    chart.dispose()
    chart = null
  }
})

// 实盘运行中 → 每 5s 自动刷新信号
let _refreshTimer = null
watch(detail, async (v) => {
  if (_refreshTimer) {
    clearInterval(_refreshTimer)
    _refreshTimer = null
  }
  if (v && v.mode === 'live' && v.status === 'running') {
    _refreshTimer = setInterval(() => loadSignals(), 5000)
  }
})
onBeforeUnmount(() => {
  if (_refreshTimer) clearInterval(_refreshTimer)
})
</script>

<style scoped>
.script-task-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.st-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}
.st-title { margin: 0; font-size: 18px; font-weight: 600; }

.st-body {
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.up { color: var(--color-up, #f56c6c); font-weight: 600; }
.down { color: var(--color-down, #67c23a); font-weight: 600; }
.st-script-name { font-weight: 500; }
.st-muted { color: var(--text-placeholder); }

.st-summary { margin-bottom: var(--space-4); }

.st-detail h4 {
  font-size: 13px;
  margin: var(--space-4) 0 var(--space-2);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.st-chart {
  width: 100%;
  height: 250px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-base);
}

.st-error {
  color: var(--color-down, #f56c6c);
  background: var(--bg-base);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 12px;
  white-space: pre-wrap;
}

.st-create-form { padding: var(--space-2) 0; }
.st-params-title {
  font-size: 13px;
  margin: var(--space-3) 0 var(--space-2);
  color: var(--text-secondary);
  text-transform: uppercase;
}
.st-hint { font-size: 11px; color: var(--text-placeholder); margin-left: var(--space-2); }
.st-create-tip { margin-top: var(--space-3); }
.st-form-actions {
  margin-top: var(--space-4);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

/* 信号流 / 进度 Tab */
.st-detail-tabs { margin-top: var(--space-2); }
.st-signals-filter {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}
.st-signals-count {
  font-size: 12px;
  color: var(--text-secondary);
  margin-left: auto;
}
.st-signal-indicators {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.st-signal-state {
  font-size: 12px;
  color: var(--text-secondary);
}
.st-order-no {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  background: var(--bg-base);
  padding: 1px 4px;
  border-radius: 2px;
}
.st-progress-summary {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

/* 执行日志 (诊断卡哪了) */
.st-exec-summary {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.st-exec-filter {
  margin-bottom: var(--space-2);
}
.st-exec-ms {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  background: var(--bg-base);
  padding: 1px 4px;
  border-radius: 2px;
}
</style>
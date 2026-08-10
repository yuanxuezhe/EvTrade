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
        <el-button :icon="Plus" type="primary" @click="openCreate" data-el="st-create">新建策略</el-button>
      </div>
    </header>

    <div class="st-split">
      <div v-loading="loading" class="st-body">
        <el-table :data="filteredTasks" stripe size="small" class="st-table" data-el="st-table"
                  highlight-current-row @row-click="openDetail">
          <el-table-column label="ID" prop="id" width="60" />
          <el-table-column label="脚本" min-width="180">
            <template #default="{ row }">
              <span class="st-script-name">{{ scriptNameById(row.script_id) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="策略描述" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="st-script-desc">{{ row.description || scriptDescById(row.script_id) || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="标的" prop="stock_code" width="100" />
          <el-table-column label="模式" width="130">
            <template #default="{ row }">
              <!-- 模式切换按钮: 决定该任务下次运行走回测还是实盘 -->
              <el-switch
                :model-value="row.mode === 'live'"
                active-text="实盘"
                inactive-text="回测"
                active-color="#f56c6c"
                :disabled="row.status === 'running'"
                @change="(v) => onToggleMode(row, v)"
              />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 'running'"
                size="small" type="danger" plain
                @click="onStop(row)" data-el="st-stop"
              >停止</el-button>
              <el-button
                v-else
                size="small" type="primary" plain
                @click="openRun(row)" data-el="st-run"
              >启动</el-button>
              <el-button
                size="small" type="danger" link
                @click="onDelete(row)" data-el="st-delete"
              >删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 右侧: 展开的详情 -->
      <div v-if="detail" class="st-side" data-el="st-side-detail">
        <div class="st-detail">
          <div class="st-side-title">策略{{ detail.id }} · {{ scriptNameById(detail.script_id) }} · {{ detail.description || scriptDescById(detail.script_id) }}</div>
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
          <!-- v91.1: 实时进度面板 (running 时显示) -->
          <el-descriptions-item v-if="detail.status === 'running' && detail.progress" label="进度" :span="3">
            <div class="st-progress-panel">
              <el-progress
                :percentage="progressPercent"
                :status="progressStatus"
                :stroke-width="14"
                text-inside
                :format="() => progressText"
                data-el="st-progress-bar"
              />
              <div class="st-progress-detail">
                <el-tag size="small" :type="progressPhaseTagType" effect="dark">
                  {{ progressPhaseLabel }}
                </el-tag>
                <span class="st-progress-msg">{{ detail.progress.msg || '' }}</span>
                <span v-if="detail.progress.bar_count" class="st-progress-meta">
                  📊 {{ detail.progress.bar_count }} bars
                </span>
                <span v-if="detail.progress.fetch_elapsed" class="st-progress-meta">
                  ⏱️ {{ detail.progress.fetch_elapsed.toFixed(1) }}s
                </span>
                <span class="st-progress-time">最后更新: {{ detail.progress.updated_at || '' }}</span>
              </div>
            </div>
          </el-descriptions-item>
          <!-- v91.1: failed 任务显示 sweep 信息 -->
          <el-descriptions-item v-if="detail.status === 'failed' && detail.error_msg" label="错误" :span="3">
            <pre class="st-error">{{ detail.error_msg }}</pre>
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

          <!-- v122+: sweep summary 任务的 per-combo 结果表 -->
          <SweepResultsTable
            v-if="detail.sweep_id && detail.backtest_result?.sweep_results"
            :backtest-result="detail.backtest_result"
            :metric="detail.sweep_metric || 'sharpe'"
          />

          <!-- 详情子 Tab: 信号流 / 进度时间轴 / 交易明细 -->
          <h4>执行详情</h4>
          <el-tabs v-model="detailSubTab" class="st-detail-tabs" data-el="st-detail-tabs">
            <el-tab-pane label="信号流" name="signals">
              <div class="st-signals-filter">
                <el-radio-group v-model="signalFilter" size="small" @change="loadSignals" data-el="st-signal-filter">
                  <el-radio-button value="">全部</el-radio-button>
                  <el-radio-button value="BUY">买入</el-radio-button>
                  <el-radio-button value="SELL">卖出</el-radio-button>
                  <el-radio-button value="INFO">信号</el-radio-button>
                </el-radio-group>
                <span class="st-signals-count">
                  共 {{ signalData.total_signals || 0 }} 条
                  <span v-if="signalData.truncated" class="st-muted">(已截断)</span>
                </span>
              </div>
              <el-table :data="signalData.signals || []" size="small" border max-height="400" data-el="st-signals-table">
                <el-table-column label="时间" prop="stime" width="140" />
                <el-table-column label="模式" width="70">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.mode === 'live' ? 'danger' : 'info'">
                      {{ row.mode === 'live' ? '实盘' : '回测' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" :type="_signalType(row.signal_type || row.type)">{{ row.signal_type || row.type }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="价格" prop="price" width="80">
                  <template #default="{ row }">
                    <span v-if="row.price !== undefined">{{ formatPrice(row.price, row.stock_code) }}</span>
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
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="BUY">买入</el-radio-button>
              <el-radio-button value="SELL">卖出</el-radio-button>
              <el-radio-button value="INFO">信号</el-radio-button>
            </el-radio-group>
            <span class="st-signals-count">共 {{ signalData.total_signals || 0 }} 条</span>
          </div>
          <el-table :data="signalData.signals || []" size="small" border max-height="500" data-el="st-live-signals-table">
            <el-table-column label="时间" prop="stime" width="140" />
            <el-table-column label="类型" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="_signalType(row.signal_type || row.type)">{{ row.signal_type || row.type }}</el-tag>
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
      </div>

      <div v-else class="st-side st-side-empty">
        <el-empty description="点击左侧任务查看详情" :image-size="80" />
      </div>
    </div>

    <!-- 新建策略抽屉 (不指定 mode) -->
    <el-drawer v-model="createOpen" title="新建策略" size="500px">
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

        <el-form-item label="描述">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="2"
            placeholder="策略描述, 例如: 5日金叉买入 / 跌破20日均线卖出..."
            data-el="st-form-desc"
          />
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
          <p>策略创建后 <strong>不会自动运行</strong>, 需在列表点击 "启动" 按钮并选择模式运行。</p>
        </el-alert>

        <div class="st-form-actions">
          <el-button @click="createOpen = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="onCreateTask" data-el="st-form-submit">
            创建策略
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <!-- 运行策略抽屉 -->
    <el-drawer v-model="runOpen" :title="`运行策略 #${runForm.id}`" size="500px">
      <el-form :model="runForm" label-width="100px" size="small" class="st-create-form">
        <el-form-item label="策略">
          <span>{{ scriptNameById(runForm.script_id) }} / {{ runForm.stock_code }}</span>
        </el-form-item>

        <!-- 运行模式由左侧表格"模式"切换按钮决定, 不再在抽屉里选 -->
        <template v-if="runForm.mode === 'backtest'">
          <!-- v122+: 回测 tab: [单次回测] / [参数扫描] -->
          <el-form-item label="运行模式">
            <el-radio-group v-model="runTab" size="small" data-el="st-run-tab">
              <el-radio-button value="backtest">单次回测</el-radio-button>
              <el-radio-button value="sweep">参数扫描</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <template v-if="runTab === 'backtest'">
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

          <template v-else>
            <SweepForm
              :schema="currentScriptSchema"
              :task-id="runForm.id"
              @submit="onRunSweep"
              @cancel="runTab = 'backtest'"
            />
            <div v-if="sweepResult" class="st-sweep-result">
              <el-alert type="success" :closable="true" @close="sweepResult = null" show-icon>
                <p>扫描已启动 — sweep_id=<code>{{ sweepResult.sweep_id }}</code>, 共 {{ sweepResult.total_runs }} 个组合, summary task #{{ sweepResult.summary_task_id }}</p>
              </el-alert>
            </div>
          </template>
        </template>

        <template v-else>
          <!-- v122+: 实盘参数来源 -->
          <el-alert type="warning" :closable="false" show-icon>
            <p><strong>实盘策略</strong>将真实下单到券商, 请确认已测试回测且参数合理。</p>
          </el-alert>
          <el-form-item label="参数来源">
            <el-radio-group v-model="liveParamSource" size="small" data-el="st-live-source">
              <el-radio-button value="default">默认值</el-radio-button>
              <el-radio-button value="picker">从历史回测选</el-radio-button>
              <el-radio-button value="manual">手动指定</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="liveParamSource === 'picker'" label="已选参数">
            <div class="st-live-preview">
              <el-tag
                v-for="(v, k) in (livePickerParams || {})"
                :key="k"
                size="small"
                effect="plain"
                type="info"
                style="margin-right: 4px"
              >{{ k }}={{ v }}</el-tag>
              <el-button size="small" link @click="pickerOpen = true" data-el="st-open-picker">选...</el-button>
            </div>
          </el-form-item>
          <el-form-item v-else-if="liveParamSource === 'manual'" label="JSON">
            <el-input
              v-model="liveManualParams"
              type="textarea"
              :rows="3"
              placeholder='{"fast": 7, "slow": 30}'
            />
          </el-form-item>
        </template>

        <div class="st-form-actions">
          <el-button @click="runOpen = false">取消</el-button>
          <el-button
            v-if="!(runForm.mode === 'backtest' && runTab === 'sweep')"
            type="primary"
            :loading="running"
            @click="onRunTask"
            data-el="st-run-submit"
          >
            {{ runForm.mode === 'live' ? '启动实盘' : '开始回测' }}
          </el-button>
        </div>
      </el-form>
    </el-drawer>

    <!-- v122+: 历史回测选择 dialog -->
    <BacktestPicker
      v-model="pickerOpen"
      :script-id="runForm.script_id || ''"
      @select="onPickerSelect"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { scriptStrategyApi } from '../api/script_strategy'
import { useWsStore } from '../stores/ws'  // v91.4: 实时进度推送
import { formatPrice } from '../composables/usePricePrecision'
// v122+ sweep + 从历史回测选参数
import SweepForm from '../components/strategy/SweepForm.vue'
import BacktestPicker from '../components/strategy/BacktestPicker.vue'
import SweepResultsTable from '../components/strategy/SweepResultsTable.vue'

const route = useRoute()

const loading = ref(false)
const tasks = ref([])
const scripts = ref([])
const detail = ref(null)
const createOpen = ref(false)
const creating = ref(false)
const runOpen = ref(false)
const running = ref(false)
const chartRef = ref(null)
let chart = null

const createForm = ref(_blankCreate())
const runForm = ref(_blankRun())
// v122+ 运行抽屉 tabs / 实盘参数来源
const runTab = ref('backtest')              // 'backtest' | 'sweep'
const liveParamSource = ref('default')       // 'default' | 'picker' | 'manual'
const pickerOpen = ref(false)                // BacktestPicker dialog 显隐
const liveManualParams = ref('{}')           // 手动模式 JSON 输入

// 详情面板子 Tab + 信号过滤
const detailSubTab = ref('signals')  // 'signals' | 'progress' | 'trades' | 'execution'
const signalFilter = ref('')           // '' / 'BUY' / 'SELL' / 'INFO'
const signalData = ref({ signals: [], progress: [], total_signals: 0, truncated: false })
const progressData = ref([])
const executionFilter = ref('')         // execution_log 过滤关键字

// v91.1: 实时进度面板 computed
const progressPercent = computed(() => {
  const p = detail.value?.progress
  if (!p) return 0
  if (p.pct !== undefined && p.pct !== null) return Math.round(p.pct)
  if (p.total) return Math.round((p.current || 0) / p.total * 100)
  // grid_combo 用 combo_idx / total_combos
  if (p.total_combos) return Math.round((p.combo_idx || 0) / p.total_combos * 100)
  // backtest_bar 用 bar_idx / total_bars
  if (p.total_bars) return Math.round((p.bar_idx || 0) / p.total_bars * 100)
  return 0
})
const progressText = computed(() => {
  const p = detail.value?.progress
  if (!p) return ''
  if (p.pct !== undefined && p.pct !== null) return `${Math.round(p.pct)}%`
  if (p.total) return `${p.current || 0}/${p.total}`
  if (p.total_combos) return `${p.combo_idx || 0}/${p.total_combos}`
  if (p.total_bars) return `${p.bar_idx || 0}/${p.total_bars}`
  return ''
})
const progressStatus = computed(() => {
  const p = detail.value?.progress
  if (!p) return ''
  if (p.phase === 'done') return 'success'
  if (p.phase === 'failed') return 'exception'
  return ''
})
// 阶段 → 中文标签 + tag type
const PHASE_LABELS = {
  start: { label: '启动', type: 'info' },
  fetch_his_bars_sending: { label: '📡 发请求', type: 'primary' },
  fetch_his_bars_waiting: { label: '⏳ 等broker', type: 'warning' },
  fetch_his_bars_done: { label: '✅ 拉取成功', type: 'success' },
  fetch_his_bars_empty: { label: '❌ broker无数据', type: 'danger' },
  expand_params: { label: '🔧 展开参数', type: 'info' },
  backtest_bar: { label: '🔄 跑回测', type: 'primary' },
  grid_combo: { label: '🔀 grid搜索', type: 'primary' },
  write_result: { label: '💾 写结果', type: 'info' },
  // strategy_exec 阶段 (v123: 引擎实时进度)
  load_script: { label: '📥 加载脚本', type: 'info' },
  build_cerebro: { label: '🔧 构造引擎', type: 'info' },
  running: { label: '🔄 回测中', type: 'primary' },
  writing_result: { label: '💾 写结果', type: 'info' },
  live_running: { label: '🟢 实盘运行中', type: 'success' },
  done: { label: '✅ 完成', type: 'success' },
  failed: { label: '❌ 失败', type: 'danger' },
}
const progressPhaseLabel = computed(() => {
  const phase = detail.value?.progress?.phase
  return PHASE_LABELS[phase]?.label || phase || '⏳ 准备中'
})
const progressPhaseTagType = computed(() => {
  const phase = detail.value?.progress?.phase
  return PHASE_LABELS[phase]?.type || 'info'
})

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
    start: 'primary',
    sandbox_ok: 'success',
    sandbox_err: 'danger',
    on_init_start: 'primary',
    on_init_done: 'success',
    on_init_err: 'danger',
    bar: 'info',
    on_bar_err: 'danger',
    on_finish_start: 'primary',
    on_finish_done: 'success',
    on_finish_err: 'warning',
    done: 'success',
    empty_bars: 'warning',
  }[p] || 'primary'
}

function _blankCreate() {
  return {
    script_id: null,
    stock_code: '',
    description: '',
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
  // 左右分栏: 默认选中第一个任务 (刷新/删除后仍保留原选中, 否则回退第一个)
  if (tasks.value.length) {
    const keep = tasks.value.find(x => x.id === detail.value?.id) || tasks.value[0]
    openDetail(keep)
  } else {
    detail.value = null
  }
}

const filteredTasks = computed(() => tasks.value)

function scriptNameById(id) {
  const s = scripts.value.find(x => x.id === id)
  return s?.name || `#${id}`
}

function scriptDescById(id) {
  const s = scripts.value.find(x => x.id === id)
  return s?.description || ''
}

function _statusType(s) {
  return {
    created: 'info',
    pending: 'info',
    running: 'warning',
    done: 'success',
    stopped: 'primary',
    failed: 'danger',
  }[s] || 'primary'
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
    STOP: 'primary',
    TP: 'primary',
    ERROR: 'danger',
  }[t] || 'primary'
}

// 提取后端错误信息: FastAPI 返回 {detail: {code, msg}} 或 {detail: '字符串'}
function _errMsg(e, fallback = '未知错误') {
  const d = e?.response?.data?.detail
  return (typeof d === 'string' ? d : d?.msg) || e?.message || fallback
}

// ─────────────── 详情 ───────────────
async function openDetail(row) {
  if (!row) return
  _disposeChart()  // 切换任务时释放旧图表 (chartRef 节点可能已卸载, 防止 setOption 到销毁实例)
  detail.value = row
  await nextTick()
  renderChart()
  await loadSignals()
  if (row.status === 'running') _startProgressPoll()
  else _stopProgressPoll()
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

async function loadDetail(taskId) {
  try {
    const t = await scriptStrategyApi.getTask(taskId)
    if (t) {
      detail.value = t
      await nextTick()
      renderChart()
      await loadSignals()
      if (t.status === 'running') _startProgressPoll()
      else _stopProgressPoll()
    }
  } catch (e) {
    // ignored
  }
}

function _disposeChart() {
  if (chart) {
    chart.dispose()
    chart = null
  }
}

function renderChart() {
  if (!chartRef.value || !detail.value?.backtest_result?.best?.equity_curve) return
  const best = detail.value.backtest_result.best
  const eq = best.equity_curve
  // v91.4: 双轴叠加 — 左轴权益曲线, 右轴价格, 买卖点 marker
  const trades = best.trades || []
  const tradeBuyData = []  // {stime, value} 上三角
  const tradeSellData = []  // 下三角
  for (const t of trades) {
    const point = { name: t.stime, value: [t.stime, t.price] }
    if (t.side === 'BUY') tradeBuyData.push(point)
    else if (t.side === 'SELL') tradeSellData.push(point)
  }
  // close 序列 (如有 bars, 从 progress_log 取; 没就用 equity 数据本身)
  const closeSeries = (best.progress_log || []).map(p => ({ stime: p.stime, value: p.close }))

  if (!chart) chart = echarts.init(chartRef.value)
  chart.setOption({
    legend: { top: 0, left: 'center', data: ['权益', '收盘价', 'BUY', 'SELL'] },
    grid: { left: 60, right: 60, top: 40, bottom: 60 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 20, bottom: 20 }],
    xAxis: { type: 'category', data: eq.map(e => e.stime), splitLine: { show: false } },
    yAxis: [
      { type: 'value', name: '权益', position: 'left', scale: true },
      { type: 'value', name: '价格', position: 'right', scale: true, splitLine: { show: false } },
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params) => {
        const lines = params.map(p => {
          let line = p.marker + p.seriesName + ': ' + (p.value[1]?.toFixed?.(2) || p.value[1])
          if (p.seriesName === 'BUY' || p.seriesName === 'SELL') {
            line += ' (' + (p.data.side || '') + ')'
          }
          return line
        })
        return lines.join('<br/>')
      },
    },
    series: [
      { name: '权益', data: eq.map(e => e.equity), type: 'line', smooth: true, yAxisIndex: 0, areaStyle: { opacity: 0.15 } },
      ...(closeSeries.length ? [{ name: '收盘价', data: closeSeries, type: 'line', yAxisIndex: 1, showSymbol: false, lineStyle: { type: 'dashed', width: 1, opacity: 0.5 } }] : []),
      { name: 'BUY', data: tradeBuyData, type: 'scatter', yAxisIndex: 1, symbol: 'triangle', symbolSize: 12, itemStyle: { color: '#67c23a' } },
      { name: 'SELL', data: tradeSellData, type: 'scatter', yAxisIndex: 1, symbol: 'triangle', symbolRotate: 180, symbolSize: 12, itemStyle: { color: '#f56c6c' } },
    ],
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
    createForm.value.script_id = String(route.query.script_id)
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
      description: createForm.value.description || '',
      params: createForm.value.params,
      period: createForm.value.period,
    }
    if (createForm.value.dateRange) {
      payload.backtest_start_date = createForm.value.dateRange[0]
      payload.backtest_end_date = createForm.value.dateRange[1]
    }
    await scriptStrategyApi.createTask(payload)
    ElMessage.success('策略已创建 (status=created), 请点击启动按钮触发')
    createOpen.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error('创建策略失败: ' + _errMsg(e))
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
    mode: row.mode || 'backtest',  // 模式来自表格切换按钮
    dateRange: row.backtest_start_date && row.backtest_end_date
      ? [row.backtest_start_date, row.backtest_end_date]
      : null,
    period: row.period || '1d',
  }
  // v122+: 重置 sweep/live-picker 状态
  runTab.value = 'backtest'
  liveParamSource.value = 'default'
  livePickerParams.value = null
  sweepResult.value = null
  runOpen.value = true
}

// 表格内模式切换: 设置该任务下次运行的模式 (回测/实盘)
function onToggleMode(row, isLive) {
  row.mode = isLive ? 'live' : 'backtest'
  if (detail.value?.id === row.id) {
    detail.value = { ...detail.value, mode: row.mode }
  }
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
  } else if (runForm.value.mode === 'live') {
    // v122+: live 参数来源校验
    if (liveParamSource.value === 'picker' && !livePickerParams.value) {
      ElMessage.warning('请先从历史回测选择参数')
      return
    }
    if (liveParamSource.value === 'manual') {
      try {
        JSON.parse(liveManualParams.value || '{}')
      } catch (e) {
        ElMessage.warning('手动 JSON 格式错误')
        return
      }
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
      // v122+: live params (default 模式不传, 后端用 schema defaults)
      if (liveParamSource.value === 'picker') payload.params = livePickerParams.value
      else if (liveParamSource.value === 'manual') payload.params = JSON.parse(liveManualParams.value || '{}')
    }
    await scriptStrategyApi.runTask(runForm.value.id, payload)
    ElMessage.success('已启动')
    runOpen.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error('回测启动失败: ' + _errMsg(e))
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
    ElMessage.error('停止失败: ' + _errMsg(e))
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除策略 #${row.id}?`, '删除', { type: 'warning' })
  } catch { return }
  try {
    await scriptStrategyApi.deleteTask(row.id)
    ElMessage.success('已删除')
    await loadAll()
  } catch (e) {
    ElMessage.error('删除失败: ' + _errMsg(e))
  }
}

// ─────────────── v122+ sweep + live picker ───────────────
const sweepResult = ref(null)
const livePickerParams = ref(null)

const currentScriptSchema = computed(() => {
  const s = scripts.value.find((x) => x.id === runForm.value?.script_id)
  return s?.params_schema || []
})

async function onRunSweep(payload) {
  running.value = true
  try {
    const res = await scriptStrategyApi.runSweepTask(runForm.value.id, payload)
    sweepResult.value = res
    ElMessage.success(`扫描已启动, ${res.total_runs} 个组合`)
    runOpen.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error('扫描启动失败: ' + _errMsg(e))
  } finally {
    running.value = false
  }
}

function onPickerSelect(payload) {
  livePickerParams.value = payload.best_params || {}
  ElMessage.success(`已选 #${payload.task_id} 的最优参数`)
}

// ─────────────── mount ───────────────
onMounted(async () => {
  await loadAll()
  if (route.query.script_id) openCreate()
})


// v123: 运行中任务每 3s 轮询 getTask 刷新 progress/status + /signals (回测+实盘)
//       实时信号由 WS task_progress_update 推送 (signal_consumer 转发 MQ) 即时插入
let _runningPollTimer = null
const wsStore = useWsStore()  // v91.4: ws task 进度推送

function _stopProgressPoll() {
  if (_runningPollTimer) {
    clearTimeout(_runningPollTimer)
    _runningPollTimer = null
  }
}

function _startProgressPoll() {
  _stopProgressPoll()
  if (!detail.value?.id) return
  _runningPollTimer = setTimeout(async () => {
    try {
      const t = await scriptStrategyApi.getTask(detail.value.id)
      if (t) {
        detail.value = {
          ...detail.value,
          status: t.status || detail.value.status,
          progress: t.progress || detail.value.progress,
          pnl: t.pnl ?? detail.value.pnl,
          trades_count: t.trades_count ?? detail.value.trades_count,
        }
        // 回测运行中 best.signal_log 未写, loadSignals 会清掉 WS 实时插入的信号 → 跳过
        // 实盘: 从 DB live_signals 兜底刷新 (WS 广播为主, DB flush 兜底)
        if (detail.value?.mode === 'live') {
          await loadSignals()
        }
        if (t.status === 'done' || t.status === 'failed' || t.status === 'stopped') {
          loadDetail(detail.value.id)
          _stopProgressPoll()
          return
        }
      }
    } catch (e) { /* 轮询失败静默, 继续下一轮 */ }
    _startProgressPoll()
  }, 3000)
}

// v91.4 + v123: ws 实时进度/信号推送 (signal_consumer 转发 MQ 信号 → task_progress_update 频道)
watch(() => wsStore.lastTaskProgress, (msg) => {
  if (!msg || !detail.value) return
  if (msg.task_id !== detail.value.id) return
  // 实时信号 → 插入信号流顶部 (按 trace_id 去重, 前端立即可见触发信号)
  if (msg.signal) {
    const sig = msg.signal
    const arr = signalData.value.signals || []
    if (sig.trace_id && !arr.some(x => x.trace_id === sig.trace_id)) {
      signalData.value = {
        ...signalData.value,
        signals: [sig, ...arr].slice(0, 500),
        total_signals: (signalData.value.total_signals || 0) + 1,
      }
    }
  }
  // 进度 / 状态更新
  if (msg.status || msg.progress) {
    detail.value = {
      ...detail.value,
      status: msg.status || detail.value.status,
      progress: msg.progress || detail.value.progress,
    }
  }
  // 回测/实盘完成 → 拉一次完整结果 (图表 + best_params 等), 停轮询
  if (msg.status === 'done' || msg.status === 'failed' || msg.status === 'stopped') {
    _stopProgressPoll()
    loadDetail(detail.value.id)
  }
})

onBeforeUnmount(() => {
  _stopProgressPoll()
  _disposeChart()
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

/* 左右分栏: 左=任务表格, 右=详情 */
.st-split {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--space-3);
  align-items: stretch;
  overflow: hidden;
}
.st-body {
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  flex: 1 1 45%;
  min-width: 0;
  overflow: auto;
}
.st-side {
  flex: 1 1 55%;
  min-width: 460px;
  background: var(--bg-elevated);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  overflow: auto;
}
.st-side-empty {
  flex: 1 1 55%;
  min-width: 460px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.st-side-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--border-light);
}

.up { color: var(--color-up, #f56c6c); font-weight: 600; }
.down { color: var(--color-down, #67c23a); font-weight: 600; }
.st-script-name { font-weight: 500; }
.st-script-desc { color: var(--text-secondary); }
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

/* v91.1: 实时进度面板 */
.st-progress-panel {
  width: 100%;
}
.st-progress-detail {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
  font-size: 13px;
  color: var(--color-text-secondary);
}
.st-progress-msg {
  flex: 1;
  min-width: 200px;
  color: var(--color-text-primary);
}
.st-progress-meta {
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.st-progress-time {
  font-size: 12px;
  color: var(--color-text-tertiary);
  margin-left: auto;
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
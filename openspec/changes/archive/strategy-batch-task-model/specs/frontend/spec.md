# spec-delta: frontend — ScriptTask 批次/任务两段式 UI（v123）

> 配套 [proposal.md](../../proposal.md) / [design.md](../../design.md)。脚本策略前端逻辑主体在 `strategy/spec.md` REQ-STRAT-017，本 delta 补登前端能力级要求。

## ADDED Requirements

### REQ-FE-320: ScriptTask 批次/任务两段式 UI（v123）

ScriptTask.vue 由"任务列表 + 详情"升级为"**批次列表 → 批次内任务表格 → 行详情下钻**"三段：

- **批次列表**：按 `(strategy_id, batch_no)` 聚合展示（batch_no / 创建时间 / mode(回测/扫描/实盘) / task 数 / best），实盘批次带"实盘"徽章
- **任务表格**：选中批次后，表格**前几列 = 参数**（按脚本 `params_schema` 动态生成列，int/float 格式化数值、choice 显示值）、**后几列 = 回测结果**（pnl / 回撤 / 胜率 / 交易数 / 指标值）；每行可排序
- **行详情下钻**：点击某行，在表格下方展示该组参数的 backtest_result（权益曲线/信号/审计等）
- **扫描表单按类型渲染**：int/float → 起止 + 步长（默认带出 schema min/max/step，可手调）；choice → 逗号分隔值列表（可手调）；string → 固定值（不参与扫描）
- **单次回测表单**：展示全部参数（默认值= schema default）
- **实盘门禁**：启动实盘前校验 `strategy.best_params`；为空提示"请先回测生成最优参数"并阻止提交
- **订阅** ws `task_progress_update` 实时刷新批次内任务进度

#### Scenario: 批次表格动态参数列

- **WHEN** 脚本 schema 参数为 `fast(int) / slow(int) / entry(choice)`
- **THEN** 任务表格首三列 = `fast / slow / entry`（分别按数值/枚举格式化），后续列为结果字段

#### Scenario: 扫描表单按类型渲染

- **WHEN** 进入参数扫描模式
- **THEN** `fast/slow` 显示起止+步长输入框；`entry` 显示逗号分隔值输入框；string 字段只读展示固定值

#### Scenario: 点击行下钻详情

- **WHEN** 用户在任务表格点击某一行
- **THEN** 表格下方区域展示该 task 的 backtest_result 图表 / 信号流 / 审计明细

#### Scenario: 实盘无 best 门禁提示

- **WHEN** 策略 `best_params` 为空时点"启动实盘"
- **THEN** UI 弹提示"请先回测生成最优参数"，不发起请求

#### Scenario: 实盘批次徽章

- **WHEN** 批次列表中存在 `mode='live'` 的批次
- **THEN** 该批次行显示"实盘"徽章，与回测/扫描批次视觉区分

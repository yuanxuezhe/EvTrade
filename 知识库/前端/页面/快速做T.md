# 快速做T（T0Trade）

## 对应代码路径
- `client/src/views/T0Trade.vue`（~55K 行，全前端最大页面）
- `client/src/composables/useT0*.js`（11 个组合函数）
- `client/src/lib/t0-calc.js`
- `client/src/stores/t0_tasks.js`、`api/t0_tasks.js`、`api/t0_stats.js`

## 功能概述
T0 日内回转交易工作台：T0 任务创建与管理、全局配比模式（百分比/股数）一键下单、实时配平（净成交差反向提示）、当日 T0 统计与图表、委托表内撤单。

## 文件清单
| 代码文件 | 作用 |
|----------|------|
| `T0Trade.vue` | 上下分区：上半任务表 + 全局配置行；下半委托表 + 实时配平 |
| `composables/useT0Balance.js` | 配平核心：diff = Σ买traded_volume − Σ卖traded_volume；>0 多买应 SELL，<0 应 BUY，=0 已平衡 |
| `composables/useT0OrderSubmit.js` | 配平下单提交（价格类型跟随做T配置，numeric） |
| `composables/useT0Quota.js` | 配额（次数/金额限制）读取与校验 |
| `composables/useT0Stats.js` / `useT0DayPnl.js` | T0 统计与当日盈亏 |
| `composables/useT0Keybindings.js` | 快捷键 |
| `composables/useT0TradeButtons.js` / `useT0ChartGeometry.js` | 交易按钮与图表几何 |
| `lib/t0-calc.js` | 配平算法（与后端 services/t0/core.py calc_t0_volume 呼应：买向下/卖向上取整） |
| `stores/t0_tasks.js` + `api/t0_tasks.js` | 任务 CRUD |

## 核心实现

### 全局配置行（v57/v109/v127）
- `globalMode: 'pct' | 'qty'` 互斥单选（ui store）
- pct 模式：globalPctInput 百分数（25 = 25%，计算 /100），基数取 holdings 实时持仓
- qty 模式：globalQtyInput 股数
- 数量计算：按 mode × 输入 + trade_unit 整手取整 + ≥ min_buy_qty
- 价格类型：PriceTypeInput numeric（默认市价 44）

### 任务表
- DataTableView 列定义（tableColumns.js）
- 默认选中第一条任务（change 2026-07-21-t0-default-select-first，修复配平 stock_code 为空 bug；后端 place.py 校验 task.stock_code == req.stock_code）
- 配平按钮文案/diff 驱动 disabled（diff=0 禁用）

### 委托表（下半区）
- 实时按 task_id 过滤 `holdings.orders`，order_time desc
- v126 防御：排除 `strategy_type=2`（策略母/子单，由 StrategyOrder 展示）
- 撤单白名单：仅 已报(50)/部成(55)（v74/v91）
- 状态文案：utils/format.js STATUS_LABEL（v63 统一）

### TDZ 陷阱（v75 教训）
taskRows 必须在 watch 之前定义，否则 setup 抛 ReferenceError 整页白屏。

## 依赖关系
- 上游：t0_tasks store、holdings store（orders/positions 实时）、quote、ui store、sysconfig（做T配置/配额）
- 下游：无；后端对应 `知识库/后端服务/T0做T/`

## 修改指南
- 配平规则改动：前端 useT0Balance/t0-calc.js 与后端 services/t0/core.py 必须同步
- 测试：`tests/client/` 内 T0 相关用例 + `pytest server/tests/test_t0*.py`

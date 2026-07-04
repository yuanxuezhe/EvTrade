## ADDED Requirements

### Requirement: QuotePanel 按行情模板.png 重排版（卖盘纵栈 + 买盘纵栈 + 16 格 stats）

The system SHALL 让 `client/src/components/QuotePanel.vue` 渲染顺序与布局
对照 broker 终端 `行情模板.png` 重排：

- 头部：股票名 + 股票代码（其上方有"涨跌状态标识" -- 当前 v15 用 Symbol 按涨/跌/平显示 `▲`/`▼`/`▬`）, **r3**: 股票代码字号 18px + `font-weight: 600`
- 最新价 hero：大字号最新价 + 涨跌额 + 涨跌幅（涨红跌绿）, **r3**: hero 整行可点击带价
- ~~委比/委差 row~~ **(r3 移除)**
- 卖盘纵栈 5 行（档位 ↓ 价格 ↓ 量），顺序 `卖5` → `卖1`（卖5 在顶）
- ~~中间最新价浮标~~ **(r3 移除, hero 已显示最新价, 重复)**
- 买盘纵栈 5 行，顺序 `买1` → `买5`（买1 在顶）
- 16 格 stats grid（8 行 2 列，**label 在左 / 数值在右**），按顺序 **(r3 Row1 改)**：
  `[昨收, 开盘]`, `[涨跌, 最高]`, `[涨幅, 最低]`, `[振幅, 均价]`,
  `[现手, 金额]`, `[总手, 量比]`, `[涨停, 跌停]`, `[市值, 费率]`
- **r3 价格格全部可点**: hero + 卖/买 5×2 价 + stats 7 个价格格 (昨收/开盘/最高/最低/均价/涨停/跌停) 共 18 个 emit 点

数字不可计算 / 后端未提供时 MUST 显示 `—` 而不是隐藏 (布局稳定)。

#### Scenario: 头部标的与最新价 hero 渲染

- **WHEN** `OrderForm` 输入了有效 stock_code 且 quote ws push 已到
- **THEN** `QuotePanel.vue` 顶部 MUST 渲染 `名+码` (Symbol ▲/▼/▬ + 股票名 + 空格 + 股票代码)
- **AND** 股票代码 MUST 字号 18px + `font-weight: 600` (r3)
- **AND** 大最新价 + 涨跌额 + 涨跌幅 MUST 在同一行展示, 颜色按 `text-up` 涨红 / `text-down` 跌绿 / `text-flat` 平黑
- **AND** hero 整行 MUST 可点击带价 (r3): `@click="emitApply(lastPrice)"` + `is-clickable` 类 + `title="点击带入委托价"` + hover 态 `var(--bg-hover)`

#### Scenario: ~~委比/委差 row 计算并展示~~ — r3 移除

- **r3 状态**: 不再渲染。trader 反馈: 后端 5 档口径与全档口径有差异, 视觉冗余。`script setup` 中 `committeeDiff` / `committeeRatio` / `sumAskVol` / `sumBidVol` helper 已删除。

#### Scenario: 卖盘纵栈 5 行渲染

- **WHEN** quote ws push 含 askPrice[1..5]
- **THEN** MUST 渲染 5 行 sell, 顺序 `卖5` (顶) → `卖1` (底)
- **AND** 每行 MUST 含 `档位` (左) / `价格` (中) / `量` (右, 整数千分位)
- **AND** 缺档位时 MUST 显示 `—` (不塌陷行)

#### Scenario: 买盘纵栈 5 行渲染

- **WHEN** quote ws push 含 bidPrice[1..5]
- **THEN** MUST 渲染 5 行 buy, 顺序 `买1` (顶) → `买5` (底)
- **AND** 每行 MUST 含 `档位` / `价格` / `量`, 缺档位显示 `—`

#### Scenario: 16 格 stats grid 渲染

- **WHEN** `QuotePanel.vue` 渲染于正常数据状态
- **THEN** MUST 渲染 8 行 × 2 列 = 16 格 grid, label 左值右
- **AND** 字段 MUST 按顺序 **(r3 Row1 首格改)** `昨收 / 开盘 / 涨跌 / 最高 / 涨幅 / 最低 / 振幅 / 均价 / 现手 / 金额 / 总手 / 量比 / 涨停 / 跌停 / 市值 / 费率`
- **AND** 已计算的字段 MUST 填实:
  - `均价 = amount / volume` (除 0 显示 `—`) — **r3 可点击**
  - `振幅 = (high - low) / prevClose * 100%` (prevClose=0 显示 `—`)
  - `涨停 = prevClose * 1.10` (2 位小数) — **r3 可点击**
  - `跌停 = prevClose * 0.90` (2 位小数) — **r3 可点击**
  - `昨收` = `fields[PREV_CLOSE]` — **r3 可点击**
  - `开盘` = `fields[OPEN]` — **r3 可点击**
  - `最高` = `fields[HIGH]` — **r3 可点击**
  - `最低` = `fields[LOW]` — **r3 可点击**
- **AND** 未计算的字段 (`现手` / `量比` / `市值` / `费率`) MUST 显示 `—`

## MODIFIED Requirements

### Requirement: QuotePanel 单击价格带入 OrderForm 委托价（替代双击; r3 覆盖 18 个 cell）

The system SHALL 让 `client/src/components/QuotePanel.vue` 中

> **改前**（v15 之前）：卖盘/买盘 cell / 6 格 cell 用 `@dblclick="emitApply(...)"` 触发价格带入
> **改后**（v15）：改用 `@click="emitApply(...)"`，鼠标 hover 态有视觉提示 (cursor + bg color + title tooltip)
> **r3 扩展**：覆盖 18 个 price cell (hero 1 + 卖 5 + 买 5 + stats 7 = 18); 非价格的 cells (涨跌/涨幅/振幅/金额/总手/现手/量比/市值/费率) 保持静态

行为约束：
- 卖 1..卖 5 / 买 1..买 5 任一档位的"价格"列 MUST 单击即向父组件 `Trade.vue` emit `apply-price` 事件
- hero 大最新价 MUST 单击可带入 (r3)
- 7 个 stats 价格格 (`昨收 / 开盘 / 最高 / 最低 / 均价 / 涨停 / 跌停`) MUST 单击可带入 (r3)
- emit payload MUST 为数字 (Number 类型, 保留原始精度)
- 鼠标 hover 任一可点击 cell MUST 变更 background 至 `var(--bg-hover)` + `cursor: pointer` + `title="点击带入委托价"`
- 非价格格 (涨跌/涨幅/振幅/金额/总手/未计算字段) MUST NOT 触发 emit (无 cursor: pointer, 无 hover 态)

#### Scenario: 单击卖 1 价带入 OrderForm

- **WHEN** user 鼠标 hover 卖盘第 `卖1` 行价格列
- **THEN** background 变 `var(--bg-hover)` + cursor `pointer`
- **WHEN** user click 卖 1 价格 cell
- **THEN** MUST emit `apply-price` 事件, payload = `Number(askPrice[0])`
- **AND** Trade.vue 调用 `onApplyPrice` → `orderStore.setPrice(price)` → OrderForm `form.price` 更新

#### Scenario: 单击买 3 价带入 OrderForm

- **WHEN** user click 买 3 价格 cell
- **THEN** MUST emit `apply-price`, payload = `Number(bidPrice[2])`

#### Scenario: 单击 hero 最新价带入 OrderForm (r3)

- **WHEN** user 鼠标 hover hero 整行
- **THEN** background 变 `var(--bg-hover)` + cursor `pointer`
- **WHEN** user click hero (任意位置)
- **THEN** MUST emit `apply-price`, payload = `Number(lastPrice)`

#### Scenario: 单击 stats 昨收 / 开盘 / 最高 / 最低 / 均价 / 涨停 / 跌停 价带入 OrderForm (r3)

- **WHEN** user click stats grid 中 `昨收` / `开盘` / `最高` / `最低` / `均价` / `涨停` / `跌停` 任一 cell
- **THEN** MUST emit `apply-price`, payload 对应 `prevClose` / `open` / `high` / `low` / `avgPrice` / `limitUp` / `limitDown` 数字

#### Scenario: 缺档位时不可点击

- **WHEN** 卖/买某档缺价 (null / 0) 或 stats 价格格字段未提供 (null / 0)
- **THEN** 该 cell MUST NOT 渲染 `cursor: pointer` 且 click MUST NOT emit (内部 `emitApply` 已对 null/0 早返)

#### Scenario: 非价格格 (涨跌/涨幅/振幅/未支持) 不可点击

- **WHEN** user hover stats grid 中 `涨跌` / `涨幅` / `振幅` / `现手` / `量比` / `市值` / `费率` cell
- **THEN** MUST NOT 变更 background + MUST NOT 显示 `cursor: pointer`
- **AND** click MUST NOT emit

## REMOVED Requirements

### Requirement: QuotePanel 双击价格带入（v15 之前行为）

**Reason**：v15 改单击, 双击与单击并存会让用户困惑; 单击节奏更短, 符合 trader "看价 → 点 → 下单" 的快节奏。

**Migration**：
- 删 `client/src/components/QuotePanel.vue` 中所有 `@dblclick="emitApply(...)"` 的模板节点
- 改为 `@click="emitApply(...)"`, tooltip `title` 改为 "点击带入委托价"
- Trade.vue `@apply-price="onApplyPrice"` 监听器不变, emit 协议不变

### Requirement: QuotePanel 委比 / 委差 row 渲染（v15 首次实现）— r3 移除

**Reason**：trader 反馈: 1) 后端 5 档口径与全档口径不一致, 显示值易误导; 2) hero 已显最新价 + 涨跌/涨幅, 委比/委差视觉冗余。

**Migration**：
- 删 `<div class="qp-committee">` 模板块
- 删 `.qp-committee` CSS 块
- 删 `<script setup>` 中 `committeeDiff` / `committeeRatio` / `committeeDiffText` / `committeeRatioText` 4 个 computed + `sumAskVol` / `sumBidVol` 2 个 helper
- Trade.vue 不消费这两个字段, 无下游影响

### Requirement: QuotePanel 卖 1 / 买 1 中间最新价浮标（v15 首次实现）— r3 移除

**Reason**：hero 已显示最新价, 中间浮标重复; 且移除后视线直"卖压 → 买力", 更紧凑。

**Migration**：
- 删 `<div class="qp-mid">` 模板块
- 删 `.qp-mid` / `.qp-mid-label` / `.qp-mid-price` CSS 块
- 卖盘栈与买盘栈之间不留空 row, 直接堆叠

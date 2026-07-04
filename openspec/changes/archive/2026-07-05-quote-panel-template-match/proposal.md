## Why

`/trade` 右下 `client/src/components/QuotePanel.vue` 当前布局 (顶部最新价 hero + 6 格 grid + 3 列横排 5+5+1 档盘口) 与 trader 习惯的 `行情模板.png` (标题头 + 委比委差行 + 卖盘纵向 5 行置顶 + 最新价 + 买盘纵向 5 行置底 + 16 格 2 列 key-value) 不匹配, 视觉信息密度与配色对比也不同; 同时当前 `@dblclick` 双击带价要求 trader 视线双击精度, 与"鼠标点击价格即填入委托价"的下单节奏不同步。

## What Changes

- 改 `client/src/components/QuotePanel.vue` (layout + interaction):
  - 改单 layout: 头部标的 (名+码) → 大最新价 + 涨跌幅 → 委比/委差 row → **卖盘 5 行纵向栈** (sell 5..sell 1) → **买盘 5 行纵向栈** (buy 1..buy 5) → 16 格 2 列 stats (最新/开盘, 涨跌/最高, 涨幅/最低, 振幅/均价, 现手/金额, 总手/量比, 涨停/跌停, 市值/费率)
  - 改交互: `@dblclick` → `@click` (trader 单击价格即填入 OrderForm 委托价); 鼠标悬停态 (cursor + hover background) 提示可点击
  - 加 computeds: `committeeRatio` 委比 / `committeeDiff` 委差 / `avgPrice` 均价 / `amplitude` 振幅 / `limitUp` 涨停 / `limitDown` 跌停 (client-side 计算)
  - 不可计算字段 (现手 / 量比 / 市值 / 费率): 后端未提供, 显示 "—" + 占位 (后续如需可开新 change 接 broker 字段)
  - 卖盘/买盘背景色: 卖红浅底 (上涨中卖盘价仍属"卖出价"), 买绿/青浅底 (与 broker 终端风格一致), 跟模板配色一致
- **BREAKING**: 无 API/数据契约变化, QuotePanel emit `apply-price` 签名不变, 仅触发方式 `@dblclick` → `@click` (Trade.vue 已 `@apply-price="onApplyPrice"` 监听, 不动)

## Capabilities

### New Capabilities
(无)

### Modified Capabilities
- `quotes`: 在 frontend 视图侧 QuotePanel 重新设计 — 改 layout / 改 click-to-apply / 加 4 个 client-side 衍生指标 (委比/委差/均价/振幅/涨/跌停, 其中涨/跌停算半衍生)

## Impact

- 受影响文件:
  - `client/src/components/QuotePanel.vue` (template + script computed + scoped style; 全量重写, 不动 emit/props)
  - `client/src/stores/quote.js`: 可选扩展 `getField(code, idx)` helper (目前已有, 不动)
- 不影响 ws push / RPC 数据契约 (前端仅展示)
- 单元测试: 项目无 QuotePanel 单元测试 (UI 组件), 跑 `npm test -- --run` 仍 103 全过
- 验证: `cd client && npx vite build` 通过 + dev 启动后浏览器走 `/trade` 输入股票代码 → 行情渲染 + 单击任意档位价 → OrderForm 委托价被填

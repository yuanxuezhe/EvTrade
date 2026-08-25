# OrderForm 委托数量快捷按钮改为分数（2026-08-25）

## 为什么改

`client/src/components/OrderForm.vue` 当前委托数量快捷按钮是 **绝对股数** `[100, 500, 1000, 5000, 10000]`，硬编码 5 个固定值：

- **与可用不联动**：用户切到另一只高价股（如 1680 元的茅台）或大持仓（如 10 万股）后，按钮失去参考价值
- **买卖不对称**：卖出时 5 个固定股数可能超过持仓（被吃掉）或不够；买入时可能超过资金上限
- **跨股失效**：不同股 trade_unit 不一定是 100（A 股 ETF 部分是 1 / 10 / 1000），硬编码 100 对其他品种不准确

## 目标

把快捷按钮改为 **可用数量的分数**：`[1/10, 1/5, 1/4, 1/2, 1/1]`：

- 按钮文案显示分数（如 `1/2`）+ tooltip / aria-label 显示对应股数
- 买入（order_type=23）：available = cash / price（按价格类型分 FIX/LATEST/MARKET_PEER），× fraction → 整手取整（向下 floor）
- 卖出（order_type=24）：available = 持仓 avl_vol，× fraction → 整手取整（向上 ceil，不超 avl_vol）
- 整手按 `Stocks.trade_unit`（cache miss 兜底 100）

## 影响面

- `client/src/components/OrderForm.vue` — 替换 `volumeShortcuts` + 加 `applyFraction(fraction)` + `availableTradeQty` computed
- `client/src/stores/stocks.js` — 加 `stockTradeUnit(code)` helper（与 `stockScale` / `stockStktype` 同签名风格）
- `tests/client/components/OrderForm.test.js`（新增）— 5 分数 × 2 方向 = 10 case

## 不变项

- 不改 API 端点 / store 接口 / OrderForm 其他字段（标的、价格、价格类型）
- 不改 `applyAvailableToVolume`（双击可交易数量仍带全额）
- 不改 `form.volume` 的默认值（100）与 `:min="100"` `:step="100"`（最低限仍是 100 股 = 1 手；分数按 trade_unit 时若 trade_unit > 100 由 `:min` 兜底）
- 不动 T0Trade / StrategyOrder 页面

## v6 commit 计划（4 个 commit）

1. `feat(stocks): 加 stockTradeUnit(code) helper`
2. `feat(orderform): 委托数量快捷按钮改分数 1/10~1/1 + trade_unit 整手`
3. `test(orderform): 5 分数 × 2 方向 = 10 case 单测`
4. `docs(openspec): 同步 知识库 + 合并 spec delta + 归档`

## KB 同步

- `知识库/前端/页面/交易下单.md` — OrderForm 章节改写快捷按钮描述
- `知识库/前端/状态管理/股票与基础信息.md`（如不存在则不动）— `stockTradeUnit` 加进 stores 字典
- `openspec/specs/frontend/spec.md` — 新增 REQ-FE-543（分数快捷按钮）+ REQ-FE-544（stockTradeUnit helper）
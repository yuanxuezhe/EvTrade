### REQ-FE-HOLDINGS-DBLCLICK: 持仓行双击带入下单面板（v53）

**语境**

Trade 页面是交易员高频入口。持仓表（HoldingsPanel）展示在右栏，下单
面板（OrderForm）在左栏（v32 2x2 四宫格布局）。已有的 quickStock
prop 通路（OrderForm `defaultStockCode` + Trade.vue `quickStock` ref
+ `@update:stock-code`）支持 StockCodePicker 选股后代码自动同步到
OrderForm。

**需求**

- HoldingsPanel 的 el-table 行支持 dblclick 交互
- 双击持仓行 → 把该行的 `stock_code` 通过 `apply-to-order` 事件传给
  Trade.vue
- Trade.vue 监听 `apply-to-order` → 写入既有 `quickStock` ref → OrderForm
  自动更新代码输入框
- 触发成功反馈（ElMessage.info），告知用户"已带入 xxx 到下单面板"
- 行视觉提示：`cursor: pointer` + hover 背景高亮，明示可双击

#### Scenario: 双击持仓行 → 代码带到下单面板

- Given user 在 `/trade` 页面，HoldingsPanel 至少有一条持仓
  （如 000001.SZ 19,600 股）
- When user 双击该持仓行
- Then HoldingsPanel 触发 `apply-to-order` 事件，payload 含
  `{ stock_code: '000001.SZ' }`
- And Trade.vue 写入 `quickStock.value = '000001.SZ'`
- And OrderForm 的代码输入框显示 "000001.SZ"
- And ElMessage.info 提示"已带入 000001.SZ 到下单面板"

#### Scenario: 双击新行 → 覆盖当前已选代码

- Given user 已手动在 OrderForm 输入 159992.SZ（未通过 dblclick）
- When user 双击另一个持仓 600000.SH 行
- Then `quickStock` 从 159992.SZ 覆盖为 600000.SH
- And OrderForm 代码输入框显示新值（不会出现两值混合）

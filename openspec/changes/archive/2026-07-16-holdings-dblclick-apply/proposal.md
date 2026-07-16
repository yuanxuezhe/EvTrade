# Proposal: 持仓双击带入下单面板

**Why**

交易场景里高频操作是"先看在手头寸，再快速下单"。当前流程：
1. 持仓表找代码
2. 切到下单面板/输入框
3. 手动打字代码（容易拼错）
4. 提交下单

第 2/3 步机械又耗时。给持仓行加 **dblclick 触发** → 直接把 `stock_code` 写
入下单面板的代码输入框，省两步。

**What**

- `HoldingsPanel.vue` el-table 加 `@row-dblclick`，双击持仓行后
  `emit('apply-to-order', { stock_code })` 通知父组件
- 整行加视觉提示（cursor: pointer + 行 hover 高亮），明示"可双击带入"
- `Trade.vue` 监听事件 → 写入既有 `quickStock` ref（已绑定 OrderForm
  的 `defaultStockCode` prop，自动反映到代码输入框）
- 触发 `ElMessage.info("已带入 xxx 到下单面板")` 给用户轻量反馈

**影响面 / 风险**

- 改动小：只新增双击交互路径，原有"手动输入代码"流程保持不变
- 不动后端、不动 store 结构（既有的 quickStock prop 通路 v32 已就位）
- 双击 vs 单击：dblclick 比 click 安全（避免与"点开详情"语义冲突）
- 不切换买卖方向（保持用户当前 tab），不抢填数量（用户保留选择权）
- OpenSpec 增量，新 REQ-FE-HOLDINGS-DBLCLICK

**取舍说明**

- 不选 "dblclick 自动判定方向（B 方案）"：有持仓可能仍要"加仓买"，智能
  方向会误判
- 不选 "dblclick 同时填 vol（C 方案）"：用户改价/数量时数量被覆盖，反而
  麻烦
- A 方案（最简注入）最确定性：只做用户明确说要做的事

# REQ-FE-231: T0 task 一键配平切前端计算 + 复用下单接口

## 修改

新增需求。

## 新增 REQ

### REQ-FE-231: T0 task 一键配平——前端计算差值 + 下市价单

**系统 SHALL** 在 T0Trade 页面"快速做T"主表"配平"按钮按下时：

1. **差值计算（前端）**：从 `holdingsStore.orders.filter(o => o.task_id === task.id && status ∈ '已成交')` 拿出该 task 全部已成交订单，按方向求和
   - `buy_vol  = sum(order.volume for order in buy_orders)`
   - `sell_vol = sum(order.volume for order in sell_orders)`
   - `diff     = buy_vol - sell_vol`
2. **方向决定**：
   - `diff > 0` → 多买了，反向 = **SELL** (`order_type: '24'`)
   - `diff < 0` → 多卖了，反向 = **BUY** (`order_type: '23'`)
   - `diff === 0` → 已平衡，按钮 disabled
3. **下单**：复用 `useT0OrderSubmit.submitOrder`，参数：
   ```js
   {
     orderType: diff > 0 ? '24' : '23',  // 反向
     volume: Math.abs(diff),            // |diff|
     price: 0,                          // 市价
     taskId: task.id,
     priceType: 'market',               // priceTypeCode=44
     t0_coefficient: 1,                 // 默认配平系数
     user_def: 'T0-balance'             // 标签区别于普通 T0 委托
   }
   ```
4. **实时显示**：下半区委托表变化 → 实时更新差值 → 主表"配平"按钮文案刷新
5. **deletes**：原 `POST /api/t0-tasks/{id}/balance` 后端 endpoint + 前端 `t0TasksApi.balance` + `store.balanceTask` + `T0TaskDetail.onBalance` 全部删除

#### Scenario 1: 多买了，应反向卖
- **GIVEN** task 有 3 笔成交：买 100 / 买 200 / 卖 100 (已成交)
- **WHEN** 用户点"配平"按钮
- **THEN** 前端算 `diff = (100+200) - 100 = +200`，方向 = SELL，下市价卖 200 股

#### Scenario 2: 多卖了，应反向买
- **GIVEN** task 有 2 笔成交：卖 500 / 买 200 (已成交)
- **WHEN** 用户点"配平"按钮
- **THEN** 前端算 `diff = 200 - 500 = -300`，方向 = BUY，下市价买 300 股

#### Scenario 3: 已平衡，按钮 disabled
- **GIVEN** task 全部已成交订单买=卖 (e.g. 买 1000 / 卖 1000)
- **WHEN** 渲染主表
- **THEN** "配平"按钮 disabled，文案显示"已平衡"

#### Scenario 4: 实时刷新（推送）
- **GIVEN** task 当前 `diff = 0`，主表"配平"按钮 disabled
- **WHEN** 新一笔 `trd_cfm` 推送到达 → `holdings.applyTradePush` 写缓存
- **THEN** 自动触发 diff 重计算，按钮 enabled 并显示新的差值

#### Scenario 5: 后端 endpoint 404
- **GIVEN** 前端代码彻底删除 `balanceTask` / `balance()`
- **WHEN** 用户访问 T0Trade 不再发任何 `/balance` 请求
- **THEN** network tab 无 `POST /api/t0-tasks/{id}/balance` 调用记录

### REQ-FE-232 (关联)：T0Trade 主页面上下分区布局

**系统 SHALL** 把 T0Trade 主页布局改为上下两区：

1. **上半区**（flex 1）：现有 8 列 task 表
2. **下半区**（flex 1）：当前选中 task (`selectedTaskId`) 的实时委托表 —— 7 列
3. **联动**：上半 task 表行选中 (点击) / 或 el-select 选 task → 下半委托表自动 filter (`holdings.orders.filter(o => o.task_id === id)`)
4. **实时推送**：ws ord_cfm/trd_cfm 推送到达 → applyOrderPush/applyTradePush 守门 → orders ref 更新 → 下半表 Vue 自动响应
5. **空态**：未选中 task → 下半区显示"请先选中一个 T0 任务"

#### Scenario 1: 选中 task 后看到委托
- **GIVEN** 选中 `selectedTaskId=2`
- **WHEN** 渲染下半区
- **THEN** 显示 stock_code=task.stock_code 的所有委托（按 order_time desc 排序），7 列

#### Scenario 2: 新委托推送到达
- **GIVEN** 选中 task=2，下半区显示 2 笔委托
- **WHEN** 用户在 trade 面板下买单 100 股 @ 11 元，server 收 ord_cfm 推送
- **THEN** holdings.applyOrderPush 写缓存 → 下半表自动多一行

#### Scenario 3: 推送撤单/成交更新
- **GIVEN** 下半表显示有 1 笔已成交买单
- **WHEN** server 推 trd_cfm (status 51)
- **THEN** 下半表 status 列更新（51 → 绿色"已成交"），上半"配平"按钮实时算 diff 变化

## Why

- 用户明确："**去掉这个接口，一键配平按钮，计算委托方向数量后，调下单接口下市价单**"
- 现实：v18/v54 balance endpoint 实现的 净敞口配平 把"算"和"报"绑在一个 RPC，前端无实时性
- 重构后：推送即实时算，UI 即时反馈，UX 提升

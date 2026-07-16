# Tasks: T0 配平切换为前端计算 + 复用下单接口

## 1. 删除后端 `/balance` endpoint
- [ ] 1.1 删除 `server/api/t0_tasks.py` L336 `@router.post("/{task_id}/balance")` 整段（约 30 行）
- [ ] 1.2 删除 L12 注释里 "POST /api/t0-tasks/{id}/balance 一键配平" 行
- [ ] 1.3 确认 `from .services.t0.tasks import balance_task` 也不再被 import（如是则移除）
- [ ] 1.4 后端 grep "balanceTask\|/balance" 验证后端 0 调用

## 2. 清理前端 balanceTask 调用
- [ ] 2.1 删除 `client/src/api/t0_tasks.js` L101 `balance(taskId, dryRun)` 方法
- [ ] 2.2 删除 `client/src/stores/t0_tasks.js` L120 `balanceTask` 函数 + L159 export
- [ ] 2.3 删除 `client/src/components/trade/T0TaskDetail.vue` L175-181 `onBalance` 函数（按钮回调已绑 → 一并移除按钮）
- [ ] 2.4 改 `client/src/components/trade/T0TaskList.vue` L11 注释（移除 "store.balanceTask" 字样）
- [ ] 2.5 前端 grep "balanceTask\|\.balance\b" 验证前端 0 调用

## 3. T0Trade.vue 主页面：上下分区 + 委托表 + 配平按钮改造
- [ ] 3.1 **layout**：把现在 main 是单个 `<el-table>` 改为 `<div class="upper-area">` + `<div class="lower-area">` flex column 1:1
- [ ] 3.2 **下半区**：新增委托表 `<el-table :data="filteredTaskOrders" ...>` 7 列
  - 委托号 / 方向 / 价格 / 数量 / 状态 / 下单时间 / 备注
- [ ] 3.3 **委托过滤**：`const filteredTaskOrders = computed(() => holdingsStore.orders.filter(o => o.task_id === selectedTaskId.value).sort(by order_time desc))`
- [ ] 3.4 **委托状态格式化**：抄 v54 已有的 statusLabel/statusClass 辅助
- [ ] 3.5 **主表"配平"按钮改造**：
  - 计算 `computedRealTimeDiff` (当前 selectedTaskId 委托的实时买-卖差)
  - 按钮 `:disabled="diff === 0"` `:loading="balanceSubmitting"`
  - 按钮文案：`差 ${diff} 股，${diff > 0 ? '卖' : '买'}` (diff=0 → "无需配平")
- [ ] 3.6 **`onBalanceTask` 函数重写**：
  - 用 `trade volumes` 而非 order volumes（如 trd_status='51'）
  - 调 `useT0OrderSubmit.submitOrder({ orderType: diff > 0 ? '24' : '23', volume: |diff|, price: 0, taskId })`
  - `price_type='market'` (priceType ref 设默认)
  - `t0_coefficient: 1`（默认配平系数）
- [ ] 3.7 引入 `useT0OrderSubmit` composable（如尚未）
- [ ] 3.8 引入 `priceType` ref + `balanceCoeff` ref（默认 1）+ `submitting` ref
- [ ] 3.9 CSS：上半区 / 下半区 各自 fill height，无外层滚动条溢出问题（沿用 Trade panel 滚动条经验）

## 4. OpenSpec spec.md + 归档
- [ ] 4.1 在 `openspec/specs/frontend/spec.md` 追加 REQ-FE-231（T0 task 配平切前端计算）：
  - ## REQ-FE-231: 前端实时配平 + 复用下单
  - 3 个 scenario：① 委托买>卖 → 自动 sell ② 委托卖>买 → 自动 buy ③ diff=0 → 按钮 disable
- [ ] 4.2 `git add openspec/specs/frontend/spec.md`
- [ ] 4.3 `mkdir -p openspec/changes/archive/2026-07-16/t0-balance-frontend`
- [ ] 4.4 `git mv openspec/changes/2026-07-16-t0-balance-frontend/* openspec/changes/archive/2026-07-16/t0-balance-frontend/`
- [ ] 4.5 commit + push

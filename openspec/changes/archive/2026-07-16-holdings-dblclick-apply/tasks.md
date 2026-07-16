# Tasks: 持仓双击带入下单面板

## 1. HoldingsPanel dblclick 注入

- [ ] 1.1 `client/src/components/trade/HoldingsPanel.vue`: el-table
      加 `@row-dblclick="onRowDblclick(row)"`
- [ ] 1.2 script setup 加 handler + `defineEmits(['apply-to-order'])`;
      handler 取 row.stock_code，emit 给父组件
- [ ] 1.3 el-table 行加视觉提示: `row-class-name` / `:deep(...)` 改
      cursor: pointer + hover 背景色

## 2. Trade.vue 监听 apply-to-order

- [ ] 2.1 `client/src/views/Trade.vue` HoldingsPanel 加
      `@apply-to-order="onApplyHolding"` listener
- [ ] 2.2 onApplyHolding(payload): 把 payload.stock_code 写入既有
      `quickStock.value`（v32 已就位的 prop 通路），触发 OrderForm
      的 defaultStockCode 更新
- [ ] 2.3 触发 `ElMessage.info('已带入 xxx 到下单面板')` 反馈

## 3. 浏览器实测

- [ ] 3.1 登录 admin → 跳 `/trade` → 等持仓表加载
- [ ] 3.2 双击 000001.SZ 行（dblclick vs single click 区别）
- [ ] 3.3 验证 OrderForm 代码输入框内容 = 000001.SZ
- [ ] 3.4 vision 截图二次复检
- [ ] 3.5 覆盖路径: 手动输入 159992.SZ 后再双击 600000.SH 行，验证
      quickStock 被覆盖

## 4. OpenSpec 提交

- [ ] 4.1 spec-deltas/frontend.md 新增 REQ-FE-HOLDINGS-DBLCLICK +
      2 scenario
- [ ] 4.2 `openspec/specs/frontend/spec.md` 同步追加 REQ 行
- [ ] 4.3 git add + commit: `feat(ui): 持仓双击带入下单面板
      (REQ-FE-HOLDINGS-DBLCLICK)` + 归档 changeset
- [ ] 4.4 双 hash 验证 + push origin master

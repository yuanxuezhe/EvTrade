# Tasks: Phase-2 Architecture Split

## 1. 后端拆分
- [x] #4 t0_aggregate 拆 fees+pnl+aggregators (`t0_aggregate.py` 340→30 + 3 子模块)
- [x] #5 main.py 拆 lifecycle.seed + ws.endpoint (`main.py` 193→70 + 2 子模块)
- [x] #1 client.py 拆 transport+parsers+handlers (`client.py` 677→25 + 4 子模块)
- [x] #2 push_handlers 拆 order_status 共享 (`push_handlers.py` 378→80 + 4 子模块)
- [x] #3 orders.py 拆 _schemas+place+cancel+query (`orders.py` 482→facade + 4 子模块)

## 2. 前端拆分
- [x] #6 Users.vue 拆 dialogs + useUserActions (719→250 + 2 dialog + 1 composable)
- [x] #7 T0Trade.vue 拆 2 composables (1821→1704 + useT0ChartGeometry + useT0OrderSubmit)
- [x] #8 ws.js 拆 heartbeat + dispatch (347→47 + 2 子模块)
- [x] #11 constants/riskProfile.js + 4 档配置 (新建 4 档含 extreme)
- [x] #9 holdings.js 拆 log+helpers+market+push (566→324 facade + 4 纯工厂)

## 3. Openspec 同步
- [x] #12 auth REQ-AUTH-006..010 (扩)
- [x] rpc-protocol REQ-RPC-010/011 (扩)
- [x] push REQ-PUSH-010 (扩)
- [x] trading REQ-TRADE-008 (扩)
- [x] frontend REQ-FE-009.7/050/051 (扩)
- [x] 新建 ws-protocol REQ-WS-001..005
- [x] 新建 risk-management REQ-RISK-001..003

## 4. 验证
- [x] `npm run build` 全过（2280 modules transformed, no errors）
- [x] 后端 `python -c "from server.X import Y"` 0 错误
- [x] 21 view 已有 `useHoldingsStore()` import 0 破坏
- [x] `useWsStore` 已有 import 0 破坏
- [x] `git log --oneline -12` 顺序符合 plan

## 5. 提交
- [x] 12 commit 按序列提交 (10 refactor + 1 spec + 1 archive)

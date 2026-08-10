# Tasks — 日初初始化期间前端推送丢弃门

> 先 spec 后代码。每个 phase 一个 commit。

## 1 — 知识库

- [ ] 1.1 创建 change proposal（proposal.md）
- [ ] 1.2 spec-deltas：`push.md`（REQ-PUSH-043）+ `frontend.md`（REQ-FE-532）
- [ ] 1.3 主 spec 落地：`openspec/specs/push/spec.md` + `openspec/specs/frontend/spec.md`
- [ ] 1.4 commit: `docs(spec): 新增 REQ-PUSH-043 init_start/init_aborted 广播 + REQ-FE-532 initializing 推送丢弃门`

## 2 — 后端 init 生命周期广播

- [ ] 2.1 `server/api/admin/sys_status.py`：`init_trading_day` 加 init_start（do_reconcile 前）/ init_aborted（失败分支）广播，成功广播 refactor 到共享 helper
- [ ] 2.2 commit: `feat(sys-status): init 生命周期广播 init_start/init_aborted (init-push-gate)`

## 3 — 前端 initializing 丢弃门

- [ ] 3.1 `holdings.js`：新增 `initializing` ref
- [ ] 3.2 `ws_dispatch.js`：`_onSystemStatusChange` 三态处理 + pos/ord/trd 丢弃门 + 丢弃计数汇总日志
- [ ] 3.3 `SystemInit.vue`：`handleInit` finally 关 gate（兜底）
- [ ] 3.4 `holdings_bootstrap.js`：bootstrap/refreshAll finally 关 gate（防御）
- [ ] 3.5 commit: `feat(holdings): 系统初始化期间丢弃 pos/ord/trd 推送 (init-push-gate)`

## 4 — 验证

- [ ] 4.1 语法验证：py_compile sys_status.py + esbuild transform 前端 4 文件
- [ ] 4.2 逻辑模拟：node 模拟广播时序（init_start→洪峰丢弃→init_completed 一次汇总日志 / init_aborted 不切日 / quote 不受门影响）
- [ ] 4.3 浏览器/ws 实测：触发日初 → 初始化期间无 push 刷屏日志，完成后一条「丢弃 N 条」汇总

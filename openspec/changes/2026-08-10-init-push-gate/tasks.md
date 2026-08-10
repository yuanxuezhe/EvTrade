# Tasks — 日初初始化期间推送丢弃门（前端 gate + 后端抑制）

> 先 spec 后代码。每个 phase 一个 commit。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 spec-deltas：`push.md`（REQ-PUSH-043）+ `frontend.md`（REQ-FE-532）
- [x] 1.3 主 spec 落地：`openspec/specs/push/spec.md` + `openspec/specs/frontend/spec.md`
- [x] 1.4 commit: `docs(spec): 新增 REQ-PUSH-043 init_start/init_aborted 广播 + REQ-FE-532 initializing 推送丢弃门`

## 2 — 后端 init 生命周期广播

- [x] 2.1 `server/api/admin/sys_status.py`：`init_trading_day` 加 init_start（do_reconcile 前）/ init_aborted（失败分支）广播，成功广播 refactor 到共享 helper
- [x] 2.2 commit: `feat(sys-status): init 生命周期广播 init_start/init_aborted (init-push-gate)`

## 3 — 前端 initializing 丢弃门

- [x] 3.1 `holdings.js`：新增 `initializing` ref
- [x] 3.2 `ws_dispatch.js`：`_onSystemStatusChange` 三态处理 + pos/ord/trd 丢弃门 + 丢弃计数汇总日志
- [x] 3.3 `SystemInit.vue`：`handleInit` finally 关 gate（兜底）
- [x] 3.4 `holdings_bootstrap.js`：bootstrap/refreshAll finally 关 gate（防御）
- [x] 3.5 commit: `feat(holdings): 系统初始化期间丢弃 pos/ord/trd 推送 (init-push-gate)` `fde48af`

## 4 — 验证

- [x] 4.1 语法验证：py_compile sys_status.py + esbuild transform 前端 4 文件
- [x] 4.2 逻辑模拟：node 模拟广播时序（init_start→洪峰丢弃→init_completed 一次汇总日志 / init_aborted 不切日 / quote 不受门影响）— 19/19 通过
- [x] 4.3 ws/后端实测（admin token 触发 init）：`init_start`(status=initializing)→`init_completed`(ok, report_id=1786302664) 广播正常、`clients=1`，两广播间**无 pos_push/ord_cfm/trd_cfm 洪峰**（后端抑制生效）。前端 console「丢弃 N 条」汇总日志待浏览器确认

## 5 — 后端 init 期间抑制 pos_push（用户确认洪峰场景=日初 reconcile）

- [x] 5.1 spec 落地：REQ-PUSH-034 新增「init reconcile 期间抑制 pos_push」场景（已入 push/spec.md）
- [x] 5.2 `pos.py`：`_SUPPRESS_POS_PUSH` + `suppress_pos_push()` context manager + handler 入口短路
- [x] 5.3 `sys_status.py`：`with suppress_pos_push():` 包住 `do_reconcile(init)` 整段
- [x] 5.4 单测：新增 suppress 生效测试（suppress 期间 handler 返回 None，恢复后正常 diff）— 7/7 通过
- [x] 5.5 commit: `feat(push): init reconcile 期间抑制 pos_push 广播 (init-push-gate)` `1c3ad87`

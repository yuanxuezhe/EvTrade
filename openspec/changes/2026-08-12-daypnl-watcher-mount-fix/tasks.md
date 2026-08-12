# Tasks — 刷新后「当日盈亏」列恒为空修复

> 先知识库后代码。改动分 2 个 commit 便于 review/回滚。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 spec-deltas：`frontend.md` — REQ-FE-533 补「已登录刷新 → _startWatchers 必须启动」约定
- [x] 1.3 主 spec 落地：`openspec/specs/frontend/spec.md`
- [x] 1.4 commit: `docs(spec): REQ-FE-533 补已登录刷新启动 watcher + prev_close 推送约定`

## 2 — 根因修复：App.vue 已登录 mount 启动 watcher

- [x] 2.1 `App.vue` onMounted 补 `holdingsStore._startWatchers()`
  - [x] 2.1.1 幂等确认（`_startWatchers` 有 `if (_unwatch) return` 守卫）
- [x] 2.2 回归测试 `tests/client/components/App.test.js`（修复前红线 → 修复后绿）
- [x] 2.3 commit: `fix(app): 已登录刷新时 onMounted 启动 _startWatchers, 否则 day_pnl recompute 不跑 (daypnl-watcher-mount-fix)`

## 3 — prev_close 推送补全

- [x] 3.1 `ws_dispatch._onQuote` + `holdings_push.applyQuote` 转发 `snapshot`
- [x] 3.2 回归测试 `tests/client/stores/daypnl_livepush.test.js`（带 snapshot → day_pnl 非 null）
- [x] 3.3 commit: `fix(quote): live push 转发 snapshot(prev_close), 当日盈亏 calcDayPnl 不再 null`

## 4 — 验证

- [x] 4.1 `daypnl_livepush` + `App` 新测试全绿；holdings/orders 等 4 个预存失败文件与基线一致（无新 regression）

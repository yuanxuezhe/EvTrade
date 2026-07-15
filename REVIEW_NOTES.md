# REVIEW_NOTES — 2026-07-15-system-init-broadcast

## Review 时建议看的 5 个 commit（按顺序）
1. `a2d3c5f` feat(ws) — 单文件 +5 行，新增 ws 频道注册
2. `82f61c1` feat(api) — 单文件 +30 行，init handler 末尾插入 broadcast
3. `93734de` feat(client) — 2 文件 +40 行，前端路由 + 双保险
4. `43ba3b6` docs(spec) — 3 spec + 4 OpenSpec 工件
5. `0df0377` chore(archive) — 4 文件 rename（纯归档）

## Review Checklist

### Commit 1 (`a2d3c5f`)
- [ ] `server/ws/manager.py` 第 56-60 行：`"system_update": set()` + 注释
- [ ] 原 4 个频道（order/trade/quote/strategy）未动
- [ ] Python 导入验证 5 频道齐全

### Commit 2 (`82f61c1`)
- [ ] `server/api/admin/sys_status.py` 顶部：`from datetime import datetime, timezone` + `import asyncio`
- [ ] init_trading_day 函数内第 105-129 行：broadcast 块
- [ ] `ensure_future` 不阻塞 HTTP 响应
- [ ] try/except 包 ws_manager 异常
- [ ] payload 7 字段（type/trd_date/report_id/status/ts/channel/trace_id）
- [ ] status 二值：'ok' / 'partial'

### Commit 3 (`93734de`)
- [ ] `ws_dispatch.js`：
  - import 区 `useAssetStore` / `usePositionStore`
  - dispatchPayload 第 51 行：`else if (t === 'init_completed') _onInitCompleted(payload.data)`
  - 文件底部 `_onInitCompleted` 函数（refreshAll + fetchAsset + fetchPositions + try/catch）
- [ ] `SystemInit.vue`：
  - import 3 个 store
  - handleInit 成功分支追加 refresh 块
  - 不动原有 `ElMessage.success / loadCurrent / loadReports`

### Commit 4 (`43ba3b6`)
- [ ] `openspec/specs/system-init/spec.md`：REQ-INIT-003.1 + REQ-INIT-005
- [ ] `openspec/specs/push/spec.md`：REQ-PUSH-002 表格新增 system_update 行 + REQ-PUSH-006
- [ ] `openspec/specs/frontend/spec.md`：REQ-FE-INIT-001 + 3 scenario
- [ ] `openspec/changes/2026-07-15-system-init-broadcast/` 含 4 文件

### Commit 5 (`0df0377`)
- [ ] 4 文件 rename 100%（git 自动识别）
- [ ] 归档目录：`openspec/changes/archive/2026-07-15-system-init-broadcast/`

## 端到端验证（已通过）

```
HTTP POST /api/admin/sys-status/init trd_date=20260716
  ↓ < 1s
HTTP 200 {code:0, msg:"日初完成", report_id:1784077199, applied:true, ...}
  ↓
WS /ws/system_update 收到 init_completed payload
```

## 浏览器实测待补

- [ ] https://evtrade.ngx.evdata.top:50443/system-init 触发 init
- [ ] 持仓页/资金页是否自动更新（不点 AppHeader 刷新按钮）
- [ ] ws 断网 → handleInit 同步刷新兜底

## 回退命令

```bash
git revert 0df0377 43ba3b6 93734de 82f61c1 a2d3c5f
# 或选择性回退某层：
git revert a2d3c5f   # 仅回退 ws 频道注册
```

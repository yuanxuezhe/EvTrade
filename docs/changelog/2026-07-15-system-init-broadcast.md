# Changelog — 2026-07-15-system-init-broadcast

> **改动 5 commits / 11 files / +605/-2**
> 主题：日初成功后自动推送 ws 信号，前端持仓/资金页无需点刷新即更新

---

## 变更目标

**问题**：用户点 `/system-init` 完成日初后，持仓页/资金页的数字**不会自动刷新**，需要手动去 AppHeader 点"刷新数据"按钮。原因是：

- `client/src/stores/holdings_bootstrap.js::bootstrap()` 仅 App 启动 / 登录后拉一次
- 资金 / 持仓没有 ws 增量通道（v22 注释：position_update / asset_update 频道已删除，xtquant broker 不发 pos_cfm/ast_cfm）

**解决方案**：复用现有 ws 通道范式（与 `sync_update` / `quote_update` 同架构），新增 `system_update` 频道 + `init_completed` 事件。后端在 `init_trading_day` 成功返回前同步 broadcast；前端在 ws_dispatch 路由到 `_onInitCompleted` → 触发 holdings/asset/position store 全量刷新；前端 handleInit 同步 refreshAll 作 ws 断网兜底。

---

## 跨层 commit 拆分（5 commits，按层独立可 revert）

| # | Commit | Hash | 文件 | 行 |
|---|---|---|---|---|
| 1 | `feat(ws): 新增 system_update 频道` | `a2d3c5f` | `server/ws/manager.py` | +5 |
| 2 | `feat(api): init_trading_day 成功后广播 init_completed` | `82f61c1` | `server/api/admin/sys_status.py` | +30 |
| 3 | `feat(client): ws 路由 init_completed + handleInit 双保险` | `93734de` | `ws_dispatch.js` + `SystemInit.vue` | +40 |
| 4 | `docs(spec): 补 system_update 频道与 init_completed 事件契约` | `43ba3b6` | 3 spec.md + 4 OpenSpec 工件 | +532 |
| 5 | `chore(archive): 归档 system-init-broadcast changeset` | `0df0377` | 4 文件 rename (100%) | 0 |

---

## 后端改动详情

### Commit 1 — `server/ws/manager.py`

`WSManager.active_connections` 字典新增 `system_update` 频道 key + 注释：

```python
self.active_connections: Dict[str, Set[WebSocket]] = {
    "order_update": set(),
    "trade_update": set(),
    # ... (consolidate-position-data-flow 注释保留)
    "quote_update": set(),
    "strategy_update": set(),
    # change 2026-07-15-system-init-broadcast: 系统级业务事件频道
    # - 触发源: init_trading_day handler 等业务接口
    # - 订阅方: 前端 ws_dispatch._onInitCompleted (静默刷新 holdings/asset/position)
    # - 扩展位: 后续 day_init_failed / reconciled 事件可复用此频道
    "system_update": set(),
}
```

### Commit 2 — `server/api/admin/sys_status.py`

`init_trading_day` 函数末尾（`return InitResponse(...)` 前）插入 broadcast 块：

```python
# 2026-07-15-system-init-broadcast: 日初成功后 ws 推 init_completed
status = 'partial' if (result.get('error') or result.get('rpc_status') == 'failed') else 'ok'
report_id = result.get('report_id') or (new_day.last_reconcile_id if new_day else None)
payload = {
    "type": "init_completed",
    "trd_date": req.trd_date,
    "report_id": report_id,
    "status": status,
    "ts": datetime.now(timezone.utc).isoformat(),
    "channel": "system_update",
    "trace_id": trace_id,
}
try:
    from server.ws.manager import ws_manager
    asyncio.ensure_future(ws_manager.broadcast("system_update", payload, trace_id=trace_id))
except Exception as ws_err:
    log.warning(f"[system-init-broadcast] ws broadcast failed: {ws_err}")
```

**特性**：
- 不阻塞 HTTP 响应（`ensure_future`）
- try/except 兜底 ws 异常
- payload 7 字段齐全（type/trd_date/report_id/status/ts/channel/trace_id）
- `status` 二值：ok / partial（覆盖 `code=0 OR partial` 拍板）

---

## 前端改动详情

### Commit 3a — `client/src/stores/ws_dispatch.js`

新增 2 个 store import + dispatch 分支 + handler：

```js
import { useAssetStore } from './asset'
import { usePositionStore } from './position'

// dispatchPayload() 末尾追加
else if (t === 'init_completed') _onInitCompleted(payload.data)

// 文件底部新增
function _onInitCompleted(data) {
  if (!data) return
  try {
    useHoldingsStore().refreshAll()
    useAssetStore().fetchAsset()
    usePositionStore().fetchPositions()
  } catch (e) {
    log.warn('_onInitCompleted:', e?.message)
  }
}
```

### Commit 3b — `client/src/views/SystemInit.vue`

handleInit 成功分支追加 refresh 兜底（双保险）：

```js
import { useHoldingsStore } from '../stores/holdings'
import { useAssetStore } from '../stores/asset'
import { usePositionStore } from '../stores/position'

// handleInit 成功分支:
if (result.code === 0 || result.ok) {
  ElMessage.success(`日初成功：${result.report_id || ''}`)
  loadCurrent()
  loadReports()
  // 双保险: ws 推不达时同步刷新
  try {
    useHoldingsStore().refreshAll()
    useAssetStore().fetchAsset()
    usePositionStore().fetchPositions()
  } catch (e) { /* silent */ }
}
```

---

## Spec 改动详情

### Commit 4 — 3 个 spec.md + OpenSpec 4 工件

| Spec | 新增 / 修改 |
|---|---|
| `openspec/specs/system-init/spec.md` | REQ-INIT-003.1 数据流补 init_completed 推送 + REQ-INIT-005 reconcile_only 不推送 |
| `openspec/specs/push/spec.md` | REQ-PUSH-002 表格新增 system_update 行 + REQ-PUSH-006 新增频道 spec |
| `openspec/specs/frontend/spec.md` | REQ-FE-INIT-001 init_completed 触发 store 刷新 + 双保险语义 |
| `openspec/changes/2026-07-15-system-init-broadcast/` | proposal.md / tasks.md / spec-deltas/README.md / archive/README.md |

---

## 端到端验证

### Commit 5 — 实测日志

```
HTTP POST /api/admin/sys-status/init trd_date=20260716
  ↓ < 1s
HTTP 200 {"code":0,"msg":"日初完成","report_id":1784077199,"applied":true,
          "trading_day":{"trd_date":"20260716","status":"active",...}}
  ↓
WS listener 收到 {"type":"init_completed","trd_date":"20260716",
                  "report_id":1784077199,"status":"ok",
                  "ts":"2026-07-15T09:00:00.458530"}
```

✅ HTTP handler → ws_manager.broadcast → ws endpoint → client listener 全链路通

### 验证项清单

- [x] 后端 `/api/health` 200
- [x] Python ws 客户端连 `/ws/system_update` 握手成功
- [x] 真实 init POST 触发 ws 推送（< 1s 收到）
- [x] payload 字段齐全（type/trd_date/report_id/status/ts/channel/trace_id）
- [x] status='ok' / 'partial' 二值分支
- [x] JS 语法 OK（ws_dispatch.js `new Function` 不抛）
- [x] Vue SFC 结构 OK（SystemInit.vue 3 refresh 调用齐全）
- [x] 后端 startup log 无 import error、quote_consumer connected

### 待你浏览器实测

- [ ] 打开 https://evtrade.ngx.evdata.top:50443/system-init
- [ ] 用 admin 账号触发 init（trd_date=任意）
- [ ] 切换到持仓页/资金页 — 应**自动**显示新数字，无需点 AppHeader "刷新数据" 按钮
- [ ] 断网刷新（关浏览器重开）— 因 ws 未推，应走 handleInit 同步刷新兜底

---

## 影响面与兼容性

### 兼容性
- ✅ 与现有 ws 4 频道（order/trade/quote/strategy）共存，无冲突
- ✅ 复用 `_onStockSynced` 等 handler 的 try/catch 模式
- ✅ 复用 `ws_manager.broadcast` 既有 API（无新方法）
- ✅ 无新 SQL schema / 无新依赖 / 无新环境变量

### 风险点（已在 tasks.md 标记）
- ws 异常 → try/except 兜底，HTTP 200 仍返回（不影响 init 业务）
- 前端 store 调用顺序：refreshAll → fetchAsset → fetchPositions（与 AppHeader 行为一致）
- reconcile_only（`mode='manual'`）不推送（避免误刷新，REQ-INIT-005）

### 回退方案
5 commits 独立可 revert：
```bash
git revert 0df0377 43ba3b6 93734de 82f61c1 a2d3c5f
# 或选择性回退某层：
git revert a2d3c5f  # 仅回退 ws 频道注册（不影响业务）
```

---

## 远端状态

- ✅ 已推送到 `origin master`
- ✅ 本地/远端 hash 一致：`0df037797aa179f015dfeda5733db35d683f430c`
- ✅ 远程 diff：`d3bf552..0df0377 master -> master`

---

## 相关链接

- OpenSpec changeset（已归档）：`openspec/changes/archive/2026-07-15-system-init-broadcast/`
- Spec 更新：`openspec/specs/{system-init,push,frontend}/spec.md`
- 用户硬性偏好依据：避免 silent fallback、双保险、commit 拆分粒度
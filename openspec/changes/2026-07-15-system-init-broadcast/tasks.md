# Tasks — 2026-07-15-system-init-broadcast

> 拆细到 2–5 分钟一项，每完成一项立即按 8 字段模板汇报。
> 跨层 commit 拆分：5 个 commit，按"按层独立可 revert"原则。

---

## Commit 1 — `feat(ws): 新增 system_update 频道`

- [ ] 1.1. 读 `server/ws/manager.py` 第 47–56 行确认字典结构（已读）
- [ ] 1.2. 在 `active_connections` 字典里加 `"system_update": set()`，并加注释说明 v2026-07-15 init-completed 信号用途
- [ ] 1.3. **不重启进程**（仅改文件，下游 Python 热重载靠 `--reload` 或下次重启）
- [ ] 1.4. 跑 `python -c "from server.ws.manager import WSManager; m=WSManager(); print('channels:', sorted(m.active_connections.keys()))"` 验证导入 + 字典 key
- [ ] 1.5. 跑 `git diff --stat` 确认仅 1 文件改动
- [ ] 1.6. **Commit 1**：`git add server/ws/manager.py && git commit -m "feat(ws): 新增 system_update 频道（init 完成后推 init_completed）"`
- [ ] 1.7. **Commit 1 验证**：`git log -1 --format='%H%n%s'` 双确认 hash + 标题

---

## Commit 2 — `feat(api): init_trading_day 成功后广播 init_completed`

- [ ] 2.1. 读 `server/api/admin/sys_status.py` 第 74–118 行（`init_trading_day` 完整体）已读
- [ ] 2.2. 在文件顶部加 `import asyncio`（已有则跳过）
- [ ] 2.3. 在 `init_trading_day` 函数内，第 117 行 `return InitResponse(...)` **之前**插入广播块：
  ```python
  # 2026-07-15-system-init-broadcast: 日初成功后 ws 推 init_completed, 让前端自动刷新缓存
  # 不 await, ensure_future 调度, 与 services/push/dispatcher.py 范式一致
  if result.get('ok') and result.get('rpc_status', 'ok') != 'failed':
      from server.ws.manager import ws_manager
      asyncio.ensure_future(ws_manager.broadcast(
          'system_update',
          {
              'type': 'init_completed',
              'trd_date': req.trd_date,
              'report_id': result['report_id'],
              'status': result.get('rpc_status', 'ok'),  # 'ok' | 'partial'
              'ts': datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
          },
          trace_id=f"init:{req.trd_date}:{result['report_id']}",
      ))
  ```
  > 注意：`do_reconcile` 返回 dict 里**没有** `rpc_status` 字段，需在 reconcile.py 加 1 行把 `rpc_status` 写入 result（或在 sys_status.py 里直接判定 `result.get('applied')` / `result.get('error')`）。**采用后者**（最小改动）：`status = 'partial' if result.get('error') else 'ok'`。再议……
- [ ] 2.4. **拍板调整 2.3**：实际 payload `status` 字段语义 = `result['ok'] and (result['applied'] or not cfg.auto_reconcile) → 'ok'`，否则 'partial'。为避免业务耦合，**简化判定**：`status = 'partial' if result.get('error') else 'ok'`（error 为空 = ok）
- [ ] 2.5. 在函数体追加 `from datetime import datetime, timezone`（如有重复 import 跳过）
- [ ] 2.6. **不重启进程**（与 Commit 1 合并到一次后端重启验证）
- [ ] 2.7. 跑 `python -c "import ast; ast.parse(open('server/api/admin/sys_status.py').read()); print('syntax ok')"` 语法检查
- [ ] 2.8. 跑 `git diff server/api/admin/sys_status.py` 确认改动
- [ ] 2.9. **Commit 2**：`git add server/api/admin/sys_status.py && git commit -m "feat(api): init_trading_day 成功后广播 init_completed（system_update 频道）"`
- [ ] 2.10. **Commit 2 验证**：`git log -1 --format='%H%n%s'`

---

## Commit 3 — `feat(client): ws_dispatch 路由 init_completed → 刷新缓存 + handleInit 双保险`

- [ ] 3.1. 读 `client/src/stores/ws_dispatch.js` 第 1–50 行确认 dispatch 入口（已读）
- [ ] 3.2. 在文件顶部 import 区加 `import { useAssetStore } from './asset'` 与 `import { usePositionStore } from './position'`（确认两个文件存在）
- [ ] 3.3. 在 `dispatchPayload()` 第 49 行 `else if (t === 'stock_synced')` **之后**新增分支：
  ```js
  // 2026-07-15-system-init-broadcast: 收到 init_completed → 刷新持仓/资金缓存
  else if (t === 'init_completed') _onInitCompleted(payload.data)
  ```
- [ ] 3.4. 在文件下方（同 `_onStockSynced` 紧邻位置）新增函数：
  ```js
  function _onInitCompleted(data) {
    if (!data) return
    log.info('init_completed 收到:', data.trd_date, 'status=', data.status)
    try {
      const holdingsStore = useHoldingsStore()
      // 全量刷新（与 AppHeader handleRefresh 行为一致）
      holdingsStore.refreshAll()
      useAssetStore().fetchAsset()
      usePositionStore().fetchPositions()
    } catch (e) {
      log.warn('_onInitCompleted:', e?.message)
    }
  }
  ```
- [ ] 3.5. 读 `client/src/views/SystemInit.vue` 第 215–220 行 handleInit 成功分支（已读）
- [ ] 3.6. 在 handleInit 顶部 import 区加 `import { useHoldingsStore } from '../stores/holdings'`（确认 holdings store 路径）
- [ ] 3.7. 修改 handleInit 成功分支（`if (result.code === 0 || result.ok)`）为：
  ```js
  if (result.code === 0 || result.ok) {
    ElMessage.success(`日初成功：${result.report_id || ''}`)
    loadCurrent()
    loadReports()
    // 2026-07-15-system-init-broadcast: 双保险 — 即便 ws 没收到 init_completed 也能立即刷新
    try {
      const hs = useHoldingsStore()
      hs.refreshAll()
      useAssetStore().fetchAsset()
      usePositionStore().fetchPositions()
    } catch (e) { /* store 未就绪忽略 */ }
  }
  ```
- [ ] 3.8. 在 handleInit 顶部 import 区加 `import { useAssetStore } from '../stores/asset'` 与 `import { usePositionStore } from '../stores/position'`
- [ ] 3.9. **前端 dev server 自动热重载**（Vite HMR）— 无需手动
- [ ] 3.10. 跑 `cd client && npx vue-tsc --noEmit 2>&1 | head -20` 或 `cd client && npm run build` 验证前端构建
- [ ] 3.11. 跑 `git diff --stat client/` 确认改动文件清单
- [ ] 3.12. **Commit 3**：`git add client/src/stores/ws_dispatch.js client/src/views/SystemInit.vue && git commit -m "feat(client): ws 路由 init_completed + handleInit 双保险刷新"`
- [ ] 3.13. **Commit 3 验证**：`git log -1 --format='%H%n%s'`

---

## Commit 4 — `docs(spec): 补 system_update 频道与 init_completed 事件契约`

- [ ] 4.1. 读 `openspec/specs/system-init/spec.md` REQ-INIT-003 数据流段（已读）
- [ ] 4.2. 写 spec-deltas/system-init.md：
  ```md
  ## REQ-INIT-003 第 ~30 行（日初对账数据流）
  
  在 `WS 推 {channel: 'system_update', ...}` 后追加 spec：
  
  ### REQ-INIT-003.1: 日初成功后 ws 推 init_completed
  
  - **WHEN** `POST /api/admin/sys-status/init` 成功（即 `result.ok=True` 且 RPC 不全失败）
  - **THEN** 后端通过 `ws_manager.broadcast('system_update', ...)` 推送：
    ```json
    {"type":"init_completed","trd_date":"20260715","report_id":123,"status":"ok","ts":"..."}
    ```
  - **AND** 不阻塞 HTTP 响应（`asyncio.ensure_future` 调度）
  - **AND** payload `status` 字段 = `'ok'`（rpc_status ok）| `'partial'`（部分 RPC 失败但交易日切成功）
  
  #### Scenario: 全成功
  
  - **WHEN** 全部 RPC 成功（`rpc_status='ok'`）
  - **THEN** 推 `status='ok'`
  
  #### Scenario: 部分 RPC 失败但交易日切成功
  
  - **WHEN** `rpc_status='partial'`（部分失败 + 应用或仅报告）
  - **THEN** 仍推 `status='partial'`，前端仍刷新（用户需要知道部分数据缺失）
  
  #### Scenario: 仅生成报告（manual mode 不切日）
  
  - **WHEN** `POST /api/admin/sys-status/reconcile` 调用
  - **THEN** **不**推送 init_completed（持仓无变化，详见 REQ-INIT-005）
  ```
- [ ] 4.3. 写 spec-deltas/push.md：REQ-PUSH-002 表格新增 system_update 频道 → init_completed 事件
- [ ] 4.4. 写 spec-deltas/frontend.md：REQ-FE 新增 REQ-FE-INIT-001 描述前端路由
- [ ] 4.5. 跑 `git diff openspec/specs/` 确认所有 3 个 spec.md 已落
- [ ] 4.6. **Commit 4**：`git add openspec/specs/ && git commit -m "docs(spec): 补 system_update 频道与 init_completed 契约 (REQ-INIT-003.1, REQ-PUSH-002, REQ-FE-INIT-001)"`
- [ ] 4.7. **Commit 4 验证**：`git log -1 --format='%H%n%s'`

---

## Commit 5 — `chore(archive): 归档 changeset + 真实环境端到端验证**

- [ ] 5.1. **重启后端**：用 `python3 scripts/evctl.py restart backend` 或类似命令（拍板时刻用户确认）
- [ ] 5.2. 等 3 秒，跑 `curl http://localhost:8000/api/health` 确认后端 alive
- [ ] 5.3. **真实环境端到端**：
  - 浏览器登录 → 进 /system-init
  - 点"触发日初" → 等响应
  - **不应** 看到 ElMessage.success 后还要手动按 AppHeader 刷新按钮
  - 用 chrome devtools 看 WS 帧：filter `init_completed` 应有 1 帧
- [ ] 5.4. 跑 `browser_vision` 截图持仓页确认数字变化
- [ ] 5.5. 跑 `python3 scripts/evctl.py log backend --tail 50` 确认 `[front<-svc] ws broadcast channel=system_update` 日志
- [ ] 5.6. 跑 `git log --oneline -5` 确认 4 commit 已落地
- [ ] 5.7. 写 `openspec/changes/2026-07-15-system-init-broadcast/verify.md`（参照 verify-template）：
  ```
  ## Verify Result
  
  ### 环境
  - 后端 FastAPI :8000 alive
  - 前端 Vite :50998 alive
  - 用户角色 admin
  
  ### 端到端
  - ✅ /system-init 点"触发日初"
  - ✅ WS 帧 init_completed 1 帧 (status='ok')
  - ✅ AppHeader 刷新按钮**无需**点
  - ✅ 持仓页数字立即更新
  - ✅ handleInit 同步刷新 + ws 推送**双保险**生效
  
  ### 单元 / 集成
  - ✅ python -c ws_manager import ok
  - ✅ ast.parse sys_status.py ok
  - ✅ client build ok
  - ✅ 4 commit 已落 + working tree 干净
  ```
- [ ] 5.8. **归档**：`mv openspec/changes/2026-07-15-system-init-broadcast openspec/changes/archive/`
- [ ] 5.9. 更新 `openspec/tracking/`（按项目惯例，若有 active_changes.md 则追加归档条目）
- [ ] 5.10. **Commit 5**：`git add openspec/ && git commit -m "chore(archive): 归档 2026-07-15-system-init-broadcast + 端到端验证通过"`
- [ ] 5.11. **最终验证**：`git log --oneline -5` 与 working tree 干净
- [ ] 5.12. **回报用户**：5 commit hash + 验证截图 + 总结

---

## 暂停点（需用户拍板）

- **Pause #1**（在 5.1 之前）：是否允许重启后端服务？**默认建议是**，因为 Commit 1+2 改动需要后端重载。**若用户拒绝重启**：Commit 5.1 跳过，但功能需用户手动 `pkill -f "uvicorn server.main"` 后再启。

---

## 风险跟踪

- 后端未重启 → Commit 5.3 端到端会失败，必须拍板重启
- 跨日 init 同一 trd_date 多次推送 → refreshAll 内部幂等，无副作用
- WS 心跳断 → Q5 双保险兜底
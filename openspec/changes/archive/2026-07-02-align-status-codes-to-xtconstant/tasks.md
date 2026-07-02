## 1. 规范同步（commit 1）

- [x] 1.1 改 `openspec/changes/align-status-codes-to-xtconstant/proposal.md`（已完成, 提交 review）
- [x] 1.2 写 `openspec/changes/align-status-codes-to-xtconstant/design.md`（本次 change 内）
- [x] 1.3 写 `openspec/changes/align-status-codes-to-xtconstant/specs/data-model/spec.md`（MODIFIED orders.status 业务规则 + v11 业务规则补遗）
- [x] 1.4 写 `openspec/changes/align-status-codes-to-xtconstant/specs/push/spec.md`（MODIFIED REQ-PUSH-005 + REQ-PUSH-030 + REQ-PUSH-008 broker 字段映射补遗）
- [x] 1.5 写 `openspec/changes/align-status-codes-to-xtconstant/specs/frontend/spec.md`（MODIFIED REQ-FE-006 + REQ-FE-009.9/9.9.1 + REQ-FE-009.5 + REMOVED fall-back 兼容 key + ADDED 5 张字典按 broker 义重映射）
- [x] 1.6 写 `openspec/changes/align-status-codes-to-xtconstant/specs/rpc-protocol/spec.md`（MODIFIED REQ-RPC-004.1 + broker xtconstant status 字段重映射表）
- [x] 1.7 写 `openspec/changes/align-status-codes-to-xtconstant/specs/trading/spec.md`（MODIFIED REQ-TRADE-002 + REQ-TRADE-003 + REQ-TRADE-002.1 ord.py R2b）
- [x] 1.8 写 `openspec/changes/align-status-codes-to-xtconstant/tasks.md`（本次任务列表）
- [x] 1.9 commit: `docs(openspec): align-status-codes-to-xtconstant design+specs+tasks`

## 2. 后端核心 — order_status.py（commit 2）

- [x] 2.1 改 `server/services/order_status.py`：删 `class Status` 整个类（含 `_LABEL` 死代码 + 5 个英文常量 `PENDING_REPORT`/`REPORTED`/`PARTIAL`/`PARTIAL_CANCEL`/`FILLED`/`REJECTED`/`CANCELLED`/`PARTIAL_CANCEL2`/`PARTIAL_FILL_CANCEL`）
- [x] 2.2 改 `server/services/order_status.py`：把 `ORDER_STATUS` 改为 broker xtconstant 字典（11 条: 48-57 + 255）
- [x] 2.3 ⚠️ **实施偏差**：原计划 `TERMINAL_STATUSES = ('52','53','54','55','56','57')`. 实施改为 `('52','53','54','56','57')`（**不含 broker 55 = PART_SUCC 部成**）. 原因: broker 字典 55=部成 非终态, 仍可继续累计到 broker 56 已成. 包含 55 会导致 3 笔成交累计 100% 后被 sticky 在 55, 无法升到 56. 与 "broker 终态口径"原则一致: 真正终态 = {53, 54, 56, 57}, 含 broker 52 撤单过渡. 此偏差同步给前端 format.js TERMINAL_STATUSES.
- [x] 2.4 改 `server/services/order_status.py`：删 `is_cancellable` 触发码从 `('48','49')` 改为 `('48','49','50')`（含 broker 50=已报也可撤）
- [x] 2.5 改 `server/services/order_status.py:_infer_order_status`：
  - 终态判定改为 `('52','53','54','56','57')`（不含 55，参见 2.3 实施偏差）
  - 输出码全集改 broker 码: `49→50`（已报）, `50→55`（部成）, `51→56`（已成）, `53→54`（已撤）, `56→53`（部成部撤）
  - broker_status 撤单类判定: `('51','52','53','54')` 含 broker 51=已报待撤
- [x] 2.6 跑 `pytest tests/server/services/push/test_handlers.py` 现有 11 个 `_infer_order_status` 矩阵用例, 此时**断言仍用本地码应全部失败**（已确认失败, 预期）
- [x] 2.7 commit: `refactor(server): order_status.py 统一到 broker xtconstant 字典`

## 3. 后端业务写入点（commit 3）

- [x] 3.1 改 `server/api/orders/place.py:90` 拒单 status: `'55'` → `'57'`（broker JUNK 废单）
- [x] 3.2 改 `server/api/orders/place.py:110` RPC 成功 status: `'49'` → `'50'`（broker REPORTED 已报）
- [x] 3.3 改 `server/api/orders/place.py:113` RPC 拒单 status: `'55'` → `'57'`（broker JUNK 废单）
- [x] 3.4 改 `server/api/orders/cancel.py:61` pre-check: `if order.status not in ("48","49"):` → `("48","49","50")`（含 broker 50=已报）
- [x] 3.5 改 `server/api/orders/cancel.py:74` cancel-row 起手 status: `'48'` → `'48'`（保留 sentinel, 无变化）
- [x] 3.6 改 `server/api/orders/cancel.py:115` DELETE 成功 status: `'53'` → `'54'`（broker CANCELED 已撤）
- [x] 3.7 改 `server/api/orders/cancel.py:144` DELETE 失败 status: `'55'` → `'57'`（broker JUNK 废单）
- [x] 3.8 改 `server/services/push/ord.py:75` R2b 触发条件: `broker_status in ('53','55')` → `('52','53','54','55','56','57')`（broker 全部终态）
- [x] 3.9 改 `server/services/push/ord.py:85` rule 3 触发: `broker_status in ('52','53','54')` → `('51','52','53','54')`（broker 撤单类, 实现在 order_status.py:_infer_order_status）
- [x] 3.10 跑 `pytest tests/server/api/orders/test_cancel.py` / `test_place.py` / `test_query.py` / `test_t0_aggregate.py` ~50 处, 此时**断言仍用本地码应全部失败**（已确认失败, 预期）
- [x] 3.11 commit: `refactor(server): 业务写入点固定码 + 判定条件改 broker 码`

## 4. 前端（commit 4）

- [x] 4.1 改 `client/src/utils/format.js:STATUS_LABEL`：删 14 个英文 fall-back key, 改 broker 字典 11 条
- [x] 4.2 改 `client/src/utils/format.js:STATUS_TYPE`：按 broker 义重映射 (48→info, 49→info, 50→primary, 51→warning, 52→warning, 53→info, 54→info, 55→warning, 56→success, 57→danger, 255→info)
- [x] 4.3 改 `client/src/utils/format.js:STATUS_TONE`：按 broker 义重映射 (48/49→pending, 50→working, 51/52→working, 53→done, 54→terminal, 55→done, 56→done, 57→terminal, 255→pending)
- [x] 4.4 改 `client/src/utils/format.js:STATUS_ICON_NAME`：按 broker 义重映射 (48→Clock, 49→Clock, 50→Promotion, 51→Loading, 52→Loading, 53→WarningFilled, 54→CircleClose, 55→Loading, 56→CircleCheckFilled, 57→WarningFilled, 255→QuestionFilled)
- [x] 4.5 改 `client/src/utils/format.js:STATUS_PULSE`：按 broker 义重映射 (48/49/50/51/52/55→true, 53/54/56/57/255→false)
- [x] 4.6 改 `client/src/utils/format.js:STATUS_OPTIONS`：按 broker 字典顺序 48→未报 / 49→待报 / 50→已报 / 51→已报待撤 / 52→部成待撤 / 53→部成部撤 / 54→已撤 / 55→部成 / 56→已成 / 57→废单 / 255→未知
- [x] 4.7 ⚠️ **实施偏差**：`TERMINAL_STATUSES` 改为 `new Set(['52', '53', '54', '56', '57'])`（**不含 broker 55=部成**）, 与后端 2.3 偏差同步
- [x] 4.8 改 `client/src/utils/format.js:inferOrderStatus`：终态判定改 `Set(['52','53','54','56','57'])`, 输出码全集改 broker 码 (49→50, 50→55, 51→56, 53→54, 56→53), broker_status 撤单类判定 `['51','52','53','54']`
- [x] 4.9 `client/src/utils/orderCalc.js`：通过 `inferOrderStatus` 间接调用 format.js, broker 码输出已生效, 不需要独立改
- [x] 4.10 改 `client/src/stores/holdings_push.js`：v9 cancel-row 短路注释码同步 (`status='54'`/`'57'` 而非 `'53'`/`'55'`), 注释文案 broker 化
- [x] 4.11 跑 `vitest client/tests/utils/orderCalc.test.js` 32 个 status 断言, 此时**断言仍用本地码应全部失败**（确认 14 failed, 预期）
- [x] 4.12 跑 `vitest client/tests/stores/holdings.test.js` 5 个 status 集成断言, 此时**断言仍用本地码应全部失败**（确认 5 failed, 预期）
- [x] 4.13 ⚠️ **额外修复**：修 `client/src/utils/format.js:formatPercent` 模板字面量语法错误 `'+' ''` (缺冒号, 阻塞所有 vitest 解析)
- [x] 4.14 commit: `refactor(client): 5 张状态字典 + inferOrderStatus 改 broker 义`

## 5. 测试断言改码 + DB backfill 跟踪（commit 5）

### 5.1 Python 测试断言改码（~20 处, 较原计划 88 处少 — 部分 setup 值不动）

- [x] 5.1.1 改 `tests/server/services/push/test_handlers.py` `_infer_order_status` 矩阵 + handle_push 断言 (49→50, 50→55, 51→56, 53→54, 56→53)
- [x] 5.1.2 改 `tests/server/api/orders/test_cancel.py` status 断言 (DELETE 成功 '53'→'54', DELETE 失败 '55'→'57')
- [x] 5.1.3 改 `tests/server/api/orders/test_place.py` status 断言 (RPC 成功 '49'→'50', RPC 拒单 '55'→'57')
- [x] 5.1.4 `tests/server/api/orders/test_query.py` 全部 status setup '49'/'51', 无 assert 引用, 不改
- [x] 5.1.5 `tests/server/api/test_t0_aggregate.py` status='51'/status='55' 全为 setup, calc_net_exposure 按 trade 计算不读 order.status, 不改 (16/16 pass)
- [x] 5.1.6 跑 `pytest tests/server/services/push/test_handlers.py` 应**全部通过**（除已知的 1 个 pre-existing failure: `test_ord_cfm_for_original_does_not_touch_cancel_row` 与本 change 无关）— **32/33 pass ✓**
- [x] 5.1.7 跑 `pytest tests/server/api/orders/test_cancel.py` 应**全部通过**（除已知的 1 个 pre-existing failure: `test_cancel_calls_rpc_inserts_local_cancel_row` 与本 change 无关）— **9/10 pass ✓**
- [x] 5.1.8 跑 `pytest tests/server/api/orders/test_place.py` 应**全部通过**— **13/13 pass ✓**
- [x] 5.1.9 跑 `pytest tests/server/api/test_t0_aggregate.py` 应**全部通过**— **16/16 pass ✓**

### 5.2 JS 测试断言改码（~16 处 实改, 较原计划 52 处少 — vitest 5.2.3/5.2.4 共 92 个 status 断言中只命中特定 status 值）

- [x] 5.2.1 改 `client/tests/utils/orderCalc.test.js` 15 处 status 断言 (49→50/54/55/56, 50→55/56, 51→56, 53→54)
- [x] 5.2.2 改 `client/tests/stores/holdings.test.js` 5 处 status 断言 (49→50/54, 50→55, 51→56, 53→54)
- [x] 5.2.3 跑 `vitest client/tests/utils/orderCalc.test.js` 应**全部通过**— **32/32 pass ✓**
- [x] 5.2.4 跑 `vitest client/tests/stores/holdings.test.js` 应**全部通过**— **5/5 pass ✓**

### 5.3 双向交叉验证（防漏改）

- [x] 5.3.1 后端 grep 旧本地码 `'49'`/`'50'`/`'51'`/`'53'`/`'56'` 在测试文件中: 现在只剩 setup 值 (sentinel/terminal), 无断言残留
- [x] 5.3.2 前端 grep 视图层 status 硬编码: 0 处命中
- [x] 5.3.3 漏改 1 处都会跑挂（dev DB 行数有限, 跑 pytest + vitest 全过即可验证）— **vitest 92/92 + pytest 201/(201+10 pre-existing) 通过**

### 5.4 DB 历史 backfill（不在线执行）

- [ ] 5.4.1 跑 `scripts/dry_run_status_distribution.py` 评估 dev DB 需改行数（已跑过: dev 仅 1 行需改, cancel-row status=53 → 54）
- [ ] 5.4.2 写 `openspec/tracking/2026-XX-XX-status-backfill/proposal.md` 草案：
  - 6 条 SQL（53→54 cancel-row / 55→57 废单 / 51→56 已成 / 50→55 部成 / 49→50 已报 / 56→53 部成部撤）
  - 与 `tracking/2026-07-02-trades-amount-backfill` 一起组成维护窗口
  - backfill 前 db 备份, backfill 后 smoke test
- [ ] 5.4.3 **不在本 change 内执行 backfill SQL**（需用户确认 + 维护窗口）

### 5.5 部署检查（design R8 风险）

- [ ] 5.5.1 部署脚本强制 commit 3 + commit 4 必须同 release tag（`deploy.sh` / `Makefile` 加 pre-deploy 检查 `git log --grep`）
- [ ] 5.5.2 部署后 smoke test:
  - 推一条 ord_cfm, 前端 status 显示与新字典一致
  - 推一条 trd_cfm, 前端 store 累计 + 反向累计 status 推断输出 broker 码
  - 撤单 cancel-row status 显示 broker 码 (54/57)
- [ ] 5.5.3 提交 tracking issue `2026-XX-XX-status-backfill` 关闭（backfill 完成后）

## 6. 验证

- [x] 6.1 commit 2 验证: 跑 `pytest tests/server/services/push/test_handlers.py` 现有 11 用例, **预期失败** ✓
- [x] 6.2 commit 3 验证: 跑 `pytest tests/server/api/orders/test_*.py`, **预期失败** ✓
- [x] 6.3 commit 4 验证: 跑 `vitest client/tests/utils/orderCalc.test.js` + `client/tests/stores/holdings.test.js`, **预期失败** ✓
- [x] 6.4 commit 5 验证: 跑 `pytest tests/` 201 通过 + `vitest client/tests/` 92 通过（除 10 个已知 pre-existing failure）
- [ ] 6.5 端到端冒烟: dev 环境需用户手动跑, 验收标准:
  - 下单 + 撤单, 前端 holdings store 在 1 秒内呈现 cancel-row status='54'（broker 已撤）或 '57'（broker 废单）
  - trd_cfm 推送后 store 中对应 order 的 status 推断输出 broker 码 (50/55/56/53/54)
  - 不依赖 broker 全量 broadcast 兜底 (前端独立累计 + 推断)

## 备注

- **5 commit 拆分** 与 `feedback_commit_granularity` memory 一致, 单文件超大 diff 拆多 commit 便于 review / bisect / 回滚
- commit 1 之后, commit 2/3/4 可任意顺序 (后端 / 前端无运行时耦合), commit 5 收尾
- 部署时序: commit 1-4 部署后, **DB backfill 必须同窗口跑完**, 否则前端字典 broker 码 vs DB 本地码不一致 → 视图层显示错位
- 风险点详见 `design.md` Risks / Trade-offs 段 (R1-R8)

## 实施偏差汇总

1. **TERMINAL_STATUSES 不含 broker 55**: 见 task 2.3 / 4.7. broker 字典 55=PART_SUCC 部成非终态, 严格 broker 终态 = {53, 54, 56, 57}, 含 broker 52 撤单过渡. 含 55 会导致 3 笔成交累计 100% 被 sticky 在 55, 无法升到 broker 56. **设计意图保留**: "broker 终态口径一致" 通过删 55 更准确实现.
2. **`formatPercent` 模板字面量 bug**: 见 task 4.13. `'+' ''` 缺冒号阻塞所有 vitest 解析. 改为 `'+' : ''`. 此 bug 与 v11 对齐无关, 应该是上次 format.js 重写时遗留, 顺手修了.
3. **测试断言改动数量低于原计划**:
   - Python: 原计划 88 处, 实际改 ~20 处. 部分 "断言" 实际是 setup 值（sentinel `status='49'`/`'50'` 是合法的非终态 broker 码, 不必改）
   - JS: 原计划 52 处, 实际改 ~16 处. 同理 setup 值不动, 只改 expect() 断言值.
   - **判断标准**: 只改 `expect(...).toBe('XX')` / `assert ... == 'XX'` 类断言, 不改 setup/const 字段值 (除非语义冲突, 比如 cancel-row 实际写 broker 54/57, 测试 setup 写 '53'/'55' 才需要同步).
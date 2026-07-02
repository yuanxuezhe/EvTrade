# design — align status codes to broker xtconstant

## Context

委托 `status` 字段当前有 3 套互相冲突的字典（见 `proposal.md` Why 段）：
- `Status._LABEL` (broker 原始码残留, 死代码, 0 处 `Status.label()` 调用)
- `ORDER_STATUS` (legacy 模块级, `_status_msg` 用)
- `client/src/utils/format.js:STATUS_LABEL` (前端, 与 #2 错位)

业务写入点 (place.py / cancel.py / ord.py) 用的是第 2 套"本地推断"码 (53=已撤 / 55=废单 / 56=部成部撤), 与 broker xtconstant 字典 (54=已撤 / 57=废单 / 53=部成部撤) **数字空间错位**. 跟 broker 协议对不齐, 跨系统对账时本地要翻译一次.

`_infer_order_status` 函数产出一套本地码 (49/50/51/53/56), 跟 broker 字典不一一对应, 但 spec/注释没把"broker 码 → 本地码"重映射关系写出来. 读者看到 51 不知道是 broker "已报待撤" 还是本地 "已成".

本次 change 把全栈 status 字典统一到 broker xtconstant 权威字典 (10 条: 48-57 + 255).

详细动机 / 影响面 / 数据影响见 `proposal.md`. 本 design 聚焦**技术决策**与**实施细节**.

## Goals / Non-Goals

**Goals:**
- 1:1 对齐 broker xtconstant 字典 (无本地扩展; broker 53=部成部撤 直接吃掉本地 56, 不留本地 56)
- 业务写入点 + `_infer_order_status` 输出码 + 前端 5 张字典 + 5 张状态映射字典 全部统一
- 历史 DB 数据 backfill 一次到位 (6 条 SQL, dev 数据仅 1 行)
- 140 处测试断言改码, 测试契约不动 (只换数值)
- 5 commit 拆分, 每 commit 独立可测可回滚 (与 `feedback_commit_granularity` memory 一致)

**Non-Goals:**
- ❌ 不引入 1 步 UPSERT 重写 push handler (那是 v8 已做的事, 本 change 不动)
- ❌ 不改 ws 推送协议字段名 / OrderOut Pydantic 形状
- ❌ 不改 DB schema (status 字段类型不变)
- ❌ 不动视图层 (Holdings.vue / Trade.vue / Orders.vue 只读 status 字段)
- ❌ 不做历史 trades.amount 与 status 联合 backfill (trades.amount 那个 backfill 在 tracking issue `2026-07-02-trades-amount-backfill` 跟踪, 本 change 只跟它一起跑窗口, 不改 SQL)
- ❌ 不实现 status 自动转换/兼容层 (硬切换; ws v8 已带守门, push/UI 端有防御性重算)

## Decisions

### D1: 字典源头选 broker xtconstant, 无本地扩展

**决策**: `ORDER_STATUS` / `TERMINAL_STATUSES` / `_infer_order_status` 输出码全集 / 前端 5 张字典 全部按 broker xtconstant (10 条) 对齐. 本地 56 (部成部撤) → broker 53, **不**保留本地 56.

**为什么**:
- broker 字典是 1:1, 跨系统对账时无需翻译
- "本地 56"是历史 v8 引入的本地扩展, 当时 broker xtconstant 没暴露 PART_CANCEL; 后来 xtconstant 暴露了 (53), 但本地没跟上

**否决方案**:
- (a) 保留本地 56 + 翻译表 → 多 1 张翻译表 + 多 1 处错位风险; 否决
- (b) broker 字典 + 1 个本地扩展 (56 = 部成部撤 留 broker 已弃用) → 跨系统对账还要翻译; 否决

### D2: Status 类下沉到模块级, 删 `Status` 命名空间

**决策**: 删 `class Status` (含 `_LABEL` 死代码 + 5 个英文常量 `PENDING_REPORT` / `REPORTED` / `PARTIAL` / `PARTIAL_CANCEL` / `FILLED` / `REJECTED` / `CANCELLED` / `PARTIAL_CANCEL2` / `PARTIAL_FILL_CANCEL`). 把 `ORDER_STATUS` / `TERMINAL_STATUSES` / `is_cancellable` 沉到模块级函数.

**为什么**:
- `_LABEL` 字典里 "51→已撤 / 52→已成交" 与 `ORDER_STATUS` "51→已成 / 52→部撤" 互相对不上, 是历史上 2 套不同语义; 删了省得新读者误解
- `Status.PARTIAL_CANCEL = "51"` 标签是 "已成" 但值是 "51", 而 broker "51" 实际是 "已报待撤" — 0 处引用 + 概念错位 = 删
- 静态扫 `Status.label()` / `Status.PARTIAL_CANCEL` 等: 0 处调用, 0 处引用

**否决方案**:
- (a) 保留 Status 类做 namespace → 没价值, 函数/常量 module-level 即可; 否决

### D3: `TERMINAL_STATUSES = ('52','53','54','55','56','57')` 含 broker 52 (部成待撤)

**决策**: TERMINAL_STATUSES 含 52 (broker 部成待撤), 与 broker 终态口径一致.

**为什么**:
- broker 52 是"部成待撤" (有部分成交, 正在等待撤单). 业务上属于过渡态
- `_infer_order_status` 输出码只产 50/53/54/55/56, 不产 52; 但 broker `ord_cfm` 推回 52 时 (cancel 链路中) 不能让它被覆盖
- 含 52 = 与 broker 字典口径一致, 防御性

**否决方案**:
- (a) 严格只含本地产出码 `('53','54','55','56','57')` → broker 推回 52 时被 trd_cfm 累计覆盖 (误判回 50/51); 否决

### D4: cancel-row 起手 sentinel 保留 `"48"`

**决策**: `cancel.py:74` 写入 cancel-row 起手 `status="48"` (本地私有 sentinel=未报), 不改成 `"49"` (broker 待报).

**为什么**:
- 48 vs 49 对 broker 都不关心 (broker 不会推 cancel-row, 仅前端 holdings 显示; DELETE 端点立刻覆盖到 53/55)
- sentinel 语义本地私有, 跟 xtconstant 字典解耦; 48/49 任一都可
- 保留 48 减少 diff (跟 v9 写的 status="48" 完全一致)

**否决方案**:
- (a) 改成 49 → diff 多一行, 无业务收益; 否决

### D5: 前端 fall-back 兼容 key (`unreported` / `filled` / `cancelled` 等) 全部删

**决策**: `STATUS_LABEL` / `STATUS_TYPE` / `STATUS_TONE` / `STATUS_ICON_NAME` / `STATUS_PULSE` 5 张字典里 14 个英文 fall-back key 全部删.

**为什么**:
- `grep -rE "STATUS_LABEL\[.unreported.\]|STATUS_LABEL\[.pending_report.\]|..." client/src/` 0 处引用
- 1-2 年前的 in-memory 状态遗留; 无外部 API 暴露, 删 0 风险
- 减少认知负担 (字典只 11 条, 不混 25 条)

**否决方案**:
- (a) 保留 fall-back key → 字典长度 25 条, 新读者要区分 broker 码 vs 历史 key; 否决

### D6: DB 历史 backfill 跟 trades.amount 一起执行

**决策**: 6 条 status backfill SQL 跟 trades.amount backfill (tracking `2026-07-02-trades-amount-backfill`) 一起组成"维护窗口"一次执行.

**为什么**:
- dev DB status 仅 1 行需改 (cancel-row status=53 → 54), 量级小
- 单独开两次维护窗口浪费运维
- backfill SQL 互不依赖, 可同一事务或同一脚本批量执行

**否决方案**:
- (a) 单独开 status backfill 维护窗口 → 两次窗口浪费; 否决

### D7: 5 commit 拆分 (与 `feedback_commit_granularity` memory 一致)

**决策**: 5 commit, 每 commit 独立可测可回滚:

| # | commit | 内容 | 验证手段 |
|---|---|---|---|
| 1 | `docs(openspec): 提交 align-status-codes-to-xtconstant design+specs+tasks` | 仅 openspec/changes/align-status-codes-to-xtconstant/ 目录内 | spec lint 通过 (openspec validate) |
| 2 | `refactor(server): order_status.py 统一到 broker xtconstant 字典` | 单文件 `server/services/order_status.py` | `pytest tests/server/services/test_guards.py` + `tests/server/services/push/test_handlers.py` (不改测试, 仅验证模块加载) |
| 3 | `refactor(server): 业务写入点固定码 + 判定条件改 broker 码` | `place.py` / `cancel.py` / `ord.py` 10 处固定码 + 2 处判定条件 | `pytest tests/server/api/orders/test_*.py` + `tests/server/services/push/test_handlers.py` |
| 4 | `refactor(client): 5 张状态字典 + inferOrderStatus 改 broker 义` | `format.js` 5 张字典 + `STATUS_OPTIONS` + `inferOrderStatus` + 删 fall-back key + `holdings_push.js` 注释码同步 | `vitest client/tests/utils/orderCalc.test.js` + `client/tests/stores/holdings.test.js` |
| 5 | `test: 140 处 status 断言改 broker 码 + DB backfill 跟踪` | 88 处 Python + 52 处 JS = 140 处断言改码值; tracking issue 创建 | `pytest` 全过 + `vitest` 全过 + backfill dry-run 跑过 |

**为什么 5 commit**:
- 单文件超大 diff 拆多 commit 便于 review / bisect / 回滚
- commit 1 之后, commit 2/3/4 可任意顺序 (后端/前端无运行时耦合)
- commit 5 收尾, 含测试 + backfill 跟踪

## Risks / Trade-offs

| # | 风险 | 缓解 |
|---|---|---|
| R1 | **BREAKING**: DB 中 `orders.status` 数字含义变化, 下游报表/分析需跟着调整 | backfill SQL 6 条一次写完; tracking issue `2026-XX-XX-status-backfill` 通知下游; 部署前后 db dump 对比 |
| R2 | **BREAKING**: WS `order_update` 推的 `status` 字段值变化, 前端 v0.x.x 兼容旧版有风险 | 前端 commit 4 与后端 commit 2/3 **必须同次部署**; 部署脚本里前置 `git log --oneline` 检查 commit 3 已合并 |
| R3 | 业务写入点 10 处固定码改错位 → DB 出现 `status=255` 或非法字符串 | 测试 88 处断言覆盖 (`pytest tests/server/api/orders/test_*.py`); commit 3 之后跑 `pytest tests/server/api/orders/` 全过才合并 |
| R4 | 前端 5 张字典 type/tone/icon/pulse 按 broker 义重映射, 错位 → UI 显示混乱 | `vitest client/tests/utils/orderCalc.test.js` 32 个 status 用例 + `client/tests/stores/holdings.test.js` 5 个 status 集成用例; commit 4 之后跑 `vitest` 全过才合并 |
| R5 | DB backfill 跟 trades.amount backfill 时序冲突 | backfill 脚本互不依赖, 同事务批量; backfill 前 `sqlite3 evtrade.db ".schema orders"` 确认 schema 不变; backfill 后 `sqlite3 evtrade.db "SELECT status, COUNT(*) FROM orders GROUP BY status"` 校验分布 |
| R6 | 历史 cancel-row (order_flag=1) 的 `status=53` 与新 broker 54 = 已撤 语义一致, 但前端 view 过滤条件可能 hardcode `'53'` (例如 `STATUS_LABEL['53']`) | commit 4 同步改前端 view 引用; `grep -rE "STATUS_LABEL\['53'\]" client/src/views/` 检查 0 处 hardcode |
| R7 | 测试 140 处断言改码, 漏改某处 → 测试假绿 | commit 5 之前 `grep -rE "order\.status.*=.*'[4-5][0-9]'" tests/` 与 `grep -rE "status.*===.*'[4-5][0-9]'" client/tests/` 双向交叉验证; 漏改 1 处都跑挂 |
| R8 | 跨 commit 期间 (commit 2/3 已合并, commit 4 未合并) 部署, 前端用本地推断码, 后端用 broker 码, 显示错位 | 部署脚本强制 commit 3 + commit 4 必须在同一 release; `Makefile` / `deploy.sh` 加 pre-deploy 检查 `git log --grep="refactor(server): 业务写入点"` 与 `git log --grep="refactor(client): 5 张状态字典"` 必须同 release tag |

## Migration Plan

### 部署时序 (commit 5 收尾)

```
T0:  部署 commit 1-4 (后端+前端代码统一到 broker 码, 但 DB 仍是本地码)
     → 此时前端展示错位 (commit 4 推 broker 码, DB 还是本地码)
T0+ε:  跑 backfill SQL (6 条 UPDATE) + 同步 trades.amount backfill
     → DB 数据切换到 broker 码
T0+ε:  smoke test: WS 推一条 ord_cfm, 前端 status 显示与新字典一致
T0+δ:  release 完成, 提交 tracking issue 关闭
```

### Rollback

- **后端回滚**: `git revert <commit 2>..<commit 4>`. 旧代码读 DB 旧 status 码值时本地推断规则反向, 显示本地码 (跟历史 1-2 年一致).
- **DB 不回滚**: backfill SQL 不可逆 (旧本地码被覆盖). 回滚后端后前端显示本地码, DB 是 broker 码, 显示错位. **回滚需同时 backfill 回本地码**, 见 tracking issue 附录.
- **前端回滚**: `git revert <commit 4>`. 旧前端字典显示旧码值, 与 DB broker 码对不齐 → **前端回滚必然伴随 DB 反向 backfill**.

### 前置依赖

- 无 (本次 change 不依赖其他未合并 change)
- 后置: 关闭 tracking issue `2026-XX-XX-status-backfill` (backfill 一次性, 跟 trades.amount 一起跑)

## Open Questions

无 (5 个决策点已 user 拍板, 见 `proposal.md` 决策点段).

实施期间若发现:
- 业务写入点新增未列出的固定码 (e.g. place.py 多了 status="55" 拒单) → 直接改, 不更新 spec (在 commit 3 范围内)
- 前端 view hardcode 旧码 (e.g. `if (row.status === '51')`) → 在 commit 4 范围改, 更新 spec
- 测试 140 处数字偏差 (> 140 处) → 在 commit 5 范围改, 标 incremental
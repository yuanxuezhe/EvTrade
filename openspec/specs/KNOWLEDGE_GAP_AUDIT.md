# Knowledge Base Gap Audit — EvTrade OpenSpec 知识库差距审计

> **生成时间**：2026-08-08（commit `9802e6a` 之后）
> **审计范围**：22 个 `openspec/specs/<cap>/spec.md` 能力文档
> **对照基准**：`server/` + `client/` + `server/schema.yml` + `server/tables/*.py` + `server/migrations/`
> **方法**：逐 spec 提取"声称的能力"（Requirement / Scenario），与代码现实对比
> **严重度图例**：🔴致命（主流程不一致）/ 🟠高（关键能力漏登记）/ 🟡中（细节过期）/ 🟢低（小瑕疵）

---

## 📊 总体规模

| 维度 | 数据 |
|---|---|
| 总能力 spec | 22 个 |
| 总行数 | 7,191 行 |
| 已归档 changes | ~50+ 个 |
| 服务端 API 端点 | ~70 个（server/api/ 下 36 个文件）|
| 物理表（`server/schema.yml`）| 18 张 |
| ORM 表（`server/tables/*.py`）| 19 张（含 t0_tasks，schema.yml 漏）|
| WS 频道（实际注册）| 8 个 |
| 前端 view | 12 个 |

---

## 🔴 致命级差距（必须立即修复）

### GAP-001：`data-model/spec.md` Tables Overview 严重过期

| 项 | 详情 |
|---|---|
| **位置** | `openspec/specs/data-model/spec.md` L5（"11 张表"）+ L22-L36（Tables Overview）|
| **问题** | 顶部声称 "11 张表（业务 4 + 配置 4 + 历史 1 + 行情 1 + 序列 1）"，但实际 **19 张表** 已有 ORM：strategy / strategy_task / strategy_grid / strategy_regime / strategy_audit / strategy_script / strategy_script_audit / users / sys_config / stocks 等 **8 张表在 Overview 完全未登记** |
| **证据** | `server/tables/*.py` 19 个文件 vs `spec.md` Tables Overview 11 行 |
| **代码引用** | L6 还引用 `server/models/orm.py`，**该文件不存在**（实际是 `server/tables/base.py` + 各 `server/tables/*.py`）|
| **修复建议** | 重写 Tables Overview 为 19 张；修正 L6 文件引用；新增 §15-§22 登记 strategy/users/sys_config/stocks 等 |

### GAP-002：`ws-protocol/spec.md` 频道清单严重过时

| 项 | 详情 |
|---|---|
| **位置** | `openspec/specs/ws-protocol/spec.md` L5（"5 个 WebSocket channel"）+ L18 REQ-WS-001 + L42 payload 表 |
| **问题** | 文档声称"5 个 channel"，实际注册到 `ws_manager.active_connections` 的有 **7 个**：`order_update` / `trade_update` / `position_update` / `quote_update` / `strategy_update` / `system_update` / `task_progress_update`。`t0_strategy_update`（T0策略引擎）在 `t0/engine.py` 定义但未注册 |
| **证据** | `server/ws/manager.py:49-64` 7 行注册 vs spec REQ-WS-001 5 行 |
| **修复建议** | 重写 REQ-WS-001 为 7 channel 表；payload 表补充 `system_update` / `strategy_update` / `task_progress_update` 的 type→store 分发；标注 `t0_strategy_update` 状态（待注册？保留为常量但未启用？）|

---

## 🟠 高级差距（影响主流程理解）

### GAP-003：`strategy/spec.md` 未覆盖 script-strategy 模块

| 项 | 详情 |
|---|---|
| **位置** | `openspec/specs/strategy/spec.md`（271 行，7/7）|
| **问题** | 该 spec 是"网格策略交易引擎"，但 **script-strategy change（2026-08-01）** 引入了完整的 Python 脚本策略模块：前端编辑器 + 回测 + 实盘任务。新增 3 张表（`strategy_script` / `strategy_script_audit` / 部分字段加到 `strategy_task`）+ 14 个 REST 端点（`server/api/script_strategy/endpoints.py`）+ 2 个前端 view（`ScriptDev.vue` / `ScriptTask.vue`），但 spec 完全没登记 |
| **证据** | `server/api/script_strategy/endpoints.py` 14 个 `@router` 端点 vs spec REQ-STRAT-009 只列"8 端点" |
| **修复建议** | 新增 `script-strategy` 子 spec，或在 `strategy/spec.md` 中加 §14-§17 段覆盖 |

### GAP-004：`push/spec.md` 频道列表与 code 偏离

| 项 | 详情 |
|---|---|
| **位置** | `openspec/specs/push/spec.md` REQ-PUSH-033 "WS 频道列表（consolidate-position-data-flow 变更后清单）" |
| **问题** | 该 REQ 应该列频道清单，但 spec 内容未抽出来对比；需逐条核对是否覆盖 `task_progress_update` 和 `t0_strategy_update` |
| **证据** | 见 GAP-002 |
| **修复建议** | 读完整 REQ-PUSH-033 内容，确认是否覆盖 7 个实际频道 |

### GAP-005：`auth/spec.md` 漏登记 `/grant` 和 `/heartbeat`

| 项 | 详情 |
|---|---|
| **位置** | `openspec/specs/auth/spec.md` REQ-AUTH-001 ~ REQ-AUTH-010 |
| **问题** | 实际代码 `server/api/auth.py` 有 `@router.post("/grant")`（v92，永久 token，env `EVTRADE_ALLOW_GRANT_TOKEN=1` 控制）+ `@router.post("/heartbeat")`（v0，token touch 防过期），spec 完全没登记 |
| **证据** | `server/api/auth.py:179, 237-244` |
| **修复建议** | 新增 REQ-AUTH-011 (`/grant` 永久 token，env 控制) + REQ-AUTH-012 (`/heartbeat` token touch) |

---

## 🟡 中级差距（细节过期或缺失）

### GAP-006：`data-model/spec.md` L6 引用错误的文件路径

- 声称 `server/models/orm.py` 和 `server/db.py`
- 实际 `server/tables/`（无 `models/` 目录）+ `server/infra/db.py`
- **修复**：改 L6 引用

### GAP-007：`configuration/spec.md` 编号跳号

- L11-L19 列 REQ-CFG-001 ~ REQ-CFG-012，但顺序中出现 `REQ-CFG-011` 在 `REQ-CFG-010` 之前（编号错乱）
- **修复**：重新编号或加注释说明

### GAP-008：`frontend/spec.md` 部分 vue view 已删/改

- L133 `TStrategy.vue` 已在本轮 commit `9802e6a` 删除 + 改 redirect → 已修复 ✅
- L871 Known Issues 提到 `TStrategy.vue` → 已修复 ✅
- 需复查：是否还有其它 view 已删除但 spec 仍提到（AlgoStrategy.vue 也是占位）

### GAP-009：`intraday-orders-trades-cache/spec.md` 与 `orders-trades-history-query/spec.md` 重叠

- 两个 spec 都讲"当日委托 / 当日成交"缓存边界
- 但 `orders-trades-history-query` 提了 v12+v13，而 `intraday-orders-trades-cache` 同样提 v12+v13
- **修复**：明确边界 — intraday = 当日 IDB 缓存机制；history-query = 历史查询页面契约

### GAP-010：`stocks/spec.md` 字段同步协议

- v23 slim-stocks-table 后只有 `stock_code` PK，但文档是否登记了所有 11 字段需逐字段核对

### GAP-011：`risk-management/spec.md` 措辞刚被修（commit `9802e6a`）

- ✅ 已修："未来扩 AlgoStrategy / TStrategy" → "未来扩 AlgoStrategy 等策略页"
- 但 spec 整体仍只 122 行，可能缺细节（如 `max_order/daily_trades/position_amount/drawdown` 等 RiskChecker 字段是否登记）

### GAP-012：`push/spec.md` 与 `ws-protocol/spec.md` 责任划分

- `push` 说"push_handlers.py 归属 push 能力"
- `ws-protocol` 说"客户端连接管理归属 ws 能力"
- 边界 OK，但服务端 `ws/endpoint.py` / `ws/manager.py`（这两个不属于 push）归属谁？没明说

---

## 🟢 低级差距（小瑕疵 / 可选优化）

### GAP-013：`view-smoke-automation/spec.md`（44 行）和 `view-testing-stack/spec.md`（42 行）过简

- 两个加起来才 86 行，几乎只是占位
- 项目里有 `client/tests/views/*.test.js` 实际测试，需要补完内容

### GAP-014：`t0-quota-frame/spec.md` 没 H1 标题

- 文件开头是 `## ADDED Requirements`，没有 `# t0-quota-frame — ...` 一级标题
- 与其它 spec 格式不一致

### GAP-015：`dev-process-control/spec.md` L1-7 是 H1+H2 但中间夹 "### Requirement" 在 H1 之前

- 阅读顺序错乱

### GAP-016：22 个 spec 没有索引

- 缺一份 `openspec/specs/README.md`（或 `index.md`），列举所有 22 个能力文档及用途
- 新人 onboarding 成本高

### GAP-017：归档 changes 数量多但无归档清单

- `openspec/changes/archive/` 有 50+ 个 change 目录
- 没有 `archive/README.md` 或清单表格
- 时间久了很难追溯历史

---

## 📋 各 spec 健康度评分（建议）

| Spec | 行数 | 修改时间 | 健康度 | 主要问题 |
|---|---|---|---|---|
| data-model | 676 | 2026-07-17 | 🔴 | Tables Overview 11→19 严重过期（**GAP-001**）|
| ws-protocol | 161 | 2026-06-28 | 🔴 | 5→7 channel 严重过期（**GAP-002**）|
| auth | 156 | 2026-07-16 | 🟠 | 漏 /grant + /heartbeat（**GAP-005**）|
| strategy | 271 | 2026-07-07 | 🟠 | 漏 script-strategy 模块（**GAP-003**）|
| push | 522 | 2026-07-31 | 🟠 | 与 ws-protocol 频道清单需对账（**GAP-004**）|
| configuration | 227 | 2026-08-06 | 🟡 | 编号跳号（**GAP-007**）|
| frontend | 1940 | 2026-08-08 | 🟢 | 本轮刚修 TStrategy，剩下 AlgoStrategy 占位待议 |
| trading | 1003 | 2026-07-17 | 🟡 | 需对账 REQ-TRADE-026 后的扩展 |
| stocks | 305 | 2026-07-16 | 🟡 | 字段同步协议需对账 |
| risk-management | 122 | 2026-08-08 | 🟢 | 本轮刚修 |
| rpc-protocol | 321 | 2026-07-07 | 🟡 | 字段映射表需对账 |
| positioning | 132 | 2026-07-31 | 🟡 | 调平 API 入口契约 |
| quotes | 155 | 2026-07-10 | 🟡 | WS 订阅 pattern 化协议 |
| system-init | 168 | 2026-07-15 | 🟡 | 日初对账 ws 推 system_update 需登记 |
| asset-position-adjust | 124 | 2026-07-07 | 🟢 | |
| orders-trades-history-query | 174 | 2026-07-07 | 🟡 | 与 intraday-cache 重叠（**GAP-009**）|
| intraday-orders-trades-cache | 155 | 2026-07-07 | 🟡 | 与 history-query 重叠（**GAP-009**）|
| view-smoke-automation | 44 | 2026-07-07 | 🟢 | 太简（**GAP-013**）|
| view-testing-stack | 42 | 2026-07-07 | 🟢 | 太简（**GAP-013**）|
| server-architecture | 172 | 2026-07-07 | 🟢 | |
| dev-process-control | 206 | 2026-07-07 | 🟡 | H1/H2 顺序错乱（**GAP-015**）|
| t0-quota-frame | 115 | 2026-07-07 | 🟡 | 缺 H1 标题（**GAP-014**）|

---

## 🎯 推荐修复优先级

按**修复 ROI（影响力 × 易修复度）**排序：

### P0（立即修，1-2 个 commit）

1. **GAP-001** — 重写 `data-model/spec.md` Tables Overview + 补 8 张表登记（🔴 致命）
2. **GAP-002** — 重写 `ws-protocol/spec.md` REQ-WS-001（🔴 致命）

### P1（本轮修，1-2 个 commit）

3. **GAP-005** — `auth/spec.md` 加 /grant + /heartbeat（🟠，新功能登记）
4. **GAP-003** — `strategy/spec.md` 加 §14-§17 段覆盖 script-strategy（🟠，大模块遗漏）
5. **GAP-006** — `data-model/spec.md` L6 文件路径修正（小修）

### P2（下一轮修）

6. **GAP-004** — `push/spec.md` REQ-PUSH-033 对账（需先有 P0 的频道清单）
7. **GAP-009** — 拆分 intraday-cache vs history-query 边界
8. **GAP-013** — view-testing-stack / view-smoke-automation 补完
9. **GAP-016** — 新建 `openspec/specs/README.md` 索引

### P3（长期）

10. **GAP-007/014/015** — 编号 / 标题格式统一（小细节）
11. **GAP-017** — 归档 changes 索引

---

## 📝 备注

- 本审计**没有修改任何 spec 文件**，仅生成此报告
- 修复 P0/P1 项预计工作量：**2-3 个工作日**（1 个工程师）
- 修复全部 P0-P3 项预计工作量：**5-7 个工作日**
- 修复过程建议：每个 spec 一个 commit，按 P0→P1→P2→P3 顺序推进
- 修复后建议：在 `openspec/specs/README.md`（GAP-016）中维护一份"各 spec 最近更新时间"清单，定期 review

---

**审计结论**：知识库**基础结构完整**，但**与代码现状存在 17 处差距**，其中 2 处致命（data-model / ws-protocol 严重过期），需立即修复。
# EvTrade — OpenSpec Entry Point

> 改代码前先看这里。OpenSpec 工作流：proposal → spec delta → 实施 → 归档。

## 项目一句话

Vue3 + FastAPI 量化交易 Web 平台。**业务数据 MySQL 优先**（v4 改造后）：
- 委托/成交/持仓/资金：MySQL 是展示源
- 下单/撤单/对账：调 QMT 柜台 RPC
- 行情：msgpacket RPC + RabbitMQ FANOUT → 独立 hqserver WebSocket

后端 = 薄包装 + JWT/RBAC + DB 落库 + WebSocket 推送；前端 = 12 页面 + Pinia 缓存。

## 架构

```
┌─────────────────┐    /api/*     ┌──────────────────┐
│  Vue3 (:50998)  │──────────────▶│  FastAPI (:8000) │
│  12 views       │◀─── /ws/...──│  + JWT + RBAC    │
└─────────────────┘               └────────┬─────────┘
       │  ws://:8765 (直连)                 │ msgpacket RPC
       ▼                                    ▼
┌─────────────────┐               ┌──────────────────┐
│  hqserver       │               │  RabbitMQ        │
│  (FANOUT→WS)    │◀─── FANOUT ───│  EvTrade.Test.*  │
└─────────────────┘               └────────┬─────────┘
                                           │ YSWY 协议
                                           ▼
                                  ┌──────────────────┐
                                  │  QMT 柜台        │
                                  │  (Windows 部署)  │
                                  └──────────────────┘

数据流（v4）：
  下单:  Vue → FastAPI place() → DB INSERT (status=48) → ord_stk RPC → status=49/55 → WS 推 Vue
  推送:  QMT → ord_cfm/trd_cfm/pos_cfm/ast_cfm → push_handlers 写 DB → WS 推 Vue
  查询:  Vue → FastAPI → DB SELECT（不再调 RPC）
  日初:  Admin → /api/admin/trading-day/init → do_reconcile → qry_4类 → 写 report → 切交易日
```

## 8 个 capability（specs/ 目录一一对应）

| Cap | 范围 | 关键文件 |
|---|---|---|
| `auth` | 登录/JWT/RBAC | `server/auth/`, `server/api/auth.py`, `client/src/stores/auth.js` |
| `trading` | 下单/撤单/委托/成交/资金/T0 | `server/api/{orders,trades,asset,fee_config}.py`, `server/services/t0.py` |
| `positioning` | 持仓查询 | `server/api/positions.py`, `client/src/views/Position.vue` |
| `quotes` | 行情推送 | `hq/hqserverd/` (Rust, 2026-08-18 取代旧 `hq/hqserver.py`), `client/src/stores/quote.js`, `client/src/stores/ws.js` |
| `push` | 柜台 push → DB 落库 + WebSocket 路由 | `server/services/push_handlers.py`, `server/rpc/client.py:121-180` |
| `frontend` | Vue 路由/角色守卫/WS | `client/src/router/`, `client/src/api/` |
| `configuration` | .env / 配置分层 | `server/config.py`, `hq/hqserverd/src/config.rs` |
| `rpc-protocol` | msgpacket 客户端契约 | `server/rpc/client.py` |

## 改东西的流程

> **强约束（2026-06-16 立）**：每个需求 / BUG，**必须先检索知识库 → 补全/修正知识库 → 再创建 change 并动代码**。详见下方「步骤 0」。

```bash
# 步骤 0【前置，必做】检索并补全知识库
#   - Glob/Grep 扫 openspec/ 相关 capability 的 spec.md
#   - 确认术语、约束、影响面在知识库里有完整说明
#   - 若知识库缺说明 / 逻辑断裂 / 与现状脱节，先把 specs/<cap>/spec.md 改对
#   - 这步不完成，禁止进入步骤 1

# 1. 创建变更（用 AI 助手）
/openspec:proposal <name>

# 2. 检查产出
ls openspec/changes/<name>/
#   proposal.md    ← 为什么改
#   tasks.md       ← checklist
#   spec-deltas/   ← 涉及 cap 的 spec 增量

# 3. 改代码，按 tasks.md 走

# 4. 归档（spec 已合并到 specs/<cap>/spec.md 后）
mv openspec/changes/<name> openspec/changes/archive/<date>-<name>
```

### 步骤 0 检查清单

处理任何需求/BUG 前，对照打勾：

- [ ] 已用 Glob/Grep 扫过相关 `specs/<cap>/spec.md` 与 `changes/` 现有条目
- [ ] 涉及的术语、约束、影响面在知识库中有完整描述
- [ ] 若知识库缺说明，先在 `specs/<cap>/spec.md` 补全；逻辑断裂处先修补
- [ ] 步骤 1 的 `proposal.md` 引用了知识库对应章节（可点击跳转）
- [ ] 知识库与现状一致后，才进入 `/openspec:proposal`

> **文档体系**：当前能力契约统一在 `openspec/specs/<cap>/spec.md`（能力级）+ `知识库/`（实现级）。`docs/`（历史归档、字段级 API 契约、大型设计稿）已删除，历史内容通过 git 历史查阅——详见 [specs/dev-process-control/spec.md](specs/dev-process-control/spec.md) §"文档目录约定"。

## 约定

- **业务数据源（v4）**：MySQL（orders/trades/positions/assets）是展示源；RPC 只用于下单/撤单/对账时的事实写入
- **下单流程**：本地 INSERT(status=48) → 调 ord_stk(remark=order_no) → 改 status=49/55 → WS 推
- **推送流程**：4 类 push → push_handlers 写 DB → WS 推 Vue
- **查询流程**：纯 DB SELECT，不调 RPC；按 trading_day 默认 = 激活日
- **三屏障**：未做日初 / 非交易时段 / 非 trader 角色 → 503（查询不受限）
- **WS 频道命名**：`order_update` / `trade_update` / `position_update` / `asset_update` / `quote_update`
- **RPC 响应统一**：`{code, msg, list}`（code=0 成功，前端 axios 拦截器自动展平）
- **配置分层**：`server/.env`（FastAPI）+ `HQ_*`（hqserver，与 server 共享 .env）
- **T0 配平**：`calc_t0_volume(target * coefficient) → 整手取整`（买向下/卖向上）
- **order_no**：8 位数字（DB 序列表原子 UPSERT），当 order_remark 透传
- **测试**：`pytest hq/` 18/18；`pytest server/test_*.py` 75/75 通过

## Commit 规范（v6）

**按功能维度拆 commit**——每个 commit 应对应**一个独立功能/模块/目的**，不要把无关改动混在一起：

| 场景 | 拆 commit 方式 |
|---|---|
| 一个 change（如 v18 T0Task）含数据库迁移 + ORM + service + API + 前端 | 按层拆：migration / orm / service / api / frontend，每层 1 commit |
| 一个 bug fix 跨多文件 | 先 fix + 验证 1 commit，再 test 改进另 1 commit |
| 文档与代码同改 | 文档单独 1 commit（`docs(...)`），代码按功能另 1 commit |
| lint 清理 | 整个批次 1 commit（`chore(lint): ruff --fix 66 个 F401`）—— 一个**单一目的**仍是单一 commit |
| 多模型试水 | 验证脚本 1 commit + 配置改动 1 commit + 文档 1 commit |

**反模式**（避免）：
- ❌ "今天所有改动 1 个 mega commit"（无法 revert 单个功能）
- ❌ "1 commit 改 N 个不相关模块"（diff 难 review）
- ❌ "1 commit 修 bug + 加新功能 + 改 docs"（3 件事纠缠）

**例外**：lint auto-fix / 格式整理可以批量 1 commit，因为它们是**单一目的**（清理），不是多目的混合。

**commit 前必做**：
1. `git diff --stat` 看改动范围是否单一功能
2. `git log -1` 校验上一个 commit hash（防 AI 误报，git-safety skill）
3. commit message 用单行 `-m`（heredoc 在 AI 工具中会 timeout，memory 拍板）
4. **不自动 push**——除非用户明确拍板

## 当前活跃 change

> 当前**1 个活跃 draft change**（`2026-08-23-ai-strategy-assistant` ScriptDev AI 生成脚本 — C0 调研完成，C1-C5 待拍板推进）。

| Change | 状态 | 解决什么 |
|---|---|---|
| `2026-06-14-persistence-and-t0` | **✅ 已归档** | v4 实施完成：11 张表 + 屏障 + 日初对账 + T0 + 费率（详见 `archive/2026-06-14-persistence-and-t0/proposal.md`） |
| `add-config-validation` | **✅ 已归档** | .env 启动校验 + JWT_SECRET auto-gen + 配置分层文档化（commit `d35ed8e`；详见 `archive/add-config-validation/proposal.md`） |
| `consolidate-rpc-parsers` | **✅ 已归档** | 8 个 _parse_* 解析器合并为统一 schema（commit `390da31`；现 parser 收敛在 `server/rpc/parsers_common.py` + `parsers_business.py`；详见 `archive/consolidate-rpc-parsers/proposal.md`） |
| `current-issues` | **✅ 已合并/退出** | 本轮分析发现的 13 项问题及修复分工（commit `93335bf` 重命名为 `tracking/`；后由 `de2a973` 全局清理时移除 — 13 项已通过后续 change 实施完毕） |
| `2026-08-23-delete-orm-layer` | **✅ 已归档** | A.8：删 server/models/ + server/db.py，User 全迁 tables.Users，metadata 由 tables/ 注册 21 表（详见 `archive/2026-08-23-delete-orm-layer/proposal.md`） |
| `2026-08-23-script-visibility-toggle` | **✅ 已归档** | ScriptDev 脚本编辑补公开/私有开关（后端 REQ-STRAT-014 已就绪，前端缺口）（详见 `archive/2026-08-23-script-visibility-toggle/proposal.md`） |
| `2026-08-23-rpc-test-mode` | **✅ 已归档** | RPC 测试模式：EVTRADE_TEST_MODE=1 时业务 RPC 不发真实请求，mock.py 固定应答（详见 `archive/2026-08-23-rpc-test-mode/proposal.md`） |
| `2026-08-23-hermes-serve-evctl` | **✅ 已归档** | hermes serve daemon 纳入 evctl 默认服务（REQ-DEVCTL-011），CLI 缺失时 preflight 报错（详见 `archive/2026-08-23-hermes-serve-evctl/proposal.md`） |
| `2026-08-23-ai-agent-panel` | **✅ 已归档** | 全局右下角浮动 AgentPanel（REQ-FE-537）+ MCP 9 tool + WS gateway（REQ-ARCH-008）+ ConfirmRegistry 状态机（commit `78a5f15` 前端 / `1d45542`+`09a4c9e` MCP / `d552c35` WS / `b2babc3` 38 单测 / `8b73c51` spec merge；详见 `archive/2026-08-23-ai-agent-panel/proposal.md`） |
| `2026-08-23-ai-agent-ws-reuse-channel` | **✅ 已归档** | AI WS 走 `/ws/agent_channel` 第 6 channel，共用现有 /ws/{channel} 鉴权/心跳/idle/ws_manager 机制，0 新端口（commit `1f30112`+`ad2796d`+`a482531`+`c02ea2f` / spec merge `88638f1`；详见 `archive/2026-08-23-ai-agent-ws-reuse-channel/proposal.md`） |
| `2026-08-23-fix-agent-is-reachable-healthz` | **✅ 已归档** | `is_reachable()` 改「HTTP 响应到达即可达」判据，避开 Hermes serve v0.19.0 无 `/healthz` 端点导致的误报 not reachable（commit `18bce19`；详见 `archive/2026-08-23-fix-agent-is-reachable-healthz/proposal.md`） |
| `2026-08-24-ai-agent-claudedemo` | **✅ 已归档** | EvTrade AI 助手架构重做 (claudedemo 模式): 后端 spawn `claude -p` 子进程 + 本机 HTTP MCP server (server/ai/), 取代旧 self-built Hermes API server 链路. 删除 server/services/agent/* (455行) + server/ws/agent_handler.py (246行) + server/tests/services/agent/* (477行) + 3 个旧 archive. 前端 AgentPanel UI 不动 + agent.js 加 claudedemo→Hermes 协议归一化层. claude binary 部署硬约束. (commit `9422e3f`+`a14a558`+`bb0d6ea`+ frontend normalizer; 详见 `archive/2026-08-24-ai-agent-claudedemo/proposal.md`) |
| `2026-08-25-t0-quote-subscription` | **✅ 已归档** | useQuoteSubscription composable (client/src/composables/, REQ-FE-538) — 自动管理 quoteStore.subscribe/unsubscribe 生命周期. 修 T0Trade.vue 任务列表 last_price 列永远空 bug (LivePriceCell 读不到数据因未订阅). 行为不变重构 StkPoolView.vue 4 段手写订阅. QuotePanel 排除 (debounce + 清空保留订阅与接口不兼容). 5 commit: composable + test / T0Trade fix / StkPool refactor / OpenSpec docs / REQ-FE-538 spec merge. (commit `6185816`+`8e1924b`+`4abdfd2`+`7462aca`+`96da270`; 详见 `archive/2026-08-25-t0-quote-subscription/proposal.md`) |

详见 `openspec/changes/archive/<date>-<name>/proposal.md`。

# EvTrade — OpenSpec Entry Point

> 改代码前先看这里。OpenSpec 工作流：proposal → spec delta → 实施 → 归档。

## 项目一句话

Vue3 + FastAPI 量化交易 Web 平台。**业务数据本地 DB 优先**（v4 改造后）：
- 委托/成交/持仓/资金：本地 SQLite 是展示源
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

- **业务数据源（v4）**：本地 SQLite（orders/trades/positions/assets）是展示源；RPC 只用于下单/撤单/对账时的事实写入
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

| Change | 状态 | 解决什么 |
|---|---|---|
| `current-issues` | draft | 列出本轮分析发现的 13 项问题及修复分工 |
| `add-config-validation` | draft | .env 启动校验 + 配置分层文档化 |
| `consolidate-rpc-parsers` | draft | 8 个 _parse_* 解析器合并为统一 schema |
| `2026-06-14-persistence-and-t0` | **✅ 已归档** | v4 实施完成：11 张表 + 屏障 + 日初对账 + T0 + 费率（详见 `archive/2026-06-14-persistence-and-t0/proposal.md`） |

详见 `openspec/changes/<name>/proposal.md`。

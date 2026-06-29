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
| `quotes` | 行情推送 | `hq/hqserver.py`, `client/src/stores/quote.js`, `client/src/stores/ws.js` |
| `push` | 柜台 push → DB 落库 + WebSocket 路由 | `server/services/push_handlers.py`, `server/rpc/client.py:121-180` |
| `frontend` | Vue 路由/角色守卫/WS | `client/src/router/`, `client/src/api/` |
| `configuration` | .env / 配置分层 | `server/config.py`, `hq/hqserver.py:26-62` |
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

> **静态知识辅助**：如需参考"被 OpenSpec 接管前的完整 spec 演进"或"阶段性大型设计 + 实施计划"，查阅 [../docs/index.md](../docs/index.md)。`openspec/`（活工作流）与 `docs/`（静态沉淀）是两套独立体系，**禁止合并**——详见 [specs/dev-process-control/spec.md](specs/dev-process-control/spec.md) §"文档目录双体系约定"。
>
> 4 份 API 契约文档（[xtquant-rpc.md](../docs/xtquant-rpc.md) / [server-rest-api.md](../docs/server-rest-api.md) / [ws-push.md](../docs/ws-push.md) / [msgpacket-python-api.md](../docs/msgpacket-python-api.md)）描述**字段级**实现细节，与本目录的**能力级** spec 并行存在。

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

## 当前活跃 change

| Change | 状态 | 解决什么 |
|---|---|---|
| `current-issues` | draft | 列出本轮分析发现的 13 项问题及修复分工 |
| `add-config-validation` | draft | .env 启动校验 + 配置分层文档化 |
| `consolidate-rpc-parsers` | draft | 8 个 _parse_* 解析器合并为统一 schema |
| `2026-06-14-persistence-and-t0` | **✅ 已归档** | v4 实施完成：11 张表 + 屏障 + 日初对账 + T0 + 费率（详见 `archive/2026-06-14-persistence-and-t0/proposal.md`） |

详见 `openspec/changes/<name>/proposal.md`。

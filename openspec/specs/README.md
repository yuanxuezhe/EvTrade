# EvTrade OpenSpec 知识库索引

> **OpenSpec** 是 EvTrade 的活工作流规范体系（proposal → spec-delta → 实施 → 归档）。
> 本目录 `openspec/specs/` 是 **23 个能力文档**（capability specs）的存放处，是项目知识的"单一事实源（single source of truth）"。
>
> **用法**：
> - 改代码前先看相关 spec（`AGENTS.md` §"步骤 0"）
> - 表结构变更同步改 `server/schema.yml` + 跑 `python scripts/sync_schema.py apply`
> - 文档陈旧/缺失？查看 [./KNOWLEDGE_GAP_AUDIT.md](./KNOWLEDGE_GAP_AUDIT.md)

---

## 📋 能力文档总览（23 个 spec）

### 核心能力（与 AGENTS.md §"8 个 capability" 对齐）

| Spec | 用途 | 行数 | 最近更新 | 健康度 |
|---|---|---|---|---|
| [auth](./auth/spec.md) | 身份认证、JWT/RBAC、用户管理、自我管理、`/grant`（v92）、`/heartbeat`（v92）| 188 | 2026-08-08 | 🟢 |
| [trading](./trading/spec.md) | 委托/成交/资金/T0Task（含 `REQ-TRADE-026` strategy_type v66）| 996 | 2026-08-10 | 🟡 |
| [positioning](./positioning/spec.md) | 持仓查询 + 调平 API | 132 | 2026-07-31 | 🟡 |
| [quotes](./quotes/spec.md) | 行情分发（hqserver + 后端 WS 接入）| 174 | 2026-08-10 | 🟡 |
| [push](./push/spec.md) | 柜台 push → DB 落库 + WS 路由（含 v118 pos_push 重新启用）| 557 | 2026-08-10 | 🟢 |
| [frontend](./frontend/spec.md) | Vue3 路由 / 角色守卫 / Pinia / IDB / WS | 1977 | 2026-08-10 | 🟢 |
| [configuration](./configuration/spec.md) | .env / 配置分层 / 启动校验 | 247 | 2026-08-10 | 🟡 |
| [rpc-protocol](./rpc-protocol/spec.md) | msgpacket RPC 客户端契约 + 字段映射 | 321 | 2026-07-07 | 🟡 |

### 跨域能力

| Spec | 用途 | 行数 | 最近更新 | 健康度 |
|---|---|---|---|---|
| [data-model](./data-model/spec.md) | **15 张 MySQL 表**结构 + schema.yml 同步工作流 | 711 | 2026-08-10 | 🟢 |
| [ws-protocol](./ws-protocol/spec.md) | WebSocket 推送协议（**6 个 channel**，v97 修订）| 175 | 2026-08-10 | 🟢 |
| [strategy](./strategy/spec.md) | 策略交易引擎（网格引擎已下线）+ script-strategy 模块（14 端点）| 400 | 2026-08-10 | 🟢 |
| [strategy-exec](./strategy-exec/spec.md) | strategy_exec 独立策略运行服务（Backtrader 引擎 + RabbitMQ 信号推送 + 沙箱）| 267 | 2026-08-10 | 🟢 |
| [stocks](./stocks/spec.md) | 股票基础信息管理（v23 slim-stocks-table 起）| 305 | 2026-07-16 | 🟡 |
| [risk-management](./risk-management/spec.md) | 风险档位（4 档）+ RiskChecker 集成 | 122 | 2026-08-08 | 🟢 |
| [system-init](./system-init/spec.md) | 系统初始化 / 日初对账 / 三屏障 | 168 | 2026-07-15 | 🟡 |

### 业务规则子能力

| Spec | 用途 | 行数 | 最近更新 | 健康度 |
|---|---|---|---|---|
| [asset-position-adjust](./asset-position-adjust/spec.md) | 资金 / 持仓调平 API（v12）| 124 | 2026-07-07 | 🟢 |
| [orders-trades-history-query](./orders-trades-history-query/spec.md) | 历史委托/成交通用查询（区间 + chip + stockCode）| 180 | 2026-08-08 | 🟢 |
| [intraday-orders-trades-cache](./intraday-orders-trades-cache/spec.md) | 当日 Pinia + IDB write-through 缓存 | 161 | 2026-08-08 | 🟢 |
| [t0-quota-frame](./t0-quota-frame/spec.md) | T0Trade 顶部 quota frame + 行内配额 | 115 | 2026-07-07 | 🟡 |

### 工程化能力

| Spec | 用途 | 行数 | 最近更新 | 健康度 |
|---|---|---|---|---|
| [server-architecture](./server-architecture/spec.md) | 后端 5 层模块契约 + 单向依赖 | 283 | 2026-08-10 | 🟢 |
| [dev-process-control](./dev-process-control/spec.md) | 单一入口 `scripts/evctl.py` + 进程管控 | 206 | 2026-07-07 | 🟡 |
| [view-testing-stack](./view-testing-stack/spec.md) | view 级 Vitest 基础设施（jsdom + Element Plus stub）| 54 | 2026-08-08 | 🟢 |
| [view-smoke-automation](./view-smoke-automation/spec.md) | 端到端业务链路 smoke 测试 | 56 | 2026-08-08 | 🟢 |

### 维护元数据

| Spec | 用途 | 行数 | 最近更新 | 健康度 |
|---|---|---|---|---|
| [KNOWLEDGE_GAP_AUDIT](./KNOWLEDGE_GAP_AUDIT.md) | **知识库差距审计报告**（17 处差距 + P0-P3 修复路线）| 219 | 2026-08-08 | 🟢 |

---

## 🗺️ 文档目录双体系约定

> **`openspec/`（活工作流）** 与 **`docs/`（静态沉淀）**是两套独立体系，**禁止合并**。
> 详见 [`dev-process-control/spec.md` §"文档目录双体系约定"](./dev-process-control/spec.md)

### `openspec/` 体系（本目录）

- `specs/<cap>/spec.md` — 22 个能力文档（capability specs）
- `changes/<name>/` — 活跃变更（proposal + tasks + spec-deltas）
- `changes/archive/<date>-<name>/` — 已归档变更
- `tracking/` — 变更追踪
- `KNOWLEDGE_GAP_AUDIT.md` — 知识库审计
- `AGENTS.md` — OpenSpec 工作流入口

### `docs/` 体系（沉淀）

- `index.md` — docs 体系导航
- `xtquant-rpc.md` — QMT 柜台 RPC 字段级契约
- `server-rest-api.md` — REST API 字段级契约
- `ws-push.md` — WS 推送字段级契约
- `msgpacket-python-api.md` — msgpacket Python 库 API 契约
- `strategy_trading_guide.md` — 策略交易用户指南
- `changelog/` — vX 变更日志
- `specs-history/` — 阶段性设计（被 OpenSpec 接管前的完整 spec 演进）
- `designs/` — 静态设计稿
- `superpowers/` — 流程 / 模板

**对照关系**：
- `openspec/specs/` 描述"**能力级**契约"（REQ-NNN / Scenario 模式）
- `docs/<X>.md` 描述"**字段级**契约"（具体接口参数 / 字段 / 错误码）
- 两者并行存在，**不要重复**也不要**合并**

---

## 🔄 工作流（精简版）

> 完整流程见 [`AGENTS.md`](./AGENTS.md)

```bash
# 步骤 0【前置，必做】检索知识库
ls openspec/specs/<相关 cap>/spec.md

# 1. 创建变更（proposal → tasks → spec-deltas）
/openspec:proposal <name>

# 2. 实施代码（按 tasks.md checklist 走）

# 3. 改 spec（如新能力 / 表结构变更）
#    - capability spec: openspec/specs/<cap>/spec.md
#    - 表结构: server/schema.yml + 跑 sync_schema.py apply
#    - 字段级契约: docs/<X>.md

# 4. 归档
mv openspec/changes/<name> openspec/changes/archive/<date>-<name>
```

---

## 📊 知识库健康度指标

| 维度 | 数值 |
|---|---|
| 总能力文档 | **23** |
| 总行数 | **~8,000** |
| 平均行数 | **~350** |
| 7 天内更新 | 11 个（auth / configuration / data-model / frontend / push / quotes / server-architecture / strategy / strategy-exec / trading / ws-protocol / view-*）|
| 30 天以上未更新 | 11 个（auth 已修；其余待 review）|
| 已识别的差距 | 17 处（详见 [AUDIT](./KNOWLEDGE_GAP_AUDIT.md)）|
| 已修复 | **12 处**（P0 致命 2 + P1 高级 3 + P2 中级 4 + P3 低级 3）|
| 待修复 | 5 处（P3 剩余：编号唯一化 + 归档索引）|

---

## 🎯 推荐 review 顺序（新人 onboarding）

1. [`AGENTS.md`](./AGENTS.md) — OpenSpec 工作流入口（必读）
2. [`KNOWLEDGE_GAP_AUDIT.md`](./KNOWLEDGE_GAP_AUDIT.md) — 知识库审计报告（了解历史变更）
3. [`auth/`](./auth/spec.md) — 入口最简
4. [`trading/`](./trading/spec.md) — 业务核心
5. [`data-model/`](./data-model/spec.md) — 表结构 SoT
6. [`frontend/`](./frontend/spec.md) — 前端架构
7. [`push/`](./push/spec.md) + [`ws-protocol/`](./ws-protocol/spec.md) — 实时推送
8. [`strategy/`](./strategy/spec.md) — 高级业务

---

**最后更新**：2026-08-08（commit `2e276ec` 之后）
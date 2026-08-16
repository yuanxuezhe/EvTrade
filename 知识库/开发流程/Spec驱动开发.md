# Spec驱动开发

## 对应代码路径

- `openspec/AGENTS.md`（工作流入口与强约束，改代码前必读）
- `openspec/specs/<capability>/spec.md`（能力级 spec 真相源）
- `openspec/changes/<name>/`（活跃变更）与 `openspec/changes/archive/`（归档变更）
- `docs/index.md`（静态沉淀目录索引）
- `scripts/verify_change.sh`（归档验收证据包）

## 功能概述

EvTrade 采用 OpenSpec 驱动的变更管理：每个需求/BUG 必须先检索并补全知识库，再创建 change（proposal → spec delta），按 tasks.md 实施，最后归档。spec 是"当前实现的真相源"，change 是"变更追踪单元"，与 `docs/` 静态沉淀构成双体系。

## 文件清单

| 代码文件/目录 | 作用 |
|----------|------|
| `openspec/AGENTS.md` | 项目一句话、架构图、8+ capability 映射表、改东西流程、commit 规范 |
| `openspec/specs/` | 23 个 capability 目录（auth/trading/positioning/quotes/push/frontend/configuration/rpc-protocol/data-model/strategy/strategy-exec/system-init/t0-quota-frame/risk-management/...） |
| `openspec/changes/<name>/proposal.md` | 为什么改（问题陈述/方案/范围 In/Out） |
| `openspec/changes/<name>/tasks.md` | 实施 checklist（分 Phase，`[x]`/`[ ]` 勾选） |
| `openspec/changes/<name>/spec-deltas/` | 涉及 capability 的 spec 增量（REQ-XXX-N 编号） |
| `openspec/changes/<name>/design.md` | （可选）架构设计、数据流、API 契约 |
| `openspec/changes/archive/` | 已完成并归档的 change（60+ 个，按日期命名） |
| `docs/` | 静态沉淀：API 契约 4 篇、specs-history/、designs/ |

## 核心实现

### 完整工作流（AGENTS.md 强约束）

```text
步骤 0  检索并补全知识库（前置，必做）
   ├─ Glob/Grep 扫 openspec/specs/<相关 cap>/spec.md 与 changes/ 现有条目
   ├─ 确认术语、约束、影响面在知识库中有完整说明
   ├─ 缺说明/逻辑断裂/与现状脱节 → 先改对 specs/<cap>/spec.md
   └─ 不完成此步，禁止进入步骤 1
步骤 1  创建变更: /openspec:proposal <name>
步骤 2  检查产出: openspec/changes/<name>/{proposal.md, tasks.md, spec-deltas/}
步骤 3  改代码，按 tasks.md 逐项推进并勾选
步骤 4  归档: spec 增量合并进 specs/<cap>/spec.md 后
        mv openspec/changes/<name> openspec/changes/archive/<date>-<name>
```

步骤 0 检查清单：①已扫相关 spec 与既有 change ②术语/约束/影响面有完整描述 ③缺口先补 ④proposal.md 引用知识库章节（可点击跳转）⑤知识库与现状一致才进 proposal。

### change 目录结构（以 archive/2026-08-09-strategy-exec-service 为例）

```text
2026-08-09-strategy-exec-service/
├── proposal.md     # Why: 4 痛点（紧耦合/扩展差/资源争抢/职责不清）；方案: Backtrader
│                   #   + 独立服务 + RabbitMQ 信号；Scope: In/Out 表格；BREAKING 声明
├── design.md       # before/after 架构图、RabbitMQ 拓扑、4 个 internal API 契约、数据模型变更
├── tasks.md        # Phase 1 骨架 / Phase 2 引擎 / ... 分阶段 checklist + 归档时修订说明
└── spec-deltas/    # 新增 strategy-exec/spec.md + strategy/data-model spec 增量
```

要点：
- proposal 必须写清 **Why（问题陈述）/ 方案 / Scope In+Out / BREAKING**；Out 表明"明确不做"防止蔓延
- tasks.md 归档时同步实际交付状态（该例标注：独立 pyproject/Dockerfile 被"复用根 .venv"决策取代，commit hash 可查）
- spec-deltas 用 `REQ-<CAP>-<N>` 编号（如 `REQ-AUTH-IDLE-001`），`verify_change.sh` 会自动抽取清单

### capability 划分（specs/ 目录）

核心 8 个（AGENTS.md 映射表）：`auth`（登录/JWT/RBAC）、`trading`（下单/撤单/T0）、`positioning`（持仓）、`quotes`（行情推送）、`push`（柜台 push 落库+WS 路由）、`frontend`（路由/守卫/WS）、`configuration`（.env 分层）、`rpc-protocol`（msgpacket 契约）。另有 `data-model`（schema 治理）、`strategy`/`strategy-exec`（策略）、`dev-process-control`（evctl 与文档双体系）、`risk-management`、`system-init`、`t0-quota-frame`、`view-testing-stack` 等扩展能力。

### 归档与验收

- 归档条件：spec delta 已合并到 `specs/<cap>/spec.md`、tasks.md 勾完（或标注实际偏差）
- 归档命令：`mv openspec/changes/<name> openspec/changes/archive/`（活跃目录名不带日期，归档带 `YYYY-MM-DD-` 前缀）
- 验收证据：`bash scripts/verify_change.sh <change-name> [base-ref]` 输出 7 段证据包（git 历史/归档结构/tasks 完成度/e2e 清单/健康检查/逐 commit stat/REQ-ID）

### Commit 规范（v6：按功能维度拆分）

| 场景 | 拆法 |
|---|---|
| 一个 change 含迁移+ORM+service+API+前端 | 按层拆，每层 1 commit（migration / orm / service / api / frontend） |
| bug fix 跨多文件 | fix+验证 1 commit，test 改进另 1 commit |
| 文档与代码同改 | 文档单独 1 commit（`docs(...)`），代码按功能另拆 |
| lint 清理 | 整批 1 commit（单一目的即可合并） |

反模式：❌ mega commit（无法 revert 单功能）❌ 1 commit 混多个不相关模块 ❌ 1 commit 修 bug+加功能+改 docs。
commit 前必做：`git diff --stat` 看范围单一 → `git log -1` 校验上一 commit hash → 单行 `-m`（heredoc 会 timeout）→ **不自动 push**。

### 与知识库双体系的关系

| 体系 | 职责 | 禁止 |
|------|------|------|
| `openspec/` | 活工作流：当前 spec 真相源 + 变更追踪 + AI 协作约定 | 存历史草稿/大型设计全文 |
| `docs/` | 静态沉淀：specs-history（被覆盖前演进稿）、designs（阶段性大设计+计划）、API 字段级契约 | 与 openspec spec 重复维护 |

规则（`specs/dev-process-control/spec.md` §文档目录双体系约定）：当前能力写 `specs/<cap>/spec.md`；历史版本稿进 `docs/specs-history/`（带日期后缀）；跨能力大设计进 `docs/designs/`；**两目录禁止合并**。4 份 API 契约（xtquant-rpc / server-rest-api / ws-push / msgpacket-python-api）描述字段级细节，与能力级 spec 并行。

## 依赖关系

- 上游：AI 助手 slash command（`/openspec:proposal`）、知识库检索（步骤 0）
- 下游：代码实施（按 tasks.md）、测试体系（验收）、`scripts/verify_change.sh`（证据）、git commit 拆分规范

## 修改指南

- 新需求/BUG 一律从步骤 0 开始，先扫 `openspec/specs/` 与本知识库（`知识库/` 目录），补齐再动代码
- proposal 引用 spec 章节用相对链接，保证可跳转核对
- spec delta 合并进 specs/<cap>/spec.md 时保持 `Requirement/Scenario` 格式（WHEN/THEN）
- 归档前跑 `verify_change.sh` 留证据；tasks.md 未完成项要么做完要么在归档说明中写明偏差与替代方案
- 本知识库（`知识库/`）是 spec 的实现级补充，代码重构后同步更新对应文档

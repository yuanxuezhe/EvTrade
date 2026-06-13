# EvTrade OpenSpec

规范驱动的 AI 协作工作流。**改代码前先看这里。**

## 目录结构

```
openspec/
├── AGENTS.md                    # AI 协作入口（必读）
├── .openspec.yaml               # 工作流配置
├── specs/                       # 当前 spec（永远反映已实现的能力）
│   ├── auth/
│   ├── trading/
│   ├── positioning/
│   ├── quotes/
│   ├── push/
│   ├── frontend/
│   ├── configuration/
│   └── rpc-protocol/
└── changes/                     # 待实施/实施中的变更
    ├── current-issues/          # 问题追踪表（13 项 + 修复状态）
    ├── add-config-validation/   # M1 提案
    ├── consolidate-rpc-parsers/ # M2 提案
    └── archive/                 # 已归档的变更
```

## 工作流

```
  proposal                   apply                   archive
┌─────────────┐         ┌──────────┐          ┌──────────┐
│  draft      │────────▶│ applying │────────▶│ archived │
│  tasks ✗   │         │  tasks ⏳ │          │  tasks ✓ │
└─────────────┘         └──────────┘          └──────────┘
```

### 命令（用 AI 助手调用）

| 命令 | 作用 |
|---|---|
| `/openspec:proposal <name>` | 在 `changes/<name>/` 生成 `proposal.md` + `tasks.md` + `spec-deltas/` |
| `/openspec:apply <name>` | 按 `tasks.md` 实施代码改动 |
| `/openspec:archive <name>` | 实施完成 + spec 已合并后归档 |

### 每个 change 必备

```
changes/<name>/
├── proposal.md         # 为什么改、改什么、影响面
├── tasks.md            # 实施 checklist（带 checkbox）
└── spec-deltas/        # 涉及 capabilities 的 spec 增量
    ├── <cap1>.md
    └── <cap2>.md
```

## 当前活跃 change

| Change | 状态 | 任务数 |
|---|---|---|
| `current-issues` | draft（追踪表） | 13 项 |
| `add-config-validation` | draft | M1 JWT_SECRET 必填 |
| `consolidate-rpc-parsers` | draft | M2 8 个 _parse_* 统一 |

详见 [`AGENTS.md`](./AGENTS.md) 和各 `changes/<name>/proposal.md`。

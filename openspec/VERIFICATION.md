# 验收工作流 (Verification Workflow)

> 每次 OpenSpec change 完成后、archive 前，调 `/opsx:verify <change-name>` 跑独立验收。
> 验收 subagent 与开发 context 完全隔离 — 这是设计目的，不是限制。

## 快速开始

```bash
# 1. 改完代码，commit + push 后，准备 archive 前
/opsx:verify 2026-07-08-t0-task-management

# 2. 看到 "Verdict: PASS" 后再 archive
/opsx:archive 2026-07-08-t0-task-management
```

## 工作原理

```
[Dev 完成] 
   ↓
[Parent 收集证据包]   ← scripts/verify_change.sh 自动跑
   ↓
[Spawn leaf subagent] ← delegate_task(role=leaf, NO context)
   ↓
[Subagent 读 verify-template.md + 证据包]
   ↓
[Subagent 写 VERIFICATION_REPORT.md]
   ↓
[Parent 展示 PASS/FAIL]
```

### 关键设计：subagent 无上下文

为什么重要？  
- **PM/Dev 的认知盲区**：开发时漏看的东西，开发完再看还是会漏
- **subagent 冷启动**：从零读 spec + 代码 + git log，**不会**被"我刚写的肯定对"带偏
- **成本**：每次 ~30-60 秒（subagent 读文件 + 写报告），但捕获的 bug 价值远高于此

## 长任务识别与工具选择

> **核心原则**: 根据任务时长挑工具,不要让"短任务工具"做"长任务活"。

### 任务分类 (按预估时长)

| 类别 | 时长范围 | 适用工具 | 例子 |
|---|---|---|---|
| **短任务** | < 1 分钟 | 主对话直接执行 | `git log`, `cat`, `grep`, 简单 `curl` |
| **中任务** | 1-10 分钟 | `delegate_task` (同步等结果) | 验证 subagent, 单文件 read, 中等 e2e |
| **长任务** | 10-30 分钟 | `delegate_task` (同步, 看上下文) | 大型 e2e 套件, 跨多文件 read |
| **超长任务** | > 30 分钟 | `background=true` + `notify_on_complete` | 模型训练, 完整 CI, 大数据迁移 |

### 为什么这样分?

- **短任务直接做**: 无工具调用成本, 1 步到位
- **中任务用 `delegate_task`**: v18 验收实测 ~6.5 分钟 (386 秒) subagent 正常返回, **远没到 `gateway_timeout: 1800` 上限**
- **长任务仍可用 `delegate_task`**: Hermes 当前配置下, 30 分钟内的同步 subagent 都安全
- **超长任务必须 `background=true`**: 因为 `gateway_timeout: 1800` (30 分钟) 是硬上限

### 长任务下"假死"误判

如果用户报告"任务卡住",**先验证 3 件事再下结论**:

1. **检查 `gateway_timeout_warning: 900` (15 分钟)**: 如果任务已跑 15 分钟, 系统**会**发警告 (不是 kill) — 这就是"假死"假象
2. **检查 `gateway_notify_interval: 180`**: 每 3 分钟会发 heartbeat, 看通知频率
3. **检查 `gateway_auto_continue_freshness: 3600`**: 1 小时内上下文可"续命", 但**不会**自动继续

**真正会被杀的边界**:
- `gateway_timeout: 1800` (30 分钟) — 同步 subagent 硬上限
- `inactivity_timeout: 120` — **只对 `browser_*` 工具生效**, 不影响 subagent

### 实战选择表

| 场景 | 推荐工具 | 理由 |
|---|---|---|
| 跑 13 个 e2e 断言 (v18 验收) | `delegate_task` | 386 秒实测成功 |
| 跑 100+ 个 e2e 套件 | `background=true` + `notify_on_complete` | 预估 > 30 分钟 |
| git log + 列 commit | 主对话 `terminal()` | 1 步, 无工具调用 |
| 读 10 个文件交叉对比 | `delegate_task` subagent | 中等耗时, 隔离上下文 |
| 部署到生产 | `background=true` + `notify_on_complete` | 不可预期, 必须后台 |
| 训练 ML 模型 | **不通过本工具**, 用 cron + dedicated worker | 跨小时级, 用专门的 cron job |

### 决策树

```
任务预估 < 1 分钟? 
  ├─ Yes → 主对话直接做
  └─ No → 预估 < 30 分钟?
              ├─ Yes → delegate_task (同步)
              └─ No → 预估 < 数小时?
                          ├─ Yes → background=true + notify_on_complete
                          └─ No  → 用 cron / dedicated worker
```

## Checklist 6 大项

详见 `openspec/verify-template.md`：

1. **文件交付**：archive 4 文件齐
2. **Git 卫生**：commit hash 真、风格一致、v6 拆小
3. **代码/测试**：backend 启得起、e2e 全 PASS
4. **业务回归**：旧 API 不破、新 API 符 spec
5. **文档**：REQ 编号、tasks 勾选、commit msg 含 spec ref
6. **结论**：PASS / PASS-with-warnings / FAIL

## 已知陷阱 (Verifier 要注意)

### 1. tasks.md "todo 数" 误报
- **症状**：`grep '\[ \]' tasks.md` 返回 > 0
- **原因**：OpenSpec tasks.md 是**工作流**任务清单（"用户拍板" / "用户确认" / "/sync"），**不是**代码任务清单
- **判断标准**：看 commit history 是否覆盖了 tasks.md 里所有 `[ ]` 项描述的工作
- **豁免**：v18 案例里 22 个 `[ ]` 全是 OpenSpec 流程任务，**不算** change 未完成

### 2. e2e 不可跑 (backend 未启)
- **症状**：`backend health: 000`
- **处理**：verifier 仍可验收代码 + spec，e2e 标 ⚠（不是 ✗）— **不阻塞 PASS**
- **建议**：要 100% 验收前先 `evctl backend start` 启 backend

### 3. main 分支未同步
- **症状**：`git log main..HEAD` = 20+ commits（包括其他 change）
- **处理**：verifier 用 `openspec/changes/archive/<change>/` 路径定位，**不依赖** commit range
- **备选**：用 change 名作为"逻辑边界"，commit hash 在 archive 文档里

### 4. spec-delta 与主 spec 不一致
- **症状**：`openspec/specs/trading/spec.md` 缺新 REQ
- **处理**：✗ FAIL — sync 是 archive 前置条件
- **修复**：调 `/opsx:sync <change>` 重新 sync

## 验收产物

每个 change archive 后会有：

```
openspec/changes/archive/2026-07-08-t0-task-management/
├── proposal.md
├── spec-deltas/
│   ├── trading.md
│   └── data-model.md
├── tasks.md
└── VERIFICATION_REPORT.md    ← 验收报告（不可删）
```

`VERIFICATION_REPORT.md` 含：
- 6 大项逐项打分（✓/⚠/✗）
- 每项的证据（文件路径、行号、命令输出、commit hash）
- subagent 完整推理过程
- e2e 原始输出
- 最终 verdict

## 升级路径

如果 verifier 发现**真问题**：
1. **FAIL** → 不 archive，回流到 change，Dev 修后重新 verify
2. **PASS-with-warnings** → 用户决定：
   - 接受警告 → archive
   - 拒绝警告 → 修后重 verify

## 未来增强（v19+）

- [ ] subagent 自动跑 e2e（需要 backend 启动 + 数据库准备）
- [ ] subagent 对比 spec delta 与 main spec diff（自动 sync 检测）
- [ ] subagent 跑 lint + type check（ruff / mypy）
- [ ] 历史 verify 报告汇总 dashboard

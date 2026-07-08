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

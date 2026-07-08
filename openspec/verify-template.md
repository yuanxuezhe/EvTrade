# 验收 Checklist 模板

> 每个 change 完成（archive 前）必须通过本 checklist。
> 跑验收 = 调 `/opsx:verify <change-name>`，由独立 subagent 按本表逐项打分。

## 0. 元信息

- **change 名**: `<change-name>`
- **archive 路径**: `openspec/changes/archive/YYYY-MM-DD-<change-name>/`
- **commits**: `<git rev-list --count main..HEAD>`（基线后新增 commit 数）
- **验收时间**: YYYY-MM-DD
- **验收人**: independent verification subagent（role=leaf, no parent context）

## 1. 文件交付核对

| 项 | 标准 | 证据 | ✓/✗ |
|---|---|---|---|
| 1.1 proposal.md 存在 | 4 文件齐 | `ls archive/.../` | |
| 1.2 spec-deltas 存在 | ≥1 delta | `ls archive/.../spec-deltas/` | |
| 1.3 tasks.md 存在 | 全 `- [x]` | `grep '\[ \]' tasks.md` 应空 | |
| 1.4 主 spec 已 sync | `openspec/specs/<cap>/spec.md` 含 change 新增 REQ | `grep REQ-XXX-NNN` | |

## 2. Git 卫生

| 项 | 标准 | 证据 | ✓/✗ |
|---|---|---|---|
| 2.1 commits 实际存在 | `git log -1 --format=%H` 全部回显 | `git log <base>..HEAD --oneline` | |
| 2.2 工作树干净 | `git status` 无 untracked/modified（除 .bak 临时） | `git status --porcelain` | |
| 2.3 commit 风格一致 | 全部 `<type>(scope): <subject>` 中文/英文 | `git log --format=%s` | |
| 2.4 v6 拆小原则 | 每个 commit < 5 文件 / < 100 行（赦免: migration） | `git show --stat <hash>` | |

## 3. 代码/测试

| 项 | 标准 | 证据 | ✓/✗ |
|---|---|---|---|
| 3.1 backend 可启动 | `python -c "import server.main"` 成功 | exit 0 | |
| 3.2 e2e 通过 | `scripts/e2e/test_*.py` 全 PASS | exit 0 + log | |
| 3.3 DB schema 一致 | ORM class ↔ migration ↔ 实际表 | `DESCRIBE` 验证 | |
| 3.4 Linter (如 ruff) | 无 error | `ruff check server/` | |

## 4. 业务回归（按 change 类型）

| 项 | 标准 | 证据 | ✓/✗ |
|---|---|---|---|
| 4.1 旧 API 不破 | 关键 endpoint 仍 200 | `curl /api/...` | |
| 4.2 新 API 实现 spec | 8 endpoints → 7 个全在 | `grep` api/*.py | |
| 4.3 RBAC 正确 | 用户/管理员分离 | e2e 含非 admin token 测试 | |
| 4.4 数据流闭环 | 下单 → push → 缓存 → UI | 端到端 | |

## 5. 文档

| 项 | 标准 | 证据 | ✓/✗ |
|---|---|---|---|
| 5.1 proposal 完整 | Why/What/Impact 三段齐 | `head -50` | |
| 5.2 spec-delta REQ 编号合规 | 沿用 REQ-CAP-NNN | `grep -E 'REQ-[A-Z]+-[0-9]+'` | |
| 5.3 tasks 全部勾选 | 无 `- [ ]` | `wc -l` 对比 | |
| 5.4 commit message 含 spec ref | 含 REQ-XXX 引用 | `git log --format=%s` | |

## 6. 验收结论

- [ ] **PASS**（所有项 ✓）→ 可 archive
- [ ] **PASS with warnings**（4.x 业务回归部分可标 ⚠）→ 人工 review 后 archive
- [ ] **FAIL**（任何 1.x / 2.x / 3.x ✗）→ 不可 archive，回流到 change

## 7. 证据归档

- 验收报告写到: `openspec/changes/archive/YYYY-MM-DD-<change-name>/VERIFICATION_REPORT.md`
- 报告含: 本 checklist 完整 + subagent 完整推理 + e2e 原始输出

# v19 Lint Cleanup — 提案

## Why

`ruff check server/` 当前有 **41 个 lint 错误**（108 个里，67 个 F401 已 auto-fix）：

| 错误类型 | 数量 | 风险 |
|---|---|---|
| F401 unused import (re-export) | 22 | 低（无功能影响，但污染 `__init__.py`） |
| F841 unused variable | 8 | 中（隐藏死代码 / 调试遗留） |
| E402 import not at top | 7 | 低（运行时正确，风格问题） |
| E712 `== True/False` | 2 | 低（不阻塞，但 Pylint 严拒） |
| E702 多语句同行 | 1 | 低 |
| F541 f-string 无占位符 | 1 | 低（应改 plain string） |

**痛点**：
- v18 验收报告发现 6 个 F401（实际 67 个，subagent 抽样不全）
- 大批 unused import 累积让 IDE 提示刷屏，开发者麻木 → 真 bug 隐藏其中
- v20+ change 在写代码时会被这些噪声干扰

## What Changes

清理 41 个 lint 错误，**严格按功能维度拆 5 commits**：

| Commit | 模块 | 错误数 |
|---|---|---|
| 1 | `core/api`（users + admin + migrations） | 4 |
| 2 | `re-exports`（enums/utils/t0 __init__） | 22 |
| 3 | `infra/rpc/repo`（client.py + repo/） | 8 |
| 4 | `tests`（strategy/） | 8 |
| 5 | `services`（strategy/quote_consumer） | 1 |

每个 commit 完成后：
- `ruff check server/ --select <改动的代码>` 验证
- `python3 -c "from server.main import app"` 验证 import 不破
- 必要时重启 backend 跑 e2e 子集

## Impact

- **行为无变化**：所有修都是"删死代码 / 改风格"，不改语义
- **API 兼容**：所有 `__init__.py` 的 re-export **保留**（用 `as X` 显式 re-export 满足 ruff F401 "explicit re-export"）
- **向后兼容**：现有 `from server.utils import xxx` 调用不变
- **CI/IDE 提示减少 41 条** → 开发者注意力清净

## Non-Goals

- ❌ **不**改 Pydantic v1 `orm_mode` 警告（v19 spec scope 不含）
- ❌ **不**改 FastAPI `Query(regex=)` 警告（已记入 v18 教训，单独 change）
- ❌ **不**引入 `pyproject.toml [tool.ruff]` 配置（只跑 `ruff check`，不改项目配置）
- ❌ **不**改 format（黑 / isort）—— ruff format 与本 change 无关

## Risks

| 风险 | 缓解 |
|---|---|
| 删错 import 导致运行时 NameError | 每 commit 后 `from server.main import app` 验证 |
| re-export 改 `as X` 改变 `__all__` 行为 | 测试 `from server.enums import PriceType` 调用面 |
| E402 调 import 位置破坏循环依赖 | **只**在测试文件和注释明确的"故意延迟导入"处改，否则不动 |
| tests 文件 F841 删变量破坏测试 setup | 逐文件 review，确保删的真是 unused |

## Commits 规划

```
1. chore(lint): api/users E712 + migrations F541 (3 fixes)
2. chore(lint): re-exports __init__.py F401 (22 fixes)  - 用 `as X` 显式 re-export
3. chore(lint): rpc/client E402 + repo E402/E702 (8 fixes)
4. chore(lint): tests/strategy F841 + E402 (8 fixes)
5. chore(lint): services/strategy F841 (1 fix)
```

## Acceptance

- [x] `ruff check server/` exit 0
- [x] `python3 -c "from server.main import app"` 成功
- [x] e2e `pytest server/test_*.py` 75/75 通过
- [x] WS push 测试通过（rpc/client E402 改动最敏感）
- [x] `/opsx:verify 2026-07-08-lint-cleanup` PASS

## References

- v18 验收报告：`openspec/changes/archive/2026-07-08-t0-task-management/VERIFICATION_REPORT.md`（首次发现 6 个 F401，实际 108 个）
- v17 commit `426266f` 已修了 67 个 F401 auto-fixable 部分
- ruff docs: https://docs.astral.sh/ruff/rules/
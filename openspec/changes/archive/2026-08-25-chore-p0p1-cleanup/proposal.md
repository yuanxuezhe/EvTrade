# Chore: P0+P1 死代码/死配置清理

## Why（背景）

2026-08-25 项目扫描发现 P0 6 项 + P1 9 项（已二次验证去除 1 项误报）共 14 项基础设施与死代码问题：
- **P0（基础设施）**：pytest testpaths 指向已废 legacy tests、`vitest@^4.1.9` 不存在、缺 ruff/CI、`tests/server/` 17 文件引用已删 ORM、`server/requirements.txt` 与现状矛盾、`server/api/orders/cancel.py` 无单元测试
- **P1（死代码）**：5 处死导入/死别名/兼容 shim、`main.py` 10 处 print 绕过 logger、`iquant` 2 处裸 except、前端 2 处死引用

按 CLAUDE.md § 三 + § 五 + § 十一 同步执行。

## What（清理范围）

按 v6 commit 规范"lint auto-fix 可整批 1 commit ——单一目的仍是单一 commit"原则，本 change 把单一目的的清理集中归口；每个 commit 仍是单一目的、可独立 review/回滚。

### P0（6 项）

| 项 | 文件 | 操作 |
|---|---|---|
| 1 | `pytest.ini:3` | `testpaths = tests` → `testpaths = server/tests tests`（让默认 `pytest` 跑到工作测试） |
| 2 | `client/package.json:32` | `vitest@^4.1.9` → `vitest@^1.6.0`（4.x 不存在，`npm install` 会失败） |
| 3 | `pyproject.toml` | 加 `[tool.ruff]` section（line-length=120，select E/F/W） |
| 3 | `.github/workflows/ci.yml` | 新建：pytest 后端 + npm run build 前端 |
| 4 | `tests/server/` 整个子树 | 删除（17 文件引用 `server.models.orm` / `server.models.user` 等已删模块；conftest.py:11-13 已注明"既存失败，待清理"） |
| 5 | `server/requirements.txt` | 删除（与 `pyproject.toml` + `uv.lock` 矛盾：第一行 `python>=3.6.8` 错；`pydantic>=1.9,<2.0` 与 Pydantic v2 现实冲突） |
| 6 | `server/tests/test_orders_cancel.py` | 新建：至少 1 个 happy-path 测试（CLAUDE.md § 八强制覆盖关键路径） |

### P1（9 项，二次验证后修正清单）

| 项 | 文件 | 操作 |
|---|---|---|
| 7 | `server/api/orders/place.py:38` | 删 `from server.utils.time import format_ts`（函数体内未用） |
| 8 | `server/api/ai_analysis.py:36,64` | 删 `import re`（未用）；把 `import threading` 挪到顶部 |
| 9 | `server/repo/quote_snapshots.py:26` | 删 `QuoteSnapshot = QuoteSnapshots` 死别名 |
| 10 | `server/services/t0/tasks.py:55,71-72,108,116-117` | 删 `user_id_kw` 兼容形参（api 层已用 `user_id=`） |
| 11 | `server/services/t0/tasks.py:767-792` | 简化 `_compute_summary` 单签名（api 层只调 `_compute_summary(t)`） |
| 12 | `server/main.py` 10 处 | `print("[INIT] ... failed: %s", e)` → `log.warning(...)`，让文件 handler 真的捕获 |
| 13 | `iquant/runtime_trdapi_rel.py:467-472` + `iquant/quota_his.py:273-278` | `except:` → `except queue.Empty:`（裸 except 会吞 `SystemExit`/`KeyboardInterrupt`） |
| 14 | `client/src/views/Dashboard.vue:169` | 删 `STATUS_TYPE` 未用导入 |
| 15 | `client/src/utils/format.js:6-16` | 删 `formatAmount = formatMoney` 别名（仅 1 调用方：`T0Trade.vue`，可内联） |

> **二次验证剔除**：`server/repo/orders.py:269,304` 报为死 import 实为活 import（line 284 / 323 `format_ts(tz='local')` 实际使用）。§ 十二铁律生效。

## 影响面

- 不改变任何业务行为、API 契约、前端 UI
- 删除 `tests/server/` 17 legacy 文件 — 知识库 `测试体系.md:33` 已规划清理；本 change 即执行
- 删除 `server/requirements.txt` — 项目已用 `uv`（`uv.lock` 存在），`requirements.txt` 实际无人引用
- `pytest` 默认收集路径变化 — 影响本地开发体验（修正后跑测试能跑到真测试）
- CI workflow 新建 — 首次 push 时会跑，CI 时间 ~5-10 分钟（backend pytest + frontend npm run build）

## 不做

- 不修 async/sync event loop 阻塞（P5，单独 change）
- 不抽常量 / 不拆大文件（P2/P4，单独 change）
- 不迁移表格到 DataTableView（P3，单独 change）
- 不同步 P6 知识库漂移（ws-protocol 7 channel / data-model 表数等）—— 单独 change

## Commit 规划（v6 规范）

按 § 五 "每个 commit 只做一件事"，本 change 拆 9 个 commit：

1. `chore(ci): 修正 pytest testpaths 指向 server/tests`
2. `chore(deps): 删除过时 server/requirements.txt + 修正 vitest 版本`
3. `chore(ci): 加 ruff 配置 + GitHub Actions workflow`
4. `chore(tests): 删除引用已删 ORM 的 legacy tests/server 子树`
5. `test(trading): 补 orders cancel happy-path 测试`
6. `chore(backend): 删 4 处死代码 / 死导入 / 兼容 shim`
7. `chore(backend): main.py 10 处 startup/shutdown print 改 log.warning`
8. `fix(iquant): 2 处裸 except 改为 queue.Empty`
9. `chore(frontend): 删 2 处死导入 / 死别名`

每 commit 单一目的，可独立 revert。

## 涉及的知识库同步

按 § 十一铁律，commit 完成后同步：
- `知识库/开发流程/测试体系.md` — pytest testpaths + tests/server 删除 + ruff/CI
- `知识库/后端服务/入口与生命周期.md` — main.py 改 logger（删"打印"叙事）
- `知识库/后端服务/交易核心/下单与撤单.md` — cancel 测试 + place.py 删死 import
- `知识库/后端服务/AI助手/` — ai_analysis.py threading 顺序（如不存在则新建）
- `知识库/后端服务/行情数据/快照.md` — quote_snapshots 删别名（如不存在则新建）
- `知识库/后端服务/T0做T/` — tasks.py 删 user_id_kw + _compute_summary 单签名
- `知识库/策略服务/架构概览.md` — iquant 裸 except → queue.Empty
- `知识库/前端/工具函数/format.md` — formatAmount 删别名（如不存在则新建）
- `知识库/前端/页面/Dashboard.md` — STATUS_TYPE 删引用（如不存在则新建）

具体同步写在 `tasks.md`。
# Tasks: Chore P0+P1 清理

## Commit 1 — `chore(ci): 修正 pytest testpaths 指向 server/tests`

- [ ] 改 `pytest.ini:3` `testpaths = tests` → `testpaths = server/tests tests`
- [ ] 验证 `pytest --collect-only` 能跑到工作测试
- [ ] 同步 `知识库/开发流程/测试体系.md:71`（testpaths 描述）

## Commit 2 — `chore(deps): 删除过时 server/requirements.txt + 修正 vitest 版本`

- [ ] 删 `server/requirements.txt`（与 pyproject + uv.lock 矛盾）
- [ ] 改 `client/package.json:32` `vitest@^4.1.9` → `vitest@^1.6.0`
- [ ] 同步 `知识库/脚本工具/数据与环境工具.md`（如有描述）
- [ ] 同步 `知识库/前端/` 工具链文档（如有）

## Commit 3 — `chore(ci): 加 ruff 配置 + GitHub Actions workflow`

- [ ] `pyproject.toml` 加 `[tool.ruff]` section（line-length=120, select=["E","F","W"]）
- [ ] 新建 `.github/workflows/ci.yml`：
  - 后端 job: 安装 uv → `pytest hq/ server/tests/`
  - 前端 job: cd client → `npm ci` → `npm run build`
- [ ] 同步 `知识库/开发流程/测试体系.md`（新增 CI 章节）

## Commit 4 — `chore(tests): 删除引用已删 ORM 的 legacy tests/server 子树`

- [ ] `rm -rf tests/server/` 整个子树（17 文件）
- [ ] `tests/` 根下保留：`test_quote_pattern_subscribe.py`、`test_quota_batch.py`、`stress_quota_5etf.py`、`client/`、`strategy_exec/`
- [ ] `tests/server/test_layer_dependencies.py` 一起删（依赖已删 ORM 模块）
- [ ] 同步 `知识库/开发流程/测试体系.md:33`（legacy/models 章节移除）
- [ ] 同步 `知识库/开发流程/测试体系.md` 文件清单（tests/server/* 行移除）

## Commit 5 — `test(trading): 补 orders cancel happy-path 测试`

- [ ] 新建 `server/tests/test_orders_cancel.py`：
  - 复用 `test_place_async.py` 的 db fixture 模式
  - happy-path: 50→54 撤单（mock rpc_cancel_order）
  - 至少 1 个 case：pre-check status=48 不可撤
- [ ] 同步 `知识库/后端服务/交易核心/下单与撤单.md:118` "测试钩子" 段补一句

## Commit 6 — `chore(backend): 删 4 处死代码 / 死导入 / 兼容 shim`

- [ ] `server/api/orders/place.py:38` 删 `format_ts` import
- [ ] `server/api/ai_analysis.py:36` 删 `import re`；line 64 `import threading` 挪到顶部
- [ ] `server/repo/quote_snapshots.py:26` 删 `QuoteSnapshot = QuoteSnapshots` 死别名
- [ ] `server/services/t0/tasks.py:55,71-72,108,116-117` 删 `user_id_kw` 形参
- [ ] `server/services/t0/tasks.py:767-792` 简化 `_compute_summary` 单签名
- [ ] 同步 `知识库/后端服务/交易核心/下单与撤单.md`（place.py 引用图）
- [ ] 同步 `知识库/后端服务/行情数据/快照.md`（如有；quote_snapshots.py 别名）
- [ ] 同步 `知识库/后端服务/T0做T/`（tasks.py 兼容 shim）

## Commit 7 — `chore(backend): main.py 10 处 startup/shutdown print 改 log.warning`

- [ ] `server/main.py` 10 处 `print("[INIT/SHUTDOWN] ... failed: %s", e)` → `log.warning(...)`
- [ ] 加 `log = logging.getLogger(__name__)` at module top
- [ ] 同步 `知识库/后端服务/入口与生命周期.md:55-69`（startup hooks 行为不变但 logging 一致化）

## Commit 8 — `fix(iquant): 2 处裸 except 改为 queue.Empty`

- [ ] `iquant/runtime_trdapi_rel.py:467-472` 顶部加 `import queue`；`except:` → `except queue.Empty:`
- [ ] `iquant/quota_his.py:273-278` 同上
- [ ] 同步 `知识库/策略服务/架构概览.md`（错误处理段）

## Commit 9 — `chore(frontend): 删 2 处死导入 / 死别名`

- [ ] `client/src/views/Dashboard.vue:169` 删 `STATUS_TYPE`
- [ ] `client/src/utils/format.js:6-16` 删 `formatAmount = formatMoney` 别名
- [ ] `client/src/views/T0Trade.vue:338` `formatAmount` 调用改为 `formatMoney`
- [ ] 同步 `知识库/前端/页面/Dashboard.md`（导入清单）
- [ ] 同步 `知识库/前端/工具函数/format.md`（导出清单）

## 验证（所有 commit 后）

- [ ] `pytest hq/ server/tests/` 通过（基线 71 collected / 64 passed 不得下降）
- [ ] `cd client && npm run build` 通过
- [ ] `cd client && npm run test` 跑通（即使无测试也要 exit 0）
- [ ] `git log --oneline -10` 看 commit 拆得是否单一目的

## 归档

- [ ] 全部 commit 后 `git log -1` 校验
- [ ] 把 spec-deltas/* 合入 `openspec/specs/<cap>/spec.md`
- [ ] `mv openspec/changes/2026-08-25-chore-p0p1-cleanup openspec/changes/archive/`
- [ ] 更新 `openspec/AGENTS.md` § 当前活跃 change 表（移除本 change）
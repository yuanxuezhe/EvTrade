# Design — Restructure Test Layout

## Context

`server/` 当前 72 个生产 .py 文件 + 21 个 `test_*.py` 混杂，导致：
- IDE 目录树噪音（点开 `api/orders/` 看到 `place.py` 旁边有 `test_orders_api.py`）
- pytest 默认不发现 server 测试（`pytest.ini: testpaths = hq`）
- 根 `conftest.py` 36 行 workaround 解决裸名 vs 限定名 import 冲突

frontend (`client/tests/`) 已正确镜像 `client/src/`，是样板。本 change 把 server 测试也按同样模式重整，**顺带**消除根 conftest 的历史包袱。

## Goals / Non-Goals

**Goals:**
- 21 个 server 测试文件移出 `server/` 到 `tests/server/`，目录结构 mirror `server/`
- 测试统一用 `from server.X import Y` 限定名（与生产代码 import 风格一致）
- 删除根 `conftest.py` workaround
- `pytest.ini` 默认发现 server 测试
- 运行时 DB 文件 `evtrade.db` 从源码目录挪到 `data/`
- 新增 `tests/manual/` 约定（手测脚本独立于 pytest 测试）
- 一条 spec 约定记录"测试镜像源码"的布局规则

**Non-Goals:**
- 不引入新测试框架 / 不替换 pytest
- 不重构 server 现有子包（api/orders/、services/push/、services/t0/ 已按业务拆分）
- 不动 `server/ws/endpoint.py` 实现位置（已存在，本 change 只移测试）
- 不动 `scripts/`、`hq/`、`iquant/`、`kb/`、`docs/`、`openspec/`
- 不改生产代码业务逻辑

## Decisions

### D1: 测试目录命名 `tests/server/` (单数)

**选择**：`tests/server/` 而非 `tests/backend/` 或 `tests/api/`

**理由**：
- 与生产代码目录名 1:1 mirror（`server/api/` ↔ `tests/server/api/`），IDE 跳转无歧义
- frontend 用 `client/tests/` 而非 `client/tests/client/`，故 server 用 `tests/server/` 也对称
- 未来若拆出 `tests/iquant-broker-mock/` 等独立测试子项目，`tests/server/` 仍是清晰边界

### D2: 测试文件名按 mirror 模块命名，不保留原 `test_X.py`

**选择**：`server/auth/security.py` 的测试叫 `tests/server/auth/test_security.py`，不是 `test_auth.py`

**理由**：
- 当前 `test_auth.py` 实际测的是 `security.py`，文件名误导
- Mirror 命名让"找 security 模块的测试"成为机械操作（去掉 `.py` 加 `test_` 前缀）
- IDE F12 "go to test" 跳转成为可能

### D3: `test_orders_api.py` (911 行) 按模块拆 3 文件

**选择**：拆为 `test_place.py` + `test_cancel.py` + `test_query.py`，对应 `server/api/orders/{place,cancel,query}.py`

**理由**：
- 911 行单文件违反项目"单文件 < 250 行"硬约束（CLAUDE.md §3）
- 文件已有清晰 section 注释（屏障/下单/撤单/查询），拆 3 文件自然
- 单测失败时定位更快（pytest 输出文件名）

**保留整文件**：601 行的 `test_push_handlers.py` — 暂不拆，按 handler 内分组；超过 800 行再拆

### D4: 删除根 conftest.py 而非迁移内容

**选择**：根 `conftest.py` 直接删除，不复制到 `tests/conftest.py`

**理由**：
- workaround 的本质是"测试用裸名 import 而生产用限定名"导致 SQLAlchemy Base 重复注册
- 测试改限定名 import 后，重复注册自然消失
- 不需要新的 conftest fixture（现有 fixture 已分布在各 test_*.py）

**风险**：若有第三方测试工具（如 pytest-cov / pytest-xdist）依赖根 conftest，需单独处理；当前 `requirements.txt` 检查后无此类依赖。

### D5: pytest.ini 加 `pythonpath = .`

**选择**：`pytest.ini` 加 `pythonpath = .` 而非依赖 conftest.py 改 sys.path

**理由**：
- pytest 7+ 原生支持 `pythonpath` 配置项
- 比 `sys.path.insert` 在 conftest 干净
- 与"删除 conftest"决策一致

### D6: DB 文件移 `data/` 而非 `var/` 或 `tmp/`，不留 fallback

**选择**：`data/evtrade.db`，启动遇 `data/` 缺失直接 fail

**理由**：
- Python 社区惯例：`data/` 用于应用数据，`var/` 用于可变运行时状态（多用于 daemon），`tmp/` 用于临时
- 开发环境 SQLite 文件用户可见，便于排查
- `.gitignore` 加 `data/evtrade.db` 避免误提交
- **不留 fallback**：防止 DB 在两个位置分裂；启动失败是 loud 信号

### D7: pytest.ini testpaths 改为 `hq tests/server`

**选择**：`testpaths = hq tests/server`（同时支持行情服务 + 后端测试）

**理由**：
- hqserver 测试已通过 `testpaths = hq` 生效
- 后端测试新加到 testpaths 后 `pytest` 命令自动跑全部
- frontend 测试由 vitest 单独管，不进 pytest

### D8: 新增 `tests/manual/` 目录放手测脚本

**选择**：`server/test_rpc.py`（手测脚本，3 行 `async def test()`）→ `tests/manual/test_rpc.py`

**理由**：
- S-DPC-008 说测试 MUST 放 `tests/server/`，但 `test_rpc.py` 是 async 调试脚本不是 pytest 测试（无 assert）
- `tests/manual/` 是 pytest 社区惯例（区分 unit tests vs manual scripts）
- `pytest.ini` 加 `pythonpaths` 自动排除 `tests/manual`（不在 testpaths 中，pytest 不会 collect）

### D9: 集成测试 `test_rpc_link.py` 加 `@pytest.mark.integration` 标记

**选择**：移 `tests/server/rpc/test_link.py`，加 mark + `pytest.ini` 配置 CI 默认 skip

**理由**：
- 需要真实 broker（RabbitMQ），CI 无法跑
- pytest mark 标准化：`-m "not integration"` 跳过；`-m integration` 单独跑
- 与"测试放 tests/server/"约定一致（pytest 仍能 collect，只是 CI skip）

### D10: WS 端点测试路径 `tests/server/ws/test_endpoint.py`（impl 不动）

**选择**：`server/test_ws_endpoint.py` → `tests/server/ws/test_endpoint.py`，**不动** `server/ws/endpoint.py`

**理由**：
- `server/ws/endpoint.py` 和 `server/ws/manager.py` **已存在**（v10 simplify-rpc-transport-thin 实施时拆出）
- 本 change 不需要新建 `server/ws/` 子包，已 ready
- 测试 mirror 即可

## Risks / Trade-offs

- **[风险] CI 脚本可能硬编码 `pytest server/` 路径** → 缓解：proposal.md §Impact 已标注；本地 + CI grep 后统一改 `pytest tests/server`
- **[风险] 测试文件 import 改限定名后漏改导致 21 文件失败** → 缓解：拆 commit 逐步迁（commit 3：加新位置文件 + 改 import；commit 5：删旧文件），每步跑 pytest 验证
- **[风险] `data/evtrade.db` 移走后，旧路径仍有文件残留** → 缓解：commit 中加 `git mv` + 旧位置 `.gitignore` 标记；启动脚本强一致（无 fallback）
- **[风险] 本地开发 DB 数据丢失** → 缓解：迁移前备份；本 change 只动文件位置，不改 DB 内容
- **[风险] `test_rpc.py` 移出 `server/` 后，`from rpc.client import` 失败** → 缓解：`tests/manual/` 下用 `python -m` 运行（cwd=项目根），需要 `pythonpath = .` 或脚本内部 `sys.path.insert`
- **[取舍] `test_push_handlers.py` 不拆** — 601 行未超 800 行阈值；按 handler 内分组已清晰；超过 800 再拆

## Migration Plan

按 commit 粒度（每步独立可跑 + 可回滚）：

```
commit 1: docs(openspec) — 新增 dev-process-control S-DPC-008/009 测试布局约定
commit 2: chore(pytest) — pytest.ini 加 tests/server + pythonpath = .  +  exclude tests/manual
commit 3: refactor(tests) — 新增 tests/server/ 全部子目录 + 20 个 pytest 测试文件迁入（import 改限定名）
commit 4: refactor(tests) — 拆分 test_orders_api.py 为 3 文件 + 加 @pytest.mark.integration 到 test_link
commit 5: chore(conftest) — 删除根 conftest.py workaround
commit 6: chore(data) — git mv server/evtrade.db → data/evtrade.db + 改 config.py DB URL + .gitignore
commit 7: chore(repo) — 移 test_rpc.py → tests/manual/ + 跑全量 pytest + 更新 README
```

**回滚策略**：每个 commit 独立可 revert。最大爆炸半径 commit 5（删 conftest），单独 commit 便于快速回退。

## Open Questions

**已解决**（基于探查结果）：

1. ✅ `test_rpc.py`：手测脚本，移到 `tests/manual/`
2. ✅ `test_rpc_link.py`：移 `tests/server/rpc/test_link.py` + `@pytest.mark.integration`
3. ✅ WS 端点路径：`server/ws/endpoint.py` 已存在（v10 实施时拆出），测试镜像即可
4. ✅ DB fallback：不留 fallback，强一致

---

## 验证清单（apply 阶段用）

- `pytest tests/server` 在 Py3.6.8 下无 import 错误
- `pytest tests/server -v` 全绿（46/47 test_push_handlers + 16 test_logflow + 23 test_format_ts 等）
- `pytest tests/server -m "not integration"` 默认 CI 跑（skip test_link）
- `grep "from db import\|from models import\|sys.path.insert" tests/server/` 无残留裸名 import
- `grep "sys.path.insert" tests/manual/test_rpc.py` 唯一 1 处可接受
- `pytest.ini` testpaths 包含 `tests/server`，不含 `tests/manual`
- 根目录 `ls conftest.py` 不存在
- `data/evtrade.db` 存在；`server/evtrade.db` 不存在（或在 .gitignore）
- `evctl.py restart` 后 `/api/health` 200 + DB 可读写
- `tests/server/ws/test_endpoint.py` 通过（覆盖 `server/ws/endpoint.py::register_ws_endpoint`）
# v125 策略可见性与权限矩阵 Implementation Plan (Part 1 — 纯回测)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为策略模块建立显式可见性/权限模型:策略级 `is_public` + 绑定标的 `stock_code`,他人公开策略只读精简可见、不可回测,策略模块改为纯回测(移除实盘/黑盒跟随)。

**Architecture:** 新增 `server/services/script_strategy/access.py` 单一权限模块,替换旧的 `_strategy_public_derived` 隐式派生规则;`strategies.py`/`batches.py` 全部访问经 `access` 判定;API 层删除 `/live` 端点并映射 `BACKTEST_FORBIDDEN→403`;前端 ScriptTask 区分「我的/公开」+ 公开开关 + 标的必选,ScriptDev 他人公开脚本只读。

**Tech Stack:** FastAPI + TableBase(MySQL) + Vue3 (Element Plus) + Vitest + pytest + OpenSpec。

**Spec:** `docs/superpowers/specs/2026-08-11-strategy-visibility-permissions-design.md` (v125, 2026-08-11)

---

## 环境命令(全程)

```bash
# venv python
PY="D:/workspace/EvTrade/.venv/Scripts/python.exe"
# 跑单个后端测试
"$PY" -m pytest tests/server/strategy/test_strategy_v123_service.py -q
# 跑全部策略测试 (含迁移幂等, DB-backed)
"$PY" -m pytest tests/server/strategy/ -q
# 跑迁移 (幂等, 可重复)
"$PY" server/migrations/2026-08-11-add-strategy-visibility.py
# 前端单测
cd client && npx vitest run --config ../tests/client/vitest.config.js tests/client/components/strategy/ScriptTask.test.js
# 后端重启 (memory: 一律走 evctl.py)
"$PY" scripts/evctl.py restart backend
```

⚠️ 迁移 auto-discovery:`scripts/run_all_migrations.py` 按 `2026-*.py` 文件名排序自动执行,新迁移放 `server/migrations/2026-08-11-add-strategy-visibility.py`。

---

## 文件结构

**创建:**
- `server/migrations/2026-08-11-add-strategy-visibility.py` — strategy 表加 is_public + stock_code
- `server/services/script_strategy/access.py` — 可见性/权限模块 (策略模块纯回测)
- `tests/server/strategy/test_access_v125.py` — access 模块单测

**修改:**
- `server/tables/strategy.py` — 8→10 字段 (is_public, stock_code)
- `server/services/script_strategy/_convert.py` — strategy_row_to_dict 输出 is_public/stock_code
- `server/services/script_strategy/strategies.py` — list/get/create/update 显式 is_public, 删 `_strategy_public_derived`
- `server/services/script_strategy/batches.py` — 严格 owner 门禁 + 绑定标的 + 删 create_live_batch
- `server/services/script_strategy/__init__.py` — 移除 create_live_batch 导出
- `server/api/script_strategy/schemas.py` — StrategyCreate.stock_code / StrategyUpdate.is_public / StrategyOut 扩字段 / BacktestRequest.stock_code Optional / 删 LiveRequest+LiveResponse
- `server/api/script_strategy/strategies.py` — 删 live 端点 + 错误码映射 (BACKTEST_FORBIDDEN→403, NO_STRATEGY→404)
- `openspec/specs/strategy/spec.md` — 补 REQ-STRAT-019
- `client/src/api/script_strategy.js` — 删 startLive
- `client/src/components/strategy/BacktestForm.vue` — 标的只读展示 (绑定标的), 存量 NULL 回退输入框
- `client/src/views/ScriptTask.vue` — 我的/公开区分 + 公开开关 + 标的必选 + 移除实盘
- `client/src/views/ScriptDev.vue` — 他人公开脚本只读
- `tests/server/strategy/test_strategy_v123_service.py` — 改签名 + 删 live 测试 + 新增 v125 行为测试
- `tests/server/strategy/test_regression_v123.py` — create_strategy 加 stock_code
- `tests/server/strategy/test_migration_idempotent.py` — 新增可见性迁移幂等测试
- `tests/client/components/strategy/ScriptTask.test.js` — 重写 (实盘→可见性/标的)

---

## Task 1: 迁移 + 表类 + 转换器

**Files:**
- Create: `server/migrations/2026-08-11-add-strategy-visibility.py`
- Modify: `server/tables/strategy.py`
- Modify: `server/services/script_strategy/_convert.py`

- [ ] **Step 1: 创建迁移脚本**

`server/migrations/2026-08-11-add-strategy-visibility.py`:

```python
"""
2026-08-11-add-strategy-visibility.py — DB 迁移 (v125)

strategy 表加 2 列:
- is_public TINYINT NOT NULL DEFAULT 0   策略级可见性: 0=私有(默认) 1=公开(列表可见, 供策略下单选择)
- stock_code VARCHAR(16) NULL            策略绑定标的 (新建时必填, 只针对此标的回测)

幂等: 已存在则跳过。存量行 stock_code=NULL → 回测回退用请求的 stock_code (旧行为)。
仿 2026-08-11-add-task-metric.py 的 INFORMATION_SCHEMA 检查模式。

执行:
    python3 server/migrations/2026-08-11-add-strategy-visibility.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

try:
    from dotenv import load_dotenv
    _ENV_PATH = os.path.join(os.path.dirname(HERE), ".env")
    if os.path.exists(_ENV_PATH):
        load_dotenv(_ENV_PATH, override=False)
except ImportError:
    pass

from sqlalchemy import text, create_engine, inspect  # noqa: E402

DATABASE_URL = os.environ.get("EVTRADE_DB_URL")
if not DATABASE_URL:
    raise RuntimeError("EVTRADE_DB_URL is required (v20 MySQL-only permanent standard).")
if not DATABASE_URL.startswith("mysql"):
    raise RuntimeError(f"Only MySQL is supported. Got URL: {DATABASE_URL[:80]!r}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

COLS = [
    ("is_public",
     "TINYINT NOT NULL DEFAULT 0 "
     "COMMENT '是否公开: 0=私有(默认) 1=公开(列表可见, 供策略下单选择)' AFTER status"),
    ("stock_code",
     "VARCHAR(16) NULL COMMENT '策略绑定标的 (新建时必填, 只针对此标的回测)' AFTER is_public"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text("""
            SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = :t
               AND COLUMN_NAME = :c
             LIMIT 1
        """),
        {"t": table, "c": column},
    ).first()
    return row is not None


def main() -> None:
    print("[start] add strategy visibility columns (is_public / stock_code)")
    print(f"  db: {DATABASE_URL.split('@')[-1] if DATABASE_URL else 'NONE'}")

    with engine.begin() as conn:
        for col, ddl in COLS:
            if _column_exists(conn, "strategy", col):
                print(f"  [skip] column '{col}' already exists")
            else:
                conn.execute(text(f"ALTER TABLE strategy ADD COLUMN {col} {ddl}"))
                print(f"  [OK] added column '{col}'")

    print("\n[verify] strategy 当前字段:")
    insp = inspect(engine)
    new = {c for c, _ in COLS}
    for c in insp.get_columns("strategy"):
        marker = "  <NEW>" if c["name"] in new else ""
        print(f"  {c['name']:20} {str(c['type']):20} nullable={c['nullable']}{marker}")

    engine.dispose()
    print("\n[DONE] migration 完成")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行迁移并验证列存在**

Run: `"$PY" server/migrations/2026-08-11-add-strategy-visibility.py`
Expected: 输出 `[OK] added column 'is_public'` / `[OK] added column 'stock_code'`;verify 列表含 `is_public` + `stock_code`。再跑一次 → `[skip]`(幂等)。

- [ ] **Step 3: 更新 strategy 表类(手改,同步 docstring)**

`server/tables/strategy.py`:

- 头部 docstring `表: strategy  (8 字段...` → `(10 字段...`
- `__fields__` 增加两行:

```python
    __fields__: ClassVar[dict] = {
        'strategy_id': '',
        'user_id': '',
        'script_id': '',
        'name': '',
        'status': '',
        'is_public': '策略是否公开: 0=私有 1=公开',
        'stock_code': '策略绑定标的 (新建时必填)',
        'best_params': '',
        'created_at': '',
        'updated_at': ''
    }
```

- `__field_types__` 增加两行:

```python
    __field_types__: ClassVar[dict] = {
        'strategy_id': 'int',
        'user_id': 'int',
        'script_id': 'varchar(64)',
        'name': 'varchar(64)',
        'status': 'varchar(16)',
        'is_public': 'tinyint',
        'stock_code': 'varchar(16)',
        'best_params': 'json',
        'created_at': 'datetime',
        'updated_at': 'datetime'
    }
```

- import 增加 `Optional`,type hints 增加两行:

```python
from typing import Any, Optional
```
```python
    is_public: int
    stock_code: Optional[str]
```

- [ ] **Step 4: 更新 strategy_row_to_dict**

`server/services/script_strategy/_convert.py`,`strategy_row_to_dict`:

```python
def strategy_row_to_dict(row) -> Dict[str, Any]:
    d = getattr(row, "_data", {})
    return {
        "strategy_id": d.get("strategy_id"),
        "user_id": d.get("user_id"),
        "script_id": d.get("script_id"),
        "name": d.get("name", ""),
        "status": d.get("status", "draft"),
        "is_public": bool(d.get("is_public", 0)),  # v125 显式可见性
        "stock_code": d.get("stock_code"),          # v125 绑定标的
        "best_params": json_loads(d.get("best_params")),
        "created_at": iso(d.get("created_at")),
        "updated_at": iso(d.get("updated_at")),
    }
```

- [ ] **Step 5: 提交**

```bash
git add server/migrations/2026-08-11-add-strategy-visibility.py server/tables/strategy.py server/services/script_strategy/_convert.py
git commit -m "feat(db): strategy 表加 is_public + stock_code (v125 可见性/绑定标的)"
```

---

## Task 2: access.py 权限模块 (TDD)

**Files:**
- Create: `server/services/script_strategy/access.py`
- Create: `tests/server/strategy/test_access_v125.py`

- [ ] **Step 1: 写失败测试**

`tests/server/strategy/test_access_v125.py`:

```python
"""
test_access_v125.py — 策略可见性/权限 access 层单测 (v125)

覆盖:
- strategy_is_public: is_public 0/1 → False/True
- public_view: 精简视图不含 script/best_params
- resolve_strategy: owner / 他人公开 / 他人私有 / 不存在
- require_backtest_access: owner 放行; 他人公开 → BACKTEST_FORBIDDEN; 他人私有/不存在 → NO_STRATEGY

DB-backed (dev MySQL), 唯一 test 数据 + teardown 清理。
"""
import os
import sys

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "server"))

from server.services import script_strategy as svc  # noqa: E402
from server.services.script_strategy import scripts as scripts_svc  # noqa: E402
from server.services.script_strategy import access  # noqa: E402
from server.services.script_strategy.strategies import StrategyError  # noqa: E402
from server.tables import Strategy, StrategyTask, StrategyScript  # noqa: E402

UID = 990010005
UID2 = 990010006

SCHEMA = [
    {"key": "fast", "type": "int", "min": 1, "max": 5, "step": 1, "default": 3},
]

_script_seq = [0]


def _new_script_id() -> str:
    _script_seq[0] += 1
    return f"ut_acc_{UID}_{_script_seq[0]}"


def _cleanup_user(user_id: int) -> None:
    for s in Strategy.query_by_fields({"user_id": user_id}):
        sid = s._data.get("strategy_id")
        for t in StrategyTask.query_by_fields({"strategy_id": sid}):
            StrategyTask.delete_one(id=t._data["id"])
        Strategy.delete_one(strategy_id=sid)
    for sc in StrategyScript.query_by_fields({"user_id": user_id}):
        StrategyScript.delete_one(user_id=user_id, id=sc._data["id"])


@pytest.fixture(autouse=True)
def _clean():
    _cleanup_user(UID)
    _cleanup_user(UID2)
    yield
    _cleanup_user(UID)
    _cleanup_user(UID2)


@pytest.fixture
def strategy_ctx():
    script_id = _new_script_id()
    scripts_svc.create_script(UID, script_id, "def init(self): pass", SCHEMA)
    strat = svc.create_strategy(UID, f"ut策略-{script_id}", script_id, stock_code="600519.SH")
    return {"user_id": UID, "script_id": script_id, "strategy_id": strat["strategy_id"]}


# ─────────────── strategy_is_public / public_view ───────────────

def test_strategy_is_public_flag(strategy_ctx):
    row = Strategy.query_one(strategy_id=strategy_ctx["strategy_id"])
    assert access.strategy_is_public(row) is False
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    assert access.strategy_is_public(Strategy.query_one(strategy_id=strategy_ctx["strategy_id"])) is True


def test_public_view_lean(strategy_ctx):
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    row = Strategy.query_one(strategy_id=strategy_ctx["strategy_id"])
    v = access.public_view(row)
    assert v["strategy_id"] == strategy_ctx["strategy_id"]
    assert v["is_public"] is True
    assert v["stock_code"] == "600519.SH"
    assert "script" not in v
    assert "best_params" not in v


# ─────────────── resolve_strategy ───────────────

def test_resolve_owner_returns_row(strategy_ctx):
    assert access.resolve_strategy(strategy_ctx["strategy_id"], UID) is not None


def test_resolve_other_public_returns_row(strategy_ctx):
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    assert access.resolve_strategy(strategy_ctx["strategy_id"], UID2) is not None


def test_resolve_other_private_none(strategy_ctx):
    assert access.resolve_strategy(strategy_ctx["strategy_id"], UID2) is None


def test_resolve_missing_none():
    assert access.resolve_strategy(99999999, UID) is None


# ─────────────── require_backtest_access ───────────────

def test_require_owner_ok(strategy_ctx):
    assert access.require_backtest_access(strategy_ctx["strategy_id"], UID) is not None


def test_require_other_public_forbidden(strategy_ctx):
    Strategy.update_one({"is_public": 1}, strategy_id=strategy_ctx["strategy_id"])
    with pytest.raises(StrategyError) as ei:
        access.require_backtest_access(strategy_ctx["strategy_id"], UID2)
    assert ei.value.code == "BACKTEST_FORBIDDEN"


def test_require_other_private_no_strategy(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        access.require_backtest_access(strategy_ctx["strategy_id"], UID2)
    assert ei.value.code == "NO_STRATEGY"


def test_require_missing_no_strategy():
    with pytest.raises(StrategyError) as ei:
        access.require_backtest_access(99999999, UID)
    assert ei.value.code == "NO_STRATEGY"
```

- [ ] **Step 2: 运行确认失败**

Run: `"$PY" -m pytest tests/server/strategy/test_access_v125.py -q`
Expected: FAIL (ModuleNotFoundError: access / StrategyError MISSING_STOCK 等)。

- [ ] **Step 3: 实现 access.py**

`server/services/script_strategy/access.py`:

```python
"""
server/services/script_strategy/access.py — 策略可见性/权限判定 (v125)

职责单一: 显式 is_public 判定, 替代旧的"派生自公开脚本即放行"隐式规则。
- strategy_is_public / public_view: 策略是否公开 + 他人公开策略的精简视图
  (只含身份/状态/绑定标的, 不含 script 源码 / params_schema / best_params)
- resolve_strategy: 解析策略 → owner/admin 返回完整行; 他人仅公开返回; 他人私有/不存在 → None
- require_backtest_access: 回测/批次/重测的严格 owner 门禁
  (他人公开 → BACKTEST_FORBIDDEN; 他人私有/不存在 → NO_STRATEGY, 不泄漏存在性)

策略模块 = 纯回测 (v125): 实盘/黑盒跟随已移出 (Part 2 策略下单另行设计)。
"""
from typing import Any, Dict, Optional

from server.services.script_strategy.errors import StrategyError


def strategy_is_public(strat) -> bool:
    """策略行是否公开 (strategy.is_public == 1)."""
    return bool(getattr(strat, "_data", {}).get("is_public", 0))


def public_view(strat) -> Dict[str, Any]:
    """他人公开策略的精简视图 (列表/精简详情). 不含 script/best_params."""
    d = getattr(strat, "_data", {})
    return {
        "strategy_id": d.get("strategy_id"),
        "user_id": d.get("user_id"),
        "script_id": d.get("script_id"),
        "name": d.get("name", ""),
        "status": d.get("status", "draft"),
        "is_public": True,
        "stock_code": d.get("stock_code"),
    }


def resolve_strategy(strategy_id: int, user_id: int, is_admin: bool = False) -> Optional[Any]:
    """解析策略: owner/admin 返回完整行; 他人仅公开策略返回; 他人私有/不存在 → None."""
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        return None
    d = getattr(row, "_data", {})
    if is_admin or d.get("user_id") == user_id:
        return row
    if strategy_is_public(row):
        return row
    return None


def require_backtest_access(strategy_id: int, user_id: int, is_admin: bool = False):
    """回测/批次/重测门禁: 仅 owner/admin 可访问.

    Raises:
        StrategyError: 他人公开 → BACKTEST_FORBIDDEN; 他人私有/不存在 → NO_STRATEGY
    """
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")
    d = getattr(row, "_data", {})
    if is_admin or d.get("user_id") == user_id:
        return row
    if strategy_is_public(row):
        raise StrategyError("BACKTEST_FORBIDDEN", "他人公开策略不可回测 (仅本人可回测)")
    raise StrategyError("NO_STRATEGY", f"strategy_id {strategy_id} 不存在或无权访问")


__all__ = [
    "strategy_is_public", "public_view", "resolve_strategy", "require_backtest_access",
]
```

- [ ] **Step 4: 运行确认通过**

Run: `"$PY" -m pytest tests/server/strategy/test_access_v125.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add server/services/script_strategy/access.py tests/server/strategy/test_access_v125.py
git commit -m "feat(strategy): 新增 access.py 可见性/权限模块 (v125)"
```

---

## Task 3: strategies.py 显式可见性

**Files:**
- Modify: `server/services/script_strategy/strategies.py`
- Modify: `tests/server/strategy/test_strategy_v123_service.py`
- Modify: `tests/server/strategy/test_regression_v123.py`

- [ ] **Step 1: 更新既有测试签名 (create_strategy 加 stock_code)**

`tests/server/strategy/test_regression_v123.py:91`:

```python
    strat = svc.create_strategy(UID, "回归策略", script_id, stock_code="600519.SH")
```

`tests/server/strategy/test_strategy_v123_service.py`:
- 顶部加 `UID2 = 990010003`
- `_clean` fixture 同时清理 UID 与 UID2:

```python
@pytest.fixture(autouse=True)
def _clean(scope="function"):
    _cleanup_user(UID)
    _cleanup_user(UID2)
    yield
    _cleanup_user(UID)
    _cleanup_user(UID2)
```

- 第 71 行 fixture:

```python
    strat = svc.create_strategy(UID, f"ut策略-{script_id}", script_id, stock_code="600519.SH")
```

- 第 87 行:

```python
        svc.create_strategy(UID, "nope", "ut_不存在_脚本", stock_code="600519.SH")
```

- [ ] **Step 2: 追加 v125 行为测试**

在 `tests/server/strategy/test_strategy_v123_service.py` 末尾(实盘门禁区块之前)追加:

```python
# ─────────────── 可见性/权限 (v125) ───────────────

def test_create_strategy_requires_stock():
    with pytest.raises(StrategyError) as ei:
        svc.create_strategy(UID, "x", "ut_不存在_脚本", stock_code="")
    assert ei.value.code == "MISSING_STOCK"


def test_create_strategy_binds_stock(strategy_ctx):
    d = svc.get_strategy(strategy_ctx["strategy_id"], UID)
    assert d["stock_code"] == "600519.SH"
    assert d["is_public"] is False


def test_update_is_public_owner_only(strategy_ctx):
    # 他人不能改公开开关
    assert svc.update_strategy(strategy_ctx["strategy_id"], UID2, False, {"is_public": True}) is None
    assert svc.get_strategy(strategy_ctx["strategy_id"], UID)["is_public"] is False
    # owner 可改
    d = svc.update_strategy(strategy_ctx["strategy_id"], UID, False, {"is_public": True})
    assert d["is_public"] is True


def test_list_strategies_others_public_lean(strategy_ctx):
    svc.update_strategy(strategy_ctx["strategy_id"], UID, False, {"is_public": True})
    items = svc.list_strategies(UID2)
    assert len(items) == 1
    d = items[0]
    assert d["strategy_id"] == strategy_ctx["strategy_id"]
    assert "script" not in d
    assert "best_params" not in d
    assert d["is_public"] is True
    assert d["stock_code"] == "600519.SH"


def test_list_strategies_others_private_hidden(strategy_ctx):
    assert svc.list_strategies(UID2) == []


def test_get_strategy_others_public_lean(strategy_ctx):
    svc.update_strategy(strategy_ctx["strategy_id"], UID, False, {"is_public": True})
    d = svc.get_strategy(strategy_ctx["strategy_id"], UID2)
    assert d is not None
    assert "script" not in d
    assert "best_params" not in d


def test_get_strategy_others_private_none(strategy_ctx):
    assert svc.get_strategy(strategy_ctx["strategy_id"], UID2) is None


def test_backtest_others_private_no_strategy(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        svc.create_backtest_batch(
            UID2, strategy_ctx["strategy_id"], mode="single",
            stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
            params={"fast": 3, "slow": 2},
        )
    assert ei.value.code == "NO_STRATEGY"


def test_backtest_others_public_forbidden(strategy_ctx):
    svc.update_strategy(strategy_ctx["strategy_id"], UID, False, {"is_public": True})
    with pytest.raises(StrategyError) as ei:
        svc.create_backtest_batch(
            UID2, strategy_ctx["strategy_id"], mode="single",
            stock_code="600519.SH", backtest_start_date="20260101", backtest_end_date="20260131",
            params={"fast": 3, "slow": 2},
        )
    assert ei.value.code == "BACKTEST_FORBIDDEN"
```

(实盘门禁 4 个测试 `test_live_gate_*` + `test_live_success_*` 到 **Task 4** 再删,此时保留。)

- [ ] **Step 3: 运行确认失败**

Run: `"$PY" -m pytest tests/server/strategy/test_strategy_v123_service.py -q`
Expected: 新测试 FAIL(create_strategy 不接受 stock_code / 无 is_public 字段)。

- [ ] **Step 4: 实现 strategies.py**

`server/services/script_strategy/strategies.py`:

- 顶部 import 增加:

```python
from server.services.script_strategy.access import (
    public_view,
    strategy_is_public,
)
```

- **删除** `_strategy_public_derived` 函数 (L32-39)。
- `list_strategies` 替换为:

```python
def list_strategies(
    user_id: int, is_admin: bool = False,
    status: Optional[str] = None, only_mine: bool = False,
) -> List[Dict[str, Any]]:
    """列策略: 自己的 (全量) + 他人公开的 (精简视图); admin 看全部 (全量)."""
    from server.tables import Strategy
    if is_admin:
        rows = Strategy.query_all(order="desc")
    else:
        rows = Strategy.query_by_fields({"user_id": user_id})
        if not only_mine:
            for r in Strategy.query_by_fields({"is_public": 1}):
                if r._data.get("user_id") != user_id:
                    rows.append(r)
        rows.sort(key=lambda r: getattr(r, "_data", {}).get("strategy_id", 0), reverse=True)
    out = []
    for r in rows:
        d = strategy_row_to_dict(r)
        if status and d.get("status") != status:
            continue
        if not is_admin and d.get("user_id") != user_id:
            out.append(public_view(r))   # 他人公开策略 → 精简
        else:
            out.append(d)
    return out
```

- `get_strategy` 替换为:

```python
def get_strategy(strategy_id: int, user_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    """策略详情: owner/admin 返回完整 (含脚本); 他人公开返回精简视图; 他人私有/不存在 → None."""
    from server.tables import Strategy
    row = Strategy.query_one(strategy_id=strategy_id)
    if row is None:
        return None
    d = strategy_row_to_dict(row)
    if not is_admin and d.get("user_id") != user_id:
        return public_view(row) if strategy_is_public(row) else None
    d["script"] = _resolve_script(d.get("user_id"), d.get("script_id"))
    return d
```

- `create_strategy` 替换为 (加 stock_code 必填):

```python
def create_strategy(user_id: int, name: str, script_id: str, stock_code: str) -> Dict[str, Any]:
    """创建策略 (必须绑定标的 stock_code, 只针对此标的回测).

    Raises:
        StrategyError: MISSING_STOCK / NO_SCRIPT
    """
    if not stock_code or not stock_code.strip():
        raise StrategyError("MISSING_STOCK", "新建策略必须指定标的 stock_code")
    from server.tables import Strategy
    from server.services.script_strategy.scripts import get_script
    script = get_script(script_id, user_id, is_admin=False)
    if script is None:
        raise StrategyError("NO_SCRIPT", f"script_id {script_id} 不存在或不可用")
    now = datetime.now()
    data = {
        "user_id": user_id,
        "script_id": script_id,
        "name": name,
        "status": "draft",
        "is_public": 0,
        "stock_code": stock_code.strip(),
        "best_params": None,
        "created_at": now,
        "updated_at": now,
    }
    row = Strategy.add_one(data)
    return strategy_row_to_dict(row)
```

- `update_strategy` 的可更新字段加 `is_public`:

```python
    update_data = {}
    for k in ("name", "status"):
        if k in patch and patch[k] is not None:
            update_data[k] = patch[k]
    if "is_public" in patch and patch["is_public"] is not None:
        update_data["is_public"] = 1 if patch["is_public"] else 0
```

- [ ] **Step 5: 运行确认通过**

Run: `"$PY" -m pytest tests/server/strategy/test_strategy_v123_service.py -q`
Expected: PASS(含新 v125 测试;实盘 4 个测试仍在)。

- [ ] **Step 6: 提交**

```bash
git add server/services/script_strategy/strategies.py tests/server/strategy/test_strategy_v123_service.py tests/server/strategy/test_regression_v123.py
git commit -m "feat(strategy): 策略显式 is_public + 绑定标的, 删 _strategy_public_derived (v125)"
```

---

## Task 4: batches.py 严格 owner 门禁 + 绑定标的 + 移除实盘

**Files:**
- Modify: `server/services/script_strategy/batches.py`
- Modify: `server/services/script_strategy/__init__.py`
- Modify: `tests/server/strategy/test_strategy_v123_service.py` (删 live 测试 + 增 stock 测试)

- [ ] **Step 1: 追加 stock 绑定测试 + 删除 live 测试**

`tests/server/strategy/test_strategy_v123_service.py`:

1. **删除** 末尾实盘门禁区块 4 个测试 (`test_live_gate_no_best_params` / `test_live_gate_empty_best_params` / `test_live_gate_param_mismatch` / `test_live_success_creates_live_task`)。`test_retest_live_batch_rejected` **保留**(手动置 mode='live' 校验 NOT_RETESTABLE,不依赖 create_live_batch)。

2. 在该区块位置追加:

```python
def test_list_batches_others_public_forbidden(strategy_ctx):
    svc.update_strategy(strategy_ctx["strategy_id"], UID, False, {"is_public": True})
    with pytest.raises(StrategyError) as ei:
        svc.list_batches(strategy_ctx["strategy_id"], UID2)
    assert ei.value.code == "BACKTEST_FORBIDDEN"


def test_backtest_uses_bound_stock(strategy_ctx):
    # 不传 stock_code → 用绑定标的 600519.SH
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="single",
        backtest_start_date="20260101", backtest_end_date="20260131",
        params={"fast": 3, "slow": 2},
    )
    assert b["stock_code"] == "600519.SH"
    t = StrategyTask.query_one(id=b["task_ids"][0])._data
    assert t["stock_code"] == "600519.SH"


def test_backtest_stock_mismatch(strategy_ctx):
    with pytest.raises(StrategyError) as ei:
        svc.create_backtest_batch(
            UID, strategy_ctx["strategy_id"], mode="single",
            stock_code="000001.SZ", backtest_start_date="20260101", backtest_end_date="20260131",
            params={"fast": 3, "slow": 2},
        )
    assert ei.value.code == "STOCK_MISMATCH"


def test_legacy_null_stock_falls_back_to_request(strategy_ctx):
    Strategy.update_one({"stock_code": None}, strategy_id=strategy_ctx["strategy_id"])
    b = svc.create_backtest_batch(
        UID, strategy_ctx["strategy_id"], mode="single",
        stock_code="000001.SZ", backtest_start_date="20260101", backtest_end_date="20260131",
        params={"fast": 3, "slow": 2},
    )
    assert b["stock_code"] == "000001.SZ"
```

- [ ] **Step 2: 运行确认失败**

Run: `"$PY" -m pytest tests/server/strategy/test_strategy_v123_service.py -q`
Expected: 新测试 FAIL(create_backtest_batch 还允许非 owner;无 STOCK_MISMATCH;list_batches 对公开策略不抛)。

- [ ] **Step 3: 实现 batches.py**

`server/services/script_strategy/batches.py`:

1. **删除** `_require_owned_strategy` 函数 (L30-39) 和顶部 import `_strategy_public_derived`;import 改为:

```python
from server.services.script_strategy.access import require_backtest_access
from server.services.script_strategy.strategies import _resolve_script
```

2. `create_backtest_batch` 开头改为(严格 owner + 绑定标的):

```python
    strat = require_backtest_access(strategy_id, user_id)
    sd = strat._data
    script = get_script(sd.get("script_id"), user_id, is_admin=False)
    if script is None:
        raise StrategyError("NO_SCRIPT", "策略所属脚本不存在或已删除")
    schema = script.get("params_schema") or []
    schema_by_key = {s.get("key"): s for s in schema}

    if not backtest_start_date or not backtest_end_date:
        raise StrategyError("MISSING_DATES", "回测必须指定 backtest_start_date / backtest_end_date")

    # v125 绑定标的: 策略有绑定 → 必须用它 (提供且不一致 → STOCK_MISMATCH);
    # 存量 NULL 行回退请求的 stock_code (旧行为)
    bound = sd.get("stock_code")
    if bound:
        if stock_code and stock_code != bound:
            raise StrategyError(
                "STOCK_MISMATCH", f"策略已绑定标的 {bound}, 与请求标的 {stock_code} 不一致")
        effective_stock = bound
    else:
        effective_stock = stock_code
```

   然后函数体内所有 `stock_code` 引用改为 `effective_stock`(create_task 调用 + return dict 的 `"stock_code":` 键)。

3. 签名改 `stock_code: Optional[str] = None`:

```python
def create_backtest_batch(
    user_id: int,
    strategy_id: int,
    *,
    mode: str,  # 'single' | 'sweep'
    stock_code: Optional[str] = None,
    backtest_start_date: str,
    backtest_end_date: str,
    params: Optional[Dict[str, Any]] = None,
    param_ranges: Optional[Dict[str, Any]] = None,
    period: Optional[str] = None,
    fields: Optional[str] = None,
    metric: str = "sharpe",
    concurrency: int = 2,
) -> Dict[str, Any]:
```

4. `list_batches` / `list_batch_tasks` / `retest_batch` 中:

```python
    strat = _require_owned_strategy(strategy_id, user_id, is_admin=is_admin)
    if strat is None:
        return None   # 或 raise NO_STRATEGY
```
→
```python
    strat = require_backtest_access(strategy_id, user_id, is_admin=is_admin)
```

   (`list_batches`/`list_batch_tasks` 删掉 `if strat is None: return None`;`retest_batch` 删掉 `raise StrategyError("NO_STRATEGY", ...)`。)

5. **删除** `create_live_batch` 函数 (L314-356) 与模块 docstring 里对应的行。

6. 模块 docstring 头部更新: 删 `create_live_batch` 行, 注明"v125: 策略模块纯回测"。

- [ ] **Step 4: 更新 __init__.py 导出**

`server/services/script_strategy/__init__.py`:删除 import `create_live_batch` 与 `__all__` 中的 `"create_live_batch"`,docstring 同步。

- [ ] **Step 5: 运行确认通过**

Run: `"$PY" -m pytest tests/server/strategy/ -q`
Expected: 全部 PASS(含 test_access_v125.py / test_regression_v123.py)。

- [ ] **Step 6: 提交**

```bash
git add server/services/script_strategy/batches.py server/services/script_strategy/__init__.py tests/server/strategy/test_strategy_v123_service.py
git commit -m "feat(strategy): 回测严格 owner 门禁 + 绑定标的 + 删 create_live_batch (v125 纯回测)"
```

---

## Task 5: API 层 (schemas + 端点)

**Files:**
- Modify: `server/api/script_strategy/schemas.py`
- Modify: `server/api/script_strategy/strategies.py`

- [ ] **Step 1: schemas.py**

`server/api/script_strategy/schemas.py`:

1. `StrategyCreate`:

```python
class StrategyCreate(BaseModel):
    name: str
    script_id: str  # v90+ 脚本 id 是用户自命名 varchar
    stock_code: str  # v125 必填: 策略绑定标的, 只针对此标的回测
```

2. `StrategyUpdate`:

```python
class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|active|archived)$")
    is_public: Optional[bool] = None  # v125 公开/私有开关 (仅 owner)
```

3. `StrategyOut`:

```python
class StrategyOut(BaseModel):
    strategy_id: int
    user_id: int
    script_id: str
    name: str
    status: str
    is_public: bool = False
    stock_code: Optional[str] = None
    best_params: Optional[Dict[str, Any]] = None
    script: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

4. `BacktestRequest.stock_code` 改 Optional:

```python
    stock_code: Optional[str] = None  # v125: 标的由策略绑定决定, 提供且不匹配 → 400 STOCK_MISMATCH
```

5. **删除** `LiveRequest` / `LiveResponse` 两个类 (v125 策略模块纯回测)。

- [ ] **Step 2: api/strategies.py**

`server/api/script_strategy/strategies.py`:

1. import 删 `LiveRequest, LiveResponse`:

```python
from server.api.script_strategy.schemas import (
    BacktestRequest,
    BacktestResponse,
    BatchOut,
    StrategyCreate,
    StrategyOut,
    StrategyUpdate,
)
```

2. 模块 docstring:删 `POST .../live` 行,注"v125: 策略模块纯回测,无实盘"。

3. `create_strategy_endpoint`:

```python
        return svc.create_strategy(user.id, name=req.name, script_id=req.script_id, stock_code=req.stock_code)
```

4. `backtest_endpoint` 错误映射改为 code_map:

```python
    except StrategyError as e:
        code_map = {
            "NO_STRATEGY": 404,
            "BACKTEST_FORBIDDEN": 403,
        }
        raise HTTPException(
            status_code=code_map.get(e.code, 400),
            detail={"code": e.code, "msg": e.msg},
        )
```

5. `batches_endpoint` / `batch_tasks_endpoint` 包 try/except (list_* 现在抛 StrategyError):

```python
@router.get("/strategies/{strategy_id}/batches", response_model=List[BatchOut])
def batches_endpoint(strategy_id: int, user: User = Depends(get_current_user)):
    try:
        return svc.list_batches(strategy_id, user.id, is_admin=(user.role == "admin"))
    except StrategyError as e:
        code_map = {"NO_STRATEGY": 404, "BACKTEST_FORBIDDEN": 403}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail={"code": e.code, "msg": e.msg})
```

```python
@router.get("/strategies/{strategy_id}/batches/{batch_no}/tasks")
def batch_tasks_endpoint(
    strategy_id: int, batch_no: int, user: User = Depends(get_current_user),
):
    try:
        return svc.list_batch_tasks(strategy_id, batch_no, user.id, is_admin=(user.role == "admin"))
    except StrategyError as e:
        code_map = {"NO_STRATEGY": 404, "BACKTEST_FORBIDDEN": 403}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail={"code": e.code, "msg": e.msg})
```

6. `retest_batch_endpoint` 的 code_map 加一行:

```python
        code_map = {
            "NO_STRATEGY": 404,
            "BATCH_NOT_FOUND": 404,
            "BATCH_RUNNING": 409,
            "BACKTEST_FORBIDDEN": 403,
        }
```

7. **删除** 末尾整个「实盘门禁」区块 (live_endpoint, L266-298)。

- [ ] **Step 3: 冒烟编译 + 重启后端**

Run:
```bash
"$PY" -c "from server.api.script_strategy import strategies; import server.services.script_strategy as svc; print('no create_live_batch:', not hasattr(svc, 'create_live_batch')); print('ok')"
"$PY" scripts/evctl.py restart backend
```
Expected: 无 import 错误;`create_live_batch` 不存在;后端健康。

- [ ] **Step 4: 提交**

```bash
git add server/api/script_strategy/schemas.py server/api/script_strategy/strategies.py
git commit -m "feat(api): 删 /live 端点, BACKTEST_FORBIDDEN→403, 策略 CRUD 扩可见性/标的 (v125)"
```

---

## Task 6: openspec spec — REQ-STRAT-019

**Files:**
- Modify: `openspec/specs/strategy/spec.md`

- [ ] **Step 1: 追加 REQ-STRAT-019**

在 `openspec/specs/strategy/spec.md` 的 `### REQ-STRAT-018` 之后、`## Cross References` 之前追加:

````markdown
### REQ-STRAT-019: 策略可见性与权限矩阵 (v125 change, 2026-08-11)

策略模块改为**纯回测**:策略级显式 `is_public` + 绑定标的 `stock_code`,他人公开策略只读精简可见、不可回测。实盘/黑盒跟随移出本模块(Part 2 策略下单另行设计)。

**数据模型**(`strategy` 表 +2 列,迁移 `2026-08-11-add-strategy-visibility.py`):

- `is_public: tinyint NOT NULL DEFAULT 0` — 0=私有(默认) 1=公开(列表可见,供策略下单选择)
- `stock_code: varchar(16) NULL` — 策略绑定标的(新建必填,只针对此标的回测;存量 NULL 回退请求标的)
- `create_strategy` 必填 `stock_code`;标的创建后不可改(update 不含该字段)

**权限矩阵**:

| 操作 | 本人(owner) | 他人·公开策略 | 他人·私有策略 |
|---|---|---|---|
| 列表可见 | ✓(完整) | ✓(精简卡片) | ✗ 404 |
| 查看详情 | ✓(含脚本/参数) | ✓ 精简(不含代码/best_params) | ✗ 404 |
| 修改/删除/公开开关 | ✓ | ✗ | ✗ |
| 回测/批次/重测 | ✓ | ✗ 403 BACKTEST_FORBIDDEN | ✗ 404 STRATEGY_NOT_FOUND |

- 隐私原则:他人**私有**策略一律 `404 STRATEGY_NOT_FOUND`(不泄漏存在性);他人**公开**策略的受限操作(回测)返回 `403`(用户已在列表看到它)。
- 错误码:`403 BACKTEST_FORBIDDEN` / `404 STRATEGY_NOT_FOUND` / `400 STOCK_MISMATCH` / `400 MISSING_STOCK`。

**端点变更**:

- 删除 `POST /strategies/{strategy_id}/live`(策略模块纯回测;实盘能力 Part 2 重建)
- `POST /strategies/{strategy_id}` 请求加必填 `stock_code`
- `PUT /strategies/{strategy_id}` 可改 `is_public`
- `GET /strategies` / `GET /strategies/{id}`:他人公开返回精简视图(`is_public` + `stock_code`,无 `script`/`best_params`)
- `BacktestRequest.stock_code` 改 Optional(标的由策略绑定决定;提供且不匹配 → `400 STOCK_MISMATCH`)

**前端**:

- `ScriptTask.vue`:新建策略必选标的;列表区分「我的 / 公开」;他人公开策略**只读精简卡片**(无回测/批次/编辑入口);公开/私有开关仅 owner;移除「实盘」按钮 + live 徽章
- `ScriptDev.vue`:他人公开脚本表单只读(禁用编辑/删除/保存)

#### Scenario: 作者发布公开策略

- **GIVEN** 用户 A 创建策略(必填标的 600519.SH),设 `is_public=true`
- **WHEN** 用户 B 调 GET /strategies
- **THEN** 看到 A 的策略精简卡片(名称/标的/owner/is_public),不含脚本源码与 best_params
- **AND** B 调 GET /strategies/{id} → 精简视图;调回测/批次 → `403 {"code": "BACKTEST_FORBIDDEN"}`

#### Scenario: 非 owner 回测被拒

- **GIVEN** 用户 A 的私有策略
- **WHEN** 用户 B 调 GET /strategies 或回测
- **THEN** 一律 `404 {"code": "STRATEGY_NOT_FOUND"}`,不泄漏策略存在性

#### Scenario: 策略绑定标的 + 回测标的失配

- **GIVEN** 策略绑定 600519.SH
- **WHEN** 回测请求带 `stock_code=000001.SZ`
- **THEN** 返回 `400 {"code": "STOCK_MISMATCH"}`
- **AND** 回测不带 stock_code → 固定用策略绑定标的 600519.SH
````

- [ ] **Step 2: 提交**

```bash
git add openspec/specs/strategy/spec.md
git commit -m "docs(spec): 补 REQ-STRAT-019 策略可见性与权限矩阵 (v125)"
```

---

## Task 7: 前端 API 客户端 — 删 startLive

**Files:**
- Modify: `client/src/api/script_strategy.js`

- [ ] **Step 1: 删除 startLive**

`client/src/api/script_strategy.js`:
- 模块 docstring 第 10 行 `*   实盘:          startLive` 删除
- 删除「实盘门禁 (v123)」区块 (L103-109):

```js
  // ─────────────── 实盘门禁 (v123) ───────────────

  async startLive(id, payload) {
    // payload: { stock_code } — best_params 门禁在后端, 400 NO_BEST_PARAMS
    const { data } = await http.post(`/script-strategy/strategies/${id}/live`, payload)
    return data
  },
```

- `createStrategy` 注释更新:

```js
  async createStrategy(payload) {
    // payload: { name, script_id, stock_code } (标的必填, 策略只针对此标的回测)
    const { data } = await http.post('/script-strategy/strategies', payload)
    return data
  },
```

- [ ] **Step 2: 提交**

```bash
git add client/src/api/script_strategy.js
git commit -m "feat(client): 移除 startLive, createStrategy 加标的 (v125 纯回测)"
```

---

## Task 8: BacktestForm.vue — 标的只读展示

**Files:**
- Modify: `client/src/components/strategy/BacktestForm.vue`

- [ ] **Step 1: 改 props + 标的字段**

`client/src/components/strategy/BacktestForm.vue`:

1. props 加 `stockCode`:

```js
const props = defineProps({
  schema: { type: Array, default: () => [] },
  visible: { type: Boolean, default: false },
  stockCode: { type: String, default: '' },  // v125 策略绑定标的 (只读展示)
})
```

2. 模板「标的」form-item 替换为(有绑定 → 只读文本;存量 NULL → 保留输入框兜底):

```html
      <el-form-item label="标的">
        <template v-if="stockCode">
          <span class="bf-stock-bound" data-el="bf-stock">{{ stockCode }}</span>
        </template>
        <el-input v-else v-model="stock_code" placeholder="如 600519.SH" data-el="bf-stock" />
      </el-form-item>
```

3. `onSubmit` 移除必填校验 + payload 只带非空 stock_code:

```js
function onSubmit() {
  if (!dateRange.value || !dateRange.value[0] || !dateRange.value[1]) {
    ElMessage.warning('请选择回测起止日期')
    return
  }
  const payload = {
    mode: mode.value,
    backtest_start_date: dateRange.value[0],
    backtest_end_date: dateRange.value[1],
    period: period.value,
  }
  // v125: 标的由策略绑定; 仅存量 NULL 策略用输入兜底
  if (stock_code.value) payload.stock_code = stock_code.value
  ...
```

4. 样式加一行:

```css
.bf-stock-bound { font-weight: 600; color: var(--text-secondary); }
```

- [ ] **Step 2: 提交**

```bash
git add client/src/components/strategy/BacktestForm.vue
git commit -m "feat(client): BacktestForm 标的改只读展示绑定标的 (v125)"
```

---

## Task 9: ScriptTask.vue — 我的/公开 + 开关 + 标的 + 移除实盘

**Files:**
- Modify: `client/src/views/ScriptTask.vue`

- [ ] **Step 1: state / computed 改动**

`client/src/views/ScriptTask.vue`:

1. 状态加 `currentUserId`,`createForm` 加 `stock_code`:

```js
const currentUserId = ref(null)
const createForm = ref({ name: '', script_id: null, stock_code: '' })
```

2. 删 `liveReady` computed;加 `isOwner`:

```js
const schema = computed(() => strategyDetail.value?.script?.params_schema || [])
const isOwner = computed(() =>
  strategyDetail.value != null && strategyDetail.value.user_id === currentUserId.value
)
```

3. 删 `hasBestParams` 函数(仅 option 的实盘 tag 用)。

- [ ] **Step 2: template 改动**

1. 策略下拉 option — 实盘 tag 换公开/私有 + owner:

```html
          <el-option
            v-for="s in strategies"
            :key="s.strategy_id"
            :value="s.strategy_id"
            :label="s.name"
          >
            <span>{{ s.name }}</span>
            <span class="st-opt-meta">#{{ s.strategy_id }} · {{ scriptNameById(s.script_id) }}</span>
            <el-tag v-if="s.is_public" size="small" type="success" effect="plain">公开</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">私有</el-tag>
            <el-tag v-if="s.user_id !== currentUserId" size="small" type="warning" effect="plain">
              u/{{ s.user_id }}
            </el-tag>
          </el-option>
```

2. 策略条 — 标的 + 公开开关 + 移除实盘按钮/徽章:

```html
    <!-- 策略工具栏: 标的 / 公开开关 (仅 owner) -->
    <div v-if="strategyDetail" class="st-strategy-bar">
      <div class="st-strategy-info">
        <span class="st-strategy-name">{{ strategyDetail.name }}</span>
        <el-tag size="small" effect="plain">{{ strategyDetail.status }}</el-tag>
        <el-tag size="small" type="info" effect="plain">标的 {{ strategyDetail.stock_code || '未绑定' }}</el-tag>
        <el-tag v-if="!isOwner" size="small" type="warning" effect="dark">他人公开策略 · 只读</el-tag>
        <el-tag v-else :type="strategyDetail.is_public ? 'success' : 'info'" effect="dark" data-el="st-public-tag">
          {{ strategyDetail.is_public ? '公开' : '私有' }}
        </el-tag>
        <span v-if="isOwner && bestParamsText" class="st-best-params" :title="bestParamsText">最佳参数: {{ bestParamsText }}</span>
      </div>
      <div class="st-strategy-actions">
        <el-button v-if="isOwner" type="primary" @click="openBacktest" data-el="st-backtest">回测</el-button>
        <el-switch
          v-if="isOwner"
          v-model="strategyDetail.is_public"
          active-text="公开"
          inactive-text="私有"
          @change="onTogglePublic"
          data-el="st-public-switch"
        />
      </div>
    </div>
```

3. 批次卡片包 `v-if="isOwner"`;他人公开给只读提示:

```html
    <!-- 批次列表 (仅 owner) -->
    <el-card v-if="isOwner" shadow="never" class="st-card" data-el="st-batches-card">
```
```html
    <el-empty v-else-if="strategyDetail && !isOwner" description="他人公开策略只读: 不可查看批次/详情/回测" />
```

4. 批次表「模式」列去掉 live 分支:

```html
        <el-table-column label="模式" width="90">
          <template #default="{ row }">
            <el-tag size="small" type="info">回测</el-tag>
            <el-tag v-if="row.abandoned" size="small" type="info" effect="dark">已废弃</el-tag>
          </template>
        </el-table-column>
```

5. 新建策略 dialog 加「绑定标的」:

```html
        <el-form-item label="绑定标的" required>
          <el-input v-model="createForm.stock_code" placeholder="如 600519.SH" data-el="st-create-stock" />
        </el-form-item>
```

- [ ] **Step 3: script 逻辑改动**

`client/src/views/ScriptTask.vue` `<script setup>`:

1. 删 `onLive` 函数 (L356-382) 与 `_canRetest` 里的 `batch.mode === 'live'` 判断:

```js
// v124 重测: 仅回测批次 (无运行中/排队 task)
function _canRetest(batch) {
  if (!batch) return false
  const running = (batch.task_count || 0) - (batch.finished_count || 0)
    - (batch.failed_count || 0) - (batch.abandoned_count || 0)
  return running <= 0
}
```

2. `loadBatches` 加 owner 守卫(他人公开策略不请求,避免 403 弹错):

```js
async function loadBatches() {
  if (strategyId.value == null || !isOwner.value) return
  batchesLoading.value = true
  try {
    batches.value = (await scriptStrategyApi.listBatches(strategyId.value)) || []
  } catch (e) {
    ElMessage.error('加载批次失败: ' + _errMsg(e))
  } finally {
    batchesLoading.value = false
  }
}
```

3. `openCreate` / `onCreateStrategy` 重置 + 校验标的:

```js
function openCreate() {
  createForm.value = { name: '', script_id: null, stock_code: '' }
  createOpen.value = true
}

async function onCreateStrategy() {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请填写策略名称')
    return
  }
  if (!createForm.value.script_id) {
    ElMessage.warning('请选择脚本')
    return
  }
  if (!createForm.value.stock_code.trim()) {
    ElMessage.warning('请填写策略绑定标的')
    return
  }
  creating.value = true
  try {
    const s = await scriptStrategyApi.createStrategy({
      name: createForm.value.name.trim(),
      script_id: createForm.value.script_id,
      stock_code: createForm.value.stock_code.trim(),
    })
    ...
```

4. 新增 `onTogglePublic`:

```js
async function onTogglePublic(val) {
  if (strategyId.value == null || val == null) return
  try {
    const d = await scriptStrategyApi.updateStrategy(strategyId.value, { is_public: val })
    strategyDetail.value = d
    ElMessage.success(val ? '策略已设为公开' : '策略已设为私有')
    await loadStrategies()  // 刷新列表里的公开/私有标记
  } catch (e) {
    strategyDetail.value = { ...strategyDetail.value, is_public: !val }  // 回滚
    ElMessage.error('切换失败: ' + _errMsg(e))
  }
}
```

5. `onMounted` 读 currentUserId (与 ScriptDev 同模式):

```js
onMounted(async () => {
  await loadStrategies()
  if (strategyId.value != null) {
    await loadStrategyDetail()
    await loadBatches()
  }
  try {
    scripts.value = (await scriptStrategyApi.listScripts()) || []
  } catch (e) { /* 脚本库加载失败不阻塞主流程 */ }
  try {
    const u = JSON.parse(localStorage.getItem('user') || '{}')
    currentUserId.value = u.id || null
  } catch (e) {
    currentUserId.value = null
  }
})
```

6. 模块顶部注释更新:删「实盘门禁」描述,注明「策略模块纯回测 (v125)」。

- [ ] **Step 4: 提交**

```bash
git add client/src/views/ScriptTask.vue
git commit -m "feat(client): ScriptTask 我的/公开区分 + 公开开关 + 标的必选, 移除实盘 (v125)"
```

---

## Task 10: ScriptDev.vue — 他人公开脚本只读

**Files:**
- Modify: `client/src/views/ScriptDev.vue`

- [ ] **Step 1: 加 isReadonly computed**

`client/src/views/ScriptDev.vue` `<script setup>`:

```js
const isReadonly = computed(() =>
  currentScript.value != null && currentScript.value.user_id !== currentUserId.value
)
```

- [ ] **Step 2: template 只读禁用**

`client/src/views/ScriptDev.vue` `<template>`:

1. 右侧 pane 顶部加只读横幅 (form 之前):

```html
        <el-alert
          v-if="isReadonly"
          type="warning"
          :closable="false"
          show-icon
          title="他人公开脚本 · 只读"
          description="可查看源码与参数, 但无权修改。可据此新建自己的策略。"
          class="sd-ro-banner"
          data-el="sd-readonly-banner"
        />
```

2. 表单字段禁用 (name / status / description / textarea):

```html
              <el-input v-model="form.name" ... :disabled="isReadonly" data-el="sd-name" />
```
```html
              <el-select v-model="form.status" style="width: 120px" :disabled="isReadonly">
```
```html
              <el-input v-model="form.description" ... :disabled="isReadonly" />
```
```html
            <textarea
              ref="editorRef"
              v-model="form.code"
              class="sd-textarea"
              spellcheck="false"
              :disabled="isReadonly"
              data-el="sd-code"
              @scroll="syncScroll"
            />
```

3. 参数 schema 区禁用:新增参数按钮 + 单元格输入:

```html
            <el-button :icon="Plus" size="small" plain :disabled="isReadonly" @click="addParam" data-el="sd-add-param">
```
```html
              <template #default="{ row }">
                <el-input v-model="row.key" size="small" placeholder="key" :disabled="isReadonly" />
              </template>
```
```html
              <template #default="{ row }">
                <el-select v-model="row.type" size="small" :disabled="isReadonly">
```
```html
                <el-input-number v-if="row.type !== 'choice'" v-model="row.min" size="small" :step="row.type === 'int' ? 1 : 0.1" :disabled="isReadonly" />
```
```html
                <el-input-number v-if="row.type !== 'choice'" v-model="row.max" size="small" :step="row.type === 'int' ? 1 : 0.1" :disabled="isReadonly" />
```
```html
                <el-input-number v-if="row.type !== 'choice'" v-model="row.step" size="small" :step="0.1" :min="0.001" :disabled="isReadonly" />
```
```html
                <el-input-number v-if="row.type !== 'choice'" v-model="row.default" size="small" :disabled="isReadonly" />
```
```html
                <el-input
                  v-if="row.type === 'choice'"
                  v-model="row.valuesStr"
                  size="small"
                  placeholder="逗号分隔, e.g. 1.5,2.0,3.0"
                  :disabled="isReadonly"
                  @change="onValuesStrChange(row)"
                />
```
```html
                <el-button :icon="Delete" size="small" link type="danger" :disabled="isReadonly" @click="form.params_schema.splice($index, 1)" />
```

4. 底部按钮禁用 (删除 / 保存 / 测试回测):

```html
          <el-button :icon="Delete" v-if="form.id" type="danger" plain :disabled="isReadonly" @click="onDelete" data-el="sd-delete">删除</el-button>
          <el-button :icon="Document" type="primary" :loading="saving" :disabled="isReadonly" @click="onSave" data-el="sd-save">
            保存
          </el-button>
          <el-button :icon="VideoPlay" type="success" :loading="testing" :disabled="isReadonly" @click="onTestBacktest" data-el="sd-test">
            去测试回测
          </el-button>
```

- [ ] **Step 3: 样式加横幅间距**

```css
.sd-ro-banner { margin-bottom: var(--space-3); }
```

- [ ] **Step 4: 提交**

```bash
git add client/src/views/ScriptDev.vue
git commit -m "feat(client): ScriptDev 他人公开脚本只读 (v125 R4)"
```

---

## Task 11: 前端测试重写 (ScriptTask.test.js)

**Files:**
- Modify: `tests/client/components/strategy/ScriptTask.test.js`

- [ ] **Step 1: 重写测试文件**

整个文件替换为:

```js
/**
 * ScriptTask.test.js — 两段式编排页: 我的/公开区分 + 公开开关 + 标的绑定 (v125)
 *
 * 覆盖:
 * - owner: 显示 公开/私有 开关 + 标的; onTogglePublic → updateStrategy({is_public})
 * - 他人公开策略: 只读 (isOwner=false, 批次不加载)
 * - 新建策略: 缺标的拒绝; 有标的 → createStrategy 含 stock_code
 * - 实盘入口已移除 (无 onLive / liveReady)
 */
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ref } from 'vue'
import '../../setup-view'
import { mountView, flushPromises } from '../../setup-view'

const mocks = vi.hoisted(() => ({
  listStrategies: vi.fn(),
  getStrategy: vi.fn(),
  listBatches: vi.fn(),
  listBatchTasks: vi.fn(),
  getTask: vi.fn(),
  listScripts: vi.fn(),
  backtestStrategy: vi.fn(),
  updateStrategy: vi.fn(),
  createStrategy: vi.fn(),
  stopTask: vi.fn(),
  retestBatch: vi.fn(),
}))

vi.mock('@/api/script_strategy', () => ({
  scriptStrategyApi: {
    listStrategies: mocks.listStrategies,
    getStrategy: mocks.getStrategy,
    listBatches: mocks.listBatches,
    listBatchTasks: mocks.listBatchTasks,
    getTask: mocks.getTask,
    listScripts: mocks.listScripts,
    backtestStrategy: mocks.backtestStrategy,
    updateStrategy: mocks.updateStrategy,
    createStrategy: mocks.createStrategy,
    stopTask: mocks.stopTask,
    retestBatch: mocks.retestBatch,
  },
}))

vi.mock('@/stores/ws', () => ({
  useWsStore: () => ({ lastTaskProgress: ref(null) }),
}))

import { ElMessage } from 'element-plus'
import ScriptTask from '@/views/ScriptTask.vue'

function _strategy(over = {}) {
  return { strategy_id: 1, user_id: 1, script_id: 's1', name: '双均线',
           status: 'draft', is_public: false, stock_code: '600519.SH',
           best_params: null, script: { params_schema: [] }, ...over }
}

function _login(uid) {
  localStorage.setItem('user', JSON.stringify({ id: uid }))
}

describe('ScriptTask (v125 可见性 + 标的)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
    _login(1)
    mocks.listStrategies.mockResolvedValue([
      { strategy_id: 1, user_id: 1, script_id: 's1', name: '双均线', is_public: false, stock_code: '600519.SH' },
    ])
    mocks.listBatches.mockResolvedValue([])
    mocks.listScripts.mockResolvedValue([])
    mocks.getTask.mockResolvedValue({})
    ElMessage.warning.mockClear()
  })

  it('owner: isOwner=true, 显示标的; onTogglePublic → updateStrategy({is_public:true})', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy())
    mocks.updateStrategy.mockResolvedValue(_strategy({ is_public: true }))
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.vm.isOwner).toBe(true)
    expect(wrapper.vm.strategyDetail.stock_code).toBe('600519.SH')
    await wrapper.vm.onTogglePublic(true)
    expect(mocks.updateStrategy).toHaveBeenCalledWith(1, { is_public: true })
    expect(wrapper.vm.strategyDetail.is_public).toBe(true)
  })

  it('他人公开策略 → 只读: isOwner=false, 批次不加载', async () => {
    mocks.listStrategies.mockResolvedValue([
      { strategy_id: 2, user_id: 99, script_id: 's1', name: '他人策略', is_public: true, stock_code: '000001.SZ' },
    ])
    mocks.getStrategy.mockResolvedValue(
      _strategy({ strategy_id: 2, user_id: 99, is_public: true, stock_code: '000001.SZ', script: null })
    )
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.vm.isOwner).toBe(false)
    expect(mocks.listBatches).not.toHaveBeenCalled()
  })

  it('新建策略: 缺标的拒绝; 有标的 → createStrategy 含 stock_code', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy())
    mocks.createStrategy.mockResolvedValue(_strategy())
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    wrapper.vm.openCreate()
    wrapper.vm.createForm.name = '新策略'
    wrapper.vm.createForm.script_id = 's1'
    await wrapper.vm.onCreateStrategy()
    expect(ElMessage.warning).toHaveBeenCalledWith('请填写策略绑定标的')
    expect(mocks.createStrategy).not.toHaveBeenCalled()
    wrapper.vm.createForm.stock_code = '600519.SH'
    await wrapper.vm.onCreateStrategy()
    expect(mocks.createStrategy).toHaveBeenCalledWith({
      name: '新策略', script_id: 's1', stock_code: '600519.SH',
    })
  })

  it('实盘入口已移除 (无 onLive / liveReady)', async () => {
    mocks.getStrategy.mockResolvedValue(_strategy({ best_params: { fast: 5 } }))
    const wrapper = mountView(ScriptTask)
    await flushPromises()
    expect(wrapper.vm.onLive).toBeUndefined()
    expect(wrapper.vm.liveReady).toBeUndefined()
  })
})
```

- [ ] **Step 2: 运行前端测试**

Run: `cd client && npx vitest run --config ../tests/client/vitest.config.js tests/client/components/strategy/ScriptTask.test.js`
Expected: 4 个测试 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/client/components/strategy/ScriptTask.test.js
git commit -m "test(client): 重写 ScriptTask.test.js 覆盖 v125 可见性/标的, 移除实盘用例"
```

---

## Task 12: 全量验证 + 迁移幂等 + 重启

**Files:** (无代码改动)

- [ ] **Step 1: 跑迁移 + 幂等复跑**

Run:
```bash
"$PY" server/migrations/2026-08-11-add-strategy-visibility.py
"$PY" server/migrations/2026-08-11-add-strategy-visibility.py   # 二次 → 全 [skip]
```
Expected: 第一次新增列, 第二次全部 skip。

- [ ] **Step 2: 迁移幂等测试追加 (test_migration_idempotent.py)**

`tests/server/strategy/test_migration_idempotent.py` 追加 (顶部常量 + 末尾测试):

```python
MIG_VISIBILITY = os.path.join(
    _PROJECT_ROOT, "server", "migrations", "2026-08-11-add-strategy-visibility.py")
```
```python
def test_visibility_migration_reapply_idempotent():
    """strategy 可见性迁移再跑一次 → 不抛错, 新列仍在."""
    vis_mod = _load("mig_visibility", MIG_VISIBILITY)
    cols = {c["name"] for c in inspect(app_engine).get_columns("strategy")}
    assert {"is_public", "stock_code"} <= cols, f"strategy 缺 v125 列: {cols}"
    _run_ok(vis_mod)
    cols2 = {c["name"] for c in inspect(app_engine).get_columns("strategy")}
    assert {"is_public", "stock_code"} <= cols2
```

- [ ] **Step 3: 全量后端测试**

Run: `"$PY" -m pytest tests/server/strategy/ -q`
Expected: 全部 PASS (test_strategy_v123_service / test_access_v125 / test_regression_v123 / test_migration_idempotent)。若 `test_layer_dependencies` 有 2 个预存失败(v123 前已存在),非本 change 引入,记录即可。

- [ ] **Step 4: 前端全量单测 + 冒烟**

Run: `cd client && npx vitest run --config ../tests/client/vitest.config.js`
Expected: 无新失败(既有失败如 ScriptTask 以外模块不变)。vite build 的 main.js top-level await 为已知预存问题,不作为本 change 验收。

- [ ] **Step 5: 重启后端 + 冒烟 HTTP**

Run:
```bash
"$PY" scripts/evctl.py restart backend
"$PY" -c "from server.services import script_strategy as svc; assert not hasattr(svc, 'create_live_batch'); print('pure-backtest OK')"
```
Expected: 后端健康, 模块无 create_live_batch。

- [ ] **Step 6: 手工冒烟 (可选, 登录态)**

用已有账号登录后:
- 新建策略必须选标的(缺标的 → 提示「请填写策略绑定标的」)
- 自己的策略:回测表单标的只读展示 = 绑定标的;可切公开/私有
- 他人公开策略:列表可见精简卡片,进入后无回测按钮、无公开开关、批次区提示只读

---

## Self-Review

**1. Spec coverage (设计文档 §1-§7):**
- §2 数据模型(is_public+stock_code 迁移、create_strategy 必填标的)→ Task 1/3/5 ✓
- §3 权限矩阵(list/get/edit/backtest)→ Task 2/3/4 + access.py ✓;他人公开回测 403、私有 404 ✓
- §4 API(schemas 扩字段、BacktestRequest Optional、删 /live、BACKTEST_FORBIDDEN→403)→ Task 5 ✓
- §5 前端(ScriptTask 公开开关/标的必选/移除实盘、ScriptDev 只读)→ Task 7-10 ✓
- §6 测试(全部列出)→ Task 2/3/4/11/12 ✓
- §7 openspec REQ-STRAT-019 → Task 6 ✓
- §8 范围外(Part 2 策略下单)→ 未实现,正确 ✓

**2. Placeholder scan:** 所有步骤含完整代码/命令,无 TBD。

**3. Type consistency:**
- `create_strategy(user_id, name, script_id, stock_code)` — Task 3 定义,Task 2/3/4 测试调用均带 stock_code ✓
- `require_backtest_access(strategy_id, user_id, is_admin)` — access.py 定义,Task 4 batches 用 ✓
- `create_backtest_batch` `stock_code: Optional[str]` + `effective_stock` 内部统一 ✓
- `strategy_row_to_dict` 输出 `is_public: bool` / `stock_code`;`public_view` 不含 script/best_params;StrategyOut 字段对齐 ✓
- `onTogglePublic(val)` / `updateStrategy(id, {is_public})` 前端一致 ✓

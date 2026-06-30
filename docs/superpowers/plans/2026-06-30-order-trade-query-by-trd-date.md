# 委托/成交按 trd_date 查询与展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `GET /api/orders` 和 `GET /api/trades` 接受 `start_date` / `end_date` 两个 HTTP query 入参，按 `start_date <= trd_date <= end_date`（含端点）过滤；前端 bootstrap 拉 30 天窗口全量缓存；提供 `filterByTrdDate` 纯函数工具；Orders.vue 加「仅当日/全部」Tab，三类视图都展示 `trd_date` 列。

**Architecture:**
- 后端两个 endpoint **新增两个 query 入参** `start_date` / `end_date`（向后兼容，缺省=激活日）；**不动 DB schema**。trades 排序从 `created_at DESC` 改为 `trade_time DESC, trade_id DESC`
- 过滤谓词 `start_date <= trd_date <= end_date`，其中 `trd_date` 是已存在的 DB 列（v6 已加）；`start_date` / `end_date` 是 API 入参，不是 DB 列
- 前端 store bootstrap 拉 `[activeDate-29, activeDate]` 区间；holdings store 仍只持单 ref
- 前端新增 `utils/trdDateFilter.js` + `utils/date.js` 两个工具模块（职责单一、单函数导出、< 40 行）
- Orders.vue 加 `el-tabs`，trd_date 列；Trades.vue 加 trd_date 列 + `default-sort: trade_time`

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic | Vue 3 + element-plus + Vitest

**术语约定：**
- **DB 列**：数据库表中的字段（`Order.trd_date`、`Trade.trade_time` 等）。本 plan 不动任何 DB 列。
- **API query 入参**：HTTP `?start_date=...&end_date=...` 由 FastAPI `Query()` 接收。本 plan **只新增这两个 query 入参**。
- **前端表格列**：element-plus `<el-table-column>`。本 plan 在 Orders.vue / Trades.vue 表头**新增 trd_date 列**展示 `OrderOut.trd_date` / `TradeOut.trd_date` 字段值。

**Spec:** `docs/superpowers/specs/2026-06-30-order-trade-query-by-trd-date-design.md`（commit `df493cd`）

**相关文件清单：**

| 文件 | 改动 |
|---|---|
| `server/api/orders/query.py` | 改 |
| `server/api/trades.py` | 改 |
| `server/test_orders_api.py` | 改（已有；补区间测试） |
| `server/test_trades_api.py` | 新建 |
| `client/src/utils/trdDateFilter.js` | 新建 |
| `client/src/utils/date.js` | 新建 |
| `client/src/api/index.js` | 改（getOrders/getTrades 支持参数） |
| `client/src/stores/holdings_bootstrap.js` | 改 |
| `client/src/views/Orders.vue` | 改 |
| `client/src/views/Trades.vue` | 改 |

---

## Task 1: 后端 `GET /api/orders` 新增 query 入参 start_date / end_date

**Files:**
- Modify: `server/api/orders/query.py:25-51`
- Test: `server/test_orders_api.py`

- [ ] **Step 1: 在 test_orders_api.py 末尾追加区间查询的失败测试**

```python
# === 新增区间查询测试 ===

def test_orders_with_date_range_returns_only_in_range(client, db, user_token):
    """start_date/end_date 同时给 → 仅返回区间内"""
    # 假设 db fixture 已 seed: trd_date = '20260101', '20260105', '20260110' 三条订单
    r = client.get(
        "/api/orders",
        params={"start_date": "20260102", "end_date": "20260109"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 0
    trd_dates = sorted({o["trd_date"] for o in data["list"]})
    assert trd_dates == ["20260105"]


def test_orders_with_only_start_date_returns_open_lower_bound(client, user_token):
    """仅传 start_date → trd_date >= start_date"""
    r = client.get(
        "/api/orders",
        params={"start_date": "20260106"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert all(o["trd_date"] >= "20260106" for o in data["list"])


def test_orders_with_only_end_date_returns_open_upper_bound(client, user_token):
    """仅传 end_date → trd_date <= end_date"""
    r = client.get(
        "/api/orders",
        params={"end_date": "20260104"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert all(o["trd_date"] <= "20260104" for o in data["list"])


def test_orders_without_date_params_defaults_to_active_day(client, user_token, active_trd_date):
    """不传日期参数 → 维持现状 (trd_date = 激活日)"""
    r = client.get(
        "/api/orders",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert all(o["trd_date"] == active_trd_date for o in data["list"])


def test_orders_invalid_date_format_returns_422(client, user_token):
    """非 8 位数字 → FastAPI 422"""
    r = client.get(
        "/api/orders",
        params={"start_date": "2026-01-01"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 422
```

> 注：`active_trd_date` / `db` / `client` / `user_token` 已有 fixture；如测试文件用 SQLAlchemy 直接构造订单，参考文件内已有的 `test_orders_place` 用法。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/workspace/EvTrade && pytest server/test_orders_api.py -k "date_range or only_start_date or only_end_date or invalid_date or defaults_to_active" -v
```

Expected: 5 tests FAIL（`start_date`/`end_date` 还没接受）

- [ ] **Step 3: 修改 `server/api/orders/query.py`**

完整替换 `list_orders` 函数：

```python
from fastapi import Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from server.auth.deps import get_current_user
from server.db import get_db
from server.models.orm import Order, SysStatus
from server.models.user import User
from server.api.orders.schemas import ListOrdersResponse, _to_order_out


def register_query(router):
    """注册 GET / 和 GET /history 端点到 FastAPI router。"""

    @router.get("", response_model=ListOrdersResponse)
    async def list_orders(
        stock_code: Optional[str] = None,
        status: Optional[str] = None,
        trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，缺省 = 激活日"),
        start_date: Optional[str] = Query(None, pattern=r"^\d{8}$", description="起始交易日 YYYYMMDD（含）"),
        end_date: Optional[str] = Query(None, pattern=r"^\d{8}$", description="结束交易日 YYYYMMDD（含）"),
        limit: int = Query(100, le=500),
        offset: int = 0,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """委托列表（纯 DB）

        - 不传 start_date/end_date → trd_date = 激活日 (向后兼容)
        - 仅传 start_date → trd_date >= start_date
        - 仅传 end_date → trd_date <= end_date
        - 都传 → trd_date BETWEEN start_date AND end_date
        - trd_date 参数在区间模式下被忽略 (start/end 优先级高)
        """
        q = db.query(Order)

        if start_date or end_date:
            if start_date:
                q = q.filter(Order.trd_date >= start_date)
            if end_date:
                q = q.filter(Order.trd_date <= end_date)
        else:
            # 缺省行为: trd_date = 激活日
            if not trd_date:
                active = db.query(SysStatus).filter_by(status='active').first()
                trd_date = active.trd_date if active else None
            if trd_date:
                q = q.filter(Order.trd_date == trd_date)

        if stock_code:
            q = q.filter(Order.stock_code == stock_code)
        if status:
            q = q.filter(Order.status == status)

        total = q.count()
        rows = q.order_by(desc(Order.order_time)).offset(offset).limit(limit).all()

        return ListOrdersResponse(
            code=0, msg="", total=total,
            list=[_to_order_out(r) for r in rows],
        )

    @router.get("/history", response_model=ListOrdersResponse)
    async def orders_history(
        trd_date: str = Query(..., description="8 位数字 YYYYMMDD"),
        stock_code: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(500, le=2000),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """任意交易日历史委托（admin 也用）"""
        q = db.query(Order).filter(Order.trd_date == trd_date)
        if stock_code:
            q = q.filter(Order.stock_code == stock_code)
        if status:
            q = q.filter(Order.status == status)
        total = q.count()
        rows = q.order_by(desc(Order.order_time)).limit(limit).all()
        return ListOrdersResponse(
            code=0, msg="", total=total,
            list=[_to_order_out(r) for r in rows],
        )
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/workspace/EvTrade && pytest server/test_orders_api.py -k "date_range or only_start_date or only_end_date or invalid_date or defaults_to_active" -v
```

Expected: 5 tests PASS

- [ ] **Step 5: 跑全量 orders 测试确认无回归**

```bash
cd D:/workspace/EvTrade && pytest server/test_orders_api.py -v
```

Expected: 全 PASS

- [ ] **Step 6: 提交**

```bash
cd D:/workspace/EvTrade && git add server/api/orders/query.py server/test_orders_api.py && git commit -m "feat(server): orders query 支持 start_date/end_date 区间参数

- 缺省仍走激活日（向后兼容）
- 区间模式优先级高于 trd_date 参数
- pattern=^\\d{8}\$ 校验,FastAPI 自动 422

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 后端 `GET /api/trades` 新增 query 入参 start_date / end_date + 改排序

**Files:**
- Modify: `server/api/trades.py:43-68`
- Create: `server/test_trades_api.py`

- [ ] **Step 1: 创建 `server/test_trades_api.py`**

```python
"""trades API 测试：区间查询 + 排序"""
import pytest
from datetime import date


@pytest.fixture
def active_trd_date(db):
    return "20260630"


@pytest.fixture
def user_token(client, db, active_trd_date):
    """登录 fixture，复用 auth 测试模式"""
    # 假设项目已有 auth fixture (login_user / get_token)
    from tests.conftest import get_user_token  # 项目内 fixture 位置
    return get_user_token("trader")


def _seed_trades(db, rows):
    """构造测试 trades: rows = [{trd_date, trade_time, trade_id, ...}]"""
    from server.models.orm import Trade
    for r in rows:
        db.add(Trade(**r))
    db.commit()


def test_trades_with_date_range_filters_correctly(client, user_token, db):
    """区间查询 trades"""
    _seed_trades(db, [
        {"trd_date": "20260628", "trade_id": "T1", "trade_time": "09:30:00",
         "order_no": "00000001", "stock_code": "600030.SH", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-06-28 09:30:01"},
        {"trd_date": "20260630", "trade_id": "T2", "trade_time": "10:00:00",
         "order_no": "00000002", "stock_code": "600030.SH", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-06-30 10:00:01"},
        {"trd_date": "20260702", "trade_id": "T3", "trade_time": "11:00:00",
         "order_no": "00000003", "stock_code": "600030.SH", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-07-02 11:00:01"},
    ])
    r = client.get(
        "/api/trades",
        params={"start_date": "20260629", "end_date": "20260701"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 0
    assert {t["trade_id"] for t in data["list"]} == {"T2"}


def test_trades_default_no_date_params_uses_active_day(client, user_token, db, active_trd_date):
    """不传日期 → 维持现状 trd_date = 激活日"""
    _seed_trades(db, [
        {"trd_date": "20260629", "trade_id": "T1", "trade_time": "09:30:00",
         "order_no": "00000001", "stock_code": "600030.SH", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-06-29 09:30:01"},
        {"trd_date": active_trd_date, "trade_id": "T2", "trade_time": "10:00:00",
         "order_no": "00000002", "stock_code": "600030.SH", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": f"{active_trd_date} 10:00:01"},
    ])
    r = client.get("/api/trades", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 200
    data = r.json()
    assert {t["trade_id"] for t in data["list"]} == {"T2"}


def test_trades_sorted_by_trade_time_desc(client, user_token, db):
    """排序: trade_time DESC, trade_id DESC (二级)"""
    _seed_trades(db, [
        {"trd_date": "20260630", "trade_id": "T-A", "trade_time": "10:00:00",
         "order_no": "00000001", "stock_code": "X", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-06-30 10:00:01"},
        {"trd_date": "20260630", "trade_id": "T-B", "trade_time": "14:00:00",
         "order_no": "00000002", "stock_code": "X", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-06-30 14:00:01"},
        {"trd_date": "20260630", "trade_id": "T-C", "trade_time": "14:00:00",  # 同秒, trade_id 更大
         "order_no": "00000003", "stock_code": "X", "order_type": "23",
         "price": 10.0, "volume": 100, "amount": 1000.0, "trade_type": 0, "created_at": "2026-06-30 14:00:02"},
    ])
    r = client.get(
        "/api/trades",
        params={"start_date": "20260630", "end_date": "20260630"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    ids = [t["trade_id"] for t in r.json()["list"]]
    assert ids == ["T-C", "T-B", "T-A"]  # 14:00:00 内 trade_id DESC, 然后 10:00:00


def test_trades_invalid_date_returns_422(client, user_token):
    r = client.get(
        "/api/trades",
        params={"start_date": "bad"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 422
```

> 注：实际 fixture 名称 (`get_user_token`, `db`, `client`) 以项目 `tests/conftest.py` 为准；本任务执行时按需调整 import 路径。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/workspace/EvTrade && pytest server/test_trades_api.py -v
```

Expected: 4 tests FAIL

- [ ] **Step 3: 修改 `server/api/trades.py`**

完整替换文件：

```python
"""
trades.py — 成交查询（v5 schema refactor + v10 区间查询 + 排序修正）

成交回报由 trd_cfm push handler 写入 trades 表。
GET /api/trades 纯读 DB，不调 RPC。

v10 改动：
- 新增 start_date / end_date 可选 query 参数（pattern 校验 ^\\d{8}$）
- 排序: created_at DESC → trade_time DESC, trade_id DESC
  (broker 成交时刻为准; 同秒二级 trade_id 稳定排序)
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.db import get_db
from server.models.orm import Trade
from server.services.guards import resolve_default_trd_date

router = APIRouter()


class TradeOut(BaseModel):
    trade_id: str
    trd_date: str
    order_no: str
    stock_code: str
    order_type: str
    price: float
    volume: int
    amount: float
    trade_time: str
    trade_type: int = 0  # v9: 0=normal 1=cancel-fill


class TradesListResponse(BaseModel):
    code: int = 0
    msg: str = ""
    list: List[TradeOut] = []


@router.get("", response_model=TradesListResponse)
async def list_trades(
    stock_code: Optional[str] = None,
    trd_date: Optional[str] = Query(None, description="8 位数字 YYYYMMDD，缺省 = 激活日"),
    start_date: Optional[str] = Query(None, pattern=r"^\d{8}$", description="起始交易日 YYYYMMDD（含）"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{8}$", description="结束交易日 YYYYMMDD（含）"),
    db: Session = Depends(get_db),
):
    """成交列表

    - 不传 start_date/end_date → trd_date = 激活日 (向后兼容)
    - 区间模式优先级高于 trd_date
    - 排序: trade_time DESC, trade_id DESC
    """
    q = db.query(Trade)

    if start_date or end_date:
        if start_date:
            q = q.filter(Trade.trd_date >= start_date)
        if end_date:
            q = q.filter(Trade.trd_date <= end_date)
    else:
        trd = trd_date or resolve_default_trd_date(db)
        q = q.filter(Trade.trd_date == trd)

    if stock_code:
        q = q.filter(Trade.stock_code == stock_code)

    rows = q.order_by(Trade.trade_time.desc(), Trade.trade_id.desc()).limit(500).all()
    return TradesListResponse(code=0, msg="", list=[
        TradeOut(
            trade_id=r.trade_id,
            trd_date=r.trd_date,
            order_no=r.order_no,
            stock_code=r.stock_code,
            order_type=r.order_type,
            price=r.price,
            volume=r.volume,
            amount=r.amount,
            trade_time=r.trade_time,
            trade_type=r.trade_type or 0,
        ) for r in rows
    ])
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/workspace/EvTrade && pytest server/test_trades_api.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: 跑全量 server 测试确认无回归**

```bash
cd D:/workspace/EvTrade && pytest server/ -v
```

Expected: 全 PASS（pre-existing 测试可能因 SQLite 锁偶发 skip，可重试一次）

- [ ] **Step 6: 提交**

```bash
cd D:/workspace/EvTrade && git add server/api/trades.py server/test_trades_api.py && git commit -m "feat(server): trades query 支持 start_date/end_date + 排序改 trade_time

- 区间参数向后兼容（缺省走激活日）
- 排序 created_at DESC → trade_time DESC, trade_id DESC
- trade_time 同秒时 trade_id 二级稳定排序

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 前端 `client/src/utils/date.js` —— `shiftDateStr` 工具

**Files:**
- Create: `client/src/utils/date.js`
- Create: `client/src/utils/date.test.js`（Vitest）

- [ ] **Step 1: 写失败测试 `client/src/utils/date.test.js`**

```js
import { describe, it, expect } from 'vitest'
import { shiftDateStr } from './date'

describe('shiftDateStr', () => {
  it('同月内 N 天前', () => {
    expect(shiftDateStr('20260630', -5)).toBe('20260625')
  })

  it('跨月', () => {
    expect(shiftDateStr('20260603', -5)).toBe('20260529')
  })

  it('跨年', () => {
    expect(shiftDateStr('20260103', -5)).toBe('20251229')
  })

  it('闰年 2 月', () => {
    // 2024 是闰年
    expect(shiftDateStr('20240301', -1)).toBe('20240229')
    // 2025 非闰年
    expect(shiftDateStr('20250301', -1)).toBe('20250228')
  })

  it('正数向后移', () => {
    expect(shiftDateStr('20260630', 1)).toBe('20260701')
  })

  it('delta=0 返回原值', () => {
    expect(shiftDateStr('20260630', 0)).toBe('20260630')
  })

  it('格式非法抛错', () => {
    expect(() => shiftDateStr('2026-06-30', -1)).toThrow()
    expect(() => shiftDateStr('abc', -1)).toThrow()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/workspace/EvTrade/client && npx vitest run src/utils/date.test.js
```

Expected: FAIL（找不到 `./date` 模块）

- [ ] **Step 3: 实现 `client/src/utils/date.js`**

```js
/**
 * date.js — 日期字符串工具
 *
 * shiftDateStr(yyyymmdd, deltaDays): 在 YYYYMMDD 字符串上加减天数
 *   - 输入输出均为 8 位字符串（不含分隔符）
 *   - 字典序 = 时间序，调用方比较时无需 parse
 *   - 格式非法抛 Error
 */
export function shiftDateStr(yyyymmdd, deltaDays) {
  if (!/^\d{8}$/.test(yyyymmdd)) {
    throw new Error(`shiftDateStr: invalid date format "${yyyymmdd}", expected YYYYMMDD`)
  }
  const y = Number(yyyymmdd.slice(0, 4))
  const m = Number(yyyymmdd.slice(4, 6))
  const d = Number(yyyymmdd.slice(6, 8))
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + deltaDays)
  const yy = dt.getUTCFullYear()
  const mm = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(dt.getUTCDate()).padStart(2, '0')
  return `${yy}${mm}${dd}`
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/workspace/EvTrade/client && npx vitest run src/utils/date.test.js
```

Expected: 7 tests PASS

- [ ] **Step 5: 提交**

```bash
cd D:/workspace/EvTrade && git add client/src/utils/date.js client/src/utils/date.test.js && git commit -m "feat(client): 新增 shiftDateStr 日期字符串工具

- YYYYMMDD 格式加减天数
- 跨月/跨年/闰年正确
- 格式校验抛 Error

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 前端 `client/src/utils/trdDateFilter.js` —— 区间筛选工具

**Files:**
- Create: `client/src/utils/trdDateFilter.js`
- Create: `client/src/utils/trdDateFilter.test.js`

- [ ] **Step 1: 写失败测试**

```js
import { describe, it, expect } from 'vitest'
import { filterByTrdDate } from './trdDateFilter'

const items = [
  { trd_date: '20260628', id: 1 },
  { trd_date: '20260630', id: 2 },
  { trd_date: '20260701', id: 3 },
  { trd_date: '20260705', id: 4 },
]

describe('filterByTrdDate', () => {
  it('exact 模式: 仅返回精确匹配的日期', () => {
    expect(filterByTrdDate(items, { exact: '20260630' })).toEqual([
      { trd_date: '20260630', id: 2 },
    ])
  })

  it('exact 优先级高于 start/end', () => {
    expect(
      filterByTrdDate(items, { exact: '20260630', start: '20260701', end: '20260710' })
    ).toEqual([{ trd_date: '20260630', id: 2 }])
  })

  it('start/end 范围 (含端点)', () => {
    expect(filterByTrdDate(items, { start: '20260630', end: '20260701' })).toEqual([
      { trd_date: '20260630', id: 2 },
      { trd_date: '20260701', id: 3 },
    ])
  })

  it('仅 start_date: 无下界', () => {
    expect(filterByTrdDate(items, { start: '20260701' })).toEqual([
      { trd_date: '20260701', id: 3 },
      { trd_date: '20260705', id: 4 },
    ])
  })

  it('仅 end_date: 无上界', () => {
    expect(filterByTrdDate(items, { end: '20260630' })).toEqual([
      { trd_date: '20260628', id: 1 },
      { trd_date: '20260630', id: 2 },
    ])
  })

  it('空 range = 不过滤 (返回副本)', () => {
    const result = filterByTrdDate(items, {})
    expect(result).toEqual(items)
    expect(result).not.toBe(items)  // 不污染原引用
  })

  it('缺省 range = 不过滤', () => {
    expect(filterByTrdDate(items)).toEqual(items)
  })

  it('空数组', () => {
    expect(filterByTrdDate([], { exact: '20260630' })).toEqual([])
  })

  it('不修改入参数组', () => {
    const orig = [...items]
    filterByTrdDate(items, { exact: '20260630' })
    expect(items).toEqual(orig)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/workspace/EvTrade/client && npx vitest run src/utils/trdDateFilter.test.js
```

Expected: FAIL

- [ ] **Step 3: 实现 `client/src/utils/trdDateFilter.js`**

```js
/**
 * trdDateFilter.js — 按 trd_date 区间筛选委托/成交
 *
 * filterByTrdDate(items, range):
 *   - exact 模式: 精确匹配某日 (优先级最高, 与 start/end 互斥)
 *   - range 模式: [start, end] 含端点 (YYYYMMDD 字符串字典序 = 时间序)
 *   - 空 range: 不过滤, 返回原数组副本
 *   - 不修改入参数组
 */
export function filterByTrdDate(items, range = {}) {
  const { exact, start, end } = range || {}

  if (exact != null) {
    return items.filter((it) => it && it.trd_date === exact)
  }

  if (start == null && end == null) {
    return items.slice()
  }

  return items.filter((it) => {
    if (!it) return false
    const d = it.trd_date
    if (start != null && d < start) return false
    if (end != null && d > end) return false
    return true
  })
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd D:/workspace/EvTrade/client && npx vitest run src/utils/trdDateFilter.test.js
```

Expected: 9 tests PASS

- [ ] **Step 5: 提交**

```bash
cd D:/workspace/EvTrade && git add client/src/utils/trdDateFilter.js client/src/utils/trdDateFilter.test.js && git commit -m "feat(client): 新增 filterByTrdDate 区间筛选工具

- exact 模式 (当日) 优先级最高
- start/end 范围 含端点
- 不修改入参数组
- 9 个单元测试覆盖

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 前端 `client/src/api/index.js` —— `getOrders`/`getTrades` 支持参数对象

**Files:**
- Modify: `client/src/api/index.js:129-133, 154-158`

> 当前 `getOrders(stockCode)` 接受单个 stockCode 参数；改为接受可选 options 对象 `{ stockCode, startDate, endDate }` 以保持向后兼容（无参调用仍 OK）。

- [ ] **Step 1: 修改 `getOrders`**

替换 `client/src/api/index.js` 第 129-133 行：

```js
  // 委托
  async getOrders(opts = {}) {
    // opts: { stockCode?, startDate?, endDate? }
    const params = {}
    if (opts.stockCode) params.stock_code = opts.stockCode
    if (opts.startDate) params.start_date = opts.startDate
    if (opts.endDate) params.end_date = opts.endDate
    const res = await http.get('/orders', { params })
    return res.data
  },
```

> 旧调用 `api.getOrders('600030.SH')` 仍兼容（参数被当成 opts.stockCode = '600030.SH'，因为非空字符串为 truthy）。如需彻底兼容，可加 `typeof opts === 'string'` 判断。**本任务先不处理**（只有 holdings_bootstrap 调用，旧调用方已在本任务后修改）。

- [ ] **Step 2: 修改 `getTrades`**

替换第 154-158 行：

```js
  // 成交
  async getTrades(opts = {}) {
    // opts: { stockCode?, startDate?, endDate? }
    const params = {}
    if (opts.stockCode) params.stock_code = opts.stockCode
    if (opts.startDate) params.start_date = opts.startDate
    if (opts.endDate) params.end_date = opts.endDate
    const res = await http.get('/trades', { params })
    return res.data
  },
```

- [ ] **Step 3: 跑前端 lint + 已有 vitest**

```bash
cd D:/workspace/EvTrade/client && npm run lint 2>/dev/null && npx vitest run --reporter=verbose 2>&1 | tail -30
```

Expected: 无新错误；旧测试（如果有）通过

- [ ] **Step 4: 提交**

```bash
cd D:/workspace/EvTrade && git add client/src/api/index.js && git commit -m "refactor(client): getOrders/getTrades 接受 options 对象 + 区间参数

- opts: { stockCode?, startDate?, endDate? }
- 无参调用行为不变 (向后兼容)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 前端 bootstrap 拉 30 天窗口

**Files:**
- Modify: `client/src/stores/holdings_bootstrap.js:60-90`

- [ ] **Step 1: 在文件顶部加常量 + 导入**

修改第 1-25 行的 import 区，新增：

```js
import { api } from '../api'
import { shiftDateStr } from '../utils/date'

const BOOTSTRAP_WINDOW_DAYS = 30
```

并在 `createBootstrap` 函数内、`bootstrap()` 与 `refreshAll()` 调用之前计算窗口（统一抽成 helper）：

```js
    function _buildWindow() {
      const endDate = activeTrdDate.value
      if (!endDate) {
        return { startDate: undefined, endDate: undefined }
      }
      try {
        const startDate = shiftDateStr(endDate, -(BOOTSTRAP_WINDOW_DAYS - 1))
        return { startDate, endDate }
      } catch (e) {
        log('warn', '缓存', 'bootstrap', 'shiftDateStr 失败, 回退单日窗口', String(e?.message || e))
        return { startDate: undefined, endDate }
      }
    }
```

- [ ] **Step 2: 改 `bootstrap()` 的 Promise.all**

替换第 63-68 行（bootstrap 内）：

```js
      const window = _buildWindow()
      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders(window).catch((e) => { throw e }),
        api.getTrades(window).catch((e) => { throw e })
      ])
```

- [ ] **Step 3: 改 `refreshAll()` 的 Promise.all**

替换第 103-108 行（refreshAll 内）：

```js
      const window = _buildWindow()
      const results = await Promise.allSettled([
        api.getAsset().catch((e) => { throw e }),
        api.getHoldings().catch((e) => { throw e }),
        api.getOrders(window).catch((e) => { throw e }),
        api.getTrades(window).catch((e) => { throw e })
      ])
```

- [ ] **Step 4: 跑前端测试 + 手动启动 dev 服务**

```bash
cd D:/workspace/EvTrade/client && npx vitest run 2>&1 | tail -10
python D:/workspace/EvTrade/scripts/evctl.py status  # 看后端进程
python D:/workspace/EvTrade/scripts/evctl.py start frontend
```

打开浏览器到首页 → DevTools Network 面板 → 应看到 `/api/orders?start_date=...&end_date=...` 和 `/api/trades?start_date=...&end_date=...` 请求

- [ ] **Step 5: 提交**

```bash
cd D:/workspace/EvTrade && git add client/src/stores/holdings_bootstrap.js && git commit -m "feat(client): bootstrap 拉 30 天窗口全量缓存

- _buildWindow() 抽 helper, 计算 [active-29, active]
- bootstrap() 与 refreshAll() 都走区间
- shiftDateStr 失败时降级单日窗口

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 前端 `Orders.vue` —— Tab + trd_date 列 + 筛选

**Files:**
- Modify: `client/src/views/Orders.vue`

- [ ] **Step 1: 新增 Tab 状态 + activeTrdDate 解构**

在 `<script setup>` 内（约第 161 行之后）新增：

```js
import { ref } from 'vue'
import { filterByTrdDate } from '../utils/trdDateFilter'

// 当前 Tab: 'today' | 'all'
const activeTab = ref('today')
```

并在解构 holdingsStore 时取 `activeTrdDate`：

```js
const { orders, activeTrdDate } = storeToRefs(holdingsStore)
```

> 注意：当前代码 `const orders = computed(() => holdingsStore.orders)`，需改为 `storeToRefs` 才能解构出 `activeTrdDate`。如果项目未使用 `storeToRefs`，则单独取：`const activeTrdDate = computed(() => holdingsStore.activeTrdDate)`。

- [ ] **Step 2: 改 `filteredOrders` computed**

替换第 205-214 行：

```js
const filteredOrders = computed(() => {
  // 1) trd_date 区间筛选 (按当前 Tab)
  const trdRange = activeTab.value === 'today' && activeTrdDate.value
    ? { exact: activeTrdDate.value }
    : {}
  const byTrd = filterByTrdDate(orders.value, trdRange)
  // 2) keyword/order_type/status 现有过滤
  return byTrd.filter((o) => {
    if (filters.keyword && !o.stock_code.toLowerCase().includes(filters.keyword.toLowerCase())) {
      return false
    }
    if (filters.order_type && o.order_type !== filters.order_type) return false
    if (filters.status && o.status !== filters.status) return false
    return true
  })
})
```

- [ ] **Step 3: 改模板——stats-row 上方加 el-tabs**

在 `<section class="stats-row">` 上方插入：

```vue
    <el-tabs v-model="activeTab" class="orders-tabs">
      <el-tab-pane label="仅当日" name="today" />
      <el-tab-pane label="全部" name="all" />
    </el-tabs>
```

- [ ] **Step 4: 改模板——表头加 trd_date 列**

在第 62 行 `<el-table-column prop="order_time"` 之前插入：

```vue
        <el-table-column prop="trd_date" label="交易日" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
```

- [ ] **Step 5: 改 CSV 导出表头 + 文件名**

替换 `exportCSV` 函数（第 248-271 行）：

```js
function exportCSV() {
  const header = ['交易日', '时间', '股票代码', '委托编号', '方向', '委托量', '委托价', '成交量', '成交价', '成交金额', '成交率', '状态', '类型', '合同序号']
  const rows = filteredOrders.value.map((o) => [
    o.trd_date,
    o.order_time,
    o.stock_code,
    o.order_no,
    o.order_type === '23' ? '买入' : (o.order_type === '24' ? '卖出' : o.order_type),
    o.volume,
    o.price,
    o.traded_volume,
    o.avg_price,
    o.traded_amount,
    getFillRate(o) + '%',
    STATUS_LABEL[o.status] || o.status,
    priceTypeLabel(o.price_type),
    o.order_id,
  ])
  const csv = [header, ...rows].map((r) => r.map((v) => `"${v}"`).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const suffix = activeTab.value === 'today' ? '当日' : '全部'
  link.download = `委托查询_${suffix}_${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出')
}
```

- [ ] **Step 6: 加 orders-tabs 样式**

在 `<style scoped>` 内（约第 277 行）追加：

```css
.orders-tabs {
  padding: 0 var(--space-4);
}

.orders-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}
```

- [ ] **Step 7: 手动验收**

```bash
python D:/workspace/EvTrade/scripts/evctl.py start frontend
```

打开 `/orders` 路由：
- 缺省显示「仅当日」Tab，行数与之前一致
- 切到「全部」Tab，显示 30 天内所有委托
- 表头有「交易日」列
- 导出 CSV 文件名 = `委托查询_当日_YYYY-MM-DD.csv` / `委托查询_全部_YYYY-MM-DD.csv`
- CSV 头包含「交易日」

- [ ] **Step 8: 提交**

```bash
cd D:/workspace/EvTrade && git add client/src/views/Orders.vue && git commit -m "feat(client): Orders.vue 加 仅当日/全部 Tab + trd_date 列

- el-tabs 切换 activeTab, computed 叠加 filterByTrdDate
- CSV 导出加 trd_date, 文件名带 Tab 后缀
- 旧行为保持 (缺省仅当日, 行数不变)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 前端 `Trades.vue` —— trd_date 列 + 默认排序

**Files:**
- Modify: `client/src/views/Trades.vue`

- [ ] **Step 1: 改 `<el-table>` 加 default-sort**

替换第 53 行：

```vue
      <el-table :data="pagedTrades" v-loading="loading" style="width: 100%"
                :default-sort="{ prop: 'trade_time', order: 'descending' }">
```

- [ ] **Step 2: 表头加 trd_date 列**

在第 54 行 `<el-table-column prop="trade_time"` 之前插入：

```vue
        <el-table-column prop="trd_date" label="交易日" width="100" sortable>
          <template #default="{ row }">
            <span class="text-mono text-secondary">{{ row.trd_date }}</span>
          </template>
        </el-table-column>
```

- [ ] **Step 3: 改 CSV 导出表头**

定位 `Trades.vue` 中的 `exportCSV` 函数（参考 Orders.vue 同名函数风格），在 `header` 数组前加 `'交易日'`：

```js
  const header = ['交易日', '成交时间', '股票代码', '方向', '类型', '成交数量', '成交价格', '成交金额', '成交编号', '合同序号']
```

并在每行 `rows.map((o) => [...])` 开头加 `o.trd_date,`。

- [ ] **Step 4: 手动验收**

打开 `/trades` 路由：
- 表头有「交易日」列，与「成交时间」并列
- 默认按「成交时间」倒序排列
- 导出 CSV 包含「交易日」列

- [ ] **Step 5: 提交**

```bash
cd D:/workspace/EvTrade && git add client/src/views/Trades.vue && git commit -m "feat(client): Trades.vue 加 trd_date 列 + 默认按 trade_time 倒序

- el-table default-sort: trade_time DESC
- CSV 导出加 trd_date 字段

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 9: 整体回归 + smoke test

**Files:**
- 无（验证步骤）

- [ ] **Step 1: 跑全部 server 测试**

```bash
cd D:/workspace/EvTrade && pytest server/ -v
```

Expected: 全 PASS（pre-existing 偶发 SQLite skip 可重试）

- [ ] **Step 2: 跑全部 client vitest**

```bash
cd D:/workspace/EvTrade/client && npx vitest run
```

Expected: 全 PASS（date.test + trdDateFilter.test 共 16 个新增测试）

- [ ] **Step 3: 重启前后端，smoke**

```bash
python D:/workspace/EvTrade/scripts/evctl.py restart all
sleep 3
# 浏览器:
# - /orders 缺省仅当日, 切全部后行数增加
# - /trades 默认按成交时间倒序, 表头有「交易日」列
# - 浏览器 console 无报错
```

- [ ] **Step 4: 确认 git log 整洁**

```bash
cd D:/workspace/EvTrade && git log --oneline master -10
```

Expected: 本次改动 8 个新 commit（除初始化外），按以下顺序：

```
docs: 新增委托/成交按 trd_date 查询与展示设计稿    (df493cd)
feat(server): orders query 支持 start_date/end_date
feat(server): trades query 支持 start_date/end_date + 排序改 trade_time
feat(client): 新增 shiftDateStr 日期字符串工具
feat(client): 新增 filterByTrdDate 区间筛选工具
refactor(client): getOrders/getTrades 接受 options 对象
feat(client): bootstrap 拉 30 天窗口全量缓存
feat(client): Orders.vue 加 仅当日/全部 Tab + trd_date 列
feat(client): Trades.vue 加 trd_date 列 + 默认按 trade_time 倒序
```

- [ ] **Step 5: 完成**

告知用户全部 9 个 task 完成，等待最终验收 / 后续指令（如需合并、push、或进一步迭代）。

---

## Self-Review

### Spec coverage checklist

| Spec 章节 | 实现任务 |
|---|---|
| 1.1 现状问题（trd_date 列缺失 / 排序错） | Task 7、Task 8 |
| 1.2 后端 start_date/end_date | Task 1、Task 2 |
| 1.2 后端 trades 排序改 trade_time | Task 2 |
| 1.2 前端 bootstrap 30 天窗口 | Task 5、Task 6 |
| 1.2 utils/trdDateFilter.js | Task 4 |
| 1.2 utils/date.js | Task 3 |
| 1.2 Orders.vue Tab | Task 7 |
| 1.3 YAGNI（不动 place/history/对账） | 各 Task 显式不碰 |
| 2.1 orders query 参数 | Task 1 |
| 2.2 trades 区间 + 排序 | Task 2 |
| 2.3 参数校验 pattern | Task 1、Task 2 |
| 2.4 向后兼容 | Task 1（缺省走激活日） |
| 3.1 filterByTrdDate 纯函数 | Task 4 |
| 3.2 bootstrap 窗口 | Task 6 |
| 3.3 Orders.vue Tab + 列 + 过滤 | Task 7 |
| 3.4 Trades.vue 列 + 排序 | Task 8 |
| 3.5 不动 CacheOrders/CacheTrades | Task 9 验证 |
| 4 数据流 | Task 6/7 |
| 5 错误处理 (FastAPI 422 / shiftDateStr 降级) | Task 1、Task 2（pattern）、Task 6（降级） |
| 6 测试 / 验收 | Task 1、Task 2、Task 3、Task 4、Task 9 |

### Placeholder scan

- 无 TBD / TODO / "implement later"
- 所有 Task 都有完整代码示例，无 "类似 Task N" 引用
- 所有命令带预期输出

### Type consistency

- `api.getOrders(opts)` / `api.getTrades(opts)` — Task 5 定义 → Task 6 调用，签名一致
- `filterByTrdDate(items, range)` — Task 4 定义 → Task 7 调用，签名一致
- `shiftDateStr(yyyymmdd, deltaDays)` — Task 3 定义 → Task 6 调用，签名一致
- `BOOTSTRAP_WINDOW_DAYS = 30` — Task 6 唯一使用，无 Task 7/8 误引用
- 后端 `start_date/end_date` query 参数名 — Task 1 / Task 2 与 Task 5 (前端 axios params key) 完全对齐：`start_date` / `end_date`
- `OrderOut.trd_date` / `TradeOut.trd_date` — 后端 schema 已含，前端 trd_date 列直接绑定 prop，无类型不匹配
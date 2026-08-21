# 2026-08-12-cost-price-scale — 持仓成本按证券 scale 保留精度（优化）

## Why

用户需求（2026-08-12 优化）：「优化一下，按证券信息里面的scale保留小数精度」。

上一 change（`cost-price-round4`）把 cost_price 统一成**固定 4 位**，但系统里价格精度口径其实是**按标的不同**：
`stocks.scale`（v80 引入，A股=2 / ETF=3，admin 可配 0-6，缺省 2）。prod 库 7523 只证券实测：scale=2 有 5542、scale=3 有 1981。
下单价（`api/orders/place.py:89-93`）、委托均价/成交额（`push/ord.py:116-121`）都按 scale round，唯独持仓成本被上一 change 固化成 4 位，
与系统其余价格字段口径不一致（ETF 成本价存 4 位会被前端按 3 位显示产生冗余尾数）。

## What Changes

**精度口径**：cost_price 从固定 `_round4` 改为**按 `stocks.scale` 保留小数**（`round(x, scale)` + scale>6 兜底 2，
与 ord.py/place.py 现有按 scale round 的写法对齐）。复用 `server/repo/stocks.get_stock_scale`（直查 DB，缺行兜底 2）。

覆盖全部 cost_price 写路径 + 序列化：

| 路径 | 位置 | 现状 | 改后 |
|---|---|---|---|
| init reconcile | `reconcile.py:225` | `_round4` | `_round_scale(v, get_stock_scale(...))` |
| pos_push 增量 | `push/pos.py:68` | `_round4` | `_round_scale(v, get_stock_scale(...))` |
| trd 建仓（买入自动建 Position） | `push/trd.py:147` | ❌ 无 rounding（`trade_price` 原样） | `_round_scale(trade_price, get_stock_scale(...))` |
| WS 序列化 | `push/helpers._position_to_out_dict:117` | `_round4` | `_round_scale(v, get_stock_scale(...))` |

### 工具函数

`push/helpers.py`：`_round4` 删除，新增 `_round_scale(v, scale)`：

```python
def _round_scale(v, scale=2):
    """按证券 scale 保留价格小数位 (round, scale>6 兜底 2)"""
    try:
        s = int(scale or 2)
    except (TypeError, ValueError):
        s = 2
    if s > 6:
        s = 2
    return float(round(float(v), s))
```

### 测试

- `test_cost_price_round4.py` → 改 scale-aware（monkeypatch `get_stock_scale`）：scale=2 → 1.41914→1.42；scale=3 → 0.763661→0.764；序列化同口径。
- `test_pos_push_diff.py` fixture 补 `get_stock_scale` monkeypatch（保持 hermetic，不触真实 DB）。

### 不做的事

- ❌ 不迁移 DB 列（延续用户确认的「仅边界四舍五入」）
- ❌ 不动 `fees._q4`（T0 费率/收益率口径，与持仓成本无关）
- ❌ 不改前端（读存储值，存储 scale-exact 后天然按 scale 计算/显示）

## 时序

```
broker avg_price (m_dOpenPrice)
  → 写路径 (reconcile / pos_push / trd 建仓): get_stock_scale → _round_scale → DB
  → API / WS 序列化: 存储值已 scale-exact, 序列化 _round_scale 防御性再 round (幂等)
  → 前端 getProfit / getReturnRate 直接按 scale 精度计算
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `server/services/push/helpers.py` | `_round4`→`_round_scale(v, scale)`；`_position_to_out_dict` 按 scale |
| 后端 | `server/services/push/pos.py` | 写路径按 scale |
| 后端 | `server/services/push/trd.py` | 建仓路径按 scale（补漏） |
| 后端 | `server/services/reconcile.py` | 写路径按 scale |
| 测试 | `server/tests/push/test_cost_price_round4.py` | scale-aware 断言 |
| 测试 | `server/tests/push/test_pos_push_diff.py` | fixture 补 get_stock_scale monkeypatch |
| 知识库 | `openspec/specs/data-model/spec.md` | cost_price 精度口径 4 位 → stocks.scale |

## 关联

- 上游：`cost-price-round4`（固定 4 位口径，本 change 取代）；`stocks.scale`（v80）；`ord.py:116-121` / `place.py:89-93`（既有按 scale round 模式）

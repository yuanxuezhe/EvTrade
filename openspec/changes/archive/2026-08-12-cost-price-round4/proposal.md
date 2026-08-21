# 2026-08-12-cost-price-round4 — broker 持仓成本统一 4 位小数

## Why

用户需求（2026-08-12）：「broker返回的持仓成本，在系统都需要存储为4位小数，后面的计算都要用四位小数算」。

排查结果：cost_price 的「4 位小数」口径在 `push/helpers._round4` 的注释里已声明为系统口径
（v130+，「所有写入路径 (pos.push / trd.push / reconcile) 落库前 round 4 位；读取路径 (推送 payload / API response) 也 round 4 位」），
但实际只有**一条写入路径**落实了，存在两处缺口导致同一口径在系统内不一致：

### 缺口 1（写路径）：init reconcile 落库未 round

- `reconcile.py:224` 落库 `cost_price=float(p.get('cost_price', 0) or 0)`，数据来自
  `parsers_business._parse_positions`（`parsers_common._to_float`，**无 rounding**）。
- broker 返回 `m_dOpenPrice`（iquant/runtime_trdapi_rel.py:94,239）可带 5-6 位小数（如 `0.763661`、`1.41914`），
  init reconcile 全表覆盖时原样入库 → 前端显示/累加出现「差 0.02 元」累积误差。
- 对比：盘中增量路径 `push/pos.py:68 handle_pos_push` 已 `_round4`（v130+ 已合规）。

### 缺口 2（读路径）：WS position_update 序列化未 round

- `push/helpers._position_to_out_dict:117` 用 `_float(pos.cost_price or 0)` 而非 `_round4`，
  与 `_round4` docstring 声明的「读取路径也 round 4 位」相矛盾。
- 虽 DB 值在写路径 round 后已 4 位，但序列化处保持 `_float` 会让未来任何绕过写路径的改动直接露原始精度。

## What Changes

**决策（用户已确认）**：**仅边界四舍五入，不迁移 DB 列**。`positions.cost_price` 保持 `float` 列，
在写入边界 + 读取序列化边界统一套 `_round4`（复用 `server/services/push/helpers._round4`，不引入第三套精度工具）。

### 写路径：reconcile.py

`reconcile.py:224` 落库前套 `_round4`：

```python
cost_price=_round4(p.get('cost_price', 0)),
```

- 复用 `server/services.push.helpers._round4`（服务层→服务层内部依赖，不反向让 rpc parser 依赖 services）。
- push 路径 `pos.py:68` 已合规，不动。

### 读路径：push/helpers._position_to_out_dict

`cost_price` 由 `_float(pos.cost_price or 0)` 改为 `_round4(pos.cost_price or 0)`，对齐既有口径注释。

### 不做的事

- ❌ 不迁移 DB 列（用户确认仅边界四舍五入；DECIMAL(12,4) 列为备选，本次不执行）
- ❌ 不改 `parsers_business._parse_positions`（保持纯 rename 边界，rounding 收口在服务层落库处）
- ❌ 不合并/重写 `_round4` 与 `fees._q4` 两套精度工具（`_q4` 归 T0 费率/收益率，`_round4` 归持仓成本，各司其职）

## 时序

```
broker qry_positions (m_dOpenPrice 5-6 位)
  → _parse_positions (rename avg_price→cost_price, 不 round)
  → reconcile.py _round4 → DB (float, 值 4 位)
  → API / holdings / positions / position_adjust 透传 (值已 4 位)
  → 前端 getProfit / getReturnRate / market_value 均用 4 位 cost_price 计算

broker pos_push (盘中增量)
  → push/pos.py handle_pos_push _round4 → DB
  → _position_to_out_dict _round4 → WS position_update → 前端
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 后端 | `server/services/reconcile.py` | 落库 cost_price 套 `_round4` |
| 后端 | `server/services/push/helpers.py` | `_position_to_out_dict` cost_price `_float`→`_round4` |
| 知识库 | `openspec/specs/data-model/spec.md` | positions.cost_price 补「统一 4 位小数」约定 + pos_push 同为写源 |

## 关联

- 上游：`openspec/specs/data-model/spec.md` §3 positions（cost_price 当前描述为 Float + 仅 do_reconcile 写入，需修正）
- 既有：`push/helpers._round4`（v130+ 已声明 4 位口径）、`push/pos.py:68`（写路径已合规）

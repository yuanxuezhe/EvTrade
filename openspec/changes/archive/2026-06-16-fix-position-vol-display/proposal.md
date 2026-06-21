# Fix position `vol` not showing in Position.vue

## Why

`Position.vue` / `PositionTable.vue` 持仓表"总持仓"列（`row.vol`）显示 0 或空，**而 `T0Trade.vue` 的 `currentVolume`（用 `avl_vol` 兜底）能正常显示**。

根因在 `server/services/push_handlers.py:handle_pos_cfm:274`：
```python
pos.vol = _int(row.get('volume', 0))
```

`row.get('volume', 0)` —— 如果 pos_cfm 推送行不送 `volume` 字段（实际生产中 broker 多只送 `available`），`vol` 就一直是 0，PositionTable 表格里"总持仓"列空着。

但 push handler 同一函数写了 `avl_vol = _int(row.get('available', pos.vol))`，且 avl_vol 在 T0Trade 优先用 —— **T0Trade 的 `currentVolume = Number(p.avl_vol ?? p.vol ?? 0)` 因此能显示**。

合约上没有把"vol 缺字段时怎么算"说清楚，造成后端/视图层各自理解不一致。

## What Changes

### 1. `handle_pos_cfm` vol 字段兜底

- 文件：`server/services/push_handlers.py:handle_pos_cfm`
- 改：`pos.vol` 在 `row.volume` 缺/为 0 而 `row.available > 0` 时，兜底为 `avl_vol`
- 具体逻辑：
  ```python
  avl = _int(row.get('available', 0))
  pos.avl_vol = avl
  pos.vol = _int(row.get('volume', 0)) or avl  # 缺字段或为 0 → 用 avl
  ```
- 兜底边界：`avl > 0` 才兜底（持仓真为 0 不兜底）

### 2. 注释 + 日志

- `handle_pos_cfm` 加注释说明 vol/avl_vol 字段映射规则
- 日志：当 vol 与 avl_vol 不一致时打 info（便于排查 broker 推送异常）

### 3. 同步 spec

- `positioning/spec.md` 新增 REQ-POS-004 兜底规则 + S-POS-002 场景
- `data-model/spec.md` 同步 positions 表 vol 字段说明

## Capabilities

### Modified Capabilities
- `positioning`: vol 兜底契约
- `push`: pos_cfm 字段映射契约
- `data-model`: positions 表 vol 字段说明

## Impact

- `server/services/push_handlers.py:handle_pos_cfm` — 改 1 行 + 注释
- `server/test_push_handlers.py` — 加 1 个测试用例（pos_cfm 不送 volume）
- 前端无改动（自动受益）

## Verification

1. 单元测试：pos_cfm 推 `{stock_code:"X", available:100, cost_price:12.5}` → `positions.vol == 100`
2. 单元测试：pos_cfm 推完整 `{volume:200, available:150}` → `vol=200, avl_vol=150`
3. 单元测试：pos_cfm 推 `{available:0}` → `vol=0, avl_vol=0`（兜底不会出错）
4. `pytest server/ -v` 全绿
5. 手动：登录后 Position.vue 总持仓列正常显示

## Spec Deltas

见 `spec-deltas/positioning.md`、`spec-deltas/push.md`、`spec-deltas/data-model.md`。

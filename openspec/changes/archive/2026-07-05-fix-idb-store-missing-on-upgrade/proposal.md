## Why

`client/src/stores/holdings_idb.js` 的 `initIDB()` 升级路径有 bug：`onupgradeneeded`
回调里 `if (oldV < 2) { db.deleteObjectStore(...) }` 会把刚被 `utils/idb.js`
自动创建的 `orders` / `trades` store 立刻删掉（`oldV=0` 也满足 `< 2`，
fresh install 路径同样触发），导致 DB 升到 v2 但 store 全部缺失。

`bootstrap` 阶段 `loadOrdersForDate` / `loadTradesForDate` → `idbGetAllKeys`
→ `db.transaction(store, 'readonly')` 抛 `NotFoundError: One of the specified
object stores was not found`，bootstrap 走 fallback RPC 路径（仍能正常出数据，
但 IDB cache 失效，每次 F5 都重新拉 RPC；写 IDB 同样静默失败）。

用户页面触发 console warn:
```
[IDB] _loadByDate(orders, 20260704) failed: ... object stores was not found.
[IDB] _loadByDate(trades, 20260704) failed: ... object stores was not found.
```

## What Changes

- 修 `client/src/stores/holdings_idb.js` 的 `initIDB()` 升级回调：
  - `oldV < 2` 仍按现状 `deleteObjectStore`（清 v12 keyPath='trd_date' 的旧 store，维度与 v13 复合 key 不兼容）
  - 删完立刻**显式 createObjectStore**，覆盖 fresh install + v12→v13 两条路径
- bump `DB_VERSION` 2 → 3，强制 `onupgradeneeded` 触发，让已损坏的 v2 DB
  （没 store 的中间状态）能 self-heal 到 v3 + store 完整
- `openDB` 包装 (`utils/idb.js`) 不动 — 它本身的设计（自动按 `storeNames` 创建缺失 store）正确，问题在用户的回调覆盖了它的语义

**BREAKING**: 无。`initIDB()` / `loadOrdersForDate` / `loadTradesForDate` /
`saveOrder` / `saveTrade` / `clearDate` 签名 + 行为均不变。仅升级路径内部修复。

## Capabilities

### Modified Capabilities
- 无（不上新 capability，不改现行 capability 边界；同步 `frontend/spec.md`
  的 `REQ-FE-300` 描述使其与 v3 schema 一致）

## Impact

- 受影响文件:
  - `client/src/stores/holdings_idb.js` (+3 行: 删完 create)
  - `openspec/specs/frontend/spec.md` (REQ-FE-300 描述同步到 v3)
- 不影响 IDB API 契约、不影响 Pinia store、不影响 view
- 单元测试: 18 用例 (`tests/client/stores/test_holdings_idb.js`) 应仍全过
  (mock 已含 onUpgrade, 但需要补一个 "createObjectStore 在 delete 后被调用"
  的断言 — task 里加)
- 验证:
  - `cd client && npm test -- --run` 全过
  - 用户浏览器 console 不再出现 `[IDB] _loadByDate(...) failed: ... object stores was not found`
  - `indexedDB` 面板查 `EvTrade-holdings-cache` 应见 `orders` / `trades` 两个 store

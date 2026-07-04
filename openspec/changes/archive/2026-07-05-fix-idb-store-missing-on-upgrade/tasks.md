# Tasks — fix-idb-store-missing-on-upgrade

单 commit。

## 1. holdings_idb.js 升级回调 + DB_VERSION bump (commit: fix(client))

- [x] 1.1 `client/src/stores/holdings_idb.js`:
  - `DB_VERSION` 2 → 3 (line 38)
  - `initIDB` 升级回调 (line 85-95): `oldV < 2` delete 完后, 加 2 行:
    ```js
    if (!db.objectStoreNames.contains(STORE_ORDERS)) db.createObjectStore(STORE_ORDERS)
    if (!db.objectStoreNames.contains(STORE_TRADES)) db.createObjectStore(STORE_TRADES)
    ```
  - 文档注释: 顶部 docblock 加 "v13 → v14 fix: 升级回调 deleteObjectStore 后漏 createObjectStore, 导致 v2/v3 DB store 缺失"
- [x] 1.2 同步 `openspec/specs/frontend/spec.md` `REQ-FE-300` 场景:
  - `initIDB` 描述: 版本 1 → **2 (v13) → 3 (v14 fix)**
  - 删 `## ADDED`/不需要新 Requirement, 改 `### Requirement: IDB 持久化模块契约`
    章节内"Scenario: 升级路径 store 重建"场景 (WHEN oldV<3 AND store 缺失 → THEN auto-create)
- [x] 1.3 验证:
  - `cd client && npm test -- --run` → 18 + 85 = 103 全过
  - `cd client && npx vite build` → OK
  - 手动 (用户刷浏览器): 打开 devtools → Application → IndexedDB →
    `EvTrade-holdings-cache` 应见 `orders` / `trades` 两个 store (版本 3)
  - console 不再出现 `[IDB] _loadByDate(...) failed: ... object stores was not found`

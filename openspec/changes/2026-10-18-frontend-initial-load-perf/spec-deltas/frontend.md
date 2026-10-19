# REQ-FE-556: 前端首屏加载性能 (frontend-initial-load-perf 2026-10-18)

## Phase 1 改动

### App.vue 不阻塞顶层 await

`client/src/App.vue` `onMounted` 中:
```diff
- if (!authStore.ready) {
-   try {
-     await authStore.hydrate()
-   } catch (e) {
-     console.warn('[App.vue] auth.hydrate failed:', e?.message || e)
-   }
- }
+ // 不再 await;fire-and-forget,首屏立即绘制 (v-if="!authStore.ready" 屏障仍保留)
+ authStore.hydrate().catch((e) =>
+   console.warn('[App.vue] auth.hydrate failed:', e?.message || e)
+ )
```

`auth.isAuthenticated` watch 改用 `ensureReady()` 共享 promise,不重复启动 hydrate。

### auth store 加 ensureReady

`client/src/stores/auth.js`:
```js
let _readyPromise = null
function ensureReady() {
  if (!_readyPromise) {
    _readyPromise = hydrate().catch((e) => {
      // 重置以允许下次重试
      _readyPromise = null
      throw e
    })
  }
  return _readyPromise
}
```

### Router guard await ensureReady

`client/src/router/index.js` `beforeEach` 顶部:
```js
try {
  await auth.ensureReady()
} catch (_) { /* 静默 — beforeEach 已能继续 */ }
```

保证 `auth.isAuthenticated / hasPageKey` 判断时 token 已从 IDB 读完,**不再误跳 /login**。

### Pinia stores 动态 import

不破坏现有 store API;**仅在 App.vue 调用的时机延后**:
- `useUiStore / useAuthStore / useWsStore` (路由/App 早期生命周期需要) → 仍顶层
- `useHoldingsStore / useStocksStore` (耗时 IDB 读取)在 `authStore.ready===true` watcher 块内触发

## 不改什么

- ❌ 不拆主图 chunk (Phase 2)
- ❌ 不改 view 业务代码
- ❌ 不改 router 结构 / pageKey
- ❌ 不动其他 store

## 验证

- `npm run build`: 主图 chunk 减 30-80 KB gzip (期望)
- `vite dev` 实测: F5 后首屏立即显示启动屏障 (1 帧),不等待 IDB
- 路由跳转: 500ms 内能进入 (IDB 已读完)

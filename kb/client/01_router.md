# Client · 01 · 路由表（Router）

> 文件：`client/src/router/index.js`
> 模式：`createWebHistory()`（不带 hash）

## 1. 路由清单

| path | name | 组件 | meta | 守卫 |
|------|------|------|------|------|
| `/login` | Login | `views/Login.vue` | `layout:'blank', public:true, title:'登录'` | 已登录跳 `/` |
| `/` | Dashboard | `views/Dashboard.vue` | `title:'仪表盘'` | 需登录 |
| `/positions` | Position | `views/Position.vue` | `title:'持仓管理'` | 需登录 |
| `/trade` | Trade | `views/Trade.vue` | `title:'交易下单', requiresTrader:true` | 需登录 + trader/admin |
| `/asset` | Asset | `views/Asset.vue` | `title:'账户资金'` | 需登录 |
| `/orders` | Orders | `views/Orders.vue` | `title:'委托查询'` | 需登录 |
| `/trades` | Trades | `views/Trades.vue` | `title:'成交查询'` | 需登录 |
| `/users` | Users | `views/Users.vue` | `title:'用户管理', requiresAdmin:true` | 需登录 + admin |
| `/profile` | Profile | `views/Profile.vue` | `title:'个人资料'` | 需登录 |
| `/:pathMatch(.*)*` | — | redirect → `/` | — | — |

所有组件使用**动态 import** 懒加载（分包）。

## 2. 守卫逻辑（`router.beforeEach`）

```js
router.beforeEach(async (to) => {
  // 1. 设置标题
  if (to.meta?.title) document.title = `${to.meta.title} · EvTrade`

  const auth = useAuthStore()

  // 2. 公开页（/login）
  if (to.meta?.public) {
    if (auth.isAuthenticated && to.path === '/login') return { path: '/' }
    return true
  }

  // 3. 未登录 → /login?redirect=...
  if (!auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 4. admin 守卫
  if (to.meta?.requiresAdmin && !auth.isAdmin) {
    return { path: '/' }
  }

  // 5. trader 守卫
  if (to.meta?.requiresTrader && !auth.isTrader) {
    return { path: '/' }
  }

  return true
})
```

## 3. 全局 401 处理

```js
setUnauthorizedHandler(() => {
  const auth = useAuthStore()
  auth.clear()
  if (router.currentRoute.value.path !== '/login') {
    router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})
```
由 `client/src/api/index.js` 的 axios 响应拦截器在 `status===401` 时触发。

## 4. 滚动行为
```js
scrollBehavior() { return { top: 0 } }
```
切换路由回到顶部。

## 5. 标题与 layout

`App.vue` 区分两种 layout：
```vue
<div v-if="isBlankLayout" class="blank-layout">
  <router-view />
</div>
<div v-else class="app-layout">
  <Sidebar />
  <div class="app-main">
    <AppHeader />
    <main class="app-content">
      <router-view v-slot="{ Component, route }">
        <transition name="page" mode="out-in">
          <component :is="Component" :key="route.fullPath" />
        </transition>
      </router-view>
    </main>
  </div>
</div>
```
- `isBlankLayout = route.meta?.layout === 'blank'`：仅 `Login.vue`
- 其它页面带 Sidebar + AppHeader
- 切换时通过 `:key="route.fullPath"` 强制重建，触发 `onMounted`

## 6. 新增页面清单

1. 在 `client/src/views/` 新建 `.vue` 文件
2. 在 `client/src/router/index.js` 加 `import` + `routes[]` 条目
3. 如需角色守卫，设 `meta.requiresAdmin` / `meta.requiresTrader`
4. 若要在 Sidebar 显示菜单项，改 `client/src/components/Sidebar.vue` 的 `menuItems`

## 7. AppHeader 标题映射

```js
const pageMeta = {
  '/':         { title: '仪表盘',     sub: '账户概览与今日行情' },
  '/positions':{ title: '持仓管理',   sub: '查看与管理您的持仓' },
  '/trade':    { title: '交易下单',   sub: '快速下单与今日委托' },
  '/orders':   { title: '委托查询',   sub: '历史委托记录' },
  '/trades':   { title: '成交查询',   sub: '历史成交明细' },
  '/asset':    { title: '账户资金',   sub: '资金详情与资产分布' },
  '/users':    { title: '用户管理',   sub: '管理系统账号与权限' },
  '/profile':  { title: '个人资料',   sub: '查看与编辑个人信息' }
}
```
新增页面需同步更新此处。

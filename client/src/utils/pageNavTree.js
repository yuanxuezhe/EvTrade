/**
 * pageNavTree.js — 页面导航 + 权限树 (rbac-roles-module 2026-09-21)
 *
 * 单一事实源 (Single Source of Truth):
 *   - client/src/components/Sidebar.vue 用它渲染左侧菜单
 *   - client/src/views/Roles.vue 用它渲染"页面权限"多选
 *   - 路由 meta.pageKey 必须在此树内 (新增路由必须登记)
 *
 * 结构: 树状 (group → pages)
 *   group:
 *     key       (String) - 稳定 key (供 i18n / 测试)
 *     label     (String) - 显示名 (中文)
 *     icon      (Component) - element-plus icon
 *     pageKey   (String|undefined) - 若该 group 自身是一个页面页 (dashboard)
 *                                     否则 undefined → 纯分组, 不可单独授权
 *     path      (String|undefined) - 同上
 *     children  (Array<page>) - 子页
 *   page:
 *     pageKey   (String) - 与 router meta.pageKey 严格对齐
 *     label     (String) - 显示名
 *     path      (String) - 路由 path
 *     icon      (Component) - element-plus icon
 *
 * 设计原则:
 *   1. 一个 group = 一个业务域 (交易/查询/系统/策略)
 *   2. group 可空 (children 为空时不渲染分组)
 *   3. group 自己不是 page 时 pageKey=undefined
 *   4. 单页无子页面时直接挂在某个 group 下
 *
 * 与 router meta.pageKey 对齐 — router/index.js 每条路由必须 有 pageKey 且存在于本树
 */
import {
  Odometer,           // 仪表盘
  Star,               // 自选池
  TrendCharts,        // 交易下单
  Coin,               // 快速做T
  DataAnalysis,       // 策略下单
  EditPen,            // 策略开发
  DataLine,           // 策略运行
  DataBoard,          // 证券信息
  Collection,         // 证券池
  Wallet,             // 资金查询
  Box,                // 持仓查询
  Tickets,            // 委托查询
  Document,           // 成交查询
  Setting,            // 系统初始化
  Operation,          // 系统配置
  UserFilled,         // 用户管理
  Avatar,             // 角色管理
  Refresh,            // 历史行情补全
  Money,              // 资金
} from '@element-plus/icons-vue'

/**
 * 树状结构 — 业务域 → 子页
 *
 * 2026-09-22 优化: 从 8 个混合 categories 改 6 个清晰业务域, 与页面权限设置树状结构 100% 对齐.
 */
export const PAGE_NAV_TREE = [
  {
    key: 'workbench',
    label: '工作台',
    children: [
      { pageKey: 'dashboard', label: '仪表盘', path: '/', icon: Odometer },
      { pageKey: 'asset', label: '账户资金', path: '/asset', icon: Money },
      { pageKey: 'profile', label: '个人资料', path: '/profile', icon: UserFilled },
    ],
  },
  {
    key: 'trade',
    label: '交易',
    children: [
      { pageKey: 'trade', label: '交易下单', path: '/trade', icon: TrendCharts },
      { pageKey: 't0-trade', label: '快速做T', path: '/t0-trade', icon: Coin },
      { pageKey: 'strategy-order', label: '策略下单', path: '/strategy-order', icon: DataAnalysis },
    ],
  },
  {
    key: 'strategy',
    label: '策略开发与运行',
    children: [
      { pageKey: 'script-dev', label: '策略开发', path: '/script-dev', icon: EditPen },
      { pageKey: 'script-task', label: '策略运行', path: '/script-task', icon: DataLine },
    ],
  },
  {
    key: 'basic-info',
    label: '基础信息',
    children: [
      { pageKey: 'admin-stock-config', label: '证券信息', path: '/admin/stock-config', icon: DataBoard },
      { pageKey: 'stkpool', label: '证券池', path: '/stkpool', icon: Collection },
      { pageKey: 'stkpool-view', label: '自选池 (只读)', path: '/stkpool-view', icon: Star },
    ],
  },
  {
    key: 'query',
    label: '交易查询',
    children: [
      { pageKey: 'cache-asset', label: '资金查询', path: '/admin/cache/asset', icon: Wallet },
      { pageKey: 'cache-positions', label: '持仓查询', path: '/admin/cache/positions', icon: Box },
      { pageKey: 'cache-orders', label: '委托查询', path: '/admin/cache/orders', icon: Tickets },
      { pageKey: 'cache-trades', label: '成交查询', path: '/admin/cache/trades', icon: Document },
    ],
  },
  {
    key: 'system',
    label: '系统管理',
    children: [
      { pageKey: 'roles', label: '角色管理', path: '/roles', icon: Avatar },
      { pageKey: 'users', label: '用户管理', path: '/users', icon: UserFilled },
      { pageKey: 'system-config', label: '系统配置', path: '/system-config', icon: Operation },
      { pageKey: 'system-init', label: '系统初始化', path: '/system-init', icon: Setting },
      { pageKey: 'data-completion-history-quote', label: '历史行情补全', path: '/data-completion/history-quote', icon: Refresh },
    ],
  },
]

/**
 * 平面化辅助 — 拿所有 page (含子页)
 * 返回: [{ pageKey, label, path, icon, groupKey, groupLabel }]
 */
export function flattenPages(tree = PAGE_NAV_TREE) {
  const out = []
  for (const group of tree) {
    for (const page of group.children || []) {
      out.push({
        ...page,
        groupKey: group.key,
        groupLabel: group.label,
      })
    }
  }
  return out
}

/** 树状结构 — element-plus el-tree 节点 (含 children) */
export function asElTreeData(tree = PAGE_NAV_TREE) {
  return tree.map((g) => ({
    key: g.key,
    label: g.label,
    children: (g.children || []).map((p) => ({
      key: p.pageKey,
      label: p.label,
      pageKey: p.pageKey,
    })),
  }))
}

/** 所有 pageKey 集合 (供 missing tests 用 keys 校验 router) */
export const ALL_PAGE_KEYS = flattenPages().map((p) => p.pageKey)
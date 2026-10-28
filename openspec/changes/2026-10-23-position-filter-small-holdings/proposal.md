# position-filter-small-holdings — 持仓查询页过滤小持仓 (2026-10-23)

## 解决什么

「交易查询 → 持仓查询」页 (`/admin/cache/positions`, `CachePositions.vue`) 当前展示全部持仓行,
没有过滤能力。用户希望在工具栏加一个 **checkbox「过滤小持仓」**:

- **勾选** → 隐藏「小持仓」行 (持仓量 ≤ 阈值 的行不显示)
- **取消勾选** → 全部显示 (当前默认行为)
- **阈值** → 存在系统配置里, 由管理员在「系统配置」页调整, 前端读该配置

## 现状摸底 (P0, 2026-10-23)

| 项 | 事实 |
|---|---|
| 页面 | `client/src/views/CachePositions.vue` (216 行), 路由 `/admin/cache/positions`, pageKey `cache-positions` |
| 数据源 | **前端 IDB** (`loadAllPositions()` from `stores/holdings_idb.js`) — 不是后端 API |
| 持仓字段 | `vol` (总持仓) / `avl_vol` (可用) / `last_vol` (期初) / `market_value` (市值) / `cost_price` |
| 现有过滤 | 只有 `stockCode` 模糊匹配 (`filteredResults` computed) |
| 现有工具栏 | `filter-bar` div + `filter-left` div + `el-input` (股票代码) |
| sysconfig 基础设施 | ✅ 完备: `server/services/sysconfig/__init__.py` (`DEFAULT_CONFIGS` + `get(key, default, user)` 类型自动 coerce) + `server/api/sysconfig.py` (CRUD) + `client/src/api/sysconfig.js` |
| sysconfig 现有 key | `commission_rate` / `stamp_tax_rate` / `slippage` / `min_commission` / `auto_reconcile` / `auto_use_broker_data` / `trdtime` / `must_change_password_required` / `cantrdstktypes` / `quote_sync_chunk_days` |

## 关键设计约束

1. **过滤在前端** — 数据源是 IDB, 后端不参与
2. **阈值走 sysconfig** — 复用现有配置体系, 不新建表 / 不改 schema
3. **默认不过滤** — checkbox 默认不勾选 = 当前行为 (100% 兼容)
4. **默认阈值 0** — 即使勾选且阈值未配置, `vol <= 0` 只过滤掉 0 持仓行, 不误伤
5. **比较含等号** — 用户原话「小于等于这个数的不显示」→ `vol <= threshold` 隐藏
6. **配置读取时机** — 页面 onMounted 时读一次; 管理员改配置后刷新页面生效 (不引入轮询)

## 配置项定义

| 项 | 值 |
|---|---|
| `cfg_key` | `position_filter_min_vol` |
| `cfg_val` (默认) | `0` |
| `desc` | `持仓查询页过滤小持仓阈值 (股数); 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤` |
| 类型 | int (`_coerce` 按 default 类型自动转) |
| scope | `user='0'` 全局默认 (管理员可在「系统配置」页改) |

## 实施计划

| # | 内容 | 类型 |
|---|---|---|
| C1 | OpenSpec change 工件 (本目录) | `docs(openspec)` |
| C2 | spec merge: `frontend/spec.md` 加 `REQ-FE-557` + `configuration/spec.md` 加 `REQ-SE-007` | `docs(spec)` |
| C3 | 后端: `DEFAULT_CONFIGS` 加 `position_filter_min_vol` seed | `feat(server)` |
| C4 | 前端: `CachePositions.vue` 加 checkbox + 过滤逻辑 + 阈值显示 | `feat(frontend)` |
| C5 | 知识库同步 (`知识库/前端/` + `知识库/后端服务/`) | `docs` |
| C6 | 验证: `npm run build` + `pytest server/tests/` (单文件) | 验证 |
| C7 | 归档 + 提交 + 推送 + 重启 | `docs(openspec)` |

## 不做什么

- ❌ 不改后端持仓查询 API (数据源是 IDB, 无后端参与)
- ❌ 不改 `PositionTable.vue` / `HoldingsPanel.vue` (Trade 页持仓面板, 非本次范围)
- ❌ 不改 `PAGE_NAV_TREE` / RBAC (本页 pageKey 不变)
- ❌ 不新建数据库表 / 不改 schema (复用 sys_config 表)
- ❌ 不做配置热轮询 (刷新页面生效)

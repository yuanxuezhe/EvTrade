# position-filter-small-holdings — 交易下单页持仓面板过滤小持仓 (2026-10-23)

## 解决什么

**交易下单页面** (`/trade`, `Trade.vue`) 右上角的 **持仓 mini 面板**
(`client/src/components/trade/HoldingsPanel.vue`) 当前展示全部持仓行,没有过滤能力。

用户希望在该面板加一个 **checkbox「过滤小持仓」**:

- **勾选** → 隐藏「小持仓」行 (持仓量 ≤ 阈值 的行不显示)
- **取消勾选** → 全部显示 (当前默认行为)
- **阈值** → 存在系统配置里, 由管理员在「系统配置」页调整, 前端读该配置

> ⚠️ **范围澄清 (2026-10-23 用户明确)**: 是**交易下单页面**的持仓面板,
> **不是**「交易查询 → 持仓查询」页 (`CachePositions.vue`)。后者不在本次范围。

## 现状摸底 (P0, 2026-10-23)

| 项 | 事实 |
|---|---|
| 组件 | `client/src/components/trade/HoldingsPanel.vue` (329 行), 挂载于 `Trade.vue` 右上角 |
| 数据源 | `useHoldingsStore().positions` (Pinia, 后端 `/api/positions` → IDB 缓存) |
| 持仓字段 | `vol` (持仓) / `avl_vol` (可用) / `last_vol` (期初) / `market_value` / `cost_price` |
| 现有过滤 | 只有 `keyword` 代码/名称模糊匹配 (`filteredPositions` computed) |
| 现有工具栏 | `tp-header` div: 标题「持仓」+ `{{ filteredPositions.length }} 只 / 持仓 {{ totalMv }}` + `el-input` 代码过滤 |
| `totalMv` | 基于 `filteredPositions` 求和 → 过滤后总市值随之变化 (显示一致, 符合预期) |
| sysconfig 基础设施 | ✅ 完备: `server/services/sysconfig/__init__.py` (`DEFAULT_CONFIGS` + `get(key, default, user)` 类型自动 coerce) + `server/api/sysconfig.py` (CRUD) + `client/src/api/sysconfig.js` |
| sysconfig 现有 key | `commission_rate` / `stamp_tax_rate` / `slippage` / `min_commission` / `auto_reconcile` / `auto_use_broker_data` / `trdtime` / `must_change_password_required` / `cantrdstktypes` / `quote_sync_chunk_days` |

## 关键设计约束

1. **过滤在前端** — 数据源是 Pinia holdings store, 后端不参与
2. **阈值走 sysconfig** — 复用现有配置体系, 不新建表 / 不改 schema
3. **默认勾选** — checkbox 默认勾上 (用户 2026-10-23 明确要求); 阈值 0 时等价于不过滤 (100% 兼容)
4. **默认阈值 0** — 即使勾选且阈值未配置, `vol <= 0` 只过滤掉 0 持仓行, 不误伤
5. **比较含等号** — 用户原话「小于等于这个数的不显示」→ `vol <= threshold` 隐藏
6. **配置读取时机** — 组件 onMounted 时读一次; 管理员改配置后刷新页面生效 (不引入轮询)
7. **过滤字段 = `vol`** (持仓股数, 与表格「持仓」列同源)

## 配置项定义

| 项 | 值 |
|---|---|
| `cfg_key` | `position_filter_min_vol` |
| `cfg_val` (默认) | `0` |
| `desc` | `交易下单页持仓面板过滤小持仓阈值 (股数); 勾选「过滤小持仓」时 vol<=此值的行隐藏, 0=不过滤` |
| 类型 | int (`_coerce` 按 default 类型自动转) |
| scope | `user='0'` 全局默认 (管理员可在「系统配置」页改) |

## 实施计划

| # | 内容 | 类型 |
|---|---|---|
| C1 | OpenSpec change 工件 (本目录) | `docs(openspec)` |
| C2 | spec merge: `frontend/spec.md` 加 `REQ-FE-557` + `configuration/spec.md` 加 `REQ-SE-014` | `docs(spec)` |
| C3 | 后端: `DEFAULT_CONFIGS` 加 `position_filter_min_vol` seed | `feat(server)` |
| C4 | 前端: `HoldingsPanel.vue` 加 checkbox + 过滤逻辑 + 阈值显示 | `feat(frontend)` |
| C5 | 知识库同步 (`知识库/前端/`) | `docs` |
| C6 | 验证: `npm run build` + `pytest server/tests/` (单文件) | 验证 |
| C7 | 归档 + 提交 + 推送 + 重启 | `docs(openspec)` |

## 不做什么

- ❌ 不改 `CachePositions.vue` (「交易查询 → 持仓查询」页, 非本次范围)
- ❌ 不改 `PositionTable.vue` / `Position.vue` / `T0Trade.vue`
- ❌ 不改后端持仓查询 API (数据源是 Pinia, 后端不参与)
- ❌ 不改 `PAGE_NAV_TREE` / RBAC
- ❌ 不新建数据库表 / 不改 schema (复用 sys_config 表)
- ❌ 不做配置热轮询 (刷新页面生效)

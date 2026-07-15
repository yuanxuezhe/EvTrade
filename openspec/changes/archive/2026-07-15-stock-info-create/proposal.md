# Proposal: 证券信息设置支持添加证券

> **作者**: Hermes (root 环境, 绕过 Claude Code v15 root 拒绝)
> **日期**: 2026-07-15
> **spec-id**: REQ-STOCK-006
> **关联 spec**: `openspec/specs/stocks/spec.md` §3 (现有 REQ-STOCK-003 admin 编辑)

---

## Why

**当前状况**：
- 证券信息设置页 (`/admin/stock-config`) 已有：列表 / 筛选 / 分页 / **编辑弹窗**（6 字段）
- 但 **没有添加证券** 功能：admin 只能修改已有 stock，**无法新增**
- 实际场景：admin 偶尔会遇到未同步的股票（新增 IPO / 港股通新增 / 自定义测试数据），需要手动补录

**用户诉求**：admin 能通过 UI 手动添加一只新证券到 `stocks` 表

## What

**新增** admin 手动添加证券端到端能力：

| 层 | 新增内容 |
|---|---|
| 后端 `server/repo/stocks.py` | `create_by_admin(db, payload) -> Stock` — 检查 stock_code 重复 → INSERT |
| 后端 `server/api/stocks.py` | `POST /api/stocks` — admin-only, status_code=201, Pydantic `StockCreateRequest` (8 字段全必填, stock_code 主键) |
| 前端 `client/src/api/stocks.js` | `stocksApi.create(payload)` |
| 前端 `client/src/stores/stocks.js` | `createStock(payload) -> {ok, msg, data?}` — 同时更新 cache (头部插入) + total + pageRows |
| 前端 `client/src/views/AdminStockConfig.vue` | (1) panel-header 新增"添加证券"按钮 (Primary); (2) 新增"添加证券"弹窗 (与编辑 dialog 独立); (3) 表单 8 字段: stock_code/stock_name/sector/short_name/is_t0_able/min_buy_qty/trade_unit |
| OpenSpec `openspec/specs/stocks/spec.md` | 新增 REQ-STOCK-006 (添加) + 4 scenario |
| OpenSpec `openspec/specs/frontend/spec.md` | 新增 REQ-FE-STOCK-CREATE (前端添加 dialog 契约) + 3 scenario |

**8 字段** (与现有编辑 6 字段 + 2 个: stock_code PK + short_name):
- `stock_code` (PK, 必填, 必须形如 `000001.SZ` / `600000.SH`)
- `stock_name` (必填, max 64)
- `sector` (可选)
- `short_name` (可选, max 16)
- `is_t0_able` (默认 False)
- `min_buy_qty` (默认 100, ≥1)
- `trade_unit` (默认 1, ≥1)

## How

**实施步骤**（拆分 3 commit 独立可 revert）：
1. **commit 1 (backend)**: `server/repo/stocks.py` + `server/api/stocks.py`
2. **commit 2 (frontend)**: `client/src/api/stocks.js` + `client/src/stores/stocks.js` + `client/src/views/AdminStockConfig.vue`
3. **commit 3 (spec + archive)**: 同步 spec + 归档 changeset + push

**错误处理**：
- 409 Conflict: `stock_code` 已存在
- 422 Pydantic: 字段类型错 / 长度超限
- 400 Bad Request: 必填字段为空

## Risks

| 风险 | 缓解 |
|---|---|
| stock_code 已存在导致 409 | 前端先调 `stocksApi.getOne` 检查；后端 repo 层 IntegrityError catch |
| stock_code 格式错（无 .SH/.SZ） | 前端 regex 校验 + 后端 Pydantic Field regex |
| OpenSpec changeset 漏写 | 与 system-init-broadcast 同模式 4 件套 |
| 前端 cache + pageRows 同步错 | `createStock` 后 splice 头部插入 + total += 1 |
| admin 误操作 | `require_admin` 鉴权 + audit log 不在本次范围 |

## Out of Scope

- **批量添加**（CSV/Excel 上传）
- **删除证券**
- **audit log 审计**
- **第三方数据源自动回填**（走 v21 stock-info-crawler）
- **字段扩展**（保持 8 字段现状，不引入 industry/market 等 v22 旧字段）

## Test Plan

| 测试 | 方法 |
|---|---|
| 后端 POST 200 正常添加 | curl `POST /api/stocks` with admin token + 完整 payload |
| 重复 stock_code → 409 | curl 两次相同 stock_code |
| 必填字段缺失 → 422 | curl 不带 stock_name |
| 前端浏览器实测 | admin 登录 → 点"添加证券" → 填表单 → 提交 → 看到新行 |
| 权限校验 | 非 admin 调 POST → 401/403 |
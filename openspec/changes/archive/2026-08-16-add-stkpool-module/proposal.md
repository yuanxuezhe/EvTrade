# add-stkpool-module — 新增"证券池"模块

## Why

`EvTrade` 当前缺乏"用户/策略维度的自定义股票分组"维度。`stocks` 表只管主数据，`positions` 表只管持仓快照，策略任务、`T0` 任务都是按 `stock_code` 独立触发的——**没有人能在 UI 上说"我关注这 50 只股票"**。

用户在交易/做 T/选股时经常需要:

- 把一组相关性强的股票放进自定义池（例如"白马组合"、"ETF 观察池"）
- 后续接策略 / T0 任务 / 监控看板时按池批量拉取
- 一次维护，多次复用

现有 22 张表都是"账户/委托/行情/策略"维度，**没有"自定义分组"维度的承载**。本次新增 `stkpool` (主表) + `stkpooldetail` (明细表) 两张表，承载这个新维度。

## 决策（用户明确选择）

### 决策 1：A — 复合 PK `(id, stock_code)`，share-id 模式

- 主表 `stkpool.id` 自增
- 明细表 `stkpooldetail` 的 `id` 字段**不是自增**，而是引用主表 `id`（物理聚簇）
- 复合 PK `(id, stock_code)` 天然去重（同池同股票不会重复）
- 查询"池 X 的明细" = `WHERE id = X`（PK 范围扫，无次索引开销）
- 删除池子 → `ON DELETE CASCADE` 自动清明细，无需手动两段 DELETE

### 决策 2：A — 主表全局共享，不分用户

- 不加 `user_id` 字段
- 所有登录用户看同一份池列表
- 走 `auth` 鉴权（任何合法用户都能用），不分 RBAC 角色
- 后续需"私有池"可平滑加 `user_id` 字段（MySQL migration 即可）

### 决策 3：A — 加 `created_at`

- 主表加 `created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`
- 用于审计 / 列表排序（按创建时间倒序取"最新池"）
- 字段约定与现有表一致（`strategy_order`、`t0_tasks` 等）

### 决策 4：A — 前端菜单作为"证券信息"同级别顶级项（修订）

- **修订**：菜单是**与"证券信息"同级别**的顶级项，**不是子菜单**
- 只是顺序**排在"证券信息"下面**（menuItems 数组依次排列）
- 路由路径 `/stkpool`（独立顶层路由，不在 `/admin/*` 命名空间下）
- 复用现有 `Sidebar.vue` 顶级项模式（class 比"资金查询/持仓查询"等）

### 决策 5：A — 走 OpenSpec 流程

- 本 change 即承担 proposal + tasks + design + 3 份 delta specs
- 落码用 `/opsx:apply`

## 安全备注（风险登记）

- **share-id 模型在项目内零先例**：22 张表全是自增 PK + 独立明细 FK。本次是首个走 share-id 的表，`tables-codegen` 需人工复核 `__auto_increment_pk__ = None` 是否正确写入（不是 `'id'`）。
- **MySQL DDL 关键约束**：`stkpooldetail.id` 必须**显式不写 `AUTO_INCREMENT`**，否则 INSERT 时 DB 自动赋值会破坏"明细 id = 主表 id"语义。
- **删除池 CASCADE 风险**：误删池子会无声清掉所有明细。当前设计无软删除，误操作不可逆——首次上线会标注"删除会清空明细"提示，二期可加 `is_deleted` 软删除。

## What Changes

### 后端 — 表结构

新增两张 MySQL 表（位于 `evtrade_dev` 库）：

```sql
-- 主表
CREATE TABLE stkpool (
    id INT NOT NULL AUTO_INCREMENT COMMENT '行主键',
    name VARCHAR(64) NOT NULL COMMENT '池名 (唯一)',
    remark VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_stkpool_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='证券池主表';

-- 明细表（share-id 模式）
CREATE TABLE stkpooldetail (
    id INT NOT NULL COMMENT '共享主表 id (不自增, 与 stkpool.id 一一对应)',
    stock_code VARCHAR(16) NOT NULL COMMENT '股票代码',
    PRIMARY KEY (id, stock_code),
    KEY ix_stkpooldetail_id (id),
    FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='证券池明细: share PK id + stock_code, 物理聚簇';
```

### 后端 — Table 类

- `server/tables/stkpool.py`：`Stkpool` 类，`__auto_increment_pk__ = 'id'`
- `server/tables/stkpooldetail.py`：`StkpoolDetail` 类，`__auto_increment_pk__ = None`，`__pk_fields__ = ('id', 'stock_code')`
- `server/tables/__init__.py` 追加两行 import

### 后端 — Repo 层

- `server/repo/stkpool.py`：`StkpoolRepo` 封装 CRUD 业务流
  - `list_pools() -> List[Row]`：全量主表，按 `id ASC`
  - `get_pool(pool_id) -> Row | None`
  - `create_pool(name, remark) -> Row`：upsert 主表
  - `update_pool(pool_id, name, remark) -> Row`
  - `delete_pool(pool_id) -> bool`：删主表 → CASCADE 清明细
  - `list_detail(pool_id) -> List[Row]`：明细查询（按 `stock_code ASC`）
  - `add_detail(pool_id, stock_code) -> Row`：upsert 明细
  - `remove_detail(pool_id, stock_code) -> bool`：复合 PK 删

### 后端 — API 层

- `server/api/stkpool.py`：5 个 REST 端点
  - `GET /api/stkpool` — 主表列表
  - `POST /api/stkpool` — 创建池
  - `PUT /api/stkpool/{pool_id}` — 改池名/备注
  - `DELETE /api/stkpool/{pool_id}` — 删池（CASCADE）
  - `GET /api/stkpool/{pool_id}/detail` — 池明细
  - `POST /api/stkpool/{pool_id}/detail` — 加明细
  - `DELETE /api/stkpool/{pool_id}/detail/{stock_code}` — 删明细

（Pydantic schema 放 `server/api/stkpool.py` 同文件，1 个 `StkpoolCreate` / `StkpoolUpdate` 即可）

### 后端 — 路由注册

- `server/main.py` 第 24-33 行路由清单追加 `include_router(stkpool.router, prefix="/api/stkpool")`

### 前端 — API 封装

- `client/src/api/stkpool.js`：`stkpoolApi.list/get/create/update/delete/detailAdd/detailRemove` 7 个方法
- 走 `axios` 通用基址（与现有 `stocksApi` 同模式）

### 前端 — 视图

- `client/src/views/StkPool.vue`：左右布局
  - 左 40%：`el-table` 主表 + "新建池"按钮；点击行 → 触发右侧查询
  - 右 60%：当前池头部（池名/备注 + 编辑/删除）+ "添加股票"按钮 + 明细 `el-table`
  - 默认进入页面 → 拉主表 → 自动选第一条 → 触发右侧明细查询
  - 空状态：主表空 → 右区显示"暂无池，请新建"
- 添加股票对话框：复用 `client/src/components/StockCodePicker.vue`（REQ-FE-521，v28 严格语义）
- 显示股票名：明细行 `stock_name` 字段从 `useStocksStore().cache` 读（不存后端）

### 前端 — 路由 + 菜单

- `client/src/router/index.js` 追加：`{ path: '/stkpool', component: () => import('@/views/StkPool.vue'), meta: { title: '证券池' } }`
- `client/src/components/Sidebar.vue` 第 80-109 `menuItems` 数组：在"证券信息"项**之后**插入顶级项 `{ name: '证券池', path: '/stkpool' }`（不嵌套为子菜单）
  - 沿用"证券信息"同级别顶级项模式（与"资金查询/持仓查询"等并列顶级项同形态）

### 迁移脚本

- `server/migrations/2026-08-16-add-stkpool.py`：3 步幂等迁移
  1. CREATE TABLE `stkpool`
  2. CREATE TABLE `stkpooldetail`（带 FK ON DELETE CASCADE）
  3. 主表 `name` 字段加 `UNIQUE KEY uk_stkpool_name`（幂等：先查 INFORMATION_SCHEMA）
- 模板：`server/migrations/2026-08-11-add-strategy-order.py`（110+ 行标准范式）

### 表类代码生成

- 不调 `tables-codegen` 自动生成（share-id 模型在 codegen 里未验证）
- **手写** `server/tables/stkpool.py` + `server/tables/stkpooldetail.py`
- 写完用 `python -c "from server.tables.stkpool import Stkpool; print(Stkpool.__tablename__)"` 验证 import OK

## 时序

### 创建池 + 加入股票

```
前端: 用户点"新建池"
  → 弹 dialog 输入 name/remark
  → stkpoolApi.create({name, remark})
  → 后端 POST /api/stkpool → StkpoolRepo.create_pool → upsert_one
  → 返回 Row { id: 5, name: "白马", ... }
  → 前端刷新主表 + 选中 id=5
  → 触发右侧明细查询 (empty)

前端: 用户点"添加股票"
  → 弹 dialog + StockCodePicker
  → 选 600519.SH
  → stkpoolApi.detailAdd(5, '600519.SH')
  → 后端 POST /api/stkpool/5/detail
  → StkpoolRepo.add_detail(5, '600519.SH')
  → upsert_one({'id': 5, 'stock_code': '600519.SH'}, id=5, stock_code='600519.SH')
  → 前端右区表格追加一行
```

### 切换池

```
前端: 用户点池 B (id=7)
  → selectedPoolId = 7
  → watch 触发 → stkpoolApi.detail(7)
  → 后端 GET /api/stkpool/7/detail
  → StkpoolRepo.list_detail(7) → query_by('id', 7) → List[Row]
  → 返回 [{id:7, stock_code:'000001.SZ'}, ...]
  → 前端渲染右区明细
```

### 删除池（CASCADE）

```
前端: 用户点"删除池 A"
  → 二次确认（提示"将清除 N 只明细"）
  → stkpoolApi.delete(5)
  → 后端 DELETE /api/stkpool/5
  → StkpoolRepo.delete_pool(5) → Stkpool.delete_one(id=5)
  → MySQL CASCADE 自动 DELETE 所有 id=5 的 stkpooldetail 行
  → 前端刷新主表 + 切到下一条
```

## 改动文件清单

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `server/migrations/2026-08-16-add-stkpool.py` | 新增（110+ 行，幂等 3 步） |
| Tables | `server/tables/stkpool.py` | 新增（手写，~40 行） |
| Tables | `server/tables/stkpooldetail.py` | 新增（手写，~40 行） |
| Tables | `server/tables/__init__.py` | 追加 2 行 import |
| Repo | `server/repo/stkpool.py` | 新增（~80 行，CRUD 业务流） |
| API | `server/api/stkpool.py` | 新增（~100 行，5 端点 + 2 schema） |
| 路由 | `server/main.py` | 追加 1 行 `include_router` |
| 前端 API | `client/src/api/stkpool.js` | 新增（~50 行） |
| 视图 | `client/src/views/StkPool.vue` | 新增（~250 行，左右布局） |
| 路由 | `client/src/router/index.js` | 追加 1 项路由 |
| 菜单 | `client/src/components/Sidebar.vue` | "证券信息"后追加顶级项（不嵌套为子菜单） |
| Spec | `openspec/specs/data-model/spec.md` | 新增 REQ-STKPOOL-* 段 |
| Spec | `openspec/specs/server-architecture/spec.md` | 新增 REQ-STKPOOL-* 段 |
| Spec | `openspec/specs/frontend/spec.md` | 新增 REQ-STKPOOL-* 段 |

## 关联

- **上游**：
  - `REQ-FE-521`（StockCodePicker v28 严格语义契约）—— 添加股票对话框复用
  - `useStocksStore.cache`（5529 行全量内存缓存）—— 池明细展示股票名
  - `TableBase.__pk_fields__ = (..., ...)` 支持的复合 PK（`base.py:17-19` 注释）
  - `tables-codegen` SKILL.md L162 规则：`__auto_increment_pk__` 仅在 EXTRA 含 `auto_increment` 时设置
- **下游**：
  - 未来 strategy 任务可按池绑定（不在本次 scope）
  - 未来 T0 任务可按池批量创建（不在本次 scope）
  - 未来监控看板可按池分组（不在本次 scope）

## 非目标（Non-goals）

- ❌ 池子归属用户（user_id 字段）—— 本次全局共享
- ❌ 池子权限/可见性分级（admin/普通用户）—— 走 auth 统一鉴权
- ❌ 池子的"私有/共享"切换
- ❌ 池子索引（query_by_field 性能优化）—— 100 池以内不需要
- ❌ 池子导出/导入（Excel/CSV）—— 二期
- ❌ 池子拖拽排序、标签、颜色等增强 UI
- ❌ 将池子与 strategy / T0 任务打通（本 change 仅做 CRUD，不联动下游模块）
- ❌ 软删除 / 删除回收站
- ❌ 池子变更审计日志

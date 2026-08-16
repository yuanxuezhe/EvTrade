# add-stkpool-module — 设计文档

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EvTrade 系统                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  client (Vue 3)                  server (FastAPI)              MySQL 8     │
│  ┌───────────────────┐            ┌──────────────────┐          ┌────────┐  │
│  │ StkPool.vue       │            │ api/stkpool.py   │          │stkpool │  │
│  │  ┌─────┬───────┐  │  axios /api│  GET /api/stkpool│  SQLAlchemy    │      │
│  │  │ 主表 │  明细  │  ├──────────►│  POST /api/stkpool│         │       │
│  │  │(40%) │ (60%) │  │  JSON    │  PUT /api/stkpool│         │ pk:id   │ │
│  │  └─────┴───────┘  │            │  DELETE  /...    │         │uk:name  │ │
│  │        │          │            │  GET /:id/detail │         │       │ │
│  │        ▼          │            │  POST /:id/detail│         │stkpool-│ │
│  │  useStocksStore   │            │  DELETE /:id/.../│         │detail  │ │
│  │  .cache (stock_   │            │       :stock_code│         │pk:(id,  │ │
│  │  name 查询)        │            └────────┬─────────┘         │ stock_ │ │
│  └───────────────────┘                     │                   │ code) │ │
│                                            ▼                   │FK:    │ │
│                                  ┌──────────────────┐          │cascade│ │
│                                  │ repo/stkpool.py  │          └────┬──┘ │
│                                  │ StkpoolRepo      │               │    │
│                                  │  - list_pools    │  TableBase    │    │
│                                  │  - create_pool   │ ──────────────┘    │
│                                  │  - add_detail    │                    │
│                                  │  - delete_pool   │  ◄── ON DELETE CASCADE
│                                  └────────┬─────────┘                    │
│                                           ▼                              │
│                                  ┌──────────────────┐                    │
│                                  │ tables/stkpool.py │  TableBase 衍生    │
│                                  │ tables/stkpool-  │  MySQL 元数据      │
│                                  │   detail.py       │                    │
│                                  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

数据流：Vue 视图 → axios → FastAPI router → Repo → TableBase → MySQL。

## 2. 关键设计抉择

### 2.1 share-id 模型（最核心的设计）

**为什么选择 share-id**：

```
方案 A: share-id (本 change 选择)
┌─────────────────┬──────────────────────────┐
│ stkpool         │ stkpooldetail            │
├─────────────────┼──────────────────────────┤
│ id = 1 ◄────────┤ id = 1, stock_code = A  │
│ id = 1 ◄────────┤ id = 1, stock_code = B  │
│ id = 1 ◄────────┤ id = 1, stock_code = C  │  ← 同池同 id 共享
│ id = 2 ◄────────┤ id = 2, stock_code = D  │
└─────────────────┴──────────────────────────┘
PK: (id, stock_code) 复合
物理聚簇: 同池明细在 InnoDB 连续页, 范围扫 O(1)

方案 B: 标 FK (项目 22 张表用)
┌─────────────────┬──────────────────────────┐
│ stkpool         │ stkpooldetail            │
├─────────────────┼──────────────────────────┤
│ id = 1          │ id = 100, pool_id = 1 ◄──┤FK
│ id = 1          │ id = 101, pool_id = 1 ◄──┤FK
│ id = 1          │ id = 102, pool_id = 1 ◄──┤FK
│ id = 2          │ id = 103, pool_id = 2 ◄──┤FK
└─────────────────┴──────────────────────────┘
PK: id 自增
查询: WHERE pool_id = 1, 走次索引
```

**优势**：

1. **物理聚簇**：查询池 X 明细 = `WHERE id = X`，PK 范围扫，无次索引
2. **零额外索引**：明细表只需 PK 即可高性能，无需 `ix_pool_id`
3. **CASCADE 优雅**：删池 → MySQL 自动清，零额外代码
4. **数据自描述**：明细"长什么样" = 主表"长什么样"

**代价**：

1. **明细无独立行号**：无法 `WHERE id = 1, stock_code = 'X' UPDATE set sort_order = 2`（除非加排序列）
2. **项目内零先例**：未在 22 张表里验证过
3. **schema 演化成本**：后续加 `added_at` / `note` 字段还能加；想给明细独立 PK 就要重构

**未来若重构**：MySQL 层面是 `ALTER TABLE stkpooldetail ADD COLUMN id INT AUTO_INCREMENT PRIMARY KEY FIRST`，但会丢失现 share-id 关联。

### 2.2 复合 PK 写入语义

```python
# 明细表 upsert_one 必须显式传 PK
StkpoolDetail.upsert_one(
    {'id': 5, 'stock_code': '600519.SH'},
    id=5, stock_code='600519.SH'
)
```

**为什么不用 `add_one`**：

- `add_one` 跳过 `__auto_increment_pk__` 字段（这里 `id` **不自增**，不能跳过）
- `upsert_one` 强制 PK 入参（复合 PK 设计契合）
- 项目约定（`tables-codegen` SKILL.md L23-29）：**统一用 `upsert_one`**

**MySQL 端 SQL**：

```sql
INSERT INTO stkpooldetail (`id`, `stock_code`) VALUES (5, '600519.SH')
ON DUPLICATE KEY UPDATE `stock_code` = VALUES(`stock_code`)
-- 重复 PK → 不抛错, 走 UPDATE 分支 (实际 stock_code 没变, 无副作用)
```

### 2.3 CASCADE 删池

**MySQL 端**：

```sql
FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE
```

**SQLAlchemy 端**：无需业务代码处理删明细，TableBase.delete_one(id=5) 只删主表，CASCADE 自动生效。

**风险**：误删池 → 误清明细。本期不做软删除，UI 加二次确认提示。

### 2.4 明细查询优先 `query_by('id', X)` 而非 `query_by_fields({'id': X})`

```python
# 推荐
StkpoolDetail.query_by('id', 5)  # 单字段快路径

# 也可
StkpoolDetail.query_by_fields({'id': 5})  # 多字段接口
```

前者走 `base.py:341-367` 的快路径，SQL 更简洁。

### 2.5 前端批量添加股票（替代单条 StockCodePicker）

```vue
<el-button @click="onOpenBatchAdd">+ 批量添加</el-button>
```

**弹窗结构**：

- 搜索栏：`el-input` + 前缀 Search icon + clearable，支持 stock_code / stock_name / short_name 三字段不区分大小写模糊匹配
- 过滤开关：`el-checkbox v-model="batchHideInPool"` 默认 true（排除已在池内的股票，避免重复）
- 已选 chips：前 12 个显示蓝色 tag，超过显示 `+N 更多`
- 表格：`el-table` + 多选列 + `row-key="stock_code"` + `:reserve-selection="true"`，max-height 420
- 数据源：`useStocksStore.cache`（5529 行内存全量）
- 提交：循环调 `stkpoolApi.detailAdd(poolId, code)`，统计成功/失败

数据源 = `useStocksStore.cache`（5529 行全量股票；通过 store 暴露的 `stockName(code)` 方法访问，内部走 `cacheMap.get(code)` O(1) 查找）。
无需后端再查股票名，省一次 round-trip。

**为什么不用 StockCodePicker**：

- v28 StockCodePicker 是单条输入 + 严格 v-model（REQ-FE-521），不适合多选场景
- 批量场景需要：表格视图 + 复选框 + chips 联动
- 复用 `useStocksStore.cache` 直接构建表格数据，避免再次走 StockCodePicker 的搜索算法

**明细行 stock_name 渲染**：

```js
function getStockName(code) {
  return useStocksStore().stockName(code) || code
}
```

`stockName(code)` 在 cache 未 loaded 时返 null，兜底显示 code（不阻塞）。

### 2.6 默认选中第一条

```js
onMounted(async () => {
  await loadPools()  // 拿主表
  if (pools.value.length > 0) {
    selectedPoolId.value = pools.value[0].id  // 选中第一条
    await loadDetail(selectedPoolId.value)   // 触发右侧查询
  }
})
```

`watch(selectedPoolId)` 监听切换，无需手动调。

**空状态**：

```vue
<template v-if="!selectedPoolId">
  <el-empty description="暂无池，请新建" />
</template>
```

### 2.7 路由位置决断

**Sidebar.vue** 当前结构（基于上轮探索看到的）：

```
menuItems = [
  仪表盘, 交易下单, 快速做T, 策略开发, 策略运行, 策略下单,
  系统初始化, 系统配置, 用户管理, 证券信息, 资金查询, 持仓查询, ...
]
```

"证券信息"当前是顶级项，对应 `AdminStockConfig.vue`。

**实施（用户修订决策 4）**：

- `stkpool` 是**与"证券信息"同级别的顶级菜单项**
- 不是子菜单 —— 不改 `el-sub-menu` 包裹结构
- 仅在 `menuItems` 数组中"证券信息"**之后**追加一个顶级项
- 路由路径独立：`/stkpool`（顶层路由，不在 `/admin/*` 命名空间下）

```js
// 改动示例（menuItems 数组）
{ name: '证券信息', path: '/admin/stock-config' },
{ name: '证券池', path: '/stkpool' },  // 新增顶级项，紧跟"证券信息"
```

**业务理由**：

- 池子与股票配置是两个独立业务（CRUD 股票 vs 业务自定义分组），没必要套父子
- 路由命名空间 `stkpool` vs `admin/stock-config` 各自独立，权限演化互不干扰
- UI 简洁：14 个顶级项 → 15 个顶级项，无嵌套深度

## 3. 接口契约（API 摘要）

### 3.1 主表端点

```
GET    /api/stkpool                     → 200 { pools: [{id, name, remark, created_at}, ...] }
POST   /api/stkpool                     → 201 { id, name, remark, created_at }
       body: { name: str, remark?: str }
       422 VALIDATION_ERROR (name 空 / 缺)
       409 POOL_NAME_DUPLICATE (name 重复)
PUT    /api/stkpool/{pool_id}           → 200 { id, name, remark, created_at }
       body: { name?: str, remark?: str }
       404 POOL_NOT_FOUND
DELETE /api/stkpool/{pool_id}           → 204
       404 POOL_NOT_FOUND
       CASCADE: 所有 stkpooldetail.id=pool_id 行被 MySQL 删除
```

### 3.2 明细端点

```
GET    /api/stkpool/{pool_id}/detail    → 200 { details: [{stock_code}, ...] }
                                          (按 stock_code ASC)
POST   /api/stkpool/{pool_id}/detail    → 201 { id, stock_code }
       body: { stock_code: str }
       404 POOL_NOT_FOUND
       重复 (id, stock_code) → 200 (idempotent, return existing)
DELETE /api/stkpool/{pool_id}/detail/{stock_code}
                                     → 204
       404 POOL_NOT_FOUND | DETAIL_NOT_FOUND
```

**Pydantic Schema**（放 `server/api/stkpool.py`）：

```python
class StkpoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    remark: str = Field(default='', max_length=255)

class StkpoolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=255)

class StkpoolDetailAdd(BaseModel):
    stock_code: str = Field(pattern=r'^\d{6}\.(SH|SZ|BJ)$')
```

## 4. 数据模型细节

### 4.1 主表 `stkpool`

```sql
CREATE TABLE stkpool (
    id INT NOT NULL AUTO_INCREMENT COMMENT '行主键',
    name VARCHAR(64) NOT NULL COMMENT '池名 (唯一)',
    remark VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_stkpool_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='证券池主表';
```

**字段决策**：

- `name VARCHAR(64) NOT NULL` — UI 展示唯一名
- `remark VARCHAR(255) DEFAULT ''` — 备注，可空
- `created_at DATETIME DEFAULT CURRENT_TIMESTAMP` — 用于排序
- `UNIQUE KEY uk_stkpool_name (name)` — 防重名

### 4.2 明细表 `stkpooldetail`

```sql
CREATE TABLE stkpooldetail (
    id INT NOT NULL COMMENT '共享主表 id (不自增)',
    stock_code VARCHAR(16) NOT NULL COMMENT '股票代码',
    PRIMARY KEY (id, stock_code),
    KEY ix_stkpooldetail_id (id),
    FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='证券池明细: share PK id + stock_code';
```

**字段决策**：

- `id INT NOT NULL` — **关键**：不写 `AUTO_INCREMENT`，由应用层写入
- `stock_code VARCHAR(16) NOT NULL` — 8.3 字符 + `.SH`/`.SZ`/`.BJ` 后缀
- `PRIMARY KEY (id, stock_code)` — 复合 PK
- `KEY ix_stkpooldetail_id (id)` — 索引 `id` 单字段（虽然 PK 包含 id，但单独查询更高效）
- `FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE` — 删池自动清

**为什么加 `ix_stkpooldetail_id` 而不是靠 PK**：

虽然 PK 包含 `id`（复合 PK 第一列），但某些 MySQL 版本对**非主键范围查询**单独走索引更优。本 change 宁可加一次索引保险。

**stock_code 校验正则**：

参考现有 `stocks.stock_code` 校验（`frontend/spec.md:1351`）：

```python
Field(pattern=r'^\d{6}\.(SH|SZ|BJ)$')
```

## 5. 错误码契约

| 错误 | HTTP | Response |
|---|---|---|
| name 为空 / 缺 | 422 | `{detail: "VALIDATION_ERROR: name is required"}` |
| name 重复 | 409 | `{detail: "POOL_NAME_DUPLICATE: '<name>'"}` |
| 池不存在 | 404 | `{detail: "POOL_NOT_FOUND: id=<id>"}` |
| 明细不存在 | 404 | `{detail: "DETAIL_NOT_FOUND: id=<id>, stock_code='<code>'"}` |
| stock_code 格式错 | 422 | `{detail: "VALIDATION_ERROR: stock_code must match pattern..."}` |
| DB 异常 | 500 | `{detail: "INTERNAL_ERROR: <msg>"}` |

错误码风格对齐现有 `asset-position-adjust` 模块（`trading/spec.md:415` 范例：`POSITION_NOT_FOUND`）。

## 6. 前端状态 / 组件契约

### 6.1 StkPool.vue 状态

```javascript
const pools = ref([])                   // 主表列表
const selectedPoolId = ref(null)       // 当前选中池
const detail = ref([])                  // 当前池明细
const loading = ref(false)             // 加载状态

// 自动触发: 选中某池 → 查明细
watch(selectedPoolId, async (newId) => {
  if (newId) await loadDetail(newId)
  else detail.value = []
})

// 生命周期
onMounted(async () => {
  await loadPools()
  if (pools.value.length > 0) {
    selectedPoolId.value = pools.value[0].id  // 默认第一条
  }
})
```

### 6.2 添加股票流程

```vue
<StockCodePicker v-model="newStockCode" @select="onPick" />
<el-button @click="confirmAddDetail">+ 添加</el-button>

<script>
async function confirmAddDetail() {
  if (!newStockCode.value || !selectedPoolId.value) return
  await stkpoolApi.detailAdd(selectedPoolId.value, newStockCode.value)
  await loadDetail(selectedPoolId.value)  // 刷新
  newStockCode.value = ''
}
</script>
```

### 6.3 明细行 stock_name 渲染

```html
<el-table :data="detail">
  <el-table-column prop="stock_code" label="代码" width="140" />
  <el-table-column label="名称">
    <template #default="{row}">
      {{ getStockName(row.stock_code) }}
    </template>
  </el-table-column>
  <el-table-column label="操作" width="80">
    <template #default="{row}">
      <el-button text @click="removeDetail(row.stock_code)">删除</el-button>
    </template>
  </el-table-column>
</el-table>
```

```javascript
function getStockName(code) {
  return useStocksStore().stockName(code) || code
}
```

## 7. 迁移脚本语义

`server/migrations/2026-08-16-add-stkpool.py` 模板（仿 `2026-08-11-add-strategy-order.py`）：

```python
def _table_exists(conn, table): ...       # INFORMATION_SCHEMA 探测
def _column_exists(conn, table, col): ...
def _index_exists(conn, table, idx): ...

def create_stkpool_table(conn):
    if _table_exists(conn, 'stkpool'):
        print("[skip] stkpool exists")
        return
    conn.execute(text("""CREATE TABLE stkpool (...)"""))

def create_stkpooldetail_table(conn):
    if _table_exists(conn, 'stkpooldetail'):
        print("[skip] stkpooldetail exists")
        return
    conn.execute(text("""CREATE TABLE stkpooldetail (...)"""))

def ensure_stkpool_unique_name(conn):
    if _index_exists(conn, 'stkpool', 'uk_stkpool_name'):
        print("[skip] uk_stkpool_name exists")
        return
    conn.execute(text("""ALTER TABLE stkpool ADD UNIQUE KEY uk_stkpool_name (name)"""))

def main():
    with engine.begin() as conn:
        create_stkpool_table(conn)
        create_stkpooldetail_table(conn)
        ensure_stkpool_unique_name(conn)
    # 验证
    insp = inspect(engine)
    assert 'stkpool' in insp.get_table_names()
    assert 'stkpooldetail' in insp.get_table_names()
```

幂等保障：3 个 helper 都先查 INFORMATION_SCHEMA，已存在跳过。

## 8. tables-codegen 不用，手写 table 类

**不调 codegen 原因**：

1. share-id 模型在 `tables-codegen` 里未验证（22 张表全是自增 PK）
2. `__auto_increment_pk__ = None` 是个边缘 case，codegen 容易误判
3. 写错 MySQL 端会被破坏（PK 自增 vs 不自增）

**手写模板**（参考 `strategy_order.py`）：

```python
"""
server/tables/stkpool.py — 证券池主表 (手写, share-id 模式)
"""
from datetime import datetime
from typing import Any, ClassVar, Tuple
from server.tables.base import TableBase, Row


class Stkpool(TableBase):
    """证券池主表: id 自增, name 唯一, remark 备注, created_at 创建时间"""

    __tablename__: ClassVar[str] = 'stkpool'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id',)
    __auto_increment_pk__: ClassVar[str | None] = 'id'

    __fields__: ClassVar[dict] = {
        'id': '行主键 (自增)',
        'name': '池名 (唯一)',
        'remark': '备注',
        'created_at': '创建时间',
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'name': 'varchar(64)',
        'remark': 'varchar(255)',
        'created_at': 'datetime',
    }

    id: int
    name: str
    remark: str
    created_at: datetime
```

```python
"""
server/tables/stkpooldetail.py — 证券池明细 (手写, share-id 模式)
⚠️ 复合 PK (id, stock_code), id 不自增 — 共享主表 id
"""
from typing import Any, ClassVar, Tuple
from server.tables.base import TableBase, Row


class StkpoolDetail(TableBase):
    """证券池明细: 复合 PK (id, stock_code), share-id 与 stkpool.id 关联"""

    __tablename__: ClassVar[str] = 'stkpooldetail'
    __pk_fields__: ClassVar[Tuple[str, ...]] = ('id', 'stock_code')
    __auto_increment_pk__: ClassVar[str | None] = None  # 关键: 不自增

    __fields__: ClassVar[dict] = {
        'id': '共享主表 id (不自增, 与 stkpool.id 一一对应)',
        'stock_code': '股票代码',
    }

    __field_types__: ClassVar[dict] = {
        'id': 'int',
        'stock_code': 'varchar(16)',
    }

    id: int
    stock_code: str
```

## 9. 测试策略

### 9.1 后端单测（`tests/server/test_stkpool.py`）

| 场景 | 验证 |
|---|---|
| 创建池成功 | `name` 不重复 → 返 Row |
| 重复 name 创建 | 冲突 → 409 |
| 列表池 | 全量返回 |
| 改池名 | upsert_one 生效 |
| 删池 | CASCADE 自动清明细 |
| 加明细 | 复合 PK 写入 |
| 重复加明细 | upsert 不报错 |
| 删明细 | 复合 PK 删 |
| 池不存在查明细 | 404 |

### 9.2 前端手动验证

- [ ] 进入 `/stkpool` 自动选中第一条池
- [ ] 主表空时右区显示"暂无池"
- [ ] 新建池 → 主表刷新 → 自动选中
- [ ] 添加股票 → 弹 StockCodePicker → 选 600519.SH → 明细表追加一行
- [ ] 删除池 → 二次确认 → 主表减一行 → 切到下一条
- [ ] 池间切换 → 右区刷新
- [ ] 明细表股票名来自 `useStocksStore.cache`（不调后端）

## 10. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| share-id 在项目零先例 | 🟡 中 | 手写 table 类 + 人工复核 `__auto_increment_pk__` |
| MySQL DDL 误写 `AUTO_INCREMENT` | 🔴 高 | 迁移脚本逐字校对 + 1 步 INFO 探测 |
| 误删池不可逆 | 🟡 中 | UI 二次确认提示"将清除 N 只明细" |
| stock_code 缓存未加载 | 🟢 低 | 明细 row 兜底显示 code |
| 池数过多（1000+） | 🟢 低 | 当前规模下 query_all 够用 |
| 池名重复 | 🟢 低 | UK 约束 + 409 错误 |
| 并发创建同名池 | 🟢 低 | UK 约束兜底 |
| API 路由未注册 | 🔴 高 | 启动后 `curl /api/stkpool` 验证 |

## 11. 与现有模块的边界

| 关联 | 关系 |
|---|---|
| `stocks` 表 | **只读** —— 明细 stock_code 引用 stocks.stock_code，但明细表不复制 stock_name |
| `positions` 表 | **无关** —— 池子不等于持仓 |
| `strategy` / `t0_tasks` | **未打通**（Non-goals）—— 池子暂不联动下游 |
| `order_no_seq` | **未用** —— share-id 不需要 sequential 生成器 |
| `users` | **无关** —— 主表不分用户 |
| `auth` | **无关** —— 走统一鉴权，不分角色 |
| `useStocksStore` | **强依赖** —— display stock_name 唯一来源 |
| `StockCodePicker` | **强依赖** —— 添加股票对话框复用 |

---

## 12. 落地清单（执行 order）

1. `server/migrations/2026-08-16-add-stkpool.py` — 迁移脚本
2. `server/tables/stkpool.py` + `stkpooldetail.py` — 手写 Table 类
3. `server/tables/__init__.py` — 追加 2 行 import
4. `server/repo/stkpool.py` — Repo 业务流
5. `server/api/stkpool.py` — 5 + 2 端点 + schema
6. `server/main.py` — 路由注册
7. 运行迁移脚本 + 验证
8. `client/src/api/stkpool.js` — API 封装
9. `client/src/views/StkPool.vue` — 视图
10. `client/src/router/index.js` — 路由
11. `client/src/components/Sidebar.vue` — "证券信息"后追加顶级项
12. 启动验证 + 手动 e2e
13. 写 3 份 delta specs
14. 归档 → `/opsx:archive`

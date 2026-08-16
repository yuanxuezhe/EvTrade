# add-stkpool-module — 任务清单

> 总计 17 个任务，分 6 个模块（migration / tables / repo / api / frontend / spec）。
> 每个任务都标注"是否依赖前序任务完成"。

## 1. 数据库迁移

### 1.1 [ ] 编写迁移脚本

- **文件**：`server/migrations/2026-08-16-add-stkpool.py`
- **依赖**：无
- **步骤**：
  - 复制 `server/migrations/2026-08-11-add-strategy-order.py` 模板
  - 改写为 3 步：create_stkpool + create_stkpooldetail + ensure_unique_name
  - 全部走 INFORMATION_SCHEMA 幂等探测
  - 主表 DDL：
    ```sql
    CREATE TABLE stkpool (
        id INT NOT NULL AUTO_INCREMENT COMMENT '行主键',
        name VARCHAR(64) NOT NULL COMMENT '池名 (唯一)',
        remark VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        PRIMARY KEY (id),
        UNIQUE KEY uk_stkpool_name (name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='证券池主表';
    ```
  - 明细表 DDL（**关键**：id 不带 AUTO_INCREMENT）：
    ```sql
    CREATE TABLE stkpooldetail (
        id INT NOT NULL COMMENT '共享主表 id (不自增)',
        stock_code VARCHAR(16) NOT NULL COMMENT '股票代码',
        PRIMARY KEY (id, stock_code),
        KEY ix_stkpooldetail_id (id),
        FOREIGN KEY (id) REFERENCES stkpool(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='证券池明细: share PK id + stock_code';
    ```
- **验收**：`python3 server/migrations/2026-08-16-add-stkpool.py` 跑通 + 二次跑幂等

### 1.2 [ ] 运行迁移

- **文件**：`server/migrations/2026-08-16-add-stkpool.py`
- **依赖**：1.1
- **步骤**：
  ```bash
  cd E:/EvTrade
  python3 server/migrations/2026-08-16-add-stkpool.py
  ```
- **验收**：脚本输出 `[OK] created table 'stkpool'` + `[OK] created table 'stkpooldetail'`，info 探测确认两个表都在

### 1.3 [ ] 验证迁移幂等

- **依赖**：1.2
- **步骤**：
  ```bash
  python3 server/migrations/2026-08-16-add-stkpool.py  # 再次跑
  ```
- **验收**：所有 `[skip] ... already exists`，无报错

## 2. Tables 层

### 2.1 [ ] 手写 `stkpool.py` Table 类

- **文件**：`server/tables/stkpool.py`
- **依赖**：1.2
- **步骤**：
  - 复制 `server/tables/strategy_order.py` 模板结构
  - 类名 `Stkpool`
  - `__pk_fields__ = ('id',)`
  - `__auto_increment_pk__ = 'id'`
  - `__fields__` = 4 项（id/name/remark/created_at）
  - `__field_types__` 对齐 MySQL DDL
  - 字段 type hints 完整
- **验收**：`python -c "from server.tables.stkpool import Stkpool; print(Stkpool.__tablename__)"` 输出 `stkpool`

### 2.2 [ ] 手写 `stkpooldetail.py` Table 类

- **文件**：`server/tables/stkpooldetail.py`
- **依赖**：1.2
- **步骤**：
  - 模板结构同上
  - 类名 `StkpoolDetail`
  - **`__pk_fields__ = ('id', 'stock_code')`** ← 复合 PK
  - **`__auto_increment_pk__ = None`** ← 关键：share-id 不自增
  - `__fields__` = 2 项
  - `__field_types__` 对齐 MySQL DDL
- **验收**：`python -c "from server.tables.stkpooldetail import StkpoolDetail; print(StkpoolDetail.__pk_fields__, StkpoolDetail.__auto_increment_pk__)"` 输出 `('id', 'stock_code') None`

### 2.3 [ ] 追加到 `__init__.py`

- **文件**：`server/tables/__init__.py`
- **依赖**：2.1, 2.2
- **步骤**：
  - 末尾追加 2 行：
    ```python
    from server.tables.stkpool import Stkpool  # noqa: F401
    from server.tables.stkpooldetail import StkpoolDetail  # noqa: F401
    ```
  - 注意：按字母序插入（`stkpool` 在 `stocks` 之后、`strategy_*` 之前，需手动定位）
- **验收**：`python -c "from server.tables import Stkpool, StkpoolDetail; print('ok')"`

## 3. Repo 层

### 3.1 [ ] 编写 `StkpoolRepo`

- **文件**：`server/repo/stkpool.py`
- **依赖**：2.3
- **步骤**：
  - 7 个方法：
    - `list_pools()` → `Stkpool.query_all('asc')`
    - `get_pool(pool_id)` → `Stkpool.query_one(id=pool_id)`
    - `create_pool(name, remark)` → `Stkpool.upsert_one({'name':name, 'remark':remark}, id=0)` 然后取 LAST_INSERT_ID
      - 实际写法：`Stkpool.upsert_one({'name': name, 'remark': remark})` 让 AUTO_INCREMENT 自增
    - `update_pool(pool_id, name, remark)` → `Stkpool.update_one({'name':name, 'remark':remark}, id=pool_id)`
    - `delete_pool(pool_id)` → `Stkpool.delete_one(id=pool_id)`（CASCADE 自动明清细）
    - `list_detail(pool_id)` → `StkpoolDetail.query_by('id', pool_id)`
    - `add_detail(pool_id, stock_code)` → `StkpoolDetail.upsert_one({'id':pool_id, 'stock_code':stock_code}, id=pool_id, stock_code=stock_code)`
    - `remove_detail(pool_id, stock_code)` → `StkpoolDetail.delete_one(id=pool_id, stock_code=stock_code)`
  - 业务校验：
    - `create_pool` 查重（name 已存在 → 抛 `PoolNameDuplicate`）
    - `add_detail` 验池存在（`get_pool` → None 抛 `PoolNotFound`）
- **验收**：每个方法手写 1 行调用无报错（用本地 DB 跑）

## 4. API 层

### 4.1 [ ] 编写 Pydantic Schema

- **文件**：`server/api/stkpool.py`（紧邻 router）
- **依赖**：3.1
- **步骤**：
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

### 4.2 [ ] 编写 5 + 2 端点

- **文件**：`server/api/stkpool.py`
- **依赖**：4.1
- **步骤**：
  ```python
  router = APIRouter(prefix="/api/stkpool", tags=["stkpool"])

  @router.get("")
  def list_pools(): ...

  @router.post("", status_code=201)
  def create_pool(payload: StkpoolCreate): ...

  @router.put("/{pool_id}")
  def update_pool(pool_id: int, payload: StkpoolUpdate): ...

  @router.delete("/{pool_id}", status_code=204)
  def delete_pool(pool_id: int): ...

  @router.get("/{pool_id}/detail")
  def list_detail(pool_id: int): ...

  @router.post("/{pool_id}/detail", status_code=201)
  def add_detail(pool_id: int, payload: StkpoolDetailAdd): ...

  @router.delete("/{pool_id}/detail/{stock_code}", status_code=204)
  def remove_detail(pool_id: int, stock_code: str): ...
  ```
- **错误处理**：
  - `PoolNotFound` → 404 + `POOL_NOT_FOUND`
  - `PoolNameDuplicate` → 409 + `POOL_NAME_DUPLICATE`
  - `DetailNotFound` → 404 + `DETAIL_NOT_FOUND`
  - 业务异常捕获后转 HTTPException

### 4.3 [ ] 注册路由

- **文件**：`server/main.py`
- **依赖**：4.2
- **步骤**：
  - 顶部追加 `from server.api import stkpool`
  - 第 24-33 行路由清单追加 `app.include_router(stkpool.router)`
- **验收**：`curl http://localhost:8000/api/stkpool` 返 `{"pools": []}` 或已有数据

### 4.4 [ ] 启动后端验证

- **依赖**：4.3
- **步骤**：
  ```bash
  uvicorn server.main:app --reload
  ```
- **验收**：
  - `GET /api/stkpool` → 200
  - `POST /api/stkpool {"name": "测试池"}` → 201 + 返 Row
  - `GET /api/stkpool/1/detail` → 200 + `{"details": []}`
  - `POST /api/stkpool/1/detail {"stock_code": "600519.SH"}` → 201
  - `DELETE /api/stkpool/1` → 204 + MySQL 自动清 detail

## 5. 前端 — API 封装

### 5.1 [ ] 编写 `stkpool.js`

- **文件**：`client/src/api/stkpool.js`
- **依赖**：4.4
- **步骤**：
  - 7 个方法：
    ```js
    export const stkpoolApi = {
      list: () => api.get('/api/stkpool').then(r => r.data.pools),
      create: (data) => api.post('/api/stkpool', data).then(r => r.data),
      update: (id, data) => api.put(`/api/stkpool/${id}`, data).then(r => r.data),
      remove: (id) => api.delete(`/api/stkpool/${id}`),
      detail: (id) => api.get(`/api/stkpool/${id}/detail`).then(r => r.data.details),
      detailAdd: (id, stock_code) => api.post(`/api/stkpool/${id}/detail`, { stock_code }).then(r => r.data),
      detailRemove: (id, stock_code) => api.delete(`/api/stkpool/${id}/detail/${stock_code}`),
    }
    ```
  - 模板参考 `client/src/api/stocks.js`

## 6. 前端 — 视图

### 6.1 [ ] 编写 `StkPool.vue`

- **文件**：`client/src/views/StkPool.vue`
- **依赖**：5.1
- **步骤**：
  - 模板结构：
    ```html
    <template>
      <div class="stkpool-layout">
        <aside class="stkpool-left">
          <header><el-button @click="onCreate">+ 新建池</el-button></header>
          <el-table :data="pools" highlight-current-row @row-click="onSelect">
            <el-table-column prop="id" label="ID" width="50" />
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="remark" label="备注" />
          </el-table>
        </aside>
        <main class="stkpool-right">
          <header v-if="selectedPool">
            <span>池名: {{ selectedPool.name }}</span>
            <el-button @click="onEdit">编辑</el-button>
            <el-button type="danger" @click="onDelete">删除</el-button>
          </header>
          <div v-if="selectedPoolId">
            <el-input v-model="newStockCode" placeholder="股票代码" />
            <el-button @click="onAddDetail">+ 添加</el-button>
            <el-table :data="detail">
              <el-table-column prop="stock_code" label="代码" />
              <el-table-column label="名称">
                <template #default="{row}">{{ getStockName(row.stock_code) }}</template>
              </el-table-column>
              <el-table-column label="操作">
                <template #default="{row}">
                  <el-button text @click="onRemoveDetail(row.stock_code)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else description="暂无池，请新建" />
        </main>
      </div>
    </template>
    ```
  - script 状态：
    - `pools`, `selectedPoolId`, `detail`, `newStockCode`, `loading`
    - `onMounted` 拉主表 + 默认选第一条
    - `watch(selectedPoolId)` 拉明细
  - 弹窗：
    - 新建/编辑池：el-dialog + form input
    - 添加股票：用 StockCodePicker 替代纯 input

### 6.2 [ ] 注入 stock_name 渲染

- **文件**：`client/src/views/StkPool.vue`
- **依赖**：6.1
- **步骤**：
  ```js
  import { useStocksStore } from '@/stores/stocks'
  const stocksStore = useStocksStore()
  function getStockName(code) {
    return stocksStore.cache[code]?.stock_name ?? code
  }
  ```
- **验收**：进入视图，肉眼能看到 600519.SH 行右侧显示 "贵州茅台"

### 6.3 [ ] 路由注册

- **文件**：`client/src/router/index.js`
- **依赖**：6.1
- **步骤**：
  - 找到 `/admin/stock-config` 路由附近
  - 添加：
    ```js
    {
      path: '/stkpool',
      component: () => import('@/views/StkPool.vue'),
      meta: { title: '证券池', requiresAuth: true }
    }
    ```

### 6.4 [ ] Sidebar 追加顶级项

- **文件**：`client/src/components/Sidebar.vue`
- **依赖**：6.3
- **步骤**：
  - 找到 `menuItems` 数组中"证券信息"顶级项
  - **在它之后**追加新的顶级项：
    ```js
    { name: '证券池', path: '/stkpool', icon: ... },
    ```
  - **保持**"证券信息"原样不动（不变 `el-sub-menu`，不嵌套）
  - 视觉上"证券池"紧跟"证券信息"之后
  - 菜单数组 `menuItems` 同步调整
  - 模板层（如有 `v-for` 渲染）确认新增顶级项渲染为 `el-menu-item`（不是 `el-sub-menu`）

### 6.5 [ ] 前端手动 e2e

- **依赖**：6.4
- **步骤**：
  ```bash
  cd E:/EvTrade/client && npm run dev
  ```
- **验收**：
  - [ ] 访问 `/stkpool` 自动选中第一条池
  - [ ] 主表空时右区显示"暂无池"
  - [ ] 新建池 → 主表刷新 + 自动选中 → 右区刷明细
  - [ ] 添加股票 → 弹 StockCodePicker → 选 600519.SH → 明细表追加一行
  - [ ] 切换池 → 右区刷新
  - [ ] 删除池 → 二次确认 → 主表减一行 → 自动切到下一条
  - [ ] 明细表股票名（如"贵州茅台"）正确显示

## 7. Spec 增量

### 7.1 [ ] 写 `data-model/spec.md` delta

- **文件**：`openspec/changes/active/add-stkpool-module/specs/data-model/spec.md`
- **依赖**：1.2
- **步骤**：
  - 新增 `## ADDED Requirements` 段
  - `### REQ-STKPOOL-DM-001: stkpool 主表` — 字段定义 + UK 约束
  - `### REQ-STKPOOL-DM-002: stkpooldetail 明细表` — 复合 PK + FK ON DELETE CASCADE
  - 每个 REQ 包含 #### Scenario（Given/When/Then）

### 7.2 [ ] 写 `server-architecture/spec.md` delta

- **文件**：`openspec/changes/active/add-stkpool-module/specs/server-architecture/spec.md`
- **依赖**：4.4
- **步骤**：
  - 新增 `## ADDED Requirements` 段
  - `### REQ-STKPOOL-API-001: 5 + 2 端点`
  - `### REQ-STKPOOL-API-002: 错误码契约`（404/409/422）
  - `### REQ-STKPOOL-API-003: 鉴权`（仅 auth，不分角色）

### 7.3 [ ] 写 `frontend/spec.md` delta

- **文件**：`openspec/changes/active/add-stkpool-module/specs/frontend/spec.md`
- **依赖**：6.5
- **步骤**：
  - 新增 `## ADDED Requirements` 段
  - `### REQ-STKPOOL-FE-001: 视图布局` — 左右 40/60
  - `### REQ-STKPOOL-FE-002: 默认选中第一条`
  - `### REQ-STKPOOL-FE-003: 添加股票复用 StockCodePicker`
  - `### REQ-STKPOOL-FE-004: 明细行 stock_name 来自 useStocksStore.cache`
  - `### REQ-STKPOOL-FE-005: 菜单位置`（"证券信息"后追加顶级项，不嵌套为子菜单）

## 8. 收尾

### 8.1 [ ] 跑全量后端测试

- **依赖**：1.2, 4.4
- **步骤**：
  ```bash
  cd E:/EvTrade && pytest tests/server/ -v
  ```
- **验收**：所有原测试 + 新增 `tests/server/test_stkpool.py` 全 pass

### 8.2 [ ] 归档 change

- **依赖**：所有上面
- **步骤**：
  - 跑 `/opsx:archive` 或手动 `mv openspec/changes/active/add-stkpool-module openspec/changes/archive/`
  - 同步 specs 到 `openspec/specs/`（`/opsx:sync`）

---

## 任务依赖图

```
1.1 migration  ─┬─► 1.2 run migrate ─┬─► 2.1 stkpool.py ─┬─► 2.3 __init__.py ─┬─► 3.1 repo ─┬─► 4.1 schema ─┬─► 4.2 端点 ─┬─► 4.3 注册 ─► 4.4 启动验证 ─┬─► 5.1 api.js ─┬─► 6.1 StkPool.vue ─┬─► 6.2 stock_name ─┬─► 6.3 router ─┬─► 6.4 sidebar ─► 6.5 e2e
                 │                    └─► 2.2 detail.py ──┘                    │             │                │                                  │                  │                      │                  │
                 │                                                                       │             │                                    │                  │                      │                  │
                 └──► 1.3 幂等验证 ─┘                                                       ▼             ▼                                    ▼                  ▼                      ▼                  ▼
                                                                                                                                       7.1 data-model  7.2 server-arc          7.3 frontend         8.1 test
                                                                                                                                           (依赖 1.2)    (依赖 4.4)              (依赖 6.5)        (依赖 1.2/4.4)
                                                                                                                                                                  │
                                                                                                                                                                  ▼
                                                                                                                                                              8.2 归档
```

## 完成检查清单

- [ ] 1.1 迁移脚本
- [ ] 1.2 跑迁移
- [ ] 1.3 幂等验证
- [ ] 2.1 stkpool.py
- [ ] 2.2 stkpooldetail.py
- [ ] 2.3 __init__.py
- [ ] 3.1 Repo
- [ ] 4.1 Schema
- [ ] 4.2 端点
- [ ] 4.3 路由注册
- [ ] 4.4 启动验证
- [ ] 5.1 api.js
- [ ] 6.1 StkPool.vue
- [ ] 6.2 stock_name
- [ ] 6.3 router
- [ ] 6.4 sidebar
- [ ] 6.5 e2e
- [ ] 7.1 data-model spec
- [ ] 7.2 server-architecture spec
- [ ] 7.3 frontend spec
- [ ] 8.1 pytest
- [ ] 8.2 归档

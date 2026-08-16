## ADDED Requirements

### Requirement: 证券池 5 + 2 端点（REQ-STKPOOL-API-001）

The system SHALL 在 `server/api/stkpool.py` 提供 7 个 REST 端点（5 主表 + 2 主子端点 + 1 加密子端点重命名）：
   - **注**：实际为 5 主表 + 2 明细（POST/DELETE detail）+ 1 明细查询 GET = 8 端点。

#### 主表端点

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| `GET` | `/api/stkpool` | 全量主表，按 `id ASC` | auth |
| `POST` | `/api/stkpool` | 创建池（body: `name`, `remark?`） | auth |
| `PUT` | `/api/stkpool/{pool_id}` | 改池名/备注（body: `name?`, `remark?`） | auth |
| `DELETE` | `/api/stkpool/{pool_id}` | 删池（CASCADE 自动清明细） | auth |

#### 明细端点

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| `GET` | `/api/stkpool/{pool_id}/detail` | 池明细列表，按 `stock_code ASC` | auth |
| `POST` | `/api/stkpool/{pool_id}/detail` | 加明细（body: `stock_code`） | auth |
| `DELETE` | `/api/stkpool/{pool_id}/detail/{stock_code}` | 删明细 | auth |

**鉴权规则（决策 2）**：

- 全部端点 MUST 走 `auth` 鉴权（任何合法登录用户）
- MUST NOT 再分 RBAC 角色（不强制 admin）
- 鉴权依赖位于 `server/api/deps.py` 现有 `get_current_user` 依赖

**路由注册**：

- `server/main.py` 第 24-33 行路由清单 MUST 追加 `app.include_router(stkpool.router, prefix="/api/stkpool")`
- 端点前缀 `/api/stkpool` 在 router 内部已声明（`APIRouter(prefix="/api/stkpool")`），main.py 复用一致

#### Scenario: 主表 GET 全量

- **WHEN** `GET /api/stkpool` 收到鉴权合法请求
- **THEN** 后端 `StkpoolRepo.list_pools()` → `Stkpool.query_all('asc')`
- **AND** 返回 200 `{pools: [{id, name, remark, created_at}, ...]}`
- **AND** 按 `id ASC` 排序
- **AND** 鉴权失败（无 token / 过期）→ 401

#### Scenario: 主表 POST 创建

- **WHEN** `POST /api/stkpool {"name": "白马", "remark": "高股息"}` 收到
- **THEN** Pydantic `StkpoolCreate` 校验：`name` 长度 1-64, `remark` ≤ 255
- **AND** `StkpoolRepo.create_pool(name, remark)` 查重 + `upsert_one`
- **AND** 成功 → 201 + Row `{id, name, remark, created_at}`
- **AND** name 重复 → 409 `POOL_NAME_DUPLICATE`
- **AND** name 缺/空 → 422 `VALIDATION_ERROR`

#### Scenario: 主表 PUT 改

- **WHEN** `PUT /api/stkpool/5 {"name": "白马 (改)"}` 收到
- **THEN** Pydantic `StkpoolUpdate` 校验（partial update）
- **AND** `StkpoolRepo.update_pool(5, name=..., remark=...)` → `Stkpool.update_one({'name':...}, id=5)`
- **AND** 成功 → 200 + Row
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`

#### Scenario: 主表 DELETE 删池

- **WHEN** `DELETE /api/stkpool/5` 收到
- **THEN** `StkpoolRepo.delete_pool(5)` → `Stkpool.delete_one(id=5)`
- **AND** MySQL FK CASCADE 自动清除 `stkpooldetail.id=5`
- **AND** 成功 → 204 No Content
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`（rowcount=0）

#### Scenario: 明细 GET 列表

- **WHEN** `GET /api/stkpool/5/detail` 收到
- **THEN** `StkpoolRepo.list_detail(5)` → `StkpoolDetail.query_by('id', 5, order='asc')`
- **AND** 返回 200 `{details: [{id, stock_code}, ...]}` 按 `stock_code ASC`
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`（先查池）

#### Scenario: 明细 POST 加（v128 批量）

- **WHEN** `POST /api/stkpool/5/detail {"stock_codes": "600519.SH,000001.SZ,600030.SH"}` 收到
- **THEN** Pydantic `StkpoolDetailAdd` 校验 `stock_codes` 非空 + 长度 ≤ 8192
- **AND** 后端按 `,` split + strip + 去空 → 候选 codes 列表
- **AND** 校验每条匹配 `^\d{6}\.(SH|SZ|BJ)$`，否则 422 `VALIDATION_ERROR: invalid stock_codes: [...]`
- **AND** 候选 codes 去重（防御性）
- **AND** `StkpoolRepo.add_detail_batch(5, codes)` → 单事务 `INSERT IGNORE INTO stkpooldetail (id, stock_code) VALUES ...`
- **AND** 返回 201 + `{pool_id: 5, added: N, skipped: M}` (added = rowcount, skipped = 总数 - added)
- **AND** 重复 → skipped > 0（幂等）
- **AND** 池不存在 → 404 `POOL_NOT_FOUND`
- **AND** split 后为空 → 422 `VALIDATION_ERROR: stock_codes cannot be empty after split`

#### Scenario: 单只兼容（向后兼容）

- **WHEN** `POST /api/stkpool/5/detail {"stock_codes": "600519.SH"}` 收到（只 1 只）
- **THEN** split 后 codes = ["600519.SH"]
- **AND** 走同一 `add_detail_batch` 路径
- **AND** 返回 201 + `{pool_id: 5, added: 1, skipped: 0}`

#### Scenario: 明细 DELETE 删

- **WHEN** `DELETE /api/stkpool/5/detail/600519.SH` 收到
- **THEN** `StkpoolRepo.remove_detail(5, '600519.SH')` → `StkpoolDetail.delete_one(id=5, stock_code='600519.SH')`
- **AND** 成功 → 204
- **AND** 不存在 → 404 `DETAIL_NOT_FOUND`

### Requirement: 错误码契约（REQ-STKPOOL-API-002）

The system SHALL 使用统一的错误码格式 `{detail: "<CODE>: <human readable message>"}`，与现有 `asset-position-adjust` 模块对齐。

| 错误码 | HTTP | 触发场景 |
|---|---|---|
| `POOL_NOT_FOUND` | 404 | 池不存在 |
| `DETAIL_NOT_FOUND` | 404 | 明细不存在 |
| `POOL_NAME_DUPLICATE` | 409 | name 重复 |
| `VALIDATION_ERROR` | 422 | Pydantic 入参校验失败 |
| `INTERNAL_ERROR` | 500 | DB 异常 |

**实现位置**：

- 业务异常类（`PoolNotFound`, `PoolNameDuplicate`, `DetailNotFound`）定义在 `server/api/stkpool.py` 内部
- 路由处理器通过 `try/except` 捕获 → 转 `HTTPException(status_code, detail)`

#### Scenario: 错误码格式统一

- **WHEN** 任何 stkpool 端点遇到业务错误
- **THEN** 响应 `detail` 字段 MUST 格式为 `<CODE>: <message>`
- **AND** 状态码 MUST 匹配上表

#### Scenario: VALIDATION_ERROR 由 Pydantic 自动生成

- **WHEN** `POST /api/stkpool {"name": ""}` 收到（name 空）
- **THEN** Pydantic FastAPI 自动生成 422 + `detail: [{loc: ["body", "name"], msg: "ensure this value has at least 1 characters", ...}]`
- **AND** MUST NOT 走到 Repo 业务层

### Requirement: 鉴权边界（REQ-STKPOOL-API-003）

The system SHALL 对所有 7 个 stkpool 端点统一鉴权，无 RBAC 角色分层。

#### Scenario: 已登录用户可访问

- **WHEN** 合法 JWT 携带 `Authorization: Bearer ...`
- **THEN** 端点正常处理，返回 200/201/204

#### Scenario: 未登录返回 401

- **WHEN** 无 token / token 过期 / token 解析失败
- **THEN** FastAPI 鉴权依赖返回 401
- **AND** 端点代码 MUST NOT 走到 Repo

#### Scenario: 普通用户与 admin 都有权限

- **WHEN** 普通用户 (`role: 'trader'`) 调 `POST /api/stkpool`
- **THEN** 入口鉴权通过 → 业务正常处理
- **WHEN** admin 调同一端点
- **THEN** 行为完全一致（无 RBAC 差异）

## MODIFIED Requirements

### Requirement: 路由清单（main.py）

`server/main.py` 路由清单（MUST 追加 stkpool）：

```python
app.include_router(stkpool.router, prefix="/api/stkpool")
```

放在 `script_strategy` 或 `admin` 路由附近（按主题分组）。

#### Scenario: 路由清单注册后启动验证

- **WHEN** `uvicorn server.main:app --reload` 启动
- **THEN** `curl http://localhost:8000/api/stkpool` 返 200 + `{pools: []}`
- **AND** 端点需带鉴权头（无 token 返 401）

### Requirement: Pydantic Schema 命名规范

The system SHALL 在 `server/api/stkpool.py` 同文件内定义 Pydantic 模型，命名遵循 `Stkpool<Verb>` 模式：

- `StkpoolCreate` — POST body
- `StkpoolUpdate` — PUT body
- `StkpoolDetailAdd` — 明细 POST body

#### Scenario: Schema 字段定义

```python
class StkpoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    remark: str = Field(default='', max_length=255)

class StkpoolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    remark: str | None = Field(default=None, max_length=255)

class StkpoolDetailAdd(BaseModel):
    """v128: 批量接口 — stock_codes 用逗号分隔多只股票"""
    stock_codes: str = Field(min_length=1, max_length=8192)
```

- **WHEN** 任何端点接到 body
- **THEN** FastAPI 自动 Pydantic 校验
- **AND** 失败 → 422 `VALIDATION_ERROR`
- **AND** 成功 → 进入业务层

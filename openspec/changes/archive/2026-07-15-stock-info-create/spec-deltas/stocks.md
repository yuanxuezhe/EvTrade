# Spec Delta: stocks — REQ-STOCK-006 admin 手动添加证券

> **目标文件**: `openspec/specs/stocks/spec.md`
> **追加章节**: 在 REQ-STOCK-005 之后追加 REQ-STOCK-006
> **不修改**: 现有 REQ-STOCK-001 ~ 005

---

## 新增 REQ-STOCK-006

## REQ-STOCK-006: admin 手动添加证券（v46 stock-info-create, 2026-07-15）

**Given** admin 用户遇到未同步的股票(新增 IPO / 港股通新增 / 自定义测试数据)需要手动补录到 stocks 表  
**When** 调用 `POST /api/stocks`(admin-only)  
**Then** 必须满足:

- 鉴权:`require_admin` 守卫(role=admin)
- Request Body 字段白名单(8 字段,Pydantic `extra="forbid"` 防脏数据):
  - `stock_code: str` — **必填**, PK, 必须形如 `000001.SZ` / `600000.SH` / `920169.BJ`(regex `^\d{6}\.(SH|SZ|BJ)$`)
  - `stock_name: str` — **必填**, max_length=64
  - `sector: Optional[str] = None` — max_length=64
  - `short_name: Optional[str] = None` — max_length=16, 拼音首字母简称
  - `is_t0_able: bool = False` — 是否支持 T+0 回转
  - `min_buy_qty: int = 100` — 最小买入数量, ge=1
  - `trade_unit: int = 1` — 买卖单位, ge=1
- 成功 → 返 201 Created + `{code:0, msg:"ok", data:{...}}`(完整 stock 对象)
- `stock_code` 已存在 → 返 409 Conflict(防重复添加)
- 必填字段缺失 / 字段类型错 → 返 422(Pydantic Validation)
- 应用层走 `repo.stocks.create_by_admin(db, payload)` 单一入口
- 不发 WS push(范围最小化,与 REQ-STOCK-003 编辑行为一致)
- `created_at` / `updated_at` 由 DB 自动维护

**错误码语义**:
- 201: 创建成功
- 409: stock_code 已存在
- 422: 字段校验失败(类型错/长度超限/正则不匹配)
- 401/403: 未鉴权 / 非 admin

**前端契约**:
- 添加成功后,前端 store 同步更新:
  - `cache.value.unshift(data)`(头部插入,便于 autocomplete)
  - `total.value += 1`
  - `pageRows.value.unshift(data)`(如果在第 1 页)
- 弹窗关闭 + ElMessage.success 提示

---

## 新增 scenario (4 条)

### Scenario 1: admin 正常添加证券(201)

**Given** admin token 有效,stocks 表中无 `999999.SH`  
**When** POST `/api/stocks` body=`{"stock_code":"999999.SH","stock_name":"测试证券","sector":"测试板块","is_t0_able":false,"min_buy_qty":100,"trade_unit":1}`  
**Then** 返 201 + `{code:0, msg:"ok", data:{stock_code:"999999.SH", stock_name:"测试证券", ...}}`,DB 中新增一行,`created_at`/`updated_at` 自动设置

### Scenario 2: stock_code 重复 → 409

**Given** stocks 表已有 `000001.SZ`  
**When** POST `/api/stocks` body=`{"stock_code":"000001.SZ",...}`  
**Then** 返 409 + `{detail:"stock 000001.SZ already exists"}`(HTTPException)

### Scenario 3: 必填字段缺失 → 422

**Given** admin token 有效  
**When** POST `/api/stocks` body=`{"stock_code":"999998.SH"}`(缺 stock_name)  
**Then** 返 422 + `{detail:[{loc:["body","stock_name"], msg:"field required", ...}]}`

### Scenario 4: 非 admin 鉴权失败 → 401/403

**Given** 普通用户 token(role=user)  
**When** POST `/api/stocks` 任意 body  
**Then** 返 401 Unauthorized 或 403 Forbidden(`require_admin` 依赖拒绝)
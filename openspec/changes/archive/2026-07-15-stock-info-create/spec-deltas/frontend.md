# Spec Delta: frontend — REQ-FE-STOCK-CREATE 证券添加对话框契约

> **目标文件**: `openspec/specs/frontend/spec.md`
> **追加章节**: 在 REQ-FE-INIT-001 之后追加 REQ-FE-STOCK-CREATE
> **不修改**: 现有所有 REQ-FE-*

---

## 新增 REQ-FE-STOCK-CREATE

## REQ-FE-STOCK-CREATE: 证券信息设置页"添加证券"对话框契约（v46 stock-info-create, 2026-07-15）

**Given** admin 在 `/admin/stock-config` 页面需要添加一只新证券  
**When** 点击 panel-header 的"添加证券"按钮(Primary 类型)  
**Then** 必须满足:

- 弹出独立 `<el-dialog>` 标题"添加证券信息"(与编辑 dialog 独立,互不影响)
- 表单字段(8 字段,与后端 `StockCreateRequest` 严格对齐):
  1. `stock_code` — 必填, regex `^\d{6}\.(SH|SZ|BJ)$`,placeholder `如:000001.SZ`
  2. `stock_name` — 必填, maxlength=64, show-word-limit
  3. `sector` — 可选, maxlength=64, placeholder `如:银行-国有大型银行`
  4. `short_name` — 可选, maxlength=16, placeholder `如:平安银行 → PAYH`, show-word-limit
  5. `is_t0_able` — el-switch, active-text=`T+0`, inactive-text=`T+1`
  6. `min_buy_qty` — el-input-number, min=1, step=100, 默认 100
  7. `trade_unit` — el-input-number, min=1, step=1, 默认 1
- 必填字段前端校验:stock_code / stock_name 缺失 → 禁用提交按钮
- 提交按钮(footer)调 `store.createStock(payload)`,loading 状态绑定 `createLoading`
- 成功后:
  - ElMessage.success(`已添加 ${stock_code}`)
  - dialog 自动关闭
  - 表格首行自动出现新 stock(因为 store 已 unshift 到 pageRows)
- 失败:
  - 409(stock_code 重复)→ ElMessage.error(`证券 ${stock_code} 已存在`)
  - 422 → ElMessage.error(后端 detail msg)
  - 其他 → ElMessage.error(`添加失败: ${msg}`)

**store 同步** (v46 stock-info-create):
- `client/src/stores/stocks.js::createStock(payload)` 必须:
  1. 调 `stocksApi.create(payload)` → 后端 201 + data
  2. `cache.value.unshift(data)` — autocomplete 立即可用
  3. `total.value += 1` — 分页 total 同步
  4. `pageRows.value.unshift(data)` — 当前页立即显示
- 失败回滚:不修改 cache/total/pageRows(若 API 抛错,store 状态保持不变)

**复用约束**:
- **不**复用 `editForm`(那是编辑专用,与 create 状态隔离)
- 新增独立 state: `createLoading: ref(false)`(与 editLoading 同)
- dialog 用独立 ref: `createDialogVisible`(与 dialogVisible 同)

---

## 新增 scenario (3 条)

### Scenario 1: 正常添加 → 弹窗关闭 + 新行出现

**GIVEN** admin 已登录,panel-header 有"添加证券"按钮  
**WHEN** 点击按钮 → 填 `stock_code=999999.SH` / `stock_name=测试` / 其他字段 → 点击"保存"  
**THEN** 后端 201,前端 dialog 关闭,ElMessage.success 提示,表格首行出现 `999999.SH 测试`

### Scenario 2: stock_code 重复 → 友好提示

**GIVEN** stocks 表已有 `000001.SZ`  
**WHEN** 尝试添加 `stock_code=000001.SZ`  
**THEN** 后端 409,前端 ElMessage.error(`证券 000001.SZ 已存在`),dialog 保持打开供用户修改

### Scenario 3: 必填字段缺失 → 提交按钮禁用

**GIVEN** 添加 dialog 已打开  
**WHEN** `stock_code` 或 `stock_name` 为空  
**THEN** "保存"按钮 disabled,无法提交(前端校验)
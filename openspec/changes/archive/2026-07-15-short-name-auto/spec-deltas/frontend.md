# Spec Delta: frontend — REQ-FE-STOCK-HIDE 隐藏 short_name 编辑界面

> **目标文件**: `openspec/specs/frontend/spec.md`
> **追加章节**: 在 REQ-FE-STOCK-CREATE 之后追加 REQ-FE-STOCK-HIDE
> **不修改**: 现有所有 REQ-FE-*

---

## 新增 REQ-FE-STOCK-HIDE

### REQ-FE-STOCK-HIDE: 隐藏 short_name 字段编辑界面 (v46+ short-name-auto)

**位置**: `/admin/stock-config` 页面 (`client/src/views/AdminStockConfig.vue`)

**背景**:
v46 stock-info-create 让 admin 可以在添加对话框手填 short_name, 但根据 v46+ short-name-auto 决策, short_name 改为后端自动生成, 前端应隐藏编辑界面, 避免误改。

**变更**:

| 位置 | 行为 |
|---|---|
| 表格"首字母"列 | **删除** (不再显示) |
| 编辑对话框 short_name input | **删除** (admin 不能改) |
| 添加对话框 short_name input | **删除** (admin 不需要手填) |
| 添加对话框 stock_name 输入 | **保留** (用于触发后端自动生成) |
| 客户端搜索 keyword 二次过滤 | **保留** (仍用 short_name 匹配) |

**Scenario**:

- **GIVEN** admin 访问 `/admin/stock-config`
- **WHEN** 表格渲染
- **THEN** 表格不含"首字母"列
- **AND** 列数从 9 列 (代码/名称/板块/首字母/...) 变为 8 列

- **GIVEN** admin 点击"添加证券"按钮
- **WHEN** 添加对话框打开
- **THEN** 对话框不含"简称"表单项
- **AND** 表单项从 7 项 (代码/名称/板块/简称/...) 变为 6 项

- **GIVEN** admin 点击表格行"编辑"按钮
- **WHEN** 编辑对话框打开
- **THEN** 对话框不含"简称"表单项
- **AND** 后端 Pydantic `StockUpdateRequest` 拒绝任何含 `short_name` 字段的请求 (422)

- **GIVEN** admin 在搜索框输入 `payh` (短名首字母)
- **WHEN** 客户端二次过滤触发
- **THEN** 仍可匹配 short_name 含 `payh` 的股票 (后端 keyword + 前端 cache 二次过滤功能不变)

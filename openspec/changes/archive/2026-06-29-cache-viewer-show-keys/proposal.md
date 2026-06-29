# Cache 查看器: 列名加英文 key 后缀

> 创建日期：2026-06-29
> 状态：draft
> 范围：CacheTableView.vue 通用组件

## Why

用户报："前端缓存展示，不光要展示中文列名，原始的英文 key 也写出来"

需求溯源：admin 缓存查看器的目标是**排查 IDB 数据是否正确**——能直接看到"这一列对应的是 `cash` 还是 `total_asset`"能省去反复对照 schema 的精力。当前 `CacheTableView.vue` 只显示中文 label（`现金`、`总资产`），英文 key 隐藏在 `<el-table-column :prop="f.key">` 里，**用户视角看不到**。

## What

`CacheTableView.vue` 渲染列时，把 `f.label` + `f.key` 拼成 `label (key)` 形式：

| 之前 | 之后 |
|---|---|
| `现金` | `现金 (cash)` |
| `总资产` | `总资产 (total_asset)` |
| `股票代码` | `股票代码 (stock_code)` |
| `买卖` | `买卖 (order_type)` |

### 字段类型化的列

`f.type === 'select'` / `'number'` 跟 key 后缀不冲突，保留 type 表单（dialog 用），label 仍拼后缀。

### 不改动的

- 4 个 page view 的 `fields` 数组**保持原样**（key 仍按英文原样，label 中文）—— 只改通用组件的渲染
- dialog 内的 `el-form-item :label="f.label"` **也加 key 后缀**——保持一致
- 不加新列、不加 tooltip，纯 label 文字增强
- 不影响 IDB 写读逻辑

## 影响的 capability

- `frontend` — 微调 REQ-FE-101（增 1 个 scenario 描述 label 格式）

## 验证

- 打开 4 个 cache 页，每列 header 是"中文 (english_key)" 形式
- dialog 表单项 label 同样显示 key
- 表格列宽自适应新长度
- console 无新警告

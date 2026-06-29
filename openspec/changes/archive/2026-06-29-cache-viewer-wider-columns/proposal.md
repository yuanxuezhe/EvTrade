# Cache 查看器: 列宽调整 (避免 header 换行)

> 创建日期：2026-06-29
> 状态：draft
> 范围：CacheTableView.vue + 4 个 page view

## Why

[2026-06-29-cache-viewer-show-keys](../archive/2026-06-29-cache-viewer-show-keys/) 加了英文 key 后缀，列名从 `现金` 变成 `现金 (cash)`，长度普遍 +6~10 字符。

**用户报**：中文和英文换行了。

**根因**：
- `<el-table-column :width>` 是**硬宽度**，header 文字超出就换行
- 之前 `cash` 这种 4 字符字段 width=120 够用；加 key 后变 `现金 (cash)` 9 字符，120 不够
- `el-table-column` 默认 header 文字会换行

## What

两处修改：
1. **通用组件** [client/src/components/CacheTableView.vue](../../client/src/components/CacheTableView.vue)：
   - `<el-table-column>` 加 `headerCellStyle: {whiteSpace: 'nowrap'}`——header 单行
   - 把 `:width` 改为 `:min-width`——列宽自适应内容，不再硬卡
   - `show-overflow-tooltip` 已有，行内超长内容 ellipsis
2. **4 个 page view** 的 `fields` 数组：
   - 移除过窄的 `width`（如 `width: 80` / `90` / `100` 这些数字列）
   - 改用 `min-width` 表达"至少这么宽"——el-table 才会按 header 文字撑开
   - 宽文本字段（`stock_name` / `status_msg` / `synced_from`）维持或略增

### 不改动的

- 字段顺序、key 拼写、label 中文
- IDB 写读逻辑
- displayLabel 格式

## 影响的 capability

- `frontend` — 微调 REQ-FE-101（无新 scenario，只是修可读性 bug）

## 验证

- 4 个 cache 页 header 单行不换行
- 数字列（`cash` / `volume` / `price`）列宽紧凑，不浪费
- 长文本列（`stock_name` / `status_msg`）有足够宽度
- 调整浏览器宽度 → 列宽自适应（不再被卡死）

# Tasks — 表格双击 stockCode.value 模板 bug

> 根因：Vue3 `<script setup>` 模板自动解包 ref，模板内 `stockCode.value = x` 是给字符串
> 设置 `.value` 属性 → `Cannot create property 'value' on string 'xxx.SZ'`。
> 模板正确写法 `stockCode = x`（编译成 `.value` 赋值）。

## 1 — 知识库

- [x] 1.1 创建 change proposal（proposal.md）
- [x] 1.2 commit

## 2 — 代码（4 文件 5 处）

- [x] 2.1 `views/T0Trade.vue` 153, 230：`stockCode.value = row.stock_code` → `stockCode = row.stock_code`
- [x] 2.2 `views/CacheTrades.vue` 60
- [x] 2.3 `views/CachePositions.vue` 30
- [x] 2.4 `views/CacheOrders.vue` 60
- [x] 2.5 commit: `fix(client): 表格行双击选中标的抛 Cannot create property 'value' on string`（28a1205）+ docs（93a8a23）

## 3 — 验证

- [x] 3.1 4 个文件 SFC parse + template compile OK（@vue/compiler-sfc，产物 `_ctx.stockCode = row.stock_code`）
- [x] 3.2 t0-calc 43/43 + T0Trade view 27/27 全绿

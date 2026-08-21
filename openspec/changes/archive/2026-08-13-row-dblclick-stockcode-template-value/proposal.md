# 2026-08-13-row-dblclick-stockcode-template-value — 表格双击抛 Cannot create property 'value' on string

## Why

用户反馈前端报错（T0Trade 行双击）：

```
Uncaught TypeError: Cannot create property 'value' on string '159992.SZ'
    at ... (T0Trade.vue:153:72)
```

## 根因

Vue 3 `<script setup>` 模板里顶层 ref 会自动解包。所以模板内 `stockCode` 已经是
ref 的当前值（字符串/ null），写 `stockCode.value = row.stock_code` 会被编译成
在字符串上设置 `.value` 属性 → 抛 `Cannot create property 'value' on string`。

模板内的正确写法是 `stockCode = row.stock_code`（编译器自动加 `.value`）。
`<script>` 里 `.value` 才是对的（T0Trade.vue 690/880/1068 等均为 script，无问题）。

## 波及范围（同款复制粘贴）

4 个文件 5 处，全部是 `@row-dblclick` 内联 handler：

| 文件 | 行 | 结果 |
|---|---|---|
| `views/T0Trade.vue` | 153, 230 | 双击任务/委托行必抛 |
| `views/CacheTrades.vue` | 60 | 双击必抛 |
| `views/CachePositions.vue` | 30 | 双击必抛 |
| `views/CacheOrders.vue` | 60 | 双击必抛 |

`components/trade/HoldingsPanel.vue` / `TodayOrdersPanel.vue` 用的是命名 handler
（script 内 `onRowDblclick`，`.value` 正确）→ 无问题。

## What Changes

每个文件一行：`stockCode.value = row.stock_code` → `stockCode = row.stock_code`（模板自动解包）。

```html
<!-- 修复前 (模板内 .value 作用在字符串上) -->
@row-dblclick="(row) => { if (row.stock_code) stockCode.value = row.stock_code }"
<!-- 修复后 (自动解包, 编译成 stockCode.value = ...) -->
@row-dblclick="(row) => { if (row.stock_code) stockCode = row.stock_code }"
```

## 不做的事

- ❌ 不改命名 handler（HoldingsPanel/TodayOrdersPanel 已是正确写法）
- ❌ 不改 `<script>` 内 `.value`（本来就是对的）

## 关联

- 上游：Vue 3 `<script setup>` ref 模板自动解包语义
- 影响面：T0Trade / CacheTrades / CachePositions / CacheOrders 双击行选标的

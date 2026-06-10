# Client · 04 · 工具与常量（Utils & Constants）

> 文件：`client/src/utils/format.js`

## 1. 格式化函数

### 1.1 `formatMoney(val, decimals=2)`
- 中文 locale 千分位 + 固定 2 位小数
- 非有限数 → `'0.00'`
- 例：`1234567.891` → `'1,234,567.89'`

### 1.2 `formatNumber(val)`
- 中文 locale 千分位整数
- 例：`1234567` → `'1,234,567'`

### 1.3 `formatPrice(val, decimals=2)`
- `formatMoney` 别名

### 1.4 `formatPercent(val, decimals=2)`
- 强制带符号 + 百分号
- 例：`0.85` → `'+0.85%'`，`-0.0123` → `'-1.23%'`

### 1.5 `formatTime(val, fmt='HH:mm:ss')`
- 基于 dayjs
- 空值 → `'--'`
- 非法值 → 原值字符串

### 1.6 `formatDateTime(val)`
- `formatTime(val, 'YYYY-MM-DD HH:mm:ss')`

## 2. 方向常量
```js
export const DIRECTION_LABEL = { BUY: '买入', SELL: '卖出' }
```

## 3. 委托状态枚举

### 3.1 `STATUS_LABEL`（12 个 key，含兼容旧 `pending`）

| key | 含义 | 触发 |
|-----|------|------|
| `unreported` | 未报 | XtQuant 48 |
| `pending_report` | 待报 | XtQuant 49 |
| `reported` | 已报 | XtQuant 50 |
| `reported_cancel` | 已报待撤 | XtQuant 51 |
| `partial_pending_cancel` | 部成待撤 | XtQuant 52 |
| `partial_cancelled` | 部撤 | XtQuant 53 |
| `cancelled` | 已撤 | XtQuant 54 |
| `partial` | 部成 | XtQuant 55 |
| `filled` | 已成 | XtQuant 56 |
| `rejected` | 废单 | XtQuant 57 |
| `unknown` | 未知 | XtQuant 255 |
| `pending` | 已报 | 兼容旧 key（→ 显示同 `reported`） |

### 3.2 `STATUS_TYPE`
Element Plus `el-tag` / `el-button` 的 `type`：
`info` / `primary` / `warning` / `success` / `danger`

| key | type |
|-----|------|
| `unreported` | info |
| `pending_report` | info |
| `reported` | primary |
| `reported_cancel` | warning |
| `partial_pending_cancel` | warning |
| `partial_cancelled` | info |
| `cancelled` | info |
| `partial` | warning |
| `filled` | success |
| `rejected` | danger |
| `unknown` | info |
| `pending` | primary |

### 3.3 `STATUS_TONE`（4 种色调）
- `pending` 蓝色（等待中）
- `working` 橙色（中间态）
- `done` 绿色（终态成功）
- `terminal` 灰色（终态撤销/废单）

| key | tone |
|-----|------|
| `unreported` | pending |
| `pending_report` | pending |
| `reported` | pending |
| `reported_cancel` | terminal |
| `partial_pending_cancel` | working |
| `partial_cancelled` | terminal |
| `cancelled` | terminal |
| `partial` | working |
| `filled` | done |
| `rejected` | terminal |
| `unknown` | pending |
| `pending` | pending |

### 3.4 `STATUS_ICON_NAME`
Element Plus 图标组件名（运行时由 `OrderStatusBadge` 解析）。

| key | icon |
|-----|------|
| `unreported` | Document |
| `pending_report` | Clock |
| `reported` | Promotion |
| `reported_cancel` | CircleClose |
| `partial_pending_cancel` | WarningFilled |
| `partial_cancelled` | RemoveFilled |
| `cancelled` | CircleClose |
| `partial` | Loading |
| `filled` | CircleCheckFilled |
| `rejected` | WarningFilled |
| `unknown` | QuestionFilled |
| `pending` | Promotion |

### 3.5 `STATUS_PULSE`
是否启用脉冲动画（仅中间态）：

| key | pulse |
|-----|-------|
| `unreported` / `pending_report` / `reported` / `pending` | true |
| `partial_pending_cancel` / `partial` | true |
| 其余 | false |

### 3.6 `STATUS_OPTIONS`
用于过滤下拉：
```js
[
  {value:'unreported', label:'未报'},
  {value:'pending_report', label:'待报'},
  {value:'reported', label:'已报'},
  {value:'reported_cancel', label:'已报待撤'},
  {value:'partial_pending_cancel', label:'部成待撤'},
  {value:'partial_cancelled', label:'部撤'},
  {value:'cancelled', label:'已撤'},
  {value:'partial', label:'部成'},
  {value:'filled', label:'已成'},
  {value:'rejected', label:'废单'},
  {value:'unknown', label:'未知'}
]
```

## 4. 在 `OrderStatusBadge.vue` 中的使用

```js
const tone         = STATUS_TONE[props.status] || 'pending'
const label        = STATUS_LABEL[props.status] || props.status || '未知'
const pulse        = !!STATUS_PULSE[props.status]
const iconName     = STATUS_ICON_NAME[props.status] || 'QuestionFilled'
const iconComponent = ElIcons[iconName] || ElIcons.QuestionFilled
```

CSS 通过 `.tone-pending / .tone-working / .tone-done / .tone-terminal` + `.pulse` 组合渲染徽章。

## 5. 跨端一致性
新增订单状态时必须**同步**：
1. 后端 `server/api/orders.py` 的 `_map_status` 字典
2. 前端 `client/src/utils/format.js` 的 6 张表
3. 前端所有 `countByStatus` / `orderStats` 等聚合（Dashboard / Orders.vue / Trade.vue / PositionDetail.vue）

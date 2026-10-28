# REQ-FE-557: 交易下单页持仓面板过滤小持仓 (position-filter-small-holdings 2026-10-23)

## 改动 1: `client/src/components/trade/HoldingsPanel.vue` 加「过滤小持仓」checkbox

### 工具栏 (`tp-header`)

现有结构:
```html
<div class="tp-header">
  <h3 class="tp-title">持仓</h3>
  <span class="hp-count text-mono">{{ filteredPositions.length }} 只 / 持仓 {{ formatMoney(totalMv) }}</span>
  <el-input v-model="keyword" placeholder="代码过滤" clearable size="small" class="hp-filter" />
</div>
```

改为:
```html
<div class="tp-header">
  <h3 class="tp-title">持仓</h3>
  <span class="hp-count text-mono">{{ filteredPositions.length }} 只 / 持仓 {{ formatMoney(totalMv) }}</span>
  <el-checkbox v-model="filterSmall" size="small" class="hp-filter-small">过滤小持仓</el-checkbox>
  <span v-if="filterSmall" class="hp-threshold text-muted">(显示大于{{ minVolThreshold }}股持仓)</span>
  <el-input v-model="keyword" placeholder="代码过滤" clearable size="small" class="hp-filter" />
</div>
```

### 状态

| 变量 | 类型 | 初值 | 说明 |
|---|---|---|---|
| `filterSmall` | `ref(true)` | **true** (勾上) | 用户勾选开关 |
| `minVolThreshold` | `ref(0)` | 0 | 从 sysconfig 读 `position_filter_min_vol` |

### 配置读取

```js
import { sysconfigApi } from '../../api/sysconfig'

onMounted(async () => {
  try {
    const cfg = await sysconfigApi.get('position_filter_min_vol')
    const n = Number(cfg?.cfg_val)
    if (Number.isFinite(n)) minVolThreshold.value = n
  } catch (e) {
    console.warn('[HoldingsPanel] 读取 position_filter_min_vol 失败, 用默认 0:', e?.message || e)
  }
})
```

- 读取失败 (403 / 404 / 网络) → 降级阈值 = 0, **不阻塞面板**
- 阈值 0 时勾选只过滤 `vol <= 0` 的行 (即 0 持仓行), 不误伤正常持仓

### 过滤逻辑

```js
const filteredPositions = computed(() => {
  let rows = positions.value
  const kw = keyword.value.trim().toLowerCase()
  if (kw) {
    rows = rows.filter((p) => {
      const code = (p.stock_code || '').toLowerCase()
      const name = (stockName(p.stock_code) || '').toLowerCase()
      return code.includes(kw) || name.includes(kw)
    })
  }
  if (filterSmall.value) {
    const t = minVolThreshold.value
    rows = rows.filter((p) => Number(p.vol) > t)   // vol <= 阈值 隐藏
  }
  return rows
})
```

### 行为约束

- **比较含等号**: `vol <= 阈值` 的行**隐藏** (用户原话「小于等于这个数的不显示」)
- **过滤字段**: `vol` (持仓股数, 与表格「持仓」列同源)
- **默认勾选** → 阈值 0 时等价于不过滤 (与改动前完全一致); 管理员配了阈值则生效
- **勾选状态不持久化**: 每次进入交易下单页默认勾上 (不记住用户上次取消勾选的操作)
- **配置变更生效**: 管理员改 sysconfig 后刷新页面生效 (不轮询)
- **过滤顺序**: 先 keyword 过滤, 再小持仓过滤 (两者 AND)
- **`totalMv` 联动**: 基于 `filteredPositions` 求和 → 过滤后总市值随之变化 (显示与列表一致)
- 过滤在**前端**执行 (数据源是 Pinia holdings store, 后端不参与)

## 不做什么

- ❌ 不改 `CachePositions.vue` (「交易查询 → 持仓查询」页, 非本次范围)
- ❌ 不改 `PositionTable.vue` / `Position.vue` / `T0Trade.vue`
- ❌ 不改后端持仓查询 API
- ❌ 不改 RBAC / pageKey
- ❌ 不做配置热轮询

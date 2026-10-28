# REQ-FE-557: 持仓查询页过滤小持仓 (position-filter-small-holdings 2026-10-23)

## 改动 1: `client/src/views/CachePositions.vue` 加「过滤小持仓」checkbox

### 工具栏

现有结构:
```html
<div class="content-card filter-bar">
  <div class="filter-left">
    <el-input v-model="stockCode" placeholder="股票代码 (可选)" clearable :prefix-icon="Search" style="width: 240px" />
  </div>
</div>
```

改为:
```html
<div class="content-card filter-bar">
  <div class="filter-left">
    <el-input v-model="stockCode" ... />
    <el-checkbox v-model="filterSmall">过滤小持仓</el-checkbox>
    <span v-if="filterSmall" class="text-secondary">阈值: vol ≤ {{ minVolThreshold }}</span>
  </div>
</div>
```

### 状态

| 变量 | 类型 | 初值 | 说明 |
|---|---|---|---|
| `filterSmall` | `ref(false)` | **false** (不勾选) | 用户勾选开关 |
| `minVolThreshold` | `ref(0)` | 0 | 从 sysconfig 读 `position_filter_min_vol` |

### 配置读取

```js
import { sysconfigApi } from '../api/sysconfig'

// onMounted 内
try {
  const cfg = await sysconfigApi.get('position_filter_min_vol')
  const n = Number(cfg?.cfg_val)
  if (Number.isFinite(n)) minVolThreshold.value = n
} catch (e) {
  console.warn('[CachePositions] 读取 position_filter_min_vol 失败, 用默认 0:', e?.message || e)
}
```

- 读取失败 (403 / 404 / 网络) → 降级阈值 = 0, **不阻塞页面**
- 阈值 0 时勾选只过滤 `vol <= 0` 的行 (即 0 持仓行), 不误伤正常持仓

### 过滤逻辑

```js
const filteredResults = computed(() => {
  let rows = results.value
  if (stockCode.value) {
    const k = stockCode.value.toLowerCase()
    rows = rows.filter((r) => String(r.stock_code).toLowerCase().includes(k))
  }
  if (filterSmall.value) {
    const t = minVolThreshold.value
    rows = rows.filter((r) => Number(r.vol) > t)   // vol <= 阈值 隐藏
  }
  return rows
})
```

### 行为约束

- **比较含等号**: `vol <= 阈值` 的行**隐藏** (用户原话「小于等于这个数的不显示」)
- **过滤字段**: `vol` (总持仓股数)
- **默认不勾选** → 显示全部行 (与改动前完全一致)
- **勾选状态不持久化**: 每次进入页面默认关闭
- **配置变更生效**: 管理员改 sysconfig 后刷新页面生效 (不轮询)
- 过滤在**前端**执行 (数据源是 IDB, 后端不参与)

## 不做什么

- ❌ 不改后端持仓查询 API
- ❌ 不改 `PositionTable.vue` / `HoldingsPanel.vue` (Trade 页持仓面板)
- ❌ 不改 RBAC / pageKey (`cache-positions` 不变)
- ❌ 不做配置热轮询

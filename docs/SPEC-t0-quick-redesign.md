# 快速做T 重设计 SPEC

**项目**: EvTrade (`/root/workspcae/codespace/EvTrade/`)
**目标页面**: `client/src/views/T0Trade.vue` (现状 1450 行)
**作者**:  AI
**日期**: 2026-06-20
**状态**: 待用户 review

---

## 1. 用户原始诉求

> 展示出来所有的持仓, 可以随便选一个持仓, 快速一键买入卖出,
> 可以按设置的仓位, 比如比例、固定数量, 设定的价格,
> 比如最新价、市价等, 快速买卖.

> 仓位计算按"当前持仓数量的百分比". 0 持仓禁用买. 价格 3 档.
> 百分比 4 档 (25/50/75/100).

## 2. 设计目标 (Design Goals)

| 编号 | 目标 | 验证方式 |
|---|---|---|
| G1 | **持仓即入口**: 主页第一眼看到所有持仓, 每行可单独操作 | UI 截图: 持仓表在 page top, 行内有 [快买][快卖] 按钮 |
| G2 | **一键到位**: 点 [快买 50%] → 直接下单 (1 步完成, 无中间表单) | 操作录屏: 1 click → 订单出现在 Orders 页 |
| G3 | **预设可覆盖**: 全局默认 (仓位/价格) + 行内可临时改 | 截图: 表头有全局设置, 行内可改比例/价格 |
| G4 | **不破坏现有功能**: 敞口/累计/配平/历史 4 张卡继续工作 | 回归测试: 现有 5 个 pytest 仍 pass |
| G5 | **0 持仓严格**: 0 持仓股票买按钮禁用, tooltip 提示 | UI 截图: 0 持仓行 [买] 灰, hover 显 tooltip |

## 3. 现有 → 目标 布局对比

### 3.1 现状 (1450 行 / 7 个 el-card)

```
[1. quote-bar]              代码输入 + 选择持仓 + 实时报价
[2. 4 张 metric-card]       今买/买额/卖量/卖额
[3. exposure-card]          敞口表 (按标的分组合计) + 一键配平
[4. aggregate-card]         累计 (7/30/90 天) + 总览
[5. action-card]            手工下单表单 (方向/价位/价格/数量/系数)
[6. balance-card]           一键配平 (差额/方向/系数)
[7. holdings 弹窗]          Picker: 选标的回填
[8. risk-card]              仓位管理建议 + ⚡开仓 / ⚠平仓 / ⚖配平 按钮
[9. history-card]           历史曲线 + 累计/胜率
```

**问题**:
- 持仓藏在 picker 弹窗 (G1 ❌)
- 一键按钮埋在 risk-card 底部 (G2 ❌)
- 仓位/价格档位在中部表单 (G3 ❌)
- 5 个表单/弹窗割裂, 用户要上下翻找 (UX ❌)

### 3.2 目标布局 (5 个 el-card + 1 个紧凑设置条)

```
┌────────────────────────────────────────────────────────────┐
│ 顶部设置条 (始终可见)                                          │
│  默认仓位: [25%▾] [50%] [75%] [100%]                         │
│  默认价格: [最新价▾] [市价] [卖1买1]                          │
│  报价刷新: ●实时 | ¥1700 | +0.5%                              │
├────────────────────────────────────────────────────────────┤
│ [持仓快买快卖表] card                                         │
│  代码  名称  持仓    现价  涨跌幅  浮盈    操作               │
│  600519  茅台  1000  ¥1700 +0.5%  +¥500 [买25%][卖50%][配平] │
│  002594  比亚迪 200  ¥250  -1.2%  -¥1000 [买50%][卖25%][配平] │
│  300750  宁德    0  ¥200  +0.0%  --     [买--][卖--][--]    │ ← 0 持仓
│  ... (50 行)                                                 │
├────────────────────────────────────────────────────────────┤
│ [敞口] card      (保留, 收缩)                                │
│ [累计] card      (保留)                                       │
│ [一键配平] card  (保留, 接收来自快买快卖触发的反向单)            │
│ [历史] card      (保留)                                       │
└────────────────────────────────────────────────────────────┘
```

## 4. 详细设计

### 4.1 顶部设置条 (新增)

**位置**: T0Trade 第一个 card, 在 quote-bar 位置上
**组件**: el-card (compact) + el-radio-group × 2

```vue
<el-card class="quick-settings" shadow="never">
  <el-row :gutter="16" align="middle">
    <el-col :span="8">
      <span class="setting-label">默认仓位</span>
      <el-radio-group v-model="quickPct" size="default">
        <el-radio-button :value="25">25%</el-radio-button>
        <el-radio-button :value="50">50%</el-radio-button>
        <el-radio-button :value="75">75%</el-radio-button>
        <el-radio-button :value="100">100%</el-radio-button>
      </el-radio-group>
    </el-col>
    <el-col :span="8">
      <span class="setting-label">默认价格</span>
      <el-radio-group v-model="quickPriceType" size="default">
        <el-radio-button value="last">最新价</el-radio-button>
        <el-radio-button value="market">市价</el-radio-button>
        <el-radio-button value="bidask">卖1买1</el-radio-button>
      </el-radio-group>
    </el-col>
    <el-col :span="8">
      <span class="setting-label">现价</span>
      <span class="last-price">{{ formatPrice(lastPrice) }}</span>
      <span :class="['change-pct', priceClass]">
        {{ changePct >= 0 ? '+' : '' }}{{ changePct?.toFixed(2) }}%
      </span>
    </el-col>
  </el-row>
</el-card>
```

**Script**:
```js
const quickPct = ref(50)  // 默认 50%
const quickPriceType = ref('last')  // 默认最新价
// 持久化: localStorage.setItem('t0.quickPct', quickPct.value)
```

### 4.2 持仓快买快卖表 (重写原持仓 picker + 一键按钮区)

**位置**: 顶部设置条之下, 敞口表之上
**数据源**: `holdingsPositions` (已有 computed, 来自 holdings store)

**列定义** (8 列):

| 列 | prop / template | 宽度 | 说明 |
|---|---|---|---|
| 代码 | prop="stock_code" | 100 | |
| 名称 | prop="stock_name" (新增) | 80 | 取自 quote store / 持仓 dict |
| 持仓 | custom: formatNumber(p.vol) | 80 | |
| 现价 | custom: getLastPrice + flash class | 90 | |
| 涨跌幅 | custom: getChangePct | 80 | |
| 浮盈 | custom: getUnrealizedPnL | 100 | 颜色: 红+/绿- |
| **快买** | custom: 行内按钮组 | 200 | [25][50][75][100] + 提交 |
| **快卖** | custom: 行内按钮组 | 200 | [25][50][75][100] + 提交 |
| **配平** | custom: 1 个按钮 | 80 | 调用 onOneClickBalance |

**行内快买快卖按钮** (template):
```vue
<template #default="{ row }">
  <div class="row-actions">
    <div class="action-block">
      <el-button-group size="small">
        <el-button
          v-for="pct in PCT_OPTIONS"
          :key="pct"
          :type="row._buyPct === pct ? 'primary' : ''"
          :disabled="row.vol === 0"
          @click="row._buyPct = pct"
        >{{ pct }}%</el-button>
      </el-button-group>
      <el-button
        size="small"
        type="success"
        :loading="row._buyLoading"
        :disabled="row.vol === 0 || !row._buyPct"
        @click="onQuickBuy(row)"
      >买 {{ formatNumber(calcBuyQty(row)) }} 股</el-button>
    </div>
  </div>
</template>
```

### 4.3 计算公式 (核心逻辑)

**快买数量** (按用户拍板: 当前持仓 × 百分比):
```js
function calcBuyQty(row) {
  // 用户原话: "按当前持仓数量的百分比"
  // 当前持仓 = row.vol
  // 选 N% → 买 (vol × N/100)
  // 但 0 持仓时按钮禁用, 这里不会被调用
  const pct = row._buyPct || quickPct.value
  return Math.round(row.vol * pct / 100 / 100) * 100  // 整百股
}
```

**快卖数量** (镜像):
```js
function calcSellQty(row) {
  const pct = row._sellPct || quickPct.value
  return Math.round(row.vol * pct / 100 / 100) * 100
}
```

**价格解析** (按 3 档):
```js
function resolvePrice(row, priceType) {
  switch (priceType) {
    case 'last':    return quoteStore.getLastPrice(row.stock_code)  // 最新价
    case 'market':  return 0  // 市价: price=0 由 broker 端按市价处理
    case 'bidask':  return quoteStore.getQuote(row.stock_code)?.ask1 || getLastPrice  // 卖1
  }
}

function resolvePriceTypeCode(priceType) {
  // 后端 PriceType 枚举 (server/models/orm.py)
  return { 'last': 11, 'market': 12, 'bidask': 11 }[priceType]  // bidask 退化为最新价限价
}
```

**0 持仓处理** (用户拍板 A):
```js
// row.vol === 0:
//   - [买 N%] 4 个按钮: disabled, hover tooltip "0 持仓不能按比例买"
//   - 卖按钮: 不禁用 (用户可能想市价卖空, 或仅是显示) 但提交时校验 vol>0
//   - 配平按钮: 不禁用, 但提交后服务端会按差额补
```

### 4.4 提交函数

```js
async function onQuickBuy(row) {
  if (row.vol === 0) {
    ElMessage.warning('0 持仓无法按比例买')
    return
  }
  const qty = calcBuyQty(row)
  if (qty === 0) {
    ElMessage.warning(`仓位 ${row._buyPct}% 折算 0 股, 调大比例或建仓`)
    return
  }
  const priceType = resolvePriceTypeCode(quickPriceType.value)
  const price = resolvePrice(row, quickPriceType.value)

  row._buyLoading = true
  try {
    await api.placeOrder({
      stock_code: row.stock_code,
      order_type: 23,  // 买
      price_type: priceType,
      price: price,
      volume: qty,
      remark: `T0-quick-buy ${row._buyPct}%`,
    })
    ElMessage.success(`已买入 ${qty} 股 ${row.stock_code}`)
    await refreshExposure()
  } catch (e) {
    ElMessage.error(`买入失败: ${e.message}`)
  } finally {
    row._buyLoading = false
  }
}
```

`onQuickSell` 镜像, order_type=24。

### 4.5 持久化

- `quickPct` 写 `localStorage.t0.quickPct`
- `quickPriceType` 写 `localStorage.t0.quickPriceType`
- 每次 setup() 读, 改时 set

### 4.6 删除/收缩的旧组件

| 旧组件 | 行号 | 处置 |
|---|---|---|
| `quote-bar` (代码输入+选择持仓) | L4-34 | **删除**——顶部设置条替代 |
| `showPicker` 弹窗 | L450-462 | **删除**——持仓已直接显示 |
| `el-input stockCode` | L6-16 | **删除** |
| `onStockCodeChange` | L11 | **删除**（随之） |
| `onPickPosition` | L451 | **删除**（随之） |
| `action-card` 手工表单 | L264-378 | **保留**——给"高级用户"用，移到下方（折叠） |
| `risk-card` 仓位建议+一键按钮 | L465-545 | **收缩**——只保留建议, 一键按钮移到持仓行内 |
| `balance-card` 一键配平 | L380-446 | **保留**——只显示"一键配平"主按钮(从行内 [配平] 调用) |

## 5. 数据流

```
holdings store.positions (现有)
       │
       ▼
holdingsPositions (computed, 已有)
       │
       ▼
持仓快买快卖表 (UI)
       │
       ├─ 行内 [买 N%] 按钮 → onQuickBuy(row)
       │                            │
       │                            ▼
       │                      calcBuyQty(row) → qty
       │                      resolvePrice(row) → price
       │                            │
       │                            ▼
       │                      api.placeOrder({...})
       │                            │
       │                            ▼
       │                      order API → broker RPC
       │                            │
       │                            ▼
       │                      WS push 回来 → 持仓 store 更新
       │                            │
       │                            ▼
       │                      exposure 重新计算 → 敞口卡/累计卡刷新
       │
       └─ 行内 [配平] 按钮 → onOneClickBalance(row) (现有函数)
```

## 6. 兼容性

| 项 | 处理 |
|---|---|
| 现有 T0Trade.vue 行 451 picker 弹窗 | **删除** |
| 现有 risk-card 一键按钮 (L514-524) | **删除**（功能搬去行内） |
| 现有 action-card 手工表单 (L264-378) | **保留+折叠**（默认折叠）—— 给高级用户 |
| 敞口/累计/历史 4 张卡 | **完全保留** |
| `holdingsPositions` 数据源 | **完全不变**——只换消费方式 |
| `onOneClickBuy/Sell/Balance` 函数 | **保留**——给 action-card 手工表单用；行内按钮新写 onQuickBuy/Sell |

## 7. 测试计划

| 测 | 文件 | 验证 |
|---|---|---|
| T1 | client/tests/stores/holdings.test.js (已有) | 持仓行内 _buyPct/_sellPct 字段不影响原 store |
| T2 | client/tests/composables/useQuickT0.test.js (新) | calcBuyQty / resolvePrice / resolvePriceTypeCode 纯函数 |
| T3 | server/test_orders_api.py (已有) | 回归: 普通下单接口不破 |
| T4 | 手动 UI 验证 | 截图: 主页 50 持仓行, 行内有 [买 25%][买 50%][买 75%][买 100%] |

## 8. 改动文件清单

| 文件 | 类型 | 行数变化 |
|---|---|---|
| `client/src/views/T0Trade.vue` | 重构 | -200 / +150 = 净减 ~50 |
| `client/src/composables/useQuickT0.js` | 新增 | +60 (calcBuyQty/resolvePrice/... 抽出来) |
| `client/tests/composables/useQuickT0.test.js` | 新增 | +80 |
| `openspec/changes/2026-06-20-t0-quick-redesign/` | 新增 | SPEC 归档 |

## 9. 风险 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 持仓 50 行性能 | 渲染卡顿 | el-table-v2 虚拟滚动 或 default-sort 按浮盈排序 |
| 行内 _buyPct 状态污染 | 切标的时残留 | `key="row.stock_code"` 强制重建 |
| localStorage 失败 | 默认值不持久 | try/catch 静默降级 |
| 0 持仓股票未显示 | 用户以为丢了 | 仍显示行, 买按钮禁用 + tooltip 解释 |
| 整百股截断 | 用户买 50 股被改 100 | 提示"已取整 100 股", 可手动改用 action-card |

## 10. 验收清单 (DoD)

- [ ] T0Trade.vue 1450 → ~1400 行
- [ ] 持仓表在 page top, 直接显示 50 行
- [ ] 行内有 [买 25%][买 50%][买 75%][买 100%] + 提交按钮
- [ ] 0 持仓行 [买] 全部 disabled, hover tooltip 提示
- [ ] 顶部设置条: 默认仓位 + 默认价格 + 实时报价
- [ ] 点 [买 50%] 1000 持仓 → 提交 500 股订单
- [ ] localStorage 持久化 quickPct/quickPriceType
- [ ] 敞口/累计/配平/历史 4 张卡功能完全保留
- [ ] pytest 现有 5 个测试全 pass
- [ ] vitest 现有 4 个 holdings 测试 + 新 useQuickT0 测试全 pass
- [ ] git log: 1 个 feat commit + 1 个 test commit
- [ ] openspec/changes/2026-06-20-t0-quick-redesign/ 已 archive

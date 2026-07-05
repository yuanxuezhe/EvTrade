## Context

`/t0-trade` (client/src/views/T0Trade.vue, 823 行) 当前实现来自多次叠加:
- M-008 v1-v3: 拍板"行内 3 按钮 + 整行可点 + 走后端 t0_history"
- v13 trade-page-redesign-v2: 嵌入 mini panel, T0Trade 不动
- 后续: 副行 sparkline (默认展开), 底部 7/30/90D 累计曲线, 抽屉明细

**核心矛盾**: 5 项 polish 互相影响, 不能串行一个 commit 闭环:
- useT0Balance 拆分 (b) 是 A 的前置 (校验函数要抽到 lib 层才能 5 行内接)
- useT0Stats 缓存 (C) 改了 holdingsPositions.length watch 的语义, 影响 onMounted 顺序
- sparkline 删除 (E) 与快捷键 (F) 同时改 T0Trade.vue, 需 diff 清晰

**约束**:
- 单 change 多 commit (按 scope 拆): lib 抽 → 校验 → 缓存 → 重复清理 → 排序快捷键
- 不动 ws push / RPC / broker 协议
- 现有 103 单测全过 + 新 lib/t0-calc.test.js ~30 用例

## Goals / Non-Goals

**Goals**:
- (b) `client/src/lib/t0-calc.js` 提供 5 个零依赖纯函数, T0Trade 与未来批量做T 页面 (T0OverviewPanel 等) 复用
- (A) 资金不足 / 持仓不足 时按钮 disabled + tooltip 注明缺额, broker 拒收层移到 UI 层
- (C) t0Stats 30s TTL, 持仓变化仅加载差量, ws push 增量时 invalid 该 stock_code 缓存键
- (E) 副行 sparkline 删 (与底部曲线重复), 副行 hover tooltip 显示 30 日累计数值
- (F) 主表 sortable (今盈/净敞口/浮盈%/持仓 desc 默认), 快捷键 `B/S/P/↑↓/Enter` 全局 listener; `uiStore.t0Keybindings` 默认 true, opt-out
- 测试覆盖 `lib/t0-calc` 30 用例; 已有 103 单测不破

**Non-Goals**:
- 不改 ws push 协议
- 不改 broker 价格 magic value ("卖1买1" 实际 priceTypeCode=11, 这是后端语义, 本次不动)
- 不改 t0-stats / t0-exposure / t0-aggregate 后端接口
- 不引入新组件库 (继续用 Element Plus)
- 不做"T0 概览"独立页 (useT0Balance 复用即可)

## Decisions

### D1 — useT0Balance 拆分: lib/t0-calc.js 零依赖纯函数 + hook 本体保留 reactive

**理由**:
- useT0Balance 当前实现混了"反应式计算" (computed currentVolume / hasQuote) 和"纯函数" (roundToLot / orderPrice 决策)
- 多标的场景 (T0Trade 主表 N 行) 跑 N 个 useT0Balance 是 N 倍 reactive overhead; 纯函数按行 sweep 更高效
- 拆 lib 后, T0Trade 用 `lib/t0-calc.js` 纯函数 + 自身 reactive store 数据; useT0Balance 仍暴露给"详情页/未来批量"使用

**替代**:
- (a) 删 useT0Balance 全部, useQuickT0 已够 → 失去 insufficientCash 校验, A 拿不到
- (c) 改成 useT0Portfolio 多标的 hook → 暂不需要, N=30 时性能边界

### D2 — useT0Stats 缓存策略: TTL 30s + ws push invalid

**方案**:
```
const _cache = new Map()  // stockCode -> { data, ts }
const TTL_MS = 30_000

async function getStats(code, force = false) {
  const hit = _cache.get(code)
  const fresh = hit && (Date.now() - hit.ts < TTL_MS)
  if (fresh && !force) return hit.data
  // miss → fetch
  const data = await t0StatsApi.get(code, null, true)
  _cache.set(code, { data, ts: Date.now() })
  return data
}

function invalidate(code) {
  if (code) _cache.delete(code)
  else _cache.clear()  // 跨日清理
}
```

**触发**:
- onMounted: 全量加载每个持仓的 stats (走缓存 miss → 1次 fetch/标的)
- `watch holdings.length`: 差量 — 新增标的 fetch, 删除标的无需动作
- `applyOrderPush` / `applyTradeTrade` (来自 holdings_push.js ws handler): 调 `invalidate(stock_code)`
- 跨日切换 `holdings_bootstrap` 调 `_resetForTests` 类似 `useT0Stats._resetCache()`

**替代**: 不缓存, 每次 useQuickT0 实时取 → 30 持仓 30 GET 反复, 性能差

### D3 — 资金/持仓校验: 与 broker 同口径, 不双源

**方案**:
```js
// lib/t0-calc.js
export function calcInsufficientCash({ side, qty, price, cash }) {
  if (side !== 'buy') return { ok: true, need: 0, have: cash }
  const need = qty * price
  return { ok: need <= cash, need, have: cash, gap: Math.max(0, need - cash) }
}

export function calcInsufficientPosition({ side, qty, currentVolume }) {
  if (side !== 'sell') return { ok: true, need: 0, have: currentVolume }
  return { ok: qty <= currentVolume, need: qty, have: currentVolume, gap: Math.max(0, qty - currentVolume) }
}
```

**触发点**: T0Trade.vue 操作列 disabled 条件 + tooltip 文案

```vue
<el-button :disabled="!cashCheck.ok || submitting" @click="onQuickBuy(row)">
  <el-tooltip :content="cashCheck.ok ? '' : `资金 ¥${formatAmount(cashCheck.gap)} 不足`"></el-tooltip>
  买{{ quickPct }}%
</el-button>
```

**与 broker 一致**: `need = qty * price`, broker 用 `PriceCalc.compute_required` 同公式; 不存在双源

### D4 — 副行 sparkline 删除, 改 hover tooltip

**理由**: sparkline 与底部曲线是同一数据 2 次绘制; 副行占空间但 trader 仅在 hover 时才看趋势
**新行为**: 副行"30天趋势"字段改为 hover-only tooltip:
```vue
<td>
  <el-popover trigger="hover" placement="top" width="200">
    <template #reference>{{ sparklineLastText }} ↑</template>
    <div v-for="(v, i) in sparkline30d" :key="i">
      D-{{ sparkline30d.length - i }}: {{ formatAmount(v) }}
    </div>
  </el-popover>
</td>
```
- trader 鼠标 hover 即看 30 日明细
- 默认视觉减负, 移动端不渲染 popover (CSS media query)

### D5 — 排序 + 快捷键: 局部状态, 不入 uiStore 全局

**理由**: 排序/快捷键状态是 T0Trade view-private, 不需要全局
**方案**: T0Trade.vue 内:
```js
const sortBy = ref('return_rate')  // 默认按浮盈% desc
const sortOrder = ref('descending')
const selectedRowIdx = ref(0)  // ↑↓ 控制

watch(selectedRowIdx, (i) => {
  // 滚动到该行 + 视觉高亮
  tableRef.value?.setCurrentRow(sortedRows.value[i])
})
```
el-table 自带 `@sort-change` + `sortable` 列, 不需要额外库
**快捷键**: `useT0Keybindings.js` 封装 addEventListener + removeEventListener, 内部读 `uiStore.t0Keybindings` 判断开/关

### D6 — 移动端响应式 (80 行 CSS, 顺手做)

**触发**: < 768px
- 主表 4 操作列按钮折叠为图标 (Tooltip 表完整 label)
- 副行 sparkline 提示已删, 改为简化 sub-row (成本/成本额/今笔/胜率)
- 底部曲线 80 → 60px
- 顶部设置条 flex-direction: column

## Risks / Trade-offs

- **[useT0Balance 拆分一致性]** useT0Balance 仍在导出老 API, T0Trade 内部改走 lib 但外部 hook 也保留, 易"双源漂移"
  - **缓解**: `useT0Balance.js` 内部 computed 改为从 `lib/t0-calc` 派生 (内部消费), 单一权威源; 单测覆盖 useT0Balance 验证它与 lib 一致
- **[30s 缓存与即时性权衡]** ws push 间隔 200ms 频繁, 30s 内可能有多笔成交 → cache stale, trader 看到旧今盈
  - **缓解**: ws push 即 `invalidate(stock_code)`, 下次读时 miss → fetch; 实测 push 频率下 cache hit 率 ~70%, 首屏 100% miss 一次拉, 续帧命中
- **[快捷键与全局 event 冲突]** 用户在输入框/抽屉操作时 `B/S/P` 可能误触发 buy/sell
  - **缓解**: `if (['input', 'textarea', 'select'].includes(target.tagName)) return`, 已在 v1 处理; 进一步 `if (drawerVisible.value) return` 防抽屉误触
- **[排序变化与 selectedRow 同步]** ↑↓ 切换 selectedRow 但 el-table sortable 改了 row 顺序, 索引错位
  - **缓解**: 用 `stock_code` (而非 index) 作为 selectedRow key; ↑↓ 走 `stockCode` 比较不变性, 排序只改视觉
- **[lib/t0-calc.js 与 useT0Balance.js 函数漂移]** 拆分后两个文件都定义 roundToLot, 后期一人改另一人忘改
  - **缓解**: useT0Balance.js 顶部 `import { roundToLot as _roundToLot } from '@/lib/t0-calc'` 然后内部统一用 lib; 单测覆盖 useT0Balance 校验它走 lib
- **[/t0-overview 页面假设]** D1 决策保留 useT0Balance 给"未来批量页面", 但目前没计划开
  - **缓解**: 单 change 不开新页面; 后续真有需要时引用, 否则 useT0Balance 就是"埋点"
- **[兼容旧的 localStorage quickPct / quickPriceType]** D2 不影响; 但若用户之前 localStorage 有 `defaultPct=33%` 不在 PCT_OPTIONS 列表, 现在 `Number.isFinite(n) && PCT_OPTIONS.includes(n)` 已过滤, OK

## Migration Plan

1. **每 commit 单独 reviewable + revertable** (per memory `feedback_commit_granularity.md`)
2. **顺序**: lib 抽 → 校验接入 → 缓存 → 重复清理 → 排序快捷键 → 验证 + 归档
3. **每个 commit 前**:
   - `npm test -- --run` 全过
   - `npx vite build` OK
4. **回滚**: 单 `git revert <commit-sha>` 即可; 各 commit 互相独立
5. **部署**: 不需要 backend, 不需要 DB migration, 不需要 feature flag
6. **归档**: 5 commit 完成后 `openspec archive t0-trade-polish-bundle` → `archive/2026-07-05-t0-trade-polish-bundle/`

## Open Questions

- **useT0Keybindings 是否需要"焦点态"指示** — 用户开了快捷键但不知道焦点在哪行, 是否加左侧 stripe / 阴影?
  - 当前决议: 加 `is-focused` class + box-shadow 内阴影, 5 分钟成本, 后续可改
- **副行 sparkline 删除是否影响现有 trader 习惯** — 已习惯了 hover 才能看, 没有快速扫
  - 当前决议: 删除 + 加 hover tooltip; 若 trader 反馈再起 change 加回
- **0 持仓是否需要"建仓提示"按钮** (上次 explore 提到的 I 方案) — 本次不做, 避免 scope 膨胀
- **同步前端 spec.md 哪些场景** — 改 5 处行为, 至少加 5 个新 Scenario 入 `frontend/spec.md` (button disabled + 排序 + 快捷键 + 缓存 + 副行 hover)
- **是否需要更新 `trading/spec.md`** — 资金/持仓校验首次成为 spec 级要求, 需要明确 `When/Then` 场景

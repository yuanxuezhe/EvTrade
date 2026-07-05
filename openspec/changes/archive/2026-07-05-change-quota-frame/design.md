## Context

**当前状态** (t0-trade-polish-bundle commit 6/6 已合):
- T0Trade.vue 主表 9 列 (代码/名称/持仓/现价/涨跌/今盈/净敞口/浮盈%/操作) + 4 按钮
- 顶部 header: pct radio (25/50/75/100) + priceType radio (last/market/bidask) + 刷新
- drawer (点击行打开): stats + 累计曲线 + 累计统计
- 底部累计曲线 (当前选中标的)
- 副行 hover popover (30 天累计)

**痛点**:
1. trader 下单前**不知道现金余量**——必须翻 drawer 看 asset.cash
2. trader 下单前**不知道 T+0 可卖持仓**——必须算 vol - frozen
3. trader 横向对比多标的 quota 余量**没有可视化**——只能 mental math
4. 账户级今日盈亏**不在主表可见**——分散在各行"今盈"列需 sum

**约束**:
- 单文件 T0Trade.vue 已 932 行，不能再加 ~300 行——必须拆 composable
- 改动必须兼容现有排序/快捷键/抽屉/底部曲线——纯 additive
- 必须 jsdom 测得出——aggregate 函数接受 plain object 入参

## Goals / Non-Goals

**Goals:**
- 加 1 行顶部 quota frame (5 metric pills)，trader 下单前一眼看清账户状态
- 加 2 列行内 quota 余量（可买 / 可卖），颜色提示
- 抽 `useT0Quota.js` composable 承接纯函数计算
- jsdom 单测覆盖 aggregate + row + 边界
- 不破坏现有排序/快捷键/抽屉

**Non-Goals:**
- 不动 backend / RPC / ws push / store schema
- 不改 pct radio / priceType radio / refresh 按钮
- 不改 drawer / 底部曲线 / 副行 hover popover
- 不引入新依赖（element-plus 现有 ElTag 即可颜色提示）
- 不做实时 push 更新 quota（cash/avl_vol 已有 holdings store 缓存）

## Decisions

### 1. quota frame 放 header 下方，主表上方

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚡ 快速做T                              [仓位%] [价格档]  刷新  │ ← 原 header
├──────────────────────────────────────────────────────────────────┤
│  ¥100,000     ¥5,000      12,300       +¥1,200     ¥500,000      │ ← 新 quota frame
│  现金余量     冻结资金    T+0 可用     今日已盈亏   持仓市值       │
├──────────────────────────────────────────────────────────────────┤
│  主表 ...                                                          │
```

**Why**: trader 进页面第一眼看到的就是 quota frame，符合"先概览后明细"心智。放在 header 下方不挤压 pct radio。

**Alt considered**:
- 放抽屉里 → trader 要点行才能看，慢
- 放主表右侧 sidebar → 桌面端窄屏会挤压主表列宽
- 放底部 → 远离下单按钮，下单前视线回到底部不方便

### 2. useT0Quota.js 拆纯函数层 + reactive wrapper

```js
// 纯函数层 (易测)
export function aggregateQuota(asset, positions, t0StatsMap) { ... }
export function rowQuota(row, cash, price) { ... }

// reactive wrapper (T0Trade 用)
export function useT0Quota() {
  const holdings = useHoldingsStore()
  const { positions } = storeToRefs(holdings)
  const { t0StatsMap } = storeToRefs(useT0StatsRef())  // 或 store 化
  const aggregate = computed(() => aggregateQuota(holdings.cachedAsset, positions.value, t0StatsMap.value))
  return { aggregate, /* rowQuota 直接调纯函数 */ }
}
```

**Why**: 复用 t0-trade-polish-bundle commit 1 拆 lib/useT0Balance 的模式——纯函数 + reactive wrapper 两层，单测只测纯函数，wrapper 是 thin pass-through。

**Alt considered**:
- 全部塞 T0Trade.vue → 单文件超 250 行硬约束违规
- 直接用 composable 算 reactive → 难测，aggregate() 内部调 store 没法传 mock

### 3. 行内配额列只显示数值，不嵌入按钮

```
... 浮盈%  | 可买 | 可卖 | 操作 ...
  +5.2%   | 800  | 1000 | [买50%][卖50%][配平][详情]
```

- 可买颜色：≥1000 绿 / 100-1000 橙 / <100 红 / =0 灰
- 可卖颜色：同

**Why**: 列只显示数值让 trader 横向对比 quota 余量；按钮保持现状不做颜色绑定（按钮有自己的 disabled 状态逻辑）。鼠标 hover 可买/可卖时显示 tooltip "估算价 ¥12.34 × 100 股"。

**Alt considered**:
- 把 quota 内嵌到按钮文字（"买50% (800 股)"）→ 按钮文字过长，按钮宽度溢出
- 配额列宽 80px → 100px → 实测 80px 够显示 4 位股数，100px 更宽松

### 4. 不实时刷新 quota frame，依赖 holdings store bootstrap 节奏

- cash/avl_vol 已有 holdings store 缓存（cachedAsset / positions）
- 改动订单后 holdings store 自动刷新（ws push + bootstrap）
- quota frame 自动 reactive 重算（computed）

**Why**: 0 额外 RPC，0 额外 store 状态。现有架构已经满足实时性。

**Alt considered**:
- 加 t0QuotaStore → 引入冗余 state，与 holdings 重复
- 加 setInterval 拉 → 多余 RPC 浪费

### 5. quota frame 移动端折叠为 1 行压缩

- 桌面（≥1100px）: 5 个 pill 横排
- 窄屏（<1100px）: 缩为 2 个核心 pill (现金余量 + 今日盈亏)，其它折叠到 popover

**Why**: 移动端主表列已经 8+ 列，再加 quota frame 5 列会爆。trader 移动端主要是看不下单，2 个核心指标够用。

**Alt considered**:
- 完全隐藏 → 移动端 trader 没法看现金余量
- 全部保留 5 列 → 列宽塌陷不可读

## Risks / Trade-offs

- **[Risk] quota frame 增加 ~60 行 T0Trade.vue 模板 → 接近 1000 行** → Mitigation: 拆 `<quota-frame>` 子组件到 `client/src/components/trade/QuotaFrame.vue`（如果 commit 3 实施后 T0Trade.vue 仍超 950 行）

- **[Risk] 可买估算依赖 last_price，quote 未到时显示 0 → trader 误以为没钱** → Mitigation: tooltip "依赖最新价 ¥X，未到时显示 0" + 列灰显 + 0 时按钮 disabled 已在 t0-trade-polish-bundle 覆盖

- **[Risk] 5 个 pill 渲染开销 → 50+ 持仓时主表渲染卡顿** → Mitigation: aggregateQuota 是 O(n) 单次计算，computed 自动 memo；实测 50 持仓 < 5ms

- **[Risk] T+0 可用 = sum(avl_vol) 不准确（broker 端冻结未同步）** → Mitigation: 已有 holdings bootstrap 兜底 day-init reconcile，avl_vol 是 broker 端权威值

- **[Risk] 改动触及 T0Trade.vue 多处（quota frame + 2 列 + composable 接入），单次 PR review 困难** → Mitigation: 拆 3 commit（composable / quota frame / 配额列），单 commit < 200 行 diff

## Migration Plan

无需 migration，纯 additive：
1. 部署后 trader 进 `/t0-trade` 自动看到 quota frame
2. 旧习惯"翻 drawer 看 cash"仍 work（drawer 未改）
3. 回滚：revert 3 commit 即可，无 schema/data 变更

## Open Questions

- quota frame 是否需要"点击 pill 跳到对应详情"（现金 pill → drawer cash tab）？建议后续迭代，本 change 只做展示
- T+0 quota 是否要区分"今日已买" / "今日可卖"（持仓底仓 vs 在途冻结）？建议下个 change，本 change 只 sum(avl_vol)